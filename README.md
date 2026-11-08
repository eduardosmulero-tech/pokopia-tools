# pokopia-tools

Read, rewrite and mod the data container of **Pokémon Pokopia** (game version 2.0.1a, update
build 655360) on a copy of **your own** game files. Python 3.11. Licence
**GPL-3.0-or-later**.

This repository contains **no game content**: no assets, no textures, no models, no text, no
names, no dump, no keys. See [PROCEDENCIA.md](PROCEDENCIA.md) for the provenance of every
figure and the full list of what is deliberately absent.

**New in 0.3.0** — the four asset families around the container now travel in the release:
`G1T` textures (**14,412 files / 14,713 textures**, 99.85 % writable), a `G1M` model reader in the
package, `G2A` animations (**17,428 files**, byte-exact round trip) and the `ASRS`/`KTSR` sound
banks with **your own audio on every stream that carries its data inside the bank** — 18,835 of
18,835 streams, 398 of 403 banks — using the kit's own MS ADPCM **and `KA1A`** encoders. Also the
24 `.fdata` archives that hold all of it, and the pointer-plus-pool text tables. Every figure is
reproducible with a command; what does not work is listed under
[status](#status-what-is-measured-what-is-not) rather than glossed over.

---

## What this is / what this is not

| This is | This is not |
|---|---|
| A reader and a **writer** for the pair `LD_C0_R.BIN` + `LI_C0_R.IDX`, the data container of the build named above. | A distribution of the game, its data, its assets or its text. Nothing here replaces a copy you must already own. |
| A public **repacker** for that container, verified byte for byte: 12,298 / 12,298 payloads and 0 bytes different on rebuild, with the zlib build declared in `pyproject.toml`. | A decryption or key tool. It never handles a key and never reads an encrypted file. |
| A **declarative mod format** (`mod.json`): every edit declares which bytes it expects to find and refuses to apply if they are not there. | An emulator, an online-play tool or anything for multiplayer. There is no networking code in this repository. |
| A save reader/writer for **save version 2.0.1 only**, with a mandatory backup and a printed undo command. | A general save editor. For save editing there is already a mature tool (see [credits and provenance](#licence-provenance-and-credits)); this kit's own contribution is the container writer. |
| A library plus a CLI, with the schema kept in data files. | A GUI, and not a stable 1.0 API. Version 0.3.0, mod format version 1. Interfaces still move. |
| A reader for the **`.fdata` archives** that sit next to the container: 79,710 typed entries across 24 files, and the `.rdb` master index. | A general-purpose unpacker of the whole RomFS: the types it does not document are listed and extracted, nothing more. |
| A reader **and writer** for `G1T` textures (14,713 measured, 99.85 % writable) and `G2A` animations (17,428 files, byte-for-byte round trip). | A mod-ready texture pipeline for the 0.15 % that is BC6H, which stays read-only. |
| A **`G1M` reader** in the package: header, chunks, sections, mesh geometry and field-by-field diff. | A model writer. Repacking a `G1M` needs an external tool and is not byte-identical; the figures are in [SPEC-G1M.md](docs/SPEC-G1M.md) §7. |
| A reader and writer for `ASRS`/`KTSR` sound banks, **including your own audio** on all 18,835 internal streams (398 of 403 banks) with two encoders of its own: MS ADPCM and `KA1A`. | An audio player or converter, and nothing that is known to sound in the game yet: `.fdata` writing is not implemented. |

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
  suite needs `pytest`. The measurement scripts that produced the figures in these documents are
  not part of this release; the tests in `tests/` are.
* **Optional, only for pixel work**: `numpy`, `imagecodecs` (decode BC1/BC3/BC4/BC5/BC6H/BC7 and
  PNG) and `etcpak` (encode BC1/BC3/BC4/BC5/BC7). Without them `pkp tex list` and
  `pkp tex inject --same` still work; `extract` and `inject --png` exit with code 2 and name what
  is missing.

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
| `pkp fdata list <path>` | Header of every entry in a `.fdata` (PDRK/IDRK): offset, type, sizes, name hash, flags. |
| `pkp fdata stat <romfs>` | Entries per `type_ktid` across every `.fdata` under a folder; headers only, so a full pass is seconds. |
| `pkp fdata extract <path> --type <type> --out <dir>` | Decompress one type (`kidsobjdb`, `g1t`, …) as `<name_hash>.<type>`; refuses to write inside the romfs. |
| `pkp tex list <path> [--json]` | Textures of a `.g1t` or a `.fdata`: format, dimensions, mip count, 512 B-aligned chain, padding, frames and the `TRUNCADA` marker. |
| `pkp tex stat <romfs>` | Format census over every `.fdata` under a folder and what share of the textures is writable. |
| `pkp tex extract <path> --out <png>` | One texture to PNG (mip 0 only, lossless); `--index` and `--g1t` pick which, `--all` writes every one of them. |
| `pkp tex inject <path> --out <g1t>` | Rewrite the pixels of one texture with the same dimensions (`--png`); `--same` is the neutral round trip. |
| `pkp anim list <path> [--deep] [--limit N]` | One line per `g1a`/`g2a` animation of a `.fdata` or a folder; `--deep` parses splines, keys and blocks. |
| `pkp anim info <path>` | Header field by field, bones, and the sizes a rewrite would produce. |
| `pkp anim export <path> --out <file> [--format json\|csv]` | Dump an animation losslessly to JSON, or baked to CSV. |
| `pkp anim build <doc.json> --out <g1a>` | Rebuild the `.g1a`/`.g2a` from the exported JSON. |
| `pkp anim roundtrip <path>` | Read and rewrite the animation, and compare the sha256. |
| `pkp anim set <path> --bone B --channel rotation\|translation\|scale --frame N --axis x\|y\|z --value V --out <g1a>` | Change one key value and re-inject it; refuses to overwrite the input. |
| `pkp catalog list [--prefix BP\|PM\|BI\|PC\|AP]` | The 2,043 entity names of the object dictionary with their KT hash, one per line on stdout (summary on stderr). |
| `pkp catalog find <text>` | Case-insensitive substring search over those names; exit 1 when nothing matches. |
| `pkp objdb stat <romfs>` | `kidsobjdb` record count, size histogram and `type_hash` histogram (top 20 + tail) for the largest database. |
| `pkp objdb dump <romfs> --type 0xXXXXXXXX [--limit N]` | Records of one `type_hash` with their unique id and their `(kind, hash, values)` triples; `--limit 0` = all. |
| `pkp objdb id <romfs> <id>` | One record by its unique id, same layout. |
| `pkp snd list <bank.srsa> [--json]` | Sound bank (`ASRS`/`KTSR`) index: per stream codec, Hz, samples, loop, bytes and decrypted name. |
| `pkp snd extract <bank.srsa> --out <dir> [--stream N]` | Raw payload of each stream as `<bank>.<n>.<codec>`; refuses to write inside the romfs. |
| `pkp snd replace <bank.srsa> --swap A B` | Swap two sounds in place (no audio byte changes); `-o` or `--in-place` with `<bank>.orig`. |
| `pkp snd replace <bank.srsa> --stream N --file F [--from-banco B --from-stream M]` | Put another sound's stream into slot N, recalculating the three sizes; with `--from-banco`, also copy its audio header. |
| `pkp snd stat <dir>` | Bank count, codecs, and how many streams are replaceable by each route. |
| `pkp snd import <bank.srsa> --stream N --wav F [--loop MS]` | Put **your own** audio (PCM 16-bit mono WAV) into a stream: encodes it with the kit's own MS ADPCM encoder, or the `KA1A` one when the destination stream is `KA1A`, keeps the destination's block size or bitrate mode, rewrites rate/samples/loop and prints the round-trip SNR. `-o` or `--in-place` with `<bank>.orig`. |

Add `--json` to any command for machine-readable output.

---

## The mod format in one example

A mod is a folder with a `mod.json`; there are no scripts to run. Four real ones live in
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
   does not apply — that is how a mod written in May cannot corrupt a save in June. For text
   edits, `expect_sha256` takes its place: the sha256 of the block, so a published mod carries
   no game text at all.
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
* The 24 `.fdata` archives: 79,710 entries, 25 types, the two chunk framings and the `.rdb`
  master index.
* `G1T` textures: 14,412 files, 14,713 textures, 13,985 with an exact 512 B per-level mip chain
  (95.05 %), 99.85 % writable, swizzle in 8×8 blocks.
* `G1M` models: header, chunks, sections, vertex/index/submesh layout, mesh counting and
  field-by-field diff — [SPEC-G1M.md](docs/SPEC-G1M.md).
* `G2A` animations: 17,428 files read and rewritten byte for byte (17,428 / 17,428).
* Sound banks: 403 banks, 19,297 streams, 18,835 with the audio inside; **both codecs have an
  encoder**, so your own audio covers 18,835 / 18,835 internal streams in 398 of 403 banks.
* The pointer-plus-pool text tables: 2,409 of the 12,298 entries, 272,281 strings,
  32,864,377 B, three substitution modes.

**Not known, and not claimed**

* 15 of the 41 fields mapped in a `#983` row (23 measured, 3 inferred, 15 unknown).
* No confirmed reference from `#983` to the model table `#44`: geometry for a new object
  cannot be created, only existing rows can be re-pointed to existing variants.
* The semantics of the catalogue bitmap in the save (which bit means what).
* `G1M` material, shader, palette and socket sections: parsed as opaque and preserved, not
  interpreted.
* 641 `G1T` textures (4.36 %) whose mip chain is not explained yet, and 22 BC6H textures that
  cannot be re-encoded.
* Whether the engine accepts any of it: `vgmstream` validates the audio file, not the game, and
  nothing here writes a `.fdata`.

**Not implemented**

* Creating **new entries** in the container, or changing an entry's `blockSize` or `flag`.
* Installing `files[]` payloads (only their shape is checked) and resolving `requires`.
* Writing a `.fdata`, and therefore putting a modified texture, model, animation or sound bank
  back into the game.
* A `pkp` subcommand for models: the `G1M` reader is a library API only.
* Any GUI. Any 32-bit/other-platform build. Any other game version.

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | The 30-second path, verified step by step, with undo. |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Every parameter: container, table geometry, text pool, `mod.json` keys, CLI flags, save fields. |
| [docs/MOD-FORMAT.md](docs/MOD-FORMAT.md) | The mod contract: manifest, `edits[]`, `text[]` (including the `expect_sha256` criterion), merge, `apply` guarantees, `validate` matrix, exit codes and the four worked examples. |
| [docs/SPEC-CONTAINER.md](docs/SPEC-CONTAINER.md) | Byte-level specification of the container, with test vectors. |
| [docs/SPEC-NAMES.md](docs/SPEC-NAMES.md) | The nine name tables and nine description tables. |
| [docs/SPEC-FDATA.md](docs/SPEC-FDATA.md) | The 24 `.fdata` archives: 79,710 entries, 25 types, both chunk framings and the `.rdb` master index. |
| [docs/SPEC-G1T.md](docs/SPEC-G1T.md) | Textures `G1T`: header field by field, the 512 B per-level mip chain, the pixel-format census, the tile swizzle and what stays read-only. |
| [docs/SPEC-G1M.md](docs/SPEC-G1M.md) | Models `G1M`: the 12-byte wrapper trap, header, chunks, sections, mesh counting and what the round trip preserves and re-lays out. |
| [docs/SPEC-G1A.md](docs/SPEC-G1A.md) | Animations `G2A`: 32 B header, 10-bit bones, key blocks and the byte-exact rewrite. |
| [docs/SPEC-TEXT.md](docs/SPEC-TEXT.md) | The pointer-plus-pool text scheme: 2,409 tables, the `a` field that is not an offset, and the three substitution modes. |
| [docs/AUDIO.md](docs/AUDIO.md) | Sound banks (`ASRS`/`KTSR`): index, sound header field by field, the four write routes and their measured coverage. |
| [docs/AUDIO-KA1A.md](docs/AUDIO-KA1A.md) | The `KA1A` transform codec byte by byte: frames, 21 bands, logarithmic codes, the window, and the kit's encoder with its measured quality. |
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
