# Contributing to ResiliCapture

Contributions are welcome. Reliability changes should preserve ResiliCapture's central rule: **never report a recording as successfully saved until the final media has been verified, and never delete recoverable source segments because finalization failed.**

## Development

1. Use Python 3.11–3.13 on Windows.
2. Install FFmpeg and FFprobe or place them in `bin/`.
3. Run `install_dev.bat` or install `requirements.txt` manually.
4. Run `python -m unittest discover -s tests -v` before opening a pull request.
5. Run `python -m compileall -q app.py recorder ui platform_tools tests`.

Changes to capture, encoding, finalization, recovery, tray lifecycle, or storage handling should include regression tests. For long-session changes, include an explanation of how the implementation scales with thousands of frames/segments.

Do not add telemetry, network upload, or collection of window titles/file paths to diagnostics without a clear privacy review and documentation update.
