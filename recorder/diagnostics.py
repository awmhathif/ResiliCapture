from __future__ import annotations

import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import APP_DISPLAY_NAME, app_data_dir, legacy_app_data_dirs
from .encoder import available_encoders
from .utils import find_binary, run_hidden


MAX_LOG_BYTES = 512 * 1024


def _tail_text(path: Path, limit: int = MAX_LOG_BYTES) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit), os.SEEK_SET)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def sanitize_text(text: str, extra_paths: Iterable[str | Path] = ()) -> str:
    replacements: list[tuple[str, str]] = []
    home = str(Path.home())
    if home:
        replacements.append((home, "<HOME>"))
    data_dir = str(app_data_dir())
    if data_dir:
        replacements.append((data_dir, "<APP_DATA>"))
    for legacy_dir in legacy_app_data_dirs():
        raw_legacy = str(legacy_dir)
        if raw_legacy:
            replacements.append((raw_legacy, "<LEGACY_APP_DATA>"))
    for value in extra_paths:
        raw = str(value)
        if raw:
            replacements.append((raw, "<USER_PATH>"))
    result = text
    # Longest first prevents a parent path from leaving sensitive suffixes.
    for raw, replacement in sorted(set(replacements), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(raw, replacement)
        result = result.replace(raw.replace("\\", "/"), replacement)
    return result


def _binary_version(name: str) -> dict[str, str | bool]:
    path = find_binary(name)
    if not path:
        return {"available": False, "name": name}
    result = run_hidden([path, "-version"], timeout=8)
    first_line = (result.stdout or result.stderr).splitlines()
    return {
        "available": True,
        "name": name,
        "version": first_line[0] if first_line else "unknown",
    }


def create_diagnostic_report(
    destination: Path,
    *,
    app_version: str,
    save_dir: str | Path | None = None,
    session_dir: str | Path | None = None,
) -> Path:
    """Create a privacy-sanitized support bundle without recordings/screenshots."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    extra_paths = [value for value in (save_dir, session_dir) if value]
    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "app": APP_DISPLAY_NAME,
        "version": app_version,
        "python": sys.version.splitlines()[0],
        "platform": platform.platform(),
        "windows_release": platform.release(),
        "architecture": platform.machine(),
        "ffmpeg": _binary_version("ffmpeg"),
        "ffprobe": _binary_version("ffprobe"),
        "encoders_detected": [item.label for item in available_encoders()],
        "privacy": "No video frames, screenshots, or full user paths are included.",
    }

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(metadata, indent=2))
        data_dir = app_data_dir()
        for name in ("application.log", "native_crash.log", "runtime_state.json"):
            path = data_dir / name
            text = _tail_text(path)
            if text:
                archive.writestr(f"logs/{name}", sanitize_text(text, extra_paths))
        if session_dir:
            root = Path(session_dir)
            for name in ("session.log", "session.json", "stats.json", "finalization.json", "encoder.log", "events.jsonl"):
                text = _tail_text(root / name)
                if text:
                    archive.writestr(f"session/{name}", sanitize_text(text, extra_paths))
    return destination
