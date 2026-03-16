# TouchView

Wayland overlays for visualizing touchpad gestures and keyboard shortcuts. Shows semi-transparent panels using Layer Shell's OVERLAY layer — sits above all windows and panels, fully click-through.

Useful for demos, screen recordings, and showcasing compositor features.

Example ([driftwm](https://github.com/malbiruk/driftwm) window movement):

https://github.com/user-attachments/assets/363d7252-dc28-4cf0-9c30-b7ca2e617972

## Tools

- **`touchview`** — touchpad finger position overlay (white dots on dark panel)
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

Visualizes touchpad finger positions in real-time.

```
touchview [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--bg-color HEX` | `#000000` | Background color |
| `--bg-opacity F` | `0.6` | Background opacity (0-1) |
| `--dot-color HEX` | `#ffffff` | Finger dot color |
| `--dot-opacity F` | `0.95` | Dot opacity (0-1) |
| `--dot-size PX` | `18` | Dot radius |
| `--glow-size PX` | `48` | Glow radius |
| `--height PX` | `400` | Window height (width from touchpad aspect ratio) |
| `--radius PX` | `24` | Corner radius |
| `--position` | `bottom-right` | Window position |
| `--margin PX` | `20` | Edge margin |

```sh
# Blue-tinted, bottom-left
touchview --bg-color '#1a1a2e' --position bottom-left

# Small overlay
touchview --height 200 --dot-size 10 --glow-size 24
```

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
