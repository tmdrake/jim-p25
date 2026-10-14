"""Vocoder layer we invent.

The NXDN framer only calls encode_pcm_codeword() and silence_codeword().
Plug-ins sit behind that API: silence (now), a test tone we write, a public
AMBE+2 wrap, or an MBE-style vocoder we design later.
"""

from __future__ import annotations

CODEWORD_DIBITS = 36  # one half-rate NXDN voice word, as OP25 stores it


def vocoder_status() -> str:
    return "silence frames (no public AMBE+2 library linked yet)"


def silence_codeword() -> list[int]:
    """36 dibits of zeros. A radio may sync and stay quiet until a real vocoder is linked."""
    return [0] * CODEWORD_DIBITS


def encode_pcm_codeword(samples: list[int]) -> list[int]:
    """Encode 160 samples of 8 kHz PCM.

    When mbelib-neo or OP25's ambe_encoder is linked, this returns 36 dibits.
    Until then it returns silence so the framer can still be tested.
    """
    if len(samples) != 160:
        raise ValueError("AMBE+2 expects 160 samples (20 ms at 8 kHz).")
    return silence_codeword()
