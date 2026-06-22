"""Health check / readiness probe for the OL MCP server.

Phase 4.5: exposes a ``HealthHandler`` class with a ``check()``
method that returns a JSON-serializable dict::

    {
        "status": "ok",
        "module": "ol",
        "version": "0.4.4",
        "uptime_s": 123
    }

A separate HTTP endpoint can be started on ``OMNI_HEALTH_PORT``
(default 8766) via ``start_health_server()``; this is **never**
on the same port as the MCP stdio transport (which would corrupt
the JSON-RPC stream).

The HTTP handler uses only the stdlib ``http.server`` (no FastAPI
or other deps, to honor the no-new-deps rule).
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODULE_NAME = "ol"
DEFAULT_HEALTH_PORT = 8766
_start_time: float = time.monotonic()


def _version() -> str:
    try:
        from ol import __version__  # type: ignore
        return str(__version__)
    except Exception:
        return "unknown"


def check() -> dict[str, Any]:
    return {
        "status": "ok",
        "module": MODULE_NAME,
        "version": _version(),
        "uptime_s": int(max(0, time.monotonic() - _start_time)),
    }


def _health_port() -> int:
    raw = os.environ.get("OMNI_HEALTH_PORT", "").strip()
    if not raw:
        return DEFAULT_HEALTH_PORT
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_HEALTH_PORT


def _health_host() -> str:
    return os.environ.get("OMNI_HEALTH_HOST", "127.0.0.1").strip() or "127.0.0.1"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server API
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health", "/healthz", "/ready"):
            body = json.dumps(check(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — http.server API
        return  # silence default access log


_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()


def start_health_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer | None:
    global _server
    if os.environ.get("OMNI_HEALTH_ENABLED", "").strip().lower() not in (
        "1", "true", "yes", "on"
    ):
        return None
    with _server_lock:
        if _server is not None:
            return _server
        bind_host = host or _health_host()
        bind_port = port if port is not None else _health_port()
        srv = ThreadingHTTPServer((bind_host, bind_port), HealthHandler)
        t = threading.Thread(target=srv.serve_forever, name="ol-health", daemon=True)
        t.start()
        _server = srv
        return srv


def stop_health_server() -> None:
    global _server
    with _server_lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
            _server = None


__all__ = [
    "MODULE_NAME",
    "DEFAULT_HEALTH_PORT",
    "check",
    "HealthHandler",
    "start_health_server",
    "stop_health_server",
]
