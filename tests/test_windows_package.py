from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.package_windows import create_package


class WindowsPackageTests(unittest.TestCase):
    def test_standalone_exe_cannot_be_published_as_complete_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "ResiliCapture.exe").write_bytes(b"incomplete app")
            with self.assertRaisesRegex(RuntimeError, "including _internal"):
                create_package(folder, folder / "output")
            self.assertFalse((folder / "output").exists())

    def test_public_package_rejects_unreviewed_ffmpeg_anywhere_in_bundle(self) -> None:
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            with self.subTest(binary=name), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                (folder / "ResiliCapture.exe").write_bytes(b"app")
                binaries = folder / "_internal" / "bin"
                binaries.mkdir(parents=True)
                (binaries / name).write_bytes(b"unreviewed tool")
                with self.assertRaisesRegex(RuntimeError, "must not contain"):
                    create_package(folder, folder / "output")
                self.assertFalse((folder / "output").exists())


if __name__ == "__main__":
    unittest.main()
