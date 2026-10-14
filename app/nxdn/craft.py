"""Write NXDN48 dibits to a file. Does not open the HackRF."""

from __future__ import annotations

import argparse
from pathlib import Path

from .frame import FRAME_DIBITS, build_stream
from .vocoder import silence_codeword, vocoder_status


def main() -> None:
    parser = argparse.ArgumentParser(description="NXDN48 conventional symbol file")
    parser.add_argument("--ran", type=int, default=1)
    parser.add_argument("--frames", type=int, default=70)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.ran <= 63:
        raise SystemExit("RAN is 0..63")
    payload = build_stream(args.ran, args.frames, silence_codeword())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(
        "wrote %s (%d bytes, %d frames, %s)"
        % (args.output, len(payload), args.frames, vocoder_status())
    )
    if len(payload) != args.frames * FRAME_DIBITS:
        raise SystemExit("unexpected file size")


if __name__ == "__main__":
    main()
