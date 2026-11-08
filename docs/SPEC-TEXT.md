# Specification — the pointer-plus-pool text scheme

The narrative text of the game (scene dialogue, NPC lines, tutorial notices, descriptions) lives in
`LD_C0_R.BIN`, in variable-length tables with a pool of UTF-8, NUL-terminated strings. There is no
message file in the RomFS: no `.msbt`, no `.txt`, no message container of any kind (§7).

This document describes the scheme shared by **2,409 of the 12,298 entries** of the container and
the measured numbers behind it. It does not replace [SPEC-NAMES.md](SPEC-NAMES.md), which covers the
name and description tables with their own 32-byte record layout.

Measured on the supported build ([README](../README.md#supported-build)).

---

## 1. Schema

```
+0x00   u32   count              rows (6 … 4,000 in the tables measured)
+0x04   u32   version            = 2 in every table of this family
+0x08   …     zeros up to 0x40   56 bytes, zero
+0x40         count records of 8 bytes:
                u32 a | u32 b    (b: no demonstrated meaning, §4)
pool          from 0x40 + 8·count: count UTF-8, NUL-terminated strings,
              one per row, in row order, contiguous
```

The invariant that closes the scheme:

```
Σ (length of the row's string + 1) = pool size − tail   (tail ≤ 16 B in all 2,409 tables)
```

In the 2,409 entries that satisfy it, the tail is 0 to 16 bytes and the strings are contiguous
(`start[row] == end[row−1] + 1`), so the pool is exactly the concatenation of the `count` strings.
That is the criterion that separates this scheme from a table of 32-byte records (`#4645`–`#4653`),
where the pool also holds strings but the record area does not fit this arithmetic.

---

## 2. Field `a` is not a direct offset

`a` is measured over a layout in which **each row dragged its own 8 record bytes along**, so

```
start(row) = a − 8 · (count − row)
```

The consequence is visible in tables whose first rows are empty: `a` **decreases** by 7 per row
while the strings advance 1 byte. Measured in `#4641`: `a[0] = 24,008`, `a[1] = 24,001`,
`a[2] = 23,994` … while the real starts are `0, 1, 2` (the first 82 rows are empty). Reading `a` as
a direct offset puts the start behind a NUL in **0 of 391** rows of `#3255`; with the formula it
lands on one in **391 of 391**.

Full proof (9 dialogue tables, 3,519 rows): every start lands at 0 or behind a NUL, 390/390 rows
contiguous, 0 non-UTF-8 strings in the nine tables.

---

## 3. Field `b`

No demonstrated meaning. In the dialogue family it takes **5 distinct values** over 391 rows
(`{0, 1, 8, 9, 10}`) and 4 values in the tutorial notices. No correlation was found with the number
of `<br>`/`<clear>` segments, with length or with language (the nine languages of a row share `b`).
It is **left untouched** when text is substituted: all three modes below preserve it.

---

## 4. Writing: three modes, and what each preserves

The pool is contiguous, so changing a string's length shifts every string after it. The three ways
to resolve that, implemented in `pokopia/tables/textpool.py::sustituir`:

| Mode | New text | Payload | Offsets | Result |
|---|---|---|---|---|
| `igual` (equal) | exactly the same length | unchanged | untouched | the rest of the payload does not change by a byte |
| `relleno` (pad) | equal or shorter + NUL padding | unchanged | untouched | empty strings are left in between |
| `ajuste` (fit) | equal or shorter | shrinks by `Δ` | `a` of every later row drops by `Δ` | pool and records stay coherent, no holes |

`ajuste` is the mode a mod wants: it rewrites the pool and re-adjusts the pointers of the later
rows. `relleno` is the conservative mode when not a byte of the records may move. `igual` moves the
least surface but forces the new text to be exactly the same length.

Before returning the new payload, all three modes pass the scheme's own validator (`validar`):
header, boundaries, monotonicity, UTF-8 and contiguity. If anything is off, `PoolError` and nothing
is written.

---

## 5. Measured figures

| Figure | Value |
|---|---|
| Entries in the container | 12,298 |
| Entries with this scheme | **2,409** |
| Rows with text | **272,281** |
| UTF-8 text | **32,864,377 B** (31.3 MiB) |
| Payload of those tables | 38,723,800 B |
| `count` minimum / maximum | 6 / 4,000 |
| Tables with a verified language | 671 of 2,409 (the rest are short strings: `-`) |

Tables whose pool is under 10 % text, or that do not close the invariant, **do not** enter the
census.

### Largest families (contiguous indices)

| Family | Tables | Payload | `count` | Strings | UTF-8 text | ASCII ratio |
|---|---:|---:|---|---:|---:|---:|
| `#1909`–`#2079` | 171 | 13,360,928 B | 1,000 | 63,360 | 11,810,405 B | 0.72 |
| `#3790`–`#3915` | 126 | 4,446,416 B | 8 values | 24,246 | 4,008,057 B | 0.72 |
| `#4546`–`#4644` | 99 | 2,249,632 B | 8 values | 25,002 | 1,864,564 B | 0.44 |
| `#3250`–`#3258` | **9** | 1,845,968 B | **391** | 3,330 | 1,813,680 B | 0.78 |
| `#2620`–`#2790` | 171 | 1,864,664 B | 18 values | 9,153 | 1,647,147 B | 0.69 |
| `#2845`–`#3060` | 216 | 1,489,328 B | 22 values | 6,381 | 1,332,596 B | 0.70 |
| `#5149`–`#5220` | 72 | 1,491,224 B | 5 values | 11,214 | 1,200,979 B | 0.51 |

`#3250`–`#3258` is the clean family to work with: 9 tables = 9 languages, the same `count` (391),
and one row = one dialogue scene with its markup (`<br>`, `<clear>`, `<$motion(…)`, `<$voicel(…)`,
`<gen;-2(o,a)>` for gender). Language verified with 20 samples per table:

| Entry | Language | Verdict | `count` | Rows with text |
|---|---|---|---:|---:|
| `#3250` | jp | 20/20 | 391 | 370 |
| `#3251` | en | 20/20 | 391 | 370 |
| `#3252` | fr | 18/20 (2 read as `es`) | 391 | 370 |
| `#3253` | it | 19/20 (1 read as `es`) | 391 | 370 |
| `#3254` | de | 20/20 | 391 | 370 |
| **`#3255`** | **es** | **20/20** | 391 | 370 |
| `#3256` | zh-TW | 20/20 | 391 | 370 |
| `#3257` | kr | 20/20 | 391 | 370 |
| `#3258` | zh-CN | 20/20 | 391 | 370 |

The language order of this family matches the one in [SPEC-NAMES.md](SPEC-NAMES.md) §3.1, but it is
**not assumed**: it is measured entry by entry.

---

## 6. The RomFS carries no text

Census of the RomFS of the supported build (44 files, 6.8 GB):

* extensions: 24 `.fdata`, 4 `.file`, 2 `.webm`, 2 `.rdb`, 2 `.rdx`, 1 `.BIN`, 1 `.IDX`,
  8 `.listing`. From the list of text extensions (`.msbt`, `.msbp`, `.txt`, `.csv`, `.json`, `.xml`,
  `.yaml`, `.po`, `.strings`, `.lang`, `.resx`): **0**.
* entry types (79,714 entries across the 28 containers): 26 KTGL types — mesh (`g1m`), texture
  (`g1t`), animation (`g1a`), skeleton (`g1s`), shaders (`g1e`, `g1co`, `g1em`), object databases
  (`kidsobjdb`)… **None is a message container**, and the type table in `pokopia/fdata.py` does not
  have one either.
* decompressing **every** type that is not mesh/texture/animation: 1,633,654,796 B and **0**
  occurrences of the `MsgStdBn`/`MsgPrjBn` magics; only 268 strings of ≥ 40 B in total, all from
  name catalogues.

---

## 7. What this document does **not** say

* It does **not** claim a meaning for `b`, nor the internal order of the strings with respect to
  the game's ids. The row → entity/scene mapping was not measured here.
* It is **not** integrated into `mod.json`: a text mod of this family is today made by running the
  text tool over a copy of the container. Moving it into the declarative format
  ([MOD-FORMAT.md](MOD-FORMAT.md)) is a separate, undone task.
* It does **not** claim the game displays the substitution: verification is on the artefact
  (re-read + validator), not on screen.
* **Open discrepancy with [SPEC-NAMES.md](SPEC-NAMES.md) §3.2**: the nine description tables
  `#4636`–`#4644` also close this scheme, with the pool at `64 + 8·3,001 = 24,072` and 3,001
  strings, whereas SPEC-NAMES declares 32-byte records and a pool at 96,096. Measured on `#4641`:
  at `+96,096` the previous byte is a letter, not a NUL (it lands mid-word); at `+24,154` the
  previous byte is a NUL and the string that starts there is a whole sentence, and the invariant
  closes with a 3-byte tail. SPEC-NAMES has not been touched: the correction is a separate task.

---

## 8. Reproduce it

The census itself was run with the author's tooling, which is not part of this release. What does
ship is the library the census uses, so the totals can be rebuilt entry by entry:

```python
from pokopia import tables, container          # container: read the pair, unpack one entry
from pokopia.tables import textpool

blob = ...                                     # decompressed payload of one entry
tabla = textpool.es_tabla(blob)                # None if the entry is not of this scheme
if tabla:
    print(tabla.count, len(tabla.textos(blob)), textpool.validar(tabla, blob))
```

Walking the 12,298 entries of the container with that loop gives **2,409** tables, **272,281**
strings and **32,864,377 B** of text, and `pokopia.tables.idioma.detectar` reproduces the language
verdicts of §5.
