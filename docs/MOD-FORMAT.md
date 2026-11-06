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
{ "table": 4650, "id": 131, "slot": 0, "expect": "", "value": "MOD-TEXT-1",
  "why": "slot 0 (singular) of block 6*(id-4); this id has the block empty in this build" }
```

| Field | Type | Mandatory | Semantics |
|---|---|---|---|
| `table` | integer | **yes** | Must be a text table (`#4636`–`#4653`). |
| `id` | integer | **yes** | Catalogue id. Valid: `4 … count+3` (here 4…3,004, `docs/SPEC-NAMES.md` §6). |
| `slot` | integer 0–5 | no (`0`) | Offset inside the 6-slot block of the id. `0` = singular, `2` = plural. |
| `expect` | string | **yes** | Current text of the slot (`""` if empty). |
| `value` | string | **yes** | New text. UTF-8, no `\x00`. |
| `why` | string | **yes** | As in `edits[]`. |
| `confidence` | as in `edits[]` | no | |

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

**Text privacy:** error messages **never** print the text found; they identify it by length and
truncated `sha256`. A failed `expect` says *how much* was expected and *how much* is there, never
*what* is there. (The expected string is printed, because it comes from your own manifest, not
from the game.)

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
| `expect` and `why` present in every edit | **error** |
| Known `type` and values that fit it | error |
| `offset + size <= stride`, `row < count` | error |
| `expect` different from the real bytes | error, with *expected / found* |
| `container_md5` different from the real one | error (and the `expect` checks are skipped: they mean nothing there) |
| Table without declared geometry | **warning** for byte edits; **error** for text edits (a text table is required) |
| `confidence: guess` | **warning** |
| Mod without edits | **warning** |
| Unknown keys | **warning** |

It does not check: that the game accepts the result (nothing is executed), the semantics of fields
without a schema, or `requires`/`files` (only their shape).

---

## 7. The three complete examples

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

---

## 10. Known limits of this version

* **It does not create new entries** in the container: it only rewrites bytes or texts of existing
  tables.
* **It does not change an entry's `blockSize`** or its `flag`: the build's metadata is preserved.
* **It does not touch the save** (`pkp save` is a separate command) nor models/assets.
* **The files of `files[]` are not installed**: their shape is checked, they are not copied.
* **`requires` is not resolved.**
* Validation does not run the game: a mod can be valid under this contract and still not please the
  engine. The format guarantees what it guarantees: declared bytes, checked `expect` and a
  re-readable container.
