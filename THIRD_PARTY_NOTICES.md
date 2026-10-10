# Third-party notices

ResiliCapture is released under the MIT License. Runtime/build dependencies retain their own licenses.

## FFmpeg

ResiliCapture can launch separately distributed `ffmpeg` and `ffprobe` executables for H.264 encoding, concatenation, recovery, and verification. FFmpeg licensing depends on the exact build configuration and enabled codecs. Anyone distributing FFmpeg binaries with ResiliCapture must review that build's license, notices, and source-code obligations and include the required materials.

The repository intentionally does not treat an arbitrary locally installed FFmpeg build as part of ResiliCapture's MIT-licensed source.

Public portable ZIPs exclude FFmpeg binaries. The optional `setup_ffmpeg.bat` helper downloads FFmpeg **8.1.2 essentials** directly from [Gyan Doshi](https://www.gyan.dev/ffmpeg/builds/) on the user's computer, verifies the pinned upstream SHA-256 before extracting/executing it, and keeps the upstream license/readme in `bin/ffmpeg-notices`. This build includes libx264 and is GPLv3. The helper does not change PATH or require administrator rights.

Do not redistribute a folder populated by this helper as an official ZIP. A binary bundle requires the exact corresponding sources, dependency notices, and build/license materials; see [FFmpeg's legal information](https://ffmpeg.org/legal.html). Private builds may explicitly set `RESILICAPTURE_BUNDLE_FFMPEG=1`, but the public packager rejects bundled FFmpeg/FFprobe.

## Python packages

See `requirements.txt` and `requirements-build.txt` for the Python dependencies used by the application and build process. Their respective upstream licenses apply.
