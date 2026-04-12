# streamdockd

A Linux daemon that drives StreamDock macro pads (by MiraboxSpace) and exposes a local web UI for configuring buttons, icons, and the touchscreen/secondary display.

Built on top of the official [MiraboxSpace StreamDock Python SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK). The SDK's `libtransport.so` is a precompiled closed-source binary; this repo only contains the daemon, systemd service, udev rules, and Arch Linux package build files.

---

## Features

- Assigns shell commands to physical buttons (press or release)
- Sets per-button icons from local image files or [Iconify](https://iconify.design/) icon names (e.g. `mdi:github`)
- **Multiple button pages** — add as many pages of 15 button configs as needed and navigate between them with prev/next/go-to shortcuts or dedicated hardware buttons
- **Scenes** — save named snapshots of any configuration (buttons, pages, display widgets) and activate them instantly from the UI
- Controls touchscreen/secondary display: clock, system stats, or a custom image
- Configurable brightness and auto-reconnect on device disconnect
- Web UI at `http://127.0.0.1:17890` — no extra dependencies, no Electron
- Clean subprocess environment so button commands can launch GUI apps (Wayland/X11) reliably
- Runs as a systemd user service

## Supported Devices

Any StreamDock device supported by the MiraboxSpace SDK. Vendor/product IDs covered by the bundled udev rules:

| Vendor | Product IDs |
|--------|-------------|
| `0x5500` | `0x1001` |
| `0x5548` | `0x6670`, `0x1008`, `0x1020`, `0x1021`, `0x1023`, `0x1028`, `0x1031` |
| `0x6602` | `0x1001`, `0x1002`, `0x1003`, `0x2929` |
| `0x6603` | `0x1000`–`0x1015`, `0x1019` |
| `0xeeef` | `0x2929` |
| `0x1500` | `0x3001` |

## Requirements

- Python 3.10+
- `python-pillow`
- `python-pyudev`
- `gcc-libs` (`libstdc++.so.6`)
- `systemd-libs` (`libudev.so.1`)

Optional (for SVG icon support, at least one recommended):

- `librsvg` — `rsvg-convert` (fastest)
- `imagemagick` — `magick`/`convert`
- `inkscape`

## Installation

### Arch Linux (via PKGBUILD)

```sh
git clone https://github.com/mrksn/streamdockd
cd streamdockd
makepkg -si
```

`makepkg` will fetch the upstream SDK from GitHub, install the daemon to `/usr/lib/streamdockd/`, the launcher to `/usr/bin/streamdockd`, the systemd user service, and the udev rules.

After install, reload udev rules and enable the service:

```sh
sudo udevadm control --reload-rules && sudo udevadm trigger
systemctl --user enable --now streamdockd.service
```

### Manual

1. Clone this repo and the [MiraboxSpace SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK).
2. Copy the SDK's `Python-SDK/src/StreamDock` tree and `Python-SDK/img/` next to `streamdockd.py`.
   Also copy all `.py` modules (`config.py`, `icon_manager.py`, `widgets.py`, `device.py`, `server.py`) and `ui.html` into the same directory.
3. Install udev rules: `sudo install -m644 99-streamdock.rules /etc/udev/rules.d/` and reload.
4. Run directly: `python streamdockd.py`

## Configuration

Config is written on first run to `~/.config/streamdockd/config.json` (respects `$XDG_CONFIG_HOME` and the `STREAMDOCKD_CONFIG` env var).

The web UI at `http://127.0.0.1:17890` is the intended way to manage it. The JSON structure is straightforward if you prefer to edit it by hand:

```json
{
  "ui": { "host": "127.0.0.1", "port": 17890 },
  "device": { "brightness": 100, "reconnect_seconds": 2 },
  "touchscreen": { "mode": "off", "interval_seconds": 5, "image": "" },
  "widgets": {
    "refresh_seconds": 5,
    "16": { "mode": "clock", "icon": "mdi:clock-outline", "icon_color": "ffffff" },
    "17": { "mode": "stats", "icon": "mdi:chart-box-outline", "icon_color": "ffffff" },
    "18": { "mode": "date", "icon": "mdi:calendar-month-outline", "icon_color": "ffffff" }
  },
  "pages": [
    {
      "1": { "enabled": true, "type": "command", "command": "firefox", "icon": "mdi:firefox", "icon_color": "ff9500" },
      "2": { "enabled": true, "type": "page_next", "icon": "mdi:chevron-right", "label": "Next page" }
    }
  ],
  "active_page": 0,
  "actions": { ... }
}
```

> **Backward compatibility** — existing configs with a flat `actions` dict (no `pages`) are automatically migrated to a single-page setup on first load; no manual changes required.

### Button action types

Each button has a `type` field that controls what happens when it is pressed:

| `type` | Behaviour |
|--------|-----------|
| `command` (default) | Run the shell `command` in the optional `cwd` directory |
| `page_next` | Switch to the next page (wraps around) |
| `page_prev` | Switch to the previous page (wraps around) |
| `page_goto` | Jump to the 1-indexed page number in the `page` field |

Navigation buttons still display their `icon` / `label` on the device as normal.

### Pages

- The web UI shows a **Pages** bar above the button grid with **← PREV**, **NEXT →**, **+ ADD PAGE**, **DEL PAGE**, and a **Go to** number field.
- Clicking **SAVE CONFIG** persists all pages and the currently active page to disk and applies the active page's icons to the device immediately.
- Switching pages in the UI is client-side only until you save — hit **SAVE CONFIG** to push the change to the device.

### Scenes

Scenes let you save and restore complete configurations (all button pages + display widgets) as named snapshots.

- The **Scenes** panel appears to the right of the icon preview grid.
- Type a name and click **SAVE** to create a new empty scene — configure it from scratch by activating it and filling in buttons, then saving.
- Click a scene name to **activate** it: the scene's button config and display settings are loaded onto the device immediately.
- The ⧉ button **duplicates** a scene with an auto-generated name (`<name> copy`).
- The ✕ button **deletes** a scene (requires two clicks within 3 s as a safety guard).
- While a scene is active, **SAVE CONFIG** also writes the changes back to that scene so re-activating it later restores them.
- Scenes are stored in `~/.config/streamdockd/scenes.json` (same config directory as `config.json`).

### Icon values

- **Local file**: absolute path or path relative to the install directory — `"/home/user/pics/logo.png"`
- **Iconify name**: `"collection:icon-name"` — e.g. `"mdi:volume-high"`, `"ph:terminal-bold"`. Icons are fetched from the Iconify API and cached locally.

### Touchscreen / secondary display modes

| Mode | Description |
|------|-------------|
| `off` | Leave touchscreen as-is |
| `time` | Live clock |
| `stats` | CPU load averages + memory usage |
| `image` | Static image from a local file path |

## Systemd service

The service runs as a **user** unit (not root). It passes graphical session environment variables so button commands can open GUI apps.

```sh
# Status
systemctl --user status streamdockd.service

# Logs
journalctl --user -u streamdockd.service -f

# Restart after config change
systemctl --user restart streamdockd.service
```

## License

The daemon, service file, udev rules, and PKGBUILD in this repository are MIT licensed.

The MiraboxSpace StreamDock SDK (fetched at build time) carries its own MIT license. The bundled `libtransport.so` is a precompiled closed-source binary distributed by MiraboxSpace.
