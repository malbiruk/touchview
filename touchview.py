"""TouchView — touchpad finger position visualizer overlay."""

import argparse
import math
import signal
import sys
import time

import cairo
import evdev
from evdev import ecodes

from _overlay import (
    POSITION_ANCHORS,
    GLib,
    Gtk,
    draw_rounded_rect,
    parse_hex_color,
    setup_fullscreen_overlay,
    setup_overlay_window,
    watch_evdev,
)
from _trails import TrailHistory


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Touch finger position overlay")
    p.add_argument(
        "--source",
        choices=("touchpad", "touchscreen"),
        default="touchpad",
        help="input device: touchpad (dots in a panel) or touchscreen "
        "(circles at the real screen position, fullscreen) (default: touchpad)",
    )
    p.add_argument(
        "--rotate",
        type=int,
        choices=(0, 90, 180, 270),
        default=0,
        help="touchscreen panel rotation in degrees, if dots don't track your "
        "finger (touchscreen mode only; default: 0)",
    )
    p.add_argument(
        "--bg-color",
        type=parse_hex_color,
        default=(0, 0, 0),
        metavar="HEX",
        help="background color (default: #000000)",
    )
    p.add_argument(
        "--bg-opacity",
        type=float,
        default=0.6,
        metavar="F",
        help="background opacity 0-1 (default: 0.6)",
    )
    p.add_argument(
        "--dot-color",
        type=parse_hex_color,
        default=(1, 1, 1),
        metavar="HEX",
        help="finger dot color (default: #ffffff)",
    )
    p.add_argument(
        "--dot-opacity",
        type=float,
        default=0.95,
        metavar="F",
        help="dot opacity 0-1 (default: 0.95)",
    )
    p.add_argument(
        "--dot-size",
        type=int,
        default=18,
        metavar="PX",
        help="dot radius in pixels (default: 18)",
    )
    p.add_argument(
        "--glow-size",
        type=int,
        default=48,
        metavar="PX",
        help="glow radius in pixels (default: 48)",
    )
    p.add_argument(
        "--trail-ms",
        type=float,
        default=0,
        metavar="MS",
        help="trail duration, 0-2000 milliseconds; 0 disables (default: 0)",
    )
    p.add_argument(
        "--trail-width",
        type=float,
        default=4,
        metavar="PX",
        help="newest trail width, greater than 0 and at most 100 pixels (default: 4)",
    )
    p.add_argument(
        "--trail-opacity",
        type=float,
        default=0.55,
        metavar="F",
        help="trail opacity multiplier, 0-1 (default: 0.55)",
    )
    p.add_argument(
        "--height",
        type=int,
        default=400,
        metavar="PX",
        help="window height in pixels (default: 400)",
    )
    p.add_argument(
        "--radius",
        type=int,
        default=24,
        metavar="PX",
        help="corner radius in pixels (default: 24)",
    )
    p.add_argument(
        "--position",
        choices=sorted(POSITION_ANCHORS),
        default="bottom-right",
        help="window position (default: bottom-right)",
    )
    p.add_argument(
        "--margin",
        type=int,
        default=20,
        metavar="PX",
        help="edge margin in pixels (default: 20)",
    )
    cfg = p.parse_args(argv)
    if not math.isfinite(cfg.trail_ms) or not 0 <= cfg.trail_ms <= 2000:
        p.error("--trail-ms must be between 0 and 2000")
    if not math.isfinite(cfg.trail_width) or not 0 < cfg.trail_width <= 100:
        p.error("--trail-width must be greater than 0 and at most 100")
    if not math.isfinite(cfg.trail_opacity) or not 0 <= cfg.trail_opacity <= 1:
        p.error("--trail-opacity must be between 0 and 1")
    return cfg


def find_device(touchscreen):
    """Find a multitouch device. Touchscreens report `INPUT_PROP_DIRECT` (absolute
    panel), touchpads `INPUT_PROP_POINTER`; prefer the matching kind so the right
    device is picked when both are present."""
    candidates = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities(absinfo=True)
        abs_caps = caps.get(ecodes.EV_ABS, [])
        abs_codes = {code for code, _info in abs_caps}
        if (
            ecodes.ABS_MT_POSITION_X not in abs_codes
            or ecodes.ABS_MT_POSITION_Y not in abs_codes
        ):
            continue
        try:
            direct = ecodes.INPUT_PROP_DIRECT in dev.input_props()
        except (AttributeError, OSError):
            direct = False
        candidates.append((dev, dict(abs_caps), direct))

    if not candidates:
        raise RuntimeError("No multitouch device found")

    want_direct = touchscreen
    for dev, absinfo, direct in candidates:
        if direct == want_direct:
            return dev, absinfo

    # No exact match (e.g. a touchscreen that doesn't flag INPUT_PROP_DIRECT) —
    # fall back to the first MT device and warn.
    dev, absinfo, _ = candidates[0]
    kind = "touchscreen" if touchscreen else "touchpad"
    print(f"Warning: no {kind} found; using {dev.name}", file=sys.stderr)
    return dev, absinfo


def _orient(nx, ny, rotate):
    """Remap normalized device coords (0-1) for a panel rotated `rotate` degrees,
    so the circles track the finger when the touchscreen is mounted rotated."""
    if rotate == 90:
        return ny, 1 - nx
    if rotate == 180:
        return 1 - nx, 1 - ny
    if rotate == 270:
        return 1 - ny, nx
    return nx, ny


class TouchOverlay(Gtk.Application):
    def __init__(self, dev, absinfo, cfg):
        super().__init__(application_id="dev.touchview")
        self.dev = dev
        self.cfg = cfg
        self.slots = {}  # slot → (norm_x, norm_y)
        self.current_slot = 0
        self.touchscreen = cfg.source == "touchscreen"
        self.rotate = cfg.rotate
        self.trails = TrailHistory(cfg.trail_ms / 1000)
        self._trail_timer = None
        self._trail_sync_dropped = False
        self._trail_wait_for_contact = False
        self.connect("shutdown", self._stop_trail_timer)

        x_info = absinfo[ecodes.ABS_MT_POSITION_X]
        y_info = absinfo[ecodes.ABS_MT_POSITION_Y]
        self.x_min, self.x_max = x_info.min, x_info.max
        self.y_min, self.y_max = y_info.min, y_info.max
        x_range = self.x_max - self.x_min
        y_range = self.y_max - self.y_min
        aspect = x_range / y_range if y_range else 1.0

        self.win_h = cfg.height
        self.win_w = int(self.win_h * aspect)

    def do_activate(self):
        win = Gtk.Window(application=self)
        area = Gtk.DrawingArea()
        area.set_draw_func(self._draw)

        if self.touchscreen:
            setup_fullscreen_overlay(win)
            area.set_hexpand(True)
            area.set_vexpand(True)
        else:
            setup_overlay_window(win, self.cfg.position, self.cfg.margin)
            win.set_default_size(self.win_w, self.win_h)
            area.set_content_width(self.win_w)
            area.set_content_height(self.win_h)

        win.set_child(area)
        self.area = area

        win.present()
        watch_evdev(self.dev, self._on_evdev)

    def _on_evdev(self, _fd, _condition):
        try:
            for event in self.dev.read():
                if self.cfg.trail_ms > 0:
                    if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                        # Discard trails and ignore events through the next
                        # report; their coordinates may be incomplete.
                        self.trails.clear()
                        self._trail_sync_dropped = True
                        self._trail_wait_for_contact = True
                        self.area.queue_draw()
                    if self._trail_sync_dropped:
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                            self._trail_sync_dropped = False
                        continue
                if event.type == ecodes.EV_ABS:
                    self._handle_abs(event)
                elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                    if self.cfg.trail_ms > 0:
                        slots = self.slots
                        if self._trail_wait_for_contact:
                            # After lost input, only newly reported contacts
                            # have a reliable identity. Don't revive old paths.
                            slots = {
                                slot: pos for slot, pos in slots.items()
                                if slot in self.trails.active
                            }
                        self.trails.sample(slots, time.monotonic())
                        if self.trails.paths and self._trail_timer is None:
                            self._trail_timer = GLib.timeout_add(16, self._fade_trails)
                    self.area.queue_draw()
        except BlockingIOError:
            pass
        return True

    def _handle_abs(self, event):
        if event.code == ecodes.ABS_MT_SLOT:
            self.current_slot = event.value
        elif event.code == ecodes.ABS_MT_TRACKING_ID:
            if event.value == -1:
                self.slots.pop(self.current_slot, None)
                if self.cfg.trail_ms > 0:
                    self.trails.end(self.current_slot)
            else:
                self.slots.setdefault(self.current_slot, (0.5, 0.5))
                if self.cfg.trail_ms > 0:
                    self.trails.begin(self.current_slot)
        elif event.code == ecodes.ABS_MT_POSITION_X:
            nx = (event.value - self.x_min) / (self.x_max - self.x_min)
            _, oy = self.slots.get(self.current_slot, (0.5, 0.5))
            self.slots[self.current_slot] = (nx, oy)
        elif event.code == ecodes.ABS_MT_POSITION_Y:
            ny = (event.value - self.y_min) / (self.y_max - self.y_min)
            ox, _ = self.slots.get(self.current_slot, (0.5, 0.5))
            self.slots[self.current_slot] = (ox, ny)

    def _fade_trails(self):
        self.trails.prune(time.monotonic())
        self.area.queue_draw()
        if not self.trails.paths:
            self._trail_timer = None
            return False
        return True

    def _stop_trail_timer(self, *_args):
        if self._trail_timer is not None:
            GLib.source_remove(self._trail_timer)
            self._trail_timer = None

    def _position(self, nx, ny, width, height):
        if self.touchscreen:
            ox, oy = _orient(nx, ny, self.rotate)
            return ox * width, oy * height
        # Inset the dots so an edge touch's glow isn't clipped by the panel.
        pad = self.cfg.glow_size
        return pad + nx * (width - 2 * pad), pad + ny * (height - 2 * pad)

    def _draw(self, _area, cr, width, height):
        cfg = self.cfg
        if not self.touchscreen:
            bg_r, bg_g, bg_b = cfg.bg_color
            draw_rounded_rect(
                cr,
                width,
                height,
                cfg.radius,
                bg_r,
                bg_g,
                bg_b,
                cfg.bg_opacity,
            )

        # Trails sit above the backdrop but below all current contact dots.
        if cfg.trail_ms > 0:
            self._draw_trails(cr, width, height)
        for nx, ny in self.slots.values():
            self._draw_dot(cr, *self._position(nx, ny, width, height))

    def _draw_trails(self, cr, width, height):
        cfg = self.cfg
        r, g, b = cfg.dot_color
        cr.save()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for start, end, fade in self.trails.segments(time.monotonic()):
            cr.new_path()
            cr.set_line_width(cfg.trail_width * (0.35 + 0.65 * fade))
            cr.set_source_rgba(r, g, b, cfg.trail_opacity * cfg.dot_opacity * fade)
            cr.move_to(*self._position(*start, width, height))
            cr.line_to(*self._position(*end, width, height))
            cr.stroke()
        cr.restore()

    def _draw_dot(self, cr, cx, cy):
        cfg = self.cfg
        dot_r, dot_g, dot_b = cfg.dot_color

        # Soft glow
        gradient = cairo.RadialGradient(cx, cy, 0, cx, cy, cfg.glow_size)
        gradient.add_color_stop_rgba(0, dot_r, dot_g, dot_b, 0.3)
        gradient.add_color_stop_rgba(1, dot_r, dot_g, dot_b, 0.0)
        cr.set_source(gradient)
        cr.arc(cx, cy, cfg.glow_size, 0, 2 * math.pi)
        cr.fill()

        # Solid dot
        cr.set_source_rgba(dot_r, dot_g, dot_b, cfg.dot_opacity)
        cr.arc(cx, cy, cfg.dot_size, 0, 2 * math.pi)
        cr.fill()


def main():
    cfg = parse_args()
    dev, absinfo = find_device(cfg.source == "touchscreen")
    print(f"Using: {dev.name} ({dev.path})")

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = TouchOverlay(dev, absinfo, cfg)
    app.run()


if __name__ == "__main__":
    main()
