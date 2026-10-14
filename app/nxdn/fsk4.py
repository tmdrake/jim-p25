"""NXDN 4FSK symbol map.

Dibit to deviation follows the MMDVM NXDN modulator (GPL-2.0, G4KLX):
11 → +1050 Hz, 10 → +350 Hz, 00 → −350 Hz, 01 → −1050 Hz.
Symbol rate is 2400 for NXDN48 (6.25 kHz) and 4800 for NXDN96 (12.5 kHz).
"""

from __future__ import annotations

# dibit 0..3 → Hz at the 4FSK mapper, before any RRC pulse shaping
LEVELS_HZ = {
    0: -350.0,   # 00
    1: -1050.0,  # 01
    2: 350.0,    # 10
    3: 1050.0,   # 11
}


def dibit_to_hz(dibit: int) -> float:
    if dibit not in LEVELS_HZ:
        raise ValueError("NXDN dibit must be 0..3")
    return LEVELS_HZ[dibit]


def dibits_to_hz(dibits: list[int]) -> list[float]:
    return [dibit_to_hz(d) for d in dibits]
