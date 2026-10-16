"""Narrowband FM audio from 2 Msps IQ, 8 kHz PCM for the browser.

Two-way NBFM: 12.5 kHz channel, ±2.5 kHz peak deviation, 750 µs de-emphasis.
"""

from __future__ import annotations

import math

import numpy as np

AUDIO_HZ = 8000
CHAN_HZ = 16_000
NBFM_DEV_HZ = 2500.0
PCM_SAMPLES = 160  # 20 ms


class AnalogDemod:
    """Mix the channel to DC, NBFM-discriminate, emit 8 kHz samples."""

    def __init__(self, fs: float = 2_000_000.0, offset_hz: float = 50_000.0) -> None:
        self.fs = float(fs)
        self.offset = float(offset_hz)
        self.decim1 = max(1, int(round(self.fs / CHAN_HZ)))
        self.chan_rate = self.fs / self.decim1
        self.decim2 = max(1, int(round(self.chan_rate / AUDIO_HZ)))
        self.phase = 0.0
        self.omega = 2.0 * math.pi * self.offset / self.fs
        self.hold = np.zeros(0, dtype=np.complex64)
        self.prev = np.complex64(0)
        self.fm_hold: list[float] = []
        self.deemp = 0.0
        self.hp_x = 0.0
        self.hp_y = 0.0
        self.alpha = 1.0 - math.exp(-1.0 / (AUDIO_HZ * 750e-6))
        self.hp_r = math.exp(-2.0 * math.pi * 300.0 / AUDIO_HZ)
        self.mag_ema = 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = np.asarray(iq, dtype=np.complex64).ravel()
        if iq.size == 0:
            return np.zeros(0, np.float32)
        n = np.arange(iq.size, dtype=np.float64)
        mixed = iq * np.exp(1j * (self.phase + self.omega * n)).astype(np.complex64)
        self.phase = (self.phase + self.omega * iq.size) % (2.0 * math.pi)
        if self.hold.size:
            mixed = np.concatenate((self.hold, mixed))
        extra = mixed.size % self.decim1
        if extra:
            self.hold = mixed[-extra:]
            mixed = mixed[:-extra]
        else:
            self.hold = np.zeros(0, dtype=np.complex64)
        if mixed.size == 0:
            return np.zeros(0, np.float32)
        lp = mixed.reshape(-1, self.decim1).mean(axis=1)
        self.mag_ema = 0.95 * self.mag_ema + 0.05 * float(np.mean(np.abs(lp)))
        prev = np.empty_like(lp)
        prev[0] = self.prev
        if lp.size > 1:
            prev[1:] = lp[:-1]
        self.prev = lp[-1]
        fm_hz = np.angle(lp * np.conj(prev)) * (self.chan_rate / (2.0 * math.pi))
        self.fm_hold.extend(fm_hz.tolist())
        out: list[float] = []
        while len(self.fm_hold) >= self.decim2:
            chunk = self.fm_hold[: self.decim2]
            del self.fm_hold[: self.decim2]
            x = (sum(chunk) / self.decim2) / NBFM_DEV_HZ
            self.deemp += self.alpha * (x - self.deemp)
            hp = self.deemp - self.hp_x + self.hp_r * self.hp_y
            self.hp_x = self.deemp
            self.hp_y = hp
            out.append(hp)
        return np.asarray(out, np.float32)


def to_pcm(samples: np.ndarray, gain: float = 28000.0) -> bytes:
    clipped = np.clip(samples * gain, -32767, 32767).astype(np.int16)
    return clipped.tobytes()
