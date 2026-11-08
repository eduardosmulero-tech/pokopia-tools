# Specification — `G1M` models

`G1M` is the model container of the KTGL engine: a header, a chain of chunks and, inside the
`GM1G` chunk, a table of sections with vertex buffers, index buffers, submeshes, materials and
shader parameters.

On disk it carries `_M1G`, the little-endian reading of the constant `0x47314D5F`; the canonical
string `G1M_` never appears. Measured on the supported build.

Status: **read**. There is a reader in the package (`pokopia/g1m.py`, standard library only) that
parses the structure, counts the mesh and localises differences field by field. There is **no
writer in this release**: repacking a model is done with a community tool, and its measured
results are reported in §7 with the tool named.

---

## 1. Where they live

Two places, and the container is not the important one:

| Place | `g1m` entries | Bytes | What is in there |
|---|---|---|---|
| The container (`LD_C0_R.BIN`, census over all 12,298 entries) | **3** | — | three toy meshes of **33–57 vertices**, version `7300`, 4 chunks |
| The 24 `.fdata` archives next to it | **3,204** | 283,331,492 | every real model: characters, props, with several buffers per mesh, bones and materials |

The same census finds **55 `GT1G`** entries in the container (1,201 textures inside) and
**14,412 `g1t`** in the `.fdata` — see [SPEC-G1T.md](SPEC-G1T.md).

---

## 2. Two traps that cost a full sweep

1. **The magic is not a string.** `G1M_` as a `u32` is written `5F 4D 31 47`, which on disk reads
   `_M1G`. Searching the dump for the canonical strings `G1M\0` or `G1M_` finds **zero** files.
2. **The model is not at offset 0.** The three container entries start with a **12-byte wrapper**
   (`u32 1 | u32 12 | u32 length`) and the model begins at `+12`. A classifier that only accepts
   "magic in byte 0" loses **100 %** of the models in this game.

`g1m.clasificar(blob)` handles both: it scans the first bytes for the real constants and returns
the offset, so a wrapped model is classified as `g1m` with `offset == 12`.

---

## 3. File header (24 bytes)

| Offset | Type | Field | Measured |
|---|---|---|---|
| `0x00` | `char[4]` | magic | `_M1G` (constant `0x47314D5F`) |
| `0x04` | `char[4]` | version | `7300` in all three container models |
| `0x08` | `u32` | `total_size` | file size; the reader reports a problem if it does not add up |
| `0x0C` | `u32` | offset of the first chunk | **24** |
| `0x10` | `u32` | reserved | 0 |
| `0x14` | `u32` | chunk count | **4** |

Chunks: `magic(4) | version(4) | u32 size`. That `u32` is the **total size of the chunk,
header included**: the next chunk starts at `pos + size`. With the opposite convention
(`pos + 12 + size`) the second chunk lands in the middle of the data and the walk leaves the
file. The four chunks plus the 24-byte header add up to the declared size exactly.

Known chunk magics: `FM1G`, `SM1G`, `MM1G`, `GM1G`, `EM1G`, `OM1G`.

---

## 4. `GM1G`: the geometry chunk

`GM1G` is its own header at the same time: **48 bytes** with

| Offset | Type | Field |
|---|---|---|
| `0x00` | `char[4]` | `GM1G` |
| `0x04` | `u32` | version, ASCII (`7300` in the real files) |
| `0x08` | `u32` | size, header included |
| `0x0C` | `char[4]` | platform, `"NX"` |
| `0x10` | `u32` | reserved |
| `0x14` | `6 × float` | bounding box |
| `0x2C` | `u32` | section count |

Sections start at byte 48 and each one is `magic(4) | u32 size | u32 count`, with `size` including
its own 12-byte header:

| `magic` | Name | What the reader does |
|---|---|---|
| `0x00010001` | `GEOMETRY_SOCKETS` | not interpreted |
| `0x00010002` | `MATERIALS` | not interpreted |
| `0x00010003` | `SHADER_PARAMS` | not interpreted |
| `0x00010004` | `VERTEX_BUFFERS` | **parsed** |
| `0x00010005` | `VERTEX_ATTRIBUTES` | not interpreted |
| `0x00010006` | `JOINT_PALETTES` | not interpreted |
| `0x00010007` | `INDEX_BUFFER` | **parsed** |
| `0x00010008` | `SUBMESH` | **parsed** |
| `0x00010009` | `MESH_LOD` | not interpreted |

### 4.1 Vertex buffers

Per buffer: `u32 unknown | u32 stride | u32 vertex count | u32 reserved` and then
`stride × count` bytes. **From version `0400` upwards** (and every file in this game is above it)
there is one **extra `u32`** after the three fields and before the data. A reader that skips it
misaligns every vertex and the numbers look plausible for a while.

### 4.2 Index buffers

Per buffer: `u32 index count | u32 bits (16 or 32) | u32 reserved`, the same extra `u32` above
version `0400`, then the indices.

### 4.3 Submeshes

**14 `u32` per submesh.** The ones this reader uses: `primitive` (4 = triangle strip, 3 =
triangle list), `vertex buffer set` (see below), `index buffer`, `vertex_count`, `index offset`
and `index_count`.

---

## 5. Counting the mesh

* **Triangle strip** (primitive 4): a run of `n` indices yields `n − 2` windows. Windows that
  repeat a vertex are **degenerate** — they are the glue between strip pieces — and are counted
  apart, not as triangles.
* **Triangle list** (primitive 3): every 3 indices are one triangle.
* The vertex count of a submesh is its declared `vertex_count`, **not** the `count` of the vertex
  buffer it points at. `vb_index` selects a *set of attributes*, which is a list of buffers, and
  in several real models one of those buffers is a constant block with `count = 1` (48 B of
  fog/size/depth that the repacker repeats per vertex). Using the buffer count produced 4 false
  "index out of range" reports out of 26 real models; using `vertex_count`, all 26 pass.

`g1m.geometria(parse_g1m(data))` returns per submesh: topology, vertices, indices, triangles,
degenerate triangles, real triangles, the first triangles and the maximum index.

---

## 6. The reader, in the package

`pokopia/g1m.py` is standard library only and does not write:

| Function | Returns |
|---|---|
| `parse_g1m(data)` | version, declared size, first chunk offset, chunk list (with each chunk's bytes) and a list of structural problems |
| `parse_g1mg(data)` | the section table of a `GM1G`, with buffers and submeshes parsed |
| `geometria(doc)` | the mesh counts of §5 |
| `problemas(data)` | structural problems plus "submesh i references vertex v of n" |
| `clasificar(blob)` | `g1m` / `g1t` / `vacio` / `otro`, including the 12-byte wrapper |
| `diferencias(a, b)` | the byte runs that differ between two files, with the length difference reported apart |
| `parse_g1t(data)` | the texture header of §1 of [SPEC-G1T.md](SPEC-G1T.md) |

```python
from pokopia import g1m

doc = g1m.parse_g1m(open("model.g1m", "rb").read())
print(doc["version"], doc["n_chunks"], doc["problemas"])
for mesh in g1m.geometria(doc)["mallas"]:
    print(mesh["topologia"], mesh["vertices"], mesh["triangulos_reales"])
```

There is no `pkp` subcommand for models in this release: the command surface for them lives in the
measurement tree (`tools/`), which is not shipped.

---

## 7. What the round trip does (measured with an external repacker)

The reader exists to **verify without trusting the writer**. The writing was measured with
`eArmada8/gust_stuff` (GPL-3.0), an external tool that is not part of this release; the numbers
below are what that tool does, not a feature of this kit.

**A container entry (`#5904`, the largest of the three):**

| Criterion | Before | After | |
|---|---|---|---|
| Vertices | 38 | **38** | same |
| Real triangles | 32 | **32** | same |
| Triangle set and winding | — | the same 32 | same |
| Triangle order | — | **different** | changed |
| Indices | 76 | **64** | changed |
| Structure | valid | valid | same |
| Re-opens with the tool | — | yes | same |
| Back into the container | 3,120 B | 3,096 B, re-read identically | same |

The whole difference is explained by **strip re-optimisation**: the original strip had 74
triangles (32 real + 42 degenerate), the new one 62 (32 + 30). Same geometry, 12 indices fewer,
which are the 24 bytes the file shrinks. **It is harmless for the engine and it is not
byte-identical.**

**A real model from a `.fdata`:**

| | Original | Repacked |
|---|---|---|
| `.g1m` bytes | 67,076 | 103,292 (**+36,216**) |
| Vertices | 756 (597 + 159) | 756 (597 + 159) |
| Indices | 2,934 (2,319 + 615) | 2,934 (2,319 + 615) |
| Real triangles | 976 (773 + 205; 2 degenerate) | 976 (773 + 205; 2 degenerate) |
| `.vb` / `.ib` exported by the tool | 4 files, md5 `6314af60…`, `f60801f1…`, `af6f5e4b…`, `20ef789b…` | **the same 4 md5** |
| `g1m.problemas()` | 0 | 0 |

The size grows because that tool **interleaves the constant 48-byte block into every vertex**:
3 buffers become 2 and the strides go from 76/80 to 124/128. Identical geometry, different
layout.

---

## 8. What is not known, and what is not shipped

* **Not interpreted**: material and shader sections, joint palettes, sockets, mesh LOD. They are
  parsed as opaque sections and preserved as-is; their fields are not documented here.
* **No writer in this release.** Repacking needs an external tool, and the result is not
  byte-identical (§7).
* **Nothing has been put back into the game**: writing a `.fdata` is not implemented, so a
  repacked `.g1m` stops at a file in `build/`.
* **Not checked against the engine**: "the geometry is the same and the structure is valid" is
  what was measured; that the game loads it is not.
