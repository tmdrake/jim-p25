"""Local page for one P25 Phase 1 simplex channel. Bind to localhost only."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from radio import Radio
from settings import SettingsError, channel_from_json, load_form, save_form

HERE = Path(__file__).resolve().parent
INDEX = (HERE / "index.html").read_text(encoding="utf-8")
SETTINGS = HERE.parent / "local" / "settings.json"
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
        if path == "/ws/pcm":
            self._pcm_socket()
            return
        if path == "/ws/mic":
            self._mic_socket()
            return
        if path == "/":
            self._send(200, INDEX.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self._json(200, RADIO.status())
            return
        if path == "/api/spectrum":
            self._json(200, RADIO.spectrum())
            return
        if path == "/api/log":
            self._json(200, RADIO.stack_log())
            return
        if path == "/api/settings":
            self._json(200, load_form(SETTINGS))
            return
        if path == "/api/pcm":
            pcm = RADIO.take_pcm()
            if not pcm:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self._send(200, pcm, "application/octet-stream")
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
            if path == "/api/settings":
                self._json(200, save_form(SETTINGS, data))
                return
            if path == "/api/sql":
                from radio import LOCAL
                from settings import form_from_json
                form = load_form(SETTINGS)
                form.update(data)
                saved = save_form(SETTINGS, form)
                (LOCAL / "sql.live").write_text(saved.get("sql", "0") + "\n", encoding="utf-8")
                self._json(200, {"sql": saved.get("sql", "0")})
                return
            channel = channel_from_json(data)
            if path in ("/api/listen", "/api/tx"):
                save_form(SETTINGS, data)
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

    def _pcm_socket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self._json(400, {"error": "Expected a WebSocket key."})
            return
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        conn = self.connection
        conn.setblocking(False)
        try:
            while True:
                chunk = RADIO.take_pcm()
                if chunk:
                    size = len(chunk)
                    if size < 126:
                        header = bytes((0x82, size))
                    else:
                        header = bytes((0x82, 126)) + struct.pack("!H", size)
                    conn.sendall(header + chunk)
                else:
                    time.sleep(0.004)
                try:
                    incoming = conn.recv(256)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not incoming:
                    break
                if incoming[0] & 0x0F == 0x8:
                    break
        except OSError:
            return

    def _mic_socket(self) -> None:
        from radio import MIC_PORT

        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self._json(400, {"error": "Expected a WebSocket key."})
            return
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        conn = self.connection
        conn.setblocking(True)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while True:
                payload = _ws_read_binary(conn)
                if payload is None:
                    break
                if payload:
                    udp.sendto(payload, ("127.0.0.1", MIC_PORT))
        except OSError:
            return
        finally:
            udp.close()


def _recvall(conn: socket.socket, count: int) -> bytes | None:
    buf = b""
    while len(buf) < count:
        part = conn.recv(count - len(buf))
        if not part:
            return None
        buf += part
    return buf


def _ws_read_binary(conn: socket.socket) -> bytes | None:
    hdr = _recvall(conn, 2)
    if hdr is None:
        return None
    opcode = hdr[0] & 0x0F
    length = hdr[1] & 0x7F
    masked = bool(hdr[1] & 0x80)
    if length == 126:
        ext = _recvall(conn, 2)
        if ext is None:
            return None
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = _recvall(conn, 8)
        if ext is None:
            return None
        length = struct.unpack("!Q", ext)[0]
    mask = b""
    if masked:
        got = _recvall(conn, 4)
        if got is None:
            return None
        mask = got
    data = _recvall(conn, length)
    if data is None:
        return None
    if masked:
        data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    if opcode == 0x8:
        return None
    if opcode != 0x2:
        return b""
    return data


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
