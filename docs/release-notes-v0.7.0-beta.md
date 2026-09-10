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

FFmpeg is strongly recommended for H.264 recording, verification, and recovery. Check the release artifact notes to see whether the exact build you downloaded bundles FFmpeg. Redistribution obligations depend on the FFmpeg build configuration; see `THIRD_PARTY_NOTICES.md`.
