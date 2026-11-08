# Specification — `G1T` textures

`G1T` is the texture container of the KTGL engine. On disk it carries `GT1G`, because a `u32`
written as text comes out little-endian. Measured on the supported build (platform word `0x18`,
Switch 2) over the **14,412 `g1t` entries** of the 24 `.fdata` archives: **14,713 textures** in
total, because some files hold more than one.

Everything here is checked by `pkp tex list` / `pkp tex stat` and by the byte-for-byte round trip
of `pkp tex inject`. What was not measured is labelled **inferred**.

Cross-checked against community implementations, without copying code: `gust_tools`
(`gust_g1t.c`, GPL-3.0) and `fmt_g1m` (Joschuka, Noesis). The flag names and masks come from
there; every figure was re-measured here.

---

## 1. File header (28 bytes)

| Offset | Type | Field | Measured |
|---|---|---|---|
| `+0x00` | `char[4]` | magic | `"GT1G"` |
| `+0x04` | `char[4]` | version | `"0600"` ×13,873 · `"1600"` ×527 · `"0500"` ×10 · `"2600"` ×2 |
| `+0x08` | `u32` | `total_size` | file size; the parser requires it to equal `len(data)` |
| `+0x0C` | `u32` | `header_size` | `0x1C` in 14,410 files; `0x20`/`0x24` in 2 |
| `+0x10` | `u32` | `texture_count` | 1 in almost all; up to **8** |
| `+0x14` | `u32` | `platform` | `0x18` in **14,412 of 14,412** |
| `+0x18` | `u32` | `extra_size` | `0` in 14,411 · `1008` in 1 |

After the fixed header:

```
[0x1C, header_size)        "pre-table" bytes (0 in 14,409; 4 B in 2; 8 B in 1)
[header_size, +4*count)    u32 offset[i], relative to header_size
[+4*count, +extra_size)    global extra data (0 almost always, 1008 in 3 files)
```

The table offsets **include the table itself and the global extra data**: the first offset is
`4*count + extra_size`, not `0`. That convention is verified, not assumed: with it, `rebuild()`
reproduces the bytes of all 14,412 entries.

---

## 2. Texture header (8 bytes + a `data[]` section)

At `header_size + offset[i]`:

| Offset | Type | Field | Notes |
|---|---|---|---|
| `+0` | `u8` | `mip_sys` | high nibble = **mip count** (1..12 measured); low nibble = "tile system" (0 ×14,123, 1 ×24, 2 ×37, 3 ×527, 4 ×2). Low nibble semantics **inferred**; it does not change any size |
| `+1` | `u8` | `format` | pixel code (§4) |
| `+2` | `u8` | `dxdy` | low nibble = `log2(width)`, high nibble = `log2(height)`; only valid for powers of two |
| `+3` | `u8[5]` | flags | 40 bits of the `u64` flags, most significant byte first with the nibbles of each byte swapped (that is how `gust_g1t.c` stores them; `g1t._canonical_flags` undoes it) |
| `+8` | `u32` | size of `data[]` | `12` in 14,168 textures; absent (`extra_size` 0) in 545 |
| `+12` | | `data[1]` | `float` depth (**inferred**: always `1.0` in what was measured) |
| `+16` | | `data[2]` | second `u64` of flags, **big-endian** |
| `+16` | `u32` | `data[3]` | real width (only when `data[]` is 16 bytes) |
| `+20` | `u32` | `data[4]` | real height (only when `data[]` is 20 bytes) |
| `+8+len` | | pixels | §3 |

**Measured trap:** in this build the `EXTENDED_DATA` flag (bit 0) is **not** set even though the
`data[]` section is there. The parser does not trust the flag: it detects the section by
arithmetic — what remains up to the next texture must be `len(data[]) + mip chain` aligned to
512 B per level (§3). If the flag happens to be set, it is honoured too.

---

## 3. Pixels and mips

* `mip 0` at `data_offset`, then `mip 1 … mip n-1` **contiguously**, each with half the side
  (minimum 1).
* **Every mip level starts on a multiple of 512 B**; if its pixels are smaller, it occupies the
  whole block — including the last level:

```
offset_0     = 0
offset_{i+1} = offset_i + align512(pixel_bytes(level_i))
```

  Measured over the whole census (14,713 textures):

| Model | Textures | % |
|---|---|---|
| 512 B chain, **exact** | **13,985** | **95.05 %** |
| 512 B chain × N frames (N = 2..8) | 87 | 0.59 % |
| Not explained yet (`tile_system=3`, `data_size` 6–48× the expected) | 641 | 4.36 % |

  An earlier description of this format modelled the same phenomenon as a "+1,368 B / +1,200 B
  trailing padding" and was wrong: `0x558` and `0x4b0` are exactly the remainders the per-level
  alignment produces, and `gust_g1t.exe` reports them as such. This document replaces that
  description.
* `data_size` = bytes up to the next texture or to the end of the file.
* **Padding is preserved as-is**: `inject` rewrites `mip 0` only, leaving the remaining mips and
  the tail untouched, so a `.g1t` never changes size.

---

## 4. Pixel formats

Full census (`pkp tex stat` over the 24 `.fdata`, 14,713 textures):

| Code | Name | Textures | % | Decode | Encode |
|---|---|---:|---:|---|---|
| `0x60` | dxt1 (BC1) | 4,183 | 28.43 % | yes | yes |
| `0x62` | dxt5 (BC3) | 3,527 | 23.97 % | yes | yes |
| `0x66` | bc7 | 3,235 | 21.99 % | yes | yes |
| `0x64` | bc5 | 2,366 | 16.08 % | yes | yes |
| `0x63` | bc4 | 908 | 6.17 % | yes | yes |
| `0x0d` | rgba32f | 241 | 1.64 % | yes | yes |
| `0x0a` | bgra8 | 184 | 1.25 % | yes | yes |
| `0x0c` | rg8 | 35 | 0.24 % | yes | yes |
| `0x65` | bc6h | 22 | 0.15 % | yes | **no** |
| `0x0b` | r32f | 7 | 0.05 % | yes | yes |
| `0x10` | dxt1 | 2 | 0.01 % | yes | yes |
| `0x01` | rgba8 | 2 | 0.01 % | yes | yes |
| `0x12` | dxt5 | 1 | 0.01 % | yes | yes |

**Writable: 14,691 of 14,713 (99.85 %).** The only exclusion is **BC6H** (22 textures, 0.15 %):
there is a decoder (`imagecodecs`) but no encoder — `etcpak` does not implement BC6H and none was
written by hand.

Block size: BC1/BC4 = 8 bytes per 4×4 block; BC3/BC5/BC6H/BC7 = 16; the raw formats take bytes per
pixel according to the table (`rgba8`/`bgra8` 4, `rg8` 2, `r32f` 4, `rgba32f` 16).

---

## 5. Swizzle (tile order)

Blocks are **not** in row order: they go in tiles of `tile × tile` blocks with Z (Morton) order
inside each tile. The tile is clipped to the power of two that divides both dimensions (the same
restriction `gust_g1t.c` applies).

Measurement on a real `dxt1 1024×1024` texture: mean jump between neighbouring pixels horizontally
(`dx`) and vertically (`dy`) when undoing the swizzle with different tiles:

| Tile | `dx` | `dy` |
|---|---|---|
| no swizzle (rows) | 0.25 | **2.18** |
| 2×2 blocks | 0.30 | 1.19 |
| 4×4 blocks (16 px) | **0.34** | **0.38** |
| **8×8 blocks (32 px)** | 0.36 | 0.39 |
| 16×16 blocks (64 px) | 0.42 | 0.36 |
| 32×32 blocks (128 px) | 0.43 | 0.38 |
| 256×256 blocks (whole level) | 0.44 | 0.38 |

In row order the image is incoherent vertically (`dy` 2.18 against 0.25 horizontally); with tiles
of 4–8 blocks both axes drop to ~0.35, which is the minimum. The kit uses **8 blocks (32 px)**, the
Tegra tile size, even though 4 blocks comes out marginally better on this sample: the difference
(0.34 vs 0.36) is smaller than the spread between textures. Coherence was also checked by eye on
decoded PNGs (legible shapes and gradients, no noise).

For the raw 4-byte-per-pixel formats the best tile is **16 px**, and `rg8` comes out better
**without** swizzle. It is in `g1t.FORMATS`, field by field.

---

## 6. What is not solved

* **Low nibble of `mip_sys`** (tile system): 5 values seen, no measured effect on size or decoding.
  It is preserved as-is.
* **`data[1]`** (float): assumed to be depth/mip bias. Always `1.0` in what was measured.
* **`f3`/`f4`/`f5` of the flag block**: copied without interpretation; the known masks from
  `gust_g1t.c` (`SRGB`, `NORMAL_MAP`, `CUBE_MAP`…) **do not match** this build (the bit that is
  `CUBE_MAP` there is set on all 14,713 textures and none of them is a cubemap). No mask is used to
  decide geometry.
* **Mips when repainting**: `inject` replaces level 0 only; levels 1..n keep the original content,
  so a repainted texture looks right up close and keeps the old pattern at distance until the mips
  are regenerated.
* **Putting it back**: `inject` writes a `.g1t`. Returning it to the game's `.fdata` is `.fdata`
  writing, which this version does not implement.

---

## 7. Usage

```bash
# list the textures of a .g1t or of a .fdata (geometry and format)
python -m pokopia.cli tex list <file.g1t|file.fdata> [--json]

# dump level 0 to PNG (needs the optional pixel backend)
python -m pokopia.cli tex extract <file> --g1t 0 --index 0 --out out.png

# re-inject the PNG (same size required), or a neutral round trip
python -m pokopia.cli tex inject <file> --g1t 0 --png out.png --out new.g1t
python -m pokopia.cli tex inject <file> --g1t 0 --same --out new.g1t
```

Pixel backend (optional, not installed with the kit): `numpy`, `imagecodecs` (decode
BC1/BC3/BC4/BC5/BC6H/BC7 + PNG) and `etcpak` (encode BC1/BC3/BC4/BC5/BC7). Without them, `list`
and `inject --same` still work; `extract` and `inject --png` exit with code 2 and say what is
missing.
