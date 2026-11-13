# Installing and removing a mod: the overlay flow

**What this is:** `pkp mod pack` / `install` / `uninstall` / `status` / `doctor` on top of the
native runtime's **overlay**. A mod is a **folder**; installing it means putting it where the game
looks first, and removing it means taking it away. The `RomFS.img` is never touched.

**Tutorials:** [MAKE-A-MOD.md](MAKE-A-MOD.md) takes you from your own file to a package;
[INSTALL-AND-DIAGNOSE.md](INSTALL-AND-DIAGNOSE.md) covers install, uninstall and every cause
`doctor` reports. This page is the reference behind both.

**Why nothing has to be repacked** `[measured]`: the runtime reads `DM_ROMFS_OVERLAY`, a list of
folders separated by `:` that it consults **before** the `RomFS.img` for every `rom:/…`, falling
back to the `img` when the file is in none of them. Same binary, same save: without the overlay the
game opens `image entry 29`; with the file in the folder it opens a host descriptor (`fd 5`); after
removing it, back to entry 29 with the `img` untouched
(`informes/t_88d29217/MOD-LOADER-NATIVO.md`, development tree only).

---

## 1. The store: one folder per mod

```
<store>/
  installed.json      registry: which mods, in which order, and what each one put there
  mods/<mod>/         the mod's tree, with the romfs paths as they are
  mods/<mod>/<path>   e.g. mods/texture-demo/LD_C0_R.BIN
```

One folder per mod rather than a shared folder, for two reasons:

* removing a mod deletes **its** folder: it cannot take away a file another mod put there;
* two mods overriding the same path are a **visible conflict** (`status` reports it, `doctor`
  counts it). The one earlier in `DM_ROMFS_OVERLAY` wins, which is exactly the runtime's rule.

The list handed to the runtime is the list of mod folders, in install order:

```
DM_ROMFS_OVERLAY=<store>/mods/texture-demo:<store>/mods/audio-demo
```

---

## 2. Three steps

```bash
# 1 · pack the working folder (optional: install accepts the folder as-is)
python pkp.py mod pack my-mod -o build/pkmod --img <RomFS.img>

# 2 · install into the overlay store (the img is not touched)
python pkp.py mod install build/pkmod/my-mod-0.1.0.pkmod \
    --overlay <store> --crear --img <RomFS.img>

# 3 · launch the game with the variable set (install and status print it)
export DM_ROMFS_OVERLAY=<store>/mods/my-mod     # PowerShell: $env:DM_ROMFS_OVERLAY = "…"
```

List and remove:

```bash
python pkp.py mod status    --overlay <store> --img <RomFS.img>
python pkp.py mod uninstall my-mod --overlay <store> --img <RomFS.img>
python pkp.py mod doctor    --overlay <store> --img <RomFS.img>
```

`uninstall` **never says "I think I removed it"**: for every file it prints what the romfs serves
now and compares the `sha256` against the original recorded at pack time. Without `--img` it cannot
prove it and refuses (unless `--sin-verificar` is given, which records that nothing was checked).

---

## 3. The manifest: one more section, `romfs[]`

Same manifest as always (`docs/MOD-FORMAT.md`); an installable mod adds one section:

```json
{
  "mod_format": 1,
  "name": "my-texture",
  "version": "0.1.0",
  "authors": ["me"],
  "game": {"title": "pokopia", "version": "2.0.1a", "container_md5": {"LD_C0_R.BIN": "…", "LI_C0_R.IDX": "…"}},
  "edits": [], "text": [], "files": [],
  "romfs": [
    {
      "path": "LD_C0_R.BIN",
      "file": "payload/LD_C0_R.BIN",
      "why": "container with texture #5879 replaced",
      "size": 237186304,
      "sha256": "…(pack fills this)…",
      "original_sha256": "…(pack fills this from the img)…"
    }
  ]
}
```

| Field | Mandatory | What it means |
|---|---|---|
| `path` | yes | path inside the romfs, relative and `/`-separated. No root, no `..`, no drive. |
| `file` | yes | file inside the mod (same path rule). |
| `why` | yes | which romfs file you replace and why. |
| `size`, `sha256` | no | filled by `pack`; when present, `install` checks them before copying. |
| `original_sha256` | no | `sha256` of what the `img` serves today at `path`; `pack --img` fills it and it is what proves the original comes back after uninstall. `null` for a new path. |

A mod **without** `romfs[]` is still valid and is applied with `pkp mod apply` as before: the
approved data mods (`t_5f0dbae7`, `t_f2665f94`) validate unchanged.

`romfs[]` is not composable with `merge`: `pkp mod merge` rejects it and says what to do instead
(install both mods and let the variable's order decide).

---

## 4. Where a texture or a sound goes (important)

This game has **no loose textures or audio in the romfs**: the 52 nodes of the `img` are
`LD_C0_R.BIN` + `LI_C0_R.IDX`, 24 `.fdata`, 2 `.webm` and the `root/system.rdb/.rdx` indexes. The
55 `G1T` textures live inside the container (entries #5879–#5948) and audio in `ASRS/KTSR` banks.
Since the overlay replaces **whole files**, a texture or audio mod replaces the file that contains
them:

```
texture:  pkp tex …                      -> modified LD_C0_R.BIN (or the .fdata)
audio:    pkp snd replace …              -> the bank inside the container / .fdata
                 ↓
          romfs[] = [{"path": "LD_C0_R.BIN", "file": "payload/LD_C0_R.BIN", …}]
```

Operational consequence: a texture mod's payload is the **247 MB** of `LD_C0_R.BIN` (measured: the
full cycle from `install` to verified `uninstall` takes seconds and never copies the `img`).

---

## 5. What this flow does not do

* **It does not write to the `RomFS.img`** or the dump: the `img` is opened read-only, and only to
  hash what it serves.
* **It does not launch the game**: `install`/`uninstall` refuse if the runtime (`nxrt`) is running
  or the `img` is held open; installing while the game runs leaves the overlay half-done.
* **It does not validate that the engine loads the asset**: it checks which file is served and that
  the original comes back. Whether the game accepts a given `G1T` is the `G1T`'s business
  (`docs/G1T-FORMAT.md`).
* **It does not publish game content**: a `.pkmod` carrying `LD_C0_R.BIN` **is** game content; it
  does not go into the repository (`docs/NORMA-CONTENIDO-Y-PUBLICACION.md`).

---

## 6. Measured trap: the `:` in the variable on Windows

The runtime splits `DM_ROMFS_OVERLAY` on `:` — on Windows too. An absolute path that starts
with a drive letter is split at the colon into the letter and the rest; the second part
resolves against the current drive, so it **works by accident when everything is on the same
drive** and is silently ignored when the store lives on another drive. `install` and `status`
print both the absolute line and the one relative to the cwd, and warn when the store's drive
is not the cwd's. In that case there is no relative-to-cwd form at all, so the warning gives
**one** instruction instead: the value relative to the store root (`mods/<mod>`, no `:` in it)
and the folder the game must start in. If the game does not see the mod, compare those lines
and the `doctor` checks `overlay.variable` / `overlay.trampa_dos_puntos` / `overlay.separador`
before looking anywhere else.

---

## 7. `doctor`: what is fatal and what is only a warning

`doctor` answers one question: **will the game load, from this store, what the registry says?**
Every line it prints is one check, and each check has a fixed severity.

| Severity | Rule |
|---|---|
| `FALLO` (`fatal: true`) | the game will not load what the store promises, or the store cannot be used at all: no store, a store inside the game's dump, an unreadable registry, an installed mod whose folder or file is gone, bytes that are not the installed ones, a `mod_format` this kit cannot read, an `img` that is not the build the store was installed against, or a `DM_ROMFS_OVERLAY` that does not point at the store. |
| `aviso` (`fatal: false`) | something worth fixing that does not, on its own, stop the mod from loading — **or** a check `doctor` cannot make in this run. |

The exit code is `0` when there is no `FALLO`, warnings included, and non-zero otherwise.

| Check | Severity | Why |
|---|---|---|
| `almacen.existe` | `FALLO` | there is no overlay to mount |
| `almacen.protegido` | `FALLO` | a store inside the game's dump would be written on the dump |
| `registro.legible` | `FALLO` | without the registry, `doctor` does not know what should be there |
| `mod.<mod>.carpeta` | `FALLO` | the mod is registered and its folder is gone: the game sees none of its files |
| `mod.<mod>.formato` | `FALLO` | a `mod_format` the runtime does not read |
| `mod.<mod>.<path>` missing | `FALLO` | the registry says that mod serves that path and it is not there |
| `mod.<mod>.<path>` different hash | `FALLO` | those are not the bytes that were installed |
| `img.<path>` | `FALLO` | the `img` no longer serves the original the registry recorded |
| `mod.<mod>.img` | `FALLO` | the image fingerprint is written **by `install` in this store**: if it does not match, the store belongs to another image and every `sha256`/`original_sha256` it records refers to another tree |
| `mod.<mod>.<path>.ruta` | `aviso` | the path is either new on purpose or a typo; the game only asks for paths that exist |
| `almacen.sin_sobras` | `aviso` | a folder outside the registry (the game would still serve it) |
| `mods.sin_conflictos` | `aviso` | two mods replace the same path: the first one in `DM_ROMFS_OVERLAY` wins, which is a choice, not corruption |
| `overlay.variable` | `FALLO` | the game is started with a list that does not include the store, so no mod loads |
| `overlay.trampa_dos_puntos` | `aviso` | an absolute Windows path in the variable; it works only while store and game sit on the same drive |
| `overlay.separador` | `aviso` | the store is on another drive: use the form relative to the store root (§6) |
| `img.comprobado` | `aviso` | no `--img`: nothing was compared against the image |
| `mod.<mod>.juego` | `FALLO` / `aviso` | see next section |

### `mod.<mod>.juego`: one finding, two severities

The `container_md5` in the manifest is written by the **mod author**: it says which build of
the game the mod was made for. Whether a mismatch is fatal depends on which container
`doctor` was asked to validate against:

* `--container <folder>`: you are declaring *that* container as the game you are going to
  run, so a mod made for another build is a `FALLO` (non-zero exit);
* `PKP_ROMFS` (the kit's default container, the one every command uses): the same mismatch
  is an `aviso` (exit 0), because that default may be another dump than the one you play
  with and the overlay still loads by path. The line says so and suggests repeating with
  `--container`;
* neither: the check is not made, and that is reported as an `aviso`.

This was a measured defect (2026-11-10): `doctor` resolved `PKP_ROMFS` on its own, so a store
validated against its own synthetic image — the way the suite does it — was compared against
whatever container the environment pointed at and came out `FALLO`. `overlay.doctor()` no
longer reads the environment: the CLI is the one that resolves both references and passes
them in (`container` = declared, `container_entorno` = default).
