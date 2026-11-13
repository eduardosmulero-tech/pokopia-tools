"""CLI del kit: `pkp` (contrato en docs/ARQUITECTURA-KIT.md §5).

Comandos implementados aqui:

    pkp info
    pkp table <n> [--rows a:b]
    pkp row <n> <r>
    pkp dump <entrada> <salida>
    pkp repack <dir> [--recompress]
    pkp mod new <nombre>
    pkp mod validate <carpeta> [--img <RomFS.img>]
    pkp mod merge <a> <b> [-o <dir>]
    pkp mod apply <carpeta> [--dry-run | --yes]
    pkp mod pack <carpeta> [-o <dir>] [--img <RomFS.img>]
    pkp mod install <carpeta|paquete> --overlay <almacen> [--img <RomFS.img>]
    pkp mod uninstall <mod> --overlay <almacen> --img <RomFS.img>
    pkp mod status --overlay <almacen> [--img <RomFS.img>]
    pkp mod doctor --overlay <almacen> [--img <RomFS.img>]
    pkp fdata list|stat|extract <ruta> [--type kidsobjdb]
    pkp catalog list [--prefix BP|PM|BI|PC|AP]
    pkp catalog find <texto>
    pkp save read [--all] [--nombres [--idioma es]]
    pkp save write --slot N [--nombres] [--dry-run | --yes]

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

from . import paths, tables, fdata, catalog, objdb, texcmd, g1t, anim, snd, srst
from . import kidstask
from . import nombres as nombresmod
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
    comprobar_originales,
    desinstalar,
    doctor,
    empaquetar,
    estado,
    instalar,
    load_mod,
    merge_mods,
    validate,
)
from .mod.manifest import ContainerView
from .mod.example import escribir as escribir_ejemplo
from .mod.overlay import (
    aviso_separador,
    destino_por_defecto,
    img_por_defecto,
    leer_registro,
    linea_relativa,
)
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


def _cabecera_derivada(args, spec, blob):
    """`check_header` + geometria derivada cuando el contenedor es modificado.

    El defecto sigue siendo estricto: sin `--modificado` un `count` distinto del
    declarado lanza `TableError` aqui, y asi se queda (docs/AÑADIR-FILAS.md).
    Con la bandera, la tabla se lee con el count real (`tables.con_conteo`) y se
    avisa en la salida para que nadie lea esa geometria como la del dump.
    """
    count, version = tables.check_header(
        spec, blob, modificado=getattr(args, "modificado", False))
    if count != spec.count:
        declarado = spec.count
        spec = tables.con_conteo(spec, count)
        out(sys.stdout, "  aviso: count del header %d != %d declarado "
                        "(contenedor modificado: geometria derivada del header)"
            % (count, declarado))
    return spec, count, version


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
    spec, count, version = _cabecera_derivada(args, spec, blob)
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
    spec, count, version = _cabecera_derivada(args, spec, blob)
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
            if getattr(args, "texto", False):
                out(sys.stdout, "       texto: %s" % data.decode("utf-8", "replace"))
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
    "romfs": [],
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
    out(sys.stdout, "  siguiente paso: rellena 'edits', 'text' o 'romfs' y ejecuta "
                    "`pkp mod validate %s`" % target)
    return EXIT_OK


def cmd_mod_example(args) -> int:
    """`pkp mod example`: un mod valido con bytes propios, para seguir las paginas."""
    destino = args.destino or os.path.join("build", "ejemplo-mod")
    try:
        hecho = escribir_ejemplo(destino, args.container, forzar=args.forzar)
    except FileExistsError as exc:
        raise UsageError(str(exc), code="usage") from None
    except (OSError, ModError) as exc:
        raise ModError(str(exc), code="io", where=destino) from None
    if args.json:
        json.dump(hecho, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "mod de ejemplo: %s" % hecho["dir"])
    out(sys.stdout, "  mod.json")
    out(sys.stdout, "  payload/%s  (%d B nuestros)" % (hecho["path"], hecho["bytes"]))
    out(sys.stdout, "  romfs[0].path = %s" % hecho["path"])
    out(sys.stdout)
    out(sys.stdout, "siguiente paso:")
    out(sys.stdout, "  python pkp.py mod validate %s" % destino)
    out(sys.stdout, "  python pkp.py mod pack %s --img <RomFS.img>" % destino)
    if set(hecho["container_md5"].values()) == {"0" * 32}:
        out(sys.stdout)
        out(sys.stdout, "los md5 del contenedor son ceros: no hay copia configurada (PKP_ROMFS)")
        out(sys.stdout, "ni se paso --container; con un contenedor real `validate` los compararia")
    return EXIT_OK


def cmd_mod_validate(args) -> int:
    mod = load_mod(args.mod)
    container = None if args.no_container else paths.resolve_container(
        args.container, must_exist=False)
    if container is not None and not os.path.isfile(container.idx):
        container = None
    report = validate(mod, container, check_expect=not args.no_expect)
    img = args.img or img_por_defecto()
    problemas = comprobar_originales(mod, img) if (img and mod.romfs) else []
    for problema in problemas:
        report.error("mod.romfs.original", problema)
    doc = {"mod": mod.name, "version": mod.version, "manifest": mod.manifest,
           "container": container.dir if container else None,
           "edits": len(mod.edits), "text": len(mod.texts), "romfs": len(mod.romfs),
           **report.as_dict()}
    if args.json:
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
    else:
        out(sys.stdout, "mod: %s@%s  (%d ediciones de bytes, %d de texto, %d fichero(s) "
                        "de overlay)"
            % (mod.name, mod.version, len(mod.edits), len(mod.texts), len(mod.romfs)))
        out(sys.stdout, "  contenedor: %s" % (doc["container"] or "(no comprobado)"))
        if mod.romfs and not img:
            out(sys.stdout, "  img: (sin --img: no se comprueban los original_sha256)")
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


def cmd_mod_pack(args) -> int:
    img = args.img or img_por_defecto()
    result = empaquetar(args.mod, salida=args.out, img=img)
    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "mod: %s@%s" % (result["mod"], result["version"]))
    out(sys.stdout, "img: %s" % (result["img"] or "(sin --img: no se anota el original)"))
    for f in result["files"]:
        out(sys.stdout, "  %-9s %10d B  sha256 %s…  ruta %s"
            % (f["nota"] or "cubre", f["size"], f["sha256"][:12], f["path"]))
        out(sys.stdout, "  %-9s %10s     original %s"
            % ("", "", (f["original_sha256"] or "-")[:12]))
    for aviso in result["warnings"]:
        out(sys.stdout, "aviso: %s" % aviso)
    out(sys.stdout, "paquete: %s" % result["package"])
    out(sys.stdout, "sha256 : %s" % result["sha256"])
    return EXIT_OK


def _overlay(args) -> str:
    store = args.overlay or destino_por_defecto()
    if not store:
        raise UsageError("falta --overlay <carpeta del overlay> (o PKP_OVERLAY)", code="usage")
    return store


def cmd_mod_install(args) -> int:
    result = instalar(args.origen, _overlay(args), img=args.img or img_por_defecto(),
                      crear=args.crear, primero=args.primero, dry_run=args.dry_run,
                      forzar=args.forzar)
    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "mod: %s@%s  ->  %s%s"
        % (result["mod"], result["version"], result["dir"],
           "   [dry-run]" if result["dry_run"] else ""))
    for f in result["files"]:
        out(sys.stdout, "  %-6s %10d B  sha256 %s…  %s"
            % (f["nota"] or "cubre", f["size"], f["sha256"][:12], f["path"]))
    for c in result["conflictos"]:
        out(sys.stdout, "aviso: conflicto: %s ya lo instala %s; gana el que este antes en "
                        "DM_ROMFS_OVERLAY" % (c["path"], c["con"]))
    for aviso in result["avisos"]:
        out(sys.stdout, "aviso: %s" % aviso)
    if not result["dry_run"]:
        out(sys.stdout, "servido: %s"
            % ", ".join("%s -> %s %s" % (s["path"], s["origen"], s["donde"])
                        for s in result["servido"]))
        out(sys.stdout, "%s=%s" % ("DM_ROMFS_OVERLAY", result["overlay"]))
        registro = leer_registro(result["store"])
        out(sys.stdout, "relativo al cwd: %s" % linea_relativa(result["store"], registro))
        aviso = aviso_separador(result["store"], registro)
        if aviso:
            out(sys.stdout, "aviso: %s" % aviso)
    return EXIT_OK


def cmd_mod_uninstall(args) -> int:
    result = desinstalar(args.mod, _overlay(args), img=args.img or img_por_defecto(),
                         dry_run=args.dry_run, forzar=args.forzar,
                         permitir_sin_verificar=args.sin_verificar)
    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK if result["ok"] else EXIT_INVALID
    out(sys.stdout, "mod: %s  (%d fichero(s))%s"
        % (result["mod"], result["files"], "   [dry-run]" if result["dry_run"] else ""))
    for v in result["verificacion"]:
        out(sys.stdout, "  %-14s %s" % (v["estado"], v["path"]))
        if v["servido"]["origen"] == "img":
            out(sys.stdout, "  %-14s img entrada %s, sha256 %s…"
                % ("", v["servido"]["indice"], (v["servido"]["sha256"] or "")[:12]))
    out(sys.stdout, "restaurados: %d  sombreados por otro mod: %d  sin original: %d"
        % (result["restaurados"], result["sombreados"], result["sin_original"]))
    out(sys.stdout, "resultado: %s" % ("OK" if result["ok"] else "FALLIDO"))
    return EXIT_OK if result["ok"] else EXIT_INVALID


def cmd_mod_status(args) -> int:
    result = estado(_overlay(args), img=args.img or img_por_defecto())
    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    if not result["mods"]:
        out(sys.stdout, "vacio: %s" % result["store"])
        return EXIT_OK
    out(sys.stdout, "almacen: %s" % result["store"])
    for mod in result["mods"]:
        out(sys.stdout, "%d. %s@%s  (%d fichero(s), instalado %s)"
            % (mod["orden"], mod["name"], mod["version"], len(mod["files"]),
               mod["installed_at"] or "?"))
        for f in mod["files"]:
            s = f["servido"]
            estado_txt = ("overlay" if s["origen"] == "overlay" else
                          "img entrada %s" % s["indice"] if s["origen"] == "img" else "nada")
            out(sys.stdout, "   %10s B  %-40s  sirve: %-14s %s"
                % (f["size"], f["path"], estado_txt,
                   "" if s["origen"] == "overlay" else (s["sha256"] or "")[:12]))
    if result["conflictos"]:
        out(sys.stdout, "conflictos: %d ruta(s) que sirven dos o mas mods"
            % len(result["conflictos"]))
        for c in result["conflictos"]:
            out(sys.stdout, "  %s lo sirven %d mods (%s); gana %s%s"
                % (c["path"], len(c["mods"]), ", ".join(c["mods"]), c["gana"],
                   " — mismos bytes" if c["mismos_bytes"] else " — bytes distintos"))
    else:
        out(sys.stdout, "conflictos: ninguno")
    out(sys.stdout, "DM_ROMFS_OVERLAY=%s" % result["overlay"])
    out(sys.stdout, "relativo al cwd: %s" % result["overlay_relativo"])
    if result["aviso"]:
        out(sys.stdout, "aviso: %s" % result["aviso"])
    return EXIT_OK


def cmd_mod_doctor(args) -> int:
    # `--container` es una referencia **declarada** por quien ejecuta: si el mod se
    # hizo para otro build, es un FALLO. `PKP_ROMFS` es el contenedor por defecto del
    # kit y solo se compara como aviso: puede ser otro dump y el overlay carga igual.
    entorno = None if args.container else os.environ.get("PKP_ROMFS")
    result = doctor(_overlay(args), img=args.img or img_por_defecto(),
                    container=args.container, container_entorno=entorno)
    if args.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK if result["ok"] else EXIT_INVALID
    for c in result["checks"]:
        etiqueta = "ok  " if c["ok"] else ("FALLO" if c["fatal"] else "aviso")
        out(sys.stdout, "%-5s %-46s %s" % (etiqueta, c["check"], c["detail"]))
    if result.get("overlay"):
        out(sys.stdout, "DM_ROMFS_OVERLAY=%s" % result["overlay"])
        out(sys.stdout, "relativo al cwd: %s" % result["overlay_relativo"])
    veredicto = ("FALLIDO" if not result["ok"] else
                 "sano con avisos" if result.get("avisos") else "sano")
    out(sys.stdout, "resultado: %s (%d fallo(s), %d aviso(s))"
        % (veredicto, result.get("fallos", 0), result.get("avisos", 0)))
    return EXIT_OK if result["ok"] else EXIT_INVALID


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

def _preparar_salida_para_nombres() -> None:
    """Que un nombre que la consola no sepa escribir no tumbe la lista.

    El texto de las tablas es UTF-8. Si `stdout` no lo es —consola de Windows en cp1252
    con la salida redirigida a un fichero, que es el caso de `--idioma jp|kr|zh-*`— Python
    lanza `UnicodeEncodeError` a mitad del inventario. Con `backslashreplace` el caracter
    sale como `\\uXXXX`: no se inventa el nombre y la lista sale entera. Cuando el flujo
    ya es UTF-8 (una consola normal) no cambia ni un byte.
    """
    stream = sys.stdout
    reconfigurar = getattr(stream, "reconfigure", None)
    if reconfigurar is not None:
        try:
            reconfigurar(errors="backslashreplace")
        except (ValueError, OSError):  # pragma: no cover - flujo cerrado o sin buffer
            pass


def _indice_de_nombres(args) -> "nombresmod.NameIndex":
    """Indice `id -> nombre` para esta ejecucion (una sola lectura de las dos tablas).

    Se construye al vuelo desde el contenedor (`--container` o `PKP_ROMFS`): sin el
    dump no hay nombres y `paths.ContainerNotFound` lo dice con las dos formas de
    apuntarlo. No se cachea en disco ni en fichero: el texto solo se imprime.
    """
    return nombresmod.NameIndex.desde_contenedor(
        args.container, language=args.idioma,
        modificado=getattr(args, "modificado", False))


def cmd_save_read(args) -> int:
    if not args.nombres and args.idioma != nombresmod.IDIOMA_POR_DEFECTO:
        raise UsageError("--idioma solo tiene efecto con --nombres", code="usage")
    page = savemod.open_page(args.save, args.page)
    items = savemod.read_items(page)
    nombres = _indice_de_nombres(args) if args.nombres else None
    if nombres is not None:
        _preparar_salida_para_nombres()
    doc = page.summary()
    doc["items"] = [r.as_dict() for r in items]
    if nombres is not None:
        for entrada, record in zip(doc["items"], items):
            entrada["nombre"] = nombres.nombre(record.item_id)
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
            if nombres is None:
                out(sys.stdout, "  %s" % record)
            else:
                # Los textos del juego solo salen aqui, en tiempo de ejecucion
                # (docs/NORMA-CONTENIDO-Y-PUBLICACION.md §1). Nada va a disco.
                out(sys.stdout, "  %s  %s"
                    % (record, nombres.nombre(record.item_id)))
    return EXIT_OK


def cmd_save_write(args) -> int:
    if args.yes and args.dry_run:
        raise UsageError("--yes y --dry-run son incompatibles", code="usage")
    if args.id is None and args.count is None and args.variant is None:
        raise UsageError("nada que escribir: pasa al menos uno de --id, --count, "
                         "--variant", code="usage")
    if not args.nombres and args.idioma != nombresmod.IDIOMA_POR_DEFECTO:
        raise UsageError("--idioma solo tiene efecto con --nombres", code="usage")
    page = savemod.open_page(args.save, args.page)
    new_payload = savemod.items.with_item(page, args.slot, item_id=args.id,
                                          count=args.count, variant=args.variant)
    cambio = None
    if args.nombres:
        # Escribir a ciegas sobre un id es como se rompe una partida: el hueco y el
        # objeto van delante del resultado, tambien en dry-run.
        antes = savemod.read_items(page)[args.slot]
        nuevo_id = antes.item_id if args.id is None else args.id
        nuevo_count = antes.count if args.count is None else args.count
        indice = _indice_de_nombres(args)
        _preparar_salida_para_nombres()
        cambio = {
            "slot": args.slot,
            "id_antes": antes.item_id, "id_despues": nuevo_id,
            "cantidad_antes": antes.count, "cantidad_despues": nuevo_count,
            "nombre_antes": indice.nombre(antes.item_id),
            "nombre_despues": indice.nombre(nuevo_id),
        }
    result = savemod.write_payload(page, new_payload, target=args.target,
                                  dry_run=not args.yes,
                                  allow_live_save=args.allow_live_save,
                                  level=args.level, strategy=args.strategy,
                                  memlevel=args.memlevel)
    if args.json:
        doc = result.as_dict()
        if cambio is not None:
            doc["cambio"] = cambio
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    if cambio is not None:
        _print_cambio(cambio)
    _print_write(result)
    return EXIT_OK


def _print_cambio(cambio: dict) -> None:
    """Que hueco y que objeto se va a tocar (solo con `--nombres`)."""
    out(sys.stdout, "cambio    : hueco %d   id %d -> %d   cant %d -> %d"
        % (cambio["slot"], cambio["id_antes"], cambio["id_despues"],
           cambio["cantidad_antes"], cambio["cantidad_despues"]))
    if cambio["id_antes"] == cambio["id_despues"]:
        out(sys.stdout, "objeto    : %s" % cambio["nombre_antes"])
    else:
        out(sys.stdout, "objeto    : %s -> %s"
            % (cambio["nombre_antes"], cambio["nombre_despues"]))


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


def _hex_u32(arg: str) -> int:
    """Un u32 en hex, con o sin `0x` (para `--name-hash` y `--flags`)."""
    texto = arg.strip()
    try:
        valor = int(texto[2:] if texto.lower().startswith("0x") else texto, 16)
    except ValueError:
        raise UsageError(
            "esperaba un u32 en hex, no %r\n  ejemplo: 0xca806e59" % arg,
            code="usage") from None
    if not 0 <= valor <= 0xFFFFFFFF:
        raise UsageError("%r se sale de 32 bits" % arg, code="usage")
    return valor


def cmd_fdata_inject(args) -> int:
    if not os.path.isfile(args.file):
        raise FileNotFoundError("no existe el fichero que se inyecta: %s" % args.file)
    with open(args.file, "rb") as fh:
        payload = fh.read()
    resultado = fdata.inject(args.fdata, args.out, args.name_hash, payload,
                             route=args.route, flags=args.flags)
    if args.json:
        json.dump(resultado.as_dict(), sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    antes = resultado.before
    out(sys.stdout, "entrada 0x%08x (%s) de %s"
        % (antes.name_hash, antes.type_name, os.path.abspath(args.fdata)))
    out(sys.stdout, "  antes   : entry %d = 48 cabecera + %d metadatos + %d comprimidos"
        " -> %d crudos, flags 0x%08x"
        % (antes.entry_size, antes.metadata_size, antes.compressed_size,
           antes.uncompressed_size, antes.flags))
    forma = "crudos (compressed_size == uncompressed_size)" if args.route == "raw" \
        else "comprimidos"
    out(sys.stdout, "  despues : entry %d = 48 cabecera + %d metadatos + %d %s,"
        " flags 0x%08x"
        % (resultado.entry_size, resultado.metadata_size,
           resultado.compressed_size, forma, resultado.flags))
    out(sys.stdout, "  fichero : %d B -> %d B (%+d)"
        % (os.path.getsize(args.fdata), resultado.repack.size,
           resultado.repack.size - os.path.getsize(args.fdata)))
    out(sys.stdout, "  sha256  : %s" % resultado.repack.sha256)
    out(sys.stdout, "  escrito : %s" % os.path.abspath(args.out))
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
# Grafo de tareas: la entrada `kidstask` (`_TGK0000`)
# --------------------------------------------------------------------------

def cmd_kidstask(args) -> int:
    """Los nodos del grafo de tareas con sus enlaces y, si hay, su tipo."""
    try:
        if args.archivo:
            datos = kidstask.leer_fichero(args.archivo)
            origen = args.archivo
        else:
            romfs = args.container or paths.configured_romfs()
            datos, origen = kidstask.leer_de_romfs(romfs)
        doc = kidstask.parse(datos, origen=origen)
    except kidstask.KidstaskError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return EXIT_INVALID

    # Nombres: `--tipos`, o el YAML por defecto del Paso 0 si esta. Sin el
    # YAML no se falla: se avisa por stderr y siguen los hashes.
    ruta_yml = args.tipos
    if ruta_yml is None and os.path.isfile(kidstask.YML_DEFECTO):
        ruta_yml = kidstask.YML_DEFECTO
    try:
        if ruta_yml is None:
            out(sys.stderr, "aviso: sin kidstypeinfodb.yml: solo hashes "
                "(--tipos <ruta>; ver docs/KIDSTASK.md)")
            tipos, props = {}, {}
        else:
            tipos, props = kidstask.cargar_nombres(ruta_yml)
    except kidstask.KidstaskError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return EXIT_INVALID

    if args.json:
        json.dump(doc.as_dict(tipos=tipos, props=props), sys.stdout,
                  indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK

    cab = doc.cabecera
    resueltos = sum(1 for n in doc.nodos
                    if doc.nombre_de_tipo(n.tipo_hash, tipos, props))
    out(sys.stdout, "kidstask: %s (%d B)" % (origen, doc.bytes_totales))
    out(sys.stdout, "%s | cabecera_tamano %d | cabecera_de_registro %d | "
        "recuento %d | cubre el fichero: %s"
        % (cab["firma"], cab["cabecera_tamano"], cab["cabecera_de_registro"],
           cab["recuento"], "si" if doc.cubre_el_fichero else "NO"))
    out(sys.stdout, "campo_0x14 0x%08x | campo_0x18 %d | campo_0x1c %d%s"
        % (cab["campo_0x14"], cab["campo_0x18"], cab["campo_0x1c"],
           " (= bytes del fichero)" if cab["campo_0x1c"] == doc.bytes_totales
           else ""))
    out(sys.stdout, "nodos: %d  aristas: %d  tipos resueltos: %d/%d"
        % (len(doc.nodos), len(doc.aristas()), resueltos, len(doc.nodos)))
    out(sys.stdout, "")
    out(sys.stdout, " #  offset   tam   id          h1          tipo")
    for n in doc.nodos:
        nombre = doc.nombre_de_tipo(n.tipo_hash, tipos, props) or "-"
        out(sys.stdout, "%02d  0x%03x  %4d  0x%08x  0x%08x  %s"
            % (n.indice, n.offset, n.tamano, n.id, n.tipo_hash, nombre))
        out(sys.stdout, "    N=%d  enlaces=%s"
            % (len(n.propiedades), list(n.enlaces)))
        if args.props:
            for p in n.propiedades:
                nombre_p = props.get(p.hash, "-")
                if kidstask.UNIDAD[p.tipo] == 4:
                    vals = " ".join("0x%08x" % v for v in p.valores)
                else:
                    vals = " ".join("%02x" % v for v in p.valores)
                out(sys.stdout, "      tipo=%d len=%d 0x%08x %s  %s"
                    % (p.tipo, p.tamano, p.hash, nombre_p, vals))
    out(sys.stdout, "")
    out(sys.stdout, "aristas (%d): %s"
        % (len(doc.aristas()),
           " ".join("%02d->%02d" % (i, j) for i, j in doc.aristas())))
    return EXIT_OK


# --------------------------------------------------------------------------
# Sonido: bancos ASRS/KTSR de los `.srsa`
# --------------------------------------------------------------------------

def _snd_line(stream) -> str:
    return ("#%-4d %-8s %3d ch %6d Hz %9d muestras %7.3f s  %10d B  id %-10d %s"
            % (stream.index, stream.codec, stream.channels, stream.sample_rate,
               stream.num_samples, stream.duration, stream.data_size,
               stream.sound_id, stream.name))


def _srst_track(serst, stream, origen: str):
    """La pista del `.srst` que corresponde a un stream **externo** del banco.

    El emparejamiento es exacto y sin heuristica: mismo `data_offset` (relativo
    al KTSR de los dos ficheros), mismo `data_size` y mismo `sound id`. Si algo
    no cuadra, se dice en vez de escribir en la pista equivocada.
    """
    if not stream.external:
        raise srst.SrstError(
            "el stream %d no es externo: su audio esta dentro del banco y `--srst` "
            "no pinta nada" % stream.index)
    track = serst.by_data_offset(stream.data_offset)
    if track is None:
        raise srst.SrstError(
            "el stream %d (data_offset 0x%x) no tiene pista en %s: no son el mismo "
            "banco y el mismo `.srst`" % (stream.index, stream.data_offset, origen))
    if track.sound_id != stream.sound_id or track.data_size != stream.data_size:
        raise srst.SrstError(
            "la pista %d de %s no es la del stream %d del banco: sound id 0x%08x/0x%08x, "
            "data_size %d/%d" % (track.index, origen, stream.index, track.sound_id,
                                 stream.sound_id, track.data_size, stream.data_size))
    return track


def _srst_line(track) -> str:
    return ("#%-4d %-8s %3d ch %6d Hz %9d muestras %7.3f s  %10d B  id %-10d externo"
            % (track.index, track.codec, track.channels, track.sample_rate,
               track.num_samples, track.duration, track.data_size, track.sound_id))


def cmd_snd_list(args) -> int:
    banco, _ = snd.read_bank(args.bank)
    serst = None
    if getattr(args, "srst", None):
        serst, datos_srst = srst.read(args.srst)
    if args.json:
        doc = banco.as_dict()
        doc.update({"codecs": banco.codecs,
                    "streams": [s.as_dict() for s in banco.streams]})
        if serst is not None:
            doc["srst"] = serst.as_dict()
            doc["srst"]["path"] = os.path.abspath(args.srst)
            doc["tracks"] = [t.as_dict() for t in serst.tracks]
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "%s  %d B  audio_id 0x%08x  %d chunks  %d streams  %s"
        % (os.path.abspath(args.bank), banco.size, banco.audio_id,
           len(banco.chunks), len(banco.streams), banco.codecs))
    if serst is not None:
        out(sys.stdout, "%s  %d pistas  clave %d B  audio_id 0x%08x"
            % (os.path.abspath(args.srst), len(serst.tracks), len(serst.key),
               serst.audio_id))
    for stream in banco.streams:
        if stream.external and serst is not None:
            track = serst.by_data_offset(stream.data_offset)
            if track is not None:
                out(sys.stdout, _srst_line(track))
                continue
        out(sys.stdout, _snd_line(stream))
    return EXIT_OK


def cmd_snd_extract(args) -> int:
    escritos = snd.extract(args.bank, args.out, args.stream or None)
    externos: list[tuple[srst.Track, str]] = []
    if getattr(args, "srst", None):
        from . import paths as pkp_paths

        serst, datos_srst = srst.read(args.srst)
        banco, _ = snd.read_bank(args.bank)
        pedidos = banco.streams if not args.stream else [banco.stream(i) for i in args.stream]
        base = os.path.splitext(os.path.basename(args.bank))[0]
        for stream in pedidos:
            if not stream.external:
                continue
            track = _srst_track(serst, stream, args.srst)
            destino = os.path.join(args.out, "%s.%03d.%s"
                                   % (base, track.index, track.codec))
            pkp_paths.guard_writable(destino)
            with open(destino, "wb") as salida:
                salida.write(srst.track_plain(datos_srst, track.index))
            externos.append((track, destino))
        escritos = list(escritos) + [(t, p) for t, p in externos]
    if args.json:
        json.dump({
            "bank": os.path.abspath(args.bank),
            "srst": os.path.abspath(args.srst) if getattr(args, "srst", None) else None,
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
        nombre = getattr(stream, "name", "externo")
        out(sys.stdout, "  %s  %10d B  %s"
            % (os.path.basename(destino), os.path.getsize(destino), nombre))
    return EXIT_OK


def _snd_replace_externo(args) -> int:
    """Sustituye audio de un stream **externo**: escribe sobre el `.srst`.

    Se exige el banco (`.srsa`) ademas del `.srst` para traducir `--stream N`
    al sitio exacto: el numero de stream es el del banco, no se adivina por
    orden del fichero.
    """
    destino = args.out or args.srst
    if destino == args.srst and not args.in_place:
        out(sys.stderr,
            "ERROR: para escribir sobre el propio `.srst` hace falta --in-place\n"
            "  (deja una copia <.srst>.orig la primera vez); si no, usa -o <salida>")
        return EXIT_USAGE
    banco, _ = snd.read_bank(args.bank)
    serst, datos = srst.read(args.srst)
    antes = paths.sha256_file(args.srst)

    if args.swap:
        a = _srst_track(serst, banco.stream(args.swap[0]), args.srst)
        b = _srst_track(serst, banco.stream(args.swap[1]), args.srst)
        modificado = srst.swap_tracks(datos, a.index, b.index)
        detalle = {"swap": list(args.swap), "tracks": [a.index, b.index]}
        descripcion = "intercambiadas las pistas %d y %d" % (a.index, b.index)
    else:
        track = _srst_track(serst, banco.stream(args.stream), args.srst)
        with open(args.file, "rb") as fh:
            plano = fh.read()
        modificado = srst.with_track(datos, track.index, plano)
        detalle = {"stream": args.stream, "track": track.index,
                   "bytes": len(plano)}
        descripcion = ("pista %d (stream %d): %d B escritos de %d"
                       % (track.index, args.stream, len(plano), track.data_size))

    srst.write_srst(destino, modificado)
    despues = paths.sha256_file(destino)
    verificado = srst.parse(modificado)
    if len(verificado.tracks) != len(serst.tracks):
        out(sys.stderr, "ERROR: el `.srst` resultante tiene %d pistas y tenia %d"
            % (len(verificado.tracks), len(serst.tracks)))
        return EXIT_INVALID
    if args.json:
        doc = {"bank": os.path.abspath(args.bank), "srst_before": os.path.abspath(args.srst),
               "written": os.path.abspath(destino),
               "sha256_before": antes, "sha256_after": despues,
               "size_before": len(datos), "size_after": len(modificado),
               "tracks": len(verificado.tracks),
               "backup": destino + ".orig" if os.path.exists(destino + ".orig") else None}
        doc.update(detalle)
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "banco   : %s (stream %d, externo)"
        % (os.path.abspath(args.bank), args.swap[0] if args.swap else args.stream))
    out(sys.stdout, ".srst   : %s (%d pistas)" % (os.path.abspath(args.srst),
                                                 len(serst.tracks)))
    out(sys.stdout, "escrito : %s" % descripcion)
    out(sys.stdout, "destino : %s" % os.path.abspath(destino))
    out(sys.stdout, "sha256  : %s" % antes)
    out(sys.stdout, "        -> %s" % despues)
    out(sys.stdout, "tamano  : %d -> %d B (no se mueve ni un desplazamiento)"
        % (len(datos), len(modificado)))
    if os.path.exists(destino + ".orig"):
        out(sys.stdout, "original: %s" % (destino + ".orig"))
    return EXIT_OK


def cmd_snd_replace(args) -> int:
    if getattr(args, "srst", None):
        if args.from_banco or args.from_stream is not None:
            out(sys.stderr, "ERROR: --from-banco/--from-stream son para bancos; "
                            "con --srst usa --file (el flujo crudo ya extraido)")
            return EXIT_USAGE
        return _snd_replace_externo(args)
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


def _snd_import_externo(args) -> int:
    """Mete un WAV propio en un stream externo: codifica y escribe en el `.srst`."""
    from . import audio as pkp_audio

    destino = args.out or args.srst
    if destino == args.srst and not args.in_place:
        out(sys.stderr,
            "ERROR: para escribir sobre el propio `.srst` hace falta --in-place\n"
            "  (deja una copia <.srst>.orig la primera vez); si no, usa -o <salida>")
        return EXIT_USAGE
    banco, _ = snd.read_bank(args.bank)
    serst, datos = srst.read(args.srst)
    track = _srst_track(serst, banco.stream(args.stream), args.srst)
    canales, rate = pkp_audio.read_wav_channels(args.wav)
    if len(canales) != track.channels:
        out(sys.stderr,
            "ERROR: la pista %d es de %d canales y %s trae %d; no se mezcla solo\n"
            "  (exporta el WAV con %d canales, p. ej. `-ac %d` en ffmpeg)"
            % (track.index, track.channels, args.wav, len(canales),
               track.channels, track.channels))
        return EXIT_USAGE
    if rate != track.sample_rate:
        out(sys.stderr,
            "ERROR: la pista va a %d Hz y el WAV a %d Hz; el kit no remuestrea\n"
            "  (convierte el WAV a %d Hz, y que la cabecera del banco siga cuadrando)"
            % (track.sample_rate, rate, track.sample_rate))
        return EXIT_USAGE
    antes = paths.sha256_file(args.srst)
    muestras = len(canales[0])
    try:
        plano = srst.build_track(track, canales, args.loop)
    except pkp_audio.AudioError as exc:
        out(sys.stderr, "ERROR: %s" % exc)
        return EXIT_INVALID
    modificado = srst.with_track(datos, track.index, plano)
    srst.write_srst(destino, modificado)
    despues = paths.sha256_file(destino)

    # segundo juez: se relee el fichero escrito, se descifra y se decodifica
    verificado, datos2 = srst.read(destino)
    nueva = verificado.track(track.index)
    decodificado, campos = srst.decode_track(srst.track_plain(datos2, track.index))
    # `ka1a_snr_db` compara PCM16 contra la escala -1..1 del decodificador
    snr = [pkp_audio.ka1a_snr_db(canales[c], [v / 32768.0 for v in decodificado[c]])
           for c in range(len(canales))]
    frame = pkp_audio.ka1a_frame_size(track.bitrate_mode)
    if args.json:
        json.dump({
            "bank": os.path.abspath(args.bank), "srst_before": os.path.abspath(args.srst),
            "written": os.path.abspath(destino),
            "sha256_before": antes, "sha256_after": despues,
            "size_before": len(datos), "size_after": len(modificado),
            "stream": args.stream, "track": nueva.as_dict(),
            "wav": os.path.abspath(args.wav), "channels": len(canales),
            "rate": rate, "samples": muestras,
            "bitrate_mode": track.bitrate_mode,
            "encoded_bytes": campos["tamano"],
            "frames_per_channel": campos["tamano"] // (frame * len(canales)),
            "snr_db": [round(v, 3) for v in snr],
            "backup": destino + ".orig" if os.path.exists(destino + ".orig") else None,
        }, sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK
    out(sys.stdout, "WAV       : %s (%d muestras por canal, %d Hz, %d canales)"
        % (os.path.abspath(args.wav), muestras, rate, len(canales)))
    out(sys.stdout, "encoder   : ka1a propio (modo %+d, frame de %d B)"
        % (track.bitrate_mode, frame))
    out(sys.stdout, "codificado: %d B en %d frames por canal (SNR ida y vuelta %s)"
        % (campos["tamano"], campos["tamano"] // (frame * len(canales)),
           ", ".join("%.2f dB" % v for v in snr)))
    out(sys.stdout, "pista     : %d (stream %d) %d Hz, %d muestras, %.3f s, bucle %d..%d"
        % (nueva.index, args.stream, nueva.sample_rate, nueva.num_samples,
           nueva.duration, nueva.loop_start, nueva.loop_end))
    out(sys.stdout, "escrito   : %s" % os.path.abspath(destino))
    out(sys.stdout, "sha256    : %s" % antes)
    out(sys.stdout, "         -> %s" % despues)
    out(sys.stdout, "tamano    : %d -> %d B (el `.srst` no cambia de tamano)"
        % (len(datos), len(modificado)))
    if os.path.exists(destino + ".orig"):
        out(sys.stdout, "original  : %s" % (destino + ".orig"))
    return EXIT_OK


def cmd_snd_import(args) -> int:
    """Mete un WAV propio en un stream del banco (MS ADPCM o KA1A)."""
    from . import audio as pkp_audio

    if getattr(args, "srst", None):
        return _snd_import_externo(args)
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


def cmd_snd_revert(args) -> int:
    """Deshace una sustitucion: restaura `<fichero>.orig` sobre `<fichero>`."""
    respaldo = args.file + ".orig"
    if not os.path.exists(respaldo):
        out(sys.stderr,
            "ERROR: no hay copia de la que volver: falta %s\n"
            "  (la deja `--in-place` la primera vez que se escribe)" % respaldo)
        return EXIT_USAGE
    antes = paths.sha256_file(args.file)
    restaurado, original = srst.revert(args.file)
    if args.json:
        json.dump({"file": os.path.abspath(args.file),
                   "backup": os.path.abspath(respaldo),
                   "sha256_before": antes, "sha256_restored": restaurado,
                   "sha256_backup": original,
                   "identical": restaurado == original},
                  sys.stdout, indent=2, ensure_ascii=False)
        out(sys.stdout)
        return EXIT_OK if restaurado == original else EXIT_INVALID
    out(sys.stdout, "modificado: %s" % antes)
    out(sys.stdout, "restaurado: %s" % restaurado)
    out(sys.stdout, "original  : %s" % original)
    out(sys.stdout, "reversion exacta: %s" % ("si" if restaurado == original else "NO"))
    return EXIT_OK if restaurado == original else EXIT_INVALID


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
    ap.add_argument("--modificado", action="store_true",
                    help="contenedor derivado del dump: admite count por encima "
                         "del declarado (docs/AÑADIR-FILAS.md)")
    # Permite escribir --container tambien despues del subcomando:
    #   pkp mod apply ejemplos/x --container build/copia
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--container", default=argparse.SUPPRESS,
                        help="carpeta del contenedor (igual que la opcion global)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="salida JSON (igual que la opcion global)")
    common.add_argument("--modificado", action="store_true",
                        default=argparse.SUPPRESS,
                        help="contenedor derivado del dump (igual que la opcion global)")
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
    p.add_argument("--texto", action="store_true",
                   help="en tablas de texto, muestra los slots en claro ademas "
                        "del sha256 (salida para terminal: no la volqueis a un "
                        "fichero del repo, docs/NORMA-CONTENIDO-Y-PUBLICACION.md §2)")
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

    p = msub.add_parser("example", help="mod de ejemplo con bytes propios (las paginas)",
                        parents=[common])
    p.add_argument("destino", nargs="?", default=None,
                   help="carpeta donde escribirlo (por defecto build/ejemplo-mod)")
    p.add_argument("--forzar", action="store_true",
                   help="escribe aunque el destino ya exista")
    p.set_defaults(func=cmd_mod_example)

    p = msub.add_parser("validate", help="esquema, rangos, md5 y expect", parents=[common])
    p.add_argument("mod")
    p.add_argument("--no-expect", action="store_true",
                   help="no comparar expect contra el contenedor")
    p.add_argument("--no-container", action="store_true",
                   help="no abrir el contenedor (solo esquema)")
    p.add_argument("--img", default=None,
                   help="RomFS.img: comprueba los original_sha256 de romfs[] (o PKP_ROMFS_IMG)")
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

    p = msub.add_parser("pack", help="carpeta de trabajo -> paquete .pkmod instalable",
                        parents=[common])
    p.add_argument("mod", help="carpeta del mod (con mod.json y sus ficheros)")
    p.add_argument("-o", "--out", default=None,
                   help="carpeta del paquete (por defecto build/pkmod)")
    p.add_argument("--img", default=None,
                   help="RomFS.img para anotar el sha256 del original (o PKP_ROMFS_IMG)")
    p.set_defaults(func=cmd_mod_pack)

    p = msub.add_parser("install", help="deja el mod en el overlay, sin tocar el img",
                        parents=[common])
    p.add_argument("origen", help="carpeta del mod o paquete .pkmod")
    p.add_argument("--overlay", default=None,
                   help="carpeta del almacen de mods (o PKP_OVERLAY)")
    p.add_argument("--img", default=None, help="RomFS.img (o PKP_ROMFS_IMG)")
    p.add_argument("--crear", action="store_true",
                   help="crea el almacen si no existe (por defecto se niega)")
    p.add_argument("--primero", action="store_true",
                   help="da prioridad a este mod (el primero gana en DM_ROMFS_OVERLAY)")
    p.add_argument("--dry-run", action="store_true", help="cuenta sin escribir nada")
    p.add_argument("--forzar", action="store_true",
                   help="salta la comprobacion de 'el juego esta en marcha'")
    p.set_defaults(func=cmd_mod_install)

    p = msub.add_parser("uninstall", help="quita un mod y comprueba que vuelve el original",
                        parents=[common])
    p.add_argument("mod", help="nombre del mod instalado")
    p.add_argument("--overlay", default=None,
                   help="carpeta del almacen de mods (o PKP_OVERLAY)")
    p.add_argument("--img", default=None,
                   help="RomFS.img con el que se verifica el original (o PKP_ROMFS_IMG)")
    p.add_argument("--dry-run", action="store_true", help="cuenta sin borrar nada")
    p.add_argument("--forzar", action="store_true",
                   help="borra aunque el overlay no coincida con el registro")
    p.add_argument("--sin-verificar", dest="sin_verificar", action="store_true",
                   help="acepta no poder demostrar que el original vuelve (sin --img)")
    p.set_defaults(func=cmd_mod_uninstall)

    p = msub.add_parser("status", help="que mods hay, quien sirve cada ruta y conflictos",
                        parents=[common])
    p.add_argument("--overlay", default=None,
                   help="carpeta del almacen de mods (o PKP_OVERLAY)")
    p.add_argument("--img", default=None, help="RomFS.img (o PKP_ROMFS_IMG)")
    p.set_defaults(func=cmd_mod_status)

    p = msub.add_parser("doctor", help="coherencia del almacen y del img",
                        parents=[common])
    p.add_argument("--overlay", default=None,
                   help="carpeta del almacen de mods (o PKP_OVERLAY)")
    p.add_argument("--img", default=None, help="RomFS.img (o PKP_ROMFS_IMG)")
    p.set_defaults(func=cmd_mod_doctor)

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
    p.add_argument("--nombres", "--name", dest="nombres", action="store_true",
                   help="añade el nombre de cada objeto (necesita el contenedor: "
                        "--container o PKP_ROMFS); sin la bandera la salida no cambia")
    p.add_argument("--idioma", default=nombresmod.IDIOMA_POR_DEFECTO,
                   choices=tuple(nombresmod.TEXT_TABLES),
                   help="tabla de nombres que se usa con --nombres (por defecto es)")
    p.set_defaults(func=cmd_save_read)

    p = ssub.add_parser("write", help="escribir un hueco del inventario (dry-run por defecto)",
                        parents=[common])
    add_save_opts(p)
    p.add_argument("--slot", type=int, required=True, help="hueco 0..129")
    p.add_argument("--id", type=int, default=None, help="id de objeto (13 bits)")
    p.add_argument("--count", type=int, default=None, help="cantidad 0..255")
    p.add_argument("--variant", type=int, default=None,
                   help="bits 13..31 del campo (variante/colocacion)")
    p.add_argument("--nombres", "--name", dest="nombres", action="store_true",
                   help="dice el hueco y el nombre del objeto que se va a tocar "
                        "(necesita el contenedor: --container o PKP_ROMFS)")
    p.add_argument("--idioma", default=nombresmod.IDIOMA_POR_DEFECTO,
                   choices=tuple(nombresmod.TEXT_TABLES),
                   help="tabla de nombres que se usa con --nombres (por defecto es)")
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

    p = fdsub.add_parser("inject",
                         help="meter un fichero en una entrada (rehace la copia del .fdata)",
                         parents=[common])
    p.add_argument("fdata", help=".fdata de partida (el del dump se abre en solo lectura)")
    p.add_argument("--name-hash", dest="name_hash", required=True, type=_hex_u32,
                   help="name_hash de la entrada que se sustituye, p. ej. 0xca806e59")
    p.add_argument("--file", required=True,
                   help="fichero con el contenido nuevo (p. ej. el .g1t recodificado)")
    p.add_argument("--out", required=True,
                   help="copia nueva del .fdata (nunca el del romfs, nunca el de partida)")
    p.add_argument("--route", choices=("raw", "slot"), default="raw",
                   help="raw: entrada cruda, sin comprimir (por defecto); "
                        "slot: parche en sitio sin desplazar nada")
    p.add_argument("--flags", type=_hex_u32, default=None,
                   help="flags de la entrada nueva (por defecto, los del original)")
    p.set_defaults(func=cmd_fdata_inject)

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

    p = sub.add_parser("kidstask",
                       help="grafo de tareas (_TGK0000): nodos, enlaces y tipo",
                       parents=[common])
    p.add_argument("archivo", nargs="?", default=None,
                   help="fichero .kidstask ya extraido; si se omite, la unica "
                        "entrada del --container")
    p.add_argument("--tipos", default=None,
                   help="kidstypeinfodb.yml para los nombres (por defecto "
                        "build/refs/fdata_dump/kidstypeinfodb.yml si existe)")
    p.add_argument("--props", action="store_true",
                   help="imprime tambien las propiedades de cada nodo")
    p.set_defaults(func=cmd_kidstask)

    sn = sub.add_parser("snd", help="bancos de sonido .srsa (ASRS/KTSR): listar, extraer y sustituir")
    snsub = sn.add_subparsers(dest="sndcmd", required=True)

    p = snsub.add_parser("list", help="los streams del banco: codec, frecuencia, muestras, nombre",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa")
    p.add_argument("--srst", help="fichero .srst: completa los streams externos con "
                                  "su codec, frecuencia, muestras y bucle")
    p.set_defaults(func=cmd_snd_list)

    p = snsub.add_parser("extract", help="escribir el flujo crudo de cada stream",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa")
    p.add_argument("--out", required=True, help="carpeta de salida (nunca dentro del romfs)")
    p.add_argument("--stream", type=int, action="append",
                   help="solo este stream (repetible); por defecto, todos")
    p.add_argument("--srst", help="fichero .srst: extrae tambien los streams externos "
                                  "(flujo ya descifrado)")
    p.set_defaults(func=cmd_snd_extract)

    p = snsub.add_parser("replace", help="sustituir audio: intercambiar dos streams o meter otro flujo",
                         parents=[common])
    p.add_argument("bank", help="fichero .srsa de partida")
    p.add_argument("--srst", help="fichero .srst: el stream es externo y su audio vive ahi "
                                  "(se escribe sobre el `.srst`, no sobre el banco)")
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
    p.add_argument("--srst", help="fichero .srst: el stream es externo y su audio vive ahi "
                                  "(el WAV tiene que traer sus mismos canales y su misma "
                                  "frecuencia)")
    p.add_argument("--loop", type=int, default=-1,
                   help="muestra donde empieza el bucle (-1 = sin bucle, por defecto)")
    p.add_argument("-o", "--out", help="fichero de salida (por defecto: el mismo, con --in-place)")
    p.add_argument("--in-place", action="store_true",
                   help="escribir sobre el banco (deja <banco>.orig la primera vez)")
    p.set_defaults(func=cmd_snd_import)

    p = snsub.add_parser("revert",
                         help="deshacer una sustitucion: restaura <fichero>.orig",
                         parents=[common])
    p.add_argument("file", help="banco .srsa o .srst que se habia modificado con --in-place")
    p.set_defaults(func=cmd_snd_revert)

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
    except kidstask.KidstaskError as exc:
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
