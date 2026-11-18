# TouchView

Wayland overlays for visualizing touchpad/touchscreen gestures and keyboard shortcuts. Shows semi-transparent panels using Layer Shell's OVERLAY layer — sits above all windows and panels, fully click-through.

Useful for demos, screen recordings, and showcasing compositor features.

Example ([driftwm](https://github.com/malbiruk/driftwm) window movement):

https://github.com/user-attachments/assets/363d7252-dc28-4cf0-9c30-b7ca2e617972

## Tools

- **`touchview`** — finger position overlay: a touchpad (white dots on a dark panel) or a touchscreen (`--source touchscreen` — circles at the real screen position, fullscreen, like Android's "show touches")
- **`keyview`** — keyboard shortcut overlay (shows key combos like "Super + L", "Alt + Tab")

## Requirements

- Wayland compositor with layer shell support (sway, Hyprland, etc.)
- `gtk4-layer-shell` (system package)
- Access to `/dev/input/event*` (user must be in `input` group)

## Install

```sh
pip install touchview
```

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install touchview
```

From source:

```sh
git clone https://github.com/malbiruk/touchview.git
cd touchview
pip install .
```

## touchview

Visualizes finger positions in real-time. Two modes:

- **touchpad** (default) — dots on a dark panel anchored to a screen corner.
- **touchscreen** (`--source touchscreen`) — circles drawn at the real finger position on a fullscreen click-through overlay, like Android's "show touches". Ideal for screen-recording touchscreen demos.

```
touchview [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `touchpad` | `touchpad` (panel) or `touchscreen` (fullscreen, absolute) |
| `--rotate` | `0` | Panel rotation `0`/`90`/`180`/`270` (touchscreen mode, if dots don't track) |
| `--dot-color HEX` | `#ffffff` | Finger dot color |
| `--dot-opacity F` | `0.95` | Dot opacity (0-1) |
| `--dot-size PX` | `18` | Dot radius |
| `--glow-size PX` | `48` | Glow radius |
| `--trail-ms MS` | `0` | Fading trail duration in milliseconds, 0-2000 (`0` disables) |
| `--trail-width PX` | `4` | Newest trail width in pixels, greater than 0 and at most 100 |
| `--trail-opacity F` | `0.55` | Trail opacity multiplier (0-1), combined with dot opacity |
| `--bg-color HEX` | `#000000` | Background color (touchpad mode) |
| `--bg-opacity F` | `0.6` | Background opacity 0-1 (touchpad mode) |
| `--height PX` | `400` | Panel height, width from aspect ratio (touchpad mode) |
| `--radius PX` | `24` | Corner radius (touchpad mode) |
| `--position` | `bottom-right` | Panel position (touchpad mode) |
| `--margin PX` | `20` | Edge margin (touchpad mode) |

Touchscreen mode is fullscreen with no backdrop, so `--bg-*`, `--height`, `--radius`, `--position`, and `--margin` apply to touchpad (panel) mode only.

```sh
# Touchpad: blue-tinted panel, bottom-left
touchview --bg-color '#1a1a2e' --position bottom-left

# Touchscreen: circles at your fingertips, fullscreen — for screen recordings
touchview --source touchscreen

# Rotated tablet — bump --rotate until the circles track your finger
touchview --source touchscreen --rotate 270

# Compact touchpad panel with fading finger trails for a demo recording
touchview --height 180 --position bottom-right --bg-opacity 0.65 \
  --dot-size 10 --glow-size 24 \
  --trail-ms 450 --trail-width 4 --trail-opacity 0.55
```

Trails are optional and work in both touchpad and touchscreen modes. Each finger
gets a separate path in the dot color, fading and tapering with age. Trails keep
fading after lift; touching again starts a new path rather than joining the old
one. Try `--trail-ms 250` for shorter trails or `--trail-ms 700` for longer ones.

## keyview

Shows keyboard shortcuts and key combos as an overlay.

- Modifier combos (Ctrl, Alt, Super, Shift + key) display as "Super + L"
- Lone modifier taps show the modifier name
- Auto-fades after timeout

```
keyview [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--bg-color HEX` | `#000000` | Background color |
| `--bg-opacity F` | `0.6` | Background opacity (0-1) |
| `--text-color HEX` | `#ffffff` | Text color |
| `--text-opacity F` | `0.95` | Text opacity (0-1) |
| `--font-size PX` | `40` | Font size |
| `--radius PX` | `16` | Corner radius |
| `--timeout SEC` | `1.5` | Seconds before fade |
| `--position` | `bottom-left` | Window position |
| `--margin PX` | `20` | Edge margin |

```sh
# Both tools side by side — touchview right, keyview left
touchview --position bottom-right &
keyview --position bottom-left &
```

## Positions

Both tools support: `top-left`, `top`, `top-right`, `left`, `right`, `bottom-left`, `bottom`, `bottom-right`

## Permissions

```sh
sudo usermod -aG input $USER
# then log out and back in
```

## Tests

With the runtime dependencies installed, run:

```sh
LD_PRELOAD=libgtk4-layer-shell.so.0 python -m unittest discover -s tests -v
```

Preloading Layer Shell avoids the application's automatic restart when running
the test runner. Tests use simulated input and offscreen drawing; no input-device
access or running Wayland session is needed.
