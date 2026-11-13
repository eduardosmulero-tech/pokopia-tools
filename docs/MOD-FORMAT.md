# Declarative mod format (`mod.json`) — contract

**Format version:** `mod_format = 1` · **Date:** 2026-11-04
**Reference contract:** `docs/ARQUITECTURA-KIT.md` §4–§5 (development document, not included in the
release; this document makes it concrete, and where it disagrees the difference is recorded in §9).
Spanish working version of this same document, also kept out of the release:
`docs/MOD-FORMAT.es.md`.

A mod is **a folder with a `mod.json` manifest and, optionally, data files**. There are no scripts
for the user to run: `pkp` reads the manifest, checks what is declared and writes bytes into a
**copy** of the container. It is not an installer, not a patch to the executable or to the save,
and not a distribution of game content: every value in it is a number, an offset or an id.

```
ejemplos/editar-fila/
  mod.json          <- mandatory
  datos/...         <- optional (files[])
```

House rule: **this document contains no game content**. Every example is expressed as
**table, row and numeric id**.

---

## 1. Manifest

```json
{
  "mod_format": 1,
  "name": "ejemplo-editar-fila",
  "version": "0.1.0",
  "authors": ["..."],
  "description": "free text, optional",
  "game": {
    "title": "pokopia",
    "version": "2.0.1a",
    "container_md5": {
      "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
      "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8"
    }
  },
  "requires": [],
  "edits": [ ... ],
  "text": [ ... ],
  "files": [ ... ]
}
```

| Field | Type | Mandatory | What it means |
|---|---|---|---|
| `mod_format` | integer | **yes** | Format version. Only `1` today. |
| `name` | string | **yes** | `^[a-z0-9][a-z0-9._-]{0,63}$` (lowercase, digits, `.`, `_`, `-`). |
| `version` | string | **yes** | `x.y.z` (semver; `0.1.0`, `1.2.3-rc1`). A value that does not look like semver is a **warning**, not an error. |
| `authors` | list of strings | **yes** | May be empty (warning). |
| `description` | string | no | Free text. |
| `game.title` | string | **yes** | Internal title id. |
| `game.version` | string | **yes** | Game version the mod was written for (`2.0.1a`). |
| `game.container_md5` | object | **yes** | md5 of **both** files. Without it nothing is applied. |
| `requires` | list | no | Dependencies (strings or objects). Preserved; not resolved today. |
| `edits` | list | no* | Byte writes (§2). |
| `text` | list | no* | Text writes (§3). |
| `files` | list | no | `{"path", "sha256"}`; only the shape is checked today. |
| `romfs` | list | no | Files the mod puts in the romfs (`path`, `file`, `why`, hashes, §11). This is what makes the mod installable with the overlay (`pkp mod install`). |

\* A mod with neither `edits` nor `text` is valid but **does nothing** (`mod.empty` warning).

Unknown root keys: **warning**, not error (forward compatibility).

---

## 2. `edits[]` — byte writes

```json
{ "table": 983, "row": 1324, "offset": 34, "type": "u16",
  "expect": "2278", "value": "2279", "why": "nameIndex", "confidence": "verified" }
```

| Field | Type | Mandatory | Semantics |
|---|---|---|---|
| `table` | integer ≥ 0 | **yes** | Entry index in the container (`#983`). |
| `row` | integer ≥ 0 | **yes** | Row inside the table. |
| `offset` | integer ≥ 0 | **yes** | Byte offset relative to the start of the row. |
| `type` | string | **yes** | `u8 i8 u16 i16 u32 i32 u64 i64 f32 f64 bytes`. |
| `expect` | number/string | **yes** | What is **there now**. If it does not match, the mod does not apply. |
| `value` | number/string | **yes** | What gets written. Must fit `type`. |
| `why` | string | **yes** | Which field you believe you are touching. Cannot be empty. |
| `confidence` | `verified` \| `inference` \| `guess` | no (`verified`) | `guess` produces a **warning** on every validation (not an error). |
| `note` | string | no | Free comment. |

**Why `expect` and `why` are mandatory.** `expect` is the value the author read on the build they
worked on; without it a mod written in May silently corrupts a container from June and nobody can
say why. `why` is the only statement of intent the format has: a reader who cannot name the field
still learns what the author believed. A missing `expect`, or a missing/empty `why`, is an
**error** (`schema.expect`, `schema.why`) and the mod does not load. When `expect` is present but
does not match the bytes on disk, the mod is rejected with the *expected / found* pair and nothing
is written — not even in a dry run.

**Numeric values:** integers in decimal (`"2279"`, `2279`) or hexadecimal (`"0x8e7"`), negatives
allowed in `i*` types. Floats in `f32`/`f64`. `bytes` is written in hex (`"0012ab"`,
`"00 12 ab"`, `"0x0012ab"`); its length is free and cannot be checked against the stride.

**Range rules** (checked by `validate`):

* `offset + size(type) <= stride` of the table, when the table has declared geometry;
* `row < count` of the table;
* the absolute bytes `header + row*stride + offset + size` must fit inside the payload.

A byte edit **cannot change the payload size**. To change lengths there is only `text` (§3).

Tables with declared geometry (registry `pokopia/tables/registry.py`):

| Table | Geometry | Confidence |
|---|---|---|
| `#983` | header 64 B, 4,600 rows of 68 B, `count` at +0, `version`=3 at +4 | geometry measured; **only demonstrated field**: `+34 u16 nameIndex` (text id = `nameIndex + 3`, `docs/SPEC-NAMES.md` §6.3) |
| `#40` / `#41` / `#44` | 80 / 16 / 100 B per row, 4,096 rows | geometry measured, fields without a schema |
| `#42` | 4 B per row, 256 rows | geometry measured; the header `count` says 255 |
| `#4636`–`#4644` | texts (descriptions), 3,001 records of 32 B, pool at 96,096 | `docs/SPEC-NAMES.md` §3.2 |
| `#4645`–`#4653` | texts (names), 3,001 records of 32 B, pool at 96,102 | `docs/SPEC-NAMES.md` §3.1 |

A table **without** declared geometry can be edited anyway: it is warned about
(`mod.unknown_table`) and only the payload bounds are checked.

---

## 3. `text[]` — text writes

```json
{ "table": 4650, "id": 5, "slot": 0,
  "expect_sha256": "4f1bac…b5813", "value": "MOD-RENOMBRA-1",
  "why": "slot 0 (singular) of block 6*(id-4); the hash identifies the block of this build" }

{ "table": 4650, "id": 131, "slot": 0, "expect": "", "value": "MOD-TEXT-1",
  "why": "slot 0 (singular) of block 6*(id-4); this id has the block empty in this build" }
```

| Field | Type | Mandatory | Semantics |
|---|---|---|---|
| `table` | integer | **yes** | Must be a text table (`#4636`–`#4653`). |
| `id` | integer | **yes** | Catalogue id. Valid: `4 … count+3` (here 4…3,004, `docs/SPEC-NAMES.md` §6). |
| `slot` | integer 0–5 | no (`0`) | Offset inside the 6-slot block of the id. `0` = singular, `2` = plural. |
| `expect_sha256` | 64 lowercase hex | **one of the two** | sha256 of the block of `id`; the criterion is fixed in §3.1. This is the form that travels. |
| `expect` | string | **one of the two** | Current text of the slot in clear (`""` if empty). Accepted, never published. |
| `value` | string | **yes** | New text. UTF-8, no `\x00`. |
| `why` | string | **yes** | As in `edits[]`. |
| `confidence` | as in `edits[]` | no | |

Declaring **both** `expect` and `expect_sha256`, or **neither**, is a schema error
(`schema.text.expect`) and the mod does not load.

How it is applied: the text zone is split into NUL-delimited slots, slot `6*(id-4)+slot` is
replaced and the **whole pool is reserialised keeping the slot order**. That is:

* the record area (the first `64 + 32*count` bytes) stays **byte for byte the same**;
* the number and the order of slots do not change: a longer text shifts the bytes that follow but
  **renames nobody**, because the game addresses by slot **ordinal**, not by offset
  (`docs/SPEC-NAMES.md` §6; the six `int32` of the record do not point at slot starts);
* the payload **does** change size; the index is recalculated on write and later entries change
  their `offset` (their content is copied verbatim).

Practical consequence: `text` and `edits` on the **same** table can be combined, but only the
`edits` go to the record area.

**Text privacy:** error messages **never** print the text found, and never print the text expected
either. A failed `expect` reports *how many bytes* were expected and *how many* are there, plus the
truncated `sha256` of what is there — never *what* is there, and never the string that was copied
from the dump into a manifest.

### 3.1 `expect_sha256` — the fixed criterion

A text edit identifies the current content of its **block** (the six slots of `id`) by hash. The
input of the hash is fixed here so that two people computing it on the same build get the same 64
characters:

> **sha256 over the concatenation of the bytes of the slots of the block, in order `+0` → `+5`,
> exactly as they sit in the pool.**

Concretely:

* **no terminator**: the NUL that separates slots inside the pool is **not** part of the input;
* **no separator** of any kind between slots — plain concatenation, nothing added;
* **no Unicode normalisation and no re-encoding**: the bytes are the ones in the payload, whatever
  they are (they are not required to be valid UTF-8, and nothing is decoded on the way);
* the result is **lowercase hexadecimal, 64 characters**, no `0x` prefix, no spaces. Uppercase is a
  schema error (`schema.text.expect_sha256`);
* if the block has **fewer than six slots** in the pool — the last block of a table can be
  truncated: `#4650` has 18,003 slots for 18,006 holes — the slots that exist are hashed, in order,
  and nothing is invented to fill the gap;
* a block whose slots are all empty hashes the empty byte string:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The hash covers the **whole block**, not the single slot being written: one hash identifies
`(table, id)` completely, and `slot` still says which of the six slots is replaced.

**Against which state it is compared.** The hash is checked against the block **as it sits in the
container before the mod is applied** — the payload the author had in front of them when they wrote
the hash. Never against the state left behind by earlier edits of the same mod, even when those
edits touch the same block: the reference is immutable, and it is exactly the one `validate` uses.
From that rule:

* two edits in the **same table, different `id`** → each hash refers to its own block; both apply;
* two edits of the **same block, different slots** (say `+0` and `+2` of one id) → both carry the
  same digest of the pristine block and both apply; the result keeps both new texts;
* two edits of the **same `(table, id, slot)`** → schema error `mod.text.duplicate` (with both
  locations): the second would silently overwrite the first, so it is refused;
* `validate` and `apply` compare the same thing against the same bytes, so they cannot disagree: if
  `validate` accepts the hash, `apply` applies it.

**How to obtain it.** `pkp row <table> <id>` prints the six slots (length and truncated sha256) and,
on the last line, the digest of the block:

```
$ pkp row 4650 5
#4650 textos es: count 3001, pool en 96102, 18003 slots (terminado=True)
id 5 -> slots 6..11 del bloque
  +0  17 B  sha256 935f8879d5e0
  +1  0 B  sha256 e3b0c44298fc
  +2  18 B  sha256 e2a8faa19321
  +3  17 B  sha256 935f8879d5e0
  +4  0 B  sha256 e3b0c44298fc
  +5  18 B  sha256 e2a8faa19321
  bloque  70 B en 6 slots  sha256 4f1bac…b5813
  ^ este es el valor de 'expect_sha256' (docs/MOD-FORMAT.md §3.1)
```

**What it protects, and what it does not.** It keeps the text out of the manifest and out of every
error message, so a mod can be published and reviewed without carrying a single line of the game's
text. It does **not** make that content secret against a determined reader: a short string can be
guessed from its hash with a dictionary. It protects against accidental publication, which is what
the repository rule (`docs/NORMA-CONTENIDO-Y-PUBLICACION.md`) is about; it is not encryption.

---

## 4. `merge`: how two mods compose

Composition is per `(table, row, offset)` (bytes) and per `(table, id, slot)` (text):

| Case | Result |
|---|---|
| Same table, same row, **same offset** | **Conflict** (`exact overlap`), even if the value matches |
| Same table, same row, byte ranges that **overlap** | **Conflict** (`partial overlap`) |
| Same table, same row, **disjoint** offsets | Composed, with a **warning** (`merge.same_row`) |
| Same table, different rows / different tables | Composed, silently |
| Same text `slot` (`table`, `id`, `slot`) | **Conflict** |
| Same block, different slots | Composed, with a **warning** |
| Both mods declare a different `container_md5` | **Conflict** |

Exit code: `0` composed (`-o/mod.json` is written if `-o` was given), `1` conflict (nothing is
written).

Why exact overlap is a conflict even with the same value: the application order is not defined, and
one mod's `expect` can stop being true once the other has been applied. Better to refuse than to
guess.

And that is why **same block, different slots does compose**: every `expect_sha256` is compared
against the pristine block (§3.1), so two edits of one block do not invalidate each other's hash and
the composed mod applies both. A pair on the **same `slot`** stays a conflict — the second would
overwrite the first.

---

## 5. `apply`: writing to a copy

```bash
# 1) working copy (once)
mkdir -p build/copia && cp <romfs>/LD_C0_R.BIN <romfs>/LI_C0_R.IDX build/copia/

# 2) rehearsal: touches nothing
pkp mod apply ejemplos/editar-fila --container build/copia --dry-run

# 3) apply for real (backup by default)
pkp mod apply ejemplos/editar-fila --container build/copia --yes
```

Guarantees:

1. **`--dry-run` is the default mode** and opens no file for writing: no temporaries, no backups,
   not even the container. The md5 before and after are identical. Without `--container`, the
   rehearsal runs against the default container (the dump, **read-only**): it is read, validated
   and planned, and nothing is written.
2. **`--container` is mandatory in order to write** (`--yes`): there is no default, so a write
   cannot land on the dump "by accident".
3. **Path guards**: any destination inside the configured romfs (`PKP_ROMFS`) or inside the trees
   of `PKP_PROTECTED` is refused (`GuardError`, exit 2). The kit never writes there.
4. **Atomic write**: bytes go to `.pkp-tmp-<pid>/` inside the copy, are read back, and **only**
   then are `LD_C0_R.BIN` and `LI_C0_R.IDX` replaced with `os.replace`.
5. **Verification before substitution**:
   * `verify` of the written container: 0 problems;
   * payload-by-payload comparison against the original using the kit's **reader**: the only
     entries that differ are the edited tables, and they are **exactly** the declared ones;
   * every payload read from disk has to be identical to the planned one;
   * for `edits`, the byte-for-byte diff has to fall **inside** the declared ranges;
   * for `text`, the record-area prefix has to be identical and the number and order of slots
     cannot change, with a single slot modified per edit.
6. **Backup** in `<copy>/.pkp-backup/<YYYYMMDD-HHMMSS>/` with both files and a `backup.json`
   (mod, version and md5). The exact undo command is printed:

   ```
   cp build/copia/.pkp-backup/20261104-001234/LD_C0_R.BIN build/copia/LD_C0_R.BIN
   cp build/copia/.pkp-backup/20261104-001234/LI_C0_R.IDX build/copia/LI_C0_R.IDX
   ```

   `--no-backup` turns it off (and then there is no undo). `--keep-backup` is the default.

What `apply` does **not** do: create new entries in the container, change an entry's `blockSize`,
touch models or assets, or write to the save.

---

## 6. `validate`: what it checks and what it does not

`pkp mod validate <folder> [--container <dir>] [--no-expect] [--no-container]`

| Check | Error or warning? |
|---|---|
| Valid JSON, root is an object | error |
| `mod_format`, `name`, `version`, `authors`, `game.*` | error (missing or wrong type) |
| `expect` and `why` present in every byte edit | **error** |
| Exactly one of `expect` / `expect_sha256` in every text edit | **error** (both or neither) |
| Two text edits on the same `(table, id, slot)` | error (`mod.text.duplicate`, both locations) |
| `expect_sha256` not 64 lowercase hex characters | error |
| Known `type` and values that fit it | error |
| `offset + size <= stride`, `row < count` | error |
| `expect` different from the real bytes, or `expect_sha256` different from the real block | error, with *expected / found* (lengths and truncated sha256, never text) |
| `container_md5` different from the real one | error (and the `expect` checks are skipped: they mean nothing there) |
| Table without declared geometry | **warning** for byte edits; **error** for text edits (a text table is required) |
| `confidence: guess` | **warning** |
| Mod without edits | **warning** |
| Unknown keys | **warning** |

It does not check: that the game accepts the result (nothing is executed), the semantics of fields
without a schema, or `requires`/`files` (only their shape).

---

## 7. The four complete examples

They live in `ejemplos/` and are validated by `tests/test_mod_validate.py`. The transcripts below
are literal: the CLI prints its human output in Spanish today, so the lines are quoted as they come
out, with the local path of the working copy elided as `build/copia`.

### 7.1 Editing a row — `ejemplos/editar-fila/mod.json`

```json
{
  "mod_format": 1,
  "name": "ejemplo-editar-fila",
  "version": "0.1.0",
  "authors": ["worker (tarjeta t_df136634)"],
  "description": "Ejemplo minimo: cambia un u16 de una fila de #983. Se expresa por id y offset, sin contenido del juego.",
  "game": {
    "title": "pokopia",
    "version": "2.0.1a",
    "container_md5": {
      "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
      "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8"
    }
  },
  "requires": [],
  "edits": [
    {
      "table": 983, "row": 1324, "offset": 34, "type": "u16",
      "expect": "2278", "value": "2279",
      "why": "nameIndex: u16 en +34; el id de texto es nameIndex + 3 (docs/SPEC-NAMES.md 6.3)",
      "confidence": "verified"
    }
  ],
  "text": [],
  "files": []
}
```

Transcript of the rehearsal against a copy (`--dry-run`):

```
mod: ejemplo-editar-fila@0.1.0
contenedor: build/copia   [dry-run]
md5 antes : BIN 358a672d506ce2b0399149ede64a6760  IDX 7e056a097f28a62f002ad961a611edf8
tabla #983: 312864 -> 312864 B  flag=1 blockSize=0x10000
  diff: 1 tramo(s), 1 byte(s)
    +90130  0xe6 -> 0xe7
  reempaquetado: ok  prefijo de texto identico: n/a
  dry-run: no se ha escrito nada
resultado: OK
```

`90130 = 64 + 1324*68 + 34`: the u16 `2278 -> 2279` only changes the low byte.

### 7.2 Editing a text — `ejemplos/editar-texto/mod.json`

```json
{
  "mod_format": 1,
  "name": "ejemplo-editar-texto",
  "version": "0.1.0",
  "authors": ["worker (tarjeta t_df136634)"],
  "description": "Ejemplo: escribe un texto en un slot vacio de una tabla de textos. El valor es un marcador, no contenido del juego.",
  "game": {
    "title": "pokopia",
    "version": "2.0.1a",
    "container_md5": {
      "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
      "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8"
    }
  },
  "requires": [],
  "edits": [],
  "text": [
    {
      "table": 4650, "id": 131, "slot": 0,
      "expect": "", "value": "MOD-TEXT-1",
      "why": "slot 0 (singular) del bloque 6*(id-4); este id tiene el bloque vacio en este build (medido)",
      "confidence": "verified"
    }
  ],
  "files": []
}
```

Transcript of the rehearsal:

```
mod: ejemplo-editar-texto@0.1.0
contenedor: build/copia   [dry-run]
md5 antes : BIN 358a672d506ce2b0399149ede64a6760  IDX 7e056a097f28a62f002ad961a611edf8
tabla #4650: 298584 -> 298594 B  flag=1 blockSize=0x10000
  slots totales: 18003 -> 18003; cambios:
    slot 762  0 B -> 10 B  nuevo='MOD-TEXT-1'
  reempaquetado: ok  prefijo de texto identico: True
  dry-run: no se ha escrito nada
resultado: OK
```

`762 = 6*(131-4)`. The payload grows by 10 bytes and the offsets of the later entries change.

### 7.3 Writing a new row — `ejemplos/escribir-fila/mod.json`

Clone an existing row (`4599`) into another one (`0`), field by field. All twelve fields go as
`confidence: guess`: there is no schema that demonstrates them (`SPEC-ITEM-ROW` is still pending).
The only demonstrated field of the row (`+34 u16 nameIndex`) is not touched by this example. The
first two and the last are shown; the repository file has all 12.

```json
{
  "mod_format": 1,
  "name": "ejemplo-escribir-fila",
  "version": "0.1.0",
  "authors": ["worker (tarjeta t_df136634)"],
  "description": "Ejemplo: escribe una fila nueva clonando el contenido de otra fila, campo a campo por offset.",
  "game": {
    "title": "pokopia", "version": "2.0.1a",
    "container_md5": {
      "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
      "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8"
    }
  },
  "requires": [],
  "edits": [
    { "table": 983, "row": 0, "offset": 8,  "type": "u32",
      "expect": "0", "value": "10",
      "why": "u32 en +8 del registro; campo sin esquema demostrado (clon de la fila 4599)",
      "confidence": "guess" },
    { "table": 983, "row": 0, "offset": 12, "type": "u32",
      "expect": "0", "value": "1999",
      "why": "u32 en +12 del registro; campo sin esquema demostrado (clon de la fila 4599)",
      "confidence": "guess" },

    "… (offsets 16, 20, 24, 28, 32, 36, 40, 48, 56 with the same pattern) …",

    { "table": 983, "row": 0, "offset": 64, "type": "u32",
      "expect": "0", "value": "8192",
      "why": "u32 en +64 del registro; campo sin esquema demostrado (clon de la fila 4599)",
      "confidence": "guess" }
  ],
  "text": [],
  "files": []
}
```

`validate` answers with 12 `confidence=guess` warnings and **exit 0**: a `guess` is not an error,
but it does not go unnoticed. The dry run reports `diff: 12 tramo(s), 19 byte(s)` inside `#983`,
all of them inside the offsets the manifest declares.

### 7.4 Renaming an existing text — `ejemplos/renombrar-texto/mod.json`

The case the format was missing: the block is **not** empty, so the mod has to prove *which* block
it is editing. It does so with `expect_sha256` (the digest of the six slots, §3.1) and never writes
the current text down. `4f1bac…b5813` is abbreviated here; the repository file has the 64
characters, and the value written is a marker, not game content.

```json
{
  "mod_format": 1,
  "name": "ejemplo-renombrar-texto",
  "version": "0.1.0",
  "authors": ["worker (tarjeta t_ca5be1e2)"],
  "description": "Ejemplo: sustituye un texto que YA existe usando expect_sha256 (sha256 del bloque de 6 slots) en vez del texto en claro. El valor escrito es un marcador inventado, no contenido del juego.",
  "game": {
    "title": "pokopia",
    "version": "2.0.1a",
    "container_md5": {
      "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
      "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8"
    }
  },
  "requires": [],
  "edits": [],
  "text": [
    {
      "table": 4650, "id": 5, "slot": 0,
      "expect_sha256": "4f1bac…b5813", "value": "MOD-RENOMBRA-1",
      "why": "slot 0 (singular) del bloque 6*(id-4); el expect_sha256 identifica el bloque de este build sin escribir su contenido (criterio en docs/MOD-FORMAT.md 3.1)",
      "confidence": "verified"
    },
    {
      "table": 4650, "id": 5, "slot": 2,
      "expect_sha256": "4f1bac…b5813", "value": "MOD-RENOMBRA-2",
      "why": "slot 2 (plural) del MISMO bloque: el hash es el del bloque tal como esta en el contenedor antes del mod, no el que deja la edicion del slot 0 (docs/MOD-FORMAT.md 3.1)",
      "confidence": "verified"
    }
  ],
  "files": []
}
```

Transcript of the rehearsal against the working copy:

```
mod: ejemplo-renombrar-texto@0.1.0
contenedor: build/copia   [dry-run]
md5 antes : BIN 358a672d506ce2b0399149ede64a6760  IDX 7e056a097f28a62f002ad961a611edf8
tabla #4650: 298584 -> 298577 B  flag=1 blockSize=0x10000
  slots totales: 18003 -> 18003; cambios:
    slot 6  17 B -> 14 B  nuevo='MOD-RENOMBRA-1'
    slot 8  18 B -> 14 B  nuevo='MOD-RENOMBRA-2'
  reempaquetado: ok  prefijo de texto identico: True
  dry-run: no se ha escrito nada
resultado: OK
```

`6 = 6*(5-4)` and `8 = 6*(5-4)+2`: the mod edits the singular **and** the plural of the same block.
Both hashes are the same digest because the reference is the pristine block, not the one left by the
previous edit (§3.1); the pool shrinks by 7 bytes and no other slot moves out of place. With a hash
that does not match the build, the mod is rejected with lengths and hashes only:

```
[ERROR] text[0] #4650 id 5 slot 0: esperaba el bloque con sha256 000…000 y encontre otro
        (70 B en 6 slots, sha256 4f1bac17691a)
```

---

## 8. Exit codes and messages

| Exit | When |
|---|---|
| `0` | Everything correct (including a correct `--dry-run`, and warnings). |
| `1` | Invalid mod, `expect` that does not match, `merge` conflict, failed verification, mod folder or `mod.json` that does not exist. |
| `2` | Wrong usage (missing `--container`, `--yes` together with `--dry-run`), container pair that does not exist, protected destination. |

Error messages always carry `where` (`edits[3] #983 fila 1324 +34 u16`) and the *expected / found*
pair in hexadecimal and decimal. Root-level schema errors have no `where`: they refer to the
manifest as a whole.

---

## 9. Corrections to the `ARQUITECTURA-KIT.md` §4 contract

They have been noted in the architecture document as well:

1. **`text[]` needs `expect` and `why`.** §4 shows `{table, id, value}`; without `expect` there is
   no way to know whether the text changed between game versions, and without `why` nobody knows
   what is being touched. This format requires both (rules 1 and 2 of §4 itself, applied to text
   too).
2. **`text[]` carries `slot` (0–5, default 0).** With `{table, id, value}` there is no way to say
   whether the singular or the plural is being edited.
3. **`name` has a pattern** (`^[a-z0-9][a-z0-9._-]{0,63}$`), because the name ends up being a
   folder name and a command-line argument.
4. **`merge` with an exact overlap is a conflict even when the values match** (§4.4 said "those
   that touch the same row, conflict"; made concrete: the same row with disjoint ranges is allowed
   with a warning, the same offset or overlapping ranges are not).
5. **`text[]` carries `expect_sha256` as the publishable alternative to `expect`** (§3.1). §4 only
   knows the clear text; a manifest with the text in it cannot be published without carrying game
   content, so the identity of the block travels as a hash instead. Exactly one of the two fields,
   never both.

---

## 10. Known limits of this version

* **It does not create new entries** in the container: it only rewrites bytes or texts of existing
  tables.
* **It does not change an entry's `blockSize`** or its `flag`: the build's metadata is preserved.
* **It does not touch the save** (`pkp save` is a separate command) nor models/assets.
* **The files of `files[]` are not installed**: their shape is checked, they are not copied.
* **`requires` is not resolved.**
* **`expect_sha256` identifies, it does not encrypt.** A hash keeps the text out of the manifest and
  out of the error messages; a short string can still be guessed from its hash with a dictionary.
* Validation does not run the game: a mod can be valid under this contract and still not please the
  engine. The format guarantees what it guarantees: declared bytes, checked `expect` and a
  re-readable container.

---

## 11. `romfs[]` — installable files (overlay), added 2026-11-08

`mod_format` **stays at 1**: `romfs[]` is optional and an older reader ignores it with an
"unknown key" warning, so no data mod changes meaning. What it adds is the way to say "this mod also
puts this file in the romfs", which is what turns a folder into a mod installable with
`pkp mod install` (see `docs/MOD-OVERLAY.md`).

```json
"romfs": [
  {
    "path": "LD_C0_R.BIN",
    "file": "payload/LD_C0_R.BIN",
    "why": "container with texture #5879 replaced by an own G1T",
    "size": 237186304,
    "sha256": "f0c1…",
    "original_sha256": "2ea7…"
  }
]
```

| Field | Type | Mandatory | What it means |
|---|---|---|---|
| `path` | string | **yes** | Path inside the romfs: relative, `/`-separated, no root, no `..`, no `:`/drive. |
| `file` | string | **yes** | File inside the mod, same path rule. |
| `why` | string | **yes** | Which romfs file you replace and why (same rule as `edits[]`). |
| `size` | integer | no | Payload size. Filled by `pkp mod pack`; when present, `install` checks it. |
| `sha256` | string | no | Payload sha256. Filled by `pack`; when present, `install` checks it. |
| `original_sha256` | string \| null | no | sha256 of what the `RomFS.img` serves at `path`. `pack --img` computes it from the image; `null` = new path. It is what proves the original comes back after uninstall. |

Rules enforced at load time (error, not warning):

* two entries with the same `path` → error (`schema.romfs.path`);
* `path`/`file` with `..`, a root, a backslash, `:` or an empty segment → error
  (`romfs_path_problem`);
* `sha256`/`original_sha256` that are not 64 lowercase hex chars → error;
* a `file` that does not exist at pack or install time → I/O error with the path.

A mod with `romfs[]` is **not** composable with `merge` (§4): `pkp mod merge` rejects it and points
at installing both mods; the order of `DM_ROMFS_OVERLAY` decides which one wins, and
`pkp mod status` says who wins and who is inert.

---

## 12. Limits that still hold (updated 2026-11-08)

* Those of §10 still hold, with two nuances: files in `files[]` are still not installed (that is
  what `romfs[]` is for), and `romfs[]` **does** change game files, but in the overlay folder: the
  `RomFS.img` is never written by any command of the kit.
* `install`/`uninstall` do not launch the game and do not verify inside the engine: they refuse to
  operate while the runtime is running and they check the `sha256` of what the `img` serves.
  Whether the engine loads the asset is the asset format's business (`docs/G1T-FORMAT.md`).
* The `.pkmod` package is a deterministic ZIP; there is no signature and no game-version check
  beyond the manifest's `game.container_md5` and each file's `original_sha256`.
