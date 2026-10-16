"""Start OP25 listen and publish a spectrum row for the page waterfall.

The HackRF local oscillator is TUNER offset above the channel. The row is
shifted so column center is the channel. The DC spike stays on the oscillator.
Gnuplot is not opened. This file is the process Start-P25 stops with the receiver.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

OP25_APPS = os.environ.get("OP25_APPS", "/root/op25/op25/gr-op25_repeater/apps")
sys.path.insert(0, OP25_APPS)

import gr_gnuplot
import numpy as np

from analog import AnalogDemod, PCM_SAMPLES, to_pcm
from moddetect import classify_am_fm
from settings import listen_mode, sql_level

SPEC_PORT = 23457
ANALOG_PORT = 23458
_IQ_LEN = 16384
_sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_DGRAM)
_audio_sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_DGRAM)
_next = 0.0
_iq = np.zeros(_IQ_LEN, dtype=np.complex64)
_iq_pos = 0
_last_mod = "unknown"
_listen_mode = "p25"
_mode_at = 0.0
_demod: AnalogDemod | None = None
_fm_buf = np.zeros(0, dtype=np.float32)
_iq_q: queue.Queue = queue.Queue(maxsize=4)


def _collect(buf: object) -> None:
    global _iq_pos
    chunk = np.asarray(buf, dtype=np.complex64).ravel()
    if chunk.size == 0:
        return
    if chunk.size >= _IQ_LEN:
        _iq[:] = chunk[-_IQ_LEN:]
        _iq_pos = 0
        return
    end = _iq_pos + chunk.size
    if end <= _IQ_LEN:
        _iq[_iq_pos:end] = chunk
    else:
        split = _IQ_LEN - _iq_pos
        _iq[_iq_pos:] = chunk[:split]
        _iq[: chunk.size - split] = chunk[split:]
    _iq_pos = end % _IQ_LEN


class _Quiet:
    def __init__(self) -> None:
        self.returncode = None
        self.stdin = self

    def write(self, _data: object) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.returncode = 0


def _attach(self: object) -> None:
    self.gp = _Quiet()


def _publish(avg_pwr: np.ndarray) -> None:
    global _next
    now = time.time()
    if now < _next:
        return
    _next = now + 0.1
    tuned = int(os.environ.get("JIM_TUNED_HZ", "0"))
    offset = int(os.environ.get("JIM_OFFSET_HZ", "50000"))
    span = int(os.environ.get("JIM_SPAN_HZ", "2000000"))
    count = int(avg_pwr.shape[0])
    if count < 16 or span <= 0:
        return
    power = np.asarray(avg_pwr, dtype=np.float64)
    if float(np.min(power)) <= 0:
        return
    shift = int(round(offset / (span / count)))
    centered = np.empty(count, dtype=np.float64)
    floor = float(np.percentile(power, 20))
    centered.fill(floor)
    if shift >= 0:
        if shift < count:
            centered[shift:] = power[: count - shift]
    elif -shift < count:
        centered[: count + shift] = power[-shift:]
    db = 20.0 * np.log10(np.maximum(centered, 1e-12))
    low = float(np.percentile(db, 10))
    high = float(np.percentile(db, 99.5))
    if high - low < 6:
        high = low + 6
    scaled = np.clip((db - low) / (high - low) * 255.0, 0, 255).astype(np.uint8)
    ordered = np.concatenate((_iq[_iq_pos:], _iq[:_iq_pos]))
    kind = classify_am_fm(ordered, float(span), float(offset))
    global _last_mod
    _last_mod = kind["mod"]
    payload = json.dumps(
        {
            "tuned_hz": tuned,
            "span_hz": span,
            "offset_hz": offset,
            "db": scaled.tolist(),
            "mod": kind["mod"],
            "env_cv": kind["env_cv"],
            "dev_hz": kind["dev_hz"],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        _sock.sendto(payload, ("127.0.0.1", SPEC_PORT))
    except OSError:
        return


_plot = gr_gnuplot.wrap_gp.plot


def _refresh_mode() -> str:
    global _listen_mode, _mode_at
    now = time.time()
    if now - _mode_at < 0.3:
        return _listen_mode
    _mode_at = now
    try:
        _listen_mode = listen_mode(Path(__file__).resolve().parent.parent / "local" / "settings.json")
    except Exception:
        pass
    return _listen_mode


def _emit_audio() -> None:
    global _fm_buf
    settings = Path(__file__).resolve().parent.parent / "local" / "settings.json"
    while _fm_buf.size >= PCM_SAMPLES:
        frame = _fm_buf[:PCM_SAMPLES]
        _fm_buf = _fm_buf[PCM_SAMPLES:]
        if _refresh_mode() != "nbfm":
            continue
        sql = 0
        try:
            live = settings.parent / "sql.live"
            if live.is_file():
                sql = max(0, min(100, int(float(live.read_text().strip() or "0"))))
            else:
                sql = sql_level(settings)
        except Exception:
            sql = 0
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        # SQL 0 is open (always audio). Higher mutes hiss. Silence keeps the stream timed.
        if sql > 0 and rms < 0.002 + (sql / 100.0) * 0.08:
            frame = np.zeros_like(frame)
        try:
            _audio_sock.sendto(to_pcm(frame), ("127.0.0.1", ANALOG_PORT))
        except OSError:
            break


def _analog_from(buf: object) -> None:
    global _demod, _fm_buf
    offset = float(os.environ.get("JIM_OFFSET_HZ", "50000"))
    span = float(os.environ.get("JIM_SPAN_HZ", "2000000"))
    if _demod is None or abs(_demod.offset - offset) > 1 or abs(_demod.fs - span) > 1:
        _demod = AnalogDemod(fs=span, offset_hz=offset)
        _fm_buf = np.zeros(0, dtype=np.float32)
    fm = _demod.process(np.asarray(buf, dtype=np.complex64))
    _fm_buf = np.concatenate((_fm_buf, fm))
    _emit_audio()


def _plot_and_send(self: object, buf: object, bufsz: int, mode: str = "eye") -> int:
    if mode == "fft":
        _collect(buf)
    consumed = _plot(self, buf, bufsz, mode)
    if mode == "fft":
        _publish(self.avg_pwr)
    return consumed


def _fft_work(self: object, input_items: object, output_items: object) -> int:
    """Copy IQ out of the graph. NBFM runs on a side thread so work stays short."""
    in0 = np.array(input_items[0], copy=True)
    try:
        _iq_q.put_nowait(in0)
    except queue.Full:
        try:
            _iq_q.get_nowait()
        except queue.Empty:
            pass
        try:
            _iq_q.put_nowait(in0)
        except queue.Full:
            pass
    now = time.time()
    if now > self.next_due:
        self.next_due = now + 0.05
        self.gnuplot.plot(in0, 512, mode="fft")
    return len(in0)


def _demod_loop() -> None:
    while True:
        buf = _iq_q.get()
        try:
            _analog_from(buf)
        except Exception:
            continue


threading.Thread(target=_demod_loop, name="nbfm", daemon=True).start()


gr_gnuplot.wrap_gp.attach_gp = _attach
gr_gnuplot.wrap_gp.plot = _plot_and_send
gr_gnuplot.fft_sink_c.work = _fft_work

args = sys.argv[1:]
if "-P" not in args and "--plot-mode" not in args:
    args = ["-P", "fft", *args]
sys.argv = [str(Path(OP25_APPS) / "rx.py"), *args]

import runpy

runpy.run_path(sys.argv[0], run_name="__main__")
