"""Checks for the NXDN48 framer. No HackRF, no vocoder."""

from __future__ import annotations

from .fsk4 import dibit_to_hz
from .frame import FS, FRAME_DIBITS, build_stream, build_voice_frame, descramble, encode_lich
from .vocoder import silence_codeword


def test_frame() -> None:
    word = silence_codeword()
    frame = build_voice_frame(1, 0, [word, word, word, word])
    assert len(frame) == FRAME_DIBITS
    assert frame[:10] == FS
    assert set(frame) <= {0, 1, 2, 3}
    lich = encode_lich(0x6E)
    assert len(lich) == 8
    assert set(lich) <= {1, 3}


def test_descramble_twice() -> None:
    data = list(range(4)) * 50
    data = data[:182]
    copy = list(data)
    descramble(copy)
    descramble(copy)
    assert copy == data


def test_stream_size() -> None:
    blob = build_stream(63, 70, silence_codeword())
    assert len(blob) == 70 * FRAME_DIBITS
    assert blob[0] == FS[0]


def test_fsk4() -> None:
    assert dibit_to_hz(3) == 1050.0
    assert dibit_to_hz(0) == -350.0


if __name__ == "__main__":
    test_frame()
    test_descramble_twice()
    test_stream_size()
    test_fsk4()
    print("ok")
