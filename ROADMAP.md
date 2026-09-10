# ResiliCapture roadmap

ResiliCapture follows a reliability-first roadmap. A feature is not considered production-ready merely because it works once; recording and recovery behavior should remain predictable under interruption, low storage, encoder failure, and long runtime.

## 0.7.x — public beta

- Rebrand from FocusFlow Recorder to ResiliCapture with legacy settings/session compatibility.
- Public-facing README, repository metadata, release workflow, social preview, and contribution/security/privacy documentation.
- Continue field-testing long timelapses and finalization on real Windows machines.
- Fix regressions without changing the core recovery contract.

## 0.8.x — process isolation

- Move capture into a dedicated recorder process.
- Move long finalization into a dedicated/resumable finalizer process.
- Define an IPC/status protocol between UI, recorder, and finalizer.
- Reconnect a restarted UI to an active recorder where safe.
- Preserve recovery if the UI crashes or is force-closed.

## 0.9.x — release engineering

- 12–24 hour soak tests on Windows 10/11.
- Hardware matrix for NVENC, Intel QSV, AMD AMF, and software H.264 fallback.
- Sleep/lock/display-disconnect/monitor-change tests.
- External-drive removal, disk-full, and forced-shutdown tests.
- Signed Windows binary/installer strategy.
- Final FFmpeg redistribution/compliance policy.
- Reproducible release artifacts and provenance/attestation where practical.

## 1.0 release gate

1. A UI crash cannot silently destroy an active recording.
2. Interrupted sessions recover to the last safely sealed chunk.
3. Interrupted finalization can be resumed or safely restarted.
4. The app never reports “Saved and verified” for an invalid/missing output.
5. Failed finalization never deletes recoverable source chunks.
6. Long-session CPU/RAM/file-handle usage remains bounded in soak testing.
7. Windows release artifacts have a documented signing/distribution path.
8. Supported encoder paths have documented real-hardware test results.
