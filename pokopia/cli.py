"""CLI del kit: `pkp` (contrato en docs/ARQUITECTURA-KIT.md §5).

Comandos implementados aqui:

    pkp info
    pkp table <n> [--rows a:b]
    pkp row <n> <r>
    pkp dump <entrada> <salida>
    pkp repack <dir> [--recompress]
    pkp mod new <nombre>
    pkp mod validate <carpeta>
    pkp mod merge <a> <b> [-o <dir>]
    pkp mod apply <carpeta> [--dry-run | --yes]
    pkp fdata list|stat|extract <ruta> [--type kidsobjdb]
    pkp catalog list [--prefix BP|PM|BI|PC|AP]
    pkp catalog find <texto>

Todos los comandos que escriben tienen `--dry-run` por defecto y ninguno escribe
en el dump original.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys

from . import paths, tables, fdata, catalog, objdb, texcmd, g1t, anim, snd
from .container import (
    DEFAULT_BLOCK_SIZE,
    entry_block_size,
    get_compressor,
    read_container,
    unpack_entry,
    verify,
    write_container,
)
from .mod import (
    GuardError,
    ModError,
    UsageError,
    apply_mod,
    load_mod,
    merge_mods,
    validate,
)
from .mod.manifest import ContainerView
from .mod import types as mt
from . import save as savemod

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------------
# Formato de salida
# --------------------------------------------------------------------------

def out(stream, line: str = "") -> None:
    stream.write(line + "\n")


def print_report(report, stream=sys.stdout) -> None:
    for issue in report.issues:
        out(stream, str(issue))


def hexdump(data: bytes, base: int = 0, width: int = 16) -> list[str]:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexes = " ".join("%02x" % b for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append("%08x  %-*s  |%s|" % (base + i, width * 3 - 1, hexes, text))
    return lines


# --------------------------------------------------------------------------
# Comandos de lectura
# --------------------------------------------------------------------------

def cmd_info(args) -> int:
    container = paths.resolve_container(args.container)
    entries, bin_data = read_container(container.idx, container.bin)
    res = verify(container.idx, container.bin, verbose=False)
    md5s = paths.container_md5(container)
    doc = {
        "container": container.dir,
        "bin": {"size": os.path.getsize(container.bin), "md5": md5s[paths.BIN_NAME]},
        "idx": {"size": os.path.getsize(container.idx), "md5": md5s[paths.IDX_NAME]},
        "entries": len(entries),
        "flags": {str(k): v for k, v in sorted(res["flags"].items())},
        "empty_entries": res["empty_entries"],
        "total_raw": res["total_raw"],
        "total_packed": res["total_packed"],
        "blocks": {"compressed": res.get("blocks_comp", 0),
                   "raw": res.get("blocks_raw", 0)},
        "problems": len(res["problems"]),
        "tables": [{"index": s.index, "kind": s.kind, "stride": s.stride,
                    "count": s.count, "header": s.header, "language": s.language,
                    "confidence": s.confidence, "note": s.note}
                   for s in tables.known()],
    }
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "contenedor : %s" % container.dir)
    out(sys.stdout, "  %s  %d B  md5 %s" % (paths.BIN_NAME, doc["bin"]["size"],
                                            doc["bin"]["md5"]))
    out(sys.stdout, "  %s  %d B  md5 %s" % (paths.IDX_NAME, doc["idx"]["size"],
                                            doc["idx"]["md5"]))
    out(sys.stdout, "entradas   : %d   flags %s   vacias %d"
        % (doc["entries"], doc["flags"], doc["empty_entries"]))
    out(sys.stdout, "payload    : %d B descomprimidos en %d B empaquetados"
        % (doc["total_raw"], doc["total_packed"]))
    out(sys.stdout, "bloques    : %d comprimidos, %d crudos"
        % (doc["blocks"]["compressed"], doc["blocks"]["raw"]))
    out(sys.stdout, "problemas  : %d" % doc["problems"])
    out(sys.stdout, "tablas conocidas:")
    for spec in tables.known():
        out(sys.stdout, "  %-46s %s" % (tables.table_name(spec.index), spec.confidence))
        if spec.note:
            out(sys.stdout, "      %s" % spec.note)
    return EXIT_OK


def _parse_rows(arg: str | None, count: int) -> tuple[int, int]:
    if not arg:
        return 0, min(count, 20)
    try:
        if ":" in arg:
            a, b = arg.split(":", 1)
            start = int(a) if a else 0
            end = int(b) if b else count
        else:
            start, end = 0, int(arg)
    except ValueError:
        raise UsageError("--rows espera 'a:b' o un numero, no %r" % arg, code="usage")
    return max(0, start), min(count, end)


def cmd_table(args) -> int:
    spec = tables.get(args.table)
    container = paths.resolve_container(args.container)
    view = ContainerView(container)
    blob = view.payload(args.table)
    if spec is None:
        size = len(blob)
        out(sys.stdout, "#%d: sin geometria declarada (%d B). hexdump de los primeros "
                        "256 B:" % (args.table, size))
        for line in hexdump(blob[:256]):
            out(sys.stdout, line)
        return EXIT_OK
    count, version = tables.check_header(spec, blob)
    out(sys.stdout, "%s" % tables.table_name(spec.index))
    out(sys.stdout, "  header %d B  count %d  version %d  stride %d  "
                    "confianza %s" % (spec.header, count, version, spec.stride,
                                      spec.confidence))
    if spec.source:
        out(sys.stdout, "  fuente: %s" % spec.source)
    if spec.note:
        out(sys.stdout, "  nota: %s" % spec.note)
    start, end = _parse_rows(args.rows, count)
    out(sys.stdout, "  filas %d..%d de %d (hex)" % (start, end - 1, count) if end > start
        else "  sin filas que mostrar")
    for row in range(start, end):
        data = tables.read_row(spec, blob, row)
        extra = ""
        for f in spec.fields:
            value = mt.describe(f.type, data[f.offset:f.offset + mt.type_size(f.type)])
            extra += "  %s=%s" % (f.name, value)
        out(sys.stdout, "  [%4d] %s%s" % (row, data.hex(), extra))
    return EXIT_OK


def cmd_row(args) -> int:
    container = paths.resolve_container(args.container)
    view = ContainerView(container)
    blob = view.payload(args.table)
    spec = tables.get(args.table)
    if spec is None:
        raise UsageError("#%d no tiene geometria declarada: usa `pkp table %d`"
                         % (args.table, args.table), code="usage")
    count, version = tables.check_header(spec, blob)
    if spec.kind == "text":
        slots, terminated = tables.parse_pool(spec, blob)
        out(sys.stdout, "#%d textos %s: count %d, pool en %d, %d slots (terminado=%s)"
            % (args.table, spec.language, count, spec.pool_start, len(slots), terminated))
        if not tables.TEXT_FIRST_ID <= args.row <= count + 3:
            raise UsageError("id de texto %d fuera de rango (%d..%d)"
                             % (args.row, tables.TEXT_FIRST_ID, count + 3), code="usage")
        base = tables.SLOTS_PER_BLOCK * (args.row - tables.TEXT_FIRST_ID)
        out(sys.stdout, "id %d -> slots %d..%d del bloque" % (args.row, base, base + 5))
        for slot in range(6):
            ordinal = base + slot
            if ordinal >= len(slots):
                out(sys.stdout, "  +%d  (no existe)" % slot)
                continue
            data = slots[ordinal]
            out(sys.stdout, "  +%d  %d B  sha256 %s" % (slot, len(data),
                                                        hashlib.sha256(data).hexdigest()[:12]))
        bloque = tables.block_slots(spec, slots, args.row)
        out(sys.stdout, "  bloque  %d B en %d slots  sha256 %s"
            % (len(b"".join(bloque)), len(bloque),
               tables.block_sha256(spec, slots, args.row)))
        out(sys.stdout, "  ^ este es el valor de 'expect_sha256' (docs/MOD-FORMAT.md §3.1)")
        return EXIT_OK
    data = tables.read_row(spec, blob, args.row)
    out(sys.stdout, "#%d fila %d de %d (stride %d, confianza %s)"
        % (args.table, args.row, count, spec.stride, spec.confidence))
    out(sys.stdout, "  bytes: %s" % data.hex())
    for f in spec.fields:
        size = mt.type_size(f.type)
        raw = data[f.offset:f.offset + size]
        out(sys.stdout, "  +%-3d %-4s %-14s %s   [%s]"
            % (f.offset, f.type, f.name, mt.describe(f.type, raw), f.confidence))
        if f.note:
            out(sys.stdout, "       %s" % f.note)
    out(sys.stdout, "  campos no declarados: %d B (sin esquema; ver docs/SPEC-ITEM-ROW.md)"
        % (spec.stride - sum(mt.type_size(f.type) or 0 for f in spec.fields)))
    return EXIT_OK


def cmd_dump(args) -> int:
    container = paths.resolve_container(args.container)
    paths.guard_writable(args.out)
    view = ContainerView(container)
    blob = view.payload(args.entry)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(blob)
    out(sys.stdout, "dump #%d -> %s (%d bytes)" % (args.entry, args.out, len(blob)))
    return EXIT_OK


def cmd_repack(args) -> int:
    container = paths.resolve_container(args.container)
    outdir = os.path.abspath(args.outdir)
    paths.guard_writable(outdir)
    os.makedirs(outdir, exist_ok=True)
    idx = os.path.join(outdir, paths.IDX_NAME)
    binp = os.path.join(outdir, paths.BIN_NAME)
    comp = get_compressor(args.backend)
    write_container(container.idx, container.bin, idx, binp,
                    compressor=comp, copy_unchanged=not args.recompress)
    before = paths.container_md5(container)
    after = {paths.BIN_NAME: paths.md5_file(binp),
             paths.IDX_NAME: paths.md5_file(idx)}
    doc = {"out": outdir, "recompress": bool(args.recompress),
           "compressor": comp.describe(), "md5_source": before, "md5_repack": after,
           "identical": before == after}
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
    else:
        out(sys.stdout, "compresor: %s" % doc["compressor"])
        out(sys.stdout, "repack: %s" % outdir)
        for key in (paths.BIN_NAME, paths.IDX_NAME):
            out(sys.stdout, "  %s  origen %s  repack %s  %s"
                % (key, before[key], after[key],
                   "IDENTICO" if before[key] == after[key] else "DISTINTO"))
    return EXIT_OK if doc["identical"] else EXIT_INVALID


# --------------------------------------------------------------------------
# Comandos de mod
# --------------------------------------------------------------------------

TEMPLATE = {
    "mod_format": 1,
    "name": "",
    "version": "0.1.0",
    "authors": [],
    "description": "",
    "game": {"title": "pokopia", "version": "",
             "container_md5": {paths.BIN_NAME: "", paths.IDX_NAME: ""}},
    "requires": [],
    "edits": [],
    "text": [],
}


def cmd_mod_new(args) -> int:
    container = paths.resolve_container(args.container)
    md5s = paths.container_md5(container)
    name = args.name
    if not name:
        raise UsageError("falta el nombre del mod", code="usage")
    target = os.path.abspath(args.dir or os.path.join("ejemplos", name))
    manifest = os.path.join(target, "mod.json")
    if os.path.exists(manifest):
        raise UsageError("%s ya existe: no se sobrescribe" % manifest, code="usage")
    doc = json.loads(json.dumps(TEMPLATE))
    doc["name"] = name
    doc["authors"] = [os.environ.get("USERNAME") or os.environ.get("USER") or "?"]
    doc["game"]["version"] = "2.0.1a"
    doc["game"]["container_md5"] = md5s
    os.makedirs(target, exist_ok=True)
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    out(sys.stdout, "mod nuevo: %s" % manifest)
    out(sys.stdout, "  md5 del contenedor tomados de %s" % container.dir)
    out(sys.stdout, "  siguiente paso: rellena 'edits' o 'text' y ejecuta "
                    "`pkp mod validate %s`" % target)
    return EXIT_OK


def cmd_mod_validate(args) -> int:
    mod = load_mod(args.mod)
    container = None if args.no_container else paths.resolve_container(
        args.container, must_exist=False)
    if container is not None and not os.path.isfile(container.idx):
        container = None
    report = validate(mod, container, check_expect=not args.no_expect)
    doc = {"mod": mod.name, "version": mod.version, "manifest": mod.manifest,
           "container": container.dir if container else None,
           "edits": len(mod.edits), "text": len(mod.texts),
           **report.as_dict()}
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
    else:
        out(sys.stdout, "mod: %s@%s  (%d ediciones de bytes, %d de texto)"
            % (mod.name, mod.version, len(mod.edits), len(mod.texts)))
        out(sys.stdout, "  contenedor: %s" % (doc["container"] or "(no comprobado)"))
        print_report(report)
        out(sys.stdout, "resultado: %s (%d errores, %d avisos)"
            % ("OK" if report.ok else "INVALIDO", len(report.errors),
               len(report.warnings)))
    return EXIT_OK if report.ok else EXIT_INVALID


def cmd_mod_merge(args) -> int:
    result = merge_mods(args.a, args.b, args.out, name=args.name, version=args.version,
                        container_dir=args.container)
    doc = {"ok": result.ok, "written": result.written,
           "mod": result.doc["name"] if result.doc else None,
           "edits": len(result.doc["edits"]) if result.doc else 0,
           "text": len(result.doc["text"]) if result.doc else 0,
           **result.report.as_dict()}
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
    else:
        print_report(result.report)
        if result.ok:
            out(sys.stdout, "merge OK: %s (%d ediciones, %d textos) -> %s"
                % (doc["mod"], doc["edits"], doc["text"],
                   result.written or "(no escrito: falta -o)"))
        else:
            out(sys.stdout, "merge CONFLICTO: %d errores, %d avisos"
                % (len(result.report.errors), len(result.report.warnings)))
    return EXIT_OK if result.ok else EXIT_INVALID


def cmd_mod_apply(args) -> int:
    write = bool(args.yes)
    if write and not args.container:
        raise UsageError(
            "`mod apply --yes` exige --container con la COPIA del contenedor; nunca se "
            "escribe en el dump (copia primero: ver docs/MOD-FORMAT.md §5)",
            code="usage")
    if args.yes and args.dry_run:
        raise UsageError("--yes y --dry-run son incompatibles", code="usage")
    mod = load_mod(args.mod)
    result = apply_mod(mod, args.container, write=write,
                      keep_backup=not args.no_backup)
    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
    else:
        _print_apply(result, write)
    return EXIT_OK if result["ok"] else EXIT_INVALID


def _print_apply(result: dict, write: bool) -> None:
    out(sys.stdout, "mod: %s@%s" % (result["mod"], result["mod_version"]))
    out(sys.stdout, "contenedor: %s%s" % (result["container"],
                                          "" if write else "   [dry-run]"))
    out(sys.stdout, "md5 antes : BIN %s  IDX %s"
        % (result["md5_before"].get(paths.BIN_NAME),
           result["md5_before"].get(paths.IDX_NAME)))
    for table in result["tables"]:
        out(sys.stdout, "tabla #%d: %d -> %d B  flag=%d blockSize=0x%x"
            % (table["table"], table["old_size"], table["new_size"], table["flag"],
               table["block_size"]))
        if table.get("diff"):
            total = sum(r["bytes"] for r in table["diff"])
            out(sys.stdout, "  diff: %d tramo(s), %d byte(s)" % (len(table["diff"]), total))
            for r in table["diff"]:
                for item in r["detail"]:
                    out(sys.stdout, "    +%-6d 0x%02x -> 0x%02x"
                        % (item["offset"], item["old"], item["new"]))
                if r["truncated"]:
                    out(sys.stdout, "    ... (tramo truncado)")
        if table.get("slots_changed"):
            out(sys.stdout, "  slots totales: %s -> %s; cambios:"
                % (table["slots_total"][0], table["slots_total"][1]))
            for change in table["slots_changed"]:
                out(sys.stdout, "    slot %d  %d B -> %d B  nuevo=%r"
                    % (change["slot"], change["old_len"], change["new_len"],
                       change["new"]))
        out(sys.stdout, "  reempaquetado: %s  prefijo de texto identico: %s"
            % ("ok" if table.get("roundtrip_ok") else "FALLO",
               table.get("pool_prefix_identical", "n/a")))
    print_report(_PseudoReport(result["issues"]))
    for note in result["notes"]:
        out(sys.stdout, "  %s" % note)
    if result["written"]:
        out(sys.stdout, "md5 despues: BIN %s  IDX %s"
            % (result["md5_after"].get(paths.BIN_NAME),
               result["md5_after"].get(paths.IDX_NAME)))
        if result["backup"]:
            out(sys.stdout, "backup: %s" % result["backup"])
            out(sys.stdout, "deshacer:")
            for cmd in result["undo"]:
                out(sys.stdout, "  %s" % cmd)
        else:
            out(sys.stdout, "sin backup (--no-backup): no hay deshacer")
    out(sys.stdout, "resultado: %s" % ("OK" if result["ok"] else "FALLIDO"))


class _PseudoReport:
    def __init__(self, issues):
        self.issues = [_Issue(i) for i in issues]


class _Issue:
    def __init__(self, raw):
        self.raw = raw

    def __str__(self):
        tag = "ERROR" if self.raw["severity"] == "error" else "aviso"
        prefix = ("%s: " % self.raw["where"]) if self.raw.get("where") else ""
        return "[%s] %s%s" % (tag, prefix, self.raw["message"])


# --------------------------------------------------------------------------
# Comandos de save y progreso
# --------------------------------------------------------------------------

def cmd_save_read(args) -> int:
    page = savemod.open_page(args.save, args.page)
    items = savemod.read_items(page)
    doc = page.summary()
    doc["items"] = [r.as_dict() for r in items]
    doc["occupied"] = sum(1 for r in items if r.occupied)
    doc["distinct_ids"] = len({r.item_id for r in items if r.occupied})
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "save      : %s" % doc["path"])
    out(sys.stdout, "pagina    : %s   juego %s   version %s"
        % (doc["page"], doc["game"], doc["version"]))
    out(sys.stdout, "fichero   : %d B   md5 %s   declarado %d B"
        % (doc["bytes"], doc["md5"], doc["declared_length"]))
    out(sys.stdout, "cuerpo    : %d B crudos" % doc["payload"])
    out(sys.stdout, "regiones  : %s" % ", ".join(
        "%s@0x%X x%d(%dB,%s)" % (r["name"], r["offset"], r["count"], r["stride"],
                                 r["confidence"]) for r in doc["regions"]))
    out(sys.stdout, "inventario: %d / %d huecos   %d ids distintos"
        % (doc["occupied"], len(items), doc["distinct_ids"]))
    for record in items:
        if record.occupied or args.all:
            out(sys.stdout, "  %s" % record)
    return EXIT_OK


def cmd_save_write(args) -> int:
    if args.yes and args.dry_run:
        raise UsageError("--yes y --dry-run son incompatibles", code="usage")
    if args.id is None and args.count is None and args.variant is None:
        raise UsageError("nada que escribir: pasa al menos uno de --id, --count, "
                         "--variant", code="usage")
    page = savemod.open_page(args.save, args.page)
    new_payload = savemod.items.with_item(page, args.slot, item_id=args.id,
                                          count=args.count, variant=args.variant)
    result = savemod.write_payload(page, new_payload, target=args.target,
                                  dry_run=not args.yes,
                                  allow_live_save=args.allow_live_save,
                                  level=args.level, strategy=args.strategy,
                                  memlevel=args.memlevel)
    if args.json:
        json.dump(result.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    _print_write(result)
    return EXIT_OK


def _print_write(result: savemod.WriteResult) -> None:
    out(sys.stdout, "pagina    : %s   destino %s%s"
        % (result.page, result.target, "   [dry-run]" if result.dry_run else ""))
    out(sys.stdout, "md5 antes : %s" % result.md5_before)
    out(sys.stdout, "md5 nuevo : %s%s" % (result.md5_after,
                                          "" if result.wrote else "  (no escrito)"))
    out(sys.stdout, "payload   : %d byte(s) distinto(s) %s"
        % (result.payload_diff,
           ("en " + ", ".join("0x%X" % o for o in result.payload_offsets[:8]))
           if result.payload_offsets else ""))
    out(sys.stdout, "fichero   : %d byte(s) distinto(s)%s"
        % (result.file_diff,
           "" if result.unchanged else " (el cuerpo se recomprime)"))
    out(sys.stdout, "ida       : %s" % ("el fichero descomprime al payload pedido"
                                        if result.roundtrip_ok else "FALLO"))
    for note in result.notes:
        out(sys.stdout, "  %s" % note)
    if result.wrote:
        out(sys.stdout, "backup    : %s" % result.backup)
        out(sys.stdout, "manifiesto: %s" % result.manifest)
        out(sys.stdout, "deshacer  :")
        for line in result.undo_commands():
            out(sys.stdout, "  %s" % line)


def cmd_save_undo(args) -> int:
    doc = savemod.undo(args.backup, dry_run=not args.yes)
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "copia     : %s" % doc["backup"])
    out(sys.stdout, "destino   : %s" % doc["target"])
    out(sys.stdout, "md5 actual: %s" % doc["md5_target_now"])
    if not doc["safe_to_undo"]:
        out(sys.stdout, "resultado : NO se restaura: %s" % doc.get("note", ""))
        return EXIT_INVALID
    out(sys.stdout, "resultado : %s" % ("restaurado, md5 %s" % doc["md5_target_after_undo"]
                                        if doc["restored"] else
                                        "se puede deshacer (dry-run)"))
    return EXIT_OK


def cmd_progress(args) -> int:
    page = savemod.open_page(args.save, args.page)
    report = savemod.build_report(page, save_dir=savemod.resolve_save(args.save))
    union = None
    if args.union:
        other = "B00" if page.page == "G00" else "G00"
        try:
            second = savemod.open_page(args.save, other)
        except savemod.SaveError:
            second = None
        union = savemod.union_ids(page, *([second] if second else []))
    if args.json:
        doc = report.as_dict()
        if union is not None:
            doc["union_ids"] = len(union)
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    for line in savemod.format_report(report, union=union):
        out(sys.stdout, line)
    if args.confidence:
        for line in savemod.confidence_lines(report):
            out(sys.stdout, line)
    return EXIT_OK



def cmd_fdata_list(args) -> int:
    rutas = fdata.find_fdata(args.path)
    documento = {
        "path": os.path.abspath(args.path),
        "files": [{"file": os.path.abspath(r),
                   "entries": [e.as_dict() for e in fdata.iter_entries(r)]}
                  for r in rutas],
    }
    if args.json:
        json.dump(documento, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    for fichero in documento["files"]:
        entradas = fichero["entries"]
        out(sys.stdout, "%s  %d B  %d entradas"
            % (fichero["file"], os.path.getsize(fichero["file"]), len(entradas)))
        out(sys.stdout, "  %-10s %-11s %10s %10s %12s %10s %10s"
            % ("offset", "tipo", "entry", "comprim.", "sin comprim.", "name_hash", "flags"))
        for e in entradas:
            out(sys.stdout, "  0x%08x %-11s %10d %10d %12d %10s 0x%08x"
                % (e["offset"], e["type"], e["entry_size"], e["compressed_size"],
                   e["uncompressed_size"], e["name_hash"], e["flags"]))
    return EXIT_OK


def cmd_fdata_stat(args) -> int:
    rutas = fdata.find_fdata(args.dir)
    resultado = fdata.scan(rutas, root=os.path.abspath(args.dir))
    if args.json:
        json.dump(resultado.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "romfs     : %s" % resultado.root)
    out(sys.stdout, "ficheros  : %d .fdata, %d B" % (len(resultado.files), resultado.total_size))
    out(sys.stdout, "entradas  : %d" % resultado.total_entries)
    out(sys.stdout, "  %-12s %-10s %9s %11s %16s"
        % ("tipo", "type_ktid", "entradas", "comprim.", "B sin comprimir"))
    for t in resultado.types:
        out(sys.stdout, "  %-12s 0x%08x %9d %11d %16d"
            % (t.name, t.ktid, t.entries, t.compressed, t.uncompressed_bytes))
    return EXIT_OK


def cmd_fdata_extract(args) -> int:
    wanted = fdata.parse_type(args.type)
    rutas = fdata.find_fdata(args.path)
    escritos = []
    for ruta in rutas:
        for entry, destino in fdata.extract(ruta, wanted, args.out):
            escritos.append((ruta, entry, destino))
    if args.json:
        json.dump({
            "out": os.path.abspath(args.out),
            "type": fdata.type_name(wanted),
            "type_ktid": "0x%08x" % wanted,
            "files": [{"fdata": os.path.abspath(r),
                       "entry": e.as_dict(),
                       "written": os.path.abspath(d),
                       "size": os.path.getsize(d)} for r, e, d in escritos],
        }, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s (0x%08x): %d entradas escritas en %s"
        % (fdata.type_name(wanted), wanted, len(escritos), os.path.abspath(args.out)))
    for ruta, entry, destino in escritos:
        out(sys.stdout, "  0x%08x  %10d B  %s  (desde 0x%x de %s)"
            % (entry.name_hash, os.path.getsize(destino), os.path.basename(destino),
               entry.offset, os.path.basename(ruta)))
    return EXIT_OK


def _anim_fuente(args):
    """`(etiqueta, animacion, bytes)` de los argumentos comunes de `pkp anim`."""
    return anim.load(args.ruta, args.hash)


def _anim_rows_from_fdata(ruta: str, *, deep: bool, limite: int | None):
    """Una fila por animacion de un `.fdata`, con cabecera o con parseo entero.

    Las entradas que no son `G2A` (29 de las 17.457 son `G1A_` del formato
    anterior) salen con `format` y `error`, sin tumbar el listado.
    """
    for n, entry in enumerate(anim.source.iter_fdata_entries(ruta)):
        if limite is not None and n >= limite:
            return
        if deep:
            datos = anim.source.read_entry(ruta, entry)
        else:
            datos = anim.source.read_entry(ruta, entry, limit=anim.g2a.HEADER_SIZE)
        fila = {"name_hash": "0x%08x" % entry.name_hash,
                "bytes": entry.uncompressed_size,
                "fdata": os.path.basename(ruta)}
        try:
            cabecera = anim.peek(datos)
        except anim.AnimError as exc:
            magic = struct.unpack_from("<I", datos, 0)[0]
            fila.update({"parseable": False, "error": str(exc),
                         "format": {anim.g2a.MAGIC_G1A: "G1A_",
                                    anim.g2a.MAGIC: "G2A_"}.get(
                                        magic, "0x%08x" % magic),
                         "version": datos[4:8].decode("ascii", "replace"),
                         "frame_rate": None, "length_frames": None,
                         "duration_s": None, "bone_count": None})
            yield fila
            continue
        fila.update(cabecera.as_dict())
        fila["parseable"] = True
        fila["format"] = "G2A_"
        if deep:
            a = anim.parse(datos)
            fila.update({"splines": a.spline_count, "keyframes": a.keyframe_count,
                         "used_blocks": a.used_blocks,
                         "pad_bytes": len(a.pad_bytes)})
        yield fila


def cmd_anim_list(args) -> int:
    filas: list[dict] = []
    if anim.source.es_fdata(args.ruta):
        filas = list(_anim_rows_from_fdata(args.ruta, deep=args.deep,
                                           limite=args.limit))
    else:
        for ruta in anim.source.iter_files(args.ruta):
            with open(ruta, "rb") as fh:
                datos = fh.read(None if args.deep else anim.g2a.HEADER_SIZE)
            cabecera = anim.peek(datos)
            fila = {"name_hash": os.path.basename(ruta), "bytes": os.path.getsize(ruta),
                    "fdata": "-"}
            fila.update(cabecera.as_dict())
            if args.deep:
                with open(ruta, "rb") as fh:
                    a = anim.parse(fh.read())
                fila.update({"splines": a.spline_count, "keyframes": a.keyframe_count,
                             "used_blocks": a.used_blocks,
                             "pad_bytes": len(a.pad_bytes)})
            filas.append(fila)
            if args.limit and len(filas) >= args.limit:
                break
    for fila in filas:
        fila["magic"] = "G2A_"
    if args.json:
        json.dump({"path": os.path.abspath(args.ruta), "count": len(filas),
                   "deep": bool(args.deep), "animations": filas},
                  sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s: %d animaciones" % (os.path.abspath(args.ruta), len(filas)))
    cabecera = "%-12s %9s %6s %6s %8s %6s"
    if args.deep:
        cabecera += " %7s %9s %6s"
    cabecera += "  %s"
    columnas = ("name", "bytes", "fps", "frames", "dur_s", "bones")
    if args.deep:
        columnas += ("splines", "claves", "bloques")
    columnas += ("fdata",)
    out(sys.stdout, cabecera % columnas)
    for fila in filas:
        if not fila.get("parseable", True):
            out(sys.stdout, "%-12s %9d %6s %6s  NO SOPORTADO (formato anterior)"
                % (fila["name_hash"], fila["bytes"], fila["format"],
                   fila["version"]))
            continue
        linea = "%-12s %9d %6.1f %6d %8.3f %6d" % (
            fila["name_hash"], fila["bytes"], fila["frame_rate"],
            fila["length_frames"], fila["duration_s"], fila["bone_count"])
        if args.deep:
            linea += " %7d %9d %6d" % (fila["splines"], fila["keyframes"],
                                       fila["used_blocks"])
        linea += "  %s" % fila["fdata"]
        out(sys.stdout, linea)
    return EXIT_OK


def cmd_anim_info(args) -> int:
    etiqueta, a, datos = _anim_fuente(args)
    reescrito = anim.build(a)
    doc = {
        "name": etiqueta,
        "size": len(datos),
        "sha256": hashlib.sha256(datos).hexdigest(),
        "header": anim.peek(datos).as_dict(),
        "summary": a.as_dict(),
        "reserved": a.reserved,
        "nonzero_pad_bytes": len(a.pad_bytes),
        "rewrite_identical": reescrito == datos,
        "rewrite_sha256": hashlib.sha256(reescrito).hexdigest(),
        "bones": [
            {"bone_id": hueso.bone_id, "bone_id_raw": hueso.bone_id_raw,
             "timing_offset": hueso.timing_offset,
             "splines": [{"opcode": s.opcode, "channel": s.channel,
                          "keyframes": s.keyframe_count,
                          "timings": list(s.timings),
                          "first_data_index": s.first_data_index}
                         for s in hueso.splines]}
            for hueso in a.bones],
    }
    if args.bone is not None:
        doc["bones"] = [b for b in doc["bones"] if b["bone_id"] == args.bone]
        if not doc["bones"]:
            raise anim.AnimError("no hay hueso con id %d" % args.bone)
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    cab = doc["header"]
    out(sys.stdout, "%s  %d B  sha256 %s" % (etiqueta, len(datos),
                                             doc["sha256"][:16] + "..."))
    out(sys.stdout, "  magic          G2A_ (en disco b\"_A2G\", u32 LE 0x4732415f)")
    out(sys.stdout, "  version        %s" % cab["version"])
    out(sys.stdout, "  fileSize       %d" % cab["file_size"])
    out(sys.stdout, "  frameRate      %g  (%d frames = %.3f s)"
        % (cab["frame_rate"], cab["length_frames"], cab["duration_s"]))
    out(sys.stdout, "  boneSection    %d B (%d huesos)"
        % (cab["bone_section_size"], cab["bone_count"]))
    out(sys.stdout, "  timingSection  %d B" % cab["timing_size"])
    out(sys.stdout, "  keyBlocks      %d x 32 B = %d B"
        % (cab["key_block_count"], cab["key_block_count"] * 32))
    out(sys.stdout, "  reserved       %d" % cab["reserved"])
    out(sys.stdout, "  geometria      0x20 + %d + %d + %d = %d  (fichero %d)  %s"
        % (cab["bone_section_size"], cab["timing_size"],
           cab["key_block_count"] * 32, cab["computed_size"], len(datos),
           "OK" if cab["computed_size"] == len(datos) else "NO CUADRA"))
    out(sys.stdout, "  canales        %s" % ", ".join(
        "%s %d" % (k, v) for k, v in doc["summary"]["channels"].items()))
    out(sys.stdout, "  splines        %d   claves totales %d   bloques usados %d/%d"
        % (doc["summary"]["splines"], doc["summary"]["keyframes"],
           doc["summary"]["used_blocks"], cab["key_block_count"]))
    out(sys.stdout, "  relleno no 0   %d registros" % doc["nonzero_pad_bytes"])
    out(sys.stdout, "  reescritura    %s  sha256 %s"
        % ("IDENTICA" if doc["rewrite_identical"] else "DISTINTA",
           doc["rewrite_sha256"][:16] + "..."))
    out(sys.stdout, "  huesos (id, splines, claves por canal):")
    for hueso in doc["bones"][:args.bones]:
        detalle = "  ".join("%s %d" % (s["channel"][:4], s["keyframes"])
                            for s in hueso["splines"])
        out(sys.stdout, "    %5d  %d  %s" % (hueso["bone_id"], len(hueso["splines"]),
                                             detalle))
    if len(doc["bones"]) > args.bones:
        out(sys.stdout, "    ... %d huesos mas (--json para todos)"
            % (len(doc["bones"]) - args.bones))
    return EXIT_OK


def cmd_anim_export(args) -> int:
    etiqueta, a, datos = _anim_fuente(args)
    formato = args.format
    if formato == "auto":
        formato = "csv" if args.out.lower().endswith(".csv") else "json"
    paths.guard_writable(args.out)
    if formato == "csv":
        filas = anim.write_csv(a, args.out)
        if args.json:
            json.dump({"out": os.path.abspath(args.out), "format": "csv",
                       "rows": filas, "summary": a.as_dict()},
                      sys.stdout, indent=2, ensure_ascii=False)
            out(sys.stdout)
            return EXIT_OK
        out(sys.stdout, "%s -> %s (csv, %d filas)" % (etiqueta, args.out, filas))
        return EXIT_OK
    doc = anim.to_json(a, name=etiqueta, size=len(datos),
                       sha256=hashlib.sha256(datos).hexdigest())
    anim.write_json(doc, args.out)
    if args.json:
        json.dump({"out": os.path.abspath(args.out), "format": "json",
                   "summary": a.as_dict()}, sys.stdout, indent=2,
                  ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s -> %s (json sin perdida: %d huesos, %d bloques)"
        % (etiqueta, args.out, a.bone_count, len(a.key_blocks)))
    return EXIT_OK


def cmd_anim_build(args) -> int:
    doc = anim.read_json(args.documento)
    a = anim.from_json(doc)
    datos = anim.build(a)
    paths.guard_writable(args.out)
    with open(args.out, "wb") as fh:
        fh.write(datos)
    original = doc.get("source", {}).get("sha256")
    nuevo = hashlib.sha256(datos).hexdigest()
    identico = original == nuevo if original else None
    if args.json:
        json.dump({"out": os.path.abspath(args.out), "size": len(datos),
                   "sha256": nuevo, "source_sha256": original,
                   "identical": identico, "summary": a.as_dict()},
                  sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s -> %s  %d B  sha256 %s" % (args.documento, args.out,
                                                   len(datos), nuevo))
    out(sys.stdout, "  origen declarado %s   %s"
        % (original or "(no consta)",
           "IDENTICO" if identico else ("DISTINTO" if identico is False else "")))
    return EXIT_OK


def cmd_anim_roundtrip(args) -> int:
    etiqueta, a, datos = _anim_fuente(args)
    reescrito = anim.build(a)
    if args.out:
        paths.guard_writable(args.out)
        with open(args.out, "wb") as fh:
            fh.write(reescrito)
    antes = hashlib.sha256(datos).hexdigest()
    despues = hashlib.sha256(reescrito).hexdigest()
    doc = {"name": etiqueta, "size": len(datos), "size_rewritten": len(reescrito),
           "sha256": antes, "sha256_rewritten": despues,
           "identical": datos == reescrito, "out": os.path.abspath(args.out)
           if args.out else None, "summary": a.as_dict()}
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s  %d B" % (etiqueta, len(datos)))
    out(sys.stdout, "  sha256 original  %s" % antes)
    out(sys.stdout, "  sha256 reescrito %s" % despues)
    out(sys.stdout, "  %s%s" % ("IDENTICO byte a byte" if doc["identical"]
                                else "DISTINTO",
                                " (%s)" % args.out if args.out else ""))
    return EXIT_OK


def cmd_anim_set(args) -> int:
    etiqueta, a, datos = _anim_fuente(args)
    if not anim.source.es_fdata(args.ruta):
        # cambiar un valor no puede tocar el fichero de entrada
        paths.guard_writable(args.ruta)
    parte = anim.set_keyframe_value(a, bone_id=args.bone, channel=args.channel,
                                    frame=args.frame, axis=args.axis,
                                    value=args.value)
    reescrito = anim.build(a)
    paths.guard_writable(args.out)
    with open(args.out, "wb") as fh:
        fh.write(reescrito)
    # relectura desde disco: el valor cambiado y nada mas
    with open(args.out, "rb") as fh:
        verificado = anim.parse(fh.read())
    hueso = verificado.bone_by_id(args.bone)
    spline = next(s for s in hueso.splines if s.channel == args.channel)
    vuelta = {"x": 0, "y": 1, "z": 2}[args.axis]
    fila = spline.keys[spline.timings.index(args.frame)].rows[0].vector
    doc = {
        "name": etiqueta, "out": os.path.abspath(args.out), "change": parte,
        "size_before": len(datos), "size_after": len(reescrito),
        "sha256_before": hashlib.sha256(datos).hexdigest(),
        "sha256_after": hashlib.sha256(reescrito).hexdigest(),
        "readback": {"x": fila[0], "y": fila[1], "z": fila[2]},
        "readback_axis": fila[vuelta],
        "same_size": len(datos) == len(reescrito),
        "valid_after": True,
    }
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s  ->  %s" % (etiqueta, args.out))
    out(sys.stdout, "  cambiado hueso %d, canal %s, frame %d, eje %s: %g -> %g"
        % (parte["bone_id"], parte["channel"], parte["frame"], parte["axis"],
           parte["before"], parte["after"]))
    out(sys.stdout, "  pedido %g, leido de vuelta %g (campo de 20 bits, exp %d)"
        % (parte["requested"], doc["readback_axis"],
           anim.g2a.Row.from_int(parte["row_after"]).exp))
    out(sys.stdout, "  int64 fila c0  0x%016x -> 0x%016x"
        % (parte["row_before"] & 0xFFFFFFFFFFFFFFFF,
           parte["row_after"] & 0xFFFFFFFFFFFFFFFF))
    out(sys.stdout, "  tamano %d -> %d   %s" % (len(datos), len(reescrito),
                                                 "igual" if doc["same_size"] else "DISTINTO"))
    out(sys.stdout, "  fichero releido y valido: %d huesos" % verificado.bone_count)
    return EXIT_OK


def _catalog(args):
    """Catalogo del romfs: `--container` manda sobre `PKP_ROMFS`/`./romfs`."""
    from . import catalog as catmod

    return catmod.load(args.container or paths.configured_romfs())


def _catalog_entries(cat, nombres) -> list[dict]:
    return [{"name": n, "hash": "0x%08X" % cat.hashes[n]} for n in nombres]


def cmd_catalog_list(args) -> int:
    """Una linea por entidad en stdout; el resumen va a stderr.

    Asi `pkp catalog list | wc -l` da el recuento exacto y el resumen no
    ensucia la salida que se quiera comparar o volcar a un fichero.
    """
    cat = _catalog(args)
    nombres = cat.names_with_prefix(args.prefix)
    if args.json:
        doc = cat.as_dict()
        doc.update({"count": len(nombres), "prefix": args.prefix,
                    "entries": _catalog_entries(cat, nombres)})
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    for nombre in nombres:
        out(sys.stdout, "0x%08X  %s" % (cat.hashes[nombre], nombre))
    reparto = ", ".join("%s %d" % (p, n) for p, n in
                        sorted(cat.by_prefix.items(), key=lambda kv: -kv[1]))
    out(sys.stderr, "# %d entidades%s de %s"
        % (len(nombres), " con prefijo %s" % args.prefix if args.prefix else "",
           os.path.basename(cat.source)))
    out(sys.stderr, "# reparto: %s" % reparto)
    return EXIT_OK


def cmd_catalog_find(args) -> int:
    cat = _catalog(args)
    nombres = cat.find(args.text)
    if args.json:
        doc = cat.as_dict()
        doc.update({"query": args.text, "count": len(nombres),
                    "entries": _catalog_entries(cat, nombres)})
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    for nombre in nombres:
        out(sys.stdout, "0x%08X  %s" % (cat.hashes[nombre], nombre))
    out(sys.stderr, "# %d de %d entidades contienen %r (sin distinguir mayusculas)"
        % (len(nombres), len(cat.names), args.text))
    return EXIT_OK if nombres else EXIT_INVALID


def _parse_type_hash(arg: str) -> int:
    """`--type` de `pkp objdb`: un `type_hash` en hex, con o sin `0x`."""
    texto = arg.strip()
    try:
        valor = int(texto[2:] if texto.lower().startswith("0x") else texto, 16)
    except ValueError:
        raise UsageError(
            "--type espera un type_hash en hex, no %r\n"
            "  ejemplo: --type 0x18eb1e56 (los valores salen de `pkp objdb stat`)"
            % arg, code="usage") from None
    if not 0 <= valor <= 0xFFFFFFFF:
        raise UsageError("--type %r se sale de 32 bits" % arg, code="usage")
    return valor


def _record_lines(record, cabecera: str) -> list[str]:
    """Un registro en texto: cabecera y un renglon por par con sus valores."""
    lineas = ["%s id %d  type_hash 0x%08x  offset 0x%08x  %d B  %d pares"
              % (cabecera, record.id, record.type_hash, record.offset,
                 record.size, record.n_pairs)]
    for par in record.pairs:
        valores = " ".join("0x%08x" % v for v in par.values) or "(sin valor)"
        lineas.append("    0x%08x  kind %d  %2d valores: %s"
                      % (par.hash, par.kind, par.n_values, valores))
    return lineas


def cmd_objdb_stat(args) -> int:
    db = objdb.load(args.romfs)
    if args.json:
        json.dump(db.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    fuente = db.origin or "?"
    out(sys.stdout, "romfs     : %s" % os.path.abspath(args.romfs))
    out(sys.stdout, "fichero   : %s" % fuente)
    if db.source_entry is not None:
        out(sys.stdout, "            kidsobjdb name_hash 0x%08x  %d B comprimidos"
            % (db.source_entry.name_hash, db.source_entry.compressed_size))
    out(sys.stdout, "cabecera  : %r  %d B  registro %d B  declarados %d"
        % (objdb.FILE_MAGIC, db.header_size, db.record_header_size, db.declared_count))
    out(sys.stdout, "registros : %d" % db.count)
    out(sys.stdout, "pares     : %d  (tríos kind/hash/valores)" % db.pair_count)
    out(sys.stdout, "type_hash : %d distintos" % len(db.by_type))
    out(sys.stdout, "por tamaño de registro:")
    for fila in db.by_size:
        out(sys.stdout, "  %4d B  %8d" % (fila.size, fila.records))
    tope = 20
    out(sys.stdout, "por type_hash (top %d de %d):" % (min(tope, len(db.by_type)),
                                                       len(db.by_type)))
    for fila in db.by_type[:tope]:
        out(sys.stdout, "  0x%08x  %8d" % (fila.type_hash, fila.records))
    cola = db.by_type[tope:]
    if cola:
        out(sys.stdout, "  cola: %d type_hash con %d registros (%d..%d por tipo)"
            % (len(cola), sum(c.records for c in cola),
               cola[-1].records, cola[0].records))
    return EXIT_OK


def cmd_objdb_dump(args) -> int:
    if args.limit < 0:
        raise UsageError("--limit no puede ser negativo (%d)" % args.limit, code="usage")
    wanted = _parse_type_hash(args.type)
    db = objdb.load(args.romfs)
    total = sum(t.records for t in db.by_type if t.type_hash == wanted)
    if total == 0:
        out(sys.stderr, "ERROR: ningun registro con type_hash 0x%08x en %s"
            % (wanted, db.origin or args.romfs))
        return EXIT_INVALID
    limite = args.limit or total
    vistos = []
    for record in db.records_of(wanted):
        if len(vistos) >= limite:
            break
        vistos.append(record)
    if args.json:
        json.dump({
            "type_hash": "0x%08x" % wanted,
            "total": total,
            "shown": len(vistos),
            "records": [r.as_dict() for r in vistos],
        }, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "0x%08x: %d registros, mostrando %d" % (wanted, total, len(vistos)))
    for i, record in enumerate(vistos):
        for linea in _record_lines(record, "[%d]" % i):
            out(sys.stdout, linea)
    return EXIT_OK


def cmd_objdb_id(args) -> int:
    db = objdb.load(args.romfs)
    record = db.find(args.id)
    if args.json:
        json.dump({"id": args.id, "found": record is not None,
                   "record": record.as_dict() if record else None},
                  sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK if record is not None else EXIT_INVALID
    if record is None:
        out(sys.stderr, "ERROR: ningun registro con id %d en %s"
            % (args.id, db.origin or args.romfs))
        return EXIT_INVALID
    for linea in _record_lines(record, "registro"):
        out(sys.stdout, linea)
    return EXIT_OK


# --------------------------------------------------------------------------
# Sonido: bancos ASRS/KTSR de los `.srsa`
# --------------------------------------------------------------------------

def _snd_line(stream) -> str:
    return ("#%-4d %-8s %3d ch %6d Hz %9d muestras %7.3f s  %10d B  id %-10d %s"
            % (stream.index, stream.codec, stream.channels, stream.sample_rate,
               stream.num_samples, stream.duration, stream.data_size,
               stream.sound_id, stream.name))


def cmd_snd_list(args) -> int:
    banco, _ = snd.read_bank(args.bank)
    if args.json:
        doc = banco.as_dict()
        doc.update({"codecs": banco.codecs,
                    "streams": [s.as_dict() for s in banco.streams]})
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s  %d B  audio_id 0x%08x  %d chunks  %d streams  %s"
        % (os.path.abspath(args.bank), banco.size, banco.audio_id,
           len(banco.chunks), len(banco.streams), banco.codecs))
    for stream in banco.streams:
        out(sys.stdout, _snd_line(stream))
    return EXIT_OK


def cmd_snd_extract(args) -> int:
    escritos = snd.extract(args.bank, args.out, args.stream or None)
    if args.json:
        json.dump({
            "bank": os.path.abspath(args.bank),
            "out": os.path.abspath(args.out),
            "files": [{"stream": s.as_dict(), "written": os.path.abspath(p),
                       "size": os.path.getsize(p),
                       "sha256": paths.sha256_file(p)} for s, p in escritos],
        }, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%d streams escritos en %s"
        % (len(escritos), os.path.abspath(args.out)))
    for stream, destino in escritos:
        out(sys.stdout, "  %s  %10d B  %s"
            % (os.path.basename(destino), os.path.getsize(destino), stream.name))
    return EXIT_OK


def cmd_snd_replace(args) -> int:
    if args.swap and (args.stream or args.file):
        out(sys.stderr, "ERROR: --swap no se combina con --stream/--file")
        return EXIT_USAGE
    if not args.swap and not (args.stream and args.file):
        out(sys.stderr,
            "ERROR: falta la sustitucion: --swap A B, o --stream N --file <flujo>")
        return EXIT_USAGE
    destino = args.out or args.bank
    if destino == args.bank and not args.in_place:
        out(sys.stderr,
            "ERROR: para escribir sobre el propio banco hace falta --in-place\n"
            "  (deja una copia <banco>.orig la primera vez); si no, usa -o <salida>")
        return EXIT_USAGE
    banco, data = snd.read_bank(args.bank)
    antes = paths.sha256_file(args.bank)

    if args.swap:
        modificado = snd.swap_streams(data, args.swap[0], args.swap[1])
        detalle = {"swap": list(args.swap)}
    else:
        with open(args.file, "rb") as fh:
            nuevo = fh.read()
        donor = None
        if (args.from_banco is None) != (args.from_stream is None):
            out(sys.stderr, "ERROR: --from-banco y --from-stream van juntos")
            return EXIT_USAGE
        if args.from_banco is not None:
            origen, origen_data = snd.read_bank(args.from_banco)
            donor = (origen_data, origen.stream(args.from_stream))
        modificado = snd.replace_stream(data, args.stream, nuevo, donor)
        detalle = {"stream": args.stream, "bytes": len(nuevo),
                   "donor": args.from_banco, "donor_stream": args.from_stream}

    snd.write_bank(destino, modificado)
    despues = paths.sha256_file(destino)
    verificado = snd.parse(modificado)
    if args.json:
        doc = {"source": os.path.abspath(args.bank), "written": os.path.abspath(destino),
               "sha256_before": antes, "sha256_after": despues,
               "size_before": len(data), "size_after": len(modificado),
               "streams_before": len(banco.streams),
               "streams_after": len(verificado.streams),
               "backup": destino + ".orig" if os.path.exists(destino + ".orig") else None}
        doc.update(detalle)
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "escrito   : %s" % os.path.abspath(destino))
    out(sys.stdout, "sha256    : %s" % antes)
    out(sys.stdout, "         -> %s" % despues)
    out(sys.stdout, "tamano    : %d -> %d B" % (len(data), len(modificado)))
    out(sys.stdout, "streams   : %d (el banco modificado vuelve a analizarse)" % len(verificado.streams))
    if os.path.exists(destino + ".orig"):
        out(sys.stdout, "original  : %s" % (destino + ".orig"))
    return EXIT_OK


def cmd_snd_import(args) -> int:
    """Mete un WAV propio en un stream del banco (MS ADPCM o KA1A)."""
    from . import audio as pkp_audio

    destino = args.out or args.bank
    if destino == args.bank and not args.in_place:
        out(sys.stderr,
            "ERROR: para escribir sobre el propio banco hace falta --in-place\n"
            "  (deja una copia <banco>.orig la primera vez); si no, usa -o <salida>")
        return EXIT_USAGE
    banco, data = snd.read_bank(args.bank)
    stream = banco.stream(args.stream)
    antes = paths.sha256_file(args.bank)

    if stream.external:
        out(sys.stderr, "ERROR: el stream %d es externo: su audio no esta en este banco"
            % stream.index)
        return EXIT_INVALID
    if stream.codec not in ("msadpcm", "ka1a"):
        out(sys.stderr,
            "ERROR: el stream %d es %s y este kit codifica MS ADPCM y KA1A.\n"
            "  De los %d streams con datos dentro del banco, esos son los dos\n"
            "  codecs que llevan audio; ver docs/AUDIO-PROPIO.md."
            % (stream.index, stream.codec, len(banco.streams)))
        return EXIT_INVALID

    muestras, rate, canales = pkp_audio.read_wav(args.wav)
    if canales != 1:
        out(sys.stderr,
            "ERROR: %s tiene %d canales y los streams del banco son mono;\n"
            "  exporta el canal que quieras con `ffmpeg -ac 1`" % (args.wav, canales))
        return EXIT_USAGE

    if stream.codec == "msadpcm":
        bloque = snd.msadpcm_block_size(data, stream)
        payload = pkp_audio.msadpcm_encode(muestras, bloque)
        nuevo = snd.StreamAudio(codec="msadpcm", sample_rate=rate,
                                num_samples=len(muestras), payload=payload,
                                block_size=bloque, loop_start=args.loop)
        codificador = "msadpcm propio (bloque %d B)" % bloque
        decodificado = pkp_audio.msadpcm_decode(payload, bloque, len(muestras))
        snr = pkp_audio.msadpcm_snr_db(muestras, decodificado)
        detalle = "%d B en %d bloques de %d B" % (len(payload),
                                                  len(payload) // bloque, bloque)
        error_maximo = max((abs(muestras[i] - decodificado[i])
                            for i in range(len(decodificado))), default=0)
    else:
        modo = snd.ka1a_bitrate_mode(data, stream)
        try:
            payload = pkp_audio.ka1a_encode(muestras, modo)
        except pkp_audio.AudioError as exc:
            out(sys.stderr, "ERROR: %s" % exc)
            return EXIT_INVALID
        nuevo = snd.StreamAudio(codec="ka1a", sample_rate=rate,
                                num_samples=len(muestras), payload=payload,
                                loop_start=args.loop, bitrate_mode=modo)
        tramas = pkp_audio.ka1a_frame_count(len(muestras))
        codificador = ("ka1a propio (modo %+d, frame de %d B)"
                       % (modo, pkp_audio.ka1a_frame_size(modo)))
        decodificado = pkp_audio.ka1a_decode(payload, modo, len(muestras))
        snr = pkp_audio.ka1a_snr_db(muestras, decodificado)
        detalle = "%d B en %d frames de %d B" % (len(payload), tramas,
                                                 pkp_audio.ka1a_frame_size(modo))
        error_maximo = max((abs(muestras[i] / 32767.0 - decodificado[i])
                            for i in range(len(decodificado))), default=0.0)

    modificado = snd.set_stream_audio(data, args.stream, nuevo)
    snd.write_bank(destino, modificado)
    despues = paths.sha256_file(destino)
    verificado = snd.parse(modificado)
    comprobado = verificado.stream(args.stream)

    if args.json:
        doc = {"source": os.path.abspath(args.bank), "written": os.path.abspath(destino),
               "sha256_before": antes, "sha256_after": despues,
               "size_before": len(data), "size_after": len(modificado),
               "streams_before": len(banco.streams),
               "streams_after": len(verificado.streams),
               "wav": os.path.abspath(args.wav),
               "audio": nuevo.as_dict(),
               "encoder": codificador,
               "encoded": detalle,
               "snr_db": round(snr, 3),
               "backup": destino + ".orig" if os.path.exists(destino + ".orig") else None}
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "WAV       : %s (%d muestras, %d Hz, %s)"
        % (os.path.abspath(args.wav), len(muestras), rate,
           "mono" if canales == 1 else "%d canales" % canales))
    out(sys.stdout, "codificado: %s (SNR ida y vuelta %s, error maximo %s)"
        % (detalle, "%.2f dB" % snr if snr is not None else "n/d",
           ("%.0f LSB" % (error_maximo * 32767)) if stream.codec == "ka1a"
           else "%.0f LSB" % error_maximo))
    out(sys.stdout, "encoder   : %s" % codificador)
    out(sys.stdout, "stream    : %d  %d Hz, %d muestras, %.3f s, bucle %d"
        % (comprobado.index, comprobado.sample_rate, comprobado.num_samples,
           comprobado.duration, comprobado.loop_start))
    out(sys.stdout, "escrito   : %s" % os.path.abspath(destino))
    out(sys.stdout, "sha256    : %s" % antes)
    out(sys.stdout, "         -> %s" % despues)
    out(sys.stdout, "tamano    : %d -> %d B" % (len(data), len(modificado)))
    out(sys.stdout, "streams   : %d (el banco modificado vuelve a analizarse)"
        % len(verificado.streams))
    if os.path.exists(destino + ".orig"):
        out(sys.stdout, "original  : %s" % (destino + ".orig"))
    return EXIT_OK


def cmd_snd_stat(args) -> int:
    rutas = snd.find_banks(args.dir)
    stats = snd.scan_folder(rutas)
    if args.json:
        json.dump(stats.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "bancos    : %d" % stats.banks)
    out(sys.stdout, "streams   : %d (%d con datos dentro del banco)"
        % (stats.streams, stats.internal))
    out(sys.stdout, "codecs    : %s" % dict(sorted(stats.codecs.items())))
    out(sys.stdout, "swap      : %d streams internos con otro en su banco (%.1f%%)"
        % (stats.swappable,
           100.0 * stats.swappable / stats.internal if stats.internal else 0.0))
    out(sys.stdout, "mismo tam.: %d comparten (codec, tamano) en su banco; "
        "%d en todo el arbol (%d grupos)"
        % (stats.same_size_same_bank, stats.same_size_anywhere,
           stats.same_size_groups))
    if stats.problems:
        out(sys.stdout, "problemas : %d" % len(stats.problems))
        for problema in stats.problems[:10]:
            out(sys.stdout, "  " + problema)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="pkp",
        description="Kit de datos de Pokemon Pokopia: contenedor KTGL y mods declarativos")
    ap.add_argument("--container", default=None,
                    help="carpeta del contenedor (por defecto PKP_ROMFS o ./romfs)")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    # Permite escribir --container tambien despues del subcomando:
    #   pkp mod apply ejemplos/x --container build/copia
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--container", default=argparse.SUPPRESS,
                        help="carpeta del contenedor (igual que la opcion global)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="salida JSON (igual que la opcion global)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="que hay en el contenedor y que tablas conocemos",
                       parents=[common])
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("table", help="volcar una tabla con su geometria", parents=[common])
    p.add_argument("table", type=int)
    p.add_argument("--rows", default=None, help="a:b (por defecto 0:20)")
    p.set_defaults(func=cmd_table)

    p = sub.add_parser("row", help="una fila campo a campo (o un bloque de texto)",
                       parents=[common])
    p.add_argument("table", type=int)
    p.add_argument("row", type=int)
    p.set_defaults(func=cmd_row)

    p = sub.add_parser("dump", help="escribir el payload descomprimido de una entrada",
                       parents=[common])
    p.add_argument("entry", type=int)
    p.add_argument("out")
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("repack", help="reempaquetar el contenedor y comprobar identidad",
                       parents=[common])
    p.add_argument("outdir")
    p.add_argument("--recompress", action="store_true",
                   help="recomprimir todo (lento; identidad byte a byte con zlib stock)")
    p.add_argument("--backend", choices=("auto", "stdlib", "stock"), default="auto")
    p.set_defaults(func=cmd_repack)

    mod = sub.add_parser("mod", help="mods declarativos (mod.json)")
    msub = mod.add_subparsers(dest="modcmd", required=True)

    p = msub.add_parser("new", help="esqueleto de mod.json", parents=[common])
    p.add_argument("name")
    p.add_argument("--dir", default=None)
    p.set_defaults(func=cmd_mod_new)

    p = msub.add_parser("validate", help="esquema, rangos, md5 y expect", parents=[common])
    p.add_argument("mod")
    p.add_argument("--no-expect", action="store_true",
                   help="no comparar expect contra el contenedor")
    p.add_argument("--no-container", action="store_true",
                   help="no abrir el contenedor (solo esquema)")
    p.set_defaults(func=cmd_mod_validate)

    p = msub.add_parser("merge", help="componer dos mods", parents=[common])
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("-o", "--out", default=None, help="carpeta de salida")
    p.add_argument("--name", default=None)
    p.add_argument("--version", default="0.1.0")
    p.set_defaults(func=cmd_mod_merge)

    p = msub.add_parser("apply", help="aplicar a una COPIA (dry-run por defecto)",
                        parents=[common])
    p.add_argument("mod")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="no escribe nada (por defecto)")
    g.add_argument("--yes", action="store_true", help="escribe en la copia")
    p.add_argument("--keep-backup", dest="no_backup", action="store_false",
                   help="guardar copia de los ficheros (por defecto si)")
    p.add_argument("--no-backup", dest="no_backup", action="store_true",
                   help="no guardar backup")
    p.set_defaults(no_backup=False)
    p.set_defaults(func=cmd_mod_apply)

    save = sub.add_parser("save", help="save: inventario y escritura con copia")
    ssub = save.add_subparsers(dest="savecmd", required=True)

    def add_save_opts(parser):
        parser.add_argument("--save", default=None,
                            help="carpeta del save (por defecto PKP_SAVE o ./save)")
        parser.add_argument("--page", default="G00", choices=tuple(savemod.PAGES),
                            help="pagina del save (por defecto G00)")

    p = ssub.add_parser("read", help="inventario y geometria de una pagina",
                        parents=[common])
    add_save_opts(p)
    p.add_argument("--all", action="store_true", help="incluye los huecos vacios")
    p.set_defaults(func=cmd_save_read)

    p = ssub.add_parser("write", help="escribir un hueco del inventario (dry-run por defecto)",
                        parents=[common])
    add_save_opts(p)
    p.add_argument("--slot", type=int, required=True, help="hueco 0..129")
    p.add_argument("--id", type=int, default=None, help="id de objeto (13 bits)")
    p.add_argument("--count", type=int, default=None, help="cantidad 0..255")
    p.add_argument("--variant", type=int, default=None,
                   help="bits 13..31 del campo (variante/colocacion)")
    p.add_argument("--target", default=None,
                   help="fichero a escribir (por defecto, sobre el mismo CMNDAT)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="no escribe nada (por defecto)")
    g.add_argument("--yes", action="store_true", help="escribe de verdad, con copia")
    p.add_argument("--allow-live-save", action="store_true",
                   help="permite escribir dentro del save del emulador (peligroso)")
    p.add_argument("--level", type=int, default=1, help="nivel zlib del cuerpo (0..9; el juego usa 1)")
    p.add_argument("--strategy", default="default",
                   choices=("default", "fixed", "filtered"),
                   help="estrategia zlib del cuerpo (por defecto la del juego)")
    p.add_argument("--memlevel", type=int, default=8,
                   help="memLevel de zlib (1..9; el juego usa 8)")
    p.set_defaults(func=cmd_save_write)

    p = ssub.add_parser("undo", help="deshacer una escritura desde su copia",
                        parents=[common])
    p.add_argument("backup", help="fichero de build/backups/...")
    p.add_argument("--yes", action="store_true", help="restaura (por defecto simula)")
    p.set_defaults(func=cmd_save_undo)

    p = sub.add_parser("progress", help="parte de progreso del save (solo cifras)",
                       parents=[common])
    add_save_opts(p)
    p.add_argument("--union", action="store_true",
                   help="cuenta tambien los ids distintos de la otra pagina")
    p.add_argument("--confidence", action="store_true",
                   help="añade confianza y evidencia de cada cifra")
    p.set_defaults(func=cmd_progress)

    fd = sub.add_parser("fdata", help="contenedores .fdata (PDRK/IDRK): listar, contar y extraer")
    fdsub = fd.add_subparsers(dest="fdcmd", required=True)

    p = fdsub.add_parser("list", help="cabeceras de todas las entradas de un .fdata",
                         parents=[common])
    p.add_argument("path", help="fichero .fdata (o carpeta con varios)")
    p.set_defaults(func=cmd_fdata_list)

    p = fdsub.add_parser("stat", help="recuento por type_ktid de todos los .fdata",
                         parents=[common])
    p.add_argument("dir", help="carpeta romfs (recorre los .fdata de dentro)")
    p.set_defaults(func=cmd_fdata_stat)

    p = fdsub.add_parser("extract", help="descomprimir las entradas de un tipo a una carpeta",
                         parents=[common])
    p.add_argument("path", help="fichero .fdata (o carpeta con varios)")
    p.add_argument("--type", required=True,
                   help="tipo de entrada: nombre (kidsobjdb, g1t, ...) o hex 0x20a6a0bb")
    p.add_argument("--out", required=True, help="carpeta de salida (nunca dentro del romfs)")
    p.set_defaults(func=cmd_fdata_extract)

    tex = sub.add_parser("tex", help="texturas G1T: listar, censar, sacar a PNG y reinyectar")
    tsub = tex.add_subparsers(dest="texcmd", required=True)

    p = tsub.add_parser("list", help="texturas de un .g1t o de un .fdata, con geometria",
                        parents=[common])
    p.add_argument("path", help="fichero .g1t, .fdata o carpeta con .g1t")
    p.set_defaults(func=texcmd.cmd_tex_list)

    p = tsub.add_parser("stat", help="censo de formatos de todo el romfs y %% escribible",
                        parents=[common])
    p.add_argument("romfs", help="carpeta romfs (recorre los .fdata de dentro)")
    p.set_defaults(func=texcmd.cmd_tex_stat)

    p = tsub.add_parser("extract", help="textura a PNG (solo el nivel 0, sin perdida)",
                        parents=[common])
    p.add_argument("path", help="fichero .g1t o .fdata")
    p.add_argument("--out", required=True,
                   help="PNG de salida, o carpeta (termina en separador) para varios")
    p.add_argument("--index", type=int, default=None, help="que textura del .g1t (por defecto 0)")
    p.add_argument("--g1t", type=int, default=0, help="que .g1t del .fdata (por defecto 0)")
    p.add_argument("--all", action="store_true", help="todas las texturas del .g1t")
    p.set_defaults(func=texcmd.cmd_tex_extract)

    p = tsub.add_parser("inject", help="reinyectar pixeles en un .g1t (mismo tamano)",
                        parents=[common])
    p.add_argument("path", help="fichero .g1t o .fdata")
    p.add_argument("--out", required=True, help="fichero de salida (.g1t)")
    p.add_argument("--index", type=int, default=None, help="que textura del .g1t (por defecto 0)")
    p.add_argument("--g1t", type=int, default=0, help="que .g1t del .fdata (por defecto 0)")
    grupo = p.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--png", help="PNG con los pixeles nuevos (mismas dimensiones)")
    grupo.add_argument("--same", action="store_true",
                       help="reescribir la misma textura sin tocar pixeles (round-trip neutro)")
    p.set_defaults(func=texcmd.cmd_tex_inject)

    an = sub.add_parser("anim",
                        help="animaciones G2A (tipo g1a del .fdata): listar, ver, exportar, reescribir")
    ansub = an.add_subparsers(dest="animcmd", required=True)

    p = ansub.add_parser("list", help="una linea por animacion (de un .fdata o de una carpeta)",
                         parents=[common])
    p.add_argument("ruta", help=".fdata, fichero .g1a/.g2a o carpeta con ellos")
    p.add_argument("--deep", action="store_true",
                   help="parsea entera cada animacion (splines, claves, bloques)")
    p.add_argument("--limit", type=int, default=None,
                   help="como mucho N animaciones (para probar sin recorrer las 17.457)")
    p.set_defaults(func=cmd_anim_list)

    p = ansub.add_parser("info", help="cabecera campo a campo, huesos y reescritura",
                         parents=[common])
    p.add_argument("ruta", help="fichero .g1a/.g2a, o un .fdata con --hash")
    p.add_argument("--hash", type=lambda s: int(s, 0), default=None,
                   help="name_hash de la entrada cuando `ruta` es un .fdata")
    p.add_argument("--bone", type=int, default=None, help="solo este hueso")
    p.add_argument("--bones", type=int, default=12,
                   help="cuantos huesos listar en la salida de texto (12)")
    p.set_defaults(func=cmd_anim_info)

    p = ansub.add_parser("export", help="volcar a JSON sin perdida o a CSV horneado",
                         parents=[common])
    p.add_argument("ruta", help="fichero .g1a/.g2a, o un .fdata con --hash")
    p.add_argument("--hash", type=lambda s: int(s, 0), default=None,
                   help="name_hash de la entrada cuando `ruta` es un .fdata")
    p.add_argument("--out", required=True, help="fichero de salida (.json o .csv)")
    p.add_argument("--format", choices=("auto", "json", "csv"), default="auto",
                   help="auto: csv si --out acaba en .csv, si no json")
    p.set_defaults(func=cmd_anim_export)

    p = ansub.add_parser("build", help="reconstruir el .g1a desde el JSON exportado",
                         parents=[common])
    p.add_argument("documento", help="JSON exportado con `pkp anim export --format json`")
    p.add_argument("--out", required=True, help="fichero .g1a/.g2a de salida")
    p.set_defaults(func=cmd_anim_build)

    p = ansub.add_parser("roundtrip", help="leer y reescribir, y comparar el sha256",
                         parents=[common])
    p.add_argument("ruta", help="fichero .g1a/.g2a, o un .fdata con --hash")
    p.add_argument("--hash", type=lambda s: int(s, 0), default=None,
                   help="name_hash de la entrada cuando `ruta` es un .fdata")
    p.add_argument("--out", default=None, help="opcional: escribir lo reescrito")
    p.set_defaults(func=cmd_anim_roundtrip)

    p = ansub.add_parser("set", help="cambiar un valor de una clave y reinyectar",
                         parents=[common])
    p.add_argument("ruta", help="fichero .g1a/.g2a, o un .fdata con --hash")
    p.add_argument("--hash", type=lambda s: int(s, 0), default=None,
                   help="name_hash de la entrada cuando `ruta` es un .fdata")
    p.add_argument("--bone", type=int, required=True, help="id del hueso")
    p.add_argument("--channel", required=True, choices=("rotation", "translation", "scale"),
                   help="canal a tocar")
    p.add_argument("--frame", type=int, required=True, help="frame de la clave")
    p.add_argument("--axis", required=True, choices=("x", "y", "z"),
                   help="componente a cambiar")
    p.add_argument("--value", type=float, required=True, help="valor nuevo")
    p.add_argument("--out", required=True, help="fichero de salida (nunca el de entrada)")
    p.set_defaults(func=cmd_anim_set)

    cat = sub.add_parser("catalog",
                         help="catalogo de entidades (2.043 nombres) y su hash KT")
    csub = cat.add_subparsers(dest="catcmd", required=True)

    p = csub.add_parser("list", help="las entidades del catalogo, con su hash",
                        parents=[common])
    p.add_argument("--prefix", default=None,
                   choices=("BP", "PM", "BI", "PC", "AP"),
                   help="solo una categoria (por defecto, todas)")
    p.set_defaults(func=cmd_catalog_list)

    p = csub.add_parser("find", help="buscar entidades por subcadena del nombre",
                        parents=[common])
    p.add_argument("text", help="texto a buscar (sin distinguir mayusculas)")
    p.set_defaults(func=cmd_catalog_find)

    ob = sub.add_parser("objdb", help="bases kidsobjdb (_DOK0000/IDOK0000): contar, volcar y buscar")
    obsub = ob.add_subparsers(dest="objcmd", required=True)

    p = obsub.add_parser("stat", help="recuento por tamano y por type_hash de la base mayor",
                         parents=[common])
    p.add_argument("romfs", help="carpeta romfs (o un .fdata, o un kidsobjdb ya extraido)")
    p.set_defaults(func=cmd_objdb_stat)

    p = obsub.add_parser("dump", help="registros de un type_hash, con su id y sus trios",
                         parents=[common])
    p.add_argument("romfs", help="carpeta romfs (o un .fdata, o un kidsobjdb ya extraido)")
    p.add_argument("--type", required=True, help="type_hash en hex, p. ej. 0x18eb1e56")
    p.add_argument("--limit", type=int, default=10,
                   help="cuantos registros volcar (por defecto 10; 0 = todos)")
    p.set_defaults(func=cmd_objdb_dump)

    p = obsub.add_parser("id", help="un registro por su id unico", parents=[common])
    p.add_argument("romfs", help="carpeta romfs (o un .fdata, o un kidsobjdb ya extraido)")
    p.add_argument("id", type=int, help="id del registro (campo +0x0C de su cabecera)")
    p.set_defaults(func=cmd_objdb_id)

    sn = sub.add_parser("snd", help="bancos de sonido .srsa (ASRS/KTSR): listar, extraer y sustituir")
    snsub = sn.add_subparsers(dest="sndcmd", required=True)

    p = snsub.add_parser("list", help="los streams del banco: codec, frecuencia, muestras, nombre",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa")
    p.set_defaults(func=cmd_snd_list)

    p = snsub.add_parser("extract", help="escribir el flujo crudo de cada stream",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa")
    p.add_argument("--out", required=True, help="carpeta de salida (nunca dentro del romfs)")
    p.add_argument("--stream", type=int, action="append",
                   help="solo este stream (repetible); por defecto, todos")
    p.set_defaults(func=cmd_snd_extract)

    p = snsub.add_parser("replace", help="sustituir audio: intercambiar dos streams o meter otro flujo",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa de partida")
    p.add_argument("--swap", type=int, nargs=2, metavar=("A", "B"),
                   help="intercambiar de sitio los streams A y B (sin encoder)")
    p.add_argument("--stream", type=int, help="stream cuyo audio se sustituye")
    p.add_argument("--file", help="fichero con el flujo nuevo (mismo codec)")
    p.add_argument("--from-banco", dest="from_banco",
                   help="banco del que sale el audio (copia su cabecera de audio)")
    p.add_argument("--from-stream", dest="from_stream", type=int,
                   help="stream del banco de origen")
    p.add_argument("-o", "--out", help="fichero de salida (por defecto: el mismo, con --in-place)")
    p.add_argument("--in-place", action="store_true",
                   help="escribir sobre el banco (deja <banco>.orig la primera vez)")
    p.set_defaults(func=cmd_snd_replace)

    p = snsub.add_parser("import",
                         help="meter un WAV propio en un stream (MS ADPCM o KA1A)",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa de partida")
    p.add_argument("--stream", type=int, required=True,
                   help="stream que se sustituye (se codifica con el codec y el "
                        "modo de bitrate que ya tiene)")
    p.add_argument("--wav", required=True,
                   help="WAV PCM 16 bits mono; su frecuencia es la que se escribe en la cabecera")
    p.add_argument("--loop", type=int, default=-1,
                   help="muestra donde empieza el bucle (-1 = sin bucle, por defecto)")
    p.add_argument("-o", "--out", help="fichero de salida (por defecto: el mismo, con --in-place)")
    p.add_argument("--in-place", action="store_true",
                   help="escribir sobre el banco (deja <banco>.orig la primera vez)")
    p.set_defaults(func=cmd_snd_import)

    p = snsub.add_parser("stat", help="codecs y tamanos de una carpeta de bancos",
                         parents=[common])
    p.add_argument("dir", help="carpeta con bancos .srsa (o uno suelto)")
    p.set_defaults(func=cmd_snd_stat)
    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GuardError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return exc.exit_code
    except PermissionError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return EXIT_USAGE
    except (ModError, FileNotFoundError) as exc:
        code = getattr(exc, "exit_code", EXIT_INVALID)
        out(sys.stderr, "ERROR: %s" % exc)
        return code
    except tables.TableError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return EXIT_INVALID
    except savemod.SaveReadOnlyError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return EXIT_USAGE
    except savemod.SaveError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except fdata.FdataError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except anim.AnimError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except catalog.CatalogError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except objdb.ObjDbError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except texcmd.TexError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except g1t.G1TError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except (texcmd.textures.TextureBackendMissing, texcmd.textures.TextureFormatError) as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except snd.SndError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return getattr(exc, "exit_code", EXIT_INVALID)
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK


def run() -> None:  # pragma: no cover - punto de entrada del script
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
