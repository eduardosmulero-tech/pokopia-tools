"""Carga y validacion del manifiesto `mod.json` (contrato: docs/MOD-FORMAT.md).

El contrato es el de `docs/ARQUITECTURA-KIT.md` §4:

    mod_format, name, version, authors, game{title, version, container_md5},
    requires[], edits[{table,row,offset,type,expect,value,why}],
    text[{table,id,slot,expect_sha256|expect,value,why}], files[{path,sha256}],
    romfs[{path,file,why,size,sha256,original_sha256}]

`romfs[]` es la seccion que hace instalable un mod: cada entrada dice que fichero
del romfs sustituye (`path`), con que fichero del mod (`file`) y cual era el
original (`original_sha256`, para poder demostrar que al desinstalar vuelve). Ver
docs/MOD-OVERLAY.es.md §3 y docs/MOD-FORMAT.md §11.

`expect` y `why` son obligatorios en toda edicion de bytes. En las ediciones de
texto el `expect` es **o** `expect_sha256` **o** `expect` (texto en claro), nunca
los dos: el sha256 del bloque es la forma publicable, porque identifica el bloque
sin escribir su contenido (docs/MOD-FORMAT.md §3.1). Aqui no se aplica nada:
solo se lee, se comprueba la forma y —si se pasa el contenedor— los rangos, el
`container_md5` y el `expect` contra los bytes reales.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from dataclasses import dataclass, field

from .. import paths, tables
from ..container import read_container, unpack_entry
from . import types as mt
from .errors import ModError, Report

MOD_FORMAT = 1
MANIFEST = "mod.json"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
#: sha256 del bloque de texto: 64 hex en minusculas, sin prefijo ni espacios.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONFIDENCES = ("verified", "inference", "guess")
REQUIRED_MD5_KEYS = (paths.BIN_NAME, paths.IDX_NAME)


# --------------------------------------------------------------------------
# Estructuras
# --------------------------------------------------------------------------

@dataclass
class Edit:
    """Una escritura de bytes declarada: `table[row + offset] = value`."""

    table: int
    row: int
    offset: int
    type: str
    expect: str
    value: str
    why: str
    confidence: str = "verified"
    note: str = ""
    index: int = 0

    @property
    def size(self) -> int | None:
        return mt.type_size(self.type)

    def where(self) -> str:
        return "edits[%d] #%d fila %d +%d %s" % (self.index, self.table, self.row,
                                                 self.offset, self.type)

    def as_dict(self) -> dict:
        out = {"table": self.table, "row": self.row, "offset": self.offset,
               "type": self.type, "expect": self.expect, "value": self.value,
               "why": self.why}
        if self.confidence != "verified":
            out["confidence"] = self.confidence
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class TextEdit:
    """Una escritura de texto declarada: `table[id, slot] = value`.

    `expect_sha256` y `expect` son excluyentes y uno de los dos es obligatorio.
    El hash es el del **bloque de 6 slots** del id, no el del slot suelto
    (criterio fijado en docs/MOD-FORMAT.md §3.1): un solo hash cubre el bloque
    entero y se calcula sin escribir ni una letra del juego.
    """

    table: int
    id: int
    value: str
    why: str
    expect: str = ""
    expect_sha256: str = ""
    slot: int = tables.SINGULAR_SLOT
    confidence: str = "verified"
    note: str = ""
    index: int = 0

    @property
    def uses_hash(self) -> bool:
        """El `expect` de esta edicion es un sha256 de bloque (no texto)."""
        return bool(self.expect_sha256)

    def where(self) -> str:
        return "text[%d] #%d id %d slot %d" % (self.index, self.table, self.id,
                                               self.slot)

    def as_dict(self) -> dict:
        out: dict[str, object] = {"table": self.table, "id": self.id, "slot": self.slot}
        if self.uses_hash:
            out["expect_sha256"] = self.expect_sha256
        else:
            out["expect"] = self.expect
        out["value"] = self.value
        out["why"] = self.why
        if self.confidence != "verified":
            out["confidence"] = self.confidence
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class RomfsFile:
    """Un fichero que el mod pone en el overlay: sustituye `path` del romfs.

    `path` y `file` son rutas relativas con `/`. `size`/`sha256` los rellena
    `pkp mod pack` (si vienen, se comprueban antes de instalar) y
    `original_sha256` es el hash de lo que el `RomFS.img` sirve hoy en `path`:
    sin el no se puede demostrar que al desinstalar vuelve el original.
    """

    path: str
    file: str
    why: str
    size: int | None = None
    sha256: str = ""
    original_sha256: str | None = None

    def where(self) -> str:
        return "romfs[%s]" % self.path

    def as_dict(self) -> dict:
        out: dict[str, object] = {"path": self.path, "file": self.file, "why": self.why}
        if self.size is not None:
            out["size"] = self.size
        if self.sha256:
            out["sha256"] = self.sha256
        if self.original_sha256:
            out["original_sha256"] = self.original_sha256
        return out


@dataclass
class Mod:
    path: str                      # carpeta del mod
    manifest: str                  # ruta del mod.json
    doc: dict
    mod_format: int = 0            # version del formato declarada (0 = ausente/ilegible)
    name: str = ""
    version: str = ""
    authors: list[str] = field(default_factory=list)
    description: str = ""
    title: str = ""
    game_version: str = ""
    container_md5: dict[str, str] = field(default_factory=dict)
    requires: list = field(default_factory=list)
    edits: list[Edit] = field(default_factory=list)
    texts: list[TextEdit] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    romfs: list[RomfsFile] = field(default_factory=list)
    report: Report = field(default_factory=Report)

    @property
    def label(self) -> str:
        return "%s@%s" % (self.name or os.path.basename(self.path), self.version or "?")


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------

def find_manifest(path: str) -> str:
    target = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(target):
        candidate = os.path.join(target, MANIFEST)
        if not os.path.isfile(candidate):
            raise ModError("no hay %s en %s" % (MANIFEST, target), code="io", where=path)
        return candidate
    if os.path.isfile(target):
        return target
    raise ModError("no existe %s" % target, code="io", where=path)


def _str_field(doc: dict, key: str, report: Report, *, required=True,
               default="") -> str:
    if key not in doc:
        if required:
            report.error("schema.%s" % key, "campo obligatorio que falta: %r" % key)
        return default
    value = doc[key]
    if not isinstance(value, str):
        report.error("schema.%s" % key, "%r debe ser cadena, es %s"
                     % (key, type(value).__name__))
        return default
    if required and not value.strip():
        report.error("schema.%s" % key, "%r no puede estar vacio" % key)
    return value


def _int_field(doc: dict, key: str, report: Report, where: str) -> int:
    if key not in doc:
        report.error("schema.missing", "falta %r" % key, where)
        return 0
    value = doc[key]
    if isinstance(value, bool) or not isinstance(value, int):
        report.error("schema.type", "%s: %r debe ser entero, es %r"
                     % (where, key, value), where)
        return 0
    if value < 0:
        report.error("schema.range", "%s: %r no puede ser negativo (%d)"
                     % (where, key, value), where)
        return 0
    return value


def load_mod(path: str) -> Mod:
    """Lee un mod (carpeta o `mod.json`) y devuelve el objeto con su informe."""
    manifest = find_manifest(path)
    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ModError("JSON invalido en %s: %s (linea %d, columna %d)"
                       % (manifest, exc.msg, exc.lineno, exc.colno),
                       code="json", where=path) from None
    if not isinstance(doc, dict):
        raise ModError("%s: la raiz debe ser un objeto JSON, es %s"
                       % (manifest, type(doc).__name__), code="json", where=path)
    return parse_mod(doc, manifest)


def parse_mod(doc: dict, manifest: str) -> Mod:
    mod = Mod(path=os.path.dirname(os.path.abspath(manifest)), manifest=manifest, doc=doc)
    rep = mod.report

    known_keys = {"mod_format", "name", "version", "authors", "description", "game",
                  "requires", "edits", "text", "files", "romfs", "merged_from"}
    for key in doc:
        if key not in known_keys:
            rep.warning("schema.unknown_key", "clave desconocida ignorada: %r" % key)

    fmt = doc.get("mod_format")
    mod.mod_format = fmt if isinstance(fmt, int) and not isinstance(fmt, bool) else 0
    if fmt is None:
        rep.error("schema.mod_format", "falta 'mod_format' (debe ser %d)" % MOD_FORMAT)
    elif fmt != MOD_FORMAT:
        rep.error("schema.mod_format", "'mod_format' es %r y esta version del kit "
                                      "solo entiende %d" % (fmt, MOD_FORMAT))

    mod.name = _str_field(doc, "name", rep)
    if mod.name and not NAME_RE.match(mod.name):
        rep.error("schema.name", "'name' debe cumplir %s (minusculas, digitos, . _ -)"
                  % NAME_RE.pattern)
    mod.version = _str_field(doc, "version", rep)
    if mod.version and not re.match(r"^\d+\.\d+\.\d+", mod.version):
        rep.warning("schema.version", "'version' %r no parece semver (x.y.z)"
                    % mod.version)
    mod.description = _str_field(doc, "description", rep, required=False)

    authors = doc.get("authors")
    if authors is None:
        rep.error("schema.authors", "falta 'authors' (lista, aunque sea vacia)")
    elif not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
        rep.error("schema.authors", "'authors' debe ser una lista de cadenas")
    else:
        mod.authors = list(authors)
        if not authors:
            rep.warning("schema.authors", "'authors' esta vacio")

    _parse_game(mod, doc, rep)
    _parse_requires(mod, doc, rep)
    _parse_edits(mod, doc, rep)
    _parse_texts(mod, doc, rep)
    _parse_files(mod, doc, rep)
    _parse_romfs(mod, doc, rep)

    if not mod.edits and not mod.texts and not mod.romfs:
        rep.warning("mod.empty", "el mod no declara ninguna edicion: no hace nada")
    return mod


def _parse_game(mod: Mod, doc: dict, rep: Report) -> None:
    game = doc.get("game")
    if game is None:
        rep.error("schema.game", "falta 'game' con title, version y container_md5")
        return
    if not isinstance(game, dict):
        rep.error("schema.game", "'game' debe ser un objeto")
        return
    mod.title = _str_field(game, "title", rep)
    mod.game_version = _str_field(game, "version", rep)
    md5s = game.get("container_md5")
    if md5s is None:
        rep.error("schema.game.container_md5",
                  "falta 'game.container_md5' (no se aplica un mod sin el md5 del "
                  "contenedor para el que se escribio)")
        return
    if not isinstance(md5s, dict):
        rep.error("schema.game.container_md5", "'container_md5' debe ser un objeto")
        return
    for key in REQUIRED_MD5_KEYS:
        value = md5s.get(key)
        if value is None:
            rep.error("schema.game.container_md5", "falta el md5 de %s" % key)
            continue
        if not isinstance(value, str) or not HEX32_RE.match(value.lower()):
            rep.error("schema.game.container_md5",
                      "md5 de %s debe ser 32 caracteres hex, es %r" % (key, value))
            continue
        mod.container_md5[key] = value.lower()
    extra = set(md5s) - set(REQUIRED_MD5_KEYS)
    if extra:
        rep.warning("schema.game.container_md5",
                    "claves de md5 desconocidas: %s" % ", ".join(sorted(extra)))


def _parse_requires(mod: Mod, doc: dict, rep: Report) -> None:
    requires = doc.get("requires", [])
    if not isinstance(requires, list):
        rep.error("schema.requires", "'requires' debe ser una lista")
        return
    for i, item in enumerate(requires):
        if not isinstance(item, (str, dict)):
            rep.error("schema.requires", "requires[%d] debe ser cadena u objeto" % i)
    mod.requires = list(requires)


def _parse_common(mod: Mod, raw: dict, rep: Report, where: str) -> tuple[str, str, str]:
    why = _str_field(raw, "why", rep)
    if not why.strip():
        rep.error("schema.why", "'why' es obligatorio y no puede estar vacio "
                                "(que campo crees que tocas)", where)
    confidence = raw.get("confidence", "verified")
    if confidence not in CONFIDENCES:
        rep.error("schema.confidence", "'confidence' debe ser uno de %s, es %r"
                  % (", ".join(CONFIDENCES), confidence), where)
        confidence = "guess"
    if confidence == "guess":
        rep.warning("mod.confidence_guess",
                    "confidence=guess — campo sin esquema que lo respalde", where)
    note = raw.get("note", "")
    if note and not isinstance(note, str):
        rep.error("schema.note", "'note' debe ser cadena", where)
        note = ""
    return why, confidence, note


def _parse_edits(mod: Mod, doc: dict, rep: Report) -> None:
    edits = doc.get("edits", [])
    if not isinstance(edits, list):
        rep.error("schema.edits", "'edits' debe ser una lista")
        return
    for i, raw in enumerate(edits):
        where = "edits[%d]" % i
        if not isinstance(raw, dict):
            rep.error("schema.edits", "debe ser un objeto", where)
            continue
        table = _int_field(raw, "table", rep, where)
        row = _int_field(raw, "row", rep, where)
        offset = _int_field(raw, "offset", rep, where)
        typ = raw.get("type")
        if not isinstance(typ, str) or typ not in mt.TYPES:
            rep.error("schema.type", "'type' debe ser uno de %s, es %r"
                      % (", ".join(mt.TYPES), typ), where)
            continue
        expect = raw.get("expect")
        if expect is None:
            rep.error("schema.expect", "'expect' es obligatorio (que habia antes)", where)
            continue
        if "value" not in raw:
            rep.error("schema.value", "falta 'value'", where)
            continue
        why, confidence, note = _parse_common(mod, raw, rep, where)
        try:
            mt.encode(typ, expect)
            mt.encode(typ, raw["value"])
        except mt.TypeError_ as exc:
            rep.error("schema.value", str(exc), where)
            continue
        edit = Edit(table=table, row=row, offset=offset, type=typ,
                    expect=expect if isinstance(expect, str) else str(expect),
                    value=raw["value"] if isinstance(raw["value"], str) else str(raw["value"]),
                    why=why, confidence=confidence, note=note, index=i)
        spec = tables.get(table)
        if spec is None:
            rep.warning("mod.unknown_table",
                        "la tabla #%d no tiene geometria declarada; solo se "
                        "comprobara offset+len contra el tamano del payload" % table,
                        where)
        elif spec.kind == "text":
            rep.warning("mod.edit_in_text_table",
                        "la tabla #%d es de texto; una edicion de bytes en su zona "
                        "de registros no tiene esquema" % table, where)
        else:
            size = mt.type_size(typ)
            if size is not None and offset + size > spec.stride:
                rep.error("schema.range",
                          "offset %d + %d B se sale del stride de %d B de la tabla #%d"
                          % (offset, size, spec.stride, table), where)
                continue
            if row >= spec.count:
                rep.error("schema.range", "fila %d fuera de rango (0..%d) de #%d"
                          % (row, spec.count - 1, table), where)
                continue
        mod.edits.append(edit)


def _parse_texts(mod: Mod, doc: dict, rep: Report) -> None:
    texts = doc.get("text", [])
    if not isinstance(texts, list):
        rep.error("schema.text", "'text' debe ser una lista")
        return
    seen: dict[tuple[int, int, int], int] = {}
    for i, raw in enumerate(texts):
        where = "text[%d]" % i
        if not isinstance(raw, dict):
            rep.error("schema.text", "debe ser un objeto", where)
            continue
        table = _int_field(raw, "table", rep, where)
        text_id = _int_field(raw, "id", rep, where)
        slot = raw.get("slot", tables.SINGULAR_SLOT)
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < 6:
            rep.error("schema.text.slot", "'slot' debe ser entero 0..5, es %r" % slot,
                      where)
            continue
        expect, expect_sha256 = _parse_text_expect(raw, rep, where)
        if expect is None:
            continue
        value = raw.get("value")
        if not isinstance(value, str):
            rep.error("schema.text.value", "'value' debe ser cadena", where)
            continue
        if "\x00" in value:
            rep.error("schema.text.value", "'value' no puede contener NUL", where)
            continue
        why, confidence, note = _parse_common(mod, raw, rep, where)
        spec = tables.get(table)
        if spec is None:
            rep.error("schema.text.table",
                      "la tabla #%d no tiene geometria declarada" % table, where)
            continue
        if spec.kind != "text":
            rep.error("schema.text.table", "la tabla #%d no es de texto" % table, where)
            continue
        try:
            tables.slot_ordinal(spec, text_id, slot)
        except tables.TableError as exc:
            rep.error("schema.range", str(exc), where)
            continue
        key = (table, text_id, slot)
        if key in seen:
            rep.error("mod.text.duplicate",
                      "dos ediciones del mismo slot de texto (text[%d] y %s): declara "
                      "una sola; para el mismo bloque usa slots distintos"
                      % (seen[key], where), where)
            continue
        seen[key] = i
        mod.texts.append(TextEdit(table=table, id=text_id, value=value, expect=expect,
                                  expect_sha256=expect_sha256 or "", why=why,
                                  slot=slot, confidence=confidence,
                                  note=note, index=i))


def _parse_text_expect(raw: dict, rep: Report, where: str) -> tuple[str | None, str | None]:
    """`expect` (texto en claro) o `expect_sha256` (bloque), excluyentes.

    Devuelve `(expect, expect_sha256)`; `expect` es `None` si hay error y la
    edicion no se puede construir.
    """
    has_text = "expect" in raw
    has_hash = "expect_sha256" in raw
    if has_text and has_hash:
        rep.error("schema.text.expect",
                  "'expect' y 'expect_sha256' son mutuamente excluyentes: declara solo "
                  "uno (el sha256 del bloque, si no quieres escribir el texto en claro)",
                  where)
        return None, None
    if not has_text and not has_hash:
        rep.error("schema.text.expect",
                  "falta 'expect_sha256' (sha256 del bloque de 6 slots; criterio en "
                  "docs/MOD-FORMAT.md §3.1). 'expect' con el texto en claro se acepta, "
                  "pero no se publica", where)
        return None, None
    if has_hash:
        sha = raw["expect_sha256"]
        if not isinstance(sha, str):
            rep.error("schema.text.expect_sha256",
                      "'expect_sha256' debe ser cadena, es %s" % type(sha).__name__,
                      where)
            return None, None
        if not SHA256_RE.match(sha):
            rep.error("schema.text.expect_sha256",
                      "'expect_sha256' debe ser sha256 hexadecimal en minusculas de 64 "
                      "caracteres (es %d caracteres: %r)"
                      % (len(sha), sha[:16] + ("..." if len(sha) > 16 else "")),
                      where)
            return None, None
        return "", sha
    expect = raw["expect"]
    if not isinstance(expect, str):
        rep.error("schema.text.expect", "'expect' debe ser cadena", where)
        return None, None
    return expect, None


def _parse_files(mod: Mod, doc: dict, rep: Report) -> None:
    files = doc.get("files", [])
    if not isinstance(files, list):
        rep.error("schema.files", "'files' debe ser una lista")
        return
    for i, raw in enumerate(files):
        if not isinstance(raw, dict) or "path" not in raw:
            rep.error("schema.files", "files[%d] debe ser un objeto con 'path'" % i)
            continue
        mod.files.append(raw)


#: Ruta relativa dentro del romfs: sin raiz, sin unidad, sin `..`, con `/`.
ROMFS_PATH_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/ -]*$")


def romfs_path_problem(text: object) -> str | None:
    """Motivo por el que `text` no vale como ruta interna del romfs (o `None`).

    Una ruta del manifiesto acaba siendo un `os.path.join` en el overlay: si
    admite `..`, `C:` o una raiz absoluta, el mod puede escribir fuera de su
    carpeta. Se rechaza aqui, una vez, en vez de en cada llamador.
    """
    if not isinstance(text, str) or not text.strip():
        return "no puede estar vacia"
    if "\\" in text:
        return "usa '/' como separador, no '\\': %r" % text
    if text.startswith("/"):
        return "no puede empezar por '/': %r" % text
    if ":" in text:
        return "no puede llevar unidad ni ':' (el runtime trocea el overlay por ':'): %r" % text
    if ".." in text.split("/"):
        return "no puede llevar '..': %r" % text
    if any(part in ("", ".") for part in text.split("/")):
        return "tiene un tramo vacio o '.': %r" % text
    if not ROMFS_PATH_RE.match(text):
        return "solo admite letras, digitos, '.', '_', '-', ' ' y '/': %r" % text
    return None


def _parse_romfs(mod: Mod, doc: dict, rep: Report) -> None:
    romfs = doc.get("romfs", [])
    if not isinstance(romfs, list):
        rep.error("schema.romfs", "'romfs' debe ser una lista")
        return
    vistos: dict[str, int] = {}
    for i, raw in enumerate(romfs):
        where = "romfs[%d]" % i
        if not isinstance(raw, dict):
            rep.error("schema.romfs", "debe ser un objeto", where)
            continue
        path = raw.get("path")
        malo = romfs_path_problem(path)
        if malo is not None or not isinstance(path, str):
            rep.error("schema.romfs.path", "romfs[%d].path %s" % (i, malo), where)
            continue
        if path in vistos:
            rep.error("schema.romfs.path",
                      "romfs[%d] y romfs[%d] sustituyen la misma ruta %r: declara una sola"
                      % (vistos[path], i, path), where)
            continue
        vistos[path] = i
        file = raw.get("file")
        malo = romfs_path_problem(file)
        if malo is not None or not isinstance(file, str):
            rep.error("schema.romfs.file", "romfs[%d].file %s" % (i, malo), where)
            continue
        why = _str_field(raw, "why", rep)
        if not why.strip():
            rep.error("schema.why", "'why' es obligatorio y no puede estar vacio "
                                    "(que fichero del romfs sustituyes)", where)
        size = raw.get("size")
        if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
            rep.error("schema.romfs.size", "'size' debe ser entero >= 0, es %r" % (size,),
                      where)
            size = None
        sha = raw.get("sha256", "")
        if sha and (not isinstance(sha, str) or not SHA256_RE.match(sha)):
            rep.error("schema.romfs.sha256",
                      "'sha256' debe ser sha256 hexadecimal en minusculas de 64 caracteres",
                      where)
            sha = ""
        original = raw.get("original_sha256")
        if original is not None and (not isinstance(original, str)
                                     or not SHA256_RE.match(original)):
            rep.error("schema.romfs.original_sha256",
                      "'original_sha256' debe ser sha256 hexadecimal en minusculas de 64 "
                      "caracteres (lo calcula `pkp mod pack --img`)", where)
            original = None
        mod.romfs.append(RomfsFile(path=path, file=file, why=why, size=size,
                                   sha256=sha or "", original_sha256=original))


# --------------------------------------------------------------------------
# Validacion contra el contenedor
# --------------------------------------------------------------------------

class ContainerView:
    """Contenedor leido una vez; payloads descomprimidos bajo demanda y cacheados."""

    def __init__(self, container: paths.Container):
        self.container = container
        self.entries, self.bin_data = read_container(container.idx, container.bin)
        self._cache: dict[int, bytes] = {}

    def payload(self, table: int) -> bytes:
        if table not in self._cache:
            if not 0 <= table < len(self.entries):
                raise ModError("tabla #%d fuera de rango (0..%d)"
                               % (table, len(self.entries) - 1), code="table")
            self._cache[table] = unpack_entry(self.bin_data, self.entries[table],
                                              index=table)
        return self._cache[table]


def check_container_identity(mod: Mod, container: paths.Container, rep: Report) -> None:
    """`game.container_md5` contra los md5 reales del contenedor."""
    actual = paths.container_md5(container)
    for key, expected in mod.container_md5.items():
        found = actual.get(key)
        if found != expected:
            rep.error("mod.container_md5",
                      "%s: esperaba %s (%s) y encontre %s — este mod se escribio para "
                      "otro contenedor" % (key, expected, mod.game_version or "?",
                                           found))


def validate(mod: Mod, container: paths.Container | None = None,
             check_expect: bool = True, view: "ContainerView | None" = None) -> Report:
    """Informe completo: esquema (ya hecho al cargar) + contenedor."""
    rep = mod.report
    if container is None:
        if mod.container_md5 and check_expect:
            rep.warning("validate.sin_contenedor",
                        "sin contenedor: no se ha comprobado container_md5 ni expect")
        return rep
    check_container_identity(mod, container, rep)
    if not rep.ok:
        # md5 distinto o esquema roto: los `expect` no significan nada aqui
        return rep
    if not check_expect:
        return rep
    view = view or ContainerView(container)

    by_table: dict[int, list[Edit]] = {}
    for edit in mod.edits:
        by_table.setdefault(edit.table, []).append(edit)
    for table, edits in sorted(by_table.items()):
        try:
            blob = view.payload(table)
        except ModError as exc:
            rep.error("mod.table", str(exc))
            continue
        spec = tables.get(table)
        for edit in edits:
            _check_edit(edit, blob, spec, rep)

    for text in mod.texts:
        spec = tables.get(text.table)
        if spec is None:
            rep.error("mod.table", "la tabla #%d no tiene geometria declarada"
                      % text.table, text.where())
            continue
        try:
            blob = view.payload(text.table)
        except ModError as exc:
            rep.error("mod.table", str(exc))
            continue
        _check_text(text, blob, spec, rep)
    return rep


def _check_edit(edit: Edit, blob: bytes, spec: tables.TableSpec | None,
                rep: Report) -> None:
    size = mt.type_size(edit.type)
    if size is None:
        size = len(mt.encode(edit.type, edit.value))
    if spec is not None:
        start = spec.row_offset(edit.row) + edit.offset
    else:
        start = edit.offset
        rep.warning("mod.unknown_table",
                    "sin stride declarado, no se comprueba offset+len <= stride",
                    edit.where())
    if start + size > len(blob):
        rep.error("mod.range", "bytes %d..%d fuera del payload de %d B"
                  % (start, start + size, len(blob)), edit.where())
        return
    found = blob[start:start + size]
    try:
        expected = mt.encode(edit.type, edit.expect)
    except mt.TypeError_ as exc:
        rep.error("mod.expect", "expect invalido: %s" % exc, edit.where())
        return
    if found != expected:
        rep.error("mod.expect",
                  "esperaba %s y encontre %s"
                  % (mt.describe(edit.type, expected),
                     mt.describe(edit.type, found)), edit.where())


def text_expect_mismatch(text: TextEdit, spec: tables.TableSpec,
                         slots: list[bytes]) -> str | None:
    """Mensaje de fallo del `expect` de un texto, o `None` si cuadra.

    Regla dura (docs/MOD-FORMAT.md §3, privacidad del texto): el mensaje **nunca**
    imprime el texto del juego. Ni el encontrado ni el esperado: solo longitudes
    y sha256. El esperado tambien se calla cuando el mod traia texto en claro,
    porque ese texto vino del juego cuando el autor lo copio del dump.
    """
    if text.uses_hash:
        block = tables.block_slots(spec, slots, text.id)
        found = tables.block_sha256(spec, slots, text.id)
        if found == text.expect_sha256:
            return None
        return ("esperaba el bloque con sha256 %s y encontre otro (%d B en %d slots, "
                "sha256 %s)" % (text.expect_sha256, len(b"".join(block)),
                                len(block), found[:12]))
    expected = text.expect.encode("utf-8")
    ordinal = tables.slot_ordinal(spec, text.id, text.slot)
    found_slot = slots[ordinal]
    if found_slot == expected:
        return None
    return ("esperaba un texto de %d B y encontre otro de %d B (sha256 %s)"
            % (len(expected), len(found_slot),
               hashlib.sha256(found_slot).hexdigest()[:12]))


def _check_text(text: TextEdit, blob: bytes, spec: tables.TableSpec, rep: Report) -> None:
    try:
        slots, _ = tables.parse_pool(spec, blob)
        ordinal = tables.slot_ordinal(spec, text.id, text.slot)
    except tables.TableError as exc:
        rep.error("mod.text.geometry", str(exc), text.where())
        return
    if ordinal >= len(slots):
        rep.error("mod.text.range", "el slot %d no existe (la tabla tiene %d slots)"
                  % (ordinal, len(slots)), text.where())
        return
    try:
        message = text_expect_mismatch(text, spec, slots)
    except tables.TableError as exc:
        rep.error("mod.text.geometry", str(exc), text.where())
        return
    if message:
        rep.error("mod.text.expect", message, text.where())
