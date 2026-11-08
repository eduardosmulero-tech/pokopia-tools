# Glossary of parameters

Every term and every field this kit accepts or produces, in one place. Use it as the reference
when reading a `mod.json`, a CLI transcript or a specification section.

**Conventions**

* Offsets are **bytes**, decimal unless prefixed `0x`. Offsets inside a table row are written
  `+34`; offsets inside the container file are written as plain numbers.
* Little endian throughout. `u16`/`u32`/`i64`… follow `struct` notation (`<H`, `<I`, `<q`).
* A **row** is addressed by its index inside a table; a **table** is addressed by its index in
  the container index (`#983`). Indices are not stable across game versions; the md5 of the
  container is what pins a version.

---

## 0 · Confidence words

The repository uses two vocabularies that mean the same thing at different depths. This is
deliberate, and it is the single most useful thing to read before trusting a figure.

| Word | Used in | Means | What falsifies it |
|---|---|---|---|
| `measured` | save regions, specs | Produced by walking the real data of the named build, over the whole set, and reproducible with a command in this repository. | One record that violates it. |
| `verified` | tables registry, `mod.json` | Measured **and** cross-checked with a second source (a screen reading, a second reader, a spec section). | A second source that disagrees. |
| `inference` / `inferred` | tables registry, save regions | The **geometry** is measured (sizes, counts, stride fit) but the **meaning** of the field is not demonstrated. Real data, unknown semantics. | An experiment that shows the assumed meaning is wrong. |
| `guess` | `mod.json` only | The mod author believes this offset is the field named in `why`, with no evidence. Allowed, always warned about. | Anything. |

A `guess` is a warning, never an error: the format's job is to make the guess **declared**, not
to forbid it.

---

## 1 · Container

| Term | Meaning |
|---|---|
| **Container** | The pair `LD_C0_R.BIN` + `LI_C0_R.IDX`, treated as one data set. |
| **Entry** | One logical payload, addressed by its ordinal position in the index, `0 … N-1` in file order. |
| **Record** | The 32-byte index record describing one entry. Exactly as many records as entries. |
| **Payload** | The decompressed bytes of an entry — what a consumer reads. |
| **Slot** | A contiguous byte range in the BIN. An entry occupies one slot. |
| **Block** | One unit of a *compressed* entry: at most `blockSize` payload bytes, stored in its own slot inside the entry. |
| **Raw** | (a) An entry with `flag = 0`, stored verbatim. (b) A block stored verbatim inside an otherwise compressed entry. |
| **Padding** | Zero bytes with no payload meaning, inserted to satisfy an alignment rule. |
| **Empty entry** | `packedSize = 0`. 2,505 of 12,298 in the supported build. Distinct from 2,506 entries with `rawSize = 0` (one 128-byte header-only entry). |

### 1.1 Index record — 32 bytes

| Field | Offset | Type | Meaning |
|---|---|---|---|
| `offset` | `+0` | `i64` LE | File offset of the entry's slot in the BIN. Always a multiple of **256**. |
| `rawSize` | `+8` | `i64` LE | Payload length after decompression. |
| `packedSize` | `+16` | `i64` LE | Bytes the entry occupies in the BIN, **excluding** the padding that follows it. |
| `flag` | `+24` | `i64` LE | `0` raw, `1` block-compressed. No other value occurs. |

`N = size(IDX) / 32`, exact division required. There is no header, no magic, no count and no
checksum in either file.

### 1.2 Constraints a valid pair satisfies

Every one of these holds in the supported build (12,298 records, 0 violations):

* `offset` non-decreasing, each a multiple of 256, first one `0`;
* last `offset + packedSize` = BIN size;
* `flag = 0` ⇒ `rawSize == packedSize`;
* for `flag = 1`: `header.rawSize == record.rawSize` and `nBlocks == ceil(rawSize / blockSize)`;
* block walk ends exactly at `packedSize` (see 1.3);
* all inter-slot and inter-block padding is zero.

### 1.3 Compressed entry (`flag = 1`)

```
+0    u32 blockSize      maximum payload bytes per block, for THIS entry
+4    u32 nBlocks        must equal ceil(rawSize / blockSize)
+8    u32 rawSize        must equal the record's rawSize
+12   u32 slotSize[nBlocks]
      zero padding to align128(12 + 4*nBlocks)
      block 0 … block n-1, each followed by zero padding to the next 128-byte boundary
```

`align128(x) = (x + 127) & ~127`. **128 is measured, not assumed**: walking all 7,686 compressed
entries with 32, 64, 128, 256, 512 or 1,024 as the alignment leaves exactly one value that makes
every walk land on `packedSize` (0 mismatches); every other value mismatches in all 7,686.

| `blockSize` | Entries in this build |
|---|---|
| `0x10000` (65,536) | 7,624 |
| `0x20000` (131,072) | 5 |
| `0x80000` (524,288) | 57 |

`blockSize` **cannot be derived from `rawSize`**: a 568-byte payload can carry `0x80000`, and a
3.3 MB payload can carry `0x10000`. It is build metadata, and a writer preserves it per entry.

### 1.4 Slot contents

| Slot kind | Contents | Size relation |
|---|---|---|
| Compressed block | `[u32 len][zlib stream]`, `len` = length of the stream | `slotSize == len + 4` |
| Raw block | the payload bytes verbatim, **no prefix** | `slotSize == want` |

`want = min(blockSize, rawSize - b*blockSize)`. Decoding rule, in this order: treat the slot as
compressed if `u32(chunk, 0) == slotSize - 4` **and** it inflates to exactly `want` **and** the
stream ends; otherwise treat it as raw if `slotSize == want`; otherwise the container is
malformed. Over all 8,853 blocks: 8,834 match the compressed form, 19 the raw form, **0 match
both** — the rule is decisive, not heuristic.

---

## 2 · Table geometry

The kit knows the geometry of a few tables by index. That knowledge is **data**, in
`pokopia/tables/registry.py`; no table's *content* is in this repository.

| Parameter | Meaning |
|---|---|
| `index` | The table's entry index in the container (`#983`). |
| `kind` | `records` (fixed-size rows) or `text` (rows of ids + a NUL-separated pool). |
| `header` | Bytes before the first row. 64 in every table measured so far. |
| `stride` | Bytes per row. |
| `count` | Number of rows. |
| `count_field` | Offset in the header holding `count` (default `+0`). A mismatch with the declared `count` is a hard error, not a warning. |
| `version_field` | Offset in the header holding `version` (default `+4`). |
| `version` | Expected value of that field, where it is declared. |
| `pool_start` | For `kind = text`: byte where the NUL-separated text pool begins. |
| `language` | For `kind = text`: language tag of that table. |
| `confidence` | `verified` or `inference`, per group 0. |
| `fields` | Declared fields: `offset`, `type`, `name`, `note`, `confidence`. Undeclared bytes are reported as such. |

Derived values:

```
row_offset(row)  = header + row * stride
records_end      = header + count * stride
```

Tables with declared geometry in the supported build:

| Table | Geometry | Confidence | What is actually known |
|---|---|---|---|
| `#40` | 64 + 4096 × 80 B | inference | geometry only |
| `#41` | 64 + 4096 × 16 B | inference | geometry only |
| `#42` | 64 + 256 × 4 B | inference | geometry only; the header says 255, not 256 |
| `#44` | 64 + 4096 × 100 B | inference | geometry only |
| `#983` | 64 + 4600 × 68 B | inference | geometry; **one** field demonstrated: `+34 u16 nameIndex` |
| `#4636`–`#4644` | 64 + 3001 × 32 B, pool at 96,096 | verified | descriptions |
| `#4645`–`#4653` | 64 + 3001 × 32 B, pool at 96,102 | verified | names |

A table **without** declared geometry can still be edited: `pkp table <n>` hexdumps it, and
`mod.json` accepts it, emitting the `mod.unknown_table` warning.

---

## 3 · Text parameters

| Parameter | Meaning |
|---|---|
| `id` | Catalogue id of a text. Valid range `4 … count+3` (here `4 … 3004`, `count = 3001`). |
| `slot` | `0`–`5`. Offset inside the 6-slot block of one id. `0` = singular, `2` = plural. |
| `ordinal` | Absolute position in the pool: `6 * (id - 4) + slot`. The game addresses by **ordinal**, not by offset. |
| Terminator | `\x00`. Slots are NUL-delimited; the last slot may lack a terminator and that is preserved. |
| `pool prefix` | The record area (`64 + 32*count` bytes) must stay byte-identical across a text edit. Reported as `prefijo de texto identico` in the apply transcript. |
| Reserialisation | Slots are rewritten **in the same order and the same number**. A longer text shifts later bytes but renames nobody, because addressing is ordinal. |
| `nameIndex` | `u16` at `+34` of a `#983` row. The text id is `nameIndex + 3`; the field stores `id - 3`. |

Consequence, and the reason `expect` is mandatory for text too: a text edit changes the payload
**size**, so the index is recalculated and later entries change `offset` — their bytes are copied
untouched, but their position in the file moves.

---

## 4 · `mod.json` — root fields

The full contract — why each rule exists, the merge table, the `apply` guarantees and the four
worked examples — is **[MOD-FORMAT.md](MOD-FORMAT.md)**. This section is the field reference it
relies on.

| Key | Type | Required | Semantics | Checked |
|---|---|---|---|---|
| `mod_format` | integer | **yes** | Format version. Only `1` today. | error if missing/other |
| `name` | string | **yes** | `^[a-z0-9][a-z0-9._-]{0,63}$`. Becomes a folder name and a CLI argument. | error |
| `version` | string | **yes** | `x.y.z` semver (`0.1.0`, `1.2.3-rc1`). | error if missing; warning if it does not look like `x.y.z` |
| `authors` | list of strings | **yes** | May be empty. | error if missing; warning if empty |
| `description` | string | no | Free text. Must not contain game content if the mod is shared. | — |
| `game.title` | string | **yes** | Internal title id of the game. | error |
| `game.version` | string | **yes** | Game version the mod was written for (`2.0.1a`). | error |
| `game.container_md5` | object | **yes** | md5 of **both** files. Without it nothing is applied. | error if it differs from the real files |
| `requires` | list | no | Dependencies as strings or objects. Preserved; **not resolved** in 0.1.0. | shape only |
| `edits` | list | no* | Byte writes (§4.1). | see §4.1 |
| `text` | list | no* | Text writes (§4.2). | see §4.2 |
| `files` | list | no | `{"path", "sha256"}`. **Not installed** in 0.1.0; shape checked only. | shape only |

\* A mod with neither `edits` nor `text` is valid and does nothing (`mod.empty` warning).
Unknown root keys produce a **warning**, not an error, so old readers tolerate new fields.

### 4.1 `edits[]` — byte writes

| Key | Type | Required | Semantics |
|---|---|---|---|
| `table` | integer ≥ 0 | **yes** | Entry index in the container. |
| `row` | integer ≥ 0 | **yes** | Row index inside the table. |
| `offset` | integer ≥ 0 | **yes** | Byte offset relative to the start of the row. |
| `type` | string | **yes** | `u8 i8 u16 i16 u32 i32 u64 i64 f32 f64 bytes`. |
| `expect` | number or string | **yes** | What is there **now**. If it differs, the mod does not apply. |
| `value` | number or string | **yes** | What gets written. Must fit `type`. |
| `why` | string | **yes** | Which field you believe you are touching. Cannot be empty. |
| `confidence` | `verified`\|`inference`\|`guess` | no (`verified`) | `guess` warns on every validation. |
| `note` | string | no | Free comment. |

Numbers are decimal (`2279`) or hex (`"0x8e7"`); negative values allowed in `i*` types; `bytes`
is written in hex (`"0012ab"`, `"00 12 ab"`) with free length. Ranges checked: `offset + size <=
stride`, `row < count`, and the absolute bytes must fit inside the payload. A byte edit **cannot
change the payload size**.

### 4.2 `text[]` — text writes

| Key | Type | Required | Semantics |
|---|---|---|---|
| `table` | integer | **yes** | Must be a text table (`#4636`–`#4653`). |
| `id` | integer | **yes** | `4 … count+3`. |
| `slot` | integer 0–5 | no (`0`) | Position in the 6-slot block. |
| `expect_sha256` | 64 lowercase hex | **one of the two** | sha256 of the block of `id`: the concatenation of the bytes of its slots, `+0`→`+5`, no terminator, no separator, no normalisation ([MOD-FORMAT.md](MOD-FORMAT.md) §3.1). This is the form that travels. |
| `expect` | string | **one of the two** | Current text of that slot in clear (`""` if empty). Accepted by the kit; not published. |
| `value` | string | **yes** | New text, UTF-8, no `\x00`. |
| `why` | string | **yes** | As in `edits[]`. |
| `confidence` | as `edits[]` | no | |

Both `expect` and `expect_sha256` at once, or neither, is a schema error. Error messages **never**
print the text: a mismatch is reported as *expected* versus *found* by **length and truncated
`sha256`**. That is a privacy rule of the project, not an oversight.

The hash is checked against the block **as it is in the container before the mod**, never against the
state left by earlier edits of the same mod: two edits of one block in different slots carry the same
digest and both apply; two edits of the same `(table, id, slot)` are an error (`mod.text.duplicate`).

### 4.3 Merge keys

Composition is per `(table, row, offset)` for bytes and `(table, id, slot)` for text.

| Case | Result |
|---|---|
| Same row, same offset | **conflict**, even if the values are identical |
| Same row, overlapping ranges | **conflict** |
| Same row, disjoint ranges | composed, with a `merge.same_row` warning |
| Different rows or tables | composed silently |
| Same text slot | **conflict** |
| Same block, different slots | composed, with a warning |
| Different `container_md5` | **conflict** |

---

## 5 · CLI parameters

Global (accepted before **or** after the subcommand):

| Flag | Default | Meaning |
|---|---|---|
| `--container <dir>` | `$PKP_ROMFS` | Folder holding `LD_C0_R.BIN` and `LI_C0_R.IDX`. |
| `--json` | off | Machine-readable output. |

Environment:

| Variable | Default | Meaning |
|---|---|---|
| `PKP_ROMFS` | `./romfs` | Container folder: the one holding `LD_C0_R.BIN` and `LI_C0_R.IDX`. Overridden by `--container`. |
| `PKP_SAVE` | `./save` | Save folder (`G00/`, `B00/`). Read-only unless you pass `--allow-live-save`. |
| `PKP_PROTECTED` | *(empty)* | Extra folders the kit refuses to write into, separated by `os.pathsep`. The resolved `PKP_ROMFS` is always protected. |

Per command:

| Command | Parameters |
|---|---|
| `table` | `table` (int), `--rows a:b` or `--rows N` (default `0:20`) |
| `row` | `table`, `row` |
| `dump` | `entry`, `out` (refused inside the dump tree) |
| `repack` | `outdir`, `--recompress`, `--backend {auto,stdlib,stock}` |
| `mod new` | `name`, `--dir` |
| `mod validate` | `mod`, `--no-expect`, `--no-container` |
| `mod merge` | `a`, `b`, `-o/--out`, `--name`, `--version` (default `0.1.0`) |
| `mod apply` | `mod`, `[--dry-run \| --yes]`, `--keep-backup` (default) / `--no-backup` |
| `save read` | `--save`, `--page {G00,B00}`, `--all` |
| `save write` | `--save`, `--page`, `--slot` (**required**), `--id`, `--count`, `--variant`, `--target`, `[--dry-run \| --yes]`, `--allow-live-save`, `--level`, `--strategy`, `--memlevel` |
| `save undo` | `backup`, `--yes` |
| `progress` | `--save`, `--page`, `--union`, `--confidence` |

Behaviour of the write-related flags:

| Flag | Meaning |
|---|---|
| `--dry-run` | Default. Nothing is opened for writing: no temporary file, no backup. |
| `--yes` | Actually writes. For `mod apply` it **requires** `--container`. |
| `--no-backup` | Skips the backup — and therefore skips the undo. The tool says so instead of implying otherwise. |
| `--allow-live-save` | Permits writing into a save the game may be using. Dangerous by definition; off by default. |
| `--recompress` | Recompresses every entry instead of copying unchanged slots. Slow (tens of seconds). |
| `--backend` | `auto` detects the stock zlib, `stdlib` forces the interpreter's, `stock` requires the pinned build. |
| `--no-expect` | Validates schema only, without comparing `expect` to the container. |
| `--no-container` | Skips opening the container at all. |

Exit codes: `0` ok (including warnings and a successful dry run), `1` invalid mod / `expect`
mismatch / merge conflict / failed verification / mod folder or `mod.json` that does not exist,
`2` usage error, missing container pair or protected destination.

---

## 6 · Save parameters

Supported: **save version 2.0.1 only** (`0x0200017D`). Magic `0x31227687`, header `0x130` bytes,
payload 4,656,365 B per page. Two pages exist: `G00` (main) and `B00` (second); the inventory
region exists at the same offset in both.

| Parameter | Value | Confidence |
|---|---|---|
| `inventory` region | offset `0x46ECEA`, 130 records of **5 B** | measured |
| `itemId` | `u32 & 0x1FFF` (13 bits); `0` = empty slot | measured |
| Variant bits | bits 13–31 of that `u32` (variant / placement) | measured as a group; individual meaning not mapped |
| `count` | `u8` at `+4` of the record, 0–255 | measured |
| `catalogue` region | offset `0x402ED9`, 4,600 bytes, one per `#983` row | measured geometry; bit semantics **inferred** |
| `villagers` region | offset `0x0`, 1,050 records of 374 B; identifier at `+1..+16` | measured geometry; semantics inferred |
| `homes` region | offset `0x079824`, 1,050 records of 21 B | measured geometry; semantics inferred |
| `player_names` region | offset `0x46E0E5`, 9 records of 25 B | inferred, **and deliberately never read**: it is content |

Reading an `itemId` without the 13-bit mask is the classic mistake: the upper bits carry variant
and placement, so a masked read is what turns an impossible id into a real one. The kit applies
the mask everywhere.

Compression of the save body (only relevant if you recompress):

| Flag | Default | Meaning |
|---|---|---|
| `--level` | `1` | zlib level 0–9. The game uses 1. |
| `--strategy` | `default` | `default`, `fixed`, `filtered`. The game uses the default. |
| `--memlevel` | `8` | zlib `memLevel` 1–9. The game uses 8. |

Every write produces a backup folder plus a `manifest` (mod-less: file, md5 before/after,
payload diff); `save undo` refuses to restore over a file that changed after the backup was
taken.

---

## 7 · Progress parameters

`pkp progress` counts magnitudes, never reads content. A `ProgressSpec` is `key`, `region`,
`kind`, `arg`, `arg2`, `total`, `confidence`.

| `kind` | Counts |
|---|---|
| `occupied` | Records with any non-zero byte in `[arg, arg2]` (`0,0` = the whole record). |
| `distinct_ids` | Distinct values of `u32 & arg` at offset `arg2` of the record. |
| `bit_set` | Records whose byte at `arg2` has bit `arg` set. |

`--union` adds the distinct ids of the other page; `--confidence` prints the evidence and the
confidence of each figure.

---

## 8 · Where each number comes from

| Figure | Reproduce with |
|---|---|
| 12,298 entries, flags, sizes, md5 | `python pkp.py info` |
| Structure of all records and blocks | `python pkp.py repack <out> --recompress` (must print `IDENTICO`) |
| Table geometry | `python pkp.py table <n>` · `python pkp.py row <n> <r>` |
| Mod contract | `python pkp.py mod validate <dir>` |
| Save regions | `python pkp.py save read --all` · `python pkp.py progress --confidence` |
| Test suite | `python run-tests.py` |

If a figure in this file disagrees with a command's output, the command wins and this file gets
fixed. See [PROCEDENCIA.md](../PROCEDENCIA.md) for the corrected figures that used to be wrong
here.
