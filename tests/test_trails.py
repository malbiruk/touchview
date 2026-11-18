"""Trail history tests; no GTK, input hardware, or third-party tools needed."""

import math
import unittest

from _trails import TrailHistory


class TrailHistoryTests(unittest.TestCase):
    def test_segments_fade_and_expire(self):
        history = TrailHistory(1)
        history.sample({0: (0.1, 0.2)}, 0)
        history.sample({0: (0.3, 0.4)}, 0.1)
        history.sample({0: (0.5, 0.6)}, 0.2)

        segments = list(history.segments(0.5))
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0][:2], ((0.1, 0.2), (0.3, 0.4)))
        self.assertAlmostEqual(segments[0][2], 0.6 ** 1.5)
        self.assertLess(segments[0][2], segments[1][2])
        self.assertEqual(list(history.segments(1.3)), [])
        self.assertEqual(history.paths, {})

    def test_lift_preserves_trail_and_reuse_starts_new_path(self):
        history = TrailHistory(1)
        history.begin(0)
        history.sample({0: (0.1, 0.2)}, 0)
        history.sample({0: (0.2, 0.3)}, 0.1)
        history.end(0)
        self.assertEqual(len(list(history.segments(0.2))), 1)
        self.assertNotIn(0, history.active)

        history.begin(0)
        history.sample({0: (0.8, 0.7)}, 0.3)
        history.sample({0: (0.9, 0.8)}, 0.4)
        segments = list(history.segments(0.4))
        self.assertEqual(len(history.paths), 2)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[1][:2], ((0.8, 0.7), (0.9, 0.8)))

    def test_each_finger_has_its_own_path(self):
        history = TrailHistory(1)
        history.sample({0: (0.1, 0.2), 1: (0.7, 0.8)}, 0)
        history.sample({0: (0.2, 0.3), 1: (0.8, 0.9)}, 0.1)
        segments = list(history.segments(0.1))
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0][:2], ((0.1, 0.2), (0.2, 0.3)))
        self.assertEqual(segments[1][:2], ((0.7, 0.8), (0.8, 0.9)))

    def test_stationary_samples_do_not_brighten_last_moving_edge(self):
        history = TrailHistory(1)
        history.sample({0: (0.1, 0.2)}, 0)
        history.sample({0: (0.3, 0.4)}, 0.1)
        history.sample({0: (0.3, 0.4)}, 0.5)
        segments = list(history.segments(0.5))
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0][2], 0.6 ** 1.5)
        history.sample({0: (0.3, 0.4)}, 1.2)
        self.assertEqual(list(history.segments(1.2)), [])

    def test_zero_lifetime_disables_history(self):
        history = TrailHistory(0)
        history.sample({0: (0.1, 0.2)}, 0)
        self.assertEqual(history.paths, {})
        self.assertEqual(list(history.segments(0)), [])

    def test_nonfinite_coordinates_are_ignored(self):
        history = TrailHistory(1)
        history.sample({0: (math.nan, 0), 1: (0, math.inf)}, 0)
        self.assertEqual(history.paths, {})

    def test_memory_is_bounded(self):
        history = TrailHistory(1)
        for i in range(3000):
            history.sample({0: (i / 3000, 0.2)}, i / 10000)
        self.assertEqual(len(next(iter(history.paths.values()))), 2048)

        for _ in range(200):
            history.begin(0)
            history.sample({0: (0.1, 0.2)}, 0.4)
        self.assertEqual(len(history.paths), 128)

    def test_clear_discards_active_and_released_contacts(self):
        history = TrailHistory(1)
        history.sample({0: (0.1, 0.2), 1: (0.3, 0.4)}, 0)
        history.end(0)
        history.clear()
        self.assertEqual(history.active, {})
        self.assertEqual(history.paths, {})


if __name__ == "__main__":
    unittest.main()
