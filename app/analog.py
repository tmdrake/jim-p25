"""AM and FM audio from 2 Msps IQ, 8 kHz PCM for the browser."""

from __future__ import annotations

import math

import numpy as np

AUDIO_HZ = 8000
IF_HZ = 40_000
PCM_SAMPLES = 160  # 20 ms


class AnalogDemod:
    """Mix the channel to DC, FM-discriminate or AM-envelope, emit 8 kHz samples."""

    def __init__(self, fs: float = 2_000_000.0, offset_hz: float = 50_000.0) -> None:
        self.fs = float(fs)
        self.offset = float(offset_hz)
        self.decim1 = max(1, int(round(self.fs / IF_HZ)))
        self.if_rate = self.fs / self.decim1
        self.decim2 = max(1, int(round(self.if_rate / AUDIO_HZ)))
        self.phase = 0.0
        self.omega = 2.0 * math.pi * self.offset / self.fs
        self.hold = np.zeros(0, dtype=np.complex64)
        self.prev = np.complex64(0)
        self.fm_hold: list[float] = []
        self.am_hold: list[float] = []
        self.am_dc = 0.0
        self.deemp = 0.0
        self.alpha = 1.0 - math.exp(-1.0 / (AUDIO_HZ * 750e-6))

    def process(self, iq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        iq = np.asarray(iq, dtype=np.complex64).ravel()
        if iq.size == 0:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
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
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        lp = mixed.reshape(-1, self.decim1).mean(axis=1)
        prev = np.empty_like(lp)
        prev[0] = self.prev
        if lp.size > 1:
            prev[1:] = lp[:-1]
        self.prev = lp[-1]
        fm_hz = np.angle(lp * np.conj(prev)) * (self.if_rate / (2.0 * math.pi))
        mag = np.abs(lp)
        self.am_dc = 0.99 * self.am_dc + 0.01 * float(np.mean(mag))
        am = mag - self.am_dc
        self.fm_hold.extend(fm_hz.tolist())
        self.am_hold.extend(am.tolist())
        fm_out: list[float] = []
        am_out: list[float] = []
        while len(self.fm_hold) >= self.decim2:
            chunk_f = self.fm_hold[: self.decim2]
            chunk_a = self.am_hold[: self.decim2]
            del self.fm_hold[: self.decim2]
            del self.am_hold[: self.decim2]
            x = sum(chunk_f) / self.decim2 / 4000.0
            self.deemp += self.alpha * (x - self.deemp)
            fm_out.append(self.deemp)
            am_out.append(sum(chunk_a) / self.decim2 / (self.am_dc + 1e-6))
        return np.asarray(fm_out, np.float32), np.asarray(am_out, np.float32)


def to_pcm(samples: np.ndarray, gain: float = 12000.0) -> bytes:
    clipped = np.clip(samples * gain, -32767, 32767).astype(np.int16)
    return clipped.tobytes()
