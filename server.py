"""HTTP request handler for the streamdockd web UI."""

import json
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent


class RequestHandler(BaseHTTPRequestHandler):
    daemon_ref = None
    config_ref = None

    def _send_json(self, data: Dict[str, Any], status=HTTPStatus.OK):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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

    def do_POST(self):
        if self.path != "/api/config":
            self.send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            data = json.loads(payload.decode("utf-8"))
            saved = self.config_ref.set(data)
            self.daemon_ref.reload_and_apply()
            self._send_json(saved)
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, fmt, *args):
        print(f"[ui] {self.address_string()} - {fmt % args}", flush=True)
