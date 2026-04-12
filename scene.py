"""Scene storage: named collections of pages (button + display configs)."""

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


__all__ = ["SceneStore"]


def _default_page_config() -> Dict[str, Any]:
    """Return a single blank page config with 15 button actions + touchscreen + widgets."""
    actions: Dict[str, Dict[str, Any]] = {}
    for i in range(1, 16):
        actions[str(i)] = {
            "enabled": False,
            "type": "command",
            "command": "",
            "cwd": "",
            "icon": "",
            "icon_color": "ffffff",
            "label": "",
            "label_pos": "bottom",
            "page": 1,
        }
    return {
        "actions": actions,
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
    }


def _empty_store() -> Dict[str, Any]:
    return {"active_scene": None, "scenes": {}}


class SceneStore:
    """Thread-safe storage for named scenes.

    Each scene holds an ordered list of pages.  Each page is a dict with keys
    ``actions``, ``touchscreen``, and ``widgets`` – mirroring the corresponding
    sections of the main config.  A scene also records which page is currently
    active (``active_page`` index).

    The store tracks which scene is globally active (``active_scene``).
    Activating a scene applies its current page's config to the device via the
    daemon's ``apply_scene_page`` method.
    """

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = self._load_or_init()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_init(self) -> Dict[str, Any]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not self.path.exists():
            data = _empty_store()
            self._write(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if "scenes" not in data:
                data["scenes"] = {}
            if "active_scene" not in data:
                data["active_scene"] = None
            return data
        except Exception:
            data = _empty_store()
            self._write(data)
            return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _copy(obj: Any) -> Any:
        return json.loads(json.dumps(obj))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_scenes(self) -> List[str]:
        """Return a list of all scene names."""
        with self.lock:
            return list(self.data["scenes"].keys())

    def get_active_scene(self) -> Optional[str]:
        """Return the name of the currently active scene, or None."""
        with self.lock:
            return self.data.get("active_scene")

    def get_scene(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a deep copy of the named scene, or None if not found.

        A scene object has the shape::

            {
                "active_page": 0,
                "pages": [
                    {
                        "actions":     { "1": {...}, ..., "15": {...} },
                        "touchscreen": { ... },
                        "widgets":     { ... }
                    },
                    ...
                ]
            }
        """
        with self.lock:
            scene = self.data["scenes"].get(name)
            if scene is None:
                return None
            return self._copy(scene)

    def save_scene(self, name: str, scene_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or replace a scene.

        *scene_data* must contain a ``pages`` list.  If it is absent or not a
        list, the scene is initialised with one blank page.  Returns a deep copy
        of the stored scene.
        """
        with self.lock:
            if not isinstance(scene_data.get("pages"), list):
                scene_data = {"active_page": 0, "pages": [_default_page_config()]}
            else:
                scene_data = self._copy(scene_data)
                scene_data.setdefault("active_page", 0)
            self.data["scenes"][name] = scene_data
            self._write(self.data)
            return self._copy(scene_data)

    def delete_scene(self, name: str) -> bool:
        """Delete a scene.  Returns True if the scene existed, False otherwise.

        If the deleted scene was active, ``active_scene`` is cleared.
        """
        with self.lock:
            if name not in self.data["scenes"]:
                return False
            del self.data["scenes"][name]
            if self.data.get("active_scene") == name:
                self.data["active_scene"] = None
            self._write(self.data)
            return True

    def set_active_scene(self, name: Optional[str]) -> bool:
        """Mark *name* as the active scene.

        Pass ``None`` to deactivate all scenes.  Returns False if *name* is not
        None and does not refer to a known scene.
        """
        with self.lock:
            if name is not None and name not in self.data["scenes"]:
                return False
            self.data["active_scene"] = name
            self._write(self.data)
            return True

    def get_active_page_config(self) -> Optional[Dict[str, Any]]:
        """Return the page config (actions + touchscreen + widgets) for the active
        scene's active page, or None if no scene is active."""
        with self.lock:
            name = self.data.get("active_scene")
            if not name:
                return None
            scene = self.data["scenes"].get(name)
            if not scene or not scene.get("pages"):
                return None
            pages = scene["pages"]
            try:
                idx = int(scene.get("active_page", 0))
            except (TypeError, ValueError):
                idx = 0
            idx = max(0, min(idx, len(pages) - 1))
            return self._copy(pages[idx])

    def get_all_pages(self, name: str) -> Optional[List[Dict[str, Any]]]:
        """Return a deep copy of all pages for the named scene, or None."""
        with self.lock:
            scene = self.data["scenes"].get(name)
            if scene is None:
                return None
            return self._copy(scene.get("pages", []))
