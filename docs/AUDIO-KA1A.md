# Specification — `KA1A`, the Koei Tecmo transform codec

Written so that **someone else** can implement it without reading our code: stream layout inside
the bank, frame by frame, tables, codes and window. At the end, the encoder this kit ships, its
limits and the measured figures.

`KA1A` is the codec of **18,558 of the 18,835** streams whose audio lives inside the 403 sound
banks of build 2.0.1a (98.53 %; the remaining 1.47 % is 277 `MS ADPCM` streams). It is not ADPCM:
it is a **512-sample transform** with an overlap window, 21 spectral bands and coefficients
quantised into 8-bit logarithmic codes. No public encoder existed before this one; everything here
was written by inverting the **decoder** of `vgmstream` r2168.

> **Attribution.** The description was derived from `vgmstream` r2168,
> `src/coding/libs/ka1a_dec.c` (568 lines) and `src/coding/libs/ka1a_dec_data.h` (247 lines),
> whose `COPYING` is **ISC** (Copyright (c) 2023-2025 vgmstream contributors). The tables in
> `pokopia/ka1a_tablas.py` are **generated** from that file by a script, not copied by hand. The
> bank parser (`ASRS`/`KTSR`) is in [AUDIO.md](AUDIO.md) §2.

---

## 1. Where a `KA1A` sits inside the bank

Each sound is a `KTSR` chunk with its own header; the codec is declared in one byte and the audio
is described by five fields:

| Field | Sound-header offset | Value in `KA1A` |
|---|---|---|
| format | `+0x10` (`u8`) | `0x02` |
| sample rate | `+0x14` (`s32`) | 29,118..48,000 Hz in this dump (158 distinct values) |
| samples | `+0x18` (`s32`) | PCM samples the decoder returns |
| loop | `+0x20` (`s32`) | `-1` = no loop, otherwise the start sample |
| extra header | `+0x28` (`u32`, relative to the sound header), `+0x2C` (`u32` size) | 4 B |
| **bitrate mode** | extra header, `+0x48` (`s32`) | `-5`..`+5` |
| data | `+0x4C` (`u32` relative), `+0x50` (`u32` size) | raw `KA1A` stream |

The **bitrate mode** is the only thing that changes from one stream to another: it fixes how many
coefficients are coded per band and therefore the frame size. Measured distribution in this dump:

| mode | `-2` | `-1` | `+0` | `+1` | `+4` |
|---|---|---|---|---|---|
| streams | 12,311 | 232 | 1,456 | 52 | 4,507 |
| frame bytes | 125 | 140 | 155 | 173 | 237 |

And the invariant we check on all 18,558:

```
data size == (ceil(samples / 512) + 1) * frame_bytes(mode)
```

The `+ 1` is the encoder's **delay** frame (§5). Zero exceptions in the dump
(`tools/snd/cobertura_audio.py` counts them: "geometria KA1A: 0 streams").

---

## 2. The frame

A frame is **512 PCM samples**, coded in `4 + S + C` bytes:

```
+0x00  f32   frame scale factor (little-endian)
+S     ...   sub-positions  ·  S = ceil(sub-position bits / 8)
+C     ...   codes          ·  C = ceil(code bits / 8)
```

The scale factor multiplies every coefficient of the frame. If it is **negative** the sub-mode of
§4 is enabled (a different code distribution across bands); the decoder handles it and **our
encoder never writes it negative**, because we choose the distribution from the table instead.

| mode | sub-positions `S` | codes `C` | frame | kbit/s @40 kHz | kbit/s @48 kHz |
|---|---|---|---|---|---|
| `-5` | 26 | 66 | **96** | 60.0 | 72.0 |
| `-4` | 30 | 70 | **104** | 65.0 | 78.0 |
| `-3` | 36 | 75 | **115** | 71.9 | 86.2 |
| `-2` | 42 | 79 | **125** | 78.1 | 93.8 |
| `-1` | 50 | 86 | **140** | 87.5 | 105.0 |
| `+0` | 59 | 92 | **155** | 96.9 | 116.2 |
| `+1` | 51 | 118 | **173** | 108.1 | 129.8 |
| `+2` | 59 | 131 | **194** | 121.2 | 145.5 |
| `+3` | 67 | 144 | **215** | 134.4 | 161.2 |
| `+4` | 76 | 157 | **237** | 148.1 | 177.8 |
| `+5` | 84 | 170 | **258** | 161.2 | 193.5 |

The frame bytes match the ones `vgmstream`'s decoder declares (`ka1a.c`:
`{0x60,0x68,0x73,0x7d,0x8c,0x9b,0xad,0xc2,0xd7,0xed,0x102}` = 96..258).

---

## 3. The 21 bands

The spectrum of 512 coefficients is split into 21 bands. Each band starts at a fixed coefficient
and keeps `n` coefficients inside a window of `2^bits` positions:

| band | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| start | 0 | 5 | 10 | 15 | 20 | 25 | 30 | 35 | 40 | 50 | 60 | 70 | 80 | 100 | 120 | 140 | 170 | 200 | 240 | 300 | 390 |
| position bits | — | — | — | — | — | — | — | — | 4 | 4 | 4 | 4 | 5 | 5 | 5 | 5 | 5 | 6 | 6 | 7 | 7 |
| positions | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 16 | 16 | 16 | 16 | 32 | 32 | 32 | 32 | 32 | 64 | 64 | 128 | 128 |

Two consequences that matter when writing:

* bands **0..7** carry no position: they are coefficients `0..39` in order (`5·band + j`). Their
  `n` codes are always 5 and they go first in the code block;
* bands **8..20 overlap** (band 20 reaches 390+128 = 518, past 511) and **the same coefficient can
  fall in two bands**. If a frame codes a coefficient twice, the last write wins, so a sensible
  encoder never repeats positions.

Codes per band (`n`), by table index:

| band | 0-7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `-5` | 5 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| `-4` | 5 | 5 | 5 | 5 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| `-3` | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 3 | 3 | 3 | 3 |
| `-2` | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| `-1` | 5 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 5 | 5 | 5 | 5 | 5 | 5 |
| `+0` | 5 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 |
| `+1` | 5 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| `+2` | 5 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 |
| `+3` | 5 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |
| `+4` | 5 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 |
| `+5` | 5 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 |

With this the bytes come out, and they have to be **computed**, not copied. In mode `-2`, with 5
codes in all 21 bands:

* sub-positions: `4·5·4` bits (bands 8..11) + `5·5·5` (12..16) + `6·5·2` (17, 18) + `7·5·2`
  (19, 20) = 335 bits = **42 B**;
* codes: `8·40` (bands 0..7) + `8·13` (main codes) + `4·13·4` (sub-codes) = 632 bits = **79 B**;
* frame: 4 + 42 + 79 = **125 B**, which is what the dump measured.

---

## 4. The codes

Everything is packed **LSB first** (bit 0 of the byte is the first bit), like the reader in
`ka1a_dec.c`.

### 4.1 Sub-positions

For each band 8..20, for each of its `n` codes, in order: `position_bits[band]` bits with the
position inside the band (`0..2^bits-1`). The coefficient is `start[band] + position`; if it falls
outside `0..511` it is discarded (happens in band 20).

### 4.2 Codes, in this order

1. bands **0..7**: `8·5 = 40` codes of 8 bits, in band order (`0..39` of the code block);
2. bands **8..20**: first the **main code** of each band (13 codes of 8 bits, one per band, in
   order);
3. then, for each band 8..20 in order, its remaining `n-1` codes:
   - modes `-5..+1`: a **4-bit sub-code** relative to the main code of its band, two per byte,
     low nibble first, in a continuous stream that crosses band boundaries;
   - modes `+2..+5`: an **absolute 8-bit code**, one byte each.

### 4.3 Absolute 8-bit code → coefficient

```
if code == 0:            value = 0
if code < 128:  m = code;        value =  exp((m - 127) * 0.086643398) * scale
if code >= 128: m = 256 - code;  value =  exp((m - 127) * 0.086643398) * (-scale)
```

That is: codes `1..127` are the positive values from smallest to largest (`127` = `1·scale`), and
`128..255` the negative ones from largest to smallest (`128` = `-1.0905·scale`, `255` = the
smallest negative), with the sign carried by the **scale**, not the exponent. The step
`0.086643398` is `ln(1.0905)`: each code rises **9.05 %** (0.75 dB). `0` is exact zero and `255`
is worth `exp(-126·step)·scale ≈ 1.8e-5·scale`, so the dynamic range of a frame is about **95 dB**
with 127 steps per sign. `_codigo_a_coef` reproduces that arithmetic to the letter.

### 4.4 4-bit sub-code → coefficient

```
value = (code * 0.14285715 - 1) * main
```

`0.14285715` ≈ `1/7`, so the sub-code sweeps **±100 % of the main value in steps of 1/7**:
`0` = −main, `7` = 0, `14` = +main. It is the reason the main code of each band has to be the
**largest-magnitude** coefficient: the others are expressed as a fraction of it and cannot exceed
±100 %.

### 4.5 The negative-scale sub-mode

If the frame's `f32` is negative, the code distribution moves: `band_codes[8..12] += mod` and
`band_codes[17..20] -= mod`, with `mod = BITRATE_SUBMODE[index]` =
`{0, 0, 0, 2, 2, 2, 4, 3, 2, 1, 0}` for indices 0..10 (modes `-5..+5`), and the `f32` is used as an
absolute value. It is a cheap way to give more codes to the high end without changing the frame
size. **We do not use it when writing**: with a positive factor the distribution is the one in the
table and the frame is predictable; the decoder supports it for game frames that carry it.

---

## 5. The transform

* **Window**: `OVERLAP_WINDOW[512]` from `ka1a_dec_data.h` (`static const float`), verbatim,
  duplicated mirrored: the analysis/synthesis window of 1024 samples is `w[0..511] ++ w[511..0]`.
  It is not derived from a formula in our code: it is the decoder's table. Its first three values
  are `0.00041374451, 0.00063187029, 0.00083242479` and the last two `0.99999976, 0.99999988`; it
  satisfies `w[i]² + w[511-i]² = 1` (power-complementary window). If your port does not give those
  numbers, nothing else will line up.
* **Synthesis (decoder)**: `y = IMDCT(c)` from 512 coefficients to 1024 samples, with the `1/512`
  normalisation `vgmstream` uses:

  ```
  y[m] = sign(m) * DCT-IV(c)[pos(m)] / 512
  ```

  where the folding `pos(m), sign(m)` is the usual one: `t = m + 256`; if `t ≥ 1024` → `t -= 1024`
  and flip the sign; else if `t ≥ 512` → `t = 1023 - t` and flip the sign.
* **Overlap**: frame `f` produces 1024 samples; the first 512 are added (weighted by `w[i]`) to the
  last 512 of the previous frame (weighted by `w[511-i]`), and the last 512 are kept for the next
  frame. **The first frame returns no samples** (it is the encoder's delay), which is why there are
  `ceil(n/512) + 1` frames.
* **Analysis (encoder)**: the exact inverse. The 1024-sample block is windowed (same window),
  folded with the synthesis map and the DCT-IV is applied **with factor 2**:

  ```
  c = 2 * DCT-IV( fold( w * x ) )
  ```

  It is the inverse of the synthesis: with that window, `analysis → synthesis → overlap`
  reconstructs the signal with `max |error| = 2.7e-07` and **SNR of 129.8 dB** (measured with 4096
  samples; the test `test_la_transformada_es_exactamente_invertible` checks it on every run).

The 512-point DCT-IV is implemented with a 1024-point radix-2 FFT. The kit uses its own pure-Python
FFT and validates the result against the decoder, not against the tables.

---

## 6. The kit's decoder

`pokopia/audio.py` → `ka1a_decode(stream, mode, samples) -> list[float]` (−1..1) and
`ka1a_decode_pcm16(...) -> list[int]` (the same thing `vgmstream` writes to WAV: `int(v·32767)`,
truncating toward zero and saturating). Pieces: `ka1a_frame_size`, `ka1a_frame_count`,
`ka1a_frame_info`, `_ka1a_desempaqueta_frame`, `_ka1a_imdct` + `_plegado`.

**Measured accuracy.** 5 modes × 8 streams per mode, 1,671,671 samples of real audio from 5
different banks, compared with `vgmstream` r2168 sample by sample:

| mode | samples | different | % | worst |
|---|---|---|---|---|
| `-2` | 177,661 | 148 | 0.083 % | 1 LSB |
| `-1` | 395,995 | 159 | 0.040 % | 1 LSB |
| `+0` | 433,657 | 39 | 0.009 % | 1 LSB |
| `+1` | 445,034 | 37 | 0.008 % | 1 LSB |
| `+4` | 219,324 | 187 | 0.085 % | 1 LSB |
| **total** | **1,671,671** | **570** | **0.034 %** | **1 LSB** |

The 570 differences are the final rounding: `vgmstream` accumulates in `float`, the kit in
`double`. One 16-bit LSB is 0.003 % of full scale: floating-point noise, not an algorithm
discrepancy.

---

## 7. The kit's encoder

`ka1a_encode(samples_pcm16, mode) -> bytes`. For each frame:

1. **Analyse** the 1024-sample block (§5) and get 512 coefficients.
2. **Distribute**: bands 0..7 with their 5 fixed positions; in each band 8..20, the `n`
   **largest-magnitude** positions not already coded by a previous band (the bands overlap; not
   repeating positions avoids throwing codes away).
3. **Scale**: the frame factor is the magnitude of the largest chosen coefficient (always `≥ 0`,
   see §4.5). That way the main code of each band fits the code range.
4. **Main first**: inside each band 8..20 the largest-magnitude coefficient goes first, because it
   is the one coded absolutely and the one the sub-codes reference (±100 %, §4.4).
5. **Quantise** each coefficient to the nearest code **in the logarithmic domain**
   (`_coef_a_codigo`: rounds `127 + ln(|v|/scale)/step`), and the sub-codes to
   `(v/main + 1)/step` rounded to `0..14`.
6. If the block is **silent** (all coefficients are 0) it writes a zero frame: scale 0, positions 0
   and codes 0. `vgmstream` decodes it as exact silence (tested).

What it does **not** do: it does not try several band assignments (it is greedy, one pass), it does
not use the negative-scale sub-mode, it does not allocate bits by psychoacoustics and it does not
search for a global optimum. That explains the numbers in §8 and is what to improve if more quality
is ever needed.

---

## 8. Measured quality (round trip, 0.5 s of signal)

`SNR` between the input PCM16 and what the kit's decoder returns; `peak` is the maximum of the
decoded PCM with the signal at half scale (16,383). None of this is "it sounds fine": it is a
number.

| signal | mode `-2` @40k | `+0` @40k | `+4` @40k | `-2` @48k | `+0` @48k | `+4` @48k |
|---|---|---|---|---|---|---|
| 440 Hz sine | 39.58 dB | 39.60 | 39.62 | 37.52 | 37.53 | 37.53 |
| 1 kHz sine | 41.24 | 41.48 | 41.73 | 37.77 | 37.82 | 37.84 |
| 3 kHz sine | 26.55 | 26.64 | 37.55 | 21.76 | 21.81 | 35.16 |
| 3-tone chord | 33.95 | 34.00 | 34.05 | 35.11 | 35.13 | 35.15 |
| white noise | 2.99 | 3.74 | 4.43 | 2.98 | 3.73 | 4.42 |

Honest reading of the table:

* **harmonic material** (almost all game audio: tones, voices, music): 33-42 dB, which is decent
  lossy-codec quality;
* **high end**: a 3 kHz tone suffers because in modes `-2`/`+0` the band that contains it has 3 or
  7 codes and its neighbours are coded in steps of 1/7 of the main value; with 9 codes (`+4`) it
  rises to 35-37 dB. If the destination allows choosing the mode and the material is bright, `+4`
  is the choice;
* **noise**: 3-4 dB. The format codes between 92 and 170 of 512 coefficients, so a flat spectrum is
  the worst thing you can give it; it is not an encoder bug but the frame size. Audio with a lot of
  noise (rain, wind, static) will sound bad in `KA1A` and there is no way to fix it without
  changing the codec.

Speed (pure CPython 3.11, no extensions): **5 s of 48 kHz audio → 0.65 s to encode and 0.53 s to
decode** (~7.7× and ~9.4× real time). Enough for the kit; not for a player.

---

## 9. How it is checked

With the dump mounted (`PKP_ROMFS`) and `vgmstream` r2168 in `VGMSTREAM_CLI`:

```
# 1. the decoder, against vgmstream, on 40 real streams of 5 modes
python tools/snd/decodificador_vs_vgm.py build/<task>/srsa

# 2. your own audio end to end, on a COPY of a real bank
python tools/snd/tono.py --out build/tone.wav --hz 440 --seconds 1 --rate 48000
python tools/snd/verifica_audio_propio.py build/<task>/srsa/<bank>.srsa \
    --stream 1 --wav build/tone.wav --work build/audio --tono 440

# 3. the suite: 31 KA1A tests, two of them with vgmstream as judge
python run-tests.py
```

The figures in this document come from those three commands plus `tools/snd/cobertura_audio.py`.
Those scripts are part of the measurement tree, which is **not** shipped in this release; the
tests in `tests/` are.

---

## 10. Known limits

* **No stereo**: the dump has not a single `KA1A` with more than one channel; the encoder writes
  mono and `pkp snd import` rejects a stereo WAV instead of mixing it down on its own.
* **The mode is not chosen by you**: `pkp snd import` encodes with the mode the destination stream
  declares (that is what keeps frame size and header coherent). To use another mode you would have
  to change the extra header's `s32` and the data size at the same time, and the command does not
  do that today.
* **Noise and transients**: §8. A `KA1A` is no place for dry percussion or noise.
* **The engine has not been tested**: `vgmstream` validates parser and decoder; for the game to
  read it, the `.srsa` has to go back into its `.fdata`, which is still pending.
