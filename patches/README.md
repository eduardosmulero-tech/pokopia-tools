# Patches

Text definitions of **code patches** for the game binary. Nothing in this folder is game content: no
assets, no text, no audio, no models, no dump and no save. A patch declares an identity (file name, game
version, build id and `sha256`) and a list of offsets with the bytes expected there and the bytes to write.

The rule this folder implements is **the patcher is publishable, the content is not**. It holds on three
conditions, which are requirements, not advice:

1. **The user's own copy only.** A patch is applied to a file the user already has. Neither the original
   file nor the patched result is distributed here.
2. **Reversible in one command, and the original is verified first.** The patch is applied from the text
   file and never written over the user's dump: remove the file and the loader is back to the original.
   `patch.json` carries the `sha256` of the exact file the patch was measured on; check it before applying
   and stop if it does not match. A patch measured on another build is not this patch.
3. **Zero foreign bytes.** A patch describes offsets, expected bytes and new bytes. It carries no code,
   data or text taken from the game.

A patch that has not been applied and reverted with evidence is published as `status: "in-testing"`, not as
working. Mechanism and measurements, not a promise.

## Layout

```
patches/
  README.md
  <name>/
    patch.json        verification manifest (schema below)
    patch.pchtxt      the patch itself, in plain text
```

Both files are plain text. A binary patch (`.ips` and friends) is not accepted: if `cat` does not show
readable offsets and bytes, it does not belong here. A patch folder may hold these two files and nothing
else, and each patch is at most 8 KB on disk.

## `patch.json`

```json
{
  "patch_format": 1,
  "name": "your-patch-name",
  "status": "in-testing",
  "target": {
    "file": "main",
    "version": "2.0.1a",
    "build_id": "0123456789abcdef0123456789abcdef01234567",
    "sha256": "<64 lowercase hex characters: sha256 of the file you measured>"
  },
  "edits": [
    {
      "offset": 41194896,
      "expect": "0000",
      "value": "9090",
      "why": "which field you believe you are touching, in your own words"
    }
  ],
  "revert": "delete this patch folder from the loader patch directory"
}
```

| Field | Required | Meaning |
|---|---|---|
| `patch_format` | yes | Format version. Only `1` today. |
| `name` | yes | `^[a-z0-9][a-z0-9._-]{0,63}$`; must be the folder name. |
| `status` | yes | `tested` (applied and reverted with evidence) or `in-testing`. |
| `target.file` | yes | File name only, no path (e.g. `main`). |
| `target.version` | yes | Game version the patch was measured on (`2.0.1a`). |
| `target.build_id` | yes | 40 lowercase hex characters: the first 20 bytes of the build id. |
| `target.sha256` | yes | 64 lowercase hex characters: `sha256` of the measured file. |
| `edits[].offset` | yes | Byte offset in the image the loader patches (header included: `0x100 + offset inside the module`). |
| `edits[].expect` | yes | Bytes that are there now, contiguous hex. If they do not match, nothing is written. |
| `edits[].value` | yes | Bytes written, contiguous hex, same length as `expect`. |
| `edits[].why` | yes | Non-empty, at most 200 characters. Says what you believe you are touching. |
| `revert` | yes | One line: the command or action that puts the original back. |

`expect` is what makes the patch checkable: without it a patch written in May silently corrupts a build
from June and nobody can say why. `expect` and `value` together make it reversible by construction — the
inverse write is the same list with the two swapped. One patch may declare at most **4,096 bytes** in total
(`expect` + `value` all together); a code patch is a handful of bytes, not a payload.

## `patch.pchtxt`

The patch in the plain-text IPSwitch format, which is what loaders read:

```
# comment lines start with '#' or '//'
@nsobid-0123456789abcdef0123456789abcdef01234567
0x02749590 aa
0x027495a0 9090
```

* One `@nsobid-<build id>` directive, and it must equal `target.build_id`.
* Then one `<offset> <bytes>` pair per line: offset in hex, bytes as contiguous hex.
* No string writes (`"..."`): text belongs to the game, not to a patch.
* Offsets are absolute in the image the loader patches: header included, so `0x100 + offset inside the
  module`.
* No offset-shift directives: a patch that depends on a build declares that build id instead.

The guardian checks that every offset and every byte in `patch.pchtxt` matches an `edits[]` entry of
`patch.json`, byte for byte, and that nothing is written that the manifest does not declare.

## Applying

1. **Check the identity.** `sha256sum <your copy of main>` must equal `target.sha256`. If it does not, stop:
   the patch was measured on another build and is not meant for yours.
2. **Install the text patch.** Copy `patch.pchtxt` into the loader patch folder for this title, under a
   folder with this patch's name:

   ```
   <loader data directory>/load/<title id>/<patch name>/exefs/patch.pchtxt
   ```

   Your loader's documentation says where its data directory is, and some want the file named after the
   build id rather than `patch.pchtxt`.
3. **Start the game.** The loader compares `@nsobid-` with the build id of the file it is loading, applies
   the declared bytes **in memory** and, if it logs patches, says so. Your file on disk is not modified.

## Reverting

Delete the folder you created in step 2 and start the game again:

```
rm -r "<loader data directory>/load/<title id>/<patch name>"
```

With nothing left to apply, the loader reads your original file. The revert is complete when
`sha256sum <your copy of main>` still equals `target.sha256`: it never changed. If you patched a copy by
hand instead, write the `expect` bytes back over the `value` bytes at the same offsets and verify that hash.

## What will not be accepted here

* **Binary patches.** `.ips` is opaque; this folder takes text that `cat` reads.
* **More than 4 KB of declared bytes, string writes, assets, text, audio or models.** Offsets, expected
  bytes and new bytes, nothing else.
* **Patches presented as tested without evidence.** Without an application and a revert on the record,
  `status` stays `in-testing`.
* **A patch whose `patch.pchtxt` does not match its `patch.json`.** The manifest is the contract; the text
  file is the application of it.
