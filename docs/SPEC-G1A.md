# Specification — `G2A` animations (type `g1a` in the container)

Skeletal animation of the KTGL engine: what makes objects and creatures move. In the supported
build there are **17,457 files** of type `g1a` (`type_ktid` `0x6fa91671`) inside the `.fdata`
archives, all compressed, **697,681,192 bytes** decompressed.

Status: **read, exported, modified and re-injected byte for byte**. Reading and writing live in
`pokopia/anim/` (`g2a.py`, `serial.py`, `source.py`); the CLI is
`pkp anim list|info|export|build|roundtrip|set`.

Provenance: the scheme was cross-checked against Joschuka's `fmt_g1m` (**GPL-3.0**,
`Noesis/plugins/python/fmt_g1m.py`, function `processG2A`, which handles version `0500` with the
same skeleton). **No code was copied**: reader and writer are new, and what is published here are
fields measured on the dump, not game content.

---

## 1. Where they live and how to get one

| Figure | Value |
|---|---|
| Archive that holds them | one single `.fdata` (836 MiB) — **all** `g1a` entries are in it |
| Entries | 17,457, **all 17,457 compressed** |
| Decompressed bytes | 697,681,192 |
| Size per animation | 168 B … 470,896 B (median 30,230 B) |
| Distinct sizes | 11,092 |

```
pkp fdata extract --type g1a --out <folder> <...>.fdata          # 697 MB: one at a time
pkp anim list  <...>.fdata [--deep] [--limit N]
pkp anim info  <...>.fdata --hash 0x71fd2510
```

**No extraction is needed to read one**: `--hash` selects the entry inside the `.fdata` and the
reader decompresses it in memory.

---

## 2. Two families, not one

| Magic (u32 LE) | On disk | Version | Files | Format |
|---|---|---|---|---|
| `0x4732415F` | `_A2G` | `0400` | **17,428** (99.83 %) | this document |
| `0x4731415F` | `_A1G` | `2400` | **29** (0.17 %) | older, **not supported** |

Both families start with `G`, and the container's type name (`g1a`) corresponds to the *old* magic:
**99.83 % of the animations in the game are `G2A`**. The trap is the usual one in KTGL: the
canonical `u32` written as text comes out reversed on disk, so `grep -a 'G2A_'` over the dump finds
**zero** and `grep -a '_A2G'` finds them. The 29 `G1A_` files are detected and rejected **by name**
(`AnimFormatError`), not mistaken for a broken file; their header is not `G2A`'s either (the size
formula fails on 29 of 29).

---

## 3. Header (32 bytes)

| Offset | Type | Field | What it is |
|---|---|---|---|
| `0x00` | `4s` | magic | `_A2G` on disk (= `G2A_`, u32 `0x4732415F`) |
| `0x04` | `4s` | version | `0400` |
| `0x08` | `u32` | `fileSize` | real file size |
| `0x0c` | `f32` | `frameRate` | 60.0 in 17,420; 30.0 in 8 |
| `0x10` | `u32` | `packed` | bits 0..17 = **length in frames**; bits 18..31 = size of the bone section in bytes |
| `0x14` | `u32` | `timingSize` | bytes of the timing section |
| `0x18` | `u32` | `keyBlockCount` | quantised 32-byte data blocks |
| `0x1c` | `u32` | `reserved` | 0 in all 17,428 |

Measured trap: version `0500` of the same format inserts one more `u32` after `keyBlockCount` and
changes the bone-section packing (8-bit boneID and a 20-bit offset instead of 10 and 18). Here the
version is **`0400`** and the header is a fixed 32 bytes: reading it with the `0500` layout shifts
the bones by 4 bytes and everything after is garbage, with no warning.

---

## 4. Bone section

`boneSectionSize / 4` entries of `u32`, one per animated bone:

| Bits | Field | What it is |
|---|---|---|
| 0..3 | `splineCount` | tracks of that bone (3 in every one of the dump: rotation, translation, scale) |
| 4..13 | `boneID` | bone index, **10 bits** |
| 14..31 | `timingOffset` | offset of its records inside the timing section |

`boneID` wraps: whenever it drops below the previous value, another wrap of 1024 is added
(`bone_id = boneID + 1024·wrap`). In all 17,428 files the maximum is **242 bones**, so **the wrap
never appears in this dump** — but the reader implements it and the writer stores the raw 10-bit
value, so nothing is lost if it ever does.

`splineCount` is **3 in 17,373 animations (99.68 %)**, the ones with rotation, translation and
scale on every bone. The other 55 carry 1 or 2 on some bones (243 bones of the dump have a single
track, 452 have two): it is not another format, it is **missing channels**, and the reader does not
assume 3. In total there are 4,243,663 tracks: 1,414,867 rotation, 1,414,624 translation and
1,414,172 scale (13 animations without translation and 53 without scale).

---

## 5. Timing section

For each bone, `splineCount` **consecutive** records; the offset of the first one is in its entry of
the previous section:

| Type | Field | What it is |
|---|---|---|
| `u16` | `opcode` | 0 = rotation, 1 = translation, 2 = scale |
| `u16` | `keyFrameCount` | keys in the record |
| `i32` | `firstDataIndex` | index of the first 32-byte block |
| `u16[keyFrameCount]` | `timings` | absolute frame of each key |
| — | padding | up to a multiple of **4 absolute** (not relative to the record) |

The padding is the count you have to get right: a one-key record measures `2+2+4+2 = 10` bytes but
occupies **12**; a two-key record measures 12 and occupies 12; a three-key one, 14 → **16**. Without
that alignment the section does not close and the whole file reads shifted. In the dump **the
padding is always zero** (0 non-zero bytes across 17,428 files), and the writer emits zeros: if a
file carried garbage in the pad, the identity test would expose it.

`timings` are frames at 60 fps, **strictly increasing**, with the first key always at **0**
(4,243,663 of 4,243,663 tracks) and the last one **always below** `length_frames` (no track ends on
the last frame). Between consecutive keys the span is `timings[k]` … `timings[k+1]−1`, and the last
key holds until the end.

---

## 6. Data section: the 32-byte block and its quantisation

`keyBlockCount` blocks of **32 bytes** = 4 × `int64`. Each `int64` carries:

| Bits | Field | Sign |
|---|---|---|
| 0..19 | `z` | signed (20 bits) |
| 20..39 | `y` | signed (20 bits) |
| 40..59 | `x` | signed (20 bits) |
| 60..63 | `exponent` | 0..15 |

and the value of each component is

```
component = field · 2**(exponent − 15)
```

That is: `exponent = 15` gives 1-unit resolution (range ±524,287) and `exponent = 0` gives
2⁻¹⁵ ≈ 3.05e−5 (range ±16). The three components of a row **share the exponent**: touching one
without respecting it spoils the other two.

Block `k` of a spline covers the span that **starts at `timings[k]`**, and its four rows are the
coefficients of a cubic per component:

```
v(t) = c0 + c1·t + c2·t² + c3·t³        t = (frame − timings[k]) / (timings[k+1] − timings[k])
```

* **rotation**: `v(t)` is an **axis-angle** vector in radians; it is turned into a quaternion with
  Rodrigues (`s = sin(a/2)/a`, `w = cos(a/2)`);
* **translation** and **scale**: `v(t)` is the vector as-is.

Checks that the decoding is not invented (file `0x71fd2510`):

| Check | Result |
|---|---|
| scale: `c0` of the 46 bones | 0.99997 … 1.00000 (max `\|x\|` 1.0000) → rest pose = 1 |
| rotation: norm of the baked quaternion | 1.0 on every frame (Rodrigues does not deform) |
| rotation: axis-angle magnitude | 0 … 3.1402 rad (π) — never impossible angles |
| translation: `c0` | 0 … 11.0 units, coherent between neighbouring bones |

---

## 7. The invariant that closes the format

```
0x20 + boneSectionSize + timingSize + keyBlockCount·32 == fileSize
```

It holds in **17,428 of 17,428** `G2A` files. It is the proof that no section is missing or extra,
and with it a file of the other family or a shifted read is detected in a second. On top of that,
walking the timing section with the `timingOffset`s and the padding consumes **exactly**
`timingSize`, and `firstDataIndex` runs in order from 0 (blocks are referenced in the order they
appear: `used_blocks == keyBlockCount` in all 17,428).

---

## 8. Commands

```
# list (fast: headers only; --deep parses and counts splines/keys)
pkp anim list <file.fdata | folder | file> [--deep] [--limit N] [--json]

# anatomy of one: fields, geometry, channels, bones, and whether rewriting it gives the same bytes
pkp anim info <path> [--hash 0x...] [--bone N] [--json]

# export: lossless JSON (to rewrite) or baked CSV (to read)
pkp anim export <path> [--hash 0x...] --out <a.json|a.csv> [--format json|csv]

# rewrite from the JSON and compare
pkp anim build <a.json> --out <b.g1a>
pkp anim roundtrip <path> [--hash 0x...] [--out <c.g1a>]

# change ONE value of ONE key and re-inject
pkp anim set <path> --bone 1 --channel translation --frame 0 --axis y --value 3.5 \
             --out <mod.g1a>
```

Export formats:

* **lossless JSON**: header, bones, splines, `timings` and the raw `int64`s of the blocks. `export`
  + `build` returns the file **byte-for-byte identical** (the test, the CLI and the census check
  it).
* **baked CSV**: `bone_id,channel,frame,time_s,x,y,z,w`, with the cubic evaluated frame by frame
  (quaternion for rotation). It is for looking and checking, **not** for rebuilding: it is a
  sampling.

---

## 9. What it covers, and what it does not

* Covers **17,428 of 17,457** animations (99.83 %) of the supported build, with identical rewrite
  in all 17,428.
* Does **not** cover the 29 `G1A_` `2400` files (0.17 %).
* Does **not** interpret what the bones mean or pair them with the model (`g1m`) that uses them:
  that is other work. Here the file is read and written.
* **Cloth/physics** animations are not in these files (same as `fmt_g1m`), so they do not appear
  here.
