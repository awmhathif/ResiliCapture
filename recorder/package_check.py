"""Opt-in executable smoke check; uses synthetic frames and temporary files only."""
from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path


def run_package_check(report: Path, *, require_ffmpeg: bool = False) -> int:
    result: dict = {"ok": False, "checks": []}
    try:
        import cv2
        import numpy as np
        import tkinter as tk
        from PIL import Image
        from .config import APP_VERSION
        from .encoder import FFmpegSegmentEncoder, finalize_segments, verify_media
        from .utils import find_binary, resource_path

        result["version"] = APP_VERSION
        with Image.open(resource_path("assets/app.ico")) as icon:
            icon.load()
        root = tk.Tk()
        try:
            root.withdraw()
            root.iconbitmap(str(resource_path("assets/app.ico")))
            root.update_idletasks()
        finally:
            root.destroy()
        result["checks"].extend(["icon", "tk-runtime"])
        with tempfile.TemporaryDirectory(prefix="ResiliCapture-check-") as tmp:
            folder = Path(tmp)
            avi = folder / "fallback.avi"
            writer = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 90))
            try:
                if not writer.isOpened():
                    raise RuntimeError("Packaged MJPEG encoder could not open")
                for index in range(12):
                    writer.write(np.full((90, 160, 3), 40 + index * 10, dtype=np.uint8))
            finally:
                writer.release()
            capture = cv2.VideoCapture(str(avi))
            try:
                success, frame = capture.read()
                if not success or frame.shape[:2] != (90, 160):
                    raise RuntimeError("Packaged MJPEG decoder could not read its output")
            finally:
                capture.release()
            result["checks"].append("mjpeg-encode-decode")
            result["ffmpeg_available"] = bool(find_binary("ffmpeg") and find_binary("ffprobe"))
            if require_ffmpeg or result["ffmpeg_available"]:
                if not result["ffmpeg_available"]:
                    raise RuntimeError("FFmpeg and FFprobe are required for this check")
                part = folder / "segment_000001.part.mkv"
                encoder = FFmpegSegmentEncoder(160, 90, 10, "Performance", "Software H.264")
                encoder.open(part)
                try:
                    for index in range(12):
                        encoder.write(np.full((90, 160, 3), 40 + index * 10, dtype=np.uint8))
                except Exception:
                    encoder.close(abort=True)
                    raise
                if not encoder.close():
                    raise RuntimeError("Packaged H.264 encoder failed")
                part.replace(folder / "segment_000001.mkv")
                output = finalize_segments(folder, folder / "check.mp4", 10)
                valid, details = verify_media(output, decode_check=True)
                if not valid:
                    raise RuntimeError(details)
                result["checks"].append("h264-finalize-verify-decode")
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
