# streamdockd

A Linux daemon that drives StreamDock macro pads (by MiraboxSpace) and exposes a local web UI for configuring buttons, icons, and the touchscreen/secondary display.

Built on top of the official [MiraboxSpace StreamDock Python SDK](https://github.com/MiraboxSpace/StreamDock-Device-SDK). The SDK's `libtransport.so` is a precompiled closed-source binary; this repo only contains the daemon, systemd service, udev rules, and Arch Linux package build files.

---

## Features

- Assigns shell commands to physical buttons (press or release)
- Sets per-button icons from local image files or [Iconify](https://iconify.design/) icon names (e.g. `mdi:github`)
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
  "actions": {
    "1": {
      "enabled": true,
      "command": "firefox",
      "cwd": "",
      "icon": "mdi:firefox",
      "icon_color": "ff9500",
      "run_on_release": false
    }
  }
}
```

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
