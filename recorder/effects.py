from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(slots=True)
class FocusSnapshot:
    center_x: float = 0.5
    center_y: float = 0.5
    zoom: float = 1.0
    spotlight: float = 0.0
    region_x: float = 0.0
    region_y: float = 0.0
    region_width: float = 1.0
    region_height: float = 1.0
    active: bool = False


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


def _smoothstep(value: float) -> float:
    t = _clamp(value, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class LiveFocusController:
    """Thread-safe, non-editor focus effect for frames written during recording.

    The controller stores only a start and target transform. The worker asks for
    a snapshot using active recording time, so pause time never advances an
    animation. Focus is therefore deterministic and is baked into the final
    recording instead of depending on a later editor/export step.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._from = FocusSnapshot()
        self._target = FocusSnapshot()
        self._started_at = 0.0
        self._duration = 0.35
        self._requested_active = False

    def _snapshot_unlocked(self, at: float) -> FocusSnapshot:
        if self._duration <= 0:
            progress = 1.0
        else:
            progress = _smoothstep((float(at) - self._started_at) / self._duration)
        start = self._from
        target = self._target
        return FocusSnapshot(
            center_x=start.center_x + (target.center_x - start.center_x) * progress,
            center_y=start.center_y + (target.center_y - start.center_y) * progress,
            zoom=start.zoom + (target.zoom - start.zoom) * progress,
            spotlight=start.spotlight + (target.spotlight - start.spotlight) * progress,
            region_x=start.region_x + (target.region_x - start.region_x) * progress,
            region_y=start.region_y + (target.region_y - start.region_y) * progress,
            region_width=start.region_width + (target.region_width - start.region_width) * progress,
            region_height=start.region_height + (target.region_height - start.region_height) * progress,
            active=self._requested_active or progress < 1.0,
        )

    def snapshot(self, at: float) -> FocusSnapshot:
        with self._lock:
            return self._snapshot_unlocked(at)

    def activate(
        self,
        *,
        at: float,
        region: dict[str, float],
        zoom: float,
        transition: float,
        style: str,
    ) -> None:
        with self._lock:
            current = self._snapshot_unlocked(at)
            x = _clamp(region.get("x", 0.0), 0.0, 1.0)
            y = _clamp(region.get("y", 0.0), 0.0, 1.0)
            width = _clamp(region.get("width", 1.0), 0.02, 1.0)
            height = _clamp(region.get("height", 1.0), 0.02, 1.0)
            if x + width > 1.0:
                x = 1.0 - width
            if y + height > 1.0:
                y = 1.0 - height
            target_zoom = _clamp(zoom, 1.05, 4.0)
            style_key = str(style).casefold()
            spotlight = 0.42 if "spotlight" in style_key else 0.0
            if style_key == "spotlight":
                target_zoom = 1.0
            self._from = current
            self._target = FocusSnapshot(
                center_x=x + width / 2.0,
                center_y=y + height / 2.0,
                zoom=target_zoom,
                spotlight=spotlight,
                region_x=x,
                region_y=y,
                region_width=width,
                region_height=height,
                active=True,
            )
            self._started_at = float(at)
            self._duration = max(0.05, float(transition))
            self._requested_active = True

    def clear(self, *, at: float, transition: float) -> None:
        with self._lock:
            current = self._snapshot_unlocked(at)
            self._from = current
            self._target = FocusSnapshot()
            self._started_at = float(at)
            self._duration = max(0.05, float(transition))
            self._requested_active = False

    @property
    def requested_active(self) -> bool:
        with self._lock:
            return self._requested_active


def apply_focus_effect(frame: np.ndarray, snapshot: FocusSnapshot) -> np.ndarray:
    """Apply spotlight and/or animated crop zoom to a BGR frame."""
    if frame.size == 0:
        return frame
    height, width = frame.shape[:2]
    output = frame

    if snapshot.spotlight > 0.001:
        x1 = int(_clamp(snapshot.region_x, 0.0, 1.0) * width)
        y1 = int(_clamp(snapshot.region_y, 0.0, 1.0) * height)
        x2 = int(_clamp(snapshot.region_x + snapshot.region_width, 0.0, 1.0) * width)
        y2 = int(_clamp(snapshot.region_y + snapshot.region_height, 0.0, 1.0) * height)
        dimmed = cv2.convertScaleAbs(frame, alpha=max(0.18, 1.0 - snapshot.spotlight), beta=0)
        if x2 > x1 and y2 > y1:
            dimmed[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
        output = dimmed

    zoom = max(1.0, float(snapshot.zoom))
    if zoom <= 1.001:
        return output

    crop_width = max(2, int(width / zoom))
    crop_height = max(2, int(height / zoom))
    center_x = int(_clamp(snapshot.center_x, 0.0, 1.0) * width)
    center_y = int(_clamp(snapshot.center_y, 0.0, 1.0) * height)
    left = max(0, min(center_x - crop_width // 2, width - crop_width))
    top = max(0, min(center_y - crop_height // 2, height - crop_height))
    crop = output[top : top + crop_height, left : left + crop_width]
    if crop.size == 0:
        return output
    return cv2.resize(crop, (width, height), interpolation=cv2.INTER_CUBIC)
