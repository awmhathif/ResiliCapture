from __future__ import annotations

import re
import unittest
from pathlib import Path

from PIL import Image

from recorder.config import APP_NAME, APP_VERSION, LEGACY_SESSION_DIR_NAMES, SESSION_DIR_NAME


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_brand_and_version_are_consistent_across_build_metadata(self) -> None:
        self.assertEqual(APP_NAME, "ResiliCapture")
        self.assertEqual(APP_VERSION, "0.7.0")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        version_info = (ROOT / "version_info.txt").read_text(encoding="utf-8")
        spec = (ROOT / "ResiliCapture.spec").read_text(encoding="utf-8")
        self.assertIn('name = "resilicapture"', pyproject)
        self.assertIn('version = "0.7.0"', pyproject)
        self.assertIn("ProductVersion', '0.7.0'", version_info)
        self.assertIn('name="ResiliCapture"', spec)

    def test_social_preview_has_github_recommended_dimensions(self) -> None:
        with Image.open(ROOT / "docs" / "social-preview.png") as image:
            self.assertEqual(image.size, (1280, 640))

    def test_current_and_legacy_recovery_names_are_explicit(self) -> None:
        self.assertEqual(SESSION_DIR_NAME, ".resilicapture_sessions")
        self.assertIn(".focusflow_sessions", LEGACY_SESSION_DIR_NAMES)

    def test_release_workflow_uses_beta_tag_and_current_executable(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn('$expected = "v$version-beta"', workflow)
        self.assertIn("ResiliCapture.spec", workflow)
        self.assertIn("ResiliCapture-$env:APP_VERSION-Windows.zip", workflow)
        self.assertIsNone(re.search(r"FocusFlowRecorder\.spec|FocusFlowRecorder\.exe", workflow))


if __name__ == "__main__":
    unittest.main()
