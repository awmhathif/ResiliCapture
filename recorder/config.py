from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_NAME = "ResiliCapture"
APP_DISPLAY_NAME = "ResiliCapture"
APP_VERSION = "0.7.0"
SESSION_DIR_NAME = ".resilicapture_sessions"
LEGACY_APP_NAMES = ("FocusFlowRecorder",)
LEGACY_SESSION_DIR_NAMES = (".focusflow_sessions",)


def _config_base_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def app_data_dir() -> Path:
    path = _config_base_dir() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_app_data_dirs() -> tuple[Path, ...]:
    """Previous product-data locations kept read-only for upgrade compatibility."""
    base = _config_base_dir()
    return tuple(base / name for name in LEGACY_APP_NAMES)


def _settings_source() -> tuple[Path, bool]:
    current = app_data_dir() / "settings.json"
    if current.exists():
        return current, False
    for legacy_dir in legacy_app_data_dirs():
        candidate = legacy_dir / "settings.json"
        if candidate.exists():
            return candidate, True
    return current, False


def default_video_dir() -> Path:
    videos = Path.home() / "Videos"
    return videos if videos.exists() else Path.home()


@dataclass(slots=True)
class AppConfig:
    save_dir: str = str(default_video_dir())
    monitor_index: int = 1
    source_mode: str = "monitor"
    source_label: str = "Display"
    region_left: int = 0
    region_top: int = 0
    region_width: int = 1280
    region_height: int = 720
    mode: str = "normal"
    fps: int = 30
    scale_percent: int = 100
    timelapse_interval: float = 2.0
    timelapse_output_fps: int = 30
    quality: str = "Quality"
    encoder: str = "Auto"
    segment_seconds: int = 30
    countdown_seconds: int = 3
    min_free_mb: int = 1024
    capture_cursor: bool = True
    auto_recover: bool = True
    keep_session_segments: bool = True
    max_duration_minutes: int = 0
    live_focus_enabled: bool = False
    auto_focus_clicks: bool = False
    focus_zoom: float = 1.75
    focus_hold: float = 1.8
    focus_transition: float = 0.42
    focus_style: str = "Zoom"
    focus_easing: str = "Smooth"
    hide_during_recording: bool = True
    toolbar_x: int = -1
    toolbar_y: int = 18
    toolbar_display: str = "timer"
    video_fidelity_revision: int = 1

    @classmethod
    def load(cls) -> "AppConfig":
        path, imported_legacy = _settings_source()
        if not path.exists():
            return cls()
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            # FocusFlow Recorder 0.6.0 and older allowed camera-oriented defaults
            # and silently persisted reduced recording sizes. Keep the original
            # one-time fidelity repair when importing an older installation.
            if int(data.get("video_fidelity_revision", 0) or 0) < 1:
                data["scale_percent"] = 100
                if data.get("quality") in {None, "Performance", "Balanced"}:
                    data["quality"] = "Quality"
                data["video_fidelity_revision"] = 1
                migrated_fidelity = True
            else:
                migrated_fidelity = False
            valid = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
            config = cls(**valid)
            # Copy legacy FocusFlow settings into ResiliCapture's own data folder,
            # leaving the old files untouched for rollback/recovery.
            if imported_legacy or migrated_fidelity:
                try:
                    config.save()
                except OSError:
                    pass
            return config
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
