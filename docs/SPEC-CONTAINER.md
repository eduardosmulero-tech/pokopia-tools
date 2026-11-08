# Container specification: `LD_C0_R.BIN` / `LI_C0_R.IDX`

Pokémon Pokopia — data container of update build 655360 (game version 2.0.1a).

Revision 1. Status: normative for the build named above. Every figure in this document was
obtained by directly measuring the container of that build; the method is in §13. Numbers from
any other build are unverified.

---

## 1. Scope and version

| | |
|---|---|
| Game | Pokémon Pokopia, version **2.0.1a** |
| Data set | update build **655360** (RomFS of the update) |
| Files covered | `LD_C0_R.BIN` (payloads), `LI_C0_R.IDX` (index) |
| Entries in this build | **12,298** |
| Index size | **393,536** B (= 12,298 × 32) |
| Payload file size | **247,317,504** B |
| Total payload, decompressed | **548,327,864** B |
| Byte order | little endian throughout |

**In scope:** the byte-level layout of both files, the index record format, the two entry
encodings, the block framing, the alignment and padding rules, the compressor behaviour
needed to reproduce the build's bytes exactly, and test vectors.

**Out of scope:** what any entry *means* (the container is a flat table; it assigns no names,
types or schema to its entries), the game code that consumes it, save files, asset or texture
formats, any other build or platform, and any statement about how to run the game. A reader
implemented from this document can extract and re-insert payloads; it cannot interpret them.

**Terminology of "verified":** a claim marked *(measured)* was produced by the walk described
in §13 over all 12,298 records of this build.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Container** | The pair (`LI_C0_R.IDX`, `LD_C0_R.BIN`) treated as one data set. |
| **Entry** | One logical payload, addressed by its ordinal position in the index. Entries are numbered `0 … N-1` in file order. |
| **Record** | The 32-byte index record that describes one entry. There are exactly as many records as entries. |
| **Payload** | The decompressed bytes of an entry — what a consumer of the container reads. |
| **Slot** | One contiguous byte range inside `LD_C0_R.BIN`. An entry occupies *one* slot; the blocks of a compressed entry occupy further slots *inside* that entry slot. |
| **Block** | One unit of a compressed entry: at most `blockSize` payload bytes, stored in its own slot. |
| **Raw** | (a) An entry with `flag = 0`, stored verbatim. (b) A *block* stored verbatim inside an otherwise compressed entry. Both are "raw"; the context says which. |
| **Slot size** | For an entry, `packedSize` (bytes the entry occupies in the BIN). For a block, `slotSize[b]` (bytes that block occupies). |
| **Padding** | Zero bytes with no payload meaning, inserted to satisfy an alignment rule. Two kinds: between entry slots (256-byte alignment) and between block slots (128-byte alignment). |
| **`blockSize`** | The maximum payload bytes per block of one compressed entry. Per entry, not global. |

---

## 3. Container layout

| File | Size (this build) | Role |
|---|---|---|
| `LI_C0_R.IDX` | 393,536 B | Flat array of 32-byte records, nothing else |
| `LD_C0_R.BIN` | 247,317,504 B | Concatenation of the entry slots, in index order |

**The index has no header.** Record 0 starts at byte 0 of the file; its first field is
`offset = 0`, which is also the first byte of the BIN *(measured)*. There is no magic number,
no version field, no entry count and no checksum in either file. The entry count is implicit:

```
N = size(LI_C0_R.IDX) / 32          # exact division required
```

`393,536 / 32 = 12,298` in this build, with no remainder *(measured)*.

**Relationship between the files.** The index holds only offsets and sizes; every payload
byte lives in the BIN. Consequences, all measured:

| Property | Value |
|---|---|
| Record offsets strictly ascending | No — non-decreasing; 0 records go backwards |
| Distinct offsets | 9,794 of 12,298 (116 offsets are shared by more than one record) |
| All offsets multiples of 256 | Yes, 12,298 / 12,298 |
| First slot starts at BIN byte | 0 |
| Last slot ends at BIN size | Yes: last `offset + packedSize` = 247,317,504 = file size |
| Sum of all `packedSize` | 246,615,606 B |
| Sum of all inter-slot padding | 701,898 B (= 247,317,504 − 246,615,606) |

**Can the index be used alone?** For locating: yes. For reading: no — it contains no payload
bytes whatsoever. What the index alone determines, and what it does not:

| Derivable from `LI_C0_R.IDX` alone | Not derivable |
|---|---|
| Number of entries | Any payload byte |
| File size of the BIN (last record's `offset`) | Which entries share a payload |
| Byte range of every entry | Whether the BIN on disk is the one this index describes (no checksum) |
| Payload size of every entry (`rawSize`) | Anything about entry semantics |

Because there is no checksum in either file, a mismatched pair is only detectable indirectly:
every alignment, `nBlocks` and block-walk constraint in this document must hold, and the last
slot must end exactly at end-of-file. All of those hold for the pair in this build *(measured:
0 violations of any constraint, see §13)*.

**Layout of `LD_C0_R.BIN`, in order:**

```
offset 0 ─────────────────────────────────────────────────────────────
  entry 0 slot   [offset=0, length=packedSize]
  zero padding   (0 … 255 B, to the next 256-byte boundary)
  entry 1 slot
  zero padding
  …
  entry N-1 slot → ends exactly at end of file
```

---

## 4. Index record (32 bytes)

```
 0                   8                  16                  24            32
 +-------------------+------------------+-------------------+-------------+
 | offset  : int64   | rawSize : int64  | packedSize : int64| flag : int64|
 +-------------------+------------------+-------------------+-------------+
```

| Field | Offset in record | Type | Semantics | Range in this build |
|---|---|---|---|---|
| `offset` | `0x00` | int64 LE | File offset of the entry's slot in `LD_C0_R.BIN`. Always a multiple of 256. | 0 … 247,317,504 |
| `rawSize` | `0x08` | int64 LE | Payload length after decompression, in bytes. For `flag = 1` it repeats the third `u32` of the entry header. | 0 … 48,768,688 |
| `packedSize` | `0x10` | int64 LE | Bytes the entry occupies in the BIN, from `offset`, **excluding** the padding that follows the slot. | 0 … 16,965,248 |
| `flag` | `0x18` | int64 LE | Storage encoding: `0` raw, `1` block-compressed. No other value occurs. | 0 or 1 |

All four fields are non-negative in this build, so the signed/unsigned distinction is not
observable; treat them as unsigned 64-bit and reject values above `2^63-1` if you need
portability of your error handling.

`flag` semantics:

| `flag` | Encoding | `rawSize` vs `packedSize` |
|---|---|---|
| `0` | Raw: the slot *is* the payload (§5) | `rawSize == packedSize` in 4,169 / 4,169 entries |
| `1` | Block-framed, possibly compressed (§6) | No fixed relation: in this build 1,682 entries have `packedSize > rawSize`, 5,990 have `packedSize < rawSize`, 457 have `packedSize == rawSize` |
| other | Undefined | A reader must reject the container |

**What `packedSize` guarantees** *(measured for all 12,298 records)*:

1. The entry's bytes are exactly `BIN[offset : offset + packedSize)`; nothing outside that
   range belongs to the entry.
2. For `flag = 0`, `packedSize == rawSize`.
3. For `flag = 1`, `packedSize` equals the position reached by walking the entry's blocks and
   rounding each step up to 128 bytes (§6). It therefore *includes* the 12-byte header, the
   block table, the zero padding after the table, and the zero padding after every block.
4. Entries do not overlap: `offset[i] + packedSize[i] <= offset[i+1]` for every `i` (measured:
   0 violations). The gap `offset[i+1] − (offset[i] + packedSize[i])` is **either 0 or 4–255
   bytes**: 7,794 records have a gap of 0 (the slot already ends on a 256-byte boundary) and
   4,504 have a gap of 4 to 255 bytes *(measured over 12,298 records; do not assert a minimum
   gap of 4, it rejects 7,794 valid slots)*.

**What `packedSize` does not guarantee:**

1. `packedSize != offset[i+1] - offset[i]` — false in **4,504** of 12,298 records, because of
   the 256-byte slot alignment (§8c).
2. It says nothing about compression: `flag = 1` does not imply the slot is smaller than the
   payload (1,682 counter-examples).
3. It does not make `offset` unique: 2,504 of the 2,505 `packedSize = 0` records share their
   offset with the next record; the remaining one is the last record of the table, which points
   at end-of-file (§9).
4. It carries no checksum, length of the compressed stream, or block count; all of that is
   inside the slot.

---

## 5. Entry, raw form (`flag = 0`)

```
offset ────────────────────────────────────────────
        payload bytes (rawSize bytes, verbatim)
```

| Property | Measured |
|---|---|
| Header | None — the first payload byte is at `offset` |
| `packedSize` vs `rawSize` | Equal, 4,169 / 4,169 |
| Padding *inside* the slot | None; the slot ends at `offset + rawSize` |
| Entries with a payload | 2,107 (the other 2,062 are zero-length, §9) |
| Smallest / largest payload | 4 B / 14,931,584 B (record 12,294) |
| Total raw payload | 136,286,774 B |

Padding exists only *between* slots: the next slot starts at `align256(offset + packedSize)`
and the gap is zero-filled (§8c). An entry whose payload is already 256-aligned has no gap
after it — that happens in 7,794 records; the final record of the table is one of them (it is
empty and sits at EOF, §9).

A reader must not "repair" a raw entry: if `rawSize != packedSize` with `flag = 0`, the
container is malformed.

---

## 6. Entry, compressed form (`flag = 1`)

### 6.1 Layout

```
offset + 0     ┌──────────────────────────────────────────┐
               │ u32 blockSize                            │  header
               │ u32 nBlocks                              │  12 bytes
               │ u32 rawSize                              │
offset + 12    ├──────────────────────────────────────────┤
               │ u32 slotSize[0]                          │  block table
               │ u32 slotSize[1]                          │  nBlocks × 4 bytes
               │ …                                        │
               │ u32 slotSize[nBlocks-1]                  │
               ├──────────────────────────────────────────┤
               │ zero padding to the 128-byte boundary    │
offset + p0    ├──────────────────────────────────────────┤  p0 = align128(12 + 4·nBlocks)
               │ block 0   (slotSize[0] bytes)            │
               ├──────────────────────────────────────────┤
               │ zero padding to the 128-byte boundary    │
offset + p1    ├──────────────────────────────────────────┤  p1 = align128(p0 + slotSize[0])
               │ block 1   (slotSize[1] bytes)            │
               │ …                                        │
offset + packedSize ─ last block + its padding ──────────┘
```

### 6.2 Header fields

| Field | Offset in entry | Type | Semantics |
|---|---|---|---|
| `blockSize` | `+0` | u32 LE | Maximum payload bytes per block, for **this** entry. Not a global constant. |
| `nBlocks` | `+4` | u32 LE | Number of blocks; must equal `ceil(rawSize / blockSize)`. |
| `rawSize` | `+8` | u32 LE | Payload length; must equal the record's `rawSize`. |

Measured constraints, all 7,686 compressed entries with a slot (see §9 for the one exception):

| Constraint | Result |
|---|---|
| `header.rawSize == record.rawSize` | 7,686 / 7,686 |
| `nBlocks == ceil(rawSize / blockSize)` | 7,686 / 7,686 |
| Block walk ends exactly at `packedSize` | 7,686 / 7,686 |
| `nBlocks = 0` | 1 entry (record 11,596, §9) |
| `nBlocks = 1` / `> 1` | 7,304 / 381 |

### 6.3 Block table and walk

```
table[b]  = u32 at  offset + 12 + 4*b          for b in 0 … nBlocks-1
pos       = align128(12 + 4*nBlocks)           # offset of block 0 relative to the entry
pos[b+1]  = align128(pos[b] + table[b])
            and the walk must end with  pos[nBlocks] == packedSize
```

`align128(x) = (x + 127) & ~127`.

The 128 constant is measured, not assumed: walking all 7,686 entries with a block alignment
of 32, 64, 128, 256, 512 or 1,024 leaves exactly one value that makes every walk land on
`packedSize` — 128 (0 mismatches); every other value mismatches in 7,686 of 7,686 entries
*(measured)*.

The zero padding after the table (between `12 + 4·nBlocks` and `pos[0]`) and after every block
is zero in every entry; no non-zero byte was found in any inter-block or post-table gap
*(measured: 0 entries)*.

### 6.4 `blockSize` values in this build

| `blockSize` | Entries | Blocks | Smallest payload | Largest payload |
|---|---|---|---|---|
| `0x10000` (65,536) | 7,624 | 8,189 | 0 B (record 11,596) | 3,330,848 B (record 5,950) |
| `0x20000` (131,072) | 5 | 33 | 69,760 B | 1,863,044 B |
| `0x80000` (524,288) | 57 | 631 | 568 B (17 records: 5,918, 5,919, 5,926–5,933, 5,935, 5,936, 5,939–5,942, 5,944) | 48,768,688 B (record 5,882) |

`blockSize` cannot be derived from `rawSize`: a 568-byte payload can carry `0x80000`
(record 5,918 stores one 53-byte slot) and a 3.3 MB payload can carry `0x10000` (record 5,950,
51 blocks). It is build metadata; a writer must preserve it per entry (§8a).

`blockSize` may exceed `rawSize`; then `nBlocks = 1` and the single block holds the whole
payload.

---

## 7. Slot contents, and how a reader tells the two kinds apart

### 7.1 Contents

| Slot kind | Contents | Size relation |
|---|---|---|
| Compressed block | `[u32 len][zlib stream]` — `len` is the length of the zlib stream that follows | `slotSize == len + 4` |
| Raw block | The block's payload bytes, verbatim, **no length prefix** | `slotSize == length of the block` |

The block's expected payload length is `min(blockSize, rawSize - b*blockSize)`; call it `want`.

Measured over all 8,853 blocks of all compressed entries:

| | Count |
|---|---|
| Blocks total | 8,853 |
| Blocks whose slot matches the compressed form (`slotSize == len+4` and the stream inflates to exactly `want` and reaches end-of-stream) | 8,834 |
| Blocks whose slot matches the raw form (`slotSize == want`) | 19 |
| Blocks matching **both** forms | **0** |
| Blocks matching **neither** | **0** |
| Compressed slots whose `slotSize` also equals `want` (i.e. a potential raw-reading) | **0** |
| Raw slots that begin with a valid-looking length prefix | **0** |
| Raw slots with `0x78` at byte 4 (a plausible zlib start) | **0** |

The 19 raw blocks are all short tails where compression does not pay: 16 slots of 18 B, 2 of
16 B, 1 of 14 B. Eighteen of them are the only block of their entry (e.g. record 10,022,
payload 18 B, `slotSize = 18`); one is the last block of a two-block entry (record 10,220,
block 1, `slotSize = 14`).

### 7.2 Deterministic rule

For each block, in this order:

```
want  = min(blockSize, rawSize - b*blockSize)
chunk = BIN[offset + pos : offset + pos + slotSize]

if slotSize >= 4 and u32(chunk, 0) == slotSize - 4
   and inflate(chunk[4:]) succeeds, consumes the whole stream (end of stream reached)
   and yields exactly `want` bytes:
        block = inflate(chunk[4:])            # compressed
elif slotSize == want:
        block = chunk                         # raw
else:
        malformed container
```

Three properties make the rule unambiguous rather than merely heuristic:

1. **The length must agree with the slot size.** `len` is redundant with `slotSize` for a
   compressed block, which is exactly what makes the test decisive: no raw block in this build
   satisfies `slotSize == len+4`.
2. **The decompressed size must be exactly `want` and the stream must end.** A coincidental
   4-byte prefix that happens to inflate is rejected unless it produces the right length.
3. **Order does not matter.** No block satisfies both branches (0 / 8,853), so trying the raw
   form first gives the same result.

Applying the rule to all 12,298 records of this build yields 8,853 decoded blocks, 12,298
payloads, and 548,327,864 payload bytes with no undecidable block and no other error
*(measured; the independent re-implementation of §13 agrees entry for entry)*.

---

## 8. The four traps

Each of these breaks a reader that has the "obvious" model of the format.

### (a) `blockSize` is per entry, not a constant

Measured: `0x10000` in 7,624 entries, `0x20000` in 5, and **`0x80000` in 57**. The 62 entries
that are not `0x10000` carry 664 blocks; assuming `0x10000` for them implies 4,849 blocks
instead (7.3×).

| Example | `rawSize` | `blockSize` | `nBlocks` |
|---|---|---|---|
| Record 5,918 | 568 | `0x80000` | 1 |
| Record 7,098 | 69,760 | `0x20000` | 1 |
| Record 5,950 | 3,330,848 | `0x10000` | 51 |
| Record 5,882 | 48,768,688 | `0x80000` | 94 |

**If ignored:** a reader that hard-codes `0x10000` and always assumes `slotSize == len + 4`
fails on **81 records** with **122 failed checks**: 62 records whose `blockSize` is not
`0x10000`, 41 of which also get the wrong `nBlocks` from the hard-coded size (103 checks over
those 62 records), plus 19 records holding a block stored raw, which an unconditional
`[u32 len][zlib]` parse cannot decode (19 checks over 19 further records; the two sets are
disjoint). The *first* failure is record **5,879** (`rawSize` 34,480,304, `blockSize` 0x80000,
66 blocks), where the naive block count would be 527. Everything before record 5,879 decodes,
which is what makes the bug easy to miss.

### (b) `slotSize` is not `len + 4`

Measured: 19 of the 8,853 blocks have no length prefix at all — the slot *is* the block.

| Example | Block | `slotSize` | Payload bytes |
|---|---|---|---|
| Record 10,022 | 0 | 18 | 18 |
| Record 10,764 | 0 | 16 | 16 |
| Record 10,220 | 1 | 14 | 14 |

**If ignored:** a reader that reads `[u32 len][zlib]` unconditionally throws a zlib error on
these 19 blocks (`incomplete or truncated stream` is the usual symptom, because it starts
inflating one byte too late) or, worse, invents a block length and walks off the entry; the
walk then fails to land on `packedSize`. Two of the three examples above are single-block
entries of 16–18 payload bytes, so the failure is confined to 19 tiny blocks — exactly the kind
of defect that survives casual testing and corrupts a container silently.

### (c) Entry slots are aligned to 256, and the padding is zero

Measured: every `offset` is a multiple of **256** (12,298 / 12,298). The rule is
`offset[i+1] = align256(offset[i] + packedSize[i])`. Alignment trials over all records:

| Alignment tried | Records violating `offset[i+1] == align(offset[i]+packedSize[i])` |
|---|---|
| 64 | 4,382 |
| 128 | 3,812 |
| **256** | **0** |
| 512 | 7,196 |
| 1,024 | 9,704 |

Consequence: in **4,504** records `packedSize != offset[i+1] - offset[i]`; the other **7,794**
already end on a 256-byte boundary and have a gap of exactly 0. The 4,504 non-zero gaps run from
**4 to 255 bytes** (87 distinct sizes), total 701,898 B, and every one of them is zero-filled
(0 non-zero gaps).

| Example | `offset` | `packedSize` | Next `offset` | Gap |
|---|---|---|---|---|
| Record 12,294 | 232,372,992 | 14,931,584 | 247,304,704 | 128 |
| Record 40 | 44,032 | 31,360 | 75,520 | 128 |
| Record 42 | 86,784 | 512 | 87,296 | 0 |

**If ignored:** a reader that computes entry length as `nextOffset - offset` gets 4,504 entries
wrong — it hands the trailing zeros to the block walk (which then fails to end on
`packedSize`) or to the payload. A writer that aligns to 128 produces a container that a
correct reader rejects at the first 128-but-not-256 offset.

### (d) There are three empty-entry encodings

Measured: 2,062 + 443 + 1 entries have `rawSize = 0`, in three different shapes (§9). The
third — one record, #11,596 — is a complete 128-byte header with `nBlocks = 0` and no blocks.

**If ignored:** a reader that decides "empty" by `packedSize == 0` alone mishandles record
11,596: it sees `flag = 1`, `packedSize = 128` and tries to decode a block table that does not
exist (`nBlocks = 0` means the table is empty and the walk ends after the header padding, which
is exactly the 128 bytes). A writer that emits zero bytes for it produces a container that is
valid by every other rule but not byte-identical to the build.

---

## 9. Empty entries

`rawSize = 0` occurs in 2,506 records, in three encodings:

| # | Form | Count | `flag` | `packedSize` | Bytes in the BIN |
|---|---|---|---|---|---|
| 1 | No slot at all | 2,062 | 0 | 0 | none |
| 2 | No slot at all | 443 | 1 | 0 | none |
| 3 | Header with `nBlocks = 0` | 1 (record 11,596) | 1 | 128 | 12-byte header + 116 zero bytes |

Details, all measured:

- **Forms 1 and 2 occupy zero bytes.** `offset` equals the *next* record's `offset` in **2,061
  of the 2,062** form-1 cases and **443 of 443** form-2 cases. The single exception is the last
  record of the table (index **12,297**): it is form 1 and its `offset` is **247,317,504** = end
  of `LD_C0_R.BIN`, so it has no next record to compare with — a zero-length terminator at EOF.
  Record 12,296 immediately before it is also form 1 at the same offset 247,317,504; the last
  record that carries bytes (12,295, 12,552 B) ends at 247,317,256 and is followed by 248 bytes
  of alignment padding up to EOF. Nothing in the BIN belongs to forms 1 and 2, and the two forms
  are distinguishable only by `flag`, which carries no payload meaning here.
- **Form 3** (record 11,596, `offset` 111,944,192): header `blockSize = 0x10000`,
  `nBlocks = 0`, `rawSize = 0`; the remaining 116 bytes of the 128-byte slot are zero. The
  entry's walk is empty and ends at 128 = `packedSize`.
- 116 offsets in the file are shared by more than one record; 115 records that do carry a payload
  share their offset with one or more zero-length records (a run of zero-length records pointing
  at the next payload).

**Unambiguous detection**, in this order:

```
if rawSize == 0:
    payload = empty                                 # all three forms, no special case
elif packedSize == 0:
    malformed container                             # rawSize > 0 without stored bytes
```

The `packedSize == 0` case must never be turned into "read `rawSize` bytes at `offset`": for
the 2,505 zero-length records that region belongs to the following entry and reading it would
silently duplicate another payload. Distinguishing form 3 from forms 1–2 is only needed by a
*writer* that wants byte identity; a reader can ignore it.

---

## 10. Compressor dependency (normative note)

Every compressed block in this build is a **zlib** stream (RFC 1950) with the two-byte header
`78 da` in 8,834 / 8,834 blocks: CMF `0x78` = deflate, 32 KB window; FLG `0xda` = FLEVEL 3
(maximum level), FCHECK valid in all 8,834 *(measured)*.

The stream is produced by **stock zlib at level 9**. Reproducing the build's bytes requires the
same implementation, not merely the same parameters. All rows below compress the same 65,536-byte
block (record 40, block 0), whose stored stream is 8,362 bytes:

| Compressor | Bytes | Δ vs stored | Header | Byte-identical |
|---|---|---|---|---|
| stored in the container | 8,362 | — | `78da` | — |
| stock zlib 1.3.2, level 9 (`compress2`) | 8,362 | 0 | `78da` | **yes** |
| zlib-ng 1.3.1, level 9 | 8,331 | −31 | `78da` | no |
| zlib-ng 1.3.1, level 9, `Z_FILTERED` | 8,271 | −91 | `78da` | no |
| zlib-ng 1.3.1, level 6 | 8,554 | +192 | `789c` | no |
| zlib-ng 1.3.1, level 1 | 14,731 | +6,369 | `7801` | no |

Over a sample of 200 blocks spread across the container: stock zlib level 9 reproduced
**200 / 200** streams byte for byte; zlib-ng level 9 reproduced **82 / 200**, and its total came
out 6,637 bytes smaller than the stored streams *(measured)*.

Consequences, measured on the whole container:

| Compressor used to re-pack | Entries byte-identical | Entries differing | BIN size |
|---|---|---|---|
| stock zlib 1.3.2, level 9 | **12,298 / 12,298** | 0 | 247,317,504 (identical) |
| zlib-ng 1.3.1, level 9 | 8,243 / 12,298 | 4,055 | 247,127,040 (−190,464) |

The 8,243 identical entries are the 4,169 raw entries (bytes copied verbatim) plus 4,074 of the
8,129 `flag = 1` entries — the 444 zero-length ones, which have no stream to recompress, and
those whose recompressed streams happen to match. The 4,055 differences are all `flag = 1`.

**Normative statements:**

1. To reproduce the build byte for byte, compress with stock zlib (the reference implementation;
   measured here with 1.3.2) at level 9, default window/strategy/memLevel.
2. zlib-ng and other zlib-compatible implementations produce **valid** containers — every
   reader following §6–§7 accepts them — but **not identical** ones. Validity and identity are
   different claims; test them separately.
3. The stream header cannot tell you which implementation produced it: zlib-ng level 9 also
   emits `78da`. Only a byte comparison against the stored stream can.
4. Nothing in the container records the compressor, its version or its level.

---

## 11. Test vectors

Six records covering every shape that exists in the build: a large raw entry, a single-block
compressed entry, a multi-block entry, the header-only empty entry, an entry with
`blockSize = 0x80000`, and an entry whose last block is stored raw.

| # | `index` | `offset` | `rawSize` | `packedSize` | `flag` | `blockSize` | `nBlocks` | `slotSize[]` | `sha256(payload)` | `sha256(stored slot)` |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 12,294 | 232,372,992 | 14,931,584 | 14,931,584 | 0 | — | — | — | `9ef5565a45d35d406590ebe1364348d829dd906c7a324515bdb8ae884bedfeb3` | `9ef5565a45d35d406590ebe1364348d829dd906c7a324515bdb8ae884bedfeb3` |
| B | 42 | 86,784 | 1,088 | 512 | 1 | `0x10000` | 1 | `[364]` | `f45654d2c4b2063a62b52d3aeb1fc4cbe297a7103a9761a99d23d4abe9b09525` | `a0782f58a6da532af073173b278cfd4e63fb6962f03e453250bfa24c970c715e` |
| C | 40 | 44,032 | 327,744 | 31,360 | 1 | `0x10000` | 6 | `[8366, 4156, 4944, 8186, 5135, 30]` | `84d16993a3d6bd8506971aee5e069188f5acefa75619f655e8f02c2c3f60370d` | `378a1cab5e7216b5f7dc3376ef1f830bf0ba3b762416a0bb3899580810ba0953` |
| D | 11,596 | 111,944,192 | 0 | 128 | 1 | `0x10000` | 0 | `[]` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty) | `cb1b09a2f5bf589949341a07542d08c82160e0c07314df2165ac9060fb651fb2` |
| E | 5,918 | 98,521,088 | 568 | 256 | 1 | `0x80000` | 1 | `[53]` | `0fbf20d96641280ac7a6ba3061e46f67bd6a69c94333c2cabe95aaf179889fe6` | `4a2331a6b3329fbb5b41e745d9b823ef57af11a32e6fbf4464674f05a1c96068` |
| F | 10,220 | 109,422,848 | 65,550 | 11,264 | 1 | `0x10000` | 2 | `[10907, 14]` | `f8aaf7af8665112a39058b8e8991bac8f35d4534a39a39ba2a220791ca229e8b` | `eb54ccdac0f35ef1fb4d78a2798f681274bc7e84808ea5e448e7f9d8284b1718` |

Block-level detail for the compressed vectors:

| # | First block at (entry-relative) | Blocks | Comments |
|---|---|---|---|
| B | 128 | 1 compressed | `slotSize = 364` = 4 + 360, payload 1,088 B |
| C | 128 | 6 compressed | slots 8,366 / 4,156 / 4,944 / 8,186 / 5,135 / 30; walk ends at 31,360 |
| D | 128 | none | `nBlocks = 0`; walk ends at 128 = `packedSize` |
| E | 128 | 1 compressed | 53-byte slot for 568 payload bytes; `blockSize` (524,288) is far larger than the payload |
| F | 128 | compressed + **raw** | block 0 `slotSize` 10,907 (compressed), block 1 `slotSize` 14 = payload 14 B, no prefix |

How to use them: a reader is correct on these six if (1) it reads the six records from the
index, (2) it produces payloads with the `sha256(payload)` values above, and (3) it reports
the `blockSize` / `nBlocks` / `slotSize` values above. `sha256(stored slot)` covers the raw
bytes of `BIN[offset : offset + packedSize)` and lets you check the block parsing independently
of the payload hashing.

---

## 12. Known limits and open questions

| # | Open question | What we know | Impact |
|---|---|---|---|
| 1 | What rule the build uses to choose `blockSize` per entry | Three values occur; it does not follow from `rawSize` (568 B with `0x80000`, 3.3 MB with `0x10000`). Preserve it per entry, never predict it. | A writer that guesses will not reproduce the build. |
| 2 | Exact tie-break of the build's raw-slot rule | The rule "store the block raw when `len(comp) + 4 >= len(block)`" reproduces all 19 raw blocks. No compressed block in this build has `slotSize` equal to its payload length *(measured: 0 of 8,834)*, so an exact tie never occurs and its tie-break is unmeasured. | Writers may differ from the build on an exact tie; readers are unaffected (§7). |
| 3 | Whether the 256-byte slot alignment is a requirement of the game or an artefact of the build | All 12,298 offsets are 256-aligned and all padding is zero. We have not tested a container with different alignment inside the game. | Use 256. |
| 4 | Whether `packedSize` may include trailing padding in another build | In this build it never does: the 701,898 padding bytes all lie outside `packedSize`. | A reader that trusts the measured rule is correct here; another build must be re-measured. |
| 5 | What the 443 zero-length `flag = 1` entries mean | They occupy zero bytes and point at the next entry's offset; byte-exact repacking reproduces them, but nothing in the file distinguishes them from the 2,062 zero-length `flag = 0` entries except the flag. | Readers: ignore. Writers: preserve the flag to stay identical. |
| 6 | Why one empty entry uses the header form (record 11,596) and 2,505 do not | Reproducible from the record alone (`flag = 1` and `packedSize = 128`); the reason is build-internal. | Writers must copy the form, not invent it. |
| 7 | Whether entries above `size/32` records, or a truncated IDX, are tolerated by the game | Untested. The format has no count field, so only the file size delimits the table. | Validate `size % 32 == 0` and the last offset before trusting a pair. |
| 8 | Semantics of the entries | None established. The container is a flat table; this document assigns no meaning to any index. | Out of scope (§1). |
| 9 | Coverage | One build, one revision, one platform. Earlier versions, later updates and the base game were not measured. | Re-measure before applying these constants elsewhere. |

### 12.1 Figures corrected since our earlier notes

Some numbers circulated in our internal packer report and in the issue text filed on the PokoHex
tracker before this document was measured end to end. The table records what changed, so that a
reader comparing sources does not have to reconcile them. Everywhere else in this document the
measured value is the one used.

| Earlier figure | Stated in | Measured for this document | Comment |
|---|---|---|---|
| 1,848 failed checks when `blockSize` is hard-coded to `0x10000` | internal packer report | **122** failed checks over **81** records, first failing record 5,879 | Does not reproduce. The probe that produced it aborts on a zlib error instead of counting to the end; recounting gives 122/81 with the same first failure (§8a). |
| "62 entries stop parsing" | issue text, PokoHex tracker | 62 entries fail on `blockSize` alone; **81** fail for a reader that also assumes `slotSize == len + 4` (§8b) | Both correct under their own assumption; this document gives both. |
| zlib-ng 1.3.1 level 1 over the 8,362-byte sample: 14,732 B, +6,370 | internal report, compressor table | **14,731 B, +6,369** | Off by one byte; the other four rows of that table reproduce exactly (§10). |
| 488 entries identical under zlib-ng 1.3.1 level 9 | internal report | 8,243 entries with byte-identical slots, of which **488** also keep their original `offset` | Not a contradiction: two metrics. Slots that survive recompression move when an earlier slot changes size; 488 is the stricter count (§10). |
| 2,505 empty entries | `verify` output | **2,506** with `rawSize = 0` (2,062 + 443 + 1); 2,505 is the count with `packedSize = 0` | The odd one out is record 11,596, the 128-byte header-only entry (§9). |

---

## 13. How we verified

Two independent implementations were written from the rules above and run over the whole
container; neither one shares code or data structures with the other.

**1. Full structural walk.** All 12,298 records, all 8,853 blocks, all payloads. Verbatim output
of the reference checker (its labels are Spanish; gloss below the block):

```
$ python pkp_pack.py verify <LI_C0_R.IDX> <LD_C0_R.BIN>
verify <LI_C0_R.IDX>
  entradas          : 12298
  tamano BIN        : 247317504
  flags             : {1: 8129, 0: 4169}
  entradas vacias   : 2505
  suma rawSize      : 548327864
  suma packedSize   : 246615606
  bloques comprimidos: 8834
  bloques crudos    : 19
  blockSizes usados : {'0x10000': 8189, '0x20000': 33, '0x80000': 631}
  problemas         : 0
```

*Only the path on the second line is replaced by a placeholder. Labels: `entradas` = records,
`tamano BIN` = BIN size, `flags` = histogram of `flag`, `entradas vacias` = records with
`packedSize = 0` (2,505 — not the 2,506 with `rawSize = 0`, see §12.1), `suma` = sum,
`bloques` = blocks, `problemas` = problems found.*

The checker asserts: IDX size is a multiple of 32; every offset is 256-aligned and
non-decreasing; every entry lies inside the BIN; `flag = 0` implies `rawSize == packedSize`;
header `rawSize` and `nBlocks` are coherent; the block walk ends exactly at `packedSize`;
every byte of inter-entry and inter-block padding is zero; the final record's
`offset + packedSize` equals the BIN size.
Result: **0 problems**.

**2. Payload hashes from a second reader** (different language structure, memory-mapped,
shares no code with the first):

```
$ python tests/independent_reader.py <LI_C0_R.IDX> <LD_C0_R.BIN>
{
 "fichero": "LD_C0_R.BIN",
 "entradas": 12298,
 "bytes": 548327864,
 "sha256_global": "1bd1f1fee2bdb116238ea3cc3147f712c423e3b21428746bead580a2e6f41551"
}
```

12,298 / 12,298 payloads hashed. Neither hash below is a checksum of the container files: both
cover the **decoded payloads**, in index order, so any correct reader can reproduce them.

| Hash | Input | Value |
|---|---|---|
| Record stream (`sha256_global` above) | the reader's text stream, one line per entry: `"<index>:<length>:<sha256 of payload>\n"` | `1bd1f1fee2bdb116238ea3cc3147f712c423e3b21428746bead580a2e6f41551` |
| Concatenation | the raw bytes of all 12,298 payloads concatenated in index order, no separators | `08a98bd557df2b2bbb195782cfedf34a2f1792b8d8cbacbeeea1944752ff9f05` |

`sha256_global` is the record-stream hash, **not** the hash of the concatenated payloads; a third
party hashing the concatenation must expect the second value. Both were recomputed for this
document over the whole container.

**3. Container rebuilt from scratch and compared byte for byte** (stock zlib level 9, rules of
§5–§7; a fresh run for this document, not a reused artefact):

```
$ python pkp_pack.py roundtrip <LI_C0_R.IDX> <LD_C0_R.BIN> --tag spec_rt3 --out-dir <dir>
compresor: stock (zlib 1.3.2) <path to zlib1.dll>
  ... 4000/12298 (3.2 s)
  ... 8000/12298 (36.6 s)
  ... 12000/12298 (39.9 s)
rebuild: 12298 entradas -> <dir>/spec_rt3.IDX + <dir>/spec_rt3.BIN (40.2 s)
roundtrip: 12298 entradas
  C1 identicas=12298 distintas=0
  entradas identicas byte a byte en el BIN: 12298/12298
  IDX identico: True (0 bytes distintos)
  BIN identico: True (0 bytes distintos, 247317504 vs 247317504)
  tiempo: 49.7 s
informe: <dir>/spec_rt3.json

$ md5sum <rebuilt BIN> <original BIN> <rebuilt IDX> <original IDX>
358a672d506ce2b0399149ede64a6760  <rebuilt BIN>
358a672d506ce2b0399149ede64a6760  <original BIN>
7e056a097f28a62f002ad961a611edf8  <rebuilt IDX>
7e056a097f28a62f002ad961a611edf8  <original IDX>
$ cmp <rebuilt BIN> <original BIN> && cmp <rebuilt IDX> <original IDX> && echo "cmp: identical"
cmp: identical
```

*Verbatim, except that file paths are replaced by `<dir>` and placeholders; `C1` = payload identity
per record (`identicas` identical, `distintas` different).*

0 bytes differ in 247,317,504 + 393,536 bytes. This is what fixes the compressor requirement of
§10: the same reader/writer with zlib-ng produces a valid container that differs in 4,055
entries and 190,464 bytes.

**4. Round trip per entry.** Unpack → repack → compare: 12,298 / 12,298 payloads identical,
0 differing, and the same 12,298 entry slots identical in the rebuilt BIN.

**5. Naive-reader counters** (used as the figures in §8a and §8b): a reader that hard-codes
`blockSize = 0x10000` and always assumes `slotSize == len + 4` fails on 81 records with 122
failed checks (62 + 41 + 19, breakdown in §8a), first failure at record 5,879. This is the
measurement that makes §8a and §8b non-optional rather than stylistic.

**6. Source container untouched.** MD5 and mtimes of both files identical before and after all
of the above; every artefact was written outside the game's directory tree.

**Timings** (reference hardware, local disk, Python, this build): full structural walk 1.2 s;
independent reader 1.7 s; container rebuild with stock zlib 40.2 s; the whole round trip
including the comparisons 49.7 s (earlier runs of the same code: 50.2 s and 50.3 s — wall-clock
figures vary by a few tenths of a second).
