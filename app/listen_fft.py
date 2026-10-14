"""Start OP25 listen and publish a spectrum row for the page waterfall.

The HackRF local oscillator is TUNER offset above the channel. The row is
shifted so column center is the channel. The DC spike stays on the oscillator.
Gnuplot is not opened. This file is the process Start-P25 stops with the receiver.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

OP25_APPS = os.environ.get("OP25_APPS", "/root/op25/op25/gr-op25_repeater/apps")
sys.path.insert(0, OP25_APPS)

import gr_gnuplot
import numpy as np

SPEC_PORT = 23457
_sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_DGRAM)
_next = 0.0


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
    payload = json.dumps(
        {
            "tuned_hz": tuned,
            "span_hz": span,
            "offset_hz": offset,
            "db": scaled.tolist(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        _sock.sendto(payload, ("127.0.0.1", SPEC_PORT))
    except OSError:
        return


_plot = gr_gnuplot.wrap_gp.plot


def _plot_and_send(self: object, buf: object, bufsz: int, mode: str = "eye") -> int:
    consumed = _plot(self, buf, bufsz, mode)
    if mode == "fft":
        _publish(self.avg_pwr)
    return consumed


gr_gnuplot.wrap_gp.attach_gp = _attach
gr_gnuplot.wrap_gp.plot = _plot_and_send

args = sys.argv[1:]
if "-P" not in args and "--plot-mode" not in args:
    args = ["-P", "fft", *args]
sys.argv = [str(Path(OP25_APPS) / "rx.py"), *args]

import runpy

runpy.run_path(sys.argv[0], run_name="__main__")
