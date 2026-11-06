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

Todos los comandos que escriben tienen `--dry-run` por defecto y ninguno escribe
en el dump original.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from . import paths, tables
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
        base = tables.SLOTS_PER_BLOCK * (args.row - tables.TEXT_FIRST_ID)
        if not tables.TEXT_FIRST_ID <= args.row <= count + 3:
            raise UsageError("id de texto %d fuera de rango (%d..%d)"
                             % (args.row, tables.TEXT_FIRST_ID, count + 3), code="usage")
        out(sys.stdout, "id %d -> slots %d..%d del bloque" % (args.row, base, base + 5))
        for slot in range(6):
            ordinal = base + slot
            if ordinal >= len(slots):
                out(sys.stdout, "  +%d  (no existe)" % slot)
                continue
            data = slots[ordinal]
            out(sys.stdout, "  +%d  %d B  sha256 %s" % (slot, len(data),
                                                        hashlib.sha256(data).hexdigest()[:12]))
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
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK


def run() -> None:  # pragma: no cover - punto de entrada del script
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
