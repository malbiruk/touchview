"""TouchView — touchpad finger position visualizer overlay."""

import argparse
import math
import signal
import sys

import cairo
import evdev
from evdev import ecodes

from _overlay import (
    POSITION_ANCHORS,
    Gtk,
    draw_rounded_rect,
    parse_hex_color,
    setup_fullscreen_overlay,
    setup_overlay_window,
    watch_evdev,
)


def parse_args():
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
    return p.parse_args()


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
                if event.type == ecodes.EV_ABS:
                    self._handle_abs(event)
                elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
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
            else:
                self.slots.setdefault(self.current_slot, (0.5, 0.5))
        elif event.code == ecodes.ABS_MT_POSITION_X:
            nx = (event.value - self.x_min) / (self.x_max - self.x_min)
            _, oy = self.slots.get(self.current_slot, (0.5, 0.5))
            self.slots[self.current_slot] = (nx, oy)
        elif event.code == ecodes.ABS_MT_POSITION_Y:
            ny = (event.value - self.y_min) / (self.y_max - self.y_min)
            ox, _ = self.slots.get(self.current_slot, (0.5, 0.5))
            self.slots[self.current_slot] = (ox, ny)

    def _draw(self, _area, cr, width, height):
        if self.touchscreen:
            # Circles at each finger's real screen position; no backdrop, so the
            # actual screen stays visible under the overlay.
            for nx, ny in self.slots.values():
                ox, oy = _orient(nx, ny, self.rotate)
                self._draw_dot(cr, ox * width, oy * height)
            return

        cfg = self.cfg
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

        # Inset the dots so an edge touch's glow isn't clipped by the panel.
        pad = cfg.glow_size
        draw_w = width - 2 * pad
        draw_h = height - 2 * pad
        for nx, ny in self.slots.values():
            self._draw_dot(cr, pad + nx * draw_w, pad + ny * draw_h)

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
