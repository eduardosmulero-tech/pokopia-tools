# Quickstart — 30 seconds to your first applied mod

Written for someone who has never seen this repository. The transcripts below are real output
on the supported build, with paths replaced by placeholders. Where a step's output depends on
your own machine or clock — the backup folder name, the undo commands, the new md5 — it is
described rather than quoted.

You need: **your own legally obtained game files** (the folder that contains `LD_C0_R.BIN` and
`LI_C0_R.IDX`), and **Python 3.11**. Nothing else — no .NET, no compiler, no internet. The pixel
commands (`pkp tex extract`, `pkp tex inject --png`) additionally want `numpy`, `imagecodecs` and
`etcpak`; every other command runs on the standard library.

> CLI output is in Spanish in version 0.2.0. The interface that matters is the numbers and the
> exit code (`0` ok, `1` invalid, `2` usage error); every term is translated in
> [GLOSSARY.md](GLOSSARY.md).

---

## 1 · Point the kit at your files

```bash
git clone https://github.com/eduardosmulero-tech/pokopia-tools
cd pokopia-tools

export PKP_ROMFS="/path/to/your/romfs"     # Windows: set PKP_ROMFS=C:\path\to\romfs
```

If you skip this, the kit looks in `./romfs`, relative to the folder you run it from — which will
not exist on your machine — and every command fails with exit code `2` and
`no encuentro LD_C0_R.BIN en ...`. That message means exactly one thing: neither `PKP_ROMFS` nor
`--container` is pointing at the folder that holds both files.

## 2 · Look at what you have (read-only)

```bash
python pkp.py info
```

Real output on the supported build:

```
contenedor : C:\...\your romfs
  LD_C0_R.BIN  247317504 B  md5 358a672d506ce2b0399149ede64a6760
  LI_C0_R.IDX  393536 B  md5 7e056a097f28a62f002ad961a611edf8
entradas   : 12298   flags {'0': 4169, '1': 8129}   vacias 2505
payload    : 548327864 B descomprimidos en 246615606 B empaquetados
bloques    : 8834 comprimidos, 19 crudos
problemas  : 0
tablas conocidas:
  #983 registros de 68 B                         inference
      ...
```

Compare the two md5 values with the table in the [README](../README.md#supported-build).

* **They match** → continue.
* **They do not match** → you are on a different build. Nothing in this kit is measured
  against it. Do not apply mods to it; you can still read it, and `pkp repack` will tell you
  whether the writer handles it (`IDENTICO`) or not (`DISTINTO`).
* **`problemas` is not 0** → the pair is inconsistent (a BIN from one build with an IDX from
  another, or a truncated copy). Nothing will be written; get a clean pair.

Nothing above opened a file for writing. `pkp info` is read-only, always.

## 3 · Make a working copy

```bash
mkdir -p build/copia
cp "$PKP_ROMFS/LD_C0_R.BIN" "$PKP_ROMFS/LI_C0_R.IDX" build/copia/
```

This is not bureaucracy. The kit **refuses** to write inside your dump or inside any tree
listed in `PKP_PROTECTED`, with this message:

```
ERROR: destino protegido (solo lectura): <path>
  el kit nunca escribe en el romfs del juego ni en los arboles de PKP_PROTECTED.
  copia el contenedor a una carpeta de trabajo y pasa --container <copia>.
```

## 4 · Rehearse the mod (this is the default)

```bash
python pkp.py mod apply ejemplos/editar-fila --container build/copia
```

No `--yes`, so this is a dry run. Real transcript:

```
mod: ejemplo-editar-fila@0.1.0
contenedor: C:\...\build\copia   [dry-run]
md5 antes : BIN 358a672d506ce2b0399149ede64a6760  IDX 7e056a097f28a62f002ad961a611edf8
tabla #983: 312864 -> 312864 B  flag=1 blockSize=0x10000
  diff: 1 tramo(s), 1 byte(s)
    +90130  0xe6 -> 0xe7
  reempaquetado: ok  prefijo de texto identico: n/a
  dry-run: no se ha escrito nada
resultado: OK
```

Read the three lines that decide everything:

* `diff: 1 tramo(s), 1 byte(s)` — a one-byte change, exactly what the mod declares.
* `reempaquetado: ok` — the entry was recompressed and read back coherently.
* `md5 antes` is printed and nothing after it: in a dry run there is no "after", because
  nothing was written.

`90130` is `64 + 1324*68 + 34`: header, then the row, then the field. The arithmetic of the
container is in [GLOSSARY.md](GLOSSARY.md#2--table-geometry).

## 5 · Apply it for real

```bash
python pkp.py mod apply ejemplos/editar-fila --container build/copia --yes
```

`--yes` requires `--container`: there is no default for a write, so it cannot land in your dump
by accident. On success the run prints the **new md5 of both files**, the **backup folder**
(`<copia>/.pkp-backup/<YYYYMMDD-HHMMSS>/`) and the **two `cp` commands that undo it**,
already filled in with your paths. Copy them somewhere before you launch the game.

The write itself is atomic: bytes go to a temporary directory inside the copy, are read back,
compared against the plan, and only then replace `LD_C0_R.BIN` and `LI_C0_R.IDX`.

## 6 · Undo

Either run the two `cp` commands the tool printed, or let a backup do it:

```bash
python pkp.py mod apply ejemplos/editar-fila --container build/copia --yes   # writes
cp build/copia/.pkp-backup/<stamp>/LD_C0_R.BIN build/copia/LD_C0_R.BIN
cp build/copia/.pkp-backup/<stamp>/LI_C0_R.IDX build/copia/LI_C0_R.IDX
```

`<stamp>` is the `YYYYMMDD-HHMMSS` folder the tool printed; copy the commands it printed
instead of retyping these, and you cannot get it wrong.

Then `python pkp.py info --container build/copia` must show your original md5 again. If it
does not, you restored only one of the two files — they are a pair, and either alone is a
broken container.

For save files there is one extra step, and it is automated: `pkp save undo <backup>` checks
that the current file is the one the backup expects, and refuses to restore over a save that
the game has written since (`NO se restaura`).

## 7 · Your own mod

```bash
python pkp.py mod new mi-mod            # skeleton with your container's md5 already filled
#   edit mod.json: add entries to "edits" or "text"
python pkp.py mod validate mi-mod       # schema, ranges, md5, and every expect against your copy
python pkp.py mod apply mi-mod --container build/copia
```

`validate` is the tool that pays for itself: it compares each `expect` with the bytes actually
in your copy, and a single mismatch stops the mod with *expected / found* in hex and decimal
(the bytes themselves are never printed — a text value is identified by length and truncated
`sha256`).

To combine two mods:

```bash
python pkp.py mod merge mi-mod otro-mod -o combinado
```

Exit `0` composed (`combinado/mod.json` written), exit `1` conflict and nothing written. The
same offset in the same row is a conflict **even if the two mods write the same value**: the
order of application is not defined, and one mod's `expect` can stop holding after the other
is applied. Refusing beats guessing.

---

## 8 · Look inside the archives (read-only, version 0.2.0)

Next to the container there are 24 `.fdata` archives with the scenes, textures, animations and
sound banks. Nothing here writes; it only walks headers and decompresses in memory.

```bash
python pkp.py fdata stat "$PKP_ROMFS"
```

Real output on the supported build, first lines:

```
ficheros  : 24 .fdata, 5063190412 B
entradas  : 79710
  tipo         type_ktid   entradas    comprim.  B sin comprimir
  g1s          0x7bcd279f     26137       26137       8481193512
  g1a          0x6fa91671     17457       17457        697681192
  g1t          0xafbec60c     14412       14412       6296584324
```

From there, each format has its own reader:

```bash
# one texture to PNG, then back into a .g1t of the same size
python pkp.py fdata extract --type g1t --out build/g1t "$PKP_ROMFS"
python pkp.py tex list build/g1t/<name_hash>.g1t
python pkp.py tex extract build/g1t/<name_hash>.g1t --out build/a.png
python pkp.py tex inject  build/g1t/<name_hash>.g1t --png build/a.png --out build/b.g1t

# animations: header, bones and a neutral round trip
python pkp.py anim list "$PKP_ROMFS/motor_asset_re" --limit 5
python pkp.py anim roundtrip <file.g1a>

# sound banks: census, then one stream out
python pkp.py fdata extract --type srsa --out build/srsa "$PKP_ROMFS"
python pkp.py snd stat build/srsa
```

`snd stat` on the supported build must print, in Spanish:

```
bancos    : 403
streams   : 19297 (18835 con datos dentro del banco)
codecs    : {'ka1a': 18558, 'msadpcm': 277}
```

Formats and limits: [SPEC-FDATA.md](SPEC-FDATA.md), [SPEC-G1T.md](SPEC-G1T.md),
[SPEC-G1A.md](SPEC-G1A.md), [AUDIO.md](AUDIO.md), [SPEC-TEXT.md](SPEC-TEXT.md).

---

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `no encuentro LD_C0_R.BIN en <dir>` (exit `2`) | Neither `PKP_ROMFS` nor `--container` points at the folder holding both files; the default is `./romfs`. | Set `PKP_ROMFS=<dir>`, or pass `--container <dir>`. |
| `destino protegido (solo lectura)` | You aimed a write at the dump or at a folder listed in `PKP_PROTECTED`. | Copy to `build/copia` and pass `--container build/copia`. |
| `` `mod apply --yes` exige --container `` | You asked for a write without saying where. | Add `--container <copy>`. |
| `--yes y --dry-run son incompatibles` | Both flags at once. | Pick one; dry run is the default, so just drop `--yes`. |
| `[ERROR] ... esperaba 2278 (0x8e6) hex e608 y encontre ...` | Your bytes differ from what the mod declares. | Different build, or another mod already touched that row. Do not force it. |
| `merge CONFLICTO` | Two mods write the same offset or the same text slot. | Apply them separately, or edit one. |
| `AVISO: zlib X != 1.3.2 declarada` | Your zlib is a different build (often zlib-ng). | Works, but byte-identity is not signed. |
| `ERROR: la suite esta declarada para >=3.11,<3.12` | Wrong Python. | Use Python 3.11. |
| Exit code `2` | Usage error, not a data problem. | Re-read the command; nothing was written. |

---

## What this quickstart does not cover

* **Saves.** `pkp save read/write` exists, works on save version 2.0.1 only, and is
  documented in [GLOSSARY.md](GLOSSARY.md#6--save-parameters). Read it before writing: a save is
  not a copy you can regenerate.
* **Adding new content** to the container. Version 0.2.0 rewrites bytes and text in existing
  tables; it does not create entries, and it does not create models.
* **Writing `.fdata`.** Textures, animations and sound banks can be modified, but the result is a
  standalone file: putting it back into its archive is not implemented, so nothing from that path
  is known to load in the game yet.
* **Installing** anything into the game. Applying a mod produces a container; what you do with
  it is outside this repository, which ships no game content and no installers.
