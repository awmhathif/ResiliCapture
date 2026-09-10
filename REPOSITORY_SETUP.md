# GitHub repository setup

Recommended repository name: **ResiliCapture**

An exact-name web/GitHub search performed during this release prep did not surface an obvious existing software project using “ResiliCapture”. That is a practical collision check, **not trademark/legal clearance**; do a jurisdiction-appropriate trademark check before building a large brand around it.

## About section

**Description**

> Local-first Windows screen recorder for reliable long recordings and timelapses, with recoverable segments and verified saves.

**Suggested topics**

`screen-recorder`, `windows`, `python`, `ffmpeg`, `timelapse`, `screen-capture`, `video-recording`, `local-first`, `privacy`, `recovery`, `pyinstaller`, `h264`

## Repository settings

- Public repository.
- Enable Issues and Discussions if you want user support in GitHub.
- Enable Dependabot alerts/security updates.
- Enable private vulnerability reporting if available.
- Protect the default branch and require the `tests` workflow before merge.
- Upload `docs/social-preview.png` under **Settings → General → Social preview**.
- Keep the MIT license detected from `LICENSE.txt`.

## First public release

Recommended tag/title:

- Tag: `v0.7.0-beta`
- Title: `ResiliCapture 0.7.0 Beta — first public beta`

Attach the Windows portable ZIP and its `.sha256` file produced by `build_windows.bat` or the release workflow. State clearly whether FFmpeg is bundled in that exact artifact.

Before announcing broadly, replace/add UI screenshots with captures taken from the actual Windows release binary and verify that no usernames, private paths, browser data, tokens, or personal content are visible.

## Launch positioning

Primary message:

> Recording failure should not mean losing the recording.

Supporting message:

> ResiliCapture is a local-first Windows screen recorder for long recordings and timelapses, using recoverable sealed chunks and verified final saves.
