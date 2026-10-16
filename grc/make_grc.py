#!/usr/bin/env python3
"""Write jim-p25 NBFM Companion flowgraphs next to this script.

Run on a machine with GNU Radio 3.10 and gr-osmosdr:
    python3 grc/make_grc.py
    grcc -o /tmp grc/nbfm_rx.grc
    grcc -o /tmp grc/nbfm_tx.grc

The page still starts app/nbfm_rx.py and app/nbfm_tx.py. These .grc files are
the portable C++-block graphs for GNU Radio Companion and later Raspberry Pi
work. No ALSA. Audio and FFT leave as UDP.
"""

from __future__ import annotations

from pathlib import Path

from gnuradio import gr
from gnuradio.grc.core.platform import Platform

HERE = Path(__file__).resolve().parent


def platform() -> Platform:
    plat = Platform(
        name="GNU Radio Companion Compiler",
        prefs=gr.prefs(),
        version=gr.version(),
        version_parts=(gr.major_version(), gr.api_version(), gr.minor_version()),
    )
    plat.build_library()
    return plat


def set_opt(fg, key: str, value: str) -> None:
    fg.options_block.params[key].set_value(value)


def add_var(fg, name: str, value: str, x: int, y: int):
    block = fg.new_block("variable")
    block.params["id"].set_value(name)
    block.params["value"].set_value(value)
    block.states["coordinate"] = [x, y]
    return block


def add_note(fg, name: str, text: str, x: int, y: int):
    block = fg.new_block("note")
    block.params["id"].set_value(name)
    block.params["note"].set_value(text)
    block.states["coordinate"] = [x, y]
    return block


def add_import(fg, name: str, imports: str, x: int, y: int):
    block = fg.new_block("import")
    block.params["id"].set_value(name)
    block.params["imports"].set_value(imports)
    block.states["coordinate"] = [x, y]
    return block


def add_block(fg, key: str, name: str, x: int, y: int, **params):
    block = fg.new_block(key)
    if block is None:
        raise SystemExit("missing GRC block %s" % key)
    block.params["id"].set_value(name)
    for param, value in params.items():
        if param not in block.params:
            raise SystemExit("%s has no param %s" % (key, param))
        block.params[param].set_value(value)
    block.states["coordinate"] = [x, y]
    return block


def stream_src(block):
    for port in block.sources:
        if port.domain == "stream":
            return port
    raise SystemExit("%s has no stream source" % block.name)


def stream_snk(block):
    for port in block.sinks:
        if port.domain == "stream":
            return port
    raise SystemExit("%s has no stream sink" % block.name)


def wire(fg, src, dst) -> None:
    fg.connect(stream_src(src), stream_snk(dst))


def save(plat: Platform, fg, path: Path) -> None:
    fg.rewrite()
    fg.validate()
    errors = list(fg.iter_error_messages())
    if errors:
        print("validate", path.name)
        for err in errors:
            print(" ", err)
    plat.save_flow_graph(str(path), fg)
    print("wrote", path)


def make_rx(plat: Platform) -> None:
    fg = plat.make_flow_graph()
    set_opt(fg, "id", "jim_nbfm_rx")
    set_opt(fg, "title", "jim-p25 NBFM receive")
    set_opt(fg, "author", "jim-p25")
    set_opt(
        fg,
        "description",
        "C++ NBFM listen. No ALSA. UDP PCM 23458, UDP FFT 23460. "
        "Same graph as app/nbfm_rx.py. Open in Companion, or grcc for a Pi.",
    )
    set_opt(fg, "generate_options", "no_gui")
    set_opt(fg, "run_options", "run")
    set_opt(fg, "output_language", "python")
    set_opt(fg, "catch_exceptions", "True")
    fg.options_block.states["coordinate"] = [16, 12]

    add_note(
        fg,
        "note_rpi",
        "Raspberry Pi / later SDR: keep UDP, keep RF gain 0, keep the 50 kHz "
        "LO offset. Change device_args (hackrf, rtl=0, soapy=0). Drop samp_rate "
        "if USB cannot hold 2 Msps. Do not add audio.sink.",
        16,
        88,
    )
    add_var(fg, "samp_rate", "2e6", 400, 12)
    add_var(fg, "audio_rate", "8000", 520, 12)
    add_var(fg, "quad_rate", "40000", 640, 12)
    add_var(fg, "offset", "50e3", 760, 12)
    add_var(fg, "freq", "100e6", 880, 12)
    add_var(fg, "ppm", "0", 1000, 12)
    add_var(fg, "if_gain", "16", 400, 76)
    add_var(fg, "rf_gain", "0", 520, 76)
    add_var(fg, "max_dev", "2.5e3", 640, 76)
    add_var(fg, "tau", "750e-6", 760, 76)
    add_var(fg, "sql_db", "-100", 880, 76)
    add_var(fg, "fft_size", "512", 1000, 76)
    add_var(fg, "keep_n", "195", 400, 140)
    add_var(fg, "cutoff", "8e3", 520, 140)
    add_var(fg, "trans_width", "3e3", 640, 140)
    add_var(fg, "audio_gain", "8", 760, 140)
    add_var(fg, "audio_scale", "8000", 880, 140)
    add_var(fg, "udp_host", '"127.0.0.1"', 1000, 140)
    add_var(fg, "audio_port", "23458", 1120, 12)
    add_var(fg, "fft_port", "23460", 1120, 76)
    add_var(fg, "device_args", '"hackrf"', 1120, 140)

    src = add_block(
        fg,
        "osmosdr_source",
        "osmo_src",
        16,
        280,
        args="device_args",
        sample_rate="samp_rate",
        nchan="1",
        num_mboards="1",
        freq0="freq + offset",
        corr0="ppm",
        gain0="rf_gain",
        if_gain0="if_gain",
        bb_gain0="if_gain",
        gain_mode0="False",
        dc_offset_mode0="0",
        iq_balance_mode0="0",
        sync="none",
    )
    xlat = add_block(
        fg,
        "freq_xlating_fir_filter_xxx",
        "xlat",
        280,
        280,
        type="ccf",
        decim="int(samp_rate / quad_rate)",
        taps="firdes.low_pass(1.0, samp_rate, cutoff, trans_width)",
        center_freq="-offset",
        samp_rate="samp_rate",
    )
    sql = add_block(
        fg,
        "analog_simple_squelch_cc",
        "sql",
        560,
        288,
        threshold="sql_db",
        alpha="0.01",
    )
    demod = add_block(
        fg,
        "analog_nbfm_rx",
        "nbfm",
        760,
        272,
        audio_rate="audio_rate",
        quad_rate="quad_rate",
        tau="tau",
        max_dev="max_dev",
    )
    gain = add_block(
        fg,
        "blocks_multiply_const_vxx",
        "gain",
        980,
        280,
        type="float",
        const="audio_gain",
        vlen="1",
    )
    f2s = add_block(
        fg,
        "blocks_float_to_short",
        "f2s",
        1180,
        280,
        vlen="1",
        scale="audio_scale",
    )
    udp_pcm = add_block(
        fg,
        "network_udp_sink",
        "udp_pcm",
        1360,
        256,
        type="short",
        addr="udp_host",
        port="audio_port",
        header="0",
        payloadsize="320",
        send_eof="True",
        vlen="1",
    )
    skip = add_block(
        fg,
        "blocks_keep_one_in_n",
        "skip",
        280,
        520,
        type="complex",
        n="keep_n",
        vlen="1",
    )
    vec = add_block(
        fg,
        "blocks_stream_to_vector",
        "vec",
        500,
        520,
        type="complex",
        num_items="fft_size",
        vlen="1",
    )
    fftb = add_block(
        fg,
        "fft_vxx",
        "fftb",
        740,
        488,
        type="complex",
        fft_size="fft_size",
        forward="True",
        window="window.blackmanharris(fft_size)",
        shift="True",
        nthreads="1",
    )
    mag = add_block(
        fg,
        "blocks_complex_to_mag_squared",
        "mag",
        980,
        520,
        vlen="fft_size",
    )
    logp = add_block(
        fg,
        "blocks_nlog10_ff",
        "logp",
        1180,
        504,
        n="10",
        k="0",
        vlen="fft_size",
    )
    udp_fft = add_block(
        fg,
        "network_udp_sink",
        "udp_fft",
        1360,
        488,
        type="float",
        addr="udp_host",
        port="fft_port",
        header="0",
        payloadsize="fft_size * 4",
        send_eof="True",
        vlen="fft_size",
    )

    fg.rewrite()
    wire(fg, src, xlat)
    wire(fg, xlat, sql)
    wire(fg, sql, demod)
    wire(fg, demod, gain)
    wire(fg, gain, f2s)
    wire(fg, f2s, udp_pcm)
    wire(fg, src, skip)
    wire(fg, skip, vec)
    wire(fg, vec, fftb)
    wire(fg, fftb, mag)
    wire(fg, mag, logp)
    wire(fg, logp, udp_fft)
    save(plat, fg, HERE / "nbfm_rx.grc")


def make_tx(plat: Platform) -> None:
    fg = plat.make_flow_graph()
    set_opt(fg, "id", "jim_nbfm_tx")
    set_opt(fg, "title", "jim-p25 NBFM transmit")
    set_opt(fg, "author", "jim-p25")
    set_opt(
        fg,
        "description",
        "C++ NBFM transmit from 8 kHz s16le UDP 23459. LO +50 kHz, rotator "
        "down so the voice sits on freq. No Python work() source. Pi-ready.",
    )
    set_opt(fg, "generate_options", "no_gui")
    set_opt(fg, "run_options", "run")
    set_opt(fg, "output_language", "python")
    set_opt(fg, "catch_exceptions", "True")
    fg.options_block.states["coordinate"] = [16, 12]

    add_import(fg, "import_math", "import math", 16, 88)
    add_note(
        fg,
        "note_rpi",
        "Feed 8000 Hz s16le PCM to UDP 23459 (320-byte frames). analog.nbfm_tx "
        "runs at 40 kHz, then interpolates to samp_rate. RF gain stays 0. "
        "On a Pi, keep device_args and IF gain modest.",
        160,
        80,
    )
    add_var(fg, "samp_rate", "2e6", 400, 12)
    add_var(fg, "audio_rate", "8000", 520, 12)
    add_var(fg, "quad_rate", "40000", 640, 12)
    add_var(fg, "offset", "50e3", 760, 12)
    add_var(fg, "freq", "100e6", 880, 12)
    add_var(fg, "ppm", "0", 1000, 12)
    add_var(fg, "if_gain", "16", 400, 76)
    add_var(fg, "rf_gain", "0", 520, 76)
    add_var(fg, "max_dev", "2.5e3", 640, 76)
    add_var(fg, "tau", "750e-6", 760, 76)
    add_var(fg, "udp_port", "23459", 880, 76)
    add_var(fg, "device_args", '"hackrf,buffers=64"', 1000, 76)

    pcm = add_block(
        fg,
        "network_udp_source",
        "udp_pcm",
        16,
        280,
        type="short",
        port="udp_port",
        header="0",
        payloadsize="320",
        notify_missed="False",
        src_zeros="True",
        ipv6="False",
        vlen="1",
    )
    s2f = add_block(
        fg,
        "blocks_short_to_float",
        "s2f",
        260,
        296,
        vlen="1",
        scale="32768",
    )
    nbfm = add_block(
        fg,
        "analog_nbfm_tx",
        "nbfm",
        480,
        264,
        audio_rate="audio_rate",
        quad_rate="quad_rate",
        tau="tau",
        max_dev="max_dev",
        fh="-1.0",
    )
    resamp = add_block(
        fg,
        "rational_resampler_xxx",
        "resamp",
        720,
        272,
        type="ccc",
        interp="int(samp_rate / quad_rate)",
        decim="1",
        taps="[]",
        fbw="0",
    )
    rot = add_block(
        fg,
        "blocks_rotator_cc",
        "rotator",
        980,
        288,
        phase_inc="-2.0 * math.pi * offset / samp_rate",
        tag_inc_update="False",
    )
    sink = add_block(
        fg,
        "osmosdr_sink",
        "osmo_sink",
        1220,
        256,
        args="device_args",
        sample_rate="samp_rate",
        nchan="1",
        num_mboards="1",
        freq0="freq + offset",
        corr0="ppm",
        gain0="rf_gain",
        if_gain0="if_gain",
        bb_gain0="0",
        sync="none",
    )

    fg.rewrite()
    wire(fg, pcm, s2f)
    wire(fg, s2f, nbfm)
    wire(fg, nbfm, resamp)
    wire(fg, resamp, rot)
    wire(fg, rot, sink)
    save(plat, fg, HERE / "nbfm_tx.grc")


def main() -> None:
    plat = platform()
    make_rx(plat)
    make_tx(plat)


if __name__ == "__main__":
    main()
