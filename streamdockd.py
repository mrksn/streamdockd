#!/usr/bin/env python3
"""Thin entrypoint for streamdockd — wires modules together and starts the daemon."""

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

# Ensure the SDK is on the path (needed when running directly, not via launcher)
_base = Path(__file__).resolve().parent
_sdk_src = _base / "src"
if str(_sdk_src) not in sys.path:
    sys.path.insert(0, str(_sdk_src))

from config import ConfigStore, resolve_config_path
from device import StreamDockDaemon
from icon_manager import IconManager
from server import RequestHandler
from widgets import WidgetRenderer


def main():
    config_store = ConfigStore(resolve_config_path())
    icon_manager = IconManager()
    widget_renderer = WidgetRenderer(icon_manager)
    daemon = StreamDockDaemon(config_store, icon_manager, widget_renderer)

    cfg = config_store.get()
    host = str(cfg["ui"].get("host", "127.0.0.1"))
    port = int(cfg["ui"].get("port", 17890))

    RequestHandler.daemon_ref = daemon
    RequestHandler.config_ref = config_store

    device_thread = threading.Thread(target=daemon.start_device_loop, daemon=True)
    device_thread.start()
    touchscreen_thread = threading.Thread(target=daemon.start_touchscreen_loop, daemon=True)
    touchscreen_thread.start()

    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"[info] streamdockd ui: http://{host}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        daemon.stop()
        device_thread.join(timeout=5)
        touchscreen_thread.join(timeout=5)
        print("[info] streamdockd stopped", flush=True)


if __name__ == "__main__":
    main()
