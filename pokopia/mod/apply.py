"""Aplicacion de un mod a una COPIA del contenedor.

Reglas duras (docs/MOD-FORMAT.md, docs/ARQUITECTURA-KIT.md §5):

* nunca se escribe en el dump original ni en el arbol del emulador;
* `--dry-run` es el modo por defecto: no toca ni un byte en disco;
* con `--yes` se escribe en un directorio temporal y **solo** se sustituye el
  contenedor cuando la relectura con el lector del kit lo confirma;
* con `--keep-backup` (por defecto) se guarda una copia de los dos ficheros y se
  imprime el comando exacto para deshacer.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import struct
from dataclasses import dataclass, field

from .. import paths, tables
from ..container import (
    FormatError,
    IndexEntry,
    compare_payloads,
    entry_block_size,
    pack_entry,
    read_container,
    unpack_entry,
    verify,
    write_container,
)
from . import types as mt
from .errors import GuardError, ModError, Report
from .manifest import ContainerView, Edit, Mod, TextEdit, validate

BACKUP_DIR = ".pkp-backup"
TMP_TAG = ".pkp-tmp"
MAX_DIFF_LINES = 500


@dataclass
class Write:
    """Una escritura ya resuelta contra el payload original."""

    kind: str                       # "bytes" | "text"
    table: int
    old: bytes
    new: bytes
    edit: object                    # Edit | TextEdit
    abs_offset: int | None = None   # bytes: offset absoluto en el payload
    slot: int | None = None         # text: ordinal del slot


@dataclass
class Plan:
    mod: Mod
    container: paths.Container
    original: dict[int, bytes] = field(default_factory=dict)
    updated: dict[int, bytes] = field(default_factory=dict)
    writes: list[Write] = field(default_factory=list)
    text_slots: dict[int, tuple[list[bytes], list[bytes], bool]] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------

def make_plan(mod: Mod, container: paths.Container,
              view: ContainerView | None = None) -> Plan:
    """Resuelve las ediciones sobre los payloads originales (sin escribir nada)."""
    view = view or ContainerView(container)
    plan = Plan(mod=mod, container=container)

    for table in sorted({e.table for e in mod.edits}):
        plan.original[table] = view.payload(table)
    for table in sorted({t.table for t in mod.texts}):
        plan.original[table] = view.payload(table)

    buffers = {t: bytearray(b) for t, b in plan.original.items()}

    for edit in mod.edits:
        spec = tables.get(edit.table)
        size = mt.type_size(edit.type)
        if size is None:
            size = len(mt.encode(edit.type, edit.value))
        start = (spec.row_offset(edit.row) + edit.offset) if spec else edit.offset
        buf = buffers[edit.table]
        if start + size > len(buf):
            raise ModError("bytes %d..%d fuera del payload de %d B"
                           % (start, start + size, len(buf)),
                           code="mod.range", where=edit.where())
        expected = mt.encode(edit.type, edit.expect)
        found = bytes(buf[start:start + size])
        if found != expected:
            raise ModError("esperaba %s y encontre %s"
                           % (mt.describe(edit.type, expected),
                              mt.describe(edit.type, found)),
                           code="mod.expect", where=edit.where())
        new = mt.encode(edit.type, edit.value)
        buf[start:start + size] = new
        plan.writes.append(Write("bytes", edit.table, found, new, edit,
                                 abs_offset=start))

    for text in mod.texts:
        spec = tables.get(text.table)
        if spec is None or spec.kind != "text":
            raise ModError("la tabla #%d no es de texto" % text.table, code="mod.table",
                           where=text.where())
        buf = buffers[text.table]
        slots, terminated = tables.parse_pool(spec, bytes(buf))
        ordinal = tables.slot_ordinal(spec, text.id, text.slot)
        if ordinal >= len(slots):
            raise ModError("el slot %d no existe (%d slots)"
                           % (ordinal, len(slots)), code="mod.text.range",
                           where=text.where())
        old = slots[ordinal]
        if old != text.expect.encode("utf-8"):
            raise ModError(
                "esperaba %r y encontre otro texto (%d B, sha256 %s)"
                % (text.expect, len(old), hashlib.sha256(old).hexdigest()[:12]),
                code="mod.text.expect", where=text.where())
        slots[ordinal] = text.value.encode("utf-8")
        new_pool = tables.build_pool(slots, terminated)
        buffers[text.table] = bytearray(bytes(buf)[:spec.pool_start] + new_pool)
        plan.writes.append(Write("text", text.table, old,
                                 slots[ordinal], text, slot=ordinal))

    plan.updated = {t: bytes(b) for t, b in buffers.items()}
    for table in plan.original:
        spec = tables.get(table)
        if spec is not None and spec.kind == "text" and plan.original[table] != plan.updated[table]:
            old_slots, term = tables.parse_pool(spec, plan.original[table])
            new_slots, _ = tables.parse_pool(spec, plan.updated[table])
            plan.text_slots[table] = (old_slots, new_slots, term)
    return plan


# --------------------------------------------------------------------------
# Verificacion
# --------------------------------------------------------------------------

def diff_ranges(old: bytes, new: bytes, limit: int = MAX_DIFF_LINES) -> list[dict]:
    """Tramos contiguos de bytes distintos entre dos payloads del mismo tamano."""
    if len(old) != len(new):
        raise ModError("payload de %d B y %d B: una edicion de bytes no puede cambiar "
                       "el tamano" % (len(old), len(new)), code="mod.verify")
    ranges: list[dict] = []
    start = None
    for i in range(len(old)):
        if old[i] != new[i]:
            if start is None:
                start = i
        elif start is not None:
            ranges.append({"start": start, "end": i, "bytes": i - start})
            start = None
    if start is not None:
        ranges.append({"start": start, "end": len(old), "bytes": len(old) - start})
    out = []
    for r in ranges:
        entries = [{"offset": k, "old": old[k], "new": new[k]}
                   for k in range(r["start"], r["end"])]
        r["detail"] = entries[:limit]
        r["truncated"] = len(entries) > limit
        out.append(r)
    return out


def check_payload_roundtrip(payload: bytes, flag: int, block_size: int) -> bool:
    """Empaqueta y vuelve a descomprimir un payload: el lector recupera lo mismo."""
    packed, _ = pack_entry(payload, flag=flag, block_size=block_size)
    if flag == 0:
        return packed == payload
    header = struct.unpack_from("<III", packed, 0)
    return header[2] == len(payload) and unpack_entry(
        packed, IndexEntry(0, len(payload), len(packed), 1)) == payload


def verify_plan(plan: Plan, view: ContainerView) -> dict:
    """Comprueba en memoria que el resultado contiene solo lo declarado."""
    res = {"tables": {}, "ok": True, "errors": []}
    for table, new_payload in plan.updated.items():
        old_payload = plan.original[table]
        ent = view.entries[table]
        block_size = entry_block_size(view.bin_data, ent)
        info = {"table": table, "old_size": len(old_payload),
                "new_size": len(new_payload), "flag": ent.flag,
                "block_size": block_size}
        writes = [w for w in plan.writes if w.table == table]
        try:
            info["roundtrip_ok"] = check_payload_roundtrip(
                new_payload, ent.flag, block_size)
        except (FormatError, ValueError) as exc:  # pragma: no cover - defensivo
            info["roundtrip_ok"] = False
            info["roundtrip_error"] = str(exc)

        byte_writes = [w for w in writes if w.kind == "bytes"]
        if byte_writes:
            ranges = diff_ranges(old_payload, new_payload)
            declared = set()
            for w in byte_writes:
                declared.update(range(w.abs_offset, w.abs_offset + len(w.new)))
            leaked = sorted({k for r in ranges for k in range(r["start"], r["end"])
                             if k not in declared})
            info["diff"] = ranges
            info["diff_bytes"] = sum(r["bytes"] for r in ranges)
            info["outside_declared"] = leaked
            if leaked:
                res["ok"] = False
                res["errors"].append("#%d: %d bytes cambiados fuera de lo declarado "
                                     "(primeros: %s)"
                                     % (table, len(leaked), leaked[:10]))
        text_writes = [w for w in writes if w.kind == "text"]
        if text_writes:
            spec = tables.get(table)
            if spec is None or spec.pool_start is None:
                res["ok"] = False
                res["errors"].append("#%d: edicion de texto sin geometria de texto" % table)
                res["tables"][table] = info
                continue
            slots_old, slots_new, _ = plan.text_slots.get(
                table, (tables.parse_pool(spec, old_payload)[0],
                        tables.parse_pool(spec, new_payload)[0], True))
            prefix_ok = new_payload[:spec.pool_start] == old_payload[:spec.pool_start]
            changed = [{"slot": i, "old_len": len(a), "new_len": len(b),
                        "old_sha256": hashlib.sha256(a).hexdigest()[:12],
                        "new": b.decode("utf-8", "replace")[:80]}
                       for i, (a, b) in enumerate(zip(slots_old, slots_new)) if a != b]
            info["pool_prefix_identical"] = prefix_ok
            info["slots_changed"] = changed
            info["slots_total"] = [len(slots_old), len(slots_new)]
            expected_slots = {w.slot for w in text_writes}
            unexpected = {c["slot"] for c in changed} - expected_slots
            if not prefix_ok or len(slots_old) != len(slots_new) or unexpected:
                res["ok"] = False
                res["errors"].append(
                    "#%d: la zona de texto no cuadra (prefijo_identico=%s slots %d->%d "
                    "inesperados=%s)" % (table, prefix_ok, len(slots_old),
                                         len(slots_new), sorted(unexpected)))
        if not info.get("roundtrip_ok", False):
            res["ok"] = False
            res["errors"].append("#%d: el payload reempaquetado no se relee igual" % table)
        res["tables"][table] = info
    return res


# --------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------

def make_backup(container: paths.Container, mod: Mod) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    root = os.path.join(container.dir, BACKUP_DIR, stamp)
    os.makedirs(root, exist_ok=True)
    for src in (container.bin, container.idx):
        shutil.copy2(src, os.path.join(root, os.path.basename(src)))
    with open(os.path.join(root, "backup.json"), "w", encoding="utf-8") as fh:
        import json
        json.dump({"created": stamp,
                   "mod": mod.name, "mod_version": mod.version,
                   "md5": paths.container_md5(container)}, fh, indent=1)
    return root


def undo_commands(backup: str, container: paths.Container) -> list[str]:
    return ["cp %s %s" % (os.path.join(backup, name),
                          os.path.join(container.dir, name))
            for name in (paths.BIN_NAME, paths.IDX_NAME)]


# --------------------------------------------------------------------------
# Aplicacion
# --------------------------------------------------------------------------

def apply_mod(mod: Mod, container_dir: str | None = None, *, write: bool = False,
              keep_backup: bool = True) -> dict:
    """Aplica `mod`. Sin `write` no toca disco (dry-run). Devuelve el informe.

    La guarda de ruta solo se aplica cuando se va a escribir: un dry-run puede
    leer el dump original (jamás lo abre en escritura).
    """
    container = paths.resolve_container(container_dir)
    protegido = paths.is_protected(container.dir)
    if write:
        try:
            paths.guard_writable(container.dir)
        except PermissionError as exc:
            raise GuardError(str(exc), code="guard", where=container.dir) from None

    result: dict = {
        "mod": mod.name, "mod_version": mod.version, "manifest": mod.manifest,
        "container": container.dir, "dry_run": not write, "written": False,
        "ok": False, "issues": [], "md5_before": {}, "md5_after": {},
        "tables": [], "undo": [], "backup": None, "notes": [],
        "container_protected": protegido,
    }
    if not write and protegido:
        result["notes"].append("contenedor de solo lectura (dump): ensayo, no se "
                               "escribe nunca aqui")
    md5_before = paths.container_md5(container)
    result["md5_before"] = md5_before
    result["md5_after"] = dict(md5_before)

    rep = validate(mod, container)
    if not rep.ok:
        result["issues"] = [i.as_dict() for i in rep.issues]
        result["notes"].append("mod rechazado: %d error(es)" % len(rep.errors))
        return result

    view = ContainerView(container)
    plan = make_plan(mod, container, view=view)
    check = verify_plan(plan, view)
    result["tables"] = [check["tables"][t] for t in sorted(check["tables"])]
    if not check["ok"]:
        result["issues"] = [{"severity": "error", "code": "mod.verify",
                             "message": m, "where": ""} for m in check["errors"]]
        result["notes"].append("verificacion en memoria fallida: no se escribe nada")
        return result

    if not write:
        result["ok"] = True
        result["notes"].append("dry-run: no se ha escrito nada")
        return result

    # --- escritura: temporal, relectura, y solo entonces sustitucion ---------
    tmp_dir = os.path.join(container.dir, TMP_TAG + "-%d" % os.getpid())
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_idx = os.path.join(tmp_dir, paths.IDX_NAME)
    tmp_bin = os.path.join(tmp_dir, paths.BIN_NAME)
    try:
        write_container(container.idx, container.bin, tmp_idx, tmp_bin,
                        replace=plan.updated)
        problems = verify(tmp_idx, tmp_bin, verbose=False)
        if problems["problems"]:
            result["issues"] = [{"severity": "error", "code": "container.verify",
                                 "message": "el contenedor escrito tiene %d problemas: %s"
                                 % (len(problems["problems"]),
                                    problems["problems"][:5]), "where": tmp_dir}]
            result["notes"].append("no se sustituye el destino")
            return result

        comp = compare_payloads(container.idx, container.bin, tmp_idx, tmp_bin)
        edited = sorted(plan.updated)
        unexpected = [i for i in comp["different"] if i not in edited]
        if comp["errors"] or unexpected or comp["different_count"] != len(edited):
            result["issues"] = [{"severity": "error", "code": "mod.verify",
                                 "message": "la relectura no coincide: distintas=%s "
                                            "esperadas=%s inesperadas=%s errores=%s"
                                            % (comp["different"], edited, unexpected,
                                               comp["errors"][:5]), "where": tmp_dir}]
            result["notes"].append("no se sustituye el destino")
            return result

        # comprobacion byte a byte desde disco contra el plan
        new_entries, new_bin = read_container(tmp_idx, tmp_bin)
        disk_ok = True
        for table in edited:
            blob = unpack_entry(new_bin, new_entries[table], index=table)
            if blob != plan.updated[table]:
                disk_ok = False
                result["issues"].append({
                    "severity": "error", "code": "mod.verify",
                    "message": "#%d: el payload leido del contenedor escrito no es el "
                               "planificado" % table, "where": tmp_dir})
        if not disk_ok:
            result["notes"].append("no se sustituye el destino")
            return result

        if keep_backup:
            backup = make_backup(container, mod)
            result["backup"] = backup
            result["undo"] = undo_commands(backup, container)
        os.replace(tmp_bin, container.bin)
        os.replace(tmp_idx, container.idx)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    result["written"] = True
    result["md5_after"] = paths.container_md5(container)
    result["ok"] = True
    result["notes"].append("contenedor sustituido en la copia %s" % container.dir)
    for issue in rep.warnings:
        result["issues"].append(issue.as_dict())
    return result
