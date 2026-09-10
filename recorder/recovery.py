from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import LEGACY_SESSION_DIR_NAMES, SESSION_DIR_NAME
from .encoder import finalize_segments, verify_media
from .models import RecordingState
from .session import RecordingSession


@dataclass(slots=True)
class RecoveryItem:
    session_dir: Path
    session_id: str
    state: str
    created_utc: str
    segment_count: int
    bytes_total: int
    error: str


def session_roots(save_dir: str | Path) -> list[Path]:
    """Return current and legacy recovery sessions without moving user data."""
    found: list[Path] = []
    base = Path(save_dir)
    for dirname in (SESSION_DIR_NAME, *LEGACY_SESSION_DIR_NAMES):
        root = base / dirname
        if not root.exists():
            continue
        found.extend(path for path in root.iterdir() if path.is_dir() and (path / "session.json").exists())
    return found


def scan_recoverable(save_dir: str | Path) -> list[RecoveryItem]:
    items: list[RecoveryItem] = []
    for session_dir in session_roots(save_dir):
        try:
            data = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            state = str(data.get("state", "unknown"))
            final_output = data.get("final_output")
            if state == RecordingState.COMPLETED.value and final_output and Path(final_output).exists():
                continue
            segments = [*session_dir.glob("segment_*.mkv"), *session_dir.glob("segment_*.avi")]
            # Try to rescue a fully readable active segment.
            for part in [*session_dir.glob("segment_*.part.mkv"), *session_dir.glob("segment_*.part.avi")]:
                valid, _ = verify_media(part)
                if valid:
                    completed = part.with_name(part.name.replace(".part", ""))
                    part.replace(completed)
                    segments.append(completed)
            if not segments:
                continue
            items.append(
                RecoveryItem(
                    session_dir=session_dir,
                    session_id=str(data.get("session_id", session_dir.name)),
                    state=state,
                    created_utc=str(data.get("created_utc", "")),
                    segment_count=len(segments),
                    bytes_total=sum(path.stat().st_size for path in segments if path.exists()),
                    error=str(data.get("error") or ""),
                )
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda item: item.created_utc, reverse=True)


def recover_session(session_dir: Path, output_dir: Path | None = None) -> Path:
    session = RecordingSession.load(session_dir)
    session.set_state(RecordingState.RECOVERING, "Manual recovery started.")
    options = session.options
    output_root = output_dir or Path(options.save_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = output_root / f"recovered_{stamp}_{session.session_id[-8:]}.mp4"
    fps = float(options.timelapse_output_fps if options.mode == "timelapse" else options.fps)
    final = finalize_segments(session_dir, output, fps)
    session.complete(final)
    return final


def delete_session(session_dir: Path) -> None:
    shutil.rmtree(session_dir, ignore_errors=False)
