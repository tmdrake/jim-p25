"""Transmit with the HackRF tuner above the channel.

dv_tx puts the C4FM carrier at baseband center and tunes the HackRF to the
channel, so the DC spike sits on the tone. This moves the carrier down by
the same offset listen uses, and tunes the HackRF up by that amount. The
tone stays on the frequency typed in the page.
"""

from __future__ import annotations

import math
import os
import runpy
import sys

from gnuradio import analog, blocks, gr

SHIFT_HZ = int(os.environ.get("JIM_TX_SHIFT_HZ", "50000"))
RATE_HZ = float(os.environ.get("JIM_TX_RATE_HZ", "2000000"))
DV_TX = os.environ.get("JIM_DV_TX", "")
_FM = analog.frequency_modulator_fc


class ShiftedFM(gr.hier_block2):
    """FM modulator whose carrier sits SHIFT_HZ below baseband center."""

    def __init__(self, sensitivity: float) -> None:
        gr.hier_block2.__init__(
            self,
            "jim_shifted_fm",
            gr.io_signature(1, 1, gr.sizeof_float),
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
        )
        modulator = _FM(sensitivity)
        # Positive rotator phase moves a tone up. The carrier has to move down.
        phase = -2.0 * math.pi * SHIFT_HZ / RATE_HZ
        self.connect(self, modulator, blocks.rotator_cc(phase), self)


def raise_lo(argv: list[str], shift_hz: int) -> tuple[list[str], int | None]:
    """Return argv with the sink frequency moved up, and the original channel."""
    if shift_hz == 0:
        return list(argv), None
    out = list(argv)
    for flag in ("-Q", "--frequency"):
        if flag not in out:
            continue
        index = out.index(flag)
        channel = int(float(out[index + 1]))
        out[index + 1] = str(channel + shift_hz)
        return out, channel
    return out, None


def install_modulator() -> None:
    if SHIFT_HZ == 0:
        return
    analog.frequency_modulator_fc = ShiftedFM


def main() -> None:
    if not DV_TX:
        raise SystemExit("JIM_DV_TX is not set")
    tx_dir = os.path.dirname(os.path.abspath(DV_TX))
    if tx_dir not in sys.path:
        sys.path.insert(0, tx_dir)
    os.chdir(tx_dir)
    install_modulator()
    argv, channel = raise_lo(sys.argv[1:], SHIFT_HZ)
    if channel is None:
        print("tx offset: no -Q frequency, tuner left unchanged", file=sys.stderr)
    else:
        print(
            "tx offset: tone %d Hz, tuner %d Hz, DC spike %d Hz above the tone"
            % (channel, channel + SHIFT_HZ, SHIFT_HZ),
            file=sys.stderr,
        )
    sys.argv = [DV_TX, *argv]
    runpy.run_path(DV_TX, run_name="__main__")


if __name__ == "__main__":
    main()
