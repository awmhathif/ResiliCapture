# ResiliCapture 0.7.0 Beta

This is the first public-beta release under the **ResiliCapture** name, continuing FocusFlow Recorder 0.6.x.

## Highlights

- Recoverable sealed recording chunks for long sessions.
- Verified MP4 saves before success is reported.
- Fast stream-copy finalization for ordinary compatible H.264 sessions.
- Adaptive long-timelapse chunking.
- Close-to-tray lifecycle with recording-safe explicit Exit.
- Native-resolution, screen-text-oriented quality defaults.
- Append-only segment/event journals and low-disk finalization protection.
- Privacy-sanitized diagnostics for bug reports.
- Legacy FocusFlow settings import and `.focusflow_sessions` recovery scanning.

## Beta notice

ResiliCapture 0.7.0 is not the 1.0 production claim. The major remaining architecture milestone is separating capture/finalization from the GUI process, followed by 12–24 hour Windows soak tests and a real hardware encoder matrix.

## FFmpeg

FFmpeg is strongly recommended for H.264 recording, verification, and recovery. The ZIP includes a one-click helper that downloads a pinned, SHA-256 verified FFmpeg 8.1.2 essentials build directly from gyan.dev into the extracted app folder. FFmpeg binaries are downloaded separately and are GPLv3; see `THIRD_PARTY_NOTICES.md`.

## Download and run

1. Download **ResiliCapture-0.7.0-Windows.zip** under Assets (Windows 10/11, 64-bit Intel/AMD).
2. Right-click → **Extract All** and open the extracted **ResiliCapture** folder.
3. Double-click **setup_ffmpeg.bat** once (internet required, about 104 MB).
4. Double-click **ResiliCapture.exe** and choose where to save recordings.

No Python, administrator rights, or installer is required. Keep the EXE and `_internal` folder together. **Do not download only ResiliCapture.exe** or use the Source code ZIP for installation.

The accompanying `.zip.sha256` contains the ZIP's SHA-256 checksum. The beta is unsigned and may show a Windows publisher/SmartScreen warning. Verify the source/checksum before deciding to run it; do not disable Windows security. Microphone/system audio is not implemented yet.
