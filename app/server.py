"""Local page for one P25 Phase 1 simplex channel. Bind to localhost only."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from radio import Radio
from settings import SettingsError, channel_from_json

HERE = Path(__file__).resolve().parent
INDEX = (HERE / "index.html").read_text(encoding="utf-8")
RADIO = Radio()
HOST = "127.0.0.1"
PORT = 8765


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8192:
            raise SettingsError("Request is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SettingsError("Request was not JSON.") from exc
        return data

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, INDEX.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self._json(200, RADIO.status())
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            data = self._read_json()
            if path == "/api/stop":
                RADIO.stop()
                self._json(200, RADIO.status())
                return
            if path == "/api/release":
                RADIO.release()
                self._json(200, RADIO.status())
                return
            channel = channel_from_json(data)
            if path == "/api/listen":
                RADIO.listen(channel)
                self._json(200, RADIO.status())
                return
            if path == "/api/tx":
                result = RADIO.transmit(channel, dry_run=bool(data.get("dry_run")))
                if data.get("dry_run"):
                    self._json(200, result)
                else:
                    self._json(200, RADIO.status())
                return
            self._json(404, {"error": "Not found"})
        except SettingsError as exc:
            self._json(400, {"error": str(exc)})


def main() -> None:
    RADIO.stop()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"jim-p25 page at http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        RADIO.stop()
        server.server_close()


if __name__ == "__main__":
    main()
