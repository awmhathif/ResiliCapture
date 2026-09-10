from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from ctypes import wintypes


@dataclass(slots=True)
class WindowInfo:
    handle: int
    title: str
    left: int
    top: int
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.title} — {self.width}×{self.height}"

    def as_region(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def list_visible_windows() -> list[WindowInfo]:
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    results: list[WindowInfo] = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @EnumWindowsProc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 160 or height < 100:
            return True
        if title in {"Program Manager", "Windows Input Experience"}:
            return True
        results.append(
            WindowInfo(
                handle=int(hwnd),
                title=title,
                left=int(rect.left),
                top=int(rect.top),
                width=width,
                height=height,
            )
        )
        return True

    user32.EnumWindows(callback, 0)
    results.sort(key=lambda item: item.title.casefold())
    return results


def exclude_window_from_capture(hwnd: int) -> bool:
    """Best-effort exclusion of a top-level window from screen capture.

    Windows 10 version 2004 and newer support WDA_EXCLUDEFROMCAPTURE. On
    older systems the API may fail or behave like WDA_MONITOR, so callers
    should treat False as a capability limitation rather than a fatal error.
    """
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        GA_ROOT = 2
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        root_hwnd = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or wintypes.HWND(hwnd)
        return bool(user32.SetWindowDisplayAffinity(root_hwnd, WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False
