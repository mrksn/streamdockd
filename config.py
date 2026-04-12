"""Config loading, path resolution, and thread-safe storage for streamdockd."""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

_BASE_DIR = Path(__file__).resolve().parent

BUTTONS_PER_PAGE = 15


def resolve_config_path() -> Path:
    env_path = os.environ.get("STREAMDOCKD_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    xdg_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_home:
        return Path(xdg_home).expanduser() / "streamdockd" / "config.json"

    return Path.home() / ".config" / "streamdockd" / "config.json"


def default_page_actions() -> Dict[str, Dict[str, Any]]:
    """Return a default set of blank button action configs for one page."""
    actions: Dict[str, Dict[str, Any]] = {}
    for i in range(1, BUTTONS_PER_PAGE + 1):
        actions[str(i)] = {
            "enabled": False,
            "type": "command",
            "command": "",
            "cwd": "",
            "icon": "",
            "icon_color": "ffffff",
            "run_on_release": False,
            "label": "",
            "label_pos": "bottom",
            "page": 1,
        }
    return actions


def default_config() -> Dict[str, Any]:
    page0 = default_page_actions()
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
        "pages": [page0],
        "active_page": 0,
        "actions": page0,
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

    def _merge_page_actions(self, template: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        """Merge incoming page actions over a template, ensuring all slots are present."""
        page: Dict[str, Any] = {str(i): dict(template[str(i)]) for i in range(1, BUTTONS_PER_PAGE + 1)}
        for key in page:
            page[key].update(incoming.get(key, {}))
        return page

    def _merge_defaults(self, data: Dict[str, Any]) -> Dict[str, Any]:
        merged = default_config()
        merged["ui"].update(data.get("ui", {}))
        merged["device"].update(data.get("device", {}))
        merged["touchscreen"].update(data.get("touchscreen", {}))
        merged["widgets"].update(data.get("widgets", {}))
        for slot in ("16", "17", "18"):
            merged["widgets"][slot].update(data.get("widgets", {}).get(slot, {}))

        template_page = default_page_actions()
        input_pages: Any = data.get("pages", None)
        active_page = int(data.get("active_page", 0))

        if isinstance(input_pages, list) and len(input_pages) > 0:
            merged_pages: List[Dict[str, Any]] = [
                self._merge_page_actions(template_page, p if isinstance(p, dict) else {})
                for p in input_pages
            ]
            active_page = max(0, min(len(merged_pages) - 1, active_page))
        else:
            # Legacy config: migrate flat "actions" dict → pages[0]
            page0 = self._merge_page_actions(template_page, data.get("actions", {}))
            merged_pages = [page0]
            active_page = 0

        merged["pages"] = merged_pages
        merged["active_page"] = active_page
        merged["actions"] = merged_pages[active_page]
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
