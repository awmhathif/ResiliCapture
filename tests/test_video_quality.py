from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from recorder.config import AppConfig
from recorder.encoder import _quality_args
from recorder.worker import RecorderWorker


class VideoQualityTests(unittest.TestCase):
    def test_fresh_install_defaults_to_native_quality(self) -> None:
        config = AppConfig()
        self.assertEqual(config.scale_percent, 100)
        self.assertEqual(config.quality, "Quality")

    def test_legacy_settings_migrate_to_native_quality_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = root / "settings.json"
            settings.write_text(json.dumps({"scale_percent": 75, "quality": "Balanced"}), encoding="utf-8")
            with patch("recorder.config.app_data_dir", return_value=root):
                config = AppConfig.load()
            self.assertEqual(config.scale_percent, 100)
            self.assertEqual(config.quality, "Quality")
            saved = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(saved["video_fidelity_revision"], 1)


    def test_brand_upgrade_imports_legacy_focusflow_settings_without_deleting_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            current = base / "ResiliCapture"
            legacy = base / "FocusFlowRecorder"
            current.mkdir()
            legacy.mkdir()
            legacy_settings = legacy / "settings.json"
            legacy_settings.write_text(
                json.dumps({"scale_percent": 100, "quality": "Near lossless", "video_fidelity_revision": 1}),
                encoding="utf-8",
            )
            with patch("recorder.config.app_data_dir", return_value=current), \
                 patch("recorder.config.legacy_app_data_dirs", return_value=(legacy,)):
                config = AppConfig.load()
            self.assertEqual(config.quality, "Near lossless")
            self.assertTrue((current / "settings.json").exists())
            self.assertTrue(legacy_settings.exists())

    def test_screen_quality_presets_use_sharp_crf_values(self) -> None:
        self.assertIn("15", _quality_args("libx264", "Quality"))
        self.assertIn("18", _quality_args("libx264", "Balanced"))
        self.assertIn("10", _quality_args("libx264", "Near lossless"))
        self.assertIn("15", _quality_args("h264_nvenc", "Quality"))

    def test_native_frame_is_not_resampled(self) -> None:
        frame = np.zeros((100, 160, 3), dtype=np.uint8)
        result = RecorderWorker._resize_for_recording(frame, 160, 100)
        self.assertIs(result, frame)

    def test_downscale_uses_lanczos_for_text_edges(self) -> None:
        frame = np.zeros((100, 160, 3), dtype=np.uint8)
        expected = np.zeros((50, 80, 3), dtype=np.uint8)
        with patch("recorder.worker.cv2.resize", return_value=expected) as resize:
            result = RecorderWorker._resize_for_recording(frame, 80, 50)
        self.assertIs(result, expected)
        resize.assert_called_once_with(frame, (80, 50), interpolation=cv2.INTER_LANCZOS4)


if __name__ == "__main__":
    unittest.main()
