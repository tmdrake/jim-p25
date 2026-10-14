"""Validate the fields the page sends. No radio I/O here."""

from __future__ import annotations

import json
from pathlib import Path

HACKRF_IF_GAINS = (0, 8, 16, 24, 32, 40)
CLEAR_ALGID = 0x80
TX_SUPERFRAMES = 70
TX_LIMIT_S = 30
FORM_FIELDS = ("frequency", "nac", "tgid", "src", "ppm", "rx_gain", "tx_if_gain")


class SettingsError(ValueError):
    pass


def parse_frequency_mhz(text) -> float:
    raw = "" if text is None else str(text).strip()
    if not raw:
        raise SettingsError("Enter a frequency in MHz.")
    try:
        mhz = float(raw)
    except ValueError as exc:
        raise SettingsError("Frequency must be a number in MHz.") from exc
    if mhz < 1 or mhz > 6000:
        raise SettingsError("Frequency must be between 1 and 6000 MHz.")
    return mhz


def parse_nac(text) -> int:
    raw = "" if text is None else str(text).strip().lower()
    if not raw:
        raise SettingsError("Enter a P25 NAC in hex.")
    if raw.startswith("0x"):
        raw = raw[2:]
    if not raw or len(raw) > 3 or any(c not in "0123456789abcdef" for c in raw):
        raise SettingsError("NAC must be 12-bit hex, for example 293.")
    return int(raw, 16)


def parse_id(text, name: str, limit: int, default: int) -> int:
    raw = "" if text is None else str(text).strip()
    if not raw:
        return default
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a whole number.") from exc
    if value < 1 or value > limit:
        raise SettingsError(f"{name} must be from 1 to {limit}.")
    return value


def snap_if_gain(text, default: int) -> int:
    raw = "" if text is None else str(text).strip()
    if not raw:
        value = default
    else:
        try:
            value = int(float(raw))
        except ValueError as exc:
            raise SettingsError("Gain must be a whole number.") from exc
    snapped = min(HACKRF_IF_GAINS, key=lambda g: abs(g - value))
    return snapped


def parse_ppm(text) -> int:
    raw = "" if text is None else str(text).strip()
    if not raw:
        return 0
    try:
        value = int(float(raw))
    except ValueError as exc:
        raise SettingsError("PPM must be a whole number.") from exc
    if value < -200 or value > 200:
        raise SettingsError("PPM must be between -200 and 200.")
    return value


def form_from_json(data: dict) -> dict:
    """Keep the typed fields. Do not require a valid channel."""
    if not isinstance(data, dict):
        raise SettingsError("Expected a JSON object.")
    form = {}
    for key in FORM_FIELDS:
        raw = data.get(key, "")
        if raw is None:
            text = ""
        elif isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise SettingsError("Settings must be text.")
        else:
            text = str(raw).strip()
        if len(text) > 32 or any(ord(ch) < 32 for ch in text):
            raise SettingsError("A setting is too long.")
        form[key] = text
    return form


def load_form(path: Path) -> dict:
    if not path.is_file():
        return {"saved": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        form = form_from_json(data)
    except (OSError, json.JSONDecodeError, SettingsError):
        return {"saved": False}
    form["saved"] = True
    return form


def save_form(path: Path, data: dict) -> dict:
    form = form_from_json(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(form, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {**form, "saved": True}


def channel_from_json(data: dict) -> dict:
    if not isinstance(data, dict):
        raise SettingsError("Expected a JSON object.")
    freq = parse_frequency_mhz(data.get("frequency"))
    nac = parse_nac(data.get("nac"))
    tgid = parse_id(data.get("tgid"), "Talkgroup", 65535, 1)
    src = parse_id(data.get("src"), "Source ID", 16777215, 1)
    rx_gain = snap_if_gain(data.get("rx_gain"), 16)
    tx_if = snap_if_gain(data.get("tx_if_gain"), 16)
    ppm = parse_ppm(data.get("ppm"))
    return {
        "frequency_mhz": freq,
        "frequency_hz": int(round(freq * 1_000_000)),
        "nac": nac,
        "nac_hex": f"0x{nac:03x}",
        "tgid": tgid,
        "src": src,
        "rx_gain": rx_gain,
        "bb_gain": min(62, rx_gain if rx_gain % 2 == 0 else rx_gain - 1),
        "tx_if_gain": tx_if,
        "ppm": ppm,
        "algid": CLEAR_ALGID,
    }
