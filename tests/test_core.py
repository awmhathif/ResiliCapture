from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from recorder import capture as capture_module
from recorder.capture import MSSBackend
from recorder.models import RecordingOptions, RecordingState
from recorder.recovery import scan_recoverable
from recorder.session import RecordingSession


class CoreTests(unittest.TestCase):
    def options(self, directory: str) -> RecordingOptions:
        return RecordingOptions(
            save_dir=directory,
            monitor_index=1,
            source_mode="monitor",
            region={"left": 0, "top": 0, "width": 640, "height": 480},
            mode="normal",
            fps=30,
            scale=1.0,
            timelapse_interval=2.0,
            timelapse_output_fps=30,
            quality="Balanced",
            encoder="Auto",
            segment_seconds=5,
            min_free_mb=128,
            capture_cursor=True,
            keep_session_segments=False,
        )


    def test_mss_backend_does_not_assign_read_only_cursor_property(self) -> None:
        class ReadOnlyCursorMSS:
            @property
            def with_cursor(self) -> bool:
                return False

            def close(self) -> None:
                return

        fake = ReadOnlyCursorMSS()
        backend = MSSBackend({"left": 0, "top": 0, "width": 64, "height": 64}, capture_cursor=True)
        with patch.object(capture_module, "_new_mss", return_value=fake) as factory:
            backend.open()
        factory.assert_called_once_with(capture_cursor=True)
        self.assertIs(backend.sct, fake)

    def test_manifest_is_atomic_and_reloadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = RecordingSession(self.options(tmp))
            session.set_state(RecordingState.RECORDING, "test")
            data = json.loads(session.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["state"], "recording")
            self.assertFalse(session.manifest_path.with_suffix(".json.tmp").exists())

    def test_recovery_scan_finds_completed_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = RecordingSession(self.options(tmp))
            segment = session.root / "segment_000001.mkv"
            segment.write_bytes(b"0" * 2048)
            session.add_segment(segment, frames=30, duration=1.0, backend="test", codec="test")
            session.fail("simulated")
            found = scan_recoverable(tmp)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].segment_count, 1)


if __name__ == "__main__":
    unittest.main()
