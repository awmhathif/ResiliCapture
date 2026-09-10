from __future__ import annotations

import queue
import tempfile
import unittest
from unittest.mock import patch

from recorder.encoder import finalize_segments
from recorder.models import RecordingOptions
from recorder.session import RecordingSession
from recorder.worker import RecorderWorker


class LongSessionScalingTests(unittest.TestCase):
    def options(self, directory: str, *, mode: str = "normal", interval: float = 2.0, segment_seconds: int = 5) -> RecordingOptions:
        return RecordingOptions(
            save_dir=directory,
            monitor_index=1,
            source_mode="monitor",
            region={"left": 0, "top": 0, "width": 640, "height": 480},
            mode=mode,
            fps=30,
            scale=1.0,
            timelapse_interval=interval,
            timelapse_output_fps=30,
            quality="Balanced",
            encoder="Auto",
            segment_seconds=segment_seconds,
            min_free_mb=128,
            capture_cursor=True,
            keep_session_segments=True,
        )

    def test_timelapse_chunks_scale_with_capture_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worker = RecorderWorker(self.options(tmp, mode="timelapse", interval=20.0), queue.Queue())
            self.assertEqual(worker._segment_duration_target(), 200.0)

            very_slow = RecorderWorker(self.options(tmp, mode="timelapse", interval=60.0), queue.Queue())
            self.assertEqual(very_slow._segment_duration_target(), 300.0)

    def test_normal_recording_avoids_tiny_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            worker = RecorderWorker(self.options(tmp, mode="normal", segment_seconds=5), queue.Queue())
            self.assertEqual(worker._segment_duration_target(), 15.0)

    def test_stats_are_checkpointed_separately_and_force_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = RecordingSession(self.options(tmp))
            with patch.object(session, "_write_stats", wraps=session._write_stats) as write_stats, \
                 patch.object(session, "_write_manifest", wraps=session._write_manifest) as write_manifest:
                session.update_stats(frames=1)
                session.update_stats(frames=2)
                self.assertEqual(write_stats.call_count, 1)
                self.assertEqual(write_manifest.call_count, 0)
                session.update_stats(force=True, frames=3)
                self.assertEqual(write_stats.call_count, 2)
                self.assertEqual(write_manifest.call_count, 1)

    def test_fast_finalizer_does_not_probe_every_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = __import__("pathlib").Path(tmp)
            for index in range(100):
                (root / f"segment_{index + 1:06d}.mkv").write_bytes(b"x" * 2048)

            def fake_ffmpeg(command, **_kwargs):
                __import__("pathlib").Path(command[-1]).write_bytes(b"video" * 500)
                return 0, ""

            with patch("recorder.encoder.find_binary", return_value="ffmpeg"), \
                 patch("recorder.encoder._run_ffmpeg_with_progress", side_effect=fake_ffmpeg) as run_ffmpeg, \
                 patch("recorder.encoder.verify_media", return_value=(True, "ok")) as verify:
                output = finalize_segments(root, root / "final.mp4", 30)

            self.assertTrue(output.exists())
            self.assertEqual(run_ffmpeg.call_count, 1)
            self.assertEqual(verify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
