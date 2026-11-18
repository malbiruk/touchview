"""Overlay tests using simulated evdev input and offscreen Cairo drawing."""

import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cairo
from evdev import ecodes

import touchview


def event(kind, code, value=0):
    return SimpleNamespace(type=kind, code=code, value=value)


def absolute(code, value):
    return event(ecodes.EV_ABS, code, value)


def report():
    return event(ecodes.EV_SYN, ecodes.SYN_REPORT)


class ArgumentTests(unittest.TestCase):
    def test_trails_are_opt_in(self):
        cfg = touchview.parse_args([])
        self.assertEqual(cfg.trail_ms, 0)
        self.assertEqual(cfg.trail_width, 4)
        self.assertEqual(cfg.trail_opacity, 0.55)

    def test_trail_options(self):
        cfg = touchview.parse_args([
            "--trail-ms", "450", "--trail-width", "4.5", "--trail-opacity", "0.6",
        ])
        self.assertEqual(cfg.trail_ms, 450)
        self.assertEqual(cfg.trail_width, 4.5)
        self.assertEqual(cfg.trail_opacity, 0.6)

    def test_invalid_values(self):
        cases = {
            "--trail-ms": ("-1", "2001", "nan", "inf"),
            "--trail-width": ("0", "-1", "101", "nan", "inf"),
            "--trail-opacity": ("-0.1", "1.1", "nan", "inf"),
        }
        for flag, values in cases.items():
            for value in values:
                with self.subTest(flag=flag, value=value):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as error:
                            touchview.parse_args([flag, value])
                    self.assertEqual(error.exception.code, 2)

    def test_boundary_values(self):
        for duration in ("0", "2000"):
            for opacity in ("0", "1"):
                touchview.parse_args([
                    "--trail-ms", duration, "--trail-width", "100",
                    "--trail-opacity", opacity,
                ])


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.cfg = touchview.parse_args(["--trail-ms", "450"])
        self.dev = Mock()
        absinfo = {
            ecodes.ABS_MT_POSITION_X: SimpleNamespace(min=100, max=1100),
            ecodes.ABS_MT_POSITION_Y: SimpleNamespace(min=200, max=1200),
        }
        self.overlay = touchview.TouchOverlay(self.dev, absinfo, self.cfg)
        self.overlay.area = Mock()
        self.timer = patch.object(touchview.GLib, "timeout_add", return_value=42)
        self.add_timer = self.timer.start()
        self.addCleanup(self.timer.stop)

    def feed(self, events, now):
        self.dev.read.return_value = iter(events)
        with patch.object(touchview.time, "monotonic", return_value=now):
            return self.overlay._on_evdev(None, None)

    def contact(self, slot=0, tracking_id=7, x=200, y=400):
        return [
            absolute(ecodes.ABS_MT_SLOT, slot),
            absolute(ecodes.ABS_MT_TRACKING_ID, tracking_id),
            absolute(ecodes.ABS_MT_POSITION_X, x),
            absolute(ecodes.ABS_MT_POSITION_Y, y),
            report(),
        ]

    def test_sample_complete_frames_and_only_start_one_timer(self):
        self.feed(self.contact(), 1)
        self.feed([
            absolute(ecodes.ABS_MT_POSITION_X, 400),
            absolute(ecodes.ABS_MT_POSITION_Y, 600),
            report(),
        ], 1.1)
        points = next(iter(self.overlay.trails.paths.values()))
        self.assertEqual(list(points), [(1, 0.1, 0.2), (1.1, 0.3, 0.4)])
        self.add_timer.assert_called_once_with(16, self.overlay._fade_trails)

    def test_multiple_reports_in_one_read_are_all_sampled(self):
        self.dev.read.return_value = iter([
            *self.contact(),
            absolute(ecodes.ABS_MT_POSITION_X, 400),
            report(),
        ])
        with patch.object(touchview.time, "monotonic", side_effect=[1, 1.1]):
            self.overlay._on_evdev(None, None)
        points = next(iter(self.overlay.trails.paths.values()))
        self.assertEqual(list(points), [(1, 0.1, 0.2), (1.1, 0.3, 0.2)])

    def test_lift_and_slot_reuse(self):
        self.feed(self.contact(), 1)
        self.feed([absolute(ecodes.ABS_MT_POSITION_X, 400), report()], 1.1)
        self.feed([absolute(ecodes.ABS_MT_TRACKING_ID, -1), report()], 1.2)
        self.assertEqual(self.overlay.slots, {})
        self.assertEqual(len(list(self.overlay.trails.segments(1.2))), 1)
        self.feed(self.contact(tracking_id=8, x=900, y=1000), 1.3)
        self.assertEqual(len(self.overlay.trails.paths), 2)
        self.assertEqual(len(list(self.overlay.trails.segments(1.3))), 1)

    def test_new_tracking_id_without_lift_does_not_join_old_path(self):
        self.feed(self.contact(), 1)
        self.feed(self.contact(tracking_id=8, x=900), 1.1)
        self.assertEqual(len(self.overlay.trails.paths), 2)
        self.assertEqual(list(self.overlay.trails.segments(1.1)), [])

    def test_disabled_trails_do_not_record_or_schedule_redraws(self):
        self.cfg.trail_ms = 0
        self.feed(self.contact(), 1)
        self.assertEqual(self.overlay.slots, {0: (0.1, 0.2)})
        self.assertEqual(self.overlay.trails.paths, {})
        self.assertEqual(self.overlay.trails.active, {})
        self.add_timer.assert_not_called()

    def test_fade_timer_runs_after_lift_and_stops_when_empty(self):
        self.feed(self.contact(), 1)
        self.feed([absolute(ecodes.ABS_MT_POSITION_X, 400), report()], 1.1)
        self.feed([absolute(ecodes.ABS_MT_TRACKING_ID, -1), report()], 1.2)
        self.overlay.area.queue_draw.reset_mock()
        with patch.object(touchview.time, "monotonic", return_value=1.3):
            self.assertTrue(self.overlay._fade_trails())
        with patch.object(touchview.time, "monotonic", return_value=2):
            self.assertFalse(self.overlay._fade_trails())
        self.assertIsNone(self.overlay._trail_timer)
        self.assertEqual(self.overlay.trails.paths, {})
        self.assertEqual(self.overlay.area.queue_draw.call_count, 2)
        self.feed(self.contact(tracking_id=8), 3)
        self.assertEqual(self.add_timer.call_count, 2)

    def test_shutdown_removes_timer(self):
        self.feed(self.contact(), 1)
        with patch.object(touchview.GLib, "source_remove") as remove:
            self.overlay._stop_trail_timer()
            self.overlay._stop_trail_timer()
        remove.assert_called_once_with(42)
        self.assertIsNone(self.overlay._trail_timer)

    def test_dropped_input_does_not_reconnect_stale_contacts(self):
        self.feed(self.contact(), 1)
        self.feed([
            event(ecodes.EV_SYN, ecodes.SYN_DROPPED),
            absolute(ecodes.ABS_MT_POSITION_X, 1000),
            report(),
        ], 1.1)
        self.assertEqual(self.overlay.trails.paths, {})
        self.feed([absolute(ecodes.ABS_MT_POSITION_X, 300), report()], 1.2)
        self.assertEqual(self.overlay.trails.paths, {})
        self.feed(self.contact(slot=1, tracking_id=8), 1.3)
        self.feed([absolute(ecodes.ABS_MT_POSITION_X, 400), report()], 1.4)
        self.assertEqual(len(self.overlay.trails.paths), 1)
        self.assertEqual(set(self.overlay.trails.active), {1})

    def test_nonblocking_reads(self):
        self.dev.read.side_effect = BlockingIOError
        self.assertTrue(self.overlay._on_evdev(None, None))

    def test_trails_draw_between_background_and_dots(self):
        self.overlay.slots = {0: (0.1, 0.2)}
        calls = []

        def record(name):
            return lambda *args: calls.append(name)

        with (
            patch.object(touchview, "draw_rounded_rect", side_effect=record("bg")),
            patch.object(self.overlay, "_draw_trails", side_effect=record("trail")),
            patch.object(self.overlay, "_draw_dot", side_effect=record("dot")),
        ):
            self.overlay._draw(None, Mock(), 400, 400)
        self.assertEqual(calls, ["bg", "trail", "dot"])

    def test_trails_draw_without_active_fingers(self):
        with patch.object(self.overlay, "_draw_trails") as draw:
            self.overlay._draw(None, Mock(), 400, 400)
        draw.assert_called_once()

    def test_coordinate_mapping_matches_dots_in_both_modes(self):
        self.assertEqual(self.overlay._position(0, 1, 400, 300), (48, 252))
        self.overlay.touchscreen = True
        for rotation, expected in (
            (0, (100, 150)),
            (90, (200, 225)),
            (180, (300, 150)),
            (270, (200, 75)),
        ):
            with self.subTest(rotation=rotation):
                self.overlay.rotate = rotation
                self.assertEqual(self.overlay._position(0.25, 0.5, 400, 300), expected)

    def test_offscreen_trail_rendering_fades_to_transparent(self):
        self.overlay.touchscreen = True
        self.cfg.dot_color = (1, 0, 0)
        self.overlay.trails.sample({0: (0.2, 0.5)}, 1)
        self.overlay.trails.sample({0: (0.8, 0.5)}, 1.1)

        def render(now):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
            with patch.object(touchview.time, "monotonic", return_value=now):
                self.overlay._draw(None, cairo.Context(surface), 100, 100)
            surface.flush()
            return surface.get_data().tobytes()

        fresh = render(1.1)
        faded = render(1.3)
        expired = render(2)
        self.assertGreater(sum(fresh), sum(faded))
        self.assertGreater(sum(faded), 0)
        self.assertEqual(sum(expired), 0)


if __name__ == "__main__":
    unittest.main()
