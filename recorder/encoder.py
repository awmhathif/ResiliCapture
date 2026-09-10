from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Callable

import cv2
import numpy as np

from .session import load_segment_records
from .utils import find_binary, run_hidden


class EncoderError(RuntimeError):
    pass


@dataclass(slots=True)
class EncoderChoice:
    label: str
    ffmpeg_name: str


ENCODER_PRIORITY = [
    EncoderChoice("NVIDIA NVENC", "h264_nvenc"),
    EncoderChoice("Intel Quick Sync", "h264_qsv"),
    EncoderChoice("AMD AMF", "h264_amf"),
    EncoderChoice("Software H.264", "libx264"),
]

ProgressCallback = Callable[[str, float, str], None]


@lru_cache(maxsize=1)
def available_encoders() -> tuple[EncoderChoice, ...]:
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        return ()
    result = run_hidden([ffmpeg, "-hide_banner", "-encoders"], timeout=10)
    text = f"{result.stdout}\n{result.stderr}"
    return tuple(item for item in ENCODER_PRIORITY if item.ffmpeg_name in text)


@lru_cache(maxsize=None)
def encoder_works(codec: str) -> bool:
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        return False
    result = run_hidden(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1",
            "-frames:v", "1", "-c:v", codec, "-f", "null", "-",
        ],
        timeout=15,
    )
    return result.returncode == 0


def choose_encoder(requested: str) -> EncoderChoice | None:
    encoders = available_encoders()
    if not encoders:
        return None
    if requested == "Auto":
        for item in encoders:
            if encoder_works(item.ffmpeg_name):
                return item
        return None
    for item in encoders:
        if requested in {item.label, item.ffmpeg_name} and encoder_works(item.ffmpeg_name):
            return item
    # An explicitly selected hardware encoder may be compiled into FFmpeg but
    # unavailable on this PC. Fall back to verified software H.264 first.
    for item in encoders:
        if item.ffmpeg_name == "libx264" and encoder_works(item.ffmpeg_name):
            return item
    return None


# Screen recordings contain high-contrast one-pixel edges and small text.  The
# old camera-video oriented CQ/CRF values (Balanced=23, Quality=19) visibly
# softened desktop text, especially after player scaling.  These values favor
# legibility while remaining real-time friendly on normal PCs.
QUALITY_VALUES = {
    "Performance": 23,
    "Balanced": 18,
    "Quality": 15,
    "Near lossless": 10,
}


def _quality_args(codec: str, quality: str) -> list[str]:
    quality_value = QUALITY_VALUES.get(quality, QUALITY_VALUES["Quality"])
    if codec == "libx264":
        preset = {
            "Performance": "veryfast",
            "Balanced": "faster",
            "Quality": "fast",
            "Near lossless": "fast",
        }.get(quality, "fast")
        return ["-preset", preset, "-crf", str(quality_value)]
    if codec == "h264_nvenc":
        preset = {
            "Performance": "p3",
            "Balanced": "p5",
            "Quality": "p6",
            "Near lossless": "p6",
        }.get(quality, "p6")
        return ["-preset", preset, "-tune", "hq", "-rc", "vbr", "-cq", str(quality_value), "-b:v", "0"]
    if codec == "h264_qsv":
        preset = "veryfast" if quality == "Performance" else "medium"
        return ["-preset", preset, "-global_quality", str(quality_value)]
    if codec == "h264_amf":
        amf_quality = "speed" if quality == "Performance" else "quality"
        return ["-quality", amf_quality, "-qp_i", str(quality_value), "-qp_p", str(quality_value)]
    return []


class FFmpegSegmentEncoder:
    backend_name = "FFmpeg"

    def __init__(
        self,
        width: int,
        height: int,
        fps: float,
        quality: str,
        requested_encoder: str,
        log_path: Path | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        self.ffmpeg = find_binary("ffmpeg")
        self.choice = choose_encoder(requested_encoder)
        if not self.ffmpeg or not self.choice:
            raise EncoderError("FFmpeg with a supported H.264 encoder was not found.")
        self.codec = self.choice.ffmpeg_name
        self.process: subprocess.Popen[bytes] | None = None
        self.stderr_file: BinaryIO | None = None
        self.path: Path | None = None
        self.log_path = log_path

    def open(self, part_path: Path) -> None:
        self.close(abort=True)
        self.path = part_path
        # One append-only encoder log per session prevents thousands of tiny
        # log files from accumulating during all-day recordings.
        stderr_path = self.log_path or (part_path.parent / "encoder.log")
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_file = open(stderr_path, "ab")
        self.stderr_file.write(f"\n--- {part_path.name} | codec={self.codec} ---\n".encode("utf-8"))
        self.stderr_file.flush()
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            f"{self.fps:g}",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            self.codec,
            *_quality_args(self.codec, self.quality),
            "-pix_fmt",
            "yuv420p",
            "-f",
            "matroska",
            str(part_path),
        ]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.stderr_file,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

    def write(self, frame: np.ndarray) -> None:
        if self.process is None or self.process.stdin is None:
            raise EncoderError("Encoder is not open.")
        if self.process.poll() is not None:
            raise EncoderError(f"FFmpeg exited unexpectedly with code {self.process.returncode}.")
        try:
            self.process.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError) as exc:
            raise EncoderError(f"FFmpeg stopped accepting video frames: {exc}") from exc

    def close(self, abort: bool = False) -> bool:
        if self.process is None:
            return True
        process = self.process
        self.process = None
        try:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if abort:
                process.terminate()
            try:
                return_code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=5)
            return return_code == 0 and not abort
        finally:
            if self.stderr_file:
                self.stderr_file.close()
                self.stderr_file = None


class OpenCVSegmentEncoder:
    backend_name = "OpenCV MJPEG fallback"
    codec = "MJPG"

    def __init__(self, width: int, height: int, fps: float) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.writer: cv2.VideoWriter | None = None

    def open(self, part_path: Path) -> None:
        self.close()
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self.writer = cv2.VideoWriter(str(part_path), fourcc, self.fps, (self.width, self.height))
        if not self.writer.isOpened():
            self.writer.release()
            self.writer = None
            raise EncoderError(f"OpenCV could not create {part_path}")

    def write(self, frame: np.ndarray) -> None:
        if self.writer is None:
            raise EncoderError("OpenCV encoder is not open.")
        self.writer.write(frame)

    def close(self, abort: bool = False) -> bool:
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        return not abort


def make_segment_encoder(
    width: int,
    height: int,
    fps: float,
    quality: str,
    requested: str,
    log_path: Path | None = None,
):
    try:
        return FFmpegSegmentEncoder(width, height, fps, quality, requested, log_path=log_path)
    except EncoderError:
        return OpenCVSegmentEncoder(width, height, fps)


def verify_media(path: Path, *, decode_check: bool = False) -> tuple[bool, str]:
    if not path.exists() or path.stat().st_size < 1024:
        return False, "File is missing or too small."
    ffprobe = find_binary("ffprobe")
    if not ffprobe:
        return True, "FFprobe unavailable; basic size check passed."
    result = run_hidden(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height:format=duration",
            "-of", "default=nw=1", str(path),
        ],
        timeout=20,
    )
    if result.returncode != 0 or "codec_name=" not in result.stdout:
        return False, result.stderr.strip() or "No readable video stream found."

    if decode_check:
        ffmpeg = find_binary("ffmpeg")
        if ffmpeg:
            duration = 0.0
            for line in result.stdout.splitlines():
                if line.startswith("duration="):
                    try:
                        duration = float(line.split("=", 1)[1])
                    except ValueError:
                        duration = 0.0
                    break
            checks = [0.0]
            if duration > 4.0:
                checks.append(max(0.0, duration - 2.0))
            for seek in checks:
                command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
                if seek > 0:
                    command += ["-ss", f"{seek:.3f}"]
                command += ["-i", str(path), "-frames:v", "1", "-f", "null", "-"]
                decoded = run_hidden(command, timeout=30)
                if decoded.returncode != 0:
                    where = "near the end" if seek > 0 else "at the beginning"
                    return False, decoded.stderr.strip() or f"Could not decode a frame {where} of the final video."
    return True, result.stdout.strip()


def _write_concat_file(path: Path, segments: list[Path]) -> None:
    lines = []
    for segment in segments:
        escaped = str(segment.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    path.write_text("\n".join(lines), encoding="utf-8")


def _manifest_segment_info(session_dir: Path) -> dict[str, dict]:
    return {str(item["name"]): item for item in load_segment_records(session_dir) if item.get("name")}


def _check_finalization_space(
    session_dir: Path,
    output_path: Path,
    segments: list[Path],
    *,
    min_free_bytes: int,
    requires_normalization: bool,
) -> None:
    """Fail before muxing when the output drive clearly lacks safe headroom.

    The original sealed segments are intentionally retained until verification,
    so finalization temporarily needs space for another copy of the recording.
    Mixed MJPEG/H.264 sessions also need normalization workspace.
    """
    source_bytes = sum(path.stat().st_size for path in segments if path.exists())
    reserve = max(0, int(min_free_bytes))
    output_need = int(source_bytes * 1.08) + reserve
    try:
        output_free = shutil.disk_usage(output_path.parent).free
    except OSError:
        return
    if output_free < output_need:
        need_mb = output_need // (1024 * 1024)
        free_mb = output_free // (1024 * 1024)
        raise EncoderError(
            f"Not enough free space to safely create the final video. "
            f"Approximately {need_mb:,} MB is needed but only {free_mb:,} MB is free. "
            "The sealed recording segments were kept and can be finalized after freeing disk space."
        )

    if requires_normalization:
        try:
            session_free = shutil.disk_usage(session_dir).free
        except OSError:
            return
        # Normalization is H.264 and is usually much smaller than emergency
        # MJPEG input; 60% of source size plus the reserve is a conservative
        # early-warning threshold without requiring 2x the entire session.
        workspace_need = int(source_bytes * 0.60) + reserve
        if session_free < workspace_need:
            need_mb = workspace_need // (1024 * 1024)
            free_mb = session_free // (1024 * 1024)
            raise EncoderError(
                f"Not enough free space for mixed-encoder recovery. "
                f"Approximately {need_mb:,} MB of workspace is needed but only {free_mb:,} MB is free. "
                "The original sealed segments were not deleted."
            )


def _emit_progress(callback: ProgressCallback | None, stage: str, percent: float, message: str) -> None:
    if callback is not None:
        callback(stage, max(0.0, min(100.0, float(percent))), message)


def _run_ffmpeg_with_progress(
    command: list[str],
    *,
    total_duration: float,
    callback: ProgressCallback | None,
    stage: str,
    start_percent: float,
    end_percent: float,
) -> tuple[int, str]:
    """Run FFmpeg and stream machine-readable progress without blocking the UI thread."""
    full_command = [command[0], "-progress", "pipe:1", "-nostats", *command[1:]]
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        full_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    assert process.stdout is not None
    last_percent = start_percent
    for raw in process.stdout:
        line = raw.strip()
        if not line.startswith("out_time_"):
            continue
        key, _, value = line.partition("=")
        seconds = 0.0
        try:
            if key == "out_time_us":
                seconds = float(value) / 1_000_000.0
            elif key == "out_time_ms":
                # FFmpeg historically labels microseconds as out_time_ms.
                seconds = float(value) / 1_000_000.0
            else:
                continue
        except ValueError:
            continue
        ratio = min(1.0, seconds / max(total_duration, 0.001))
        percent = start_percent + (end_percent - start_percent) * ratio
        if percent >= last_percent + 0.25:
            _emit_progress(callback, stage, percent, f"Combining video… {percent:.0f}%")
            last_percent = percent
    stderr = process.stderr.read() if process.stderr is not None else ""
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    return_code = process.wait()
    return return_code, stderr


def _normalize_segments(
    ffmpeg: str,
    session_dir: Path,
    segments: list[Path],
    fps: float,
    callback: ProgressCallback | None,
) -> list[Path]:
    normalized_dir = session_dir / "normalized"
    normalized_dir.mkdir(exist_ok=True)
    normalized_segments: list[Path] = []
    total = len(segments)
    for index, segment in enumerate(segments, start=1):
        percent = 10.0 + (index - 1) / max(total, 1) * 55.0
        _emit_progress(callback, "normalizing", percent, f"Preparing segment {index:,} of {total:,}…")
        normalized = normalized_dir / f"normalized_{index:06d}.mkv"
        result = run_hidden(
            [
                ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                "-i", str(segment), "-an", "-vf", f"fps={fps:g},format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-crf", "15",
                "-f", "matroska", str(normalized),
            ],
            timeout=None,
        )
        if result.returncode != 0 or not normalized.exists() or normalized.stat().st_size < 1024:
            raise EncoderError(result.stderr.strip() or f"Could not normalize {segment.name}.")
        normalized_segments.append(normalized)
    return normalized_segments


def finalize_segments(
    session_dir: Path,
    output_path: Path,
    fps: float,
    progress_callback: ProgressCallback | None = None,
    *,
    min_free_bytes: int = 0,
) -> Path:
    """Finalize sealed segments with a fast path for normal H.264 MKV sessions.

    Completed segments were already sealed by the recorder before being listed in
    the session manifest. The normal path therefore performs cheap existence/size
    checks and probes only the final output, avoiding thousands of FFprobe process
    launches on long timelapses. Expensive normalization is reserved for mixed
    AVI/MJPEG fallback sessions.
    """
    _emit_progress(progress_callback, "preparing", 2.0, "Reading completed recording segments…")
    candidates = sorted(
        [*session_dir.glob("segment_*.mkv"), *session_dir.glob("segment_*.avi")],
        key=lambda p: p.name,
    )
    segments = [path for path in candidates if path.exists() and path.stat().st_size >= 1024]
    if not segments:
        raise EncoderError("No completed recording segments were found.")

    metadata = _manifest_segment_info(session_dir)
    requires_normalization = any(path.suffix.lower() != ".mkv" for path in segments)
    _check_finalization_space(
        session_dir, output_path, segments,
        min_free_bytes=min_free_bytes,
        requires_normalization=requires_normalization,
    )
    total_duration = sum(float(metadata.get(path.name, {}).get("duration", 0.0) or 0.0) for path in segments)
    if total_duration <= 0:
        total_duration = max(1.0, len(segments) / max(fps, 1.0))

    _emit_progress(progress_callback, "preparing", 7.0, f"Preparing {len(segments):,} sealed segment{'s' if len(segments) != 1 else ''}…")
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg:
        # AVI means the emergency OpenCV/MJPEG fallback was used. Normalize only
        # in that exceptional case; all-H.264 MKV sessions go straight to concat.
        concat_segments = segments
        if requires_normalization:
            concat_segments = _normalize_segments(ffmpeg, session_dir, segments, fps, progress_callback)
            total_duration = sum(float(metadata.get(path.name, {}).get("duration", 0.0) or 0.0) for path in segments) or total_duration

        concat_file = session_dir / "concat.txt"
        _write_concat_file(concat_file, concat_segments)
        temp_output = output_path.with_suffix(".finalizing.mp4")
        temp_output.unlink(missing_ok=True)

        combine_start = 68.0 if requires_normalization else 12.0
        _emit_progress(progress_callback, "combining", combine_start, "Combining sealed segments…")
        copy_command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", "-movflags", "+faststart", str(temp_output),
        ]
        copy_code, copy_stderr = _run_ffmpeg_with_progress(
            copy_command,
            total_duration=total_duration,
            callback=progress_callback,
            stage="combining",
            start_percent=combine_start,
            end_percent=88.0,
        )

        valid = False
        details = ""
        if copy_code == 0:
            _emit_progress(progress_callback, "verifying", 91.0, "Verifying final video…")
            valid, details = verify_media(temp_output, decode_check=True)

        if copy_code != 0 or not valid:
            # Stream copy should succeed for ordinary H.264 MKV segments. If it
            # does not, perform a single final transcode before considering the
            # much slower per-segment normalization fallback.
            temp_output.unlink(missing_ok=True)
            _emit_progress(progress_callback, "transcoding", combine_start, "Fast combine was not compatible; rebuilding video…")
            transcode_command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c:v", "libx264", "-preset", "fast", "-crf", "15",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp_output),
            ]
            transcode_code, transcode_stderr = _run_ffmpeg_with_progress(
                transcode_command,
                total_duration=total_duration,
                callback=progress_callback,
                stage="transcoding",
                start_percent=combine_start,
                end_percent=88.0,
            )
            if transcode_code != 0:
                error = transcode_stderr.strip() or copy_stderr.strip() or "FFmpeg could not finalize the recording."
                raise EncoderError(error)
            _emit_progress(progress_callback, "verifying", 92.0, "Verifying rebuilt video…")
            valid, details = verify_media(temp_output, decode_check=True)

        if not valid:
            raise EncoderError(f"Final video verification failed: {details}")
        _emit_progress(progress_callback, "saving", 97.0, "Saving verified MP4…")
        os.replace(temp_output, output_path)
        try:
            (session_dir / "concat.txt").unlink(missing_ok=True)
            shutil.rmtree(session_dir / "normalized", ignore_errors=True)
        except OSError:
            pass
        _emit_progress(progress_callback, "complete", 100.0, "Saved and verified")
        return output_path

    # FFmpeg-free fallback: combine completed AVI segments into one AVI.
    if any(path.suffix.lower() != ".avi" for path in segments):
        raise EncoderError("FFmpeg is required to combine MKV recording segments.")
    capture = cv2.VideoCapture(str(segments[0]))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    avi_output = output_path.with_suffix(".avi")
    temp_output = avi_output.with_suffix(".finalizing.avi")
    writer = cv2.VideoWriter(str(temp_output), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        raise EncoderError("Could not create the final AVI file.")
    try:
        total = len(segments)
        for index, segment in enumerate(segments, start=1):
            _emit_progress(progress_callback, "combining", 10 + (index - 1) / max(total, 1) * 85, f"Combining segment {index:,} of {total:,}…")
            cap = cv2.VideoCapture(str(segment))
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    writer.write(frame)
            finally:
                cap.release()
    finally:
        writer.release()
    os.replace(temp_output, avi_output)
    _emit_progress(progress_callback, "complete", 100.0, "Saved recording")
    return avi_output
