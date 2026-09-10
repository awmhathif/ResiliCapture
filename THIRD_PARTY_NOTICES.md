# Third-party notices

ResiliCapture is released under the MIT License. Runtime/build dependencies retain their own licenses.

## FFmpeg

ResiliCapture can launch separately distributed `ffmpeg` and `ffprobe` executables for H.264 encoding, concatenation, recovery, and verification. FFmpeg licensing depends on the exact build configuration and enabled codecs. Anyone distributing FFmpeg binaries with ResiliCapture must review that build's license, notices, and source-code obligations and include the required materials.

The repository intentionally does not treat an arbitrary locally installed FFmpeg build as part of ResiliCapture's MIT-licensed source.

## Python packages

See `requirements.txt` and `requirements-build.txt` for the Python dependencies used by the application and build process. Their respective upstream licenses apply.
