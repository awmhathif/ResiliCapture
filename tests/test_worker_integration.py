from __future__ import annotations

import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from recorder.models import RecordingOptions
from recorder.worker import RecorderWorker
from recorder.encoder import find_binary, verify_media


class FakeCapture:
    def __init__(self, region, capture_cursor):
        self.region = region
        self.capture_cursor = capture_cursor
        self.total_retries = 0
        self.backend_name = "Synthetic test capture"
        self.counter = 0

    def open(self):
        return

    def grab(self, attempts=4):
        self.counter += 1
        frame = np.zeros((self.region["height"], self.region["width"], 3), dtype=np.uint8)
        frame[:, :, self.counter % 3] = 100 + self.counter % 100
        return frame

    def close(self):
        return


@unittest.skipUnless(find_binary("ffmpeg"), "FFmpeg is not installed")
class WorkerIntegrationTests(unittest.TestCase):
    def test_worker_records_stops_finalizes_and_emits_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            options = RecordingOptions(
                save_dir=tmp,
                monitor_index=1,
                source_mode="monitor",
                region={"left": 0, "top": 0, "width": 160, "height": 90},
                mode="normal",
                fps=10,
                scale=1.0,
                timelapse_interval=1.0,
                timelapse_output_fps=10,
                quality="Performance",
                encoder="Software H.264",
                segment_seconds=1,
                min_free_mb=1,
                capture_cursor=False,
                keep_session_segments=True,
            )
            events = queue.Queue()
            with patch("recorder.worker.ResilientCapture", FakeCapture):
                worker = RecorderWorker(options, events)
                worker.start()
                time.sleep(1.35)
                worker.stop()
                worker.join(timeout=20)
            self.assertFalse(worker.is_alive())
            emitted = []
            while not events.empty():
                emitted.append(events.get_nowait())
            completed = [event for event in emitted if event.kind == "completed"]
            failures = [event for event in emitted if event.kind == "failed"]
            self.assertFalse(failures, failures[0].payload if failures else "")
            self.assertEqual(len(completed), 1)
            output = Path(completed[0].payload["path"])
            valid, details = verify_media(output)
            self.assertTrue(valid, details)
            self.assertGreaterEqual(len(list((Path(tmp) / ".resilicapture_sessions").glob("*/segment_*"))), 1)

    def test_worker_records_manual_focus_span_and_closes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            options = RecordingOptions(
                save_dir=tmp,
                monitor_index=1,
                source_mode="monitor",
                region={"left": 0, "top": 0, "width": 160, "height": 90},
                mode="normal",
                fps=10,
                scale=1.0,
                timelapse_interval=1.0,
                timelapse_output_fps=10,
                quality="Performance",
                encoder="Software H.264",
                segment_seconds=1,
                min_free_mb=1,
                capture_cursor=False,
                keep_session_segments=True,
                live_focus_enabled=True,
            )
            events = queue.Queue()
            with patch("recorder.worker.ResilientCapture", FakeCapture):
                worker = RecorderWorker(options, events)
                worker.start()
                deadline = time.time() + 5
                while worker.session is None and time.time() < deadline:
                    time.sleep(0.02)
                self.assertIsNotNone(worker.session)
                worker.set_paused(True)
                time.sleep(0.2)
                marker = worker.begin_focus_marker(
                    {"x": 0.4, "y": 0.25, "width": 0.2, "height": 0.3},
                    zoom=1.8,
                    transition=0.3,
                )
                self.assertIsNotNone(marker)
                worker.set_paused(False)
                time.sleep(0.55)
                finished = worker.end_focus_marker()
                self.assertIsNotNone(finished)
                worker.stop()
                worker.join(timeout=20)
            self.assertFalse(worker.is_alive())
            assert worker.session is not None
            markers = worker.session.manifest["focus_markers"]
            self.assertEqual(len(markers), 1)
            self.assertFalse(markers[0].get("open"))
            self.assertGreater(float(markers[0]["duration"]), float(markers[0]["transition"]))

    def test_worker_records_timelapse_and_finalizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            options = RecordingOptions(
                save_dir=tmp,
                monitor_index=1,
                source_mode="monitor",
                region={"left": 0, "top": 0, "width": 160, "height": 90},
                mode="timelapse",
                fps=30,
                scale=1.0,
                timelapse_interval=0.15,
                timelapse_output_fps=12,
                quality="Performance",
                encoder="Software H.264",
                segment_seconds=1,
                min_free_mb=1,
                capture_cursor=False,
                keep_session_segments=True,
            )
            events = queue.Queue()
            with patch("recorder.worker.ResilientCapture", FakeCapture):
                worker = RecorderWorker(options, events)
                self.assertAlmostEqual(worker._capture_interval(), 0.15)
                self.assertEqual(worker._output_fps(), 12.0)
                worker.start()
                time.sleep(0.85)
                worker.stop()
                worker.join(timeout=20)
            self.assertFalse(worker.is_alive())
            emitted = []
            while not events.empty():
                emitted.append(events.get_nowait())
            failures = [event for event in emitted if event.kind == "failed"]
            completed = [event for event in emitted if event.kind == "completed"]
            self.assertFalse(failures, failures[0].payload if failures else "")
            self.assertEqual(len(completed), 1)
            output = Path(completed[0].payload["path"])
            self.assertTrue(output.name.startswith("timelapse_"))
            valid, details = verify_media(output)
            self.assertTrue(valid, details)



if __name__ == "__main__":
    unittest.main()
