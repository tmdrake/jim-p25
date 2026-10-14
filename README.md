# jim-p25

P25 Phase 1 conventional simplex tester for a HackRF One and a Motorola radio you are allowed to test.

The page runs in Ubuntu on WSL2 and opens in the Windows browser. Set the frequency and the NAC. Listen plays decoded audio. Push-to-talk sends the standard 1011 Hz Phase 1 test tone with that NAC, talkgroup, and source ID. Voice is clear only (algorithm `0x80`).

Phase 2, trunking, scanning, encryption keys, and radio-disable messages are not part of this program.

The HackRF cannot receive and transmit at the same time. Transmit lasts only while push-to-talk is held, and it stops after 30 seconds. RF gain stays at 0. Use a frequency you are allowed to transmit on, with the radios close together or a dummy load on the HackRF.

## Start

```powershell
.\Start-P25.ps1
```

That attaches the HackRF to Ubuntu 24.04 and opens `http://127.0.0.1:8765/`.

Frequency, NAC, talkgroup, and source ID are written under `local/` when you press a button. That folder is gitignored. Nothing in git has a channel filled in.

## Toolchain

This stack does not run on Windows itself. On this machine it lives in WSL distro `Ubuntu-24.04`:

- GNU Radio 3.10, `gr-osmosdr`, and `libhackrf` from Ubuntu
- [boatbod/op25](https://github.com/boatbod/op25) built with `./install.sh -f` after source packages are enabled in `/etc/apt/sources.list.d/ubuntu.sources`
- HackRF USB shared with `usbipd attach --wsl Ubuntu-24.04 --hardware-id 1d50:6089`

`1d50:6089` is the public HackRF product id. The board serial is not stored in this repo.
