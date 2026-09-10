from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

import cv2
import numpy
from PIL import __version__ as pillow_version

from recorder.capture import list_monitors
from recorder.encoder import available_encoders
from recorder.utils import find_binary


def main() -> int:
    print("ResiliCapture diagnostics")
    print("=" * 36)
    print("Platform:", platform.platform())
    print("Python:", sys.version.replace("\n", " "))
    print("OpenCV:", cv2.__version__)
    print("NumPy:", numpy.__version__)
    print("Pillow:", pillow_version)
    print("FFmpeg:", find_binary("ffmpeg") or "not found")
    print("FFprobe:", find_binary("ffprobe") or "not found")
    print("Encoders:", ", ".join(item.label for item in available_encoders()) or "OpenCV fallback")
    try:
        monitors = list_monitors()
        for monitor in monitors:
            print("Monitor:", monitor.label)
    except Exception as exc:
        print("Monitor detection ERROR:", exc)
    free = shutil.disk_usage(Path.home()).free / (1024 ** 3)
    print(f"Home drive free: {free:.1f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
