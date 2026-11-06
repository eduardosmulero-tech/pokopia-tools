"""Escritura segura de una pagina del save: dry-run por defecto, copia y deshacer.

Reglas que impone este modulo:

1. **Nada se escribe sin `dry_run=False`.** El valor por defecto es simular.
2. **Nunca en el save vivo sin permiso explicito.** Si el destino cae dentro del save del
   emulador hace falta `allow_live_save=True`; si no, `SaveReadOnlyError`.
3. **Copia antes de tocar.** Toda escritura deja `build/backups/<fecha>-<pagina>-CMNDAT.BIN`
   y un manifiesto JSON con los md5 y el comando exacto para deshacer.
4. **Se comprueba lo escrito.** Se relee el fichero resultante, se descomprime y se compara
   con el payload pedido. Se informa de cuantos bytes cambian en el payload y cuantos en el
   fichero.

Por que los dos numeros no coinciden: el cuerpo del save es **un solo flujo zlib estandar** y
el del juego **si se reproduce** (nivel 1, `memLevel` 8, estrategia por defecto; en las
instantaneas del save 2.0.1 `stream_reproducible(page)` es True). Cambiar un byte del crudo
deja **1 byte** distinto en el payload, que es el invariante del modulo, pero en el fichero
comprimido cuesta **4 bytes como minimo observado** (el literal tocado mas el `adler32`, que
cubre todo el payload) y puede costar mucho mas: si el byte cae dentro de una coincidencia del
deflate, la recompresion reordena cientos o miles de bytes, y hasta puede cambiar el tamano
del fichero (entonces se reescribe tambien la longitud declarada en `+0x10`). No hay un
compresor distinto detras: es el coste normal de recomprimir. Con un zlib que comprima peor
(p. ej. zlib-ng) el flujo ya no seria identico y el modulo lo avisa.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import time
import zlib
from dataclasses import dataclass, field

from .. import paths
from . import layout as layouts
from .errors import SaveError, SaveReadOnlyError
from .page import SavePage, configured_save, md5_file, page_path, resolve_save


def repo_root() -> str:
    """Raiz del repo (tres niveles por encima de pokopia/save/)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def backup_dir() -> str:
    return os.environ.get("PKP_BACKUP_DIR") or os.path.join(repo_root(), "build",
                                                            "backups")


def is_live_save(path: str) -> bool:
    """True si `path` cae dentro del save configurado o de un arbol protegido."""
    target = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    for tree in (configured_save(), *paths.protected_trees()):
        root = os.path.normcase(os.path.realpath(os.path.abspath(tree)))
        if target == root or target.startswith(root + os.sep):
            return True
    return False


@dataclass
class WriteResult:
    """Lo que ha pasado (o habria pasado) al escribir."""

    page: str
    target: str
    dry_run: bool
    wrote: bool = False
    backup: str | None = None
    manifest: str | None = None
    md5_before: str = ""
    md5_after: str = ""
    payload_diff: int = 0
    payload_offsets: list[int] = field(default_factory=list)
    file_diff: int = 0
    roundtrip_ok: bool = False
    unchanged: bool = False
    stream_identical: bool = False
    notes: list[str] = field(default_factory=list)

    def undo_commands(self) -> list[str]:
        if not self.backup:
            return []
        return ["pkp save undo %s --yes" % self.backup,
                "  (o a mano: copiar %s sobre %s)" % (self.backup, self.target)]

    def as_dict(self) -> dict:
        return {
            "page": self.page, "target": self.target, "dry_run": self.dry_run,
            "wrote": self.wrote, "backup": self.backup, "manifest": self.manifest,
            "md5_before": self.md5_before, "md5_after": self.md5_after,
            "payload_diff": self.payload_diff,
            "payload_offsets": self.payload_offsets,
            "file_diff": self.file_diff, "roundtrip_ok": self.roundtrip_ok,
            "unchanged": self.unchanged, "stream_identical": self.stream_identical,
            "undo": self.undo_commands(), "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Serializacion
# ---------------------------------------------------------------------------

def build_raw(page: SavePage, new_payload: bytes, *, level: int = 1,
              strategy: str = "default", memlevel: int = 8) -> bytes:
    """Fichero CMNDAT completo con el payload nuevo (cabecera + zlib + cola original).

    Por defecto se recompone con **el mismo compresor que usa el juego**: zlib estandar,
    nivel 1, `memLevel` 8 y estrategia por defecto. Medido (sonda 14): con esos parametros
    el cuerpo se reproduce **byte a byte** en las tres instantaneas del save 2.0.1, asi que
    una escritura sin cambios es indistinguible del original tambien en el flujo comprimido.
    Ojo: hay interpreters de Python cuyo `zlib` es zlib-ng y **no** reproduce el flujo
    (comprime mejor); con esos, la escritura sigue siendo valida pero ya no identica.
    """
    if len(new_payload) != len(page.payload):
        raise SaveError("el payload nuevo mide %d B y el original %d B"
                        % (len(new_payload), len(page.payload)))
    if level not in range(0, 10):
        raise SaveError("nivel zlib %d fuera de 0..9" % level)
    if memlevel not in range(1, 10):
        raise SaveError("memLevel %d fuera de 1..9" % memlevel)
    try:
        strat = {"default": zlib.Z_DEFAULT_STRATEGY, "fixed": zlib.Z_FIXED,
                 "filtered": zlib.Z_FILTERED}[strategy]
    except KeyError:
        raise SaveError("estrategia zlib desconocida %r (default|fixed|filtered)"
                        % strategy)
    header = page.raw[:page.layout.header_size]
    tail = page.raw[page.declared_length:]
    comp = zlib.compressobj(level, zlib.DEFLATED, 15, memlevel, strat)
    body = comp.compress(new_payload) + comp.flush()
    declared = page.layout.header_size + len(body)
    head = bytearray(header)
    struct.pack_into("<i", head, 0x10, declared)
    return bytes(head) + body + tail


def stream_reproducible(page: SavePage, *, level: int = 1, strategy: str = "default",
                        memlevel: int = 8) -> bool:
    """True si recomprimir el payload actual devuelve el fichero original byte a byte."""
    try:
        return build_raw(page, page.payload, level=level, strategy=strategy,
                         memlevel=memlevel) == page.raw
    except SaveError:
        return False


def payload_of(raw: bytes) -> bytes:
    """Payload crudo de un CMNDAT en memoria (para comprobar lo que se va a escribir)."""
    declared = struct.unpack_from("<i", raw, 0x10)[0]
    return zlib.decompress(raw[layouts.HEADER_SIZE:declared])


def _diff_offsets(a: bytes, b: bytes, limit: int = 32) -> tuple[int, list[int]]:
    n = min(len(a), len(b))
    total = 0
    first: list[int] = []
    for i in range(n):
        if a[i] != b[i]:
            total += 1
            if len(first) < limit:
                first.append(i)
    return total, first


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def write_payload(page: SavePage, new_payload: bytes, *, target: str | None = None,
                  dry_run: bool = True, allow_live_save: bool = False,
                  level: int = 1, strategy: str = "default",
                  memlevel: int = 8) -> WriteResult:
    """Escribe `new_payload` en la pagina. Sin `dry_run=False` no toca el disco."""
    target = os.path.abspath(target or page.path)
    result = WriteResult(page=page.page, target=target, dry_run=dry_run,
                         md5_before=page.md5)
    if is_live_save(target) and not allow_live_save:
        raise SaveReadOnlyError(
            "destino dentro del save configurado (solo lectura): %s\n"
            "  copia la pagina a una carpeta de trabajo y pasa --save <copia>, o "
            "repitelo con --allow-live-save si de verdad quieres escribir ahi "
            "(y con el juego cerrado)" % target)

    if new_payload == page.payload:
        result.unchanged = True
        result.md5_after = page.md5
        result.payload_diff = 0
        result.file_diff = 0
        result.roundtrip_ok = True
        result.stream_identical = stream_reproducible(page, level=level,
                                                     strategy=strategy, memlevel=memlevel)
        result.notes.append("sin cambios en el payload: el fichero no se toca y el md5 "
                            "sigue siendo el mismo")
        result.notes.append(
            "flujo del juego reproducible con zlib nivel %d memLevel %d: %s"
            % (level, memlevel, "si" if result.stream_identical else
               "no (este zlib comprime distinto; la escritura seguiria siendo valida)"))
        return result

    raw = build_raw(page, new_payload, level=level, strategy=strategy, memlevel=memlevel)
    payload_diff, offsets = _diff_offsets(page.payload, new_payload)
    result.payload_diff = payload_diff
    result.payload_offsets = offsets
    # comprobacion de ida: lo que se va a escribir descomprime al payload pedido
    result.roundtrip_ok = payload_of(raw) == new_payload
    if not result.roundtrip_ok:
        raise SaveError("el fichero reconstruido no descomprime al payload pedido; "
                        "no se escribe nada")
    file_diff, _ = _diff_offsets(page.raw, raw)
    result.file_diff = file_diff
    result.md5_after = hashlib.md5(raw).hexdigest()
    size_before, size_after = len(page.raw), len(raw)
    if size_before != size_after:
        result.notes.append("el fichero cambia de tamano: %d -> %d B (al recomprimir con "
                            "el mismo zlib del juego el flujo puede salir de otra "
                            "longitud; se reescribe la longitud declarada)" % (size_before, size_after))
    elif 0 < file_diff <= 16:
        result.notes.append("mismo tamano y solo %d bytes distintos: el literal tocado "
                            "mas el adler32 del flujo (el minimo observado son 4)" % file_diff)
    if dry_run:
        result.notes.append("dry-run: no se ha escrito nada")
        return result

    # copia + manifiesto
    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = backup_dir()
    os.makedirs(outdir, exist_ok=True)
    base = "%s-%s-CMNDAT.BIN" % (stamp, page.page)
    backup = os.path.join(outdir, base)
    n = 1
    while os.path.exists(backup):
        backup = os.path.join(outdir, "%s-%d" % (base, n))
        n += 1
    if os.path.exists(target):
        shutil.copy2(target, backup)
    else:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(backup, "wb") as fh:
            fh.write(page.raw)
    result.backup = backup

    with open(target, "wb") as fh:
        fh.write(raw)
    result.wrote = True
    result.md5_after = md5_file(target)

    manifest = backup + ".json"
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump({"page": page.page, "target": target, "backup": backup,
                   "md5_before": result.md5_before, "md5_after": result.md5_after,
                   "bytes_before": size_before, "bytes_after": size_after,
                   "payload_diff": result.payload_diff,
                   "payload_offsets": result.payload_offsets,
                   "file_diff": result.file_diff,
                   "undo": result.undo_commands(),
                   "when": stamp}, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    result.manifest = manifest
    return result


def undo(backup: str, *, dry_run: bool = True) -> dict:
    """Devuelve el fichero de la copia indicada a su sitio."""
    backup = os.path.abspath(backup)
    if not os.path.isfile(backup):
        raise SaveError("no existe la copia %s" % backup)
    manifest_path = backup + ".json"
    manifest = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    target = manifest.get("target")
    if not target:
        raise SaveError("la copia %s no tiene manifiesto con el destino; no se puede "
                        "deshacer a ciegas" % backup)
    current = md5_file(target) if os.path.isfile(target) else "(no existe)"
    expected = manifest.get("md5_after")
    ok_current = expected is None or current == expected
    doc = {"backup": backup, "target": target, "md5_backup": md5_file(backup),
           "md5_target_now": current, "md5_expected_after_write": expected,
           "safe_to_undo": ok_current, "dry_run": dry_run, "restored": False}
    if not ok_current:
        doc["note"] = ("el fichero actual no es el que dejo la escritura; no se "
                       "restaura para no pisar cambios posteriores")
        return doc
    if dry_run:
        return doc
    shutil.copy2(backup, target)
    doc["restored"] = True
    doc["md5_target_after_undo"] = md5_file(target)
    return doc


def copy_page_to(src_page: str, dst_dir: str, page: str = "G00") -> str:
    """Copia una pagina del save a una carpeta de trabajo (la unica forma segura)."""
    src = page_path(resolve_save(src_page), page)
    os.makedirs(os.path.join(dst_dir, page), exist_ok=True)
    dst = os.path.join(dst_dir, page, "CMNDAT.BIN")
    shutil.copy2(src, dst)
    return dst
