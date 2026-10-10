# Windows portable releases

The PyInstaller EXE is a **one-folder build**, not a standalone executable.
It depends on `_internal` (Python, Tcl/Tk, native libraries and assets). Publishing
just `ResiliCapture.exe` creates a broken download on a clean computer.

## Build and verify

Use Windows and 64-bit Python 3.11–3.13. Run `build_windows.bat`.
The shared `scripts/package_windows.py` packages the complete folder, setup helper,
help/privacy/license files and tests the EXE from the extracted ZIP in a temporary
directory containing spaces, with PATH limited to Windows system tools. Failure
to launch, load Tk/assets, or encode/decode synthetic video fails packaging.
The release workflow separately exercises H.264 finalization and decoded MP4
verification using its test-only FFmpeg installation.

Public ZIPs exclude FFmpeg binaries. Users can run `setup_ffmpeg.bat` to download
the pinned upstream build for their own installation. Do not upload a local
folder after installing FFmpeg into it; the public packager rejects that bundle.

Outputs:

- `dist/ResiliCapture-0.7.0-Windows.zip`
- `dist/ResiliCapture-0.7.0-Windows.zip.sha256`
- `dist/package-smoke.json` (local verification evidence)

For the full executable H.264 check, install tools into an extracted copy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\dist\ResiliCapture\setup_ffmpeg.ps1
.\.venv\Scripts\python.exe scripts\package_windows.py --check-only --require-ffmpeg
```

Keep this check copy separate from the archive you upload. Automated checks use
temporary synthetic frames, not desktop capture, existing recordings or user
settings. Real desktop/tray/hotkey checks and long Windows soak tests are separate.

## Publish

Review the ZIP, checksum, smoke report and version-specific release notes first.
After publication is authorized, upload **both the ZIP and checksum** to the beta
release, use `docs/release-notes-v0.7.0-beta.md` for the description, and mark it as
a **prerelease**. Remove the incomplete standalone EXE asset once the complete ZIP
is available. Use the release tag link in the README because `/releases/latest`
does not select prereleases.

The release workflow handles versioned beta tag pushes and manual dispatch. It
can upload the complete ZIP/checksum into an existing release and update the
description/prerelease status; it does not remove old assets automatically.

Do not claim Authenticode signing, a tested hardware matrix or 12–24 hour soak
coverage until those gates are completed. This is a portable beta release.
