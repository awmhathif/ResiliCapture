from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class RecordingState(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    COUNTDOWN = "countdown"
    RECORDING = "recording"
    PAUSED = "paused"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    RECOVERING = "recovering"
    FAILED = "failed"


@dataclass(slots=True)
class RecordingOptions:
    save_dir: str
    monitor_index: int
    source_mode: str
    region: dict[str, int]
    mode: str
    fps: int
    scale: float
    timelapse_interval: float
    timelapse_output_fps: int
    quality: str
    encoder: str
    segment_seconds: int
    min_free_mb: int
    capture_cursor: bool
    keep_session_segments: bool
    countdown_seconds: int = 0
    max_duration_seconds: float = 0.0
    live_focus_enabled: bool = False
    auto_focus_clicks: bool = False
    focus_zoom: float = 1.75
    focus_hold: float = 1.8
    focus_transition: float = 0.42
    focus_style: str = "Zoom"
    focus_easing: str = "Smooth"
    source_label: str = "Display"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RecorderEvent:
    kind: str
    payload: dict[str, Any]
