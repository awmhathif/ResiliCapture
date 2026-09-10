from __future__ import annotations

import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

from .capture import CaptureError, ResilientCapture
from .encoder import EncoderError, finalize_segments, make_segment_encoder
from .effects import LiveFocusController, apply_focus_effect
from .models import RecorderEvent, RecordingOptions, RecordingState
from .session import RecordingSession

try:
    from pynput import mouse as pynput_mouse
except Exception:  # optional until installed on the target PC
    pynput_mouse = None


class RecorderWorker(threading.Thread):
    def __init__(self, options: RecordingOptions, events: "queue.Queue[RecorderEvent]") -> None:
        super().__init__(name="ResiliCaptureWorker", daemon=False)
        self.options = options
        self.events = events
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.screenshot_event = threading.Event()
        self.paused_ack_event = threading.Event()
        self.session: RecordingSession | None = None
        self.output_path: Path | None = None
        self._started_at = 0.0
        self._active_elapsed = 0.0
        self._active_started = 0.0
        self._mouse_listener = None
        self._active_focus_id: str | None = None
        self._active_focus_start = 0.0
        self._focus_controller = LiveFocusController()

    def emit(self, kind: str, **payload: Any) -> None:
        self.events.put(RecorderEvent(kind=kind, payload=payload))

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.pause_event.set()
        else:
            self.pause_event.clear()
            self.paused_ack_event.clear()

    def is_pause_sealed(self) -> bool:
        return self.paused_ack_event.is_set()

    def request_screenshot(self) -> None:
        self.screenshot_event.set()

    def active_elapsed(self) -> float:
        elapsed = self._active_elapsed
        if self._active_started and not self.pause_event.is_set() and not self.stop_event.is_set():
            elapsed += time.perf_counter() - self._active_started
        return elapsed

    def add_focus_marker(
        self,
        region: dict[str, float],
        *,
        zoom: float | None = None,
        duration: float | None = None,
        transition: float | None = None,
        style: str | None = None,
        easing: str | None = None,
        source: str = "manual",
    ) -> dict[str, Any] | None:
        if not self.session:
            return None
        marker = self.session.add_focus_marker(
            start=self.active_elapsed(),
            region=region,
            zoom=zoom if zoom is not None else self.options.focus_zoom,
            duration=duration if duration is not None else self.options.focus_hold,
            transition=transition if transition is not None else self.options.focus_transition,
            style=style or self.options.focus_style,
            easing=easing or self.options.focus_easing,
            source=source,
        )
        self.emit("focus", marker=marker)
        return marker

    def begin_focus_marker(
        self,
        region: dict[str, float],
        *,
        zoom: float | None = None,
        transition: float | None = None,
        style: str | None = None,
        easing: str | None = None,
    ) -> dict[str, Any] | None:
        """Start a live focus span that is baked into recorded frames."""
        if not self.session or not self.options.live_focus_enabled:
            return None
        if self._active_focus_id:
            self.end_focus_marker()
        start = self.active_elapsed()
        chosen_zoom = zoom if zoom is not None else self.options.focus_zoom
        chosen_transition = transition if transition is not None else self.options.focus_transition
        chosen_style = style or self.options.focus_style
        marker = self.session.start_focus_marker(
            start=start,
            region=region,
            zoom=chosen_zoom,
            transition=chosen_transition,
            style=chosen_style,
            easing=easing or self.options.focus_easing,
            source="live",
        )
        self._focus_controller.activate(
            at=start,
            region=region,
            zoom=chosen_zoom,
            transition=chosen_transition,
            style=chosen_style,
        )
        self._active_focus_id = str(marker["id"])
        self._active_focus_start = start
        self.emit("focus_started", marker=marker)
        return marker

    def end_focus_marker(self) -> dict[str, Any] | None:
        if not self.session or not self._active_focus_id:
            return None
        at = self.active_elapsed()
        self._focus_controller.clear(at=at, transition=self.options.focus_transition)
        marker_id = self._active_focus_id
        marker = self.session.finish_focus_marker(marker_id, end_at=at)
        self._active_focus_id = None
        self._active_focus_start = 0.0
        if marker:
            self.emit("focus_ended", marker=marker)
        return marker

    def _seal_active_focus(self) -> None:
        if self._active_focus_id:
            self.end_focus_marker()

    def _start_mouse_tracking(self) -> None:
        if pynput_mouse is None or not self.options.auto_focus_clicks:
            return

        def on_click(x: float, y: float, button: Any, pressed: bool) -> None:
            if not pressed or self.stop_event.is_set() or self.pause_event.is_set() or not self.session:
                return
            region = self.options.region
            rel_x = (float(x) - region["left"]) / max(1, region["width"])
            rel_y = (float(y) - region["top"]) / max(1, region["height"])
            if not (0.0 <= rel_x <= 1.0 and 0.0 <= rel_y <= 1.0):
                return
            at = self.active_elapsed()
            self.session.add_click_marker(at=at, x=rel_x, y=rel_y, button=str(button))
            focus_w = min(0.48, max(0.24, 1.0 / max(1.0, self.options.focus_zoom)))
            focus_h = min(0.42, max(0.20, focus_w * 0.72))
            focus_region = {
                "x": max(0.0, min(rel_x - focus_w / 2, 1.0 - focus_w)),
                "y": max(0.0, min(rel_y - focus_h / 2, 1.0 - focus_h)),
                "width": focus_w,
                "height": focus_h,
            }
            marker = self.session.add_focus_marker(
                start=max(0.0, at - 0.10),
                region=focus_region,
                zoom=self.options.focus_zoom,
                duration=self.options.focus_hold,
                transition=self.options.focus_transition,
                style=self.options.focus_style,
                easing=self.options.focus_easing,
                source="click",
            )
            self.emit("focus", marker=marker)

        try:
            self._mouse_listener = pynput_mouse.Listener(on_click=on_click)
            self._mouse_listener.start()
            self.emit("input_tracking", available=True)
        except Exception as exc:
            self._mouse_listener = None
            self.emit("warning", message=f"Automatic click focus is unavailable: {exc}")

    def _stop_mouse_tracking(self) -> None:
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def _preflight(self) -> None:
        save_dir = Path(self.options.save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        probe = save_dir / ".resilicapture_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        free_mb = shutil.disk_usage(save_dir).free // (1024 * 1024)
        if free_mb < self.options.min_free_mb:
            raise RuntimeError(f"Only {free_mb} MB is free. At least {self.options.min_free_mb} MB is required.")
        if self.options.region["width"] < 16 or self.options.region["height"] < 16:
            raise RuntimeError("The capture area is too small.")

    def _scaled_size(self) -> tuple[int, int]:
        width = max(2, int(self.options.region["width"] * self.options.scale))
        height = max(2, int(self.options.region["height"] * self.options.scale))
        width -= width % 2
        height -= height % 2
        return width, height

    @staticmethod
    def _resize_for_recording(frame, width: int, height: int):
        """Resize only when requested, using an edge-preserving filter for UI text.

        INTER_AREA is excellent for photographs but can make thin glyph strokes
        look soft when a desktop is downscaled. Lanczos retains substantially
        more apparent text detail. Upscaling uses cubic interpolation.
        """
        if frame.shape[1] == width and frame.shape[0] == height:
            return frame
        shrinking = width < frame.shape[1] or height < frame.shape[0]
        interpolation = cv2.INTER_LANCZOS4 if shrinking else cv2.INTER_CUBIC
        return cv2.resize(frame, (width, height), interpolation=interpolation)

    def _output_fps(self) -> float:
        return float(self.options.timelapse_output_fps if self.options.mode == "timelapse" else self.options.fps)

    def _capture_interval(self) -> float:
        return float(self.options.timelapse_interval if self.options.mode == "timelapse" else 1.0 / self.options.fps)

    def _new_output_path(self) -> Path:
        prefix = "timelapse" if self.options.mode == "timelapse" else "recording"
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        candidate = Path(self.options.save_dir) / f"{prefix}_{stamp}.mp4"
        counter = 2
        while candidate.exists():
            candidate = Path(self.options.save_dir) / f"{prefix}_{stamp}_{counter}.mp4"
            counter += 1
        return candidate

    def _segment_duration_target(self) -> float:
        """Choose a crash-safe chunk size that also scales to all-day captures.

        A 5-second real-time chunk is reasonable for ordinary video but becomes
        pathological for timelapse capture where a single frame can arrive every
        10-30 seconds. Timelapse chunks therefore contain roughly ten frames,
        capped at five minutes of real time.
        """
        configured = max(3.0, float(self.options.segment_seconds))
        if self.options.mode == "timelapse":
            return max(configured, min(300.0, self._capture_interval() * 10.0))
        return max(configured, 15.0)

    @staticmethod
    def _current_part_bytes(current_part: Path | None) -> int:
        if current_part is None:
            return 0
        try:
            return current_part.stat().st_size if current_part.exists() else 0
        except OSError:
            return 0

    def run(self) -> None:
        capture: ResilientCapture | None = None
        encoder = None
        segment_index = 0
        segment_frames = 0
        segment_started = 0.0
        current_part: Path | None = None
        width = height = 0
        output_fps = self._output_fps()
        capture_interval = self._capture_interval()
        captured_frames = 0
        written_frames = 0
        dropped_frames = 0
        last_stats = time.perf_counter()
        encoder_fallback_used = False
        software_fallback_used = False
        sealed_bytes = 0
        finalization_headroom_warned = False
        segment_target_seconds = self._segment_duration_target()

        def close_segment(abort: bool = False) -> None:
            nonlocal encoder, segment_frames, segment_started, current_part, sealed_bytes
            if encoder is None or current_part is None:
                return
            ok = False
            try:
                ok = encoder.close(abort=abort)
            finally:
                duration = segment_frames / output_fps if output_fps else 0.0
                if ok and segment_frames > 0 and current_part.exists():
                    completed = current_part.with_name(current_part.name.replace(".part", ""))
                    current_part.replace(completed)
                    assert self.session is not None
                    completed_size = completed.stat().st_size
                    sealed_bytes += completed_size
                    self.session.add_segment(
                        completed,
                        frames=segment_frames,
                        duration=duration,
                        backend=encoder.backend_name,
                        codec=encoder.codec,
                    )
                    self.emit("segment", name=completed.name, frames=segment_frames, duration=duration, bytes=completed_size)
                elif current_part.exists() and current_part.stat().st_size == 0:
                    current_part.unlink(missing_ok=True)
                encoder = None
                current_part = None
                segment_frames = 0
                segment_started = 0.0

        def open_segment(force_opencv: bool = False, force_software: bool = False) -> None:
            nonlocal encoder, segment_index, segment_started, current_part
            segment_index += 1
            if force_opencv:
                from .encoder import OpenCVSegmentEncoder
                encoder = OpenCVSegmentEncoder(width, height, output_fps)
            else:
                requested = "Software H.264" if force_software else self.options.encoder
                encoder = make_segment_encoder(
                    width, height, output_fps, self.options.quality, requested,
                    log_path=(self.session.root / "encoder.log") if self.session else None,
                )
            extension = ".avi" if encoder.backend_name.startswith("OpenCV") else ".mkv"
            assert self.session is not None
            current_part = self.session.root / f"segment_{segment_index:06d}.part{extension}"
            encoder.open(current_part)
            segment_started = time.perf_counter()
            self.emit("encoder", backend=encoder.backend_name, codec=encoder.codec)

        try:
            self.emit("state", state=RecordingState.PREPARING.value, message="Checking capture, storage and encoder…")
            self._preflight()
            self.session = RecordingSession(self.options)
            self.output_path = self._new_output_path()
            self.session.set_state(RecordingState.PREPARING, "Preflight checks passed.")

            width, height = self._scaled_size()
            capture = ResilientCapture(self.options.region, self.options.capture_cursor)
            capture.open()
            open_segment()

            self._started_at = time.perf_counter()
            self._active_started = self._started_at
            self._start_mouse_tracking()
            self.session.set_state(RecordingState.RECORDING, f"Capture backend: {capture.backend_name}")
            self.emit(
                "state",
                state=RecordingState.RECORDING.value,
                message="Recording recoverable segments",
                session_dir=str(self.session.root),
                width=width,
                height=height,
                output_fps=output_fps,
            )

            next_frame = time.perf_counter()
            pause_segment_closed = False

            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    if not pause_segment_closed:
                        self._active_elapsed += max(0.0, time.perf_counter() - self._active_started)
                        self._active_started = 0.0
                        close_segment()
                        pause_segment_closed = True
                        self.session.set_state(RecordingState.PAUSED, "Paused; completed footage is sealed.")
                        self.paused_ack_event.set()
                        self.emit("state", state=RecordingState.PAUSED.value, message="Paused — completed footage is sealed")
                    time.sleep(0.08)
                    next_frame = time.perf_counter()
                    continue

                if pause_segment_closed:
                    self.paused_ack_event.clear()
                    open_segment(force_opencv=encoder_fallback_used, force_software=software_fallback_used)
                    pause_segment_closed = False
                    self._active_started = time.perf_counter()
                    self.session.set_state(RecordingState.RECORDING, "Recording resumed.")
                    self.emit("state", state=RecordingState.RECORDING.value, message="Recording resumed")

                now = time.perf_counter()
                if self.options.max_duration_seconds > 0 and self.active_elapsed() >= self.options.max_duration_seconds:
                    self.emit("warning", message="The recording duration limit was reached. Saving safely…")
                    self.stop_event.set()
                    continue
                if now < next_frame:
                    time.sleep(min(next_frame - now, 0.05))
                    continue

                if now - next_frame > capture_interval * 2:
                    skipped = max(0, int((now - next_frame) / capture_interval) - 1)
                    dropped_frames += skipped
                    next_frame = now

                try:
                    frame = capture.grab()
                except CaptureError as exc:
                    self.session.set_state(RecordingState.RECONNECTING, str(exc))
                    self.emit("state", state=RecordingState.RECONNECTING.value, message="Display interrupted; restoring capture…")
                    try:
                        frame = capture.grab(attempts=8)
                    except CaptureError as final_exc:
                        raise RuntimeError(f"All display capture recovery attempts failed: {final_exc}") from final_exc
                    self.session.set_state(RecordingState.RECORDING, f"Capture restored with {capture.backend_name}.")
                    self.emit("state", state=RecordingState.RECORDING.value, message=f"Capture restored with {capture.backend_name}")

                captured_frames += 1
                frame = self._resize_for_recording(frame, width, height)
                if self.options.live_focus_enabled:
                    frame = apply_focus_effect(frame, self._focus_controller.snapshot(self.active_elapsed()))
                if self.screenshot_event.is_set():
                    self.screenshot_event.clear()
                    shot = Path(self.options.save_dir) / f"screenshot_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
                    if cv2.imwrite(str(shot), frame):
                        self.emit("screenshot", path=str(shot))

                try:
                    assert encoder is not None
                    encoder.write(frame)
                except EncoderError as exc:
                    failed_codec = getattr(encoder, "codec", "") if encoder is not None else ""
                    close_segment(abort=True)
                    if not software_fallback_used and failed_codec != "libx264":
                        software_fallback_used = True
                        self.emit("warning", message="Hardware encoder failed; switched to software H.264.")
                        open_segment(force_software=True)
                    elif not encoder_fallback_used:
                        encoder_fallback_used = True
                        self.emit("warning", message="H.264 encoder failed; switched to recoverable MJPEG segments.")
                        open_segment(force_opencv=True)
                    else:
                        raise RuntimeError(f"Primary and fallback encoders failed: {exc}") from exc
                    assert encoder is not None
                    encoder.write(frame)

                written_frames += 1
                segment_frames += 1
                next_frame += capture_interval

                if segment_started and time.perf_counter() - segment_started >= segment_target_seconds:
                    close_segment()
                    open_segment(force_opencv=encoder_fallback_used, force_software=software_fallback_used)

                if time.perf_counter() - last_stats >= 1.0:
                    free_mb = shutil.disk_usage(self.options.save_dir).free // (1024 * 1024)
                    if free_mb < self.options.min_free_mb:
                        raise RuntimeError(f"Recording stopped safely because free disk space fell below {self.options.min_free_mb} MB.")
                    elapsed = self.active_elapsed()
                    actual_fps = written_frames / elapsed if elapsed > 0 else 0.0
                    bytes_written = sealed_bytes + self._current_part_bytes(current_part)
                    bytes_per_minute = bytes_written / max(elapsed, 1.0) * 60.0
                    free_bytes = free_mb * 1024 * 1024
                    reserve_bytes = self.options.min_free_mb * 1024 * 1024
                    if not finalization_headroom_warned and bytes_written > 0 and free_bytes < int(bytes_written * 1.15) + reserve_bytes:
                        finalization_headroom_warned = True
                        self.emit(
                            "warning",
                            message="Disk space is getting tight for finalization. ResiliCapture will keep recording while the safety reserve remains available, but freeing space before Stop is recommended.",
                        )
                    self.session.update_stats(
                        captured_frames=captured_frames,
                        written_frames=written_frames,
                        dropped_frames=dropped_frames,
                        capture_retries=capture.total_retries,
                        active_seconds=round(elapsed, 2),
                        free_mb=free_mb,
                        bytes_written=bytes_written,
                    )
                    self.emit(
                        "stats",
                        elapsed=elapsed,
                        actual_fps=actual_fps,
                        dropped=dropped_frames,
                        retries=capture.total_retries,
                        free_mb=free_mb,
                        backend=capture.backend_name,
                        bytes_written=bytes_written,
                        bytes_per_minute=bytes_per_minute,
                        focus_count=len(self.session.manifest.get("focus_markers", [])),
                    )
                    last_stats = time.perf_counter()

            self._seal_active_focus()
            self.emit("state", state=RecordingState.STOPPING.value, message="Sealing the active recording segment…")
            self.session.set_state(RecordingState.STOPPING, "Stop requested.")
            if self._active_started:
                self._active_elapsed += max(0.0, time.perf_counter() - self._active_started)
                self._active_started = 0.0
            close_segment()

            self.session.set_state(RecordingState.FINALIZING, "Combining and verifying completed segments.")
            self.session.update_finalization(
                stage="preparing", percent=0.0, message="Preparing the final video…", output=str(self.output_path), force=True
            )
            self.emit("state", state=RecordingState.FINALIZING.value, message="Preparing the final video…")

            def on_finalize_progress(stage: str, percent: float, message: str) -> None:
                assert self.session is not None
                self.session.update_finalization(
                    stage=stage, percent=percent, message=message, output=str(self.output_path)
                )
                self.emit("finalize_progress", stage=stage, percent=percent, message=message, path=str(self.output_path))

            final_path = finalize_segments(
                self.session.root, self.output_path, output_fps,
                progress_callback=on_finalize_progress,
                min_free_bytes=self.options.min_free_mb * 1024 * 1024,
            )
            self.session.update_stats(
                captured_frames=captured_frames,
                written_frames=written_frames,
                dropped_frames=dropped_frames,
                capture_retries=capture.total_retries if capture else 0,
                active_seconds=round(self._active_elapsed, 2),
                bytes_written=sealed_bytes + self._current_part_bytes(current_part),
                force=True,
            )
            self.session.complete(final_path)

            if not self.options.keep_session_segments:
                for path in self.session.root.glob("segment_*.*"):
                    path.unlink(missing_ok=True)

            self.emit(
                "completed",
                path=str(final_path),
                session_dir=str(self.session.root),
                elapsed=self._active_elapsed,
                dropped=dropped_frames,
                focus_count=len(self.session.manifest.get("focus_markers", [])),
                width=width,
                height=height,
                quality=self.options.quality,
                encoder=getattr(encoder, "codec", "") if encoder is not None else "",
            )
        except Exception as exc:
            try:
                self._seal_active_focus()
            except Exception:
                pass
            try:
                close_segment(abort=False)
            except Exception:
                pass
            if self.session:
                self.session.fail(str(exc))
                session_dir = str(self.session.root)
            else:
                session_dir = None
            self.emit(
                "failed",
                error=str(exc),
                session_dir=session_dir,
                recoverable=bool(self.session and self.session.segment_count > 0),
            )
        finally:
            self.paused_ack_event.clear()
            self._stop_mouse_tracking()
            if capture:
                capture.close()
            try:
                if encoder is not None:
                    encoder.close(abort=True)
            except Exception:
                pass
