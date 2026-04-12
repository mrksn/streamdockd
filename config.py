"""Config loading, path resolution, and thread-safe storage for streamdockd."""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

_BASE_DIR = Path(__file__).resolve().parent


def resolve_config_path() -> Path:
    env_path = os.environ.get("STREAMDOCKD_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    xdg_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_home:
        return Path(xdg_home).expanduser() / "streamdockd" / "config.json"

    return Path.home() / ".config" / "streamdockd" / "config.json"


def default_config() -> Dict[str, Any]:
    actions: Dict[str, Dict[str, Any]] = {}
    for i in range(1, 16):
        actions[str(i)] = {
            "enabled": False,
            "command": "",
            "cwd": "",
            "icon": "",
            "icon_color": "ffffff",
            "run_on_release": False,
            "label": "",
            "label_pos": "bottom",
        }
    return {
        "ui": {"host": "127.0.0.1", "port": 17890},
        "device": {"brightness": 100, "reconnect_seconds": 2},
        "touchscreen": {
            "mode": "off",
            "interval_seconds": 5,
            "image": "",
        },
        "widgets": {
            "refresh_seconds": 5,
            "16": {"mode": "clock", "style": "bold", "image": "", "text": "", "label_pos": "off", "icon": "mdi:clock-outline", "icon_color": "ffffff"},
            "17": {"mode": "stats", "style": "bold", "image": "", "text": "", "label_pos": "off", "icon": "mdi:chart-box-outline", "icon_color": "ffffff"},
            "18": {"mode": "date", "style": "bold", "image": "", "text": "", "label_pos": "off", "icon": "mdi:calendar-month-outline", "icon_color": "ffffff"},
        },
        "actions": actions,
    }


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = self._load_or_init()

    def _load_or_init(self) -> Dict[str, Any]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.path = _BASE_DIR / ".streamdockd" / "config.json"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            data = default_config()
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return self._merge_defaults(data)
        except Exception:
            data = default_config()
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data

    def _merge_defaults(self, data: Dict[str, Any]) -> Dict[str, Any]:
        merged = default_config()
        merged["ui"].update(data.get("ui", {}))
        merged["device"].update(data.get("device", {}))
        merged["touchscreen"].update(data.get("touchscreen", {}))
        merged["widgets"].update(data.get("widgets", {}))
        for slot in ("16", "17", "18"):
            merged["widgets"][slot].update(data.get("widgets", {}).get(slot, {}))
        input_actions = data.get("actions", {})
        for key, action in merged["actions"].items():
            action.update(input_actions.get(key, {}))
        return merged

    def get(self) -> Dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def set(self, data: Dict[str, Any]) -> Dict[str, Any]:
        merged = self._merge_defaults(data)
        with self.lock:
            self.data = merged
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            return json.loads(json.dumps(self.data))
