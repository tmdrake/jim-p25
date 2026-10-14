"""NXDN48 conventional voice frame (192 dibits).

Layout and FEC match Osmocom OP25 nxdn_tx_sb (GPL-3.0-or-later, Max H. Parke).
This module builds FS, LICH, SACCH, and RAN. Voice dibits come from vocoder.py.
"""

from __future__ import annotations

FRAME_DIBITS = 192
FS = [3, 0, 3, 1, 3, 3, 1, 1, 2, 1]
# Conventional half-rate voice, 4V. Comment in OP25: LICH 0x6e.
LICH_VOICE_4V = 0x6E

# OP25 nxdn_const.h
PERM_12_5 = [
    0, 12, 24, 36, 48,
    1, 13, 25, 37, 49,
    2, 14, 26, 38, 50,
    3, 15, 27, 39, 51,
    4, 16, 28, 40, 52,
    5, 17, 29, 41, 53,
    6, 18, 30, 42, 54,
    7, 19, 31, 43, 55,
    8, 20, 32, 44, 56,
    9, 21, 33, 45, 57,
    10, 22, 34, 46, 58,
    11, 23, 35, 47, 59,
]

# OP25 nxdn.cc scramble_t: invert the sign bit of these dibit indexes
SCRAMBLE_AT = [
    2, 5, 6, 7, 10, 12, 14, 16, 17, 22, 23, 25, 26, 27, 28, 30, 33, 34, 36, 37, 38, 41, 45, 47,
    52, 54, 56, 57, 59, 62, 63, 64, 65, 66, 67, 69, 70, 73, 76, 79, 81, 82, 84, 85, 86, 87, 88,
    89, 92, 95, 96, 98, 100, 103, 104, 107, 108, 116, 117, 121, 122, 125, 127, 131, 132, 134,
    137, 139, 140, 141, 142, 143, 144, 145, 147, 151, 153, 154, 158, 159, 160, 162, 164, 165,
    168, 170, 171, 174, 175, 176, 177, 181,
]

TRELLIS_PC = [
    0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0,
    1, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1,
]


def store_i(value: int, width: int) -> list[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def load_i(bits: list[int]) -> int:
    acc = 0
    for bit in bits:
        acc = (acc << 1) | (bit & 1)
    return acc


def crc6(bits: list[int]) -> int:
    s = [1, 1, 1, 1, 1, 1]
    for bit in bits:
        a = (bit & 1) ^ s[0]
        s = [a ^ s[1], s[2], s[3], a ^ s[4], a ^ s[5], a]
    return load_i(s)


def trellis_encode(src_bits: list[int], dest_len: int) -> list[int]:
    dest = [0] * dest_len
    reg = 0
    for i in range(dest_len // 2):
        reg = (reg << 1) | src_bits[i]
        dest[i * 2] = TRELLIS_PC[reg & 0x19]
        dest[i * 2 + 1] = TRELLIS_PC[reg & 0x17]
    return dest


def bits_to_dibits(bits: list[int]) -> list[int]:
    return [bits[i] * 2 + bits[i + 1] for i in range(0, len(bits), 2)]


def encode_lich(lich: int) -> list[int]:
    bits = store_i(lich & 0x7F, 7)
    bits.append((bits[0] + bits[1] + bits[2] + bits[3]) & 1)
    return [3 if bit else 1 for bit in bits]


def encode_sacch_chunk(src_bits: list[int], structure: int, ran: int) -> list[int]:
    if len(src_bits) != 18:
        raise ValueError("SACCH payload is 18 bits")
    if not 0 <= ran <= 63:
        raise ValueError("RAN is 0..63")
    header = store_i(((structure & 3) << 6) | (ran & 0x3F), 8)
    buf = header + list(src_bits)
    buf += store_i(crc6(buf), 6)
    buf += [0, 0, 0, 0]
    coded = trellis_encode(buf, 72)
    punctured: list[int] = []
    for i in range(0, 72, 12):
        punctured.extend(coded[i : i + 5])
        punctured.extend(coded[i + 6 : i + 11])
    permuted = [punctured[PERM_12_5[i]] for i in range(60)]
    return bits_to_dibits(permuted)


def descramble(dibits: list[int]) -> None:
    for index in SCRAMBLE_AT:
        if index >= len(dibits):
            break
        dibits[index] ^= 2


def build_voice_frame(ran: int, sacch_seq: int, codewords: list[list[int]]) -> list[int]:
    """One 80 ms NXDN48 voice frame. codewords is four lists of 36 dibits."""
    if not 0 <= ran <= 63:
        raise ValueError("RAN is 0..63")
    if len(codewords) != 4 or any(len(word) != 36 for word in codewords):
        raise ValueError("Need four 36-dibit voice words")
    payload = [0] * 18
    frame = (
        list(FS)
        + encode_lich(LICH_VOICE_4V)
        + encode_sacch_chunk(payload, 3 - (sacch_seq % 4), ran)
        + [dibit for word in codewords for dibit in word]
    )
    if len(frame) != FRAME_DIBITS:
        raise RuntimeError("NXDN48 frame is %d dibits" % len(frame))
    body = frame[10:]
    descramble(body)
    frame[10:] = body
    if any(d not in (0, 1, 2, 3) for d in frame):
        raise RuntimeError("dibit out of range")
    return frame


def build_stream(ran: int, frames: int, codeword: list[int]) -> bytes:
    out = bytearray()
    words = [list(codeword) for _ in range(4)]
    for seq in range(frames):
        out.extend(build_voice_frame(ran, seq, words))
    return bytes(out)
