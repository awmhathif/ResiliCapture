from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from recorder.encoder import FFmpegSegmentEncoder, finalize_segments, find_binary, verify_media


@unittest.skipUnless(find_binary("ffmpeg"), "FFmpeg is not installed")
class EncoderSmokeTests(unittest.TestCase):
    def test_segment_and_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            part = root / "segment_000001.part.mkv"
            encoder = FFmpegSegmentEncoder(160, 90, 10, "Performance", "Software H.264")
            encoder.open(part)
            for index in range(12):
                frame = np.zeros((90, 160, 3), dtype=np.uint8)
                frame[:, :, index % 3] = 60 + index * 10
                encoder.write(frame)
            self.assertTrue(encoder.close())
            segment = root / "segment_000001.mkv"
            part.replace(segment)
            output = finalize_segments(root, root / "smoke.mp4", 10)
            valid, details = verify_media(output)
            self.assertTrue(valid, details)
            self.assertGreater(output.stat().st_size, 1024)

    def test_mixed_encoder_segments_are_normalized(self) -> None:
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # H.264/MKV segment
            part = root / "segment_000001.part.mkv"
            encoder = FFmpegSegmentEncoder(160, 90, 10, "Performance", "Software H.264")
            encoder.open(part)
            for index in range(8):
                frame = np.zeros((90, 160, 3), dtype=np.uint8)
                frame[:, :, 1] = 80 + index * 10
                encoder.write(frame)
            self.assertTrue(encoder.close())
            part.replace(root / "segment_000001.mkv")

            # MJPEG/AVI fallback segment
            avi = root / "segment_000002.avi"
            writer = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 90))
            self.assertTrue(writer.isOpened())
            for index in range(8):
                frame = np.zeros((90, 160, 3), dtype=np.uint8)
                frame[:, :, 2] = 80 + index * 10
                writer.write(frame)
            writer.release()

            output = finalize_segments(root, root / "mixed.mp4", 10)
            valid, details = verify_media(output)
            self.assertTrue(valid, details)
            self.assertGreater(output.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
