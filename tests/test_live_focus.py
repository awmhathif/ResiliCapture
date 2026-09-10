from __future__ import annotations

import unittest

import numpy as np

from recorder.effects import LiveFocusController, apply_focus_effect


class LiveFocusTests(unittest.TestCase):
    def test_focus_zooms_selected_region_and_returns(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[:, :100] = (20, 20, 20)
        frame[:, 100:] = (220, 220, 220)
        controller = LiveFocusController()
        controller.activate(
            at=0.0,
            region={"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0},
            zoom=2.0,
            transition=0.2,
            style="Zoom",
        )
        focused = apply_focus_effect(frame, controller.snapshot(0.3))
        self.assertGreater(float(focused.mean()), float(frame.mean()))
        controller.clear(at=0.3, transition=0.2)
        returned = apply_focus_effect(frame, controller.snapshot(0.6))
        self.assertTrue(np.array_equal(returned, frame))

    def test_spotlight_dims_outside_selected_region(self) -> None:
        frame = np.full((80, 120, 3), 200, dtype=np.uint8)
        controller = LiveFocusController()
        controller.activate(
            at=0.0,
            region={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
            zoom=1.0,
            transition=0.1,
            style="Spotlight",
        )
        output = apply_focus_effect(frame, controller.snapshot(0.2))
        self.assertLess(int(output[2, 2, 0]), 200)
        self.assertEqual(int(output[40, 60, 0]), 200)


if __name__ == "__main__":
    unittest.main()
