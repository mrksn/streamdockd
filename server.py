"""HTTP request handler for the streamdockd web UI."""

import json
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent

# Route prefix for per-scene operations (e.g. /api/scene/<name>)
_SCENE_PREFIX = "/api/scene/"


class RequestHandler(BaseHTTPRequestHandler):
    daemon_ref = None
    config_ref = None
    scene_ref = None

    def _send_json(self, data: Dict[str, Any], status=HTTPStatus.OK):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        return json.loads(payload.decode("utf-8"))

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        if path == "/api/preview":
            try:
                q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                icon = str(q.get("icon", [""])[0])
                color = str(q.get("color", ["ffffff"])[0])
                size_raw = str(q.get("size", ["84"])[0])
                try:
                    size = max(32, min(256, int(size_raw)))
                except Exception:
                    size = 84
                png = self.daemon_ref.icon_manager.build_button_preview_bytes(icon, color, size=size)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
            except Exception:
                self.send_error(HTTPStatus.BAD_REQUEST, "preview failed")
            return

        if path == "/api/config":
            self._send_json(self.config_ref.get())
            return

        # GET /api/scenes  →  list all scenes + active scene name
        if path == "/api/scenes":
            self._send_json({
                "scenes": self.scene_ref.list_scenes(),
                "active_scene": self.scene_ref.get_active_scene(),
            })
            return

        # GET /api/scenes/active  →  active scene name (or null)
        if path == "/api/scenes/active":
            self._send_json({"active_scene": self.scene_ref.get_active_scene()})
            return

        # GET /api/scene/<name>  →  full scene object (all pages)
        if path.startswith(_SCENE_PREFIX):
            name = urllib.parse.unquote(path[len(_SCENE_PREFIX):])
            if not name:
                self.send_error(HTTPStatus.BAD_REQUEST, "scene name required")
                return
            scene = self.scene_ref.get_scene(name)
            if scene is None:
                self.send_error(HTTPStatus.NOT_FOUND, f"scene '{name}' not found")
                return
            self._send_json({"name": name, **scene})
            return

        if path == "/":
            try:
                html = (BASE_DIR / "ui.html").read_text(encoding="utf-8").encode("utf-8")
            except Exception as exc:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"ui.html not found: {exc}")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/page":
            self._handle_page_action()
            return

        if path == "/api/config":
            try:
                data = self._read_json()
                saved = self.config_ref.set(data)
                self.daemon_ref.reload_and_apply()
                self._send_json(saved)
            except Exception as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        # POST /api/scenes/active  →  body: {"scene": "<name>"|null}
        if path == "/api/scenes/active":
            try:
                data = self._read_json()
                name = data.get("scene")
                ok = self.scene_ref.set_active_scene(name)
                if not ok:
                    self.send_error(HTTPStatus.NOT_FOUND, f"scene '{name}' not found")
                    return
                # Load the full scene (all pages) into the device
                scene = self.scene_ref.get_scene(name)
                if scene is not None:
                    self.daemon_ref.apply_scene(scene)
                self._send_json({"active_scene": self.scene_ref.get_active_scene()})
            except Exception as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        # POST /api/scene/<name>  →  create or replace a scene
        if path.startswith(_SCENE_PREFIX):
            name = urllib.parse.unquote(path[len(_SCENE_PREFIX):])
            if not name:
                self.send_error(HTTPStatus.BAD_REQUEST, "scene name required")
                return
            try:
                data = self._read_json()
                is_new = self.scene_ref.get_scene(name) is None
                saved = self.scene_ref.save_scene(name, data)
                status = HTTPStatus.CREATED if is_new else HTTPStatus.OK
                self._send_json({"name": name, **saved}, status=status)
            except Exception as exc:
                self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return

        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # DELETE /api/scene/<name>
        if path.startswith(_SCENE_PREFIX):
            name = urllib.parse.unquote(path[len(_SCENE_PREFIX):])
            if not name:
                self.send_error(HTTPStatus.BAD_REQUEST, "scene name required")
                return
            deleted = self.scene_ref.delete_scene(name)
            if not deleted:
                self.send_error(HTTPStatus.NOT_FOUND, f"scene '{name}' not found")
                return
            self._send_json({"deleted": name})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def _handle_page_action(self):
        """Handle POST /api/page — switch the active page without a full UI reload."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            req = json.loads(payload.decode("utf-8"))
            action = str(req.get("action", ""))
            config = self.config_ref.get()
            pages = config.get("pages", [])
            if not pages:
                self._send_json(config)
                return
            current = int(config.get("active_page", 0))
            count = len(pages)
            if action == "next":
                new_page = (current + 1) % count
            elif action == "prev":
                new_page = (current - 1) % count
            elif action == "goto":
                target = int(req.get("page", 1)) - 1
                new_page = max(0, min(count - 1, target))
            else:
                self.send_error(HTTPStatus.BAD_REQUEST, f"unknown action: {action}")
                return
            config["active_page"] = new_page
            config["actions"] = pages[new_page]
            saved = self.config_ref.set(config)
            self.daemon_ref.reload_and_apply()
            self._send_json(saved)
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, fmt, *args):
        print(f"[ui] {self.address_string()} - {fmt % args}", flush=True)
