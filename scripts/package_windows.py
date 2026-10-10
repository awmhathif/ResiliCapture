"""Package the complete one-folder app and verify its executable after extraction."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recorder.config import APP_VERSION

DOCUMENTS = (
    "START-HERE.txt", "setup_ffmpeg.bat", "setup_ffmpeg.ps1", "LICENSE.txt",
    "THIRD_PARTY_NOTICES.md", "PRIVACY.md", "KNOWN_LIMITATIONS.md", "SUPPORT.md",
)


def smoke_check(exe: Path, *, require_ffmpeg: bool = False, isolated: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="ResiliCapture-smoke-") as tmp:
        report = Path(tmp) / "report.json"
        command = [str(exe.resolve()), "--self-test", "--report", str(report)]
        if require_ffmpeg:
            command.append("--require-ffmpeg")
        environment = os.environ.copy()
        if isolated:
            environment["PATH"] = str(Path(environment.get("SystemRoot", "C:/Windows")) / "System32")
        completed = subprocess.run(command, cwd=tmp, timeout=120, env=environment,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not report.is_file():
            raise RuntimeError(f"Packaged EXE produced no smoke report (exit {completed.returncode})")
        details = json.loads(report.read_text(encoding="utf-8"))
        if completed.returncode != 0 or not details.get("ok"):
            raise RuntimeError(f"Packaged EXE smoke failed: {details}")
        return details


def create_package(folder: Path, output: Path) -> Path:
    if not (folder / "ResiliCapture.exe").is_file() or not (folder / "_internal").is_dir():
        raise RuntimeError("The complete PyInstaller one-folder app is required, including _internal")
    # Public archives keep FFmpeg as a separate user download until redistribution is finalized.
    if any(folder.rglob("ffmpeg.exe")) or any(folder.rglob("ffprobe.exe")):
        raise RuntimeError("Public ZIP must not contain locally installed FFmpeg/FFprobe")
    for name in DOCUMENTS:
        shutil.copy2(ROOT / name, folder / name)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"ResiliCapture-{APP_VERSION}-Windows.zip"
    staging = archive.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    package.write(path, Path("ResiliCapture") / path.relative_to(folder))
        # Test the delivered ZIP, from a folder with spaces and a different working directory.
        with tempfile.TemporaryDirectory(prefix="ResiliCapture extracted ") as tmp:
            with zipfile.ZipFile(staging) as package:
                package.extractall(tmp)
            details = smoke_check(Path(tmp) / "ResiliCapture" / "ResiliCapture.exe", isolated=True)
        staging.replace(archive)
    finally:
        staging.unlink(missing_ok=True)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    (output / "package-smoke.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=ROOT / "dist" / "ResiliCapture")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--require-ffmpeg", action="store_true")
    args = parser.parse_args()
    if args.check_only:
        print(json.dumps(smoke_check(args.folder / "ResiliCapture.exe", require_ffmpeg=args.require_ffmpeg), indent=2))
    else:
        print(create_package(args.folder, args.output))
