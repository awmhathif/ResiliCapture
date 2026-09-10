from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from PIL import ImageGrab, ImageTk


@dataclass(slots=True)
class SelectionResult:
    left: int
    top: int
    width: int
    height: int

    def as_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


class SelectionOverlay:
    """Frozen-screen drag selector used for capture areas and focus markers."""

    def __init__(
        self,
        root: tk.Misc,
        bounds: dict[str, int],
        *,
        title: str,
        on_done: Callable[[SelectionResult | None], None],
        minimum_size: int = 24,
    ) -> None:
        self.bounds = dict(bounds)
        self.on_done = on_done
        self.minimum_size = minimum_size
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.photo = None

        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        geometry = f"{bounds['width']}x{bounds['height']}{bounds['left']:+d}{bounds['top']:+d}"
        self.window.geometry(geometry)
        self.window.configure(bg="#111111")
        self.window.focus_force()

        self.canvas = tk.Canvas(self.window, highlightthickness=0, cursor="cross", bg="#111111")
        self.canvas.pack(fill="both", expand=True)
        try:
            image = ImageGrab.grab(
                bbox=(
                    bounds["left"],
                    bounds["top"],
                    bounds["left"] + bounds["width"],
                    bounds["top"] + bounds["height"],
                ),
                all_screens=True,
            )
            self.photo = ImageTk.PhotoImage(image)
            self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        except Exception:
            pass

        self.canvas.create_rectangle(0, 0, bounds["width"], bounds["height"], fill="#111111", stipple="gray50", outline="")
        self.canvas.create_text(
            bounds["width"] // 2,
            44,
            text=title,
            fill="white",
            font=("Segoe UI Semibold", 14),
        )
        self.canvas.create_text(
            bounds["width"] // 2,
            72,
            text="Drag to select  •  Esc to cancel",
            fill="#d6d6d6",
            font=("Segoe UI", 10),
        )

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.window.bind("<Escape>", lambda _e: self._finish(None))

    def _press(self, event: tk.Event) -> None:
        self.start_x = int(event.x)
        self.start_y = int(event.y)
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline="white",
            width=2,
            fill="#ffffff",
            stipple="gray25",
        )

    def _drag(self, event: tk.Event) -> None:
        if self.rect_id is None:
            return
        x = max(0, min(int(event.x), self.bounds["width"]))
        y = max(0, min(int(event.y), self.bounds["height"]))
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, x, y)

    def _release(self, event: tk.Event) -> None:
        x1 = min(self.start_x, int(event.x))
        y1 = min(self.start_y, int(event.y))
        x2 = max(self.start_x, int(event.x))
        y2 = max(self.start_y, int(event.y))
        x1 = max(0, min(x1, self.bounds["width"]))
        y1 = max(0, min(y1, self.bounds["height"]))
        x2 = max(0, min(x2, self.bounds["width"]))
        y2 = max(0, min(y2, self.bounds["height"]))
        width = x2 - x1
        height = y2 - y1
        if width < self.minimum_size or height < self.minimum_size:
            return
        self._finish(
            SelectionResult(
                left=self.bounds["left"] + x1,
                top=self.bounds["top"] + y1,
                width=width,
                height=height,
            )
        )

    def _finish(self, result: SelectionResult | None) -> None:
        try:
            self.window.destroy()
        finally:
            self.on_done(result)
