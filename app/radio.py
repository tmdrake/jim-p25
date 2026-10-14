"""Start and stop boatbod OP25 for one Phase 1 conventional channel.

HackRF is half duplex, so listen and transmit never run together.
Transmit is the 1011 Hz Phase 1 test tone with the NAC, talkgroup, and
source ID from the page. Algorithm ID is fixed at 0x80 (clear).
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

from settings import TX_SUPERFRAMES, SettingsError

OP25_APPS = Path(os.environ.get("OP25_APPS", "/root/op25/op25/gr-op25_repeater/apps"))
REPO = Path(__file__).resolve().parent.parent
LOCAL = REPO / "local"
RX_HTTP = "127.0.0.1:18765"
# 160 samples of 8000 Hz 16-bit audio, one IMBE voice frame.
PCM_BYTES = 320
PCM_PORT = 23456
# HackRF LO sits this far above the channel so the DC spike is not on the tuned frequency.
TUNER_OFFSET_HZ = 50_000
RX_RATE_HZ = 2_000_000
SPEC_PORT = 23457

_NAC_RE = re.compile(r"\bNAC[:\s]+(0x[0-9a-fA-F]{1,3}|\d+)\b")
_TG_RE = re.compile(r"tgid\((\d+)\)", re.IGNORECASE)


class RadioBusy(SettingsError):
    pass


def _env(unbuffered: bool = False) -> dict:
    """Build the child environment.

    rx.py turns off stderr buffering with detach().detach(). That crashes
    when Python is already unbuffered, because stderr is a raw FileIO.
    Transmit does not do that, so only the transmitter is unbuffered.
    """
    env = os.environ.copy()
    env.pop("PYTHONUNBUFFERED", None)
    if unbuffered:
        env["PYTHONUNBUFFERED"] = "1"
    pulse = "/mnt/wslg/PulseServer"
    if os.path.exists(pulse):
        env["PULSE_SERVER"] = "unix:" + pulse
    return env


def _tx_env(unbuffered: bool) -> dict:
    env = _env(unbuffered=unbuffered)
    env["JIM_TX_SHIFT_HZ"] = str(TUNER_OFFSET_HZ)
    env["JIM_TX_RATE_HZ"] = "2000000"
    env["JIM_DV_TX"] = str(OP25_APPS / "tx" / "dv_tx.py")
    return env


class _PcmTap:
    """Collect the vocoder's UDP audio. Control packets are not 320 bytes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._run = False
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", PCM_PORT))
        sock.settimeout(0.4)
        self._sock = sock
        self._run = True
        with self._lock:
            self._buf.clear()
        thread = threading.Thread(target=self._loop, name="pcm", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._run = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            sock.close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
        with self._lock:
            self._buf.clear()

    def _loop(self) -> None:
        sock = self._sock
        while self._run and sock is not None:
            try:
                data, _addr = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            if len(data) != PCM_BYTES:
                continue
            with self._lock:
                self._buf.extend(data)
                extra = len(self._buf) - 8000 * 2 * 2
                if extra > 0:
                    del self._buf[:extra]

    def take(self) -> bytes:
        with self._lock:
            data = bytes(self._buf)
            self._buf.clear()
            return data


class _SpectrumTap:
    """Latest waterfall row from the listen process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: dict | None = None
        self._run = False
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", SPEC_PORT))
        sock.settimeout(0.4)
        self._sock = sock
        self._run = True
        with self._lock:
            self._frame = None
        thread = threading.Thread(target=self._loop, name="spectrum", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._run = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            sock.close()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    def _loop(self) -> None:
        sock = self._sock
        while self._run and sock is not None:
            try:
                data, _addr = sock.recvfrom(65535)
            except (socket.timeout, OSError):
                continue
            try:
                frame = json.loads(data.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(frame, dict) or not isinstance(frame.get("db"), list):
                continue
            with self._lock:
                self._frame = frame

    def latest(self) -> dict | None:
        with self._lock:
            if self._frame is None:
                return None
            return dict(self._frame)


def _tail(path: Path, limit: int = 65536) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()[-limit:]
    return data.decode("utf-8", "replace")


def _stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=3)


def write_trunk(channel: dict, path: Path) -> None:
    """One conventional Phase 1 row. tdma is not set."""
    mhz = f"{channel['frequency_mhz']:.6f}".rstrip("0").rstrip(".")
    header = (
        '"Sysname"\t"Control Channel List"\t"Offset"\t"NAC"\t"Modulation"\t'
        '"TGID Tags File"\t"Whitelist"\t"Blacklist"\t"Center Frequency"\n'
    )
    row = (
        f'"simplex"\t"{mhz}"\t"0"\t"{channel["nac_hex"]}"\t"cqpsk"\t'
        '""\t""\t""\t""\n'
    )
    path.write_text(header + row, encoding="utf-8")


def rx_command(channel: dict, trunk_path: Path) -> list[str]:
    gains = f"RF:0,IF:{channel['rx_gain']},BB:{channel['bb_gain']}"
    return [
        "python3",
        str(REPO / "app" / "listen_fft.py"),
        "--args",
        "hackrf",
        "-N",
        gains,
        "-S",
        str(RX_RATE_HZ),
        "-f",
        str(channel["frequency_hz"]),
        "-o",
        str(TUNER_OFFSET_HZ),
        "-q",
        str(channel["ppm"]),
        "-D",
        "cqpsk",
        "-T",
        str(trunk_path),
        "-V",
        "-w",
        "-l",
        f"http:{RX_HTTP}",
        "-v",
        "1",
    ]


def craft_command(channel: dict, out_path: Path) -> list[str]:
    return [
        "python3",
        str(OP25_APPS / "tx" / "p25craft.py"),
        "--superframes",
        str(TX_SUPERFRAMES),
        "--nac",
        str(channel["nac"]),
        "--tgid",
        str(channel["tgid"]),
        "--src",
        str(channel["src"]),
        "--dst",
        "1",
        "--algid",
        str(channel["algid"]),
        "--kid",
        "0",
        "--mi",
        "0",
        "--mfid",
        "0",
        "--lco",
        "0",
        "--sqtail",
        "0:1:2",
        "--1011",
        "--quiet",
        "--output-file",
        str(out_path),
    ]


def unpack_command(packed: Path, symbols: Path) -> list[str]:
    return [
        "python3",
        str(OP25_APPS / "tx" / "unpack.py"),
        "-i",
        str(packed),
        "-o",
        str(symbols),
    ]


def tx_command(channel: dict, symbols: Path, iq_path: Path | None) -> list[str]:
    cmd = [
        "python3",
        str(REPO / "app" / "tx_offset.py"),
        "-p",
        "p25",
        "-t",
        str(symbols),
        "-Q",
        str(channel["frequency_hz"]),
        "-q",
        str(channel["ppm"]),
        "-v",
        "1",
        "-i",
        "2000000",
        "-r",
    ]
    if iq_path is None:
        # buffers cushions USB stalls. Each stall is a "U" and a gap of silence.
        cmd.extend(
            [
                "--args",
                "hackrf,buffers=64",
                "-N",
                f"RF:0,IF:{channel['tx_if_gain']}",
            ]
        )
    else:
        cmd.extend(["-o", str(iq_path)])
    return cmd


class Radio:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode = "idle"
        self._proc: subprocess.Popen | None = None
        self._resume_listen = False
        self._channel: dict | None = None
        self._message = "Idle"
        self._timer: threading.Timer | None = None
        self._pcm = _PcmTap()
        self._spec = _SpectrumTap()
        LOCAL.mkdir(exist_ok=True)

    def _hackrf_ready(self) -> str:
        if self._proc is not None and self._proc.poll() is None:
            return "busy"
        try:
            proc = subprocess.run(
                ["hackrf_info"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "missing"
        text = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and "Found HackRF" in text:
            return "ready"
        return "missing"

    def _decoded(self) -> tuple[str, str]:
        text = _tail(LOCAL / "rx.log")
        nac = ""
        tg = ""
        found = _NAC_RE.findall(text)
        if found:
            token = found[-1]
            nac = token if token.lower().startswith("0x") else f"0x{int(token):03x}"
        groups = _TG_RE.findall(text)
        if groups:
            tg = groups[-1]
        return nac, tg

    def status(self) -> dict:
        exited = False
        with self._lock:
            if self._proc is not None and self._proc.poll() is not None:
                code = self._proc.returncode
                if self._mode != "idle":
                    self._message = f"{self._mode} stopped (exit {code})"
                self._mode = "idle"
                self._proc = None
                exited = True
            mode = self._mode
            message = self._message
            channel = dict(self._channel) if self._channel else None
        if exited:
            self._pcm.stop()
            self._spec.stop()
        nac, tg = self._decoded() if mode == "listen" else ("", "")
        device = "busy" if mode in ("listen", "tx") else self._hackrf_ready()
        view = None
        if channel:
            view = {
                "frequency_mhz": channel["frequency_mhz"],
                "nac_hex": channel["nac_hex"],
                "tgid": channel["tgid"],
                "src": channel["src"],
            }
        return {
            "mode": mode,
            "device": device,
            "message": message,
            "nac_decoded": nac,
            "talkgroup": tg,
            "channel": view,
        }

    def take_pcm(self) -> bytes:
        return self._pcm.take()

    def spectrum(self) -> dict:
        with self._lock:
            listening = self._mode == "listen"
        frame = self._spec.latest() or {}
        return {
            "listening": listening,
            "tuned_hz": frame.get("tuned_hz"),
            "span_hz": frame.get("span_hz", RX_RATE_HZ),
            "offset_hz": frame.get("offset_hz", TUNER_OFFSET_HZ),
            "db": frame.get("db"),
        }

    def stop(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
            proc = self._proc
            self._proc = None
            was = self._mode
            self._mode = "idle"
            self._resume_listen = False
            if was != "idle":
                self._message = "Stopped"
        if timer:
            timer.cancel()
        self._pcm.stop()
        self._spec.stop()
        _stop_process(proc)

    def listen(self, channel: dict) -> None:
        apps = OP25_APPS / "rx.py"
        if not apps.exists():
            raise SettingsError("OP25 is not installed yet.")
        with self._lock:
            if self._mode != "idle":
                raise RadioBusy("Stop the radio before listening again.")
            LOCAL.mkdir(exist_ok=True)
            trunk = LOCAL / "trunk.tsv"
            write_trunk(channel, trunk)
            log = open(LOCAL / "rx.log", "w", encoding="utf-8")
            cmd = rx_command(channel, trunk)
            try:
                self._pcm.start()
                self._spec.start()
            except OSError as exc:
                self._pcm.stop()
                self._spec.stop()
                log.close()
                raise SettingsError("The voice port is already in use.") from exc
            env = _env()
            env["JIM_TUNED_HZ"] = str(channel["frequency_hz"])
            env["JIM_OFFSET_HZ"] = str(TUNER_OFFSET_HZ)
            env["JIM_SPAN_HZ"] = str(RX_RATE_HZ)
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(OP25_APPS),
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                self._pcm.stop()
                self._spec.stop()
                log.close()
                raise
            self._proc = proc
            self._mode = "listen"
            self._channel = channel
            self._message = (
                f"Listening on {channel['frequency_mhz']} MHz. "
                "Voice plays in this browser."
            )
            log.close()

    def _build_symbols(self, channel: dict) -> Path:
        LOCAL.mkdir(exist_ok=True)
        packed = LOCAL / "p25.out"
        symbols = LOCAL / "p25.dat"
        craft = subprocess.run(
            craft_command(channel, packed),
            cwd=str(LOCAL),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if craft.returncode != 0 or not packed.exists() or packed.stat().st_size == 0:
            detail = (craft.stderr or craft.stdout or "p25craft failed").strip()
            raise SettingsError(detail[-500:])
        unpacked = subprocess.run(
            unpack_command(packed, symbols),
            cwd=str(OP25_APPS / "tx"),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if unpacked.returncode != 0 or not symbols.exists() or symbols.stat().st_size == 0:
            detail = (unpacked.stderr or unpacked.stdout or "unpack failed").strip()
            raise SettingsError(detail[-500:])
        return symbols

    def transmit(self, channel: dict, dry_run: bool = False) -> dict:
        if not (OP25_APPS / "tx" / "dv_tx.py").exists():
            raise SettingsError("OP25 is not installed yet.")
        symbols = self._build_symbols(channel)
        if dry_run:
            iq = LOCAL / "dry.iq"
            if iq.exists():
                iq.unlink()
            cmd = tx_command(channel, symbols, iq)
            proc = subprocess.Popen(
                cmd,
                cwd=str(OP25_APPS / "tx"),
                env=_tx_env(unbuffered=False),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                _stop_process(proc)
            size = iq.stat().st_size if iq.exists() else 0
            if iq.exists():
                iq.unlink()
            if size <= 0:
                raise SettingsError("Transmit dry run wrote no samples.")
            return {"ok": True, "iq_bytes": size, "nac_hex": channel["nac_hex"], "algid": channel["algid"]}

        with self._lock:
            resume = self._mode == "listen"
            proc = self._proc
            self._proc = None
            self._mode = "idle"
        _stop_process(proc)
        with self._lock:
            log = open(LOCAL / "tx.log", "w", encoding="utf-8")
            cmd = tx_command(channel, symbols, None)
            started = subprocess.Popen(
                cmd,
                cwd=str(OP25_APPS / "tx"),
                env=_tx_env(unbuffered=True),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._proc = started
            self._mode = "tx"
            self._channel = channel
            self._resume_listen = resume
            self._message = (
                f"Transmitting test tone on {channel['frequency_mhz']} MHz. "
                "The tuner is 50 kHz higher, so the DC spike stays off the carrier. "
                "Press Stop to end it."
            )
            log.close()
        time.sleep(0.6)
        if started.poll() is not None:
            with self._lock:
                self._proc = None
                self._mode = "idle"
                self._resume_listen = False
                self._message = "Transmit stopped."
            detail = (LOCAL / "tx.log").read_text(encoding="utf-8", errors="replace").strip()
            raise SettingsError(detail[-500:] or "Transmit process exited.")
        return {"ok": True, "nac_hex": channel["nac_hex"], "algid": channel["algid"]}

    def release(self) -> None:
        with self._lock:
            if self._mode != "tx":
                return
            timer = self._timer
            self._timer = None
            proc = self._proc
            self._proc = None
            resume = self._resume_listen
            channel = self._channel
            self._mode = "idle"
            self._resume_listen = False
            self._message = "Transmit stopped"
        if timer:
            timer.cancel()
        _stop_process(proc)
        if resume and channel:
            time.sleep(0.5)
            self.listen(channel)
