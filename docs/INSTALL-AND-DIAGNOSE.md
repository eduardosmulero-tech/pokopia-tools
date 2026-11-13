# Install, uninstall and diagnose an overlay mod

**What this is:** the overlay flow. A mod is a **folder**; installing it means putting it
where the game looks first, and uninstalling means taking it away. **The `RomFS.img` is never
touched**, nothing is repacked, and the game files keep their hashes.

**Why that works** `[measured]`: the runtime reads `DM_ROMFS_OVERLAY`, a list of folders
separated by `:`, and consults them **before** the `RomFS.img` for every `rom:/…` path,
falling back to the `img` when the file is in none of them. The same binary and the same save
open `image entry 29` without the variable, a host descriptor (`fd 5`) when the file is in the
folder, and entry 29 again after removing it (measurement `t_88d29217`, in the development
tree's `informes/`; the transcript is not part of the published kit).

You need: a mod built as in [MAKE-A-MOD.md](MAKE-A-MOD.md), your `RomFS.img`, and a runtime
that honours `DM_ROMFS_OVERLAY`. This page does not launch the game for you.

---

## 1. Install

```bash
python pkp.py mod install build/pkmod/ejemplo-overlay-0.1.0.pkmod \
    --overlay build/overlay --crear --img <RomFS.img>
```

```
mod: ejemplo-overlay@0.1.0  ->  …/build/overlay/mods/ejemplo-overlay
  cubre          23 B  sha256 66b4b919021f…  motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx
servido: motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx -> overlay ejemplo-overlay
DM_ROMFS_OVERLAY=…/build/overlay/mods/ejemplo-overlay
relativo al cwd: build/overlay/mods/ejemplo-overlay
```

What it did, in order:

1. checked the package: manifest valid, file size and `sha256` equal to the ones recorded at
   pack time;
2. copied the file to `<store>/mods/<mod>/<romfs path>`, **not** into the `img`;
3. wrote `<store>/installed.json` (what is installed, in which order, and the `sha256` of the
   original it covers);
4. printed the value of `DM_ROMFS_OVERLAY` the game needs, in absolute form (for reference) and
   relative to the current folder — or, when the store and the folder are on different Windows
   drives, the fact that no relative-to-cwd form exists **and one instruction**: set the value
   relative to the store root and start the game from there (§2).

The store looks like this:

```
build/overlay/
  installed.json
  mods/ejemplo-overlay/motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx
```

One folder per mod, so uninstalling one can never delete a file another mod put there.

> **What the example replaces.** `motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx` is a path the
> runtime opens **while it boots** (`image entry 29` in the harness trace of `t_88d29217`), and the
> 23 bytes the example writes are not a valid replacement. Use it to walk the flow, but **do not
> launch the game with it installed**: uninstall it first (§4), or point your own mod at a path the
> game reads later. [MAKE-A-MOD.md](MAKE-A-MOD.md) §3 says the payload is not an asset.

`install` refuses to run — before writing anything — if the runtime process (`nxrt`) is
running, if the `img` is held open, if the store is inside the game's dump, or if the store
does not exist and `--crear` was not given. A refused `install --crear` does not even leave the
store folder behind. Close the game yourself; this kit never closes it.

---

## 2. Launch the game with the variable

`DM_ROMFS_OVERLAY` is the list of mod folders, in priority order:

```bash
export DM_ROMFS_OVERLAY=build/overlay/mods/ejemplo-overlay     # sh / bash
```
```bat
set DM_ROMFS_OVERLAY=build\overlay\mods\ejemplo-overlay        :: cmd.exe
```
```powershell
$env:DM_ROMFS_OVERLAY = "build\overlay\mods\ejemplo-overlay"   # PowerShell
```

Two rules that come from the runtime, not from this kit:

* **The relative form depends on the folder you launch from.** `install` prints both forms;
  the relative one is correct only if the game starts with that folder as its working
  directory.
* **On Windows, never use the absolute form**: the runtime splits the variable on `:` and a
  path that starts with a drive letter is cut in two (the letter, then the rest), which only
  works by accident when the whole store is on the current drive. `doctor` flags this case
  explicitly (`overlay.trampa_dos_puntos`).

**When the store lives on another drive than the folder you launch from**, Windows cannot
express the relative-to-cwd form at all: `install`, `status` and `doctor` say so and give the
form that always works — the one relative to the **store root** (`mods\<mod>`, no `:` in it) —
together with the folder the game has to start in. The store path is shortened to `<store>`
here; the command prints it in full:

```
relativo al cwd: (no hay forma relativa al cwd: el almacen esta en D: y el cwd en C:)
aviso: el almacen esta en D: y el cwd en C: — el runtime trocea DM_ROMFS_OVERLAY por ':' y una
ruta absoluta no vale; pon DM_ROMFS_OVERLAY=mods\demo (relativa a la raiz del almacen) y
arranca el juego con el cwd en <store>
```

So, with the store at `<store>`:

```bat
cd /d <store>
set DM_ROMFS_OVERLAY=mods\demo
```

One instruction, and it does not ask for an absolute path nor for a relative-to-cwd form that
does not exist. `doctor` repeats it as `aviso overlay.separador`.

---

## 3. Check what the game will see, without launching it

```bash
python pkp.py mod status --overlay build/overlay --img <RomFS.img>
```

```
almacen: …/build/overlay
0. ejemplo-overlay@0.1.0  (1 fichero(s), instalado 2026-11-09T00:04:58Z)
           23 B  motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx  sirve: overlay
conflictos: ninguno
DM_ROMFS_OVERLAY=…/build/overlay/mods/ejemplo-overlay
relativo al cwd: build/overlay/mods/ejemplo-overlay
```

`sirve: overlay` is the answer to "who wins this path": the runtime searches the folders in
`DM_ROMFS_OVERLAY` order first and falls back to the `img`. `status` also works per file:
`sirve: img entrada N` means that path still comes from the image.

At the file level, the proof is a hash: the file in `build/overlay/mods/ejemplo-overlay/…`
has the `sha256` you packed, and the `img` keeps its own (compare with `sha256sum` before and
after the whole cycle).

---

## 4. Uninstall

```bash
python pkp.py mod uninstall ejemplo-overlay --overlay build/overlay --img <RomFS.img>
```

```
mod: ejemplo-overlay  (1 fichero(s))
  original restaurado motor_asset_re/KIDS_PLATFORM_OUNCE/system.rdx
                 img entrada 5, sha256 05784a71f65e…
restaurados: 1  sombreados por otro mod: 0  sin original: 0
resultado: OK
```

`uninstall` does not say "I think I removed it": for every file it reports what the romfs
serves now and compares the `sha256` with the original recorded at pack time.

| Column | Meaning |
|---|---|
| `restaurados` | the file is gone from the overlay and the `img` serves the original again |
| `sombreados` | another installed mod still covers that path; the original is not back yet |
| `sin original` | the mod added a path the `img` does not have, so there is nothing to restore |

It **refuses** (non-zero exit) when the overlay file was modified after installing, when the
`img` no longer serves the recorded original, or when it cannot verify at all because no
`--img` was given. `--sin-verificar` exists to record that nothing was checked; it is not a
success.

Like `install`, it also refuses **while the runtime process (`nxrt`) is running**: same
`ERROR … el runtime del juego esta en marcha`, non-zero exit, nothing written. It never closes the
game for you — close it and run the command again. `--forzar` skips that guard; it is for synthetic
stores and tests, not for the store the game is using.

---

## 5. Doctor: why a mod does not load

```bash
python pkp.py mod doctor --overlay build/overlay --img <RomFS.img>
```

`doctor` reads the registry, the overlay tree and the `img`. It **does not start the game**,
does not list processes and writes nothing. Each line is one check: `ok`, `aviso` (worth
looking at, does not block) or `FALLO` (a cause that stops the mod from loading). Exit code is
`0` when there is no `FALLO`, non-zero otherwise. The last line closes the run with
`resultado: sano`, `resultado: sano con avisos` or `resultado: FALLIDO`, plus the counts.

### The causes it recognises, with its literal message

Every line below is copied from the transcript `tools/demo_doctor.py` prints (that script
ships with the development tree, not with the published kit; run `python tools/demo_doctor.py`
to regenerate it): it builds a synthetic `DMROMFS1` image and a mod with our own bytes, then
breaks it on purpose, one cause at a time. Paths are shortened to `<path>`.

| # | What was broken | Message |
|---|---|---|
| 1 | the overlay file is missing | `FALLO mod.demo.<path> falta en el overlay: el juego sirve el original del img` |
| 2 | the overlay bytes are not the installed ones | `FALLO mod.demo.<path> el fichero del overlay no es el que se instalo (sha256 f5797539e31a…)` |
| 3 | the mod declares a format this kit cannot read | `FALLO mod.demo.formato mod_format 2 no soportado: este kit solo carga 1` |
| 4 | the `img` is another build | `FALLO mod.demo.img el img es otro build: al instalar era 328 B / huella 5d8ba7ebdb5d… y ahora es 345 B / huella 2639627c2399…; el mod se hizo para el otro` |
| 4b | the container is another build | `FALLO mod.demo.juego el mod se hizo para 2.0.1a@demo y tu contenedor es otro build (LD_C0_R.BIN esperaba 000000000000… y tienes e3ea360555da…, …): pide el mod para tu version o quitalo` |
| 4c | the same, with the container `PKP_ROMFS` points at instead of `--container` | `aviso mod.demo.juego el mod se hizo para 2.0.1a@demo y tu contenedor es otro build (LD_C0_R.BIN esperaba 000000000000… y tienes e3ea360555da…, …): pide el mod para tu version o quitalo; se compara contra el contenedor del entorno (PKP_ROMFS), que puede ser otro dump: si es el tuyo, repite con --container` |
| 5 | two mods cover the same path | `aviso mods.sin_conflictos <path> lo sirven demo y otro (gana demo, bytes distintos)` |
| 6 | `DM_ROMFS_OVERLAY` does not point at the store | `FALLO overlay.variable DM_ROMFS_OVERLAY vale '<otra carpeta>' y el almacen sirve desde '<store>/mods/demo:…': el juego no cargara <store>/mods/demo; usa <store-rel> (relativa al cwd) y arranca el juego con el cwd en <cwd>` |
| 7 | a path that the `img` does not have (a typo) | `aviso mod.mala.<ruta con errata>.ruta la ruta no esta en el img: o es nueva a proposito, o esta mal escrita (mayusculas, separadores o nombre); el juego solo pide las rutas que existen` |
| 7b | `DM_ROMFS_OVERLAY` with Windows absolute paths, same drive | `aviso overlay.trampa_dos_puntos DM_ROMFS_OVERLAY trae una ruta absoluta de Windows (<path>:<path>): el runtime la trocea por ':' y solo funciona por casualidad cuando el almacen cae en la unidad del cwd; usa <rel> (relativa al cwd) y arranca el juego con el cwd en <cwd>` |
| 7c | the store is on another drive than the folder you run from | `aviso overlay.separador el almacen esta en D: y el cwd en C: — el runtime trocea DM_ROMFS_OVERLAY por ':' y una ruta absoluta no vale; pon DM_ROMFS_OVERLAY=mods\demo (relativa a la raiz del almacen) y arranca el juego con el cwd en <store>` |

Reading the names: `mod.<mod>.<path>` is the check of one installed file; `mod.<mod>.formato`,
`.juego` and `.img` are the mod-level ones; `img.<path>` compares the `img` against the
original recorded at pack time.

Which of those is a `FALLO` and which is an `aviso` — and why — is not a matter of taste:
the table is in [MOD-OVERLAY.md](MOD-OVERLAY.md) §7. The one case with two severities is
`mod.<mod>.juego`: declaring the container with `--container` makes a mismatch a `FALLO`
(you asked to validate against that build), while the container `PKP_ROMFS` points at makes
it an `aviso` (exit 0), because that default may be another dump and the overlay still
loads by path.

### What each cause means and what to do

| Message | Cause | What to do |
|---|---|---|
| `falta en el overlay` | the file was deleted, renamed or never copied | `mod install` again from the package |
| `no es el que se instalo` | something edited the overlay file after installing | reinstall; if the change is yours, `pack` and install the new version |
| `mod_format N no soportado` | the store was written by a newer kit | use that kit, or rebuild the mod for `mod_format: 1` |
| `el img es otro build` | you are pointing at a different `RomFS.img` | use the image the mod was packed against, or repack for this one |
| `tu contenedor es otro build` | your `LD_C0_R.BIN`/`LI_C0_R.IDX` are another version | rebuild the mod against your copy |
| `lo sirven X y Y` | two mods replace the same path | keep one; the first in `DM_ROMFS_OVERLAY` wins |
| `DM_ROMFS_OVERLAY vale …` | the game is started with a different list, or with an absolute Windows path | start the game with the line `install` prints; see §2 |
| `trae una ruta absoluta de Windows` | you exported `C:\...` instead of the relative form | it works only while the store sits on the drive you launch from; use the relative line `install` prints |
| `el almacen esta en D: y el cwd en C:` | the store is on another drive, so there is no relative-to-cwd form | set the store-relative value and start the game from the store root, exactly as the line says (§2) |
| `la ruta no esta en el img` | the manifest path has a typo, or the file really is new | fix the path; if the path is new on purpose, the warning is expected |
| `el img cambio: esperaba … y sirve …` | the image content at that path changed | the mod covers a different build; repack |

## 6. Two mods on the same file: who wins

`DM_ROMFS_OVERLAY` is ordered. The first folder that has the path wins and the rest are never
consulted for it. `status` shows it per path and `doctor` counts it as an `aviso` (not a
failure: a conflict is a choice, not corruption).

* `install --primero` puts the new mod at the front of the list.
* `uninstall` of the winning mod does **not** claim victory: the other mod still covers the
  path, so the file is reported as `sombreado` and the original only comes back when the last
  mod covering it is uninstalled.

## 7. Leave the game exactly as it was

```bash
# with the game closed (§4)
python pkp.py mod uninstall <each-mod> --overlay build/overlay --img <RomFS.img>
python pkp.py mod doctor --overlay build/overlay --img <RomFS.img>   # 0 mod(s), sin FALLO
```

Then compare the image's hash with the one you had before installing (`sha256sum` or
`certutil -hashfile`): nothing in this flow writes to it, so it must be identical. The store
folder can then be deleted; `doctor`'s `almacen.sin_sobras` check exists precisely to catch
folders left behind outside the registry, which the game would still serve.

## 8. What this page does not promise

* **`doctor` does not launch the game.** It diagnoses the installation: files, hashes, format,
  build identity, variable, conflicts. Whether the engine *accepts* your asset (a `G1T`, a
  bank) is the asset format's business, not the flow's.
* **Data-only mods are not overlay mods.** `edits[]`/`text[]` are applied to a **copy** of the
  container with `pkp mod apply`; the overlay replaces whole files. A data mod reaches the game
  as a replaced container file, `romfs[] = [{"path": "LD_C0_R.BIN", …}]`.
* **One build is supported** (game 2.0.1a, update 655360). Another build may work; `doctor`
  says when the `img` or the container is not the one the mod was packed for.
