from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from recorder.encoder import EncoderError, finalize_segments
from recorder.models import RecordingOptions, RecordingState
from recorder.session import RecordingSession, load_segment_records
from recorder.diagnostics import create_diagnostic_report
from recorder.recovery import session_roots
from recorder.models import RecorderEvent
from ui.main_window import MainWindow


class ProductionHardeningTests(unittest.TestCase):
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
            segment_seconds=30,
            min_free_mb=128,
            capture_cursor=True,
            keep_session_segments=True,
        )


    def test_recovery_scans_legacy_focusflow_session_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = base / ".focusflow_sessions" / "legacy-session"
            current = base / ".resilicapture_sessions" / "new-session"
            legacy.mkdir(parents=True)
            current.mkdir(parents=True)
            (legacy / "session.json").write_text('{"session_id":"legacy-session"}', encoding="utf-8")
            (current / "session.json").write_text('{"session_id":"new-session"}', encoding="utf-8")
            roots = set(session_roots(base))
            self.assertIn(legacy, roots)
            self.assertIn(current, roots)

    def test_segment_metadata_uses_append_only_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = RecordingSession(self.options(tmp))
            for index in range(25):
                segment = session.root / f"segment_{index + 1:06d}.mkv"
                segment.write_bytes(b"x" * 2048)
                session.add_segment(segment, frames=30, duration=1.0, backend="test", codec="libx264")
            session.set_state(RecordingState.STOPPING, "checkpoint")

            records = load_segment_records(session.root)
            manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(records), 25)
            self.assertEqual(manifest["segment_count"], 25)
            self.assertNotIn("segments", manifest)
            self.assertTrue(session.segments_path.exists())

    def test_truncated_last_journal_line_does_not_hide_prior_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = RecordingSession(self.options(tmp))
            segment = session.root / "segment_000001.mkv"
            segment.write_bytes(b"x" * 2048)
            session.add_segment(segment, frames=30, duration=1.0, backend="test", codec="libx264")
            with session.segments_path.open("ab") as handle:
                handle.write(b'{"name":"incomplete"')
            self.assertEqual(len(load_segment_records(session.root)), 1)

    def test_finalizer_refuses_obviously_insufficient_output_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "segment_000001.mkv").write_bytes(b"x" * 4096)
            fake_usage = SimpleNamespace(total=10_000, used=9_900, free=100)
            with patch("recorder.encoder.shutil.disk_usage", return_value=fake_usage), \
                 patch("recorder.encoder.find_binary", return_value="ffmpeg"):
                with self.assertRaisesRegex(EncoderError, "Not enough free space"):
                    finalize_segments(root, root / "final.mp4", 30, min_free_bytes=1024)

    def test_window_close_delegates_to_non_destructive_tray_minimize(self) -> None:
        dummy = SimpleNamespace(_minimize_to_tray=Mock())
        MainWindow._on_close(dummy)
        dummy._minimize_to_tray.assert_called_once_with()


    def test_hidden_finalization_progress_does_not_reopen_window(self) -> None:
        root = Mock()
        dummy = SimpleNamespace(
            _hidden_to_tray=True,
            start_button=Mock(),
            _set_status=Mock(),
            root=root,
        )
        event = RecorderEvent(kind="finalize_progress", payload={"percent": 42.0, "message": "Combining video…"})
        MainWindow._handle_event(dummy, event)
        root.deiconify.assert_not_called()

    def test_diagnostic_bundle_excludes_recording_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "session"
            session_dir.mkdir()
            (session_dir / "session.log").write_text(f"path={root}\n", encoding="utf-8")
            (session_dir / "segment_000001.mkv").write_bytes(b"private-video-data")
            report = create_diagnostic_report(
                root / "diagnostics.zip", app_version="test", save_dir=root, session_dir=session_dir
            )
            import zipfile
            with zipfile.ZipFile(report) as archive:
                names = set(archive.namelist())
                self.assertNotIn("session/segment_000001.mkv", names)
                text = archive.read("session/session.log").decode("utf-8")
                self.assertNotIn(str(root), text)
                self.assertIn("<USER_PATH>", text)

    def test_explicit_exit_during_recording_stops_and_saves_first(self) -> None:
        worker = SimpleNamespace(is_alive=lambda: True)
        dummy = SimpleNamespace(
            _closing=False,
            recording_state=RecordingState.RECORDING,
            worker=worker,
            _show_from_tray=Mock(),
            _exit_after_save=False,
            stop_recording=Mock(),
            root=object(),
        )
        with patch("ui.main_window.messagebox.askyesno", return_value=True):
            MainWindow._request_exit(dummy)
        self.assertTrue(dummy._exit_after_save)
        dummy.stop_recording.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
