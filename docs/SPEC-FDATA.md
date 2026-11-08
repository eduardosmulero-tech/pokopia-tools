# Specification — `.fdata` archives (`PDRK`/`IDRK`)

The RomFS of the supported build carries **24 `.fdata` archives** that hold most of the game's
structured data: scenes, skeletons, textures, animation, audio banks, object databases. They are
**not** part of `LD_C0_R.BIN`; they sit next to it as separate files.

This document describes the container: its two magics, the entry header, how payloads are
compressed and how to walk 79,710 entries without guessing. It says nothing about what any entry
contains; that is each format's own document.

Everything below was measured on the supported build (see the md5 values in the
[README](../README.md#supported-build)). The reproducing command is at the end.

---

## 1. The numbers

```
$ pkp fdata stat <your romfs>
ficheros  : 24 .fdata, 5063190412 B
entradas  : 79710
```

| Figure | Value |
|---|---|
| `.fdata` archives | **24** |
| Total bytes of the 24 archives | **5,063,190,412 B** (4.72 GiB) |
| Entries across all of them | **79,710** |
| Distinct `type_ktid` values | **25** |
| Largest archive | 2,560,389,883 B, **25,023 entries** |
| Time to walk every header (no decompression) | **~0.6 s** |

All 24 start with the `PDRK0000` magic and live under one `motor_asset_re/` tree (plus two
`MountPoint_*` folders). The file name is a **hash**: nothing in the RomFS maps an archive back to
a readable name.

### Entries per type

| `type_ktid` | Name | Entries | Compressed |
|---|---|---:|---:|
| `0x7bcd279f` | `g1s` | 26,137 | 26,137 |
| `0x6fa91671` | `g1a` | 17,457 | 17,457 |
| `0xafbec60c` | `g1t` | 14,412 | 14,412 |
| `0x8e39aa37` | `ktid` | 5,554 | 5,517 |
| `0xf20de437` | `texinfo` | 4,341 | 4,341 |
| `0x20a6a0bb` | `kidsobjdb` | 4,144 | 4,144 |
| `0x563bdef1` | `g1m` | 3,204 | 3,204 |
| `0xb340861a` | `mtl` | 1,531 | 1,505 |
| `0xb097d41f` | `g1e` | 1,173 | 1,173 |
| `0x1ab40ae8` | `oid` | 581 | 576 |
| `0xbbd39f2d` | `srsa` | 403 | 403 |
| `0x5599aa51` | `kscl` | 361 | 361 |
| `0x56efe45c` | `grp` | 323 | 268 |
| `0xed410290` | `kts` | 31 | 31 |
| `0xb1630f51` | `kidsrender` | 18 | 18 |
| `0x133d2c3b` | `sid` | 17 | 17 |
| `0x786dcd84` | `g1n` | 6 | 6 |
| `0xd7f47fb1` | `efpl` | 5 | 5 |
| `0x27bc54b7` | `rigbin` | 3 | 3 |
| `0x4d0102ac` | `g1em` | 2 | 2 |
| `0x54738c76` | `g1co` | 2 | 2 |
| `0x5c3e543c` | `swg` | 2 | 2 |
| `0x1fdcaa40` | `kidstask` | 1 | 1 |
| `0x6dbd6ea6` | `mit` | 1 | 1 |
| `0xb0a14534` | `sgcbin` | 1 | 1 |
| | **total** | **79,710** | **79,587** |

The column sums to 79,710 exactly, which is the point of publishing it: a walk that does not add
up to that number has skipped or double-counted an entry.

**Raw entries exist.** `ktid` has 37 uncompressed entries, `mtl` 26, `oid` 5 and `grp` 55; the
other types are compressed in full. An entry declares this itself (see §3), so no table of
exceptions is needed.

---

## 2. Archive header (16 B)

```
+0x00   char[8]  PDRK0000     magic
+0x08   u32      0x10         header size (16)
+0x0C   u32      0            reserved
```

Entries are **concatenated from `0x10`** and each one starts on a **16-byte boundary**. The gap
between the end of an entry and the next boundary is padding whose content is not significant.

---

## 3. Entry header

Each entry is `IDRK0000` + 48 bytes of fixed fields + a variable metadata region + the payload:

| Offset | Type | Field | Notes |
|---|---|---|---|
| `+0x00` | `char[8]` | `IDRK0000` | magic |
| `+0x08` | `u64` | `entry_size` | **total size of the entry**, including this header |
| `+0x10` | `u64` | `compressed_size` | bytes of the payload region as stored |
| `+0x18` | `u64` | `uncompressed_size` | bytes of payload after decompression |
| `+0x20` | `u32` | `entry_type` | per-archive identifier; not the type |
| `+0x24` | `u32` | `name_hash` | hash of the asset name (see §6) |
| `+0x28` | `u32` | `type_ktid` | **the type**, the column of §1 |
| `+0x2C` | `u32` | `flags` | `0x00100000` selects the "FETH" chunk framing (§4) |
| `+0x30` | — | metadata | `entry_size − compressed_size − 0x30` bytes |
| … | — | payload | `compressed_size` bytes |

**The three sizes are `u64`.** This is the trap that costs an hour: read as `u32` you get the low
half followed by four zero bytes, the 10-byte chunk field of §4 falls out of phase, and nothing
decompresses. There is a test in `tests/test_fdata.py` that fixes the layout with an entry that
declares more than 4 GiB.

`entry_size` is `0x30 + metadata_size + compressed_size`; an entry whose payload is stored raw
has `compressed_size == uncompressed_size` and no chunk framing at all (§4).

---

## 4. Payload compression

If `compressed_size == uncompressed_size`, the payload is **stored raw** and copied as-is.

Otherwise the payload is a sequence of **zlib streams, back to back**, read until
`uncompressed_size` bytes have been produced. Each chunk is preceded by its compressed length:

| `flags & 0x00100000` | Length field | Payload starts at |
|---|---|---|
| clear (the normal case here) | `u16 zsize` then **6 bytes** (a `u64` slot used as padding) | `+8` after the length |
| set ("FETH" framing) | `u32 zsize` | `+4` after the length |

```python
pos = 0
while produced < uncompressed_size:
    if flags & 0x00100000:
        zsize = u32(payload, pos); pos += 4
    else:
        zsize = u16(payload, pos); pos += 10       # u16 + 6 bytes
    out += zlib.decompress(payload[pos:pos + zsize])
    pos += zsize
```

There is no per-chunk output size in either framing: the chunk ends where zlib says it ends. A
walker that trusts `zsize` alone, or that assumes the 10-byte form, desynchronises on the first
archive whose entries use the other one.

The data is **not encrypted**: measured entropy is 5.0–7.8 bits/byte and it varies entry by
entry, which is what zlib over structured data looks like.

---

## 5. The two sibling formats

Two other extensions use the *entry* layout of §3 but not the archive wrapper:

| File | Wrapper | Content |
|---|---|---|
| `*.file` (4 files, 1,421,073,776 B total) | **none**: a bare sequence of `IDRK0000` entries | uncompressed `srst` audio |
| `*.rdb` (`root.rdb` 5,752,340 B, `system.rdb` 1,832,428 B) | `_DRK0000` + 32 B header + entries | the **master index** of every asset |

`root.rdb` walks to **60,722 entries** and the final offset lands exactly on the end of the file
(`0x57C614` of `0x57C614`), with 26 distinct types. Each entry is 52 B: `IDRK0000`, `u32 version`,
`<3Q>` (`entry_size`, `string_size`, `file_size`), `<4I>` (`entry_type`, `file_hash`, `type_ktid`,
`flags`).

**There are no readable names anywhere in this index.** `string_size` is 13 on every entry and the
bytes it covers are not ASCII; the hashes are sequential ids, not CRCs of a name. So "where is
asset X" is answerable only if you already know X's hash. That is a naming wall, not a format
wall, and it is not solved here.

The `.file` and `.rdb` layouts above were measured on the dump; **the kit has no command for
them** in this version. `pkp fdata` walks the 24 archives and nothing else.

---

## 6. What the kit does with this

```
pkp fdata list    <archive.fdata | folder>        # one line per entry: offset, type, sizes, hash, flags
pkp fdata stat    <romfs>                         # entries per type across every archive
pkp fdata extract <archive> --type g1t --out DIR  # decompress one type as <name_hash>.<type>
```

`extract` writes `<name_hash>.<type>` and **refuses to write inside the RomFS**
(`paths.guard_writable`), like every other write command in the kit.

**Reading only.** There is no writer for `.fdata` in this version: an entry can be decompressed,
modified in memory and re-compressed, but putting it back into the archive is not implemented
(`FUTURO.md`), which is why a modified texture or sound bank stops at a file in `build/`.

---

## 7. Provenance

The layout is documented by the community and was cross-checked against the dump; no code was
copied:

* `eArmada8/yumia_fdata_tools` — `yumia_mod_lib.py`, `read_fdata_file` and
  `read_fdata_for_idrk_information` (the type table).
* `bnnm/vgm-tools` — `koei_rdb_fdata_file.bms` (the `.file`/`.rdb` variants).
* `DeathChaos25/fdata_dump`.
* `umin135/katanaDOCS`.

The type names (`g1s`, `g1t`, …) come from that published table; the counts, the 25 types, the
two chunk framings and the `u64` sizes were re-measured here.

---

## 8. Reproduce it

```
export PKP_ROMFS=<folder with your LD_C0_R.BIN and LI_C0_R.IDX>
python pkp.py fdata stat "$PKP_ROMFS"
python pkp.py fdata list "$PKP_ROMFS/motor_asset_re"/*/*.fdata
```

The first command prints the 25 rows of §1; the entry count on its `entradas` line must be
**79,710** on the supported build.
