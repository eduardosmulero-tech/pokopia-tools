# pokopia-tools

Read, rewrite and mod the data container of **Pokémon Pokopia** (game version 2.0.1a, update
build 655360) on a copy of **your own** game files. Python 3.11. Licence
**GPL-3.0-or-later**.

This repository contains **no game content**: no assets, no textures, no models, no text, no
names, no dump, no keys. See [PROCEDENCIA.md](PROCEDENCIA.md) for the provenance of every
figure and the full list of what is deliberately absent.

---

## What this is / what this is not

| This is | This is not |
|---|---|
| A reader and a **writer** for the pair `LD_C0_R.BIN` + `LI_C0_R.IDX`, the data container of the build named above. | A distribution of the game, its data, its assets or its text. Nothing here replaces a copy you must already own. |
| A public **repacker** for that container, verified byte for byte: 12,298 / 12,298 payloads and 0 bytes different on rebuild, with the zlib build declared in `pyproject.toml`. | A decryption or key tool. It never handles a key and never reads an encrypted file. |
| A **declarative mod format** (`mod.json`): every edit declares which bytes it expects to find and refuses to apply if they are not there. | An emulator, an online-play tool or anything for multiplayer. There is no networking code in this repository. |
| A save reader/writer for **save version 2.0.1 only**, with a mandatory backup and a printed undo command. | A general save editor. For save editing there is already a mature tool (see [credits and provenance](#licence-provenance-and-credits)); this kit's own contribution is the container writer. |
| A library plus a CLI, with the schema kept in data files. | A GUI, and not a stable 1.0 API. Version 0.1.0, mod format version 1. Interfaces still move. |

---

## Supported build

| | |
|---|---|
| Game version | **2.0.1a** |
| Update build | **655360** (RomFS of the update) |
| Entries in `LI_C0_R.IDX` | **12,298** |
| `LD_C0_R.BIN` | **247,317,504 B**, md5 `358a672d506ce2b0399149ede64a6760` |
| `LI_C0_R.IDX` | **393,536 B**, md5 `7e056a097f28a62f002ad961a611edf8` |

Those md5 values are not decoration: a mod declares the md5 of the two files it was written
for, and `pkp` refuses to apply it anywhere else. Run `pkp info` to see the md5 of *your*
files and compare.

**Nothing else has been measured.** Another build may work, or may be silently wrong. If
`pkp repack` reports `IDENTICO` for both files on your build, the writer handles it; if it
reports `DISTINTO`, do not use the writer on it.

---

## 30-second quickstart

```bash
# 1. point the kit at the folder that holds your two container files
#    (optional: the default is ./romfs, relative to where you run pkp)
export PKP_ROMFS="/path/to/your/romfs"      # Windows: set PKP_ROMFS=C:\path\to\romfs

# 2. look at what you have (read-only, nothing is written)
python pkp.py info

# 3. work on a COPY - the kit refuses to write anywhere inside your dump
mkdir -p build/copia
cp "$PKP_ROMFS/LD_C0_R.BIN" "$PKP_ROMFS/LI_C0_R.IDX" build/copia/

# 4. rehearse a mod (default: dry run, no file is opened for writing)
python pkp.py mod apply ejemplos/editar-fila --container build/copia

# 5. apply it for real (writes, keeps a backup, prints the undo command)
python pkp.py mod apply ejemplos/editar-fila --container build/copia --yes
```

Step 2 on the supported build prints, among other things:

```
entradas   : 12298   flags {'0': 4169, '1': 8129}   vacias 2505
payload    : 548327864 B descomprimidos en 246615606 B empaquetados
problemas  : 0
```

**[docs/QUICKSTART.md](docs/QUICKSTART.md)** is the same path written out for someone who has
never seen this repository, including the undo and what to do when a step fails.

---

## Requirements

* **Python 3.11** — `requires-python = ">=3.11,<3.12"`. The test suite is signed on 3.11 and
  refuses to run elsewhere; that is deliberate, not an accident.
* **zlib 1.3.2** (stock build) for the byte-for-byte identity guarantee. With a zlib-ng build
  the recompressed slots come out different; the tool still works, the identity guarantee
  does not apply.
* **Nothing else at runtime**: the CLI and the library are standard library only. The test
  suite needs `pytest`, and the measurement scripts under `tools/` additionally need `PyYAML`.

---

## Environment variables

No path from anyone's machine is built into the code: every default is relative to the working
directory, and each one can be overridden.

| Variable | Default | Meaning |
|---|---|---|
| `PKP_ROMFS` | `./romfs` | Folder holding your `LD_C0_R.BIN` and `LI_C0_R.IDX`. Same as passing `--container`. |
| `PKP_SAVE` | `./save` | Folder holding your save pages (`G00/`, `B00/`). Read-only unless you pass `--allow-live-save`. |
| `PKP_PROTECTED` | *(empty)* | Extra folders the kit must never write into, separated by `os.pathsep` (`:` on POSIX, `;` on Windows). The resolved `PKP_ROMFS` is always protected, set it or not. |
| `PKP_BACKUP_DIR` | `build/backups` | Where the write commands keep the backup they print the undo command for. |

---

## Commands

Every command that writes has `--dry-run` as its **default**, and there is no code path that
writes to your dump.

| Command | What it does |
|---|---|
| `pkp info` | Entry count, flags, sizes, md5 of both files, and which tables have known geometry. |
| `pkp table <n> [--rows a:b]` | Dump a table using its declared geometry (header, count, stride, confidence). |
| `pkp row <n> <r>` | One row, field by field, with the confidence of each field. |
| `pkp dump <entry> <out>` | Write the decompressed payload of one entry to a file. |
| `pkp repack <outdir> [--recompress]` | Rebuild the container and compare md5 with the source. Exit 0 only if identical. |
| `pkp mod new <name>` | Skeleton `mod.json`, with the md5 of your container filled in. |
| `pkp mod validate <dir>` | Schema, ranges, cross-references, `container_md5` and every `expect`. |
| `pkp mod merge <a> <b> -o <dir>` | Compose two mods and report overlaps. |
| `pkp mod apply <dir> [--yes]` | Apply to a **copy**; dry run by default; backup and undo command printed. |
| `pkp save read [--page G00\|B00]` | Inventory region of a save: geometry, occupied slots, distinct ids. |
| `pkp save write --slot N [--id .. --count .. --variant ..]` | Write one slot; dry run by default; backup, manifest and undo. |
| `pkp save undo <backup> [--yes]` | Restore from one of those backups. |
| `pkp progress` | Counts only (occupied slots, distinct ids, catalogue bits) with the confidence of each figure. |

Add `--json` to any command for machine-readable output.

---

## The mod format in one example

A mod is a folder with a `mod.json`; there are no scripts to run. Three real ones live in
[`ejemplos/`](ejemplos/).

```json
{
  "mod_format": 1,
  "name": "ejemplo-editar-fila",
  "version": "0.1.0",
  "authors": ["you"],
  "game": {
    "title": "pokopia",
    "version": "2.0.1a",
    "container_md5": {
      "LD_C0_R.BIN": "358a672d506ce2b0399149ede64a6760",
      "LI_C0_R.IDX": "7e056a097f28a62f002ad961a611edf8"
    }
  },
  "edits": [
    { "table": 983, "row": 1324, "offset": 34, "type": "u16",
      "expect": "2278", "value": "2279",
      "why": "nameIndex: u16 at +34; the text id is nameIndex + 3",
      "confidence": "verified" }
  ]
}
```

The five rules that make a mod safe to share:

1. **`expect` is mandatory.** It is the value the author found. If your bytes differ, the mod
   does not apply — that is how a mod written in May cannot corrupt a save in June.
2. **`why` is mandatory.** An edit that cannot name the field it touches is marked
   `"confidence": "guess"` and every validation warns about it.
3. **`container_md5` is mandatory.** The mod states which build it was written for.
4. **Merge is per row and per offset**, never per file. Two mods touching different rows
   coexist; the same offset is a declared conflict, even if the values agree.
5. **Uninstall = delete a folder.** If it were harder than that, the design would be wrong.

Field-by-field reference for every key, type and range: **[docs/GLOSSARY.md](docs/GLOSSARY.md)**.
The contract itself — why `expect` and `why` are mandatory, how merge decides, what `apply`
guarantees and what it refuses to do — is **[docs/MOD-FORMAT.md](docs/MOD-FORMAT.md)**.

---

## Why it is safe to run

1. **Dry run is the default** for everything that writes. A dry run does not open a single
   file for writing, not even a temporary one.
2. **Writing requires `--container <copy>`.** There is no default, so a write cannot land in
   your dump "by accident", and a path guard rejects the dump tree explicitly.
3. **Writes are atomic**: bytes go to a temporary directory inside the copy, are read back,
   verified against the plan, and only then replace the originals.
4. **Verification before substitution**: the written container re-verifies with 0 problems,
   the only entries that differ are exactly the declared ones, and for text edits the record
   area must stay byte-identical with the same number of slots in the same order.
5. **Backup plus a printed undo command**, every time. `--no-backup` exists and then there is
   no undo — the tool says so instead of pretending otherwise.

---

## Status: what is measured, what is not

**Measured and reproducible**

* Container layout, index records, both entry encodings, block framing, alignment, padding.
* The writer: 12,298 / 12,298 payloads identical on rebuild, and 0 bytes different in
  247,317,504 + 393,536 bytes.
* Geometry of tables `#40`, `#41`, `#42`, `#44`, `#983`, `#4636`–`#4653` (row size, count,
  header, text pool start).
* One field of the 68-byte row of `#983`: `+34 u16`, the text index.
* Text tables: id → block of 6 slots, ordinal addressing, reserialisation that keeps the
  order of slots.
* Save version 2.0.1: header, magic, inventory region (130 records of 5 bytes), the id mask
  (13 bits) and the count byte, on both save pages.

**Not known, and not claimed**

* 15 of the 41 fields mapped in a `#983` row (23 measured, 3 inferred, 15 unknown).
* No confirmed reference from `#983` to the model table `#44`: geometry for a new object
  cannot be created, only existing rows can be re-pointed to existing variants.
* The semantics of the catalogue bitmap in the save (which bit means what).
* Whether the game accepts the result of a mod: nothing here executes the game.

**Not implemented**

* Creating **new entries** in the container, or changing an entry's `blockSize` or `flag`.
* Installing `files[]` payloads (only their shape is checked) and resolving `requires`.
* Any GUI. Any 32-bit/other-platform build. Any other game version.

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | The 30-second path, verified step by step, with undo. |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Every parameter: container, table geometry, text pool, `mod.json` keys, CLI flags, save fields. |
| [docs/MOD-FORMAT.md](docs/MOD-FORMAT.md) | The mod contract: manifest, `edits[]`, `text[]`, merge, `apply` guarantees, `validate` matrix, exit codes and the three worked examples. |
| [docs/SPEC-CONTAINER.md](docs/SPEC-CONTAINER.md) | Byte-level specification of the container, with test vectors. |
| [docs/SPEC-NAMES.md](docs/SPEC-NAMES.md) | The nine name tables and nine description tables. |
| [PROCEDENCIA.md](PROCEDENCIA.md) | Who made this, from which measurements, under which licence, and what is excluded. |
| [github.com/eduardosmulero-tech/pokopia-data-formats](https://github.com/eduardosmulero-tech/pokopia-data-formats) | The published format specifications (CC BY-SA 4.0). |

`docs/` also holds working notes in Spanish (item-row schema, save regions, architecture,
reports). They are kept in the repository for continuity and are not part of the documented
interface.

---

## Licence, provenance and credits

* **Code and documentation in this repository: GPL-3.0-or-later.** Full text in
  [LICENSE](LICENSE). GPL-3 is not the default here by accident: the index record layout was
  cross-checked against a GPL-3.0 reader, so the conservative choice is to inherit the
  licence rather than argue about it. Details in [PROCEDENCIA.md](PROCEDENCIA.md).
* **The format specifications are also published separately** under CC BY-SA 4.0 in
  `pokopia-data-formats`. This repository links them; it does not re-license them.
* **Credits:** the reader that first showed this container's index layout is
  [PokoHex](https://github.com/berichan/PokoHex) by *berichan* (C#, GPL-3.0). Its author
  reviewed our findings, reproduced them, and asked for exactly the split this repository
  implements: the save editor upstream, the container repacker and its documentation in a
  separate project. The issue is
  [PokoHex#1](https://github.com/berichan/PokoHex/issues/1).
* **No affiliation.** "Pokémon" and "Pokopia" are trademarks of Nintendo / Creatures Inc. /
  GAME FREAK inc. This project is not affiliated with, endorsed by or sponsored by any of
  them.
* **AI assistance, declared.** This toolkit was written with AI assistance under the
  direction and responsibility of its author. Every figure published here was produced by
  re-running a command, and the corrections that followed are recorded rather than quietly
  edited — that is the only reason to trust a number in this repository.

## No game content, ever

This repository documents **format**, not content. Examples and tests are expressed as table
index, row, offset and id (`#983`, row 1324, `+34`). There is no asset, no string from the
game, no dump and no key anywhere in the tree or in its history. If you ever find game
content here, that is a bug: open an issue and it will be removed.
