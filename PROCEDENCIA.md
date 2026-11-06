# Provenance and authorship

> *Filename kept in Spanish to match this project's internal records; the content is in English
> because this document is meant to be read by strangers.*

**Document version:** 1 · **Date:** 2026-11-04 · **Scope:** the whole repository.

This document answers four questions that a reader has no other way to settle: **who** made
this, **from what**, **under which licence**, and **what is deliberately not here**. Where it
disagrees with any other document about provenance, this one wins; where it disagrees about
usage, the README wins.

---

## 1 · Who, and what this is not

`pokopia-tools` is a data toolkit for the container format of one game build, written by
**Eduardo Smulero** ([@eduardosmulero-tech](https://github.com/eduardosmulero-tech)), with AI
assistance as declared in §6.

* Not affiliated with, endorsed by or sponsored by Nintendo, Creatures Inc., GAME FREAK inc. or
  any of their subsidiaries. "Pokémon" and "Pokopia" are their trademarks, used here only to
  say which file format this is.
* No game files are distributed here. Every user works on **their own** copy. This repository
  does not obtain, download, decrypt or describe how to obtain one — that is out of scope
  permanently, not by omission.

---

## 2 · Provenance of the facts

Every figure in this repository was **measured** on one build (game 2.0.1a, update build
655360), by walking the real data with code in this repository, and is reproducible with a
command listed in [docs/GLOSSARY.md](docs/GLOSSARY.md#8--where-each-number-comes-from).

| What | How it was established |
|---|---|
| Container layout, index records, both entry encodings, block framing, alignment, padding | Full structural walk of all 12,298 records and 8,853 blocks; two independent readers written from the rules, sharing no code; **0 problems**. |
| The writer reproduces the build | Container rebuilt from scratch and compared byte for byte: 12,298 / 12,298 payloads identical, **0 bytes different** in 247,317,504 + 393,536 bytes, `cmp` clean. |
| Table geometry (`#40`, `#41`, `#42`, `#44`, `#983`, `#4636`–`#4653`) | Size = `64 + count × stride` measured on every table, `count`/`version` read from the header, text pools located by decoding. |
| The single demonstrated field of `#983` (`+34 u16`, text index) | 7 anchor readings taken on screen against the real save, plus the arithmetic `text id = nameIndex + 3` holding for every id in the save (0 incoherences across 9 languages). |
| Save regions (version 2.0.1) | Walk of both save pages, plus a cross-check between two independent magnitudes (villager slots vs home slots) with a constant residual per page. |
| Block alignment is 128 | Every other candidate (32, 64, 128, 256, 512, 1,024) fails in all 7,686 compressed entries; 128 fails in none. |

**The published specifications** of the container and of the name tables live in a separate
public repository, [pokopia-data-formats](https://github.com/eduardosmulero-tech/pokopia-data-formats),
first published on **2026-11-03**. The two documents in this repository
([docs/SPEC-CONTAINER.md](docs/SPEC-CONTAINER.md), [docs/SPEC-NAMES.md](docs/SPEC-NAMES.md)) are
the same specifications; the separate repository is the citable copy.

**Where the figures were wrong, they were repaired in public.** §8 lists each correction with
the figure that was retired. A repository that only ever adds numbers is not trustworthy, and
the record is the point.

---

## 3 · Provenance of the code

* **Language and dependencies:** Python 3.11, standard library only at runtime. No third-party
  code is vendored, and the only external obligation is the zlib build used for compression
  (a permissive licence, not bundled here).
* **Written for this project:** the container reader/writer, the mod loader/validator/merger,
  the save layer and the CLI were written here, in layers (format → schema → operations →
  presentation). None of it is a copy of another project's source.
* **One deliberate cross-check against GPL-3.0 source:** the 32-byte index record layout
  (`offset`, `rawSize`, `packedSize`, `flag`) was confirmed against the reader in
  [PokoHex](https://github.com/berichan/PokoHex) (`Parsing/GameArchive.cs`, C#, **GPL-3.0**, by
  *berichan*). Reading a GPL implementation to understand a format does not by itself make a
  derivative work — but arguing about that costs more than inheriting the licence, so this
  project is **GPL-3.0-or-later** and credits the chain explicitly. That is a conservative
  choice, made on purpose, and it is not presented as a legal analysis.
* **The upstream author reviewed the work.** Findings were filed as
  [PokoHex#1](https://github.com/berichan/PokoHex/issues/1) on 2026-11-03: entry counts, block
  framing, raw slots, alignment, and a reproducible zlib-ng size difference. *berichan*
  reproduced them and replied asking for exactly the split this repository implements — the save
  editor stays upstream, the general-purpose repacker and the container documentation live in a
  separate project. That request is the origin of this repository's scope.

---

## 4 · Licence map

| Material | Licence | Where |
|---|---|---|
| All code in `pokopia/`, `tools/`, `tests/`, `pkp*.py`, `run-tests.py` | **GPL-3.0-or-later** | [LICENSE](LICENSE) |
| Documentation written in this repository (README, quickstart, glossary, this file) | **GPL-3.0-or-later** | [LICENSE](LICENSE) |
| The format specifications, as published separately | **CC BY-SA 4.0** | `pokopia-data-formats` |
| Game data, game assets, game text, save files, container dumps | **not present, not licensed, not distributed** | — |

This repository **links** the specifications rather than re-licensing them: the same prose is
not published under two different licences, because a reader then cannot tell which one applies.
If you want the specification text for a non-GPL use, take it from `pokopia-data-formats` under
CC BY-SA 4.0.

**Attribution, when you reuse this work.** Credit the chain, not only this project: the format
documentation and the repacker come from here; the reader lineage starts at PokoHex (GPL-3.0,
*berichan*). A fork that keeps the GPL and says where it came from is welcome.

---

## 5 · What is deliberately absent

This repository will not contain, and no release will ship, any of the following:

| Absent | Why |
|---|---|
| Any game content: assets, textures, models, audio, fonts, strings, item or character names, map data | Redistributing the game's own material is the one thing that reliably gets a project removed, and it is not needed to document a format. Examples are expressed as table index, row, offset and id. |
| Container dumps, save files, or any byte of original data as a fixture | Every user brings their own copy. Fixtures are generated or expressed as expectations, never as redistributed bytes. |
| Decryption keys of any kind — the console's key files, title keys — or instructions to obtain them | Not a key tool, not a circumvention tool. The kit reads files the user already has, decrypted by their own setup. |
| Emulator patches, cheats, memory-edit codes, or executable patches | A different project with a different licence, a different fragility and a different legal axis. Mixing them here would put both at risk. |
| Anything for online or multiplayer play | No networking code, by design. |
| Any statement about how to run the game | Out of scope; the toolkit stops at "a container that re-verifies". |

This repository also documents **format, not content**: no figure here tells a player what is in
the game or what is left to discover.

---

## 6 · AI assistance, declared

The code, the specifications and the measurements in this repository were produced **with AI
assistance**, under the direction, review and responsibility of the human author.

What that means in practice, and what you may rely on:

* **Every published figure was re-run, by a command, before it was signed.** Not recalled, not
  copied from an earlier draft.
* **The assistant's own reports were audited by a mechanical verifier** that checks the shape of
  a report (provenance, counts, absolutes, forbidden content) and marks it as unverified when a
  check cannot run. A verifier cannot validate a *conclusion*; only re-running the commands can,
  which is why §9 exists.
* **Corrections are recorded, not silently edited** (§8). Two of the retired figures were
  wrong by a factor that would have embarrassed a public release, and they were caught by
  re-measuring rather than by a reviewer's intuition.
* **The author can explain what he signs.** Anything in this repository that he cannot explain
  in his own words is a defect; report it as one.

---

## 7 · Dated record

| Date (2026) | Event | Artefact |
|---|---|---|
| 10-31 | The save editor that first documented the index record appears | PokoHex, GPL-3.0 |
| 11-03 | Container measured end to end; findings filed upstream, reproduced by its author, who asks for a separate repacker project | PokoHex#1 (closed 19:13Z) |
| 11-03 | Container specification published | `pokopia-data-formats`, commit `016a092` |
| 11-04 | Writer validated (12,298/12,298, byte-identical), declarative mod format + CLI, item-row schema, save module, mechanical report verifier | this repository |
| 11-04 | Licence chosen (GPL-3.0), this provenance document written | [LICENSE](LICENSE), this file |

No claim of primacy is made anywhere in this repository. Where the record supports a first, it
says **"one of the first"**; where it does not, it says nothing. Specifically: reading this
container, rewriting it by hand, and editing the save were all done publicly by others before
this project started, and saying otherwise would be false. What is arguably new here is a
*general-purpose repacker whose round trip is verified over all 12,298 entries and published
with criteria a stranger can re-run* — and "arguably" is deliberate.

---

## 8 · Figures that were retired

Each row is a claim that was published or circulated and later failed to reproduce. The
correction, not the original, is what the rest of the repository uses.

| Retired figure | Replaced by | How it was caught |
|---|---|---|
| "70 of 74 save objects resolve to a name; 4 have no row in `#983`" | **74 of 74** | The reader took the first two bytes of the record as a `u16` instead of `u32 & 0x1FFF`: four records carry variant bits, which became impossible ids. The upper bits were the bug, not the data. |
| "301 objects with no name" | **21** | Artefact of a 3-id offset: the field stores `id - 3`. |
| "The 69 objects resolve to their name in Spanish" | *withdrawn* | The mapping resolved the right count and every id shifted by one position. |
| "1,848 failed checks when `blockSize` is hard-coded to 0x10000" | **122 over 81 records** | The probe aborted on a zlib error instead of counting to the end. |
| "First to read / rewrite the container; first save editor" | *all withdrawn — false* | Both were done publicly on 10-31, before this project existed. |
| "Entry with `rawSize = 0`: 2,505" vs "empty entries: 2,505" | **2,505 with `packedSize = 0`**; 2,506 with `rawSize = 0` | Two different metrics wearing one word. |
| "Test suite: 75 passed" | **78 passed, 1 skipped** | Three guards were added afterwards; a count that moves is announced, not adjusted in silence. |

The pattern behind every row is the same: a figure was trusted because it *looked* reproduced.
The rule that came out of it is now enforced — a number that leaves this repository is
re-measured in the session that publishes it.

---

## 9 · How to verify this document

A stranger with their own copy of the supported build can check the load-bearing claims in a few
minutes:

```bash
python pkp.py info          # 12,298 entries, flags {0: 4169, 1: 8129}, 0 problems, md5 of both files
python pkp.py repack build/rt --recompress    # must print IDENTICO for both files
python run-tests.py         # 78 passed, 1 skipped, on Python 3.11 with zlib 1.3.2
```

`repack` is the one that matters: it is the claim that this project's writer reproduces the
build rather than merely producing something plausible.

---

## 10 · Contact and corrections

Corrections are welcome and are the fastest way to earn credit here: an issue with a command and
its output beats a paragraph of disagreement. Where a figure of ours does not reproduce, it gets
retired in the next commit and listed in §8 with your name on it, if you want it there.
