# Known limitations — 0.7.0

1. **Still a beta hardening release:** the recorder and finalizer still run inside the main Python process. A future production milestone should isolate them from the Tk GUI process.
2. **Video only:** microphone and system-audio recording are not implemented in this release.
3. **Window capture is rectangle-based:** another window covering the selected application can appear in the recording.
4. **One source at a time:** desktop and phone mirror cannot yet be composed simultaneously.
5. **Toolbar exclusion is best-effort:** `WDA_EXCLUDEFROMCAPTURE` depends on Windows version, graphics drivers, and capture backend behavior. Global hotkeys remain available if exclusion is unsupported.
6. **Live focus is permanent:** focus is baked into frames while recording and cannot be changed afterward. It is disabled by default.
7. **Focus selection briefly pauses capture:** the active segment is sealed before the selector opens to avoid corrupting footage.
8. **Windows cursor is reconstructed:** the cursor toggle draws a clean high-contrast arrow and does not reproduce every native cursor theme or animation.
9. **FFmpeg is strongly recommended:** without FFmpeg, ResiliCapture uses a larger MJPEG fallback and has reduced MP4 verification/recovery capabilities.
10. **FFmpeg redistribution needs license review:** the exact obligations depend on the FFmpeg build and enabled codecs. See `THIRD_PARTY_NOTICES.md`.
11. **Global hotkeys can be blocked:** security tools, elevated applications, or other programs may intercept F-key shortcuts.
12. **Tray support depends on the Windows shell/pystray backend:** if tray initialization fails, X falls back to taskbar minimization rather than hiding the application completely.
13. **No signed installer yet:** the repository builds a portable one-folder application; Authenticode signing/installer work remains before a 1.0 public production release.
14. **No prebuilt Windows executable is included in this source ZIP:** build on Windows with `build_windows.bat`.
15. **Long Windows soak testing still required:** 12–24 hour real-hardware tests and NVENC/QSV/AMF matrices are release-gate work before 1.0.
