"""StreamDock device lifecycle, button actions, and display update orchestration."""

import glob as _glob
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from config import ConfigStore
from icon_manager import IconManager
from widgets import WidgetRenderer

from StreamDock.DeviceManager import DeviceManager
from StreamDock.InputTypes import EventType


__all__ = ["StreamDockDaemon"]

_BASE_DIR = Path(__file__).resolve().parent


class StreamDockDaemon:
    def __init__(self, config_store: ConfigStore, icon_manager: IconManager, widget_renderer: WidgetRenderer):
        self.config_store = config_store
        self.icon_manager = icon_manager
        self.widget_renderer = widget_renderer
        self.manager = DeviceManager()
        self.device = None
        self.device_path = None
        self.stop_event = threading.Event()
        self.refresh_event = threading.Event()
        self.device_lock = threading.Lock()
        self.is_legacy_293_family = False
        self.last_touchscreen_update_ts = 0.0
        self.touchscreen_failures = 0
        self.secondary_display_active = False

    @staticmethod
    def _clean_env() -> Dict[str, str]:
        """Return an environment safe for launching GUI subprocesses."""
        keep_keys = {
            "HOME", "USER", "LOGNAME", "SHELL",
            "LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES",
            "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
            "DBUS_SESSION_BUS_ADDRESS",
            "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
            "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP",
            "QT_QPA_PLATFORM", "GDK_BACKEND",
        }
        env = {k: v for k, v in os.environ.items() if k in keep_keys}
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")

        xdg = env.get("XDG_RUNTIME_DIR", "")

        # Reconstruct common session vars when user-manager env is incomplete.
        if xdg and "WAYLAND_DISPLAY" not in env:
            for wayland_socket in ("wayland-0", "wayland-1"):
                if os.path.exists(os.path.join(xdg, wayland_socket)):
                    env["WAYLAND_DISPLAY"] = wayland_socket
                    break

        if xdg and "DBUS_SESSION_BUS_ADDRESS" not in env:
            bus_path = os.path.join(xdg, "bus")
            if os.path.exists(bus_path):
                env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"

        # Prefer native Wayland for Qt apps, but keep xcb fallback.
        if "QT_QPA_PLATFORM" not in env and "WAYLAND_DISPLAY" in env:
            env["QT_QPA_PLATFORM"] = "wayland;xcb"

        if "XAUTHORITY" not in env:
            if xdg:
                candidates = _glob.glob(os.path.join(xdg, "xauth*"))
                if candidates:
                    env["XAUTHORITY"] = candidates[0]
        return env

    def _run_action(self, action: Dict[str, Any], key: int):
        command = str(action.get("command", "")).strip()
        if not command:
            return
        cwd = str(action.get("cwd", "")).strip() or None
        if cwd and not os.path.isdir(cwd):
            print(f"[warn] key {key}: cwd does not exist: {cwd}", flush=True)
            cwd = None
        print(f"[exec] key={key} cmd={command}", flush=True)
        subprocess.Popen(
            command,
            shell=True,
            executable="/bin/bash",
            cwd=cwd,
            env=self._clean_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _on_input(self, _device, event):
        if event.event_type != EventType.BUTTON:
            return
        key = int(event.key.value)
        state = int(event.state)
        device = self.device  # snapshot to avoid race with _detach_device
        if type(device).__name__ == "StreamDock293s" and key >= 16:
            return
        config = self.config_store.get()
        action = config["actions"].get(str(key), {})
        if not action.get("enabled", False):
            return
        should_run = state == 0
        if should_run:
            action_type = str(action.get("type", "command"))
            if action_type in ("page_next", "page_prev", "page_goto"):
                self._handle_page_action(action_type, action)
            else:
                self._run_action(action, key)

    def _handle_page_action(self, action_type: str, action: Dict[str, Any]):
        """Switch the active button page in response to a page-navigation button press."""
        config = self.config_store.get()
        pages = config.get("pages", [])
        if not pages:
            return
        current = int(config.get("active_page", 0))
        count = len(pages)
        if action_type == "page_next":
            new_page = (current + 1) % count
        elif action_type == "page_prev":
            new_page = (current - 1) % count
        elif action_type == "page_goto":
            # page field is 1-indexed in UI
            target = int(action.get("page", 1)) - 1
            new_page = max(0, min(count - 1, target))
        else:
            return
        print(f"[page] switching from page {current + 1} to page {new_page + 1}", flush=True)
        config["active_page"] = new_page
        config["actions"] = pages[new_page]
        self.config_store.set(config)
        self.reload_and_apply()

    def _apply_icons_locked(self):
        if self.device is None:
            return
        config = self.config_store.get()
        actions = config["actions"]
        for key_text, action in actions.items():
            key_num = int(key_text)
            icon = str(action.get("icon", "")).strip()
            label = str(action.get("label", "")).strip()
            label_pos = str(action.get("label_pos", "off")).strip() or "off"
            color = str(action.get("icon_color", "ffffff")).strip()

            icon_path: Optional[Path] = None
            if not icon:
                icon_path = self.icon_manager.blank_button_image_path()
                if icon_path is None:
                    continue
            elif self.icon_manager.is_iconify_name(icon):
                icon_path = self.icon_manager.materialize_button_icon(icon, color)
                if icon_path is None:
                    details = self.icon_manager.last_icon_error or "unknown fetch error"
                    print(f"[warn] icon fetch failed for key {key_text}: {icon} | {details}", flush=True)
                    continue
            else:
                p = Path(icon).expanduser()
                if not p.is_absolute():
                    p = (_BASE_DIR / p).resolve()
                if not p.exists():
                    print(f"[warn] icon for key {key_text} not found: {p}", flush=True)
                    continue
                icon_path = p

            final_path = self.icon_manager.render_button_image(icon_path, label, label_pos, color)

            try:
                result = self.device.set_key_image(key_num, str(final_path))
                rc = int(result) if isinstance(result, (int, float)) else 0
                if rc != 0:
                    print(f"[warn] set_key_image returned {rc} for key {key_text} (icon={final_path})", flush=True)
            except Exception as exc:
                print(f"[warn] set_key_image failed key={key_text}: {exc}", flush=True)
        try:
            self.device.refresh()
        except Exception:
            pass

    def _apply_touchscreen_locked(self):
        if self.device is None:
            return

        cfg = self.config_store.get()
        ts_cfg = cfg.get("touchscreen", {})
        mode = str(ts_cfg.get("mode", "off")).lower()
        widgets_cfg = cfg.get("widgets", {})

        if type(self.device).__name__ == "StreamDock293s":
            self._apply_secondary_display_293s_locked(widgets_cfg)
            return

        if mode == "off":
            return

        if not hasattr(self.device, "set_touchscreen_image"):
            return

        now = time.time()
        interval_cfg = int(ts_cfg.get("interval_seconds", 5))
        interval_cfg = max(1, min(60, interval_cfg))
        min_interval = 15 if self.is_legacy_293_family and mode in {"time", "stats"} else interval_cfg
        if now - self.last_touchscreen_update_ts < min_interval:
            return

        image_path: Optional[Path] = None
        if mode == "image":
            raw = str(ts_cfg.get("image", "")).strip()
            if not raw:
                return
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (_BASE_DIR / p).resolve()
            if not p.exists():
                print(f"[warn] touchscreen image not found: {p}", flush=True)
                return
            image_path = p
        elif mode in {"time", "stats"}:
            try:
                sz = tuple(self.device.touchscreen_image_format()["size"])
            except Exception:
                sz = (854, 480)
            image_path = self.widget_renderer.render_touchscreen_image(mode, (int(sz[0]), int(sz[1])))
        else:
            print(f"[warn] unknown touchscreen mode: {mode}", flush=True)
            return

        if image_path is None:
            return
        try:
            self.device.set_touchscreen_image(str(image_path))
            self.device.refresh()
            self.touchscreen_failures = 0
            self.last_touchscreen_update_ts = now
        except Exception as exc:
            self.touchscreen_failures += 1
            print(f"[warn] touchscreen update failed: {exc}", flush=True)
            if self.touchscreen_failures >= 3:
                new_cfg = self.config_store.get()
                new_cfg.setdefault("touchscreen", {})["mode"] = "off"
                self.config_store.set(new_cfg)
                print(
                    "[warn] right display auto-disabled after repeated errors; "
                    "set mode=image or increase interval and re-enable in UI",
                    flush=True,
                )

    def _apply_secondary_display_293s_locked(self, widgets_cfg: Dict[str, Any]):
        if self.device is None:
            return
        now = time.time()
        interval = int(widgets_cfg.get("refresh_seconds", 5))
        interval = max(1, min(60, interval))
        if now - self.last_touchscreen_update_ts < interval:
            return

        slot_cfg = {k: widgets_cfg.get(k, {}) for k in ("16", "17", "18")}
        if all(str(slot_cfg[s].get("mode", "off")).lower() == "off" for s in ("16", "17", "18")):
            self._clear_secondary_display_293s_locked(force=True)
            return

        tmp_files = []
        try:
            for key in (16, 17, 18):
                s = str(key)
                tile = self.widget_renderer.render_widget_tile_293s(s, slot_cfg[s])
                out = Path(tempfile.gettempdir()) / f"streamdockd_293s_widget_{key}.jpg"
                tmp_files.append(out)
                tile.save(out, "JPEG", quality=95)
                self.device.set_key_image(key, str(out))
            self.device.refresh()
            self.touchscreen_failures = 0
            self.last_touchscreen_update_ts = now
            self.secondary_display_active = True
        except Exception as exc:
            self.touchscreen_failures += 1
            print(f"[warn] 293s widget update failed: {exc}", flush=True)
            if self.touchscreen_failures >= 3:
                new_cfg = self.config_store.get()
                for s in ("16", "17", "18"):
                    new_cfg.setdefault("widgets", {}).setdefault(s, {})["mode"] = "off"
                self.config_store.set(new_cfg)
                print("[warn] right widgets auto-disabled after repeated errors", flush=True)
        finally:
            for path in tmp_files:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _clear_secondary_display_293s_locked(self, force: bool = False):
        if self.device is None:
            return
        if not self.secondary_display_active and not force:
            return
        tmp_files = []
        try:
            black = Image.new("RGB", (80, 80), (0, 0, 0))
            for key in (16, 17, 18):
                out = Path(tempfile.gettempdir()) / f"streamdockd_293s_slot_clear_{key}.jpg"
                tmp_files.append(out)
                black.save(out, "JPEG", quality=95)
                self.device.set_key_image(key, str(out))
            self.device.refresh()
            self.secondary_display_active = False
        except Exception as exc:
            print(f"[warn] failed to clear 293s secondary display: {exc}", flush=True)
        finally:
            for path in tmp_files:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _attach_first_device(self):
        devices = self.manager.enumerate()
        if not devices:
            return False

        dev = devices[0]
        with self.device_lock:
            if self.device is not None:
                return True
            try:
                dev.open()
                dev.init()
                cfg = self.config_store.get()
                brightness = int(cfg["device"].get("brightness", 100))
                brightness = max(1, min(100, brightness))
                dev.set_brightness(brightness)
                dev.refresh()
                dev.set_key_callback(self._on_input)
                self.device = dev
                self.device_path = getattr(dev, "path", None)
                self.is_legacy_293_family = type(dev).__name__ in {"StreamDock293", "StreamDock293s"}
                self.last_touchscreen_update_ts = 0.0
                self.touchscreen_failures = 0
                self.secondary_display_active = False
                self._apply_icons_locked()
                self._apply_touchscreen_locked()
                print(f"[info] connected device path={self.device_path}", flush=True)
                return True
            except Exception as exc:
                print(f"[warn] failed to open/init device: {exc}", flush=True)
                try:
                    dev.close()
                except Exception:
                    pass
                self.device = None
                self.device_path = None
                return False

    def _detach_device(self):
        with self.device_lock:
            if self.device is None:
                return
            try:
                self.device.set_key_callback(None)
            except Exception:
                pass
            try:
                self.device.close()
            except Exception:
                pass
            print(f"[info] disconnected device path={self.device_path}", flush=True)
            self.device = None
            self.device_path = None
            self.is_legacy_293_family = False
            self.secondary_display_active = False

    def _health_check(self):
        if self.device is None:
            return False
        try:
            devices = self.manager.enumerate()
            paths = {getattr(d, "path", "") for d in devices}
            if self.device_path not in paths:
                return False
            return True
        except Exception:
            return False

    def start_device_loop(self):
        print("[info] device loop started", flush=True)
        while not self.stop_event.is_set():
            if self.device is None:
                self._attach_first_device()
            else:
                ok = self._health_check()
                if not ok:
                    self._detach_device()
            cfg = self.config_store.get()
            wait_s = int(cfg["device"].get("reconnect_seconds", 2))
            wait_s = max(1, min(10, wait_s))
            self.stop_event.wait(wait_s)
        self._detach_device()
        print("[info] device loop stopped", flush=True)

    def start_touchscreen_loop(self):
        while not self.stop_event.is_set():
            cfg = self.config_store.get()
            interval = 5
            should_apply = False
            device = self.device
            if device is not None and type(device).__name__ == "StreamDock293s":
                widgets_cfg = cfg.get("widgets", {})
                interval = int(widgets_cfg.get("refresh_seconds", 5))
                interval = max(1, min(60, interval))
                should_apply = any(
                    str(widgets_cfg.get(slot, {}).get("mode", "off")).lower() != "off"
                    for slot in ("16", "17", "18")
                ) or self.secondary_display_active
            else:
                ts_cfg = cfg.get("touchscreen", {})
                mode = str(ts_cfg.get("mode", "off")).lower()
                interval = int(ts_cfg.get("interval_seconds", 5))
                interval = max(1, min(60, interval))
                should_apply = mode != "off"

            if should_apply:
                with self.device_lock:
                    self._apply_touchscreen_locked()

            # Wait for next cycle, but wake immediately if refresh_event is set
            self.refresh_event.wait(timeout=interval)
            if self.refresh_event.is_set():
                self.refresh_event.clear()

    def reload_and_apply(self):
        """Reload config and push brightness + icons + display to device."""
        with self.device_lock:
            if self.device is None:
                return
            cfg = self.config_store.get()
            try:
                brightness = int(cfg["device"].get("brightness", 100))
                brightness = max(1, min(100, brightness))
                self.device.set_brightness(brightness)
            except Exception:
                pass
            self._apply_icons_locked()
            self.last_touchscreen_update_ts = 0.0
            self._apply_touchscreen_locked()
        # Wake the touchscreen loop immediately for the next render cycle
        self.refresh_event.set()

    def apply_scene(self, scene: Dict[str, Any]):
        """Load a scene's pages into the live config and push to device.

        Replaces the config's pages/active_page with the scene's, then merges
        touchscreen and widgets from the scene's active page so the full device
        state reflects the activated scene.
        """
        pages = scene.get("pages", [])
        if not pages:
            return
        active_page = int(scene.get("active_page", 0))
        active_page = max(0, min(len(pages) - 1, active_page))
        page_cfg = pages[active_page]

        # Scene pages are stored as {actions, touchscreen, widgets} dicts.
        # config.py expects pages[] to be flat button-key dicts ({1: {...}, ...}).
        flat_pages = [p.get("actions", p) if isinstance(p, dict) else {} for p in pages]

        cfg = self.config_store.get()
        cfg["pages"] = flat_pages
        cfg["active_page"] = active_page
        cfg["actions"] = page_cfg.get("actions", cfg.get("actions", {}))
        if "touchscreen" in page_cfg:
            cfg["touchscreen"] = page_cfg["touchscreen"]
        if "widgets" in page_cfg:
            cfg["widgets"] = page_cfg["widgets"]
        self.config_store.set(cfg)
        self.reload_and_apply()

    def stop(self):
        """Signal all loops to stop."""
        self.stop_event.set()
        self.refresh_event.set()  # Wake touchscreen loop so it exits promptly
