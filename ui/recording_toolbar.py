from __future__ import annotations

import tkinter as tk
from typing import Callable

from platform_tools.windows import exclude_window_from_capture


WHITE = "#ffffff"
TEXT = "#171717"
MUTED = "#777773"
LINE = "#d8d8d4"
SOFT = "#f2f2ef"
RED = "#c83f38"
GREEN = "#3f7657"


def format_bytes(value: int | float) -> str:
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def update(self, text: str) -> None:
        self.text = text

    def _show(self, _event=None) -> None:
        if self.tip or not self.text:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(
            self.tip,
            text=self.text,
            bg="#20201f",
            fg=WHITE,
            padx=8,
            pady=5,
            font=("Segoe UI", 8),
            relief="solid",
            bd=0,
        ).pack()
        try:
            self.tip.update_idletasks()
            exclude_window_from_capture(int(self.tip.winfo_id()))
        except Exception:
            pass

    def _hide(self, _event=None) -> None:
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


class RecordingToolbar:
    """Compact, draggable recording controller.

    It is deliberately icon-first so it does not cover application text. On
    supported Windows versions WDA_EXCLUDEFROMCAPTURE keeps this top-level
    window out of display captures. The timer can be clicked to show the live
    file size without making the bar wider.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_pause: Callable[[], None],
        on_focus: Callable[[], None],
        on_screenshot: Callable[[], None],
        on_stop: Callable[[], None],
        focus_enabled: bool,
        initial_x: int = -1,
        initial_y: int = 18,
        initial_display: str = "timer",
        on_position_changed: Callable[[int, int], None] | None = None,
        on_display_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.on_pause = on_pause
        self.on_focus = on_focus
        self.on_screenshot = on_screenshot
        self.on_stop = on_stop
        self.on_position_changed = on_position_changed
        self.on_display_changed = on_display_changed
        self.focus_enabled = focus_enabled
        self.display_mode = initial_display if initial_display in {"timer", "size"} else "timer"
        self._drag_origin = (0, 0)
        self._window_origin = (0, 0)
        self._excluded = False
        self._elapsed = 0.0
        self._bytes_written = 0
        self._bytes_per_minute = 0

        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        try:
            self.window.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        self.window.configure(bg=LINE)

        shell = tk.Frame(self.window, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        self.drag_area = tk.Frame(shell, bg=WHITE, width=18, height=36, cursor="fleur")
        self.drag_area.pack(side="left", fill="y")
        self.drag_area.pack_propagate(False)
        dots = tk.Label(self.drag_area, text="⋮", bg=WHITE, fg="#9a9a96", font=("Segoe UI", 13), cursor="fleur")
        dots.pack(expand=True)

        self.status_button = tk.Button(
            shell,
            text="00:00",
            command=self._toggle_display,
            bg=WHITE,
            fg=TEXT,
            activebackground=SOFT,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            width=7,
            padx=3,
            pady=7,
            font=("Cascadia Mono", 9, "bold"),
            cursor="hand2",
        )
        self.status_button.pack(side="left", padx=(1, 4), pady=3)
        self.status_tip = ToolTip(self.status_button, "Click to show live file size")

        self.pause_button, self.pause_tip = self._icon_button(shell, "Ⅱ", self.on_pause, "Pause  ·  F10")
        self.focus_button, self.focus_tip = self._icon_button(shell, "⌖", self.on_focus, "Choose a focus area  ·  F6")
        self.shot_button, self.shot_tip = self._icon_button(shell, "▣", self.on_screenshot, "Save screenshot  ·  F8")
        self.stop_button, self.stop_tip = self._icon_button(shell, "■", self.on_stop, "Stop and save  ·  F9", danger=True)

        if not focus_enabled:
            self.focus_button.configure(state="disabled", fg="#b8b8b4")
            self.focus_tip.update("Live focus is off in Advanced settings")

        for widget in (shell, self.drag_area, dots):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)

        self.window.bind("<Escape>", lambda _event: None)
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = initial_x if initial_x >= 0 else max(8, (screen_width - width) // 2)
        y = max(4, min(initial_y, max(4, screen_height - 48)))
        self.window.geometry(f"+{x}+{y}")
        self.window.after(30, self._apply_capture_exclusion)
        self.window.after(250, self._apply_capture_exclusion)

    def _icon_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        tooltip: str,
        *,
        danger: bool = False,
    ) -> tuple[tk.Button, ToolTip]:
        frame = tk.Frame(parent, bg=WHITE, width=34, height=34)
        frame.pack(side="left", padx=2, pady=3)
        frame.pack_propagate(False)
        button = tk.Button(
            frame,
            text=text,
            command=command,
            bg=WHITE,
            fg=RED if danger else TEXT,
            activebackground=SOFT,
            activeforeground=RED if danger else TEXT,
            disabledforeground="#aaaaa6",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI Symbol", 11, "bold"),
            cursor="hand2",
        )
        button.pack(fill="both", expand=True)
        return button, ToolTip(button, tooltip)

    def _apply_capture_exclusion(self) -> None:
        try:
            self.window.update_idletasks()
            self._excluded = exclude_window_from_capture(int(self.window.winfo_id()))
        except Exception:
            self._excluded = False

    @property
    def excluded_from_capture(self) -> bool:
        return self._excluded

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_origin = (int(event.x_root), int(event.y_root))
        self._window_origin = (self.window.winfo_x(), self.window.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        dx = int(event.x_root) - self._drag_origin[0]
        dy = int(event.y_root) - self._drag_origin[1]
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = max(0, min(self._window_origin[0] + dx, screen_w - width))
        y = max(0, min(self._window_origin[1] + dy, screen_h - height))
        self.window.geometry(f"+{x}+{y}")

    def _drag_end(self, _event=None) -> None:
        if self.on_position_changed:
            self.on_position_changed(self.window.winfo_x(), self.window.winfo_y())
        self.window.after(20, self._apply_capture_exclusion)

    def _toggle_display(self) -> None:
        self.display_mode = "size" if self.display_mode == "timer" else "timer"
        if self.on_display_changed:
            self.on_display_changed(self.display_mode)
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self.display_mode == "size":
            text = format_bytes(self._bytes_written)
            if len(text) > 8:
                text = text.replace(" ", "")
            self.status_button.configure(text=text)
            self.status_tip.update(f"{format_bytes(self._bytes_per_minute)} per minute · click to show timer")
            return
        total = max(0, int(self._elapsed))
        text = f"{total // 60:02d}:{total % 60:02d}" if total < 3600 else f"{total // 3600:d}:{(total % 3600) // 60:02d}"
        self.status_button.configure(text=text)
        self.status_tip.update(f"{format_bytes(self._bytes_written)} written · click to show size")

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.attributes("-topmost", True)
        self.window.after(30, self._apply_capture_exclusion)
        self.window.after(350, self._apply_capture_exclusion)

    def hide(self) -> None:
        self.window.withdraw()

    def close(self) -> None:
        try:
            self._drag_end()
            self.window.destroy()
        except tk.TclError:
            pass

    def update_stats(self, elapsed: float, bytes_written: int, bytes_per_minute: int) -> None:
        self._elapsed = max(0.0, float(elapsed))
        self._bytes_written = max(0, int(bytes_written))
        self._bytes_per_minute = max(0, int(bytes_per_minute))
        self._refresh_status()

    def set_paused(self, paused: bool) -> None:
        self.pause_button.configure(text="▶" if paused else "Ⅱ")
        self.pause_tip.update("Resume  ·  F10" if paused else "Pause  ·  F10")

    def set_focus_active(self, active: bool) -> None:
        self.focus_button.configure(text="↙" if active else "⌖", fg=GREEN if active else TEXT)
        self.focus_tip.update("Return to full screen  ·  F6" if active else "Choose a focus area  ·  F6")

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.pause_button.configure(state=state)
        self.focus_button.configure(state=state if self.focus_enabled else "disabled")
        self.shot_button.configure(state=state)

    def set_stopping(self) -> None:
        self.pause_button.configure(state="disabled")
        self.focus_button.configure(state="disabled")
        self.shot_button.configure(state="disabled")
        self.stop_button.configure(state="disabled", text="…")
        self.stop_tip.update("Finalizing and verifying the recording")
