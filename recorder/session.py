from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import APP_DISPLAY_NAME, SESSION_DIR_NAME
from .models import RecordingOptions, RecordingState


class _PerWriteFileHandler(logging.Handler):
    """Logging handler that never keeps the session log file open.

    Windows does not allow deleting a file while another process still has an
    open handle to it. Tests and recovery tooling frequently create temporary
    session folders, so keeping a FileHandler alive can make those folders
    undeletable until interpreter shutdown. Opening the log only for each emit
    avoids that lock while preserving the same on-disk log format.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = Path(path)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            message = self.format(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
                handle.flush()
        except Exception:
            self.handleError(record)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    # A power loss can leave only the final append incomplete.
                    # Earlier journal entries remain valid and recoverable.
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        return []
    return records


def load_segment_records(session_dir: Path) -> list[dict[str, Any]]:
    """Load sealed-segment metadata from the v3 journal or legacy manifest."""
    journal = _read_jsonl(session_dir / "segments.jsonl")
    if journal:
        return journal
    try:
        data = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return [item for item in data.get("segments", []) if isinstance(item, dict)]


class RecordingSession:
    """Crash-safe project manifest.

    Every mutation is written through a temporary file and atomically replaced.
    Focus markers are stored as normalized coordinates, so they survive output
    scaling and can be edited after recording.
    """

    def __init__(self, options: RecordingOptions, existing_dir: Path | None = None) -> None:
        self.options = options
        self._lock = threading.RLock()
        self._last_stats_persist = 0.0
        self._last_finalization_persist = 0.0
        self._segments_since_checkpoint = 0
        if existing_dir is None:
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.session_id = f"{stamp}_{uuid.uuid4().hex[:8]}"
            self.root = Path(options.save_dir) / SESSION_DIR_NAME / self.session_id
            self.root.mkdir(parents=True, exist_ok=False)
            self.manifest: dict[str, Any] = {
                "version": 3,
                "app": APP_DISPLAY_NAME,
                "session_id": self.session_id,
                "created_utc": utc_now(),
                "updated_utc": utc_now(),
                "state": RecordingState.PREPARING.value,
                "options": options.to_dict(),
                "segment_count": 0,
                "segment_bytes": 0,
                "focus_markers": [],
                "click_markers": [],
                "final_output": None,
                "finalization": None,
                "error": None,
                "stats": {},
            }
        else:
            self.root = existing_dir
            self.manifest = json.loads((self.root / "session.json").read_text(encoding="utf-8"))
            self.session_id = str(self.manifest["session_id"])
            self.manifest.setdefault("version", 2)
            self.manifest.setdefault("focus_markers", [])
            self.manifest.setdefault("click_markers", [])
            legacy_segments = [item for item in self.manifest.get("segments", []) if isinstance(item, dict)]
            self.manifest.setdefault("segment_count", len(legacy_segments))
            self.manifest.setdefault("segment_bytes", sum(int(item.get("bytes", 0) or 0) for item in legacy_segments))
            self.manifest.setdefault("finalization", None)

        self.log_path = self.root / "session.log"
        self.logger = logging.getLogger(f"resilicapture.{self.session_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = _PerWriteFileHandler(self.log_path)
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            self.logger.addHandler(handler)
        self._write_manifest()

    @property
    def manifest_path(self) -> Path:
        return self.root / "session.json"

    @property
    def segments_path(self) -> Path:
        return self.root / "segments.jsonl"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def stats_path(self) -> Path:
        return self.root / "stats.json"

    @property
    def finalization_path(self) -> Path:
        return self.root / "finalization.json"

    @property
    def segment_count(self) -> int:
        journal_count = len(_read_jsonl(self.segments_path))
        if journal_count:
            return journal_count
        return int(self.manifest.get("segment_count", len(self.manifest.get("segments", []))) or 0)

    @property
    def segment_bytes(self) -> int:
        records = _read_jsonl(self.segments_path)
        if records:
            return sum(int(item.get("bytes", 0) or 0) for item in records)
        return int(self.manifest.get("segment_bytes", 0) or 0)

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _write_stats(self) -> None:
        self._atomic_json(self.stats_path, dict(self.manifest.get("stats", {})))

    def _write_finalization(self, payload: dict[str, Any]) -> None:
        self._atomic_json(self.finalization_path, payload)

    def _record_event(self, state: str, message: str) -> None:
        self._append_jsonl(self.events_path, {"time": utc_now(), "state": state, "message": message})

    def _write_manifest(self) -> None:
        with self._lock:
            self.manifest["updated_utc"] = utc_now()
            self._atomic_json(self.manifest_path, self.manifest)

    def set_state(self, state: RecordingState, message: str | None = None) -> None:
        with self._lock:
            self.manifest["state"] = state.value
            if message:
                self._record_event(state.value, message)
                self.logger.info("%s: %s", state.value, message)
            self._write_manifest()

    def add_segment(self, path: Path, frames: int, duration: float, backend: str, codec: str) -> None:
        with self._lock:
            record = {
                "name": path.name,
                "frames": int(frames),
                "duration": round(float(duration), 3),
                "bytes": path.stat().st_size if path.exists() else 0,
                "backend": backend,
                "codec": codec,
                "completed_utc": utc_now(),
            }
            self._append_jsonl(self.segments_path, record)
            self.manifest["segment_count"] = int(self.manifest.get("segment_count", 0) or 0) + 1
            self.manifest["segment_bytes"] = int(self.manifest.get("segment_bytes", 0) or 0) + int(record["bytes"])
            self._segments_since_checkpoint += 1
            # The segment journal is already durable. Checkpoint aggregate counts
            # periodically so session.json stays tiny even for all-day captures.
            if self._segments_since_checkpoint >= 10:
                self._write_manifest()
                self._segments_since_checkpoint = 0

    def add_focus_marker(
        self,
        *,
        start: float,
        region: dict[str, float],
        zoom: float,
        duration: float,
        transition: float,
        style: str = "Zoom",
        easing: str = "Smooth",
        source: str = "manual",
    ) -> dict[str, Any]:
        marker = {
            "id": uuid.uuid4().hex[:10],
            "start": round(max(0.0, float(start)), 3),
            "duration": round(max(0.15, float(duration)), 3),
            "transition": round(max(0.0, min(float(transition), float(duration) / 2)), 3),
            "zoom": round(max(1.0, min(float(zoom), 4.0)), 3),
            "style": style,
            "easing": easing,
            "source": source,
            "region": {
                "x": round(max(0.0, min(float(region["x"]), 1.0)), 6),
                "y": round(max(0.0, min(float(region["y"]), 1.0)), 6),
                "width": round(max(0.01, min(float(region["width"]), 1.0)), 6),
                "height": round(max(0.01, min(float(region["height"]), 1.0)), 6),
            },
        }
        with self._lock:
            self.manifest["focus_markers"].append(marker)
            self.manifest["focus_markers"].sort(key=lambda item: float(item.get("start", 0.0)))
            self.logger.info("Focus marker added: %s", marker)
            self._write_manifest()
        return marker

    def start_focus_marker(
        self,
        *,
        start: float,
        region: dict[str, float],
        zoom: float,
        transition: float,
        style: str = "Zoom",
        easing: str = "Smooth",
        source: str = "manual-span",
    ) -> dict[str, Any]:
        """Start an open-ended focus span.

        The marker is immediately journaled so a crash still preserves the
        selected region. ``finish_focus_marker`` later sets the real duration
        and gives the return-to-full-screen animation its own exit time.
        """
        marker = self.add_focus_marker(
            start=start,
            region=region,
            zoom=zoom,
            duration=max(0.25, float(transition) * 2.0 + 0.05),
            transition=transition,
            style=style,
            easing=easing,
            source=source,
        )
        with self._lock:
            marker["open"] = True
            marker["focus_end"] = None
            self._write_manifest()
        return marker

    def finish_focus_marker(self, marker_id: str, *, end_at: float) -> dict[str, Any] | None:
        """Close a focus span and animate back after the user's end action."""
        with self._lock:
            for marker in self.manifest["focus_markers"]:
                if marker.get("id") != marker_id:
                    continue
                start = max(0.0, float(marker.get("start", 0.0)))
                transition = max(0.0, float(marker.get("transition", 0.4)))
                focus_end = max(start, float(end_at))
                # The existing renderer fades out during the final transition
                # of a marker. Adding transition to the duration means the
                # zoom-out begins when End focus is pressed, not before it.
                marker["focus_end"] = round(focus_end, 3)
                marker["duration"] = round(max(0.2, focus_end - start + transition), 3)
                marker["open"] = False
                self.logger.info("Focus marker finished: %s", marker)
                self._write_manifest()
                return marker
        return None

    def add_click_marker(self, *, at: float, x: float, y: float, button: str) -> None:
        with self._lock:
            self.manifest["click_markers"].append(
                {
                    "at": round(max(0.0, float(at)), 3),
                    "x": round(max(0.0, min(float(x), 1.0)), 6),
                    "y": round(max(0.0, min(float(y), 1.0)), 6),
                    "button": str(button),
                }
            )
            self._write_manifest()

    def update_focus_marker(self, marker_id: str, **changes: Any) -> bool:
        with self._lock:
            for marker in self.manifest["focus_markers"]:
                if marker.get("id") == marker_id:
                    for key in ("start", "duration", "transition", "zoom", "style", "easing", "region"):
                        if key in changes:
                            marker[key] = changes[key]
                    self.manifest["focus_markers"].sort(key=lambda item: float(item.get("start", 0.0)))
                    self._write_manifest()
                    return True
        return False

    def remove_focus_marker(self, marker_id: str) -> bool:
        with self._lock:
            before = len(self.manifest["focus_markers"])
            self.manifest["focus_markers"] = [m for m in self.manifest["focus_markers"] if m.get("id") != marker_id]
            changed = len(self.manifest["focus_markers"]) != before
            if changed:
                self._write_manifest()
            return changed

    def update_stats(self, force: bool = False, **stats: Any) -> None:
        """Persist live stats separately from the session manifest.

        A small stats.json checkpoint can be replaced every five seconds without
        repeatedly serializing focus/session metadata. Significant state changes
        still checkpoint session.json.
        """
        with self._lock:
            self.manifest["stats"].update(stats)
            now = time.monotonic()
            if force or now - self._last_stats_persist >= 5.0:
                self._write_stats()
                self._last_stats_persist = now
                if force:
                    self._write_manifest()

    def update_finalization(self, *, stage: str, percent: float, message: str, output: str | None = None, force: bool = False) -> None:
        with self._lock:
            payload = {
                "stage": str(stage),
                "percent": round(max(0.0, min(100.0, float(percent))), 2),
                "message": str(message),
                "output": output,
                "updated_utc": utc_now(),
            }
            self.manifest["finalization"] = payload
            now = time.monotonic()
            if force or now - self._last_finalization_persist >= 0.75:
                self._write_finalization(payload)
                self._last_finalization_persist = now

    def fail(self, error: str) -> None:
        with self._lock:
            self.manifest["state"] = RecordingState.FAILED.value
            self.manifest["error"] = error
            self._record_event("failed", error)
            self.logger.error("%s", error)
            self._write_manifest()

    def complete(self, output: Path) -> None:
        with self._lock:
            self.manifest["state"] = RecordingState.COMPLETED.value
            self.manifest["final_output"] = str(output)
            self.manifest["error"] = None
            completed_finalization = {
                "stage": "completed",
                "percent": 100.0,
                "message": "Saved and verified",
                "output": str(output),
                "updated_utc": utc_now(),
            }
            self.manifest["finalization"] = completed_finalization
            self._write_finalization(completed_finalization)
            self._record_event("completed", str(output))
            self.logger.info("Completed: %s", output)
            self._write_manifest()

    @classmethod
    def load(cls, path: Path) -> "RecordingSession":
        data = json.loads((path / "session.json").read_text(encoding="utf-8"))
        options_data = dict(data["options"])
        valid = {k: v for k, v in options_data.items() if k in RecordingOptions.__dataclass_fields__}
        options = RecordingOptions(**valid)
        return cls(options=options, existing_dir=path)
