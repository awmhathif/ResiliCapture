# Changelog

## 0.7.0 — ResiliCapture public beta

- Renamed FocusFlow Recorder to **ResiliCapture** to avoid a public-project naming collision and align the product with its reliability/recovery focus.
- Added first-run import of legacy FocusFlow Recorder settings without deleting or moving the old app-data folder.
- New sessions are stored under `.resilicapture_sessions`; Recovery now scans both that folder and legacy `.focusflow_sessions`.
- Renamed the executable, PyInstaller target, Windows version metadata, diagnostics, tray labels, build outputs, and package metadata to ResiliCapture.
- Rewrote the README around the core promise: recording failure should not mean losing the recording.
- Added a clean current UI preview and a 1280×640 GitHub social-preview image with no private user paths/content.
- Added `ROADMAP.md`, `SUPPORT.md`, `REPOSITORY_SETUP.md`, a pull-request safety checklist, public-beta release notes, and a tagged GitHub prerelease workflow.
- Added build provenance/attestation support in the tagged release workflow where GitHub supports it.
- Added regression coverage for legacy settings import and legacy recovery-session discovery.
- Retains the 0.6.1 screen-text quality fix: native 100% + Quality defaults, sharper H.264 presets, Lanczos downscaling, and CRF 15 recovery transcodes.

## 0.6.1 — FocusFlow Recorder

- Fixed visibly soft/blurry desktop text by replacing camera-oriented H.264 quality values with screen-recording-oriented presets.
- Changed the default for fresh installations from Balanced to Quality.
- Added a one-time upgrade migration that restores legacy installs to 100% native size and upgrades old Performance/Balanced defaults to Quality; users can deliberately select a reduced size again afterward.
- Balanced now uses CRF/CQ 18, Quality 15, Near lossless 10; Performance is also sharper than before.
- Increased fallback/recovery transcode quality from CRF 21 to CRF 15 so a compatibility rebuild does not noticeably soften the recording.
- Changed reduced-resolution desktop scaling from INTER_AREA to Lanczos to preserve glyph and UI edge detail.
- Added a live output-resolution/sharpness indicator and an explicit warning when recording below 100% native size.
- Completion status now shows the verified output resolution and selected quality preset.
- Kept standard yuv420p output for broad player/editor compatibility; normal finalization remains stream-copy with no second-generation encode.

## 0.6.0 — FocusFlow Recorder

- Changed the main-window close button to minimize FocusFlow Recorder to the system tray instead of terminating the application.
- Added tray actions for Show, Pause / Resume, Stop & Save, Open Recordings, and explicit Exit FocusFlow Recorder.
- Explicit Exit during recording now offers to stop/save first and exits only after the final video is verified.
- Tray-minimized finalization no longer reopens the window on each progress event; completion can notify through the tray.
- Added append-only `segments.jsonl` and `events.jsonl` journals so long recordings do not grow one giant session manifest.
- Moved high-frequency live statistics into an atomic `stats.json` checkpoint and finalization progress into `finalization.json`.
- Added tolerant journal loading so a truncated final JSONL append after a power loss does not hide earlier sealed segments.
- Added a finalization disk-space preflight that preserves sealed segments instead of starting a final output that obviously cannot fit.
- Added a low-finalization-headroom warning during recording.
- Final MP4 verification now optionally decodes frames near the beginning and end before reporting success.
- Successful mixed-codec recovery removes derived normalization workspace after final verification.
- Added privacy-sanitized diagnostic ZIP creation for GitHub issue reports; recordings and screenshots are never included.
- Added GitHub Actions tests/build smoke checks, Dependabot configuration, bug/feature templates, `SECURITY.md`, `PRIVACY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and third-party notices.
- Added `pyproject.toml` metadata and bounded dependency ranges for more predictable builds.
- Disabled UPX in the PyInstaller release build and added automated tests plus SHA-256 generation to `build_windows.bat`.
- Expanded the automated suite to 21 tests.

## 0.5.0 — FocusFlow Recorder

- Added a fast finalization path that avoids per-segment FFprobe calls for normal sealed MKV sessions.
- Added staged finalization progress events and visible saving status after Stop.
- Restored the main window immediately when saving begins so long finalization no longer looks like the app disappeared.
- Added adaptive timelapse chunk duration and a minimum normal-recording chunk duration to reduce process churn on long sessions.
- Replaced recursive once-per-second session size scans with incremental sealed/current-part byte accounting.
- Throttled live-stat manifest checkpoint writes to every five seconds while preserving forced final state writes.
- Consolidated per-segment FFmpeg logs into one session-level encoder log.
- Changed runtime fallback order to hardware H.264 → software H.264 → MJPEG.
- Added unclean-shutdown detection, `threading.excepthook`, Tk callback logging, and `faulthandler` native crash logs.
- Changed the default recovery segment setting for new installations from 5 to 30 seconds.
- Added long-session scaling tests; 14 automated tests pass in the validation environment.

## 0.4.0 — FocusFlow Recorder

- Repositioned the product as a flexible screen recorder rather than a focus editor.
- Restored normal and timelapse modes in the main interface.
- Added timelapse capture interval and independent playback FPS controls.
- Added speed-up and real-hour-to-output-duration estimates.
- Removed the live screen preview.
- Replaced the wide floating bar with a compact icon-only controller.
- Added Pause, optional Focus, Screenshot, and Stop to the floating bar.
- Added timer/file-size switching and persistent toolbar position.
- Disabled Focus by default.
- Replaced metadata-only focus with a live baked-in zoom/spotlight effect.
- Added pause acknowledgement before focus selection to remove timing races.
- Removed the focus editor and automatic editor launch.
- Added countdown, duration limit, segment length, free-space reserve, and recovery retention controls.
- Added Windows cursor reconstruction while avoiding MSS's read-only cursor property.
- Added timelapse and live-focus automated tests.
- Updated clean white interface previews.

## 0.3.0 — FocusFlow Recorder

- Added a draggable floating recording bar.
- Removed the live preview.
- Added manual focus start/end metadata and editor workflow.
- Added capture exclusion for the toolbar.

## 0.2.1 — FocusFlow Recorder

- Fixed the MSS read-only `with_cursor` assignment crash.

## 0.2.0 — FocusFlow Recorder

- Added the initial white recorder and focus editor interfaces.
