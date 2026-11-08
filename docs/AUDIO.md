# Specification — sound banks (`ASRS`/`KTSR`) and your own audio

The game's sound effects live inside the `.fdata` archives as entries of type `srsa` (403 of
them). Each one is a small container: `ASRS` for the file, `KTSR` for the bank, then a sequence of
chunks — one per sound, one per cue, a few per state. The audio itself is **not** decrypted or
unpacked: it is stored raw, either as MS ADPCM or as Koei Tecmo's `KA1A`.

This document covers what is inside a bank, how the kit reads it, and the **three ways to write
one**: swap two sounds, drop another stream into a slot, or encode audio of your own. The last one
only reaches **3.47 % of the banks** and this document says so with the measurement attached.

Everything was measured on the supported build ([README](../README.md#supported-build)). The
external judge is **vgmstream r2168**, which opens these banks with its own `KTSR` parser; where a
number depends on it, it is named.

---

## 1. Where the banks are, and how many

The `.srsa` files are not loose in the RomFS. They are entries of type `srsa`
(`type_ktid` `0xBBD39F2D`) inside one `.fdata` archive, all 403 of them in the same one:

```
pkp fdata extract --type srsa --out <folder> <romfs>/motor_asset_re/<...>/<archive>.fdata
```

| Figure | Value |
|---|---|
| Banks | **403** (199,492,064 B decompressed) |
| Streams | **19,297** |
| Streams with the audio inside the bank | **18,835** — 18,558 `KA1A` + **277 MS ADPCM** |
| Streams whose audio lives in another file the RomFS does not ship | **462**, in 5 banks |
| Sound / cue / state chunks | 19,297 / 6,400 / 24 |
| Sample rates | 12,311 streams at 40,000 Hz, 6,242 at 48,000 Hz, 5 at 44,100 Hz, ~270 outliers (29,118–46,619 Hz) |
| Duration per stream | minimum **0.049 s**, maximum **31.467 s** (1,510,435 samples at 48 kHz) |
| Banks with 41 streams | 370 (the house size: 15,170 of the 19,297 streams) |
| Bank with the most streams | **1,196** |
| Largest bank by size | 13,648,416 B |

There is no music here: effects and short loops. The 5 banks whose streams are external point at
an `.srst` that is not part of the RomFS (its name is hashed away), so that audio cannot be read
even by `vgmstream`.

---

## 2. Container

`ASRS` is a 16-byte wrapper in front of the `KTSR` bank:

| Offset | Type | Field |
|---|---|---|
| `+00` | 4 B | `ASRS` |
| `+04` | u32 | 0 |
| `+08` | u64 | **total file size** |
| `+10` | 4 B | `KTSR` — the bank starts here |

`KTSR` header, offsets relative to `E = 0x10`:

| Offset | Type | Field | Measured value |
|---|---|---|---|
| `+00` | 4 B | `KTSR` | magic |
| `+04` | u32 | id | `0x777B481A` read **big-endian** = a sound bank |
| `+08` | u16 | version | `1` |
| `+0A` | u16 | — | `0x05F0` in all 403 |
| `+0B` | u8 | platform | `5` in all 403 |
| `+0C` | u32 | **audio id** | seed of the name cipher (§5) |
| `+10`, `+14` | u32 ×2 | — | 0 |
| `+18`, `+1C` | u32 ×2 | size of the `KTSR` | file size − `0x10`; both fields equal, and a mismatch means a truncated dump |
| `+30`, `+34` | u32 ×2 | two hashes | identical across the banks measured, not interpreted |

Chunks begin at `0x50` (a 0x40-byte `KTSR` header after the `ASRS`) and run to the end of the file
**with no gaps**:

| Offset | Type | Field |
|---|---|---|
| `+00` | u32 **big-endian** | chunk type |
| `+04` | u32 **little-endian** | chunk size, 8-byte header included (always a multiple of 16) |
| `+08` | … | chunk body |

The endianness mix is the trap: the type is big-endian and the size is little-endian. A walker
that reads both the same way desynchronises on the second chunk and concludes the format does not
close.

Chunk types in this build:

| Type | What it is | Note |
|---|---|---|
| `0xC5CCCB70` | **sound** | one per stream; carries its own header and the audio |
| `0xBD888C36` | **cue / configuration** | holds the stream id and the name; no absolute offsets |
| `0xA9D23BF1` | state container | 24 in the whole dump; not interpreted |

---

## 3. Sound chunk and sound header

| Offset | Type | Field |
|---|---|---|
| `+00` | u32be | `0xC5CCCB70` |
| `+04` | u32le | chunk size, header included |
| `+08` | u32 | **sound id** (what a cue refers to) |
| `+0C` | u32 | flags; `0x0008` = name is encrypted, `0x10000` = external (not seen here) |
| `+10` | u32 | sub-stream count: `1` in all 19,297 |
| `+14` | u32 | delta **to a delta field** (two hops) |
| `+18` | u32 | offset of the name, **relative to the chunk** (0 = no name) |
| `+1C` | u32 | delta; the second hop yields the start of the sound header |

So the header starts at `chunk + u32(chunk + u32(chunk + 0x14))` — **two** hops. With one hop you
land at `0x20000000`, which is how a correct format gets declared broken.

The sound header (`0x6FCAB62E` or `0x6AD86FE9`, same geometry):

| Offset | Type | Field |
|---|---|---|
| `+00` | u32be | sub-header type |
| `+04` | u32 | chunk size **minus** the header offset (`chunk_size − (hoff − chunk)`) |
| `+08` | u32 | subtype hash |
| `+0C` | u32 | **channels** (1 everywhere in this dump) |
| `+10` | u8 | **format**: `0x00` MS ADPCM, `0x01` `KA1A` |
| `+14` | s32 | **sample rate** |
| `+18` | s32 | **samples** |
| `+20` | s32 | **loop start** (`-1` = no loop; the end is `samples`) |
| `+24` | u32 | channel layout |
| `+28` | u32 | offset of the extra header, relative to the sound header |
| `+2C` | u32 | size of that extra header (4) |
| `+30` | u32 | offset of the **start table**, relative to the sound header |
| `+34` | u32 | offset of the **size table**, relative to the sound header |
| `+38`, `+40`, `+44` | u32 | hashes; not interpreted |
| extra header | s32 *or* 2 × u16 | `KA1A`: bitrate mode (may be negative). MS ADPCM: **samples per block** (`+00`, 512) and **bytes per block** (`+02`, 262) |
| start table | u32 × channels | offset of each channel, relative to the sound header, 16-byte aligned |
| size table | u32 × channels | audio bytes per channel |

The audio bytes sit **raw** (no codec header of their own) from the offset in the start table, and
the chunk is zero-padded to the next multiple of 16.

A worked example, three banks, field by field:

```
bank             0x3BA4F753   0x8A27E068   0x01F7A089
size             122,976 B    403,536 B    3,566,880 B
audio id         0x3CDC3E84   0x3CDC3E84   0x3CDC3E84
cue chunks       1            43           59
sound chunks     3            11           82
first sound:
  chunk          0x200 / 41,616  0x4D90 / 17,824  0x5730 / 699,792
  header         0x220           0x4DD8           0x5770
  subtype        0x6FCAB62E      0x6FCAB62E       0x6FCAB62E
  format         0x01 (KA1A)     0x01             0x01
  channels / Hz  1 / 48,000      1 / 48,000       1 / 48,000
  samples        88,870          63,840           1,510,435
  loop           -1              12,888           -1
  data           0x280 / 41,475  0x4E40 / 17,640  0x57D0 / 699,624
```

### Internal and external streams

| Sub-header | Meaning |
|---|---|
| `0x6FCAB62E`, `0x6AD86FE9` | the audio is inside the chunk — 18,835 streams |
| `0x793A1FD7` | the audio lives in a separate `.srst`; format in `+14`, data offset and size in `+34`/`+38`, **relative to that other file** |

The 462 external streams are listed by the kit and **refused** for extraction or replacement,
instead of returning bytes from somewhere else.

---

## 4. The two codecs, and what is missing

| Codec | Streams with data inside the bank | Share | Decoder in the kit |
|---|---|---|---|
| `KA1A` | 18,558 | 98.53 % | yes, to WAV |
| MS ADPCM | 277 | 1.47 % | yes (and an **encoder**, §6) |

`KA1A` is a **transform** codec: frames of 512 samples, 21 bands, per-frame delays. `vgmstream`
decodes it (`ktsr.c`); **no encoder exists outside Koei Tecmo**, and nothing public implements one.
The geometry of all 18,558 streams is accounted for, and the cost of writing an encoder is
estimated at 700–900 lines and 3–5 days in the project's internal notes — which is why this
version does not attempt it.

That is the honest boundary of "your own audio": it works on the MS ADPCM streams and on nothing
else.

---

## 5. Names are encrypted with a known LCG

With flag `0x0008` set, the sound name is encrypted byte by byte with the classic MSVC linear
congruential generator (`0x343FD · x + 0x269EC3`) seeded with the bank's **audio id**; a decrypted
`0` ends the string. It is the same algorithm `vgmstream` documents in `src/meta/ktsr.c`
(`decrypt_string_ktsr`, ISC licence) and it is re-implemented in `pokopia/snd.py`, decoding to
`cp932` when the text is Shift-JIS. `pkp snd list` prints the decrypted name; this repository does
not reproduce the names themselves.

---

## 6. Writing: three routes, and the coverage of each

```
pkp snd list    <bank.srsa> [--json]
pkp snd extract <bank.srsa> --out <dir> [--stream N]
pkp snd stat    <dir>
pkp snd replace <bank.srsa> --swap A B              [-o out | --in-place]
pkp snd replace <bank.srsa> --stream N --file F [--from-banco B --from-stream M]
                                                   [-o out | --in-place]
pkp snd import  <bank.srsa> --stream N --wav F.wav [--loop MS] [-o out | --in-place]
```

| Route | Streams that accept it | Share |
|---|---|---|
| (a) swap two chunks inside one bank | **18,832** | 99.98 % |
| (b) put a stream with the same codec and size into a slot, same bank | **16,898** | 89.72 % |
| (b') the same, taking the stream from any bank in the tree | **18,473** (532 codec+size groups) | 98.08 % |
| (c) **your own audio** (`pkp snd import`, MS ADPCM only) | **277**, in **14 of 403** banks | **3.47 % of the banks** (1.47 % of the streams) |

Routes (a) and (b) **do not re-encode a byte**: they move audio that is already compressed. The 3
streams that reject (a) are alone in their bank (nothing to swap with), but (b) still works on
them. Measured distribution: 384 `KA1A`-only banks, 12 mixed, 2 `MS ADPCM`-only, 5 fully external.

What the writer guarantees in every route:

* the rest of the file is copied byte for byte — no audio is normalised;
* the three sizes (`ASRS`, `KTSR`, chunk) and the size table stay coherent with the result, and
  the modified bank is re-parsed by the kit's own reader before it is accepted;
* `--in-place` writes `<bank>.orig` the first time and never overwrites it on later passes, so the
  undo stays available;
* `paths.guard_writable` refuses to write inside the RomFS.

Undo is `cp bank.srsa.orig bank.srsa`; the sha256 returns to the original, which the verification
scripts check.

### The MS ADPCM encoder

`pkp snd import` encodes your WAV **locally** (no `ffmpeg` at run time) with the block geometry the
destination declares: in this dump every block is **262 B = 512 samples** (7-byte header + 255
bytes of nibbles). The encoder picks, per block, the best of Microsoft's seven factory
coefficients, restarts the prediction with the two real samples of each block, and emits the
nibbles high-first.

Measured round-trip quality: **55.5 dB SNR** for a 440 Hz sine, **47.0 dB** for 1 kHz. `vgmstream`
decodes the result **sample for sample identical** to the kit's own decoder (`>> 8` in the
prediction, as `msadp32.acm` does); `ffmpeg` differs in a few samples because it truncates towards
zero.

Why not just use `ffmpeg`? Its `adpcm_ms` encoder requires a block size that is a power of two
(`ffmpeg -h encoder=adpcm_ms`), and these banks use 262 B. Hence the encoder in this repository.

The command rewrites rate, sample count, loop and the samples/bytes-per-block pair, and leaves the
sound id, the name, the codec and every other stream untouched. A stereo WAV is **refused**
instead of being silently mixed down, and so is a sample outside PCM16 range.

---

## 7. Verifying with vgmstream

`vgmstream` r2168 opens these banks through `ktsr.c` and `-s N` selects a stream. It is the judge
of the *file*, not of the engine. The verification used here (with the author's scripts, which are
not part of this release) compares, before and after, the stream count, the sample count and the
sha256 of every decoded WAV, and fails if the bank stops opening, if the count changes, if the
touched stream does not change or if an untouched one does.

For your own audio there are two extra checks, and both can be repeated with a plain `vgmstream`
build: the PCM it returns matches the kit's decoder sample for sample (**0 differing samples** on
the reference tone), and the tone you inserted dominates the decoded audio.

What this does **not** prove: that the game's engine accepts the result. For that the bank has to
go back into its `.fdata`, and `.fdata` writing is not implemented in this version — so a modified
bank stops at a file in `build/`. **Nothing from this route is known to sound in the game yet.**

---

## 8. Provenance

* **vgmstream** (ISC) — `src/meta/ktsr.c` documents the container and the name cipher. No code was
  copied; the kit's reader and writer are new.
* **FFmpeg** (LGPL/GPL) — `libavcodec/adpcm.c`, `adpcm_data.c`, `adpcm_data.h` were read for the
  factory coefficient table and the block arithmetic; no code was copied.
* **Microsoft** — the MS ADPCM block specification (7-byte header, adaptive delta, 4-bit
  nibbles).

---

## 9. Reproduce it

```
export PKP_ROMFS=<folder with your LD_C0_R.BIN and LI_C0_R.IDX>
python pkp.py fdata extract --type srsa --out build/srsa "$PKP_ROMFS"
python pkp.py snd stat build/srsa
```

`pkp snd stat` prints the bank count, the streams with audio inside, the codec histogram and how
many streams each write route accepts. On the supported build it must print **403** banks,
**18,835** streams with audio inside, `{'ka1a': 18558, 'msadpcm': 277}`, and **277** gives the
MS ADPCM coverage figure of §6: counting the banks that hold at least one of those 277 streams
(`pkp snd list --json` per bank) gives **14 of 403 = 3.47 %**.
