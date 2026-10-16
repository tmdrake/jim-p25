"""GNU Radio FM receiver. No ALSA.

Narrow: 12.5 kHz ±2.5 kHz. Wide: 25 kHz ±5 kHz. 750 µs de-emphasis.
Audio is C++ UDP to 127.0.0.1:23458, then the page WebSocket.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from gnuradio import analog, blocks, fft, filter, gr, network
from gnuradio.fft import window
from gnuradio.filter import firdes
import osmosdr

from settings import sql_level

RATE = 2_000_000
QUAD = 40_000
AUDIO = 8_000
SINK = 48_000
OFFSET = 50_000
SPEC_PORT = 23457
SPEC_BIN_PORT = 23460
FFT_BINS = 512
SQL_LIVE = Path(__file__).resolve().parent.parent / "local" / "sql.live"
SETTINGS = Path(__file__).resolve().parent.parent / "local" / "settings.json"


def sql_to_db(level: int) -> float:
    level = max(0, min(100, int(level)))
    return -100.0 + level * 0.85


class NbfmRx(gr.top_block):
    def __init__(self, freq_hz: int, ppm: int, if_gain: int, wide: bool) -> None:
        gr.top_block.__init__(self, "nbfm_rx")
        bw = 25_000 if wide else 12_500
        cutoff = 12_000 if wide else 8_000
        dev = 5_000.0 if wide else 2_500.0
        src = osmosdr.source(args="hackrf")
        src.set_sample_rate(RATE)
        src.set_center_freq(freq_hz + OFFSET)
        src.set_freq_corr(ppm)
        src.set_gain(0)
        src.set_if_gain(if_gain)
        src.set_bb_gain(min(62, if_gain if if_gain % 2 == 0 else if_gain + 1))
        taps = firdes.low_pass(1.0, RATE, cutoff, 3_000)
        xlat = filter.freq_xlating_fir_filter_ccf(RATE // QUAD, taps, -OFFSET, RATE)
        self.sql = analog.simple_squelch_cc(sql_to_db(0), 0.01)
        demod = analog.nbfm_rx(AUDIO, QUAD, 750e-6, dev)
        gain = blocks.multiply_const_ff(8.0)
        f2s = blocks.float_to_short(1, 8000.0)
        udp = network.udp_sink(gr.sizeof_short, 1, "127.0.0.1", 23458, 0, 320, True)
        skip = blocks.keep_one_in_n(gr.sizeof_gr_complex, 195)
        vec = blocks.stream_to_vector(gr.sizeof_gr_complex, FFT_BINS)
        fftb = fft.fft_vcc(FFT_BINS, True, window.blackmanharris(FFT_BINS), True, 1)
        mag = blocks.complex_to_mag_squared(FFT_BINS)
        logp = blocks.nlog10_ff(10, FFT_BINS, 0)
        spec = network.udp_sink(gr.sizeof_float, FFT_BINS, "127.0.0.1", SPEC_BIN_PORT, 0, FFT_BINS * 4, True)
        self.connect(src, xlat, self.sql, demod, gain, f2s, udp)
        self.connect(src, skip, vec, fftb, mag, logp, spec)
        print("nbfm rx: C++ audio UDP 23458, C++ FFT UDP 23460", file=sys.stderr)
        self._sql_thread = threading.Thread(target=self._sql_loop, name="sql", daemon=True)
        self._sql_thread.start()

    def _sql_loop(self) -> None:
        while True:
            level = 0
            try:
                if SQL_LIVE.is_file():
                    level = int(float(SQL_LIVE.read_text().strip() or "0"))
                else:
                    level = sql_level(SETTINGS)
            except Exception:
                level = 0
            try:
                self.sql.set_threshold(sql_to_db(level))
            except Exception:
                pass
            time.sleep(0.05)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-Q", type=int, required=True)
    parser.add_argument("-q", type=int, default=0)
    parser.add_argument("-N", type=str, default="RF:0,IF:16")
    parser.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    if_gain = 16
    for part in args.N.split(","):
        if part.startswith("IF:"):
            if_gain = int(part.split(":")[1])
    print(
        "nbfm rx: UDP 23458, %s, channel %d, LO %d"
        % ("wide 25 kHz ±5 kHz" if args.wide else "narrow 12.5 kHz ±2.5 kHz", args.Q, args.Q + OFFSET),
        file=sys.stderr,
    )
    tb = NbfmRx(args.Q, args.q, if_gain, args.wide)
    tb.start()
    try:
        tb.wait()
    except KeyboardInterrupt:
        pass
    tb.stop()
    tb.wait()


if __name__ == "__main__":
    main()
