from __future__ import annotations

import queue
import shutil
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from platform_tools.windows import WindowInfo, list_visible_windows
from recorder.capture import MonitorInfo, list_monitors
from recorder.config import APP_VERSION, AppConfig, app_data_dir
from recorder.diagnostics import create_diagnostic_report
from recorder.encoder import available_encoders
from recorder.models import RecorderEvent, RecordingOptions, RecordingState
from recorder.recovery import scan_recoverable
from recorder.utils import find_binary, open_in_file_manager
from recorder.worker import RecorderWorker
from .recording_toolbar import RecordingToolbar
from .recovery_dialog import RecoveryDialog
from .selection_overlay import SelectionOverlay, SelectionResult
from .tray import TrayController

try:
    from pynput import keyboard as pynput_keyboard
except Exception:
    pynput_keyboard = None


BG = "#f5f5f2"
WHITE = "#ffffff"
TEXT = "#171717"
MUTED = "#6f6f6b"
LINE = "#dcdcd8"
SOFT = "#efefec"
DARK = "#1b1b1a"
RED = "#c8423b"
GREEN = "#3f7657"
AMBER = "#8b682d"


def format_bytes(value: int | float) -> str:
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = AppConfig.load()
        self.events: "queue.Queue[RecorderEvent]" = queue.Queue()
        self.ui_actions: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self.worker: RecorderWorker | None = None
        self.toolbar: RecordingToolbar | None = None
        self.recording_state = RecordingState.IDLE
        self.monitors: list[MonitorInfo] = []
        self.monitor_lookup: dict[str, MonitorInfo] = {}
        self.windows: list[WindowInfo] = []
        self.window_lookup: dict[str, WindowInfo] = {}
        self.current_region = {
            "left": self.config.region_left,
            "top": self.config.region_top,
            "width": self.config.region_width,
            "height": self.config.region_height,
        }
        self.last_elapsed = 0.0
        self.last_session_dir: str | None = None
        self.last_output: str | None = None
        self._closing = False
        self._exit_after_save = False
        self._hidden_to_tray = False
        self._tray_notice_shown = False
        self.hotkey_listener = None
        self.hotkeys_available = False
        self.focus_active = False
        self._focus_overlay_open = False
        self._focus_was_already_paused = False
        self._focus_pause_deadline = 0
        self._countdown_job: str | None = None
        self._pending_options: RecordingOptions | None = None

        self.root.title("ResiliCapture")
        self.root.geometry("860x660")
        self.root.minsize(780, 600)
        self.root.configure(bg=BG)
        self._configure_styles()
        self._build_ui()
        self.refresh_monitors()
        self.refresh_windows()
        self._load_config_into_ui()
        self._source_changed()
        self._mode_changed()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F9>", lambda _e: self._toggle_start_stop())
        self.root.bind("<F10>", lambda _e: self.toggle_pause())
        self.root.bind("<F6>", lambda _e: self.toggle_focus())
        self.root.bind("<F8>", lambda _e: self.take_screenshot())
        self._start_global_hotkeys()
        asset_root = Path(__file__).resolve().parent.parent / "assets"
        tray_icon = asset_root / "app.png"
        self.tray = TrayController(
            icon_path=tray_icon,
            dispatch=self._queue_ui_action,
            on_show=self._show_from_tray,
            on_toggle_pause=self._tray_toggle_pause,
            on_stop=self._tray_stop,
            on_open_recordings=self.open_recordings,
            on_exit=self._request_exit,
        )
        self.tray.start()
        self._update_tray_status()
        self.root.after(500, self._check_recovery)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=WHITE)
        style.configure("TLabel", background=WHITE, foreground=TEXT, font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background=WHITE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure(
            "TButton",
            background=WHITE,
            foreground=TEXT,
            bordercolor=LINE,
            lightcolor=WHITE,
            darkcolor=WHITE,
            padding=(11, 7),
            font=("Segoe UI Semibold", 9),
        )
        style.map("TButton", background=[("active", SOFT), ("disabled", "#f3f3f0")], foreground=[("disabled", "#aaa")])
        style.configure(
            "Primary.TButton",
            background=DARK,
            foreground=WHITE,
            bordercolor=DARK,
            lightcolor=DARK,
            darkcolor=DARK,
            padding=(25, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Primary.TButton", background=[("active", "#343432"), ("disabled", "#dededb")], foreground=[("disabled", "#999")])
        style.configure("TCombobox", fieldbackground=WHITE, background=WHITE, foreground=TEXT, bordercolor=LINE, arrowcolor=MUTED, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", WHITE)], foreground=[("readonly", TEXT)])
        style.configure("TEntry", fieldbackground=WHITE, foreground=TEXT, insertcolor=TEXT, bordercolor=LINE, padding=6)
        style.configure("TSpinbox", fieldbackground=WHITE, foreground=TEXT, bordercolor=LINE, padding=6)
        style.configure("TCheckbutton", background=WHITE, foreground=TEXT, font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", WHITE)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 8), borderwidth=0, font=("Segoe UI Semibold", 9))
        style.map("TNotebook.Tab", background=[("selected", WHITE)], foreground=[("selected", TEXT)])

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=WHITE, height=66, highlightthickness=1, highlightbackground=LINE)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=WHITE)
        brand.pack(side="left", padx=20, pady=10)
        tk.Label(brand, text="ResiliCapture", bg=WHITE, fg=TEXT, font=("Segoe UI Semibold", 16)).pack(anchor="w")
        tk.Label(brand, text="Reliable local-first recording with recoverable saves.", bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        actions = tk.Frame(header, bg=WHITE)
        actions.pack(side="right", padx=16, pady=14)
        ttk.Button(actions, text="Recordings", command=self.open_recordings).pack(side="left", padx=3)
        ttk.Button(actions, text="Recovery", command=self.open_recovery).pack(side="left", padx=3)
        ttk.Button(actions, text="Diagnostics", command=self.show_diagnostics).pack(side="left", padx=3)

        footer = tk.Frame(self.root, bg=WHITE, height=72, highlightthickness=1, highlightbackground=LINE)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        status_box = tk.Frame(footer, bg=WHITE)
        status_box.pack(side="left", padx=20, pady=13)
        self.header_status = tk.Label(status_box, text="Ready", bg=WHITE, fg=MUTED, font=("Segoe UI Semibold", 9), anchor="w")
        self.header_status.pack(anchor="w")
        self.shortcut_label = tk.Label(status_box, text="F9 record/stop  ·  F10 pause  ·  F6 focus  ·  F8 screenshot", bg=WHITE, fg="#92928e", font=("Segoe UI", 8))
        self.shortcut_label.pack(anchor="w", pady=(3, 0))
        self.start_button = ttk.Button(footer, text="Record", style="Primary.TButton", command=self.start_recording)
        self.start_button.pack(side="right", padx=20, pady=13)

        notebook_wrap = tk.Frame(self.root, bg=BG)
        notebook_wrap.pack(fill="both", expand=True, padx=16, pady=13)
        self.notebook = ttk.Notebook(notebook_wrap)
        self.notebook.pack(fill="both", expand=True)
        self.recording_tab = tk.Frame(self.notebook, bg=BG)
        self.advanced_tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.recording_tab, text="Recording")
        self.notebook.add(self.advanced_tab, text="Advanced")
        self._build_recording_tab()
        self._build_advanced_tab()

    def _build_recording_tab(self) -> None:
        tab = self.recording_tab
        tab.grid_columnconfigure(0, weight=1, uniform="recording_columns")
        tab.grid_columnconfigure(1, weight=1, uniform="recording_columns")
        tab.grid_rowconfigure(0, weight=1)
        left = tk.Frame(tab, bg=BG)
        right = tk.Frame(tab, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=8)

        capture_card = self._card(left, "Capture", "Display, selected area, or a visible application/phone mirror window.")
        capture_card.pack(fill="x", pady=(0, 10))
        self.source_mode_var = tk.StringVar(value="Display")
        self.source_box = ttk.Combobox(capture_card, textvariable=self.source_mode_var, values=["Display", "Area", "Window / phone mirror"], state="readonly")
        self.source_box.pack(fill="x", padx=15, pady=(1, 7))
        self.source_box.bind("<<ComboboxSelected>>", lambda _e: self._source_changed())
        self.source_control = tk.Frame(capture_card, bg=WHITE)
        self.source_control.pack(fill="x", padx=15)
        self.monitor_var = tk.StringVar()
        self.monitor_box = ttk.Combobox(self.source_control, textvariable=self.monitor_var, state="readonly")
        self.monitor_box.bind("<<ComboboxSelected>>", lambda _e: self._monitor_selected())
        self.window_var = tk.StringVar()
        self.window_box = ttk.Combobox(self.source_control, textvariable=self.window_var, state="readonly")
        self.window_box.bind("<<ComboboxSelected>>", lambda _e: self._window_selected())
        self.area_button = ttk.Button(self.source_control, text="Select area", command=self.select_capture_area)
        self.source_summary = tk.Label(capture_card, text="", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.source_summary.pack(fill="x", padx=15, pady=(7, 6))
        self.cursor_var = tk.BooleanVar(value=self.config.capture_cursor)
        ttk.Checkbutton(capture_card, text="Capture mouse cursor", variable=self.cursor_var).pack(anchor="w", padx=15, pady=(0, 12))

        mode_card = self._card(left, "Mode", "Normal recording or controlled timelapse capture.")
        mode_card.pack(fill="both", expand=True)
        self.mode_var = tk.StringVar(value="Normal")
        self.mode_box = ttk.Combobox(mode_card, textvariable=self.mode_var, values=["Normal", "Timelapse"], state="readonly")
        self.mode_box.pack(fill="x", padx=15, pady=(1, 7))
        self.mode_box.bind("<<ComboboxSelected>>", lambda _e: self._mode_changed())
        self.mode_controls = tk.Frame(mode_card, bg=WHITE)
        self.mode_controls.pack(fill="x", padx=15)
        self.fps_var = tk.IntVar(value=self.config.fps)
        self.normal_fps_row = tk.Frame(self.mode_controls, bg=WHITE)
        tk.Label(self.normal_fps_row, text="Frame rate", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), width=12, anchor="w").pack(side="left")
        ttk.Combobox(self.normal_fps_row, textvariable=self.fps_var, values=[10, 15, 24, 30, 60], state="readonly").pack(side="left", fill="x", expand=True, padx=(5, 4))
        tk.Label(self.normal_fps_row, text="fps", bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")

        self.timelapse_interval_var = tk.DoubleVar(value=self.config.timelapse_interval)
        self.timelapse_interval_row = tk.Frame(self.mode_controls, bg=WHITE)
        tk.Label(self.timelapse_interval_row, text="Capture every", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), width=12, anchor="w").pack(side="left")
        ttk.Spinbox(self.timelapse_interval_row, from_=0.1, to=3600.0, increment=0.1, textvariable=self.timelapse_interval_var).pack(side="left", fill="x", expand=True, padx=(5, 4))
        tk.Label(self.timelapse_interval_row, text="sec", bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")

        self.timelapse_fps_var = tk.IntVar(value=self.config.timelapse_output_fps)
        self.timelapse_fps_row = tk.Frame(self.mode_controls, bg=WHITE)
        tk.Label(self.timelapse_fps_row, text="Playback rate", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), width=12, anchor="w").pack(side="left")
        ttk.Combobox(self.timelapse_fps_row, textvariable=self.timelapse_fps_var, values=[15, 24, 30, 60], state="readonly").pack(side="left", fill="x", expand=True, padx=(5, 4))
        tk.Label(self.timelapse_fps_row, text="fps", bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
        self.mode_summary = tk.Label(mode_card, text="", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left")
        self.mode_summary.pack(fill="x", padx=15, pady=(5, 12))

        video_card = self._card(right, "Video", "No live preview is rendered; capture resources stay with the recorder.")
        video_card.pack(fill="x", pady=(0, 10))
        video_grid = tk.Frame(video_card, bg=WHITE)
        video_grid.pack(fill="x", padx=15, pady=(1, 12))
        video_grid.grid_columnconfigure(1, weight=1)
        self.scale_var = tk.IntVar(value=self.config.scale_percent)
        self.quality_var = tk.StringVar(value=self.config.quality)
        self.encoder_var = tk.StringVar(value=self.config.encoder)
        self._field(video_grid, 0, "Recording size", ttk.Combobox(video_grid, textvariable=self.scale_var, values=[25, 50, 75, 100], state="readonly"), "%")
        self._field(video_grid, 1, "Quality", ttk.Combobox(video_grid, textvariable=self.quality_var, values=["Performance", "Balanced", "Quality", "Near lossless"], state="readonly"))
        encoders = available_encoders()
        encoder_values = ["Auto"] + [item.label for item in encoders]
        if "Software H.264" not in encoder_values:
            encoder_values.append("Software H.264")
        self._field(video_grid, 2, "Encoder", ttk.Combobox(video_grid, textvariable=self.encoder_var, values=encoder_values, state="readonly"))
        self.sharpness_label = tk.Label(
            video_card, text="", bg=WHITE, fg=GREEN, font=("Segoe UI", 8),
            anchor="w", justify="left", wraplength=340,
        )
        self.sharpness_label.pack(fill="x", padx=15, pady=(0, 11))

        output_card = self._card(right, "Output", "The compact recording bar can switch between timer and live file size.")
        output_card.pack(fill="both", expand=True)
        self.save_var = tk.StringVar(value=self.config.save_dir)
        save_row = tk.Frame(output_card, bg=WHITE)
        save_row.pack(fill="x", padx=15, pady=(1, 7))
        ttk.Entry(save_row, textvariable=self.save_var).pack(side="left", fill="x", expand=True)
        ttk.Button(save_row, text="Browse", command=self.browse_save_dir).pack(side="left", padx=(7, 0))
        self.estimate_label = tk.Label(output_card, text="", bg=WHITE, fg=TEXT, font=("Segoe UI Semibold", 10), anchor="w")
        self.estimate_label.pack(fill="x", padx=15, pady=(8, 2))
        self.storage_label = tk.Label(output_card, text="", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=340)
        self.storage_label.pack(fill="x", padx=15)
        tk.Label(output_card, text="Recorded as short recoverable segments, then verified into one MP4.", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=340).pack(fill="x", padx=15, pady=(12, 13))

        for variable in (self.fps_var, self.scale_var, self.quality_var, self.timelapse_interval_var, self.timelapse_fps_var):
            variable.trace_add("write", lambda *_args: self._update_estimate())
        self.scale_var.trace_add("write", lambda *_args: self._update_sharpness_hint())
        self.quality_var.trace_add("write", lambda *_args: self._update_sharpness_hint())

    def _build_advanced_tab(self) -> None:
        tab = self.advanced_tab
        tab.grid_columnconfigure(0, weight=1, uniform="advanced_columns")
        tab.grid_columnconfigure(1, weight=1, uniform="advanced_columns")
        tab.grid_rowconfigure(0, weight=1)
        left = tk.Frame(tab, bg=BG)
        right = tk.Frame(tab, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=8)

        safety_card = self._card(left, "Safety and controls", "Startup, segment sealing, storage reserve, automatic stop, and the compact recording bar.")
        safety_card.pack(fill="both", expand=True)
        safety_grid = tk.Frame(safety_card, bg=WHITE)
        safety_grid.pack(fill="x", padx=15, pady=(1, 6))
        safety_grid.grid_columnconfigure(1, weight=1)
        self.countdown_var = tk.IntVar(value=self.config.countdown_seconds)
        self.segment_var = tk.IntVar(value=self.config.segment_seconds)
        self.min_free_var = tk.IntVar(value=self.config.min_free_mb)
        self.max_duration_var = tk.IntVar(value=self.config.max_duration_minutes)
        self._field(safety_grid, 0, "Countdown", ttk.Combobox(safety_grid, textvariable=self.countdown_var, values=[0, 3, 5, 10], state="readonly"), "sec")
        self._field(safety_grid, 1, "Seal segment", ttk.Combobox(safety_grid, textvariable=self.segment_var, values=[15, 30, 60, 120], state="readonly"), "sec")
        self._field(safety_grid, 2, "Keep free", ttk.Spinbox(safety_grid, from_=128, to=102400, increment=128, textvariable=self.min_free_var), "MB")
        self._field(safety_grid, 3, "Stop after", ttk.Spinbox(safety_grid, from_=0, to=1440, increment=1, textvariable=self.max_duration_var), "min")
        self.keep_segments_var = tk.BooleanVar(value=self.config.keep_session_segments)
        ttk.Checkbutton(safety_card, text="Keep recovery segments after success", variable=self.keep_segments_var).pack(anchor="w", padx=15, pady=(2, 8))
        tk.Frame(safety_card, bg=LINE, height=1).pack(fill="x", padx=15, pady=(2, 8))
        tk.Label(safety_card, text="Compact bar", bg=WHITE, fg=TEXT, font=("Segoe UI Semibold", 9), anchor="w").pack(fill="x", padx=15)
        tk.Label(safety_card, text="Ⅱ  Pause     ⌖  Focus     ▣  Screenshot     ■  Stop", bg=WHITE, fg=TEXT, font=("Segoe UI Symbol", 9), anchor="w").pack(fill="x", padx=15, pady=(5, 3))
        tk.Label(safety_card, text="Click the timer to show file size. Drag the left handle to move it. Set Stop after to 0 for no limit.", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=340).pack(fill="x", padx=15, pady=(0, 5))
        tk.Label(safety_card, text="Closing the main window sends ResiliCapture to the system tray. Use Exit ResiliCapture from the tray menu for a full shutdown.", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=340).pack(fill="x", padx=15, pady=(0, 12))

        focus_card = self._card(right, "Optional live focus", "Focus is secondary and is baked directly into the recording—there is no editor step.")
        focus_card.pack(fill="both", expand=True)
        self.live_focus_var = tk.BooleanVar(value=self.config.live_focus_enabled)
        ttk.Checkbutton(focus_card, text="Enable Focus button while recording", variable=self.live_focus_var, command=self._focus_enabled_changed).pack(anchor="w", padx=15, pady=(1, 7))
        self.focus_controls = tk.Frame(focus_card, bg=WHITE)
        self.focus_controls.pack(fill="x", padx=15, pady=(0, 6))
        self.focus_controls.grid_columnconfigure(1, weight=1)
        self.zoom_var = tk.DoubleVar(value=self.config.focus_zoom)
        self.transition_var = tk.DoubleVar(value=self.config.focus_transition)
        self.focus_style_var = tk.StringVar(value=self.config.focus_style if self.config.focus_style in {"Zoom", "Spotlight", "Zoom + Spotlight"} else "Zoom")
        self._field(self.focus_controls, 0, "Zoom", ttk.Spinbox(self.focus_controls, from_=1.1, to=4.0, increment=0.05, textvariable=self.zoom_var), "×")
        self._field(self.focus_controls, 1, "Transition", ttk.Spinbox(self.focus_controls, from_=0.1, to=2.0, increment=0.05, textvariable=self.transition_var), "sec")
        self._field(self.focus_controls, 2, "Style", ttk.Combobox(self.focus_controls, textvariable=self.focus_style_var, values=["Zoom", "Spotlight", "Zoom + Spotlight"], state="readonly"))
        tk.Frame(focus_card, bg=LINE, height=1).pack(fill="x", padx=15, pady=(2, 8))
        tk.Label(focus_card, text="Keyboard", bg=WHITE, fg=TEXT, font=("Segoe UI Semibold", 9), anchor="w").pack(fill="x", padx=15)
        tk.Label(focus_card, text="F9   Record / stop\nF10  Pause / resume\nF6   Focus / return\nF8   Screenshot", bg=WHITE, fg=TEXT, font=("Cascadia Mono", 9), justify="left", anchor="nw").pack(fill="x", padx=15, pady=(5, 6))
        tk.Label(focus_card, text="Normal recording, pause, stop, timelapse, recovery, and size tracking never depend on Focus.", bg=WHITE, fg=MUTED, font=("Segoe UI", 8), justify="left", anchor="nw", wraplength=340).pack(fill="x", padx=15, pady=(0, 12))

    @staticmethod
    def _card(parent: tk.Misc, title: str, subtitle: str) -> tk.Frame:
        card = tk.Frame(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        tk.Label(card, text=title, bg=WHITE, fg=TEXT, font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=15, pady=(13, 2))
        tk.Label(card, text=subtitle, bg=WHITE, fg=MUTED, font=("Segoe UI", 8), wraplength=350, justify="left").pack(anchor="w", padx=15, pady=(0, 9))
        return card

    @staticmethod
    def _field(parent: tk.Frame, row: int, label: str, widget: tk.Widget, suffix: str = "") -> None:
        tk.Label(parent, text=label, bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).grid(row=row, column=0, sticky="w", pady=4)
        widget.grid(row=row, column=1, sticky="ew", padx=(11, 4), pady=4)
        if suffix:
            tk.Label(parent, text=suffix, bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).grid(row=row, column=2, sticky="w", pady=4)

    @staticmethod
    def _inline_row(parent: tk.Frame, label: str, widget: tk.Widget, suffix: str = "") -> tk.Frame:
        row = tk.Frame(parent, bg=WHITE)
        tk.Label(row, text=label, bg=WHITE, fg=MUTED, font=("Segoe UI", 8), width=12, anchor="w").pack(side="left")
        widget.pack(side="left", fill="x", expand=True, padx=(5, 4))
        if suffix:
            tk.Label(row, text=suffix, bg=WHITE, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
        return row

    def _start_global_hotkeys(self) -> None:
        if pynput_keyboard is None:
            return

        def released(key) -> None:
            actions = {
                pynput_keyboard.Key.f9: self._toggle_start_stop,
                pynput_keyboard.Key.f10: self.toggle_pause,
                pynput_keyboard.Key.f6: self.toggle_focus,
                pynput_keyboard.Key.f8: self.take_screenshot,
            }
            action = actions.get(key)
            if action and not self._closing:
                self.root.after(0, lambda a=action: self._run_global_hotkey(a))

        try:
            self.hotkey_listener = pynput_keyboard.Listener(on_release=released)
            self.hotkey_listener.start()
            self.hotkeys_available = True
        except Exception:
            self.hotkey_listener = None
            self.hotkeys_available = False

    def _run_global_hotkey(self, action) -> None:
        try:
            focused = self.root.focus_get()
            if focused is not None and self.root.state() == "normal":
                return
        except tk.TclError:
            return
        action()

    def refresh_monitors(self) -> None:
        try:
            self.monitors = list_monitors()
        except Exception:
            self.monitors = []
        self.monitor_lookup = {item.label: item for item in self.monitors}
        self.monitor_box["values"] = list(self.monitor_lookup)
        preferred = next((m.label for m in self.monitors if m.index == self.config.monitor_index), None)
        if preferred:
            self.monitor_var.set(preferred)
        elif self.monitors:
            self.monitor_var.set(self.monitors[1].label if len(self.monitors) > 1 else self.monitors[0].label)

    def refresh_windows(self) -> None:
        self.windows = list_visible_windows()
        self.window_lookup = {item.label: item for item in self.windows}
        self.window_box["values"] = list(self.window_lookup)
        if self.windows and self.window_var.get() not in self.window_lookup:
            self.window_var.set(self.windows[0].label)

    def _load_config_into_ui(self) -> None:
        source_map = {"monitor": "Display", "region": "Area", "window": "Window / phone mirror"}
        self.source_mode_var.set(source_map.get(self.config.source_mode, "Display"))
        self.save_var.set(self.config.save_dir)
        self.mode_var.set("Timelapse" if self.config.mode == "timelapse" else "Normal")
        self.fps_var.set(self.config.fps)
        self.timelapse_interval_var.set(self.config.timelapse_interval)
        self.timelapse_fps_var.set(self.config.timelapse_output_fps)
        self.scale_var.set(self.config.scale_percent)
        self.quality_var.set(self.config.quality)
        self.encoder_var.set(self.config.encoder)
        self.cursor_var.set(self.config.capture_cursor)
        self.countdown_var.set(self.config.countdown_seconds)
        self.segment_var.set(max(15, self.config.segment_seconds))
        self.min_free_var.set(self.config.min_free_mb)
        self.max_duration_var.set(self.config.max_duration_minutes)
        self.keep_segments_var.set(self.config.keep_session_segments)
        self.live_focus_var.set(self.config.live_focus_enabled)
        self.zoom_var.set(self.config.focus_zoom)
        self.transition_var.set(self.config.focus_transition)
        self.focus_style_var.set(self.config.focus_style)
        self._focus_enabled_changed()

    def _source_changed(self) -> None:
        for child in self.source_control.winfo_children():
            child.pack_forget()
        mode = self.source_mode_var.get()
        if mode == "Display":
            self.monitor_box.pack(fill="x")
            self._monitor_selected()
        elif mode == "Area":
            self.area_button.pack(fill="x")
        else:
            self.window_box.pack(fill="x")
            self._window_selected()
        self._update_source_summary()
        self._update_estimate()

    def _mode_changed(self) -> None:
        self.normal_fps_row.pack_forget()
        self.timelapse_interval_row.pack_forget()
        self.timelapse_fps_row.pack_forget()
        if self.mode_var.get() == "Timelapse":
            self.timelapse_interval_row.pack(fill="x", pady=3)
            self.timelapse_fps_row.pack(fill="x", pady=3)
        else:
            self.normal_fps_row.pack(fill="x", pady=3)
        self._update_estimate()

    def _focus_enabled_changed(self) -> None:
        enabled = bool(self.live_focus_var.get())
        for child in self.focus_controls.winfo_children():
            try:
                if isinstance(child, ttk.Combobox):
                    child.configure(state="readonly" if enabled else "disabled")
                else:
                    child.configure(state="normal" if enabled else "disabled")
            except tk.TclError:
                pass

    def _monitor_selected(self) -> None:
        monitor = self.monitor_lookup.get(self.monitor_var.get())
        if monitor:
            self.current_region = monitor.as_dict()
        self._update_source_summary()
        self._update_estimate()

    def _window_selected(self) -> None:
        window = self.window_lookup.get(self.window_var.get())
        if window:
            self.current_region = window.as_region()
        self._update_source_summary()
        self._update_estimate()

    def _update_source_summary(self) -> None:
        region = self.current_region
        mode = self.source_mode_var.get()
        detail = f"{region['width']} × {region['height']}  ·  position {region['left']}, {region['top']}"
        if mode == "Window / phone mirror" and self.window_var.get():
            detail = f"{self.window_var.get().split(' — ')[0]}  ·  {region['width']} × {region['height']}"
        self.source_summary.configure(text=detail)
        self._update_sharpness_hint()

    def _update_sharpness_hint(self) -> None:
        if not hasattr(self, "sharpness_label"):
            return
        try:
            scale = max(1, int(self.scale_var.get()))
            quality = self.quality_var.get()
        except (tk.TclError, ValueError):
            return
        source_w = max(1, int(self.current_region.get("width", 1)))
        source_h = max(1, int(self.current_region.get("height", 1)))
        out_w = max(2, int(source_w * scale / 100.0))
        out_h = max(2, int(source_h * scale / 100.0))
        out_w -= out_w % 2
        out_h -= out_h % 2
        if scale == 100:
            if quality in {"Quality", "Near lossless"}:
                text = f"{out_w} × {out_h} native · sharp text preset"
                color = GREEN
            elif quality == "Balanced":
                text = f"{out_w} × {out_h} native · Balanced is now screen-text optimized"
                color = GREEN
            else:
                text = f"{out_w} × {out_h} native · Performance trades some text detail for speed"
                color = AMBER
        else:
            text = f"{out_w} × {out_h} output · downscaled from {source_w} × {source_h}; small text will be less sharp"
            color = AMBER
        self.sharpness_label.configure(text=text, fg=color)

    def select_capture_area(self) -> None:
        all_monitor = next((m for m in self.monitors if m.index == 0), None)
        if not all_monitor:
            messagebox.showerror("Displays unavailable", "Could not determine the virtual desktop bounds.", parent=self.root)
            return
        self.root.withdraw()

        def done(result: SelectionResult | None) -> None:
            self.root.deiconify()
            self.root.lift()
            if result:
                self.current_region = result.as_dict()
                self._update_source_summary()
                self._update_estimate()

        SelectionOverlay(self.root, all_monitor.as_dict(), title="Select the area to record", on_done=done, minimum_size=64)

    def _current_options(self) -> RecordingOptions:
        source_label = self.source_mode_var.get()
        source_mode = {"Display": "monitor", "Area": "region", "Window / phone mirror": "window"}[source_label]
        monitor = self.monitor_lookup.get(self.monitor_var.get())
        mode = "timelapse" if self.mode_var.get() == "Timelapse" else "normal"
        return RecordingOptions(
            save_dir=self.save_var.get().strip(),
            monitor_index=monitor.index if monitor else 0,
            source_mode=source_mode,
            region=dict(self.current_region),
            mode=mode,
            fps=int(self.fps_var.get()),
            scale=int(self.scale_var.get()) / 100.0,
            timelapse_interval=max(0.1, float(self.timelapse_interval_var.get())),
            timelapse_output_fps=int(self.timelapse_fps_var.get()),
            quality=self.quality_var.get(),
            encoder=self.encoder_var.get(),
            segment_seconds=max(15, int(self.segment_var.get())),
            min_free_mb=max(128, int(self.min_free_var.get())),
            capture_cursor=bool(self.cursor_var.get()),
            keep_session_segments=bool(self.keep_segments_var.get()),
            countdown_seconds=max(0, int(self.countdown_var.get())),
            max_duration_seconds=max(0, int(self.max_duration_var.get())) * 60.0,
            live_focus_enabled=bool(self.live_focus_var.get()) and mode == "normal",
            auto_focus_clicks=False,
            focus_zoom=float(self.zoom_var.get()),
            focus_hold=0.0,
            focus_transition=float(self.transition_var.get()),
            focus_style=self.focus_style_var.get(),
            focus_easing="Smooth",
            source_label=source_label,
        )

    def _save_config(self) -> None:
        source_label = self.source_mode_var.get()
        monitor = self.monitor_lookup.get(self.monitor_var.get())
        self.config.save_dir = self.save_var.get().strip()
        self.config.monitor_index = monitor.index if monitor else 0
        self.config.source_mode = {"Display": "monitor", "Area": "region", "Window / phone mirror": "window"}.get(source_label, "monitor")
        self.config.source_label = source_label
        self.config.region_left = self.current_region["left"]
        self.config.region_top = self.current_region["top"]
        self.config.region_width = self.current_region["width"]
        self.config.region_height = self.current_region["height"]
        self.config.mode = "timelapse" if self.mode_var.get() == "Timelapse" else "normal"
        self.config.fps = int(self.fps_var.get())
        self.config.timelapse_interval = max(0.1, float(self.timelapse_interval_var.get()))
        self.config.timelapse_output_fps = int(self.timelapse_fps_var.get())
        self.config.scale_percent = int(self.scale_var.get())
        self.config.quality = self.quality_var.get()
        self.config.encoder = self.encoder_var.get()
        self.config.capture_cursor = bool(self.cursor_var.get())
        self.config.countdown_seconds = int(self.countdown_var.get())
        self.config.segment_seconds = max(15, int(self.segment_var.get()))
        self.config.min_free_mb = int(self.min_free_var.get())
        self.config.max_duration_minutes = int(self.max_duration_var.get())
        self.config.keep_session_segments = bool(self.keep_segments_var.get())
        self.config.live_focus_enabled = bool(self.live_focus_var.get())
        self.config.auto_focus_clicks = False
        self.config.focus_zoom = float(self.zoom_var.get())
        self.config.focus_transition = float(self.transition_var.get())
        self.config.focus_style = self.focus_style_var.get()
        self.config.hide_during_recording = True
        self.config.save()

    def _estimate_per_real_minute(self) -> int:
        region = self.current_region
        pixels = region["width"] * region["height"] * (int(self.scale_var.get()) / 100.0) ** 2
        quality = {"Performance": 0.070, "Balanced": 0.125, "Quality": 0.180, "Near lossless": 0.300}.get(self.quality_var.get(), 0.180)
        if self.mode_var.get() == "Timelapse":
            effective_capture_fps = 1.0 / max(0.1, float(self.timelapse_interval_var.get()))
        else:
            effective_capture_fps = int(self.fps_var.get())
        return int(pixels * effective_capture_fps * quality / 8 * 60)

    def _update_estimate(self) -> None:
        if not hasattr(self, "estimate_label"):
            return
        estimate = max(1, self._estimate_per_real_minute())
        if self.mode_var.get() == "Timelapse":
            interval = max(0.1, float(self.timelapse_interval_var.get()))
            output_fps = max(1, int(self.timelapse_fps_var.get()))
            speed = interval * output_fps
            output_seconds_per_hour = 3600.0 / speed
            self.mode_summary.configure(text=f"Approximately {speed:.0f}× faster  ·  1 real hour becomes {output_seconds_per_hour:.1f} seconds")
            self.estimate_label.configure(text=f"About {format_bytes(estimate)} per real minute")
        else:
            self.mode_summary.configure(text="Continuous recording with pause, screenshot, and optional live focus. Use 100% for native-sharp text.")
            self.estimate_label.configure(text=f"About {format_bytes(estimate)} per minute")
        try:
            free = shutil.disk_usage(self.save_var.get() or Path.home()).free
            minutes = int(free / estimate)
            self.storage_label.configure(text=f"{format_bytes(free)} free  ·  approximately {minutes:,} real minutes at these settings")
        except OSError:
            self.storage_label.configure(text="Choose a writable folder to calculate available recording time.")

    def start_recording(self) -> None:
        if self.recording_state == RecordingState.COUNTDOWN:
            self._cancel_countdown()
            return
        if self.worker and self.worker.is_alive():
            return
        save_dir = self.save_var.get().strip()
        if not save_dir:
            messagebox.showerror("Save folder required", "Choose where recordings should be stored.", parent=self.root)
            return
        if self.source_mode_var.get() == "Window / phone mirror":
            self.refresh_windows()
            self._window_selected()
            if not self.window_var.get():
                messagebox.showerror("Window required", "Select the mirrored phone or application window to record.", parent=self.root)
                return
        try:
            options = self._current_options()
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return
        self._save_config()
        if options.countdown_seconds > 0:
            self._pending_options = options
            self.recording_state = RecordingState.COUNTDOWN
            self.start_button.configure(text="Cancel", state="normal")
            self._countdown_tick(options.countdown_seconds)
        else:
            self._launch_worker(options)

    def _countdown_tick(self, remaining: int) -> None:
        if self.recording_state != RecordingState.COUNTDOWN:
            return
        if remaining <= 0:
            self._countdown_job = None
            options = self._pending_options
            self._pending_options = None
            if options:
                self._launch_worker(options)
            return
        self._set_status(f"Recording starts in {remaining}…", AMBER)
        self._countdown_job = self.root.after(1000, lambda: self._countdown_tick(remaining - 1))

    def _cancel_countdown(self) -> None:
        if self._countdown_job:
            try:
                self.root.after_cancel(self._countdown_job)
            except tk.TclError:
                pass
        self._countdown_job = None
        self._pending_options = None
        self.recording_state = RecordingState.IDLE
        self.start_button.configure(text="Record", state="normal")
        self._set_status("Countdown cancelled", MUTED)

    def _launch_worker(self, options: RecordingOptions) -> None:
        self.focus_active = False
        self.worker = RecorderWorker(options, self.events)
        self.worker.start()
        self.recording_state = RecordingState.PREPARING
        self.start_button.configure(state="disabled", text="Preparing…")
        self._set_status("Checking capture, storage and encoder…", AMBER)

    def _show_recording_toolbar(self) -> None:
        if not self.worker:
            return
        if self.toolbar is None:
            self.toolbar = RecordingToolbar(
                self.root,
                on_pause=self.toggle_pause,
                on_focus=self.toggle_focus,
                on_screenshot=self.take_screenshot,
                on_stop=self.stop_recording,
                focus_enabled=bool(self.worker.options.live_focus_enabled),
                initial_x=self.config.toolbar_x,
                initial_y=self.config.toolbar_y,
                initial_display=self.config.toolbar_display,
                on_position_changed=self._toolbar_position_changed,
                on_display_changed=self._toolbar_display_changed,
            )
        self.toolbar.set_paused(self.recording_state == RecordingState.PAUSED)
        self.toolbar.set_focus_active(self.focus_active)
        self.toolbar.show()
        self._hidden_to_tray = False
        self.root.withdraw()

    def _toolbar_position_changed(self, x: int, y: int) -> None:
        self.config.toolbar_x = int(x)
        self.config.toolbar_y = int(y)
        self.config.save()

    def _toolbar_display_changed(self, mode: str) -> None:
        self.config.toolbar_display = mode
        self.config.save()

    def _close_recording_toolbar(self) -> None:
        if self.toolbar:
            self.toolbar.close()
            self.toolbar = None

    def stop_recording(self) -> None:
        if self.recording_state == RecordingState.COUNTDOWN:
            self._cancel_countdown()
            return
        if self.worker and self.worker.is_alive():
            if self.focus_active:
                self.worker.end_focus_marker()
                self.focus_active = False
            self.worker.stop()
            self.recording_state = RecordingState.STOPPING
            if self.toolbar:
                self.toolbar.set_stopping()
            # Bring the main application back immediately. Long timelapses can
            # take time to finalize, and leaving only the floating toolbar visible
            # made a healthy save operation look like the app had disappeared.
            self._close_recording_toolbar()
            self.root.deiconify()
            self.root.lift()
            self.start_button.configure(state="disabled", text="Saving…")
            self._set_status("Stopping capture and sealing the final segment…", AMBER)

    def toggle_pause(self) -> None:
        if not self.worker or not self.worker.is_alive() or self._focus_overlay_open:
            return
        paused = not self.worker.pause_event.is_set()
        self.worker.set_paused(paused)
        if self.toolbar:
            self.toolbar.set_paused(paused)

    def toggle_focus(self) -> None:
        if not self.worker or not self.worker.is_alive() or self._focus_overlay_open:
            return
        if not self.worker.options.live_focus_enabled:
            return
        if self.focus_active:
            marker = self.worker.end_focus_marker()
            self.focus_active = False
            if self.toolbar:
                self.toolbar.set_focus_active(False)
            if marker:
                self._set_status("Returning smoothly to the full screen", GREEN)
            return

        self._focus_was_already_paused = self.recording_state == RecordingState.PAUSED or self.worker.pause_event.is_set()
        if self.toolbar:
            self.toolbar.set_busy(True)
        if self._focus_was_already_paused and self.worker.is_pause_sealed():
            self._launch_focus_selection()
            return
        self.worker.set_paused(True)
        self._focus_pause_deadline = 100
        self._wait_for_focus_pause()

    def _wait_for_focus_pause(self) -> None:
        if not self.worker or not self.worker.is_alive():
            if self.toolbar:
                self.toolbar.set_busy(False)
            return
        if self.worker.is_pause_sealed():
            self._launch_focus_selection()
            return
        self._focus_pause_deadline -= 1
        if self._focus_pause_deadline <= 0:
            if not self._focus_was_already_paused:
                self.worker.set_paused(False)
            if self.toolbar:
                self.toolbar.set_busy(False)
            self._set_status("Focus selection could not pause safely; recording continued", RED)
            return
        self.root.after(40, self._wait_for_focus_pause)

    def _launch_focus_selection(self) -> None:
        if self._focus_overlay_open or not self.worker or not self.worker.is_alive():
            return
        self._focus_overlay_open = True
        bounds = dict(self.current_region)
        if self.toolbar:
            self.toolbar.hide()

        def done(result: SelectionResult | None) -> None:
            self._focus_overlay_open = False
            if self.toolbar:
                self.toolbar.show()
                self.toolbar.set_busy(False)
            if not self.worker or not self.worker.is_alive():
                return
            if result:
                region = {
                    "x": max(0.0, min((result.left - bounds["left"]) / max(1, bounds["width"]), 1.0)),
                    "y": max(0.0, min((result.top - bounds["top"]) / max(1, bounds["height"]), 1.0)),
                    "width": max(0.01, min(result.width / max(1, bounds["width"]), 1.0)),
                    "height": max(0.01, min(result.height / max(1, bounds["height"]), 1.0)),
                }
                marker = self.worker.begin_focus_marker(
                    region,
                    zoom=float(self.zoom_var.get()),
                    transition=float(self.transition_var.get()),
                    style=self.focus_style_var.get(),
                    easing="Smooth",
                )
                self.focus_active = marker is not None
                if self.toolbar:
                    self.toolbar.set_focus_active(self.focus_active)
                if not self._focus_was_already_paused:
                    self.worker.set_paused(False)
                self._set_status("Focus active — press Focus again to return", GREEN if self.focus_active else RED)
            elif not self._focus_was_already_paused:
                self.worker.set_paused(False)

        SelectionOverlay(self.root, bounds, title="Draw the area to focus", on_done=done, minimum_size=24)

    def take_screenshot(self) -> None:
        if self.worker and self.worker.is_alive():
            self.worker.request_screenshot()

    def _toggle_start_stop(self) -> None:
        if self.recording_state == RecordingState.COUNTDOWN:
            self._cancel_countdown()
        elif self.worker and self.worker.is_alive():
            self.stop_recording()
        else:
            self.start_recording()

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self.header_status.configure(text=text, fg=color)
        self._update_tray_status() if hasattr(self, "tray") else None

    def _queue_ui_action(self, callback: Callable[[], None]) -> None:
        # Tray callbacks run outside Tk's thread. Queueing is safe; _poll_events
        # executes the action from the Tk event loop.
        self.ui_actions.put(callback)

    def _poll_events(self) -> None:
        try:
            while True:
                callback = self.ui_actions.get_nowait()
                callback()
        except queue.Empty:
            pass
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        if not self._closing:
            self.root.after(70, self._poll_events)

    def _handle_event(self, event: RecorderEvent) -> None:
        payload = event.payload
        if event.kind == "state":
            try:
                self.recording_state = RecordingState(payload.get("state", RecordingState.IDLE.value))
            except ValueError:
                pass
            self.last_session_dir = payload.get("session_dir", self.last_session_dir)
            color = GREEN if self.recording_state == RecordingState.RECORDING else AMBER
            self._set_status(payload.get("message", self.recording_state.value), color)
            if self.recording_state == RecordingState.RECORDING:
                self._show_recording_toolbar()
                if self.toolbar:
                    self.toolbar.set_paused(False)
                    self.toolbar.set_busy(False)
            elif self.recording_state == RecordingState.PAUSED:
                if self.toolbar:
                    self.toolbar.set_paused(True)
            elif self.recording_state in {RecordingState.STOPPING, RecordingState.FINALIZING}:
                self._close_recording_toolbar()
                if not self._hidden_to_tray:
                    self.root.deiconify()
                    self.root.lift()
                self.start_button.configure(state="disabled", text="Saving…")
        elif event.kind == "finalize_progress":
            percent = float(payload.get("percent", 0.0))
            message = payload.get("message", "Saving video…")
            if "%" not in message and percent > 0:
                message = f"{message} {percent:.0f}%"
            self.start_button.configure(state="disabled", text=f"Saving {percent:.0f}%" if percent > 0 else "Saving…")
            self._set_status(message, GREEN if percent >= 100 else AMBER)
            if not self._hidden_to_tray:
                self.root.deiconify()
        elif event.kind == "stats":
            self.last_elapsed = float(payload.get("elapsed", 0.0))
            if self.toolbar:
                self.toolbar.update_stats(self.last_elapsed, int(payload.get("bytes_written", 0)), int(payload.get("bytes_per_minute", 0)))
        elif event.kind == "focus_started":
            self.focus_active = True
            if self.toolbar:
                self.toolbar.set_focus_active(True)
        elif event.kind == "focus_ended":
            self.focus_active = False
            if self.toolbar:
                self.toolbar.set_focus_active(False)
        elif event.kind == "warning":
            self._set_status(payload.get("message", "Recording warning"), AMBER)
        elif event.kind == "screenshot":
            self._set_status(f"Screenshot saved: {Path(payload['path']).name}", GREEN)
        elif event.kind == "completed":
            self.recording_state = RecordingState.COMPLETED
            self.last_output = payload.get("path")
            self.last_session_dir = payload.get("session_dir")
            self.worker = None
            self.focus_active = False
            self._close_recording_toolbar()
            self.start_button.configure(state="normal", text="Record")
            filename = Path(self.last_output).name if self.last_output else "recording"
            width = int(payload.get("width", 0) or 0)
            height = int(payload.get("height", 0) or 0)
            quality = payload.get("quality", "")
            details = f" · {width}×{height} · {quality}" if width and height else ""
            self._set_status(f"Saved and verified: {filename}{details}", GREEN)
            if getattr(self, "tray", None) is not None:
                self.tray.notify("Recording saved and verified", filename)
            if self._exit_after_save:
                self.root.after(100, self._shutdown)
            elif not self._hidden_to_tray:
                self.root.deiconify()
                self.root.lift()
        elif event.kind == "failed":
            self.recording_state = RecordingState.FAILED
            self.last_session_dir = payload.get("session_dir")
            self.worker = None
            self.focus_active = False
            self._exit_after_save = False
            self._hidden_to_tray = False
            self._close_recording_toolbar()
            self.root.deiconify()
            self.root.lift()
            self.start_button.configure(state="normal", text="Record")
            self._set_status("Recording stopped safely", RED)
            message = payload.get("error", "Unknown recording error")
            if payload.get("recoverable"):
                message += "\n\nCompleted segments are still available in Recovery."
            messagebox.showerror("Recording stopped", message, parent=self.root)

    def browse_save_dir(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, initialdir=self.save_var.get() or str(Path.home()))
        if selected:
            self.save_var.set(selected)
            self._save_config()
            self._update_estimate()

    def open_recordings(self) -> None:
        path = Path(self.save_var.get() or Path.home())
        path.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(path)

    def open_recovery(self) -> None:
        RecoveryDialog(self.root, Path(self.save_var.get() or Path.home()))

    def _check_recovery(self) -> None:
        try:
            sessions = scan_recoverable(Path(self.save_var.get() or Path.home()))
        except Exception:
            sessions = []
        if sessions:
            self._set_status(f"{len(sessions)} interrupted recording{'s' if len(sessions) != 1 else ''} can be recovered", AMBER)

    def show_diagnostics(self) -> None:
        ffmpeg = find_binary("ffmpeg") or "Not found"
        ffprobe = find_binary("ffprobe") or "Not found"
        try:
            free = shutil.disk_usage(self.save_var.get() or Path.home()).free
            free_text = format_bytes(free)
        except OSError:
            free_text = "Unavailable"
        details = (
            f"ResiliCapture: {APP_VERSION}\n"
            f"FFmpeg: {ffmpeg}\n"
            f"FFprobe: {ffprobe}\n"
            f"System tray: {'available' if getattr(self, 'tray', None) and self.tray.available else 'unavailable'}\n"
            f"Global hotkeys: {'available' if self.hotkeys_available else 'unavailable'}\n"
            f"Displays: {len(self.monitors)}\n"
            f"Visible windows: {len(self.windows)}\n"
            f"Free storage: {free_text}\n\n"
            "Create a privacy-sanitized diagnostic ZIP for a GitHub issue? "
            "It excludes recordings, screenshots, and full user paths."
        )
        if not messagebox.askyesno("Diagnostics", details, parent=self.root):
            return
        default_name = f"ResiliCapture-Diagnostics-{APP_VERSION}.zip"
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save diagnostic report",
            initialfile=default_name,
            defaultextension=".zip",
            filetypes=[("ZIP archive", "*.zip")],
        )
        if not selected:
            return
        try:
            report = create_diagnostic_report(
                Path(selected),
                app_version=APP_VERSION,
                save_dir=self.save_var.get() or None,
                session_dir=self.last_session_dir,
            )
            messagebox.showinfo("Diagnostic report created", f"Saved: {report.name}", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Could not create diagnostics", str(exc), parent=self.root)

    def _update_tray_status(self, message: str | None = None) -> None:
        tray = getattr(self, "tray", None)
        if tray is None:
            return
        if message:
            title = f"ResiliCapture — {message}"
        elif self.recording_state == RecordingState.RECORDING:
            title = "ResiliCapture — Recording"
        elif self.recording_state == RecordingState.PAUSED:
            title = "ResiliCapture — Paused"
        elif self.recording_state in {RecordingState.STOPPING, RecordingState.FINALIZING}:
            title = "ResiliCapture — Saving video"
        else:
            title = "ResiliCapture"
        tray.set_title(title)

    def _show_from_tray(self) -> None:
        if self._closing:
            return
        self._hidden_to_tray = False
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.after(50, self.root.focus_force)
        except tk.TclError:
            pass

    def _minimize_to_tray(self) -> None:
        if self._closing:
            return
        tray = getattr(self, "tray", None)
        if tray is not None and tray.available:
            self._hidden_to_tray = True
            self._save_config()
            self.root.withdraw()
            self._update_tray_status()
            if not self._tray_notice_shown:
                tray.notify("ResiliCapture is still running", "The window was sent to the system tray. Use the tray icon to show or exit ResiliCapture.")
                self._tray_notice_shown = True
            return
        # Never make the application unreachable if tray integration could not
        # start. Fall back to the normal taskbar minimize behavior.
        self._hidden_to_tray = False
        self.root.iconify()
        self._set_status("System tray is unavailable; ResiliCapture was minimized to the taskbar", AMBER)

    def _tray_toggle_pause(self) -> None:
        if self.worker and self.worker.is_alive() and self.recording_state in {RecordingState.RECORDING, RecordingState.PAUSED}:
            self.toggle_pause()
        else:
            self._show_from_tray()

    def _tray_stop(self) -> None:
        if self.worker and self.worker.is_alive() and self.recording_state not in {RecordingState.STOPPING, RecordingState.FINALIZING}:
            self._show_from_tray()
            self.stop_recording()
        else:
            self._show_from_tray()

    def _request_exit(self) -> None:
        if self._closing:
            return
        if self.recording_state == RecordingState.COUNTDOWN:
            self._show_from_tray()
            if not messagebox.askyesno("Exit ResiliCapture", "Cancel the countdown and exit ResiliCapture?", parent=self.root):
                return
            self._cancel_countdown()
            self._shutdown()
            return
        if self.worker and self.worker.is_alive():
            self._show_from_tray()
            if self.recording_state in {RecordingState.STOPPING, RecordingState.FINALIZING}:
                if messagebox.askyesno(
                    "Saving in progress",
                    "ResiliCapture is still creating and verifying the final video. Exit automatically after saving finishes?",
                    parent=self.root,
                ):
                    self._exit_after_save = True
                    self._minimize_to_tray()
                return
            if messagebox.askyesno(
                "Recording in progress",
                "Stop and save this recording, then exit ResiliCapture after the video is verified?",
                parent=self.root,
            ):
                self._exit_after_save = True
                self.stop_recording()
            return
        self._shutdown()

    def _shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._save_config()
        self._close_recording_toolbar()
        if self.hotkey_listener is not None:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        # The window close button is intentionally non-destructive. ResiliCapture
        # remains alive in the system tray so recording/finalization cannot be
        # accidentally killed. Full shutdown is available from the tray's Exit
        # command, which applies recording-aware confirmation.
        self._minimize_to_tray()
