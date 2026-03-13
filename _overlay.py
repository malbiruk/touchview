"""Shared overlay utilities for touchview and keyview."""

import argparse
import ctypes.util
import fcntl
import math
import os
import sys
from pathlib import Path

# gtk4-layer-shell must be loaded before libwayland-client.
# When imported via gi.repository it's too late, so we LD_PRELOAD it and re-exec.
_LAYER_SHELL_LIB = "libgtk4-layer-shell.so"
if _LAYER_SHELL_LIB not in os.environ.get("LD_PRELOAD", ""):
    lib_path = ctypes.util.find_library("gtk4-layer-shell")
    if not lib_path:
        for candidate in (
            "/usr/lib64/libgtk4-layer-shell.so",
            "/usr/lib/libgtk4-layer-shell.so",
        ):
            if Path(candidate).exists():
                lib_path = candidate
                break
    if lib_path:
        env = os.environ.copy()
        existing = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = f"{lib_path}:{existing}" if existing else lib_path
        os.execve(sys.executable, [sys.executable, *sys.argv], env)  # noqa: S606
    else:
        print("Warning: could not find libgtk4-layer-shell.so", file=sys.stderr)

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import GLib, Gtk, Gtk4LayerShell, Pango, PangoCairo  # noqa: E402

__all__ = [
    "POSITION_ANCHORS",
    "GLib",
    "Gtk",
    "Pango",
    "PangoCairo",
    "draw_rounded_rect",
    "parse_hex_color",
    "setup_overlay_window",
    "watch_evdev",
]

_EDGE = Gtk4LayerShell.Edge

POSITION_ANCHORS = {
    "top-left": (_EDGE.TOP, _EDGE.LEFT),
    "top-right": (_EDGE.TOP, _EDGE.RIGHT),
    "top": (_EDGE.TOP,),
    "bottom-left": (_EDGE.BOTTOM, _EDGE.LEFT),
    "bottom-right": (_EDGE.BOTTOM, _EDGE.RIGHT),
    "bottom": (_EDGE.BOTTOM,),
    "left": (_EDGE.LEFT,),
    "right": (_EDGE.RIGHT,),
}


def parse_hex_color(value):
    """Parse hex color like '#ff0000' or 'ff0000' → (r, g, b) floats 0-1."""
    value = value.lstrip("#")
    if len(value) != 6:
        msg = f"Invalid hex color: #{value}"
        raise argparse.ArgumentTypeError(msg)
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return (r / 255, g / 255, b / 255)


def setup_overlay_window(win, position, margin):
    """Configure a GTK window as a transparent click-through layer shell overlay."""
    Gtk4LayerShell.init_for_window(win)
    Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
    Gtk4LayerShell.set_keyboard_mode(win, Gtk4LayerShell.KeyboardMode.NONE)
    Gtk4LayerShell.set_exclusive_zone(win, -1)

    for edge in POSITION_ANCHORS[position]:
        Gtk4LayerShell.set_anchor(win, edge, True)  # noqa: FBT003
        Gtk4LayerShell.set_margin(win, edge, margin)

    # Transparent background — custom CSS class + USER priority to override theme
    win.add_css_class("transparent")
    css = Gtk.CssProvider()
    css.load_from_string(
        ".transparent, .transparent * { background-color: rgba(0,0,0,0); background: none; }",
    )
    Gtk.StyleContext.add_provider_for_display(
        win.get_display(),
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )

    # Click-through after realize
    win.connect("realize", _on_realize)


def _on_realize(win):
    surface = win.get_surface()
    surface.set_input_region(cairo.Region([]))


def watch_evdev(dev, callback):
    """Register an evdev device fd with GLib main loop for non-blocking reads."""
    fd = dev.fd
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    GLib.io_add_watch(fd, GLib.IO_IN, callback)


def draw_rounded_rect(cr, width, height, radius, r, g, b, a):
    """Draw a filled rounded rectangle."""
    cr.new_sub_path()
    cr.arc(width - radius, radius, radius, -math.pi / 2, 0)
    cr.arc(width - radius, height - radius, radius, 0, math.pi / 2)
    cr.arc(radius, height - radius, radius, math.pi / 2, math.pi)
    cr.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()
    cr.set_source_rgba(r, g, b, a)
    cr.fill()
