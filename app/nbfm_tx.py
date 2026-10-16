"""Transmit analog NBFM from 8 kHz microphone PCM on UDP 23459.

LO is 50 kHz above the channel. The FM carrier is rotated down so the
voice sits on the typed frequency. Two-way deviation is ±2.5 kHz.
"""

from __future__ import annotations

import argparse
import math
import os
import queue
import socket
import sys
import threading

import numpy as np
from gnuradio import analog, blocks, filter, gr
import osmosdr

from analog import NBFM_DEV_HZ
from tx_offset import SHIFT_HZ, ShiftedFM, install_modulator

MIC_PORT = 23459
RATE = 2_000_000
AUDIO = 8000


class PcmSource(gr.sync_block):
    """8 kHz float samples from the browser microphone WebSocket."""

    def __init__(self) -> None:
        gr.sync_block.__init__(self, "mic_pcm", None, [np.float32])
        self._q: queue.Queue = queue.Queue(maxsize=40)
        self._hold = np.zeros(0, dtype=np.float32)
        thread = threading.Thread(target=self._listen, name="mic-udp", daemon=True)
        thread.start()

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", MIC_PORT))
        while True:
            data, _addr = sock.recvfrom(4096)
            if len(data) < 2 or len(data) % 2:
                continue
            pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                self._q.put_nowait(pcm)
            except queue.Full:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._q.put_nowait(pcm)
                except queue.Full:
                    pass

    def work(self, _input_items: object, output_items: object) -> int:
        out = output_items[0]
        need = len(out)
        while self._hold.size < need:
            try:
                self._hold = np.concatenate((self._hold, self._q.get_nowait()))
            except queue.Empty:
                break
        if self._hold.size >= need:
            out[:] = self._hold[:need]
            self._hold = self._hold[need:]
        elif self._hold.size:
            out[: self._hold.size] = self._hold
            out[self._hold.size :] = 0
            self._hold = np.zeros(0, dtype=np.float32)
        else:
            out[:] = 0
        return need


class NbfmTx(gr.top_block):
    def __init__(self, freq_hz: int, ppm: int, if_gain: int) -> None:
        gr.top_block.__init__(self, "nbfm_tx")
        install_modulator()
        src = PcmSource()
        interp = filter.rational_resampler_fff(int(RATE // AUDIO), 1)
        sensitivity = 2.0 * math.pi * NBFM_DEV_HZ / RATE
        fm = analog.frequency_modulator_fc(sensitivity)
        sink = osmosdr.sink(args="hackrf,buffers=64")
        sink.set_sample_rate(RATE)
        sink.set_center_freq(freq_hz + SHIFT_HZ)
        sink.set_freq_corr(ppm)
        sink.set_gain(0)
        sink.set_if_gain(if_gain)
        sink.set_bb_gain(0)
        self.connect(src, interp, fm, sink)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Q", type=int, required=True)
    parser.add_argument("-q", type=int, default=0)
    parser.add_argument("-N", type=str, default="RF:0,IF:16")
    args = parser.parse_args()
    if_gain = 16
    for part in args.N.split(","):
        if part.startswith("IF:"):
            if_gain = int(part.split(":")[1])
    print(
        "nbfm tx: mic on %d Hz, tuner %d Hz, ±%.0f Hz NBFM"
        % (args.Q, args.Q + SHIFT_HZ, NBFM_DEV_HZ),
        file=sys.stderr,
    )
    tb = NbfmTx(args.Q, args.q, if_gain)
    tb.start()
    try:
        tb.wait()
    except KeyboardInterrupt:
        pass
    tb.stop()
    tb.wait()


if __name__ == "__main__":
    main()
