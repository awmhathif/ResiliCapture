from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import ImageGrab

try:
    import mss
except ImportError:  # handled by preflight
    mss = None  # type: ignore[assignment]


class CaptureError(RuntimeError):
    pass


def _overlay_windows_cursor(frame: np.ndarray, region: dict[str, int]) -> np.ndarray:
    """Draw a lightweight cursor reconstruction on Windows captures.

    MSS does not expose its cursor option on Windows. This keeps the user-facing
    cursor toggle functional without mutating MSS's read-only ``with_cursor``
    property. The arrow is intentionally simple and high-contrast.
    """
    if os.name != "nt" or frame.size == 0:
        return frame
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        point = POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return frame
        x = int(point.x) - int(region["left"])
        y = int(point.y) - int(region["top"])
        height, width = frame.shape[:2]
        if not (0 <= x < width and 0 <= y < height):
            return frame
        size = max(12, min(24, int(min(width, height) * 0.022)))
        points = np.array(
            [
                [x, y],
                [x + int(size * 0.30), y + size],
                [x + int(size * 0.48), y + int(size * 0.65)],
                [x + int(size * 0.78), y + int(size * 0.96)],
                [x + int(size * 0.96), y + int(size * 0.80)],
                [x + int(size * 0.66), y + int(size * 0.52)],
                [x + size, y + int(size * 0.36)],
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(frame, [points], (20, 20, 20), lineType=cv2.LINE_AA)
        inner = points.copy()
        inner[:, 0] = x + ((inner[:, 0] - x) * 0.78).astype(np.int32)
        inner[:, 1] = y + ((inner[:, 1] - y) * 0.78).astype(np.int32)
        cv2.fillPoly(frame, [inner], (245, 245, 245), lineType=cv2.LINE_AA)
    except Exception:
        return frame
    return frame


@dataclass(slots=True)
class MonitorInfo:
    index: int
    left: int
    top: int
    width: int
    height: int

    @property
    def label(self) -> str:
        prefix = "All monitors" if self.index == 0 else f"Monitor {self.index}"
        return f"{prefix} — {self.width}×{self.height} ({self.left}, {self.top})"

    def as_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def _new_mss(*, capture_cursor: bool = False) -> Any:
    if mss is None:
        raise CaptureError("The 'mss' package is not installed.")
    constructor = getattr(mss, "MSS", None) or getattr(mss, "mss", None)
    if constructor is None:
        raise CaptureError("This MSS installation does not expose a supported constructor.")

    # MSS exposes ``with_cursor`` as a read-only property. It must be supplied
    # when constructing MSS, and the feature is currently supported only by
    # the GNU/Linux backend. Assigning ``sct.with_cursor = ...`` raises
    # ``AttributeError: property 'with_cursor' ... has no setter`` on Windows.
    kwargs: dict[str, Any] = {}
    if sys.platform.startswith("linux"):
        kwargs["with_cursor"] = bool(capture_cursor)

    try:
        return constructor(**kwargs)
    except TypeError:
        # Compatibility with older MSS releases that do not accept keywords.
        return constructor()


def list_monitors() -> list[MonitorInfo]:
    sct = _new_mss()
    try:
        result: list[MonitorInfo] = []
        for index, monitor in enumerate(sct.monitors):
            result.append(
                MonitorInfo(
                    index=index,
                    left=int(monitor["left"]),
                    top=int(monitor["top"]),
                    width=int(monitor["width"]),
                    height=int(monitor["height"]),
                )
            )
        return result
    finally:
        close = getattr(sct, "close", None)
        if callable(close):
            close()


class MSSBackend:
    name = "MSS"

    def __init__(self, region: dict[str, int], capture_cursor: bool) -> None:
        self.region = dict(region)
        self.capture_cursor = capture_cursor
        self.sct: Any | None = None

    def open(self) -> None:
        self.close()
        self.sct = _new_mss(capture_cursor=self.capture_cursor)

    def grab(self) -> np.ndarray:
        if self.sct is None:
            self.open()
        try:
            image = np.asarray(self.sct.grab(self.region))
            if image.ndim != 3 or image.shape[2] < 3:
                raise CaptureError(f"MSS returned an unexpected frame shape: {image.shape}")
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        except Exception as exc:
            raise CaptureError(f"MSS capture failed: {exc}") from exc

    def close(self) -> None:
        if self.sct is not None:
            try:
                close = getattr(self.sct, "close", None)
                if callable(close):
                    close()
            finally:
                self.sct = None


class PILBackend:
    name = "Pillow fallback"

    def __init__(self, region: dict[str, int], capture_cursor: bool) -> None:
        self.region = dict(region)
        self.capture_cursor = capture_cursor

    def open(self) -> None:
        return

    def grab(self) -> np.ndarray:
        left = self.region["left"]
        top = self.region["top"]
        right = left + self.region["width"]
        bottom = top + self.region["height"]
        try:
            image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
            rgb = np.asarray(image)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception as exc:
            raise CaptureError(f"Pillow capture failed: {exc}") from exc

    def close(self) -> None:
        return


class ResilientCapture:
    """MSS capture with reopen/retry and a Pillow emergency fallback."""

    def __init__(self, region: dict[str, int], capture_cursor: bool) -> None:
        self.region = region
        self.capture_cursor = capture_cursor
        self.backends = [MSSBackend(region, capture_cursor), PILBackend(region, capture_cursor)]
        self.backend_index = 0
        self.backend = self.backends[0]
        self.consecutive_failures = 0
        self.total_retries = 0

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def open(self) -> None:
        self.backend.open()

    def grab(self, attempts: int = 4) -> np.ndarray:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                frame = self.backend.grab()
                if self.capture_cursor and not sys.platform.startswith("linux"):
                    frame = _overlay_windows_cursor(frame, self.region)
                self.consecutive_failures = 0
                return frame
            except Exception as exc:
                last_error = exc
                self.consecutive_failures += 1
                self.total_retries += 1
                self.backend.close()
                time.sleep(min(0.15 * (attempt + 1), 0.75))
                try:
                    self.backend.open()
                except Exception:
                    pass

        if self.backend_index + 1 < len(self.backends):
            self.backend.close()
            self.backend_index += 1
            self.backend = self.backends[self.backend_index]
            try:
                self.backend.open()
                frame = self.backend.grab()
                if self.capture_cursor and not sys.platform.startswith("linux"):
                    frame = _overlay_windows_cursor(frame, self.region)
                self.consecutive_failures = 0
                return frame
            except Exception as exc:
                last_error = exc

        raise CaptureError(str(last_error or "All screen capture backends failed."))

    def close(self) -> None:
        for backend in self.backends:
            backend.close()
