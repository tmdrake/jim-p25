# GNU Radio Companion flowgraphs

These `.grc` files are the portable NBFM stack for this HackRF One bench radio. Open them in GNU Radio Companion, or compile with `grcc`. They use C++ blocks and UDP. They do not use `audio.sink`. A later Raspberry Pi project is a different effort and does not run boatbod OP25 from this bench.

The live page still starts `app/nbfm_rx.py` and `app/nbfm_tx.py`. Keep those scripts and these flowgraphs in step. After you change a graph here, run `python3 grc/make_grc.py` on a GNU Radio 3.10 box that has gr-osmosdr.

P25 listen and the 1011 Hz test tone stay in boatbod OP25 (`rx.py`, `dv_tx.py`). This folder is the analog NBFM pair we own.

## Files

| File | Graph |
| --- | --- |
| `nbfm_rx.grc` | HackRF 2 Msps → xlating FIR → squelch → `analog.nbfm_rx` → UDP shorts **23458**. Same IQ → C++ FFT → UDP floats **23460**. |
| `nbfm_tx.grc` | UDP shorts **23459** → `analog.nbfm_tx` at 40 kHz → interpolate to 2 Msps → rotator −50 kHz → HackRF LO +50 kHz. |
| `make_grc.py` | Rebuilds the two `.grc` files from the GRC library. |

`freq` defaults to 100 MHz as a placeholder. Set it to a frequency you are allowed to use.

## Open and compile

```bash
gnuradio-companion grc/nbfm_rx.grc
gnuradio-companion grc/nbfm_tx.grc
grcc -o /tmp grc/nbfm_rx.grc
grcc -o /tmp grc/nbfm_tx.grc
```

## Device args

Change the `device_args` box if the SDR is not a HackRF:

- HackRF: `"hackrf"` (receive) or `"hackrf,buffers=64"` (transmit)
- RTL-SDR receive: `"rtl=0"`
- Soapy: `"soapy=0,driver=hackrf"`

Keep RF gain at 0. Keep the 50 kHz tuner offset so the DC spike is off the channel. If USB cannot hold 2 Msps, lower `samp_rate` and keep `quad_rate` a divisor of it.

Audio leaves as 8000 Hz s16le UDP, 320 bytes per 20 ms, on 23458. Transmit expects the same PCM shape on 23459. `src_zeros` is on, so a silent UDP feed transmits silence instead of stalling.

Do not add an ALSA or Pulse sink.

## Rates and ports

| Name | Value |
| --- | --- |
| Sample rate | 2 Msps |
| Tuner offset | +50 kHz |
| Quad rate | 40 kHz |
| Audio | 8000 Hz, ±2.5 kHz, 750 µs |
| PCM UDP | 23458 RX, 23459 TX |
| FFT UDP | 23460, 512 bins |

Wide 25 kHz / ±5 kHz is a change of `max_dev` and `cutoff` on the receive graph (12 kHz cutoff, 5e3 deviation).
