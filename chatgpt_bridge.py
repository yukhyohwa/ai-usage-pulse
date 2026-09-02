"""Loopback-only receiver for the UsagePulse Chrome extension."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    # A second instance would split extension updates between two widgets.
    allow_reuse_address = False
    daemon_threads = True


class ChatGPTUsageBridge:
    """Receive display-only usage values; credentials are never accepted."""

    def __init__(self, port: int = 8765) -> None:
        self._lock = threading.Lock()
        self._payload: dict[str, Any] = {}
        self._refresh_version = 0
        self._last_page_heartbeat = 0.0
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, status: int, body: dict[str, Any]) -> None:
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(encoded)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_json(204, {})

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    self.send_json(200, {"ok": True})
                elif self.path == "/chatgpt-refresh-version":
                    with bridge._lock:
                        version = bridge._refresh_version
                    self.send_json(200, {"version": version})
                else:
                    self.send_json(404, {"ok": False})

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/chatgpt-page-heartbeat":
                    # Posted only while a ChatGPT page with the extension is loaded.
                    with bridge._lock:
                        bridge._last_page_heartbeat = time.monotonic()
                    self.send_json(200, {"ok": True})
                    return
                if self.path != "/chatgpt-usage":
                    self.send_json(404, {"ok": False})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4096:
                        raise ValueError("invalid payload size")
                    payload = json.loads(self.rfile.read(size))
                    if not isinstance(payload, dict):
                        raise ValueError("payload must be an object")
                    allowed = {
                        "five_hour",
                        "weekly",
                        "reset_time",
                        "reset_cards",
                        "captured_at",
                        "source_url",
                    }
                    with bridge._lock:
                        bridge._payload = {
                            key: str(value)[:240]
                            for key, value in payload.items()
                            if key in allowed and value
                        }
                    self.send_json(200, {"ok": True})
                except (ValueError, json.JSONDecodeError):
                    self.send_json(400, {"ok": False})

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ReusableThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="chatgpt-usage-bridge",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._payload.copy()

    def request_refresh(self) -> None:
        """Notify an open Chrome Usage page that the user requested a refresh."""
        with self._lock:
            self._refresh_version += 1

    def has_active_page(self, max_age_seconds: float = 8.0) -> bool:
        """Whether a ChatGPT page with the companion extension is still open."""
        with self._lock:
            return time.monotonic() - self._last_page_heartbeat <= max_age_seconds

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
