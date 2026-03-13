"""KeyView — keyboard shortcut visualizer overlay."""

import argparse
import signal

import evdev
from evdev import ecodes

from _overlay import (
    POSITION_ANCHORS,
    GLib,
    Gtk,
    Pango,
    PangoCairo,
    draw_rounded_rect,
    parse_hex_color,
    setup_overlay_window,
    watch_evdev,
)

# Modifier keycodes → display names
_MODIFIERS = {
    ecodes.KEY_LEFTCTRL: "Ctrl",
    ecodes.KEY_RIGHTCTRL: "Ctrl",
    ecodes.KEY_LEFTALT: "Alt",
    ecodes.KEY_RIGHTALT: "Alt",
    ecodes.KEY_LEFTSHIFT: "Shift",
    ecodes.KEY_RIGHTSHIFT: "Shift",
    ecodes.KEY_LEFTMETA: "Super",
    ecodes.KEY_RIGHTMETA: "Super",
}

# Nice display names for special keys
_KEY_NAMES = {
    ecodes.KEY_SPACE: "Space",
    ecodes.KEY_ENTER: "Enter",
    ecodes.KEY_TAB: "Tab",
    ecodes.KEY_BACKSPACE: "Backspace",
    ecodes.KEY_ESC: "Esc",
    ecodes.KEY_DELETE: "Del",
    ecodes.KEY_INSERT: "Ins",
    ecodes.KEY_HOME: "Home",
    ecodes.KEY_END: "End",
    ecodes.KEY_PAGEUP: "PgUp",
    ecodes.KEY_PAGEDOWN: "PgDn",
    ecodes.KEY_UP: "\u2191",
    ecodes.KEY_DOWN: "\u2193",
    ecodes.KEY_LEFT: "\u2190",
    ecodes.KEY_RIGHT: "\u2192",
    ecodes.KEY_CAPSLOCK: "CapsLock",
    ecodes.KEY_NUMLOCK: "NumLock",
    ecodes.KEY_SCROLLLOCK: "ScrollLock",
    ecodes.KEY_PRINT: "PrtSc",
    ecodes.KEY_PAUSE: "Pause",
}
# F1-F12
for _i in range(1, 13):
    _KEY_NAMES[getattr(ecodes, f"KEY_F{_i}")] = f"F{_i}"


def _key_label(code):
    """Get a human-readable label for an evdev keycode."""
    if code in _KEY_NAMES:
        return _KEY_NAMES[code]
    name = ecodes.KEY.get(code, "")
    if isinstance(name, list):
        name = name[0]
    name = name.removeprefix("KEY_")
    return name.capitalize() if len(name) > 1 else name.upper()


def parse_args():
    p = argparse.ArgumentParser(description="Keyboard shortcut overlay")
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
        "--text-color",
        type=parse_hex_color,
        default=(1, 1, 1),
        metavar="HEX",
        help="text color (default: #ffffff)",
    )
    p.add_argument(
        "--text-opacity",
        type=float,
        default=0.95,
        metavar="F",
        help="text opacity 0-1 (default: 0.95)",
    )
    p.add_argument(
        "--font-size",
        type=int,
        default=40,
        metavar="PX",
        help="font size in pixels (default: 40)",
    )
    p.add_argument(
        "--radius",
        type=int,
        default=16,
        metavar="PX",
        help="corner radius in pixels (default: 16)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=1.5,
        metavar="SEC",
        help="seconds before combo fades (default: 1.5)",
    )
    p.add_argument(
        "--position",
        choices=sorted(POSITION_ANCHORS),
        default="bottom-left",
        help="window position (default: bottom-left)",
    )
    p.add_argument(
        "--margin",
        type=int,
        default=20,
        metavar="PX",
        help="edge margin in pixels (default: 20)",
    )
    return p.parse_args()


def find_keyboard():
    """Find first evdev device with keyboard capabilities."""
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities()
        key_caps = caps.get(ecodes.EV_KEY, [])
        if ecodes.KEY_A in key_caps and ecodes.KEY_Z in key_caps:
            return dev
    raise RuntimeError("No keyboard device found")


class KeyOverlay(Gtk.Application):
    def __init__(self, dev, cfg):
        super().__init__(application_id="dev.keyview")
        self.dev = dev
        self.cfg = cfg
        self.held_modifiers = set()
        self.combo_used = False
        self.display_text = ""
        self.fade_timeout_id = None
        self.visible = False

    def do_activate(self):
        win = Gtk.Window(application=self)
        cfg = self.cfg

        setup_overlay_window(win, cfg.position, cfg.margin)

        area = Gtk.DrawingArea()
        area.set_draw_func(self._draw)
        area.set_content_height(cfg.font_size + 32)
        area.set_content_width(1)
        win.set_child(area)
        self.area = area

        win.present()
        watch_evdev(self.dev, self._on_evdev)

    def _on_evdev(self, _fd, _condition):
        try:
            for event in self.dev.read():
                if event.type == ecodes.EV_KEY:
                    self._handle_key(event)
        except BlockingIOError:
            pass
        return True

    def _handle_key(self, event):
        code = event.code
        is_press = event.value in (1, 2)

        if code in _MODIFIERS:
            mod_name = _MODIFIERS[code]
            if is_press:
                self.held_modifiers.add(mod_name)
                self.combo_used = False
                # Show modifiers immediately (useful for modifier + touchpad gestures)
                self._show_modifiers()
            else:
                # Modifier released — show lone modifier tap if no combo was triggered
                if not self.combo_used and mod_name in self.held_modifiers:
                    self._show_combo(mod_name)
                self.held_modifiers.discard(mod_name)
                if self.held_modifiers:
                    self._show_modifiers()
        elif is_press:
            label = _key_label(code)
            if not label:
                return
            if self.held_modifiers:
                mod_order = ["Super", "Ctrl", "Alt", "Shift"]
                mods = [m for m in mod_order if m in self.held_modifiers]
                combo = " + ".join([*mods, label])
                self.combo_used = True
            else:
                combo = label
            self._show_combo(combo)

    def _show_modifiers(self):
        """Show currently held modifiers immediately (no fade timer)."""
        mod_order = ["Super", "Ctrl", "Alt", "Shift"]
        mods = [m for m in mod_order if m in self.held_modifiers]
        if not mods:
            return
        text = " + ".join(mods) + " + ..."
        self.display_text = text
        self.visible = True

        layout = self._make_layout(text)
        text_w, text_h = layout.get_pixel_size()
        pad_x, pad_y = 32, 16
        self.area.set_content_width(text_w + pad_x * 2)
        self.area.set_content_height(text_h + pad_y * 2)
        self.area.queue_draw()

        # Cancel any pending fade since we're actively holding modifiers
        if self.fade_timeout_id is not None:
            GLib.source_remove(self.fade_timeout_id)
            self.fade_timeout_id = None

    def _show_combo(self, text):
        self.display_text = text
        self.visible = True

        layout = self._make_layout(text)
        text_w, text_h = layout.get_pixel_size()
        pad_x, pad_y = 32, 16
        self.area.set_content_width(text_w + pad_x * 2)
        self.area.set_content_height(text_h + pad_y * 2)
        self.area.queue_draw()

        if self.fade_timeout_id is not None:
            GLib.source_remove(self.fade_timeout_id)
        self.fade_timeout_id = GLib.timeout_add(
            int(self.cfg.timeout * 1000),
            self._on_fade,
        )

    def _on_fade(self):
        self.visible = False
        self.display_text = ""
        self.area.set_content_width(1)
        self.area.queue_draw()
        self.fade_timeout_id = None
        return False

    def _make_layout(self, text):
        """Create a PangoLayout for measuring text."""
        ctx = PangoCairo.font_map_get_default().create_context()
        layout = Pango.Layout(ctx)
        font = Pango.FontDescription.from_string(f"Sans Bold {self.cfg.font_size}px")
        layout.set_font_description(font)
        layout.set_text(text)
        return layout

    def _draw(self, _area, cr, width, height):
        if not self.visible or not self.display_text:
            return

        cfg = self.cfg
        bg_r, bg_g, bg_b = cfg.bg_color
        txt_r, txt_g, txt_b = cfg.text_color

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

        # Text
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string(f"Sans Bold {cfg.font_size}px")
        layout.set_font_description(font)
        layout.set_text(self.display_text)
        text_w, text_h = layout.get_pixel_size()
        cr.move_to((width - text_w) / 2, (height - text_h) / 2)
        cr.set_source_rgba(txt_r, txt_g, txt_b, cfg.text_opacity)
        PangoCairo.show_layout(cr, layout)


def main():
    cfg = parse_args()
    dev = find_keyboard()
    print(f"Using: {dev.name} ({dev.path})")

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = KeyOverlay(dev, cfg)
    app.run()


if __name__ == "__main__":
    main()
