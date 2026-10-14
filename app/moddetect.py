"""AM vs FM from complex IQ around the tuned channel."""

from __future__ import annotations

import numpy as np

DECIM = 64  # 2 Msps -> 31.25 kHz, enough for a 12.5 kHz channel


def classify_am_fm(iq: np.ndarray, fs: float, offset_hz: float) -> dict:
    """Return mod, envelope CV, and RMS deviation in Hz.

    Mixes the channel (offset below the LO) to DC, then compares envelope
    variation (AM) with instantaneous-frequency spread (FM / C4FM).
    """
    iq = np.asarray(iq, dtype=np.complex64).ravel()
    unknown = {"mod": "unknown", "env_cv": 0.0, "dev_hz": 0}
    if iq.size < 2048 or fs <= 0:
        return unknown
    n = np.arange(iq.size, dtype=np.float64)
    mixed = iq * np.exp(1j * 2.0 * np.pi * offset_hz / fs * n).astype(np.complex64)
    usable = (mixed.size // DECIM) * DECIM
    if usable < DECIM * 16:
        return unknown
    lp = mixed[:usable].reshape(-1, DECIM).mean(axis=1)
    mag = np.abs(lp)
    mean_mag = float(np.mean(mag) + 1e-12)
    env_cv = float(np.std(mag) / mean_mag)
    dphi = np.angle(lp[1:] * np.conj(lp[:-1]))
    dev_hz = float(np.std(dphi) * (fs / DECIM) / (2.0 * np.pi))
    if mean_mag < 1e-6:
        label = "noise"
    elif env_cv >= 0.35 and dev_hz < 800:
        label = "am"
    elif env_cv < 0.28 and dev_hz >= 250:
        label = "fm"
    elif env_cv < 0.22 and dev_hz < 80:
        label = "carrier"
    else:
        label = "noise"
    return {"mod": label, "env_cv": round(env_cv, 3), "dev_hz": int(round(dev_hz))}
