"""Composicion de dos mods (`pkp mod merge`).

Reglas (docs/ARQUITECTURA-KIT.md §4.4 y docs/MOD-FORMAT.md):

* se compone por `(table, row, offset)`, nunca por fichero;
* **solape exacto** — misma tabla, fila y offset — es **conflicto**, aunque el
  valor coincida: dos mods que declaran lo mismo no se ordenan;
* **solape parcial** de rangos en la misma fila con valores distintos es
  **conflicto**; con los mismos bytes tambien, porque el orden sigue sin estar
  definido;
* **misma fila, offsets distintos** (rangos disjuntos) se permite, con aviso;
* filas o tablas distintas conviven sin ruido.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .. import paths, tables
from . import types as mt
from .errors import ModError, Report
from .manifest import Edit, Mod, TextEdit, load_mod


@dataclass
class MergeResult:
    doc: dict | None
    report: Report = field(default_factory=Report)
    written: str | None = None

    @property
    def ok(self) -> bool:
        return self.report.ok and self.doc is not None


def _byte_range(edit: Edit) -> tuple[int, int]:
    size = mt.type_size(edit.type)
    if size is None:
        size = len(mt.encode(edit.type, edit.value))
    return edit.offset, edit.offset + size


def _slot_ordinal(edit: TextEdit) -> int:
    spec = tables.get(edit.table)
    return tables.slot_ordinal(spec, edit.id, edit.slot) if spec else -1


def check_pair(a: Mod, b: Mod, rep: Report) -> None:
    """Conflictos y avisos entre dos mods ya validados en forma."""
    for ea in a.edits:
        for eb in b.edits:
            if ea.table != eb.table or ea.row != eb.row:
                continue
            sa, sb = _byte_range(ea), _byte_range(eb)
            same_start = ea.offset == eb.offset
            overlap = sa[0] < sb[1] and sb[0] < sa[1]
            if same_start and sa == sb:
                rep.error("merge.conflict",
                          "solape exacto en #%d fila %d +%d: %s@%s y %s@%s"
                          % (ea.table, ea.row, ea.offset, a.label, ea.value,
                             b.label, eb.value))
            elif overlap:
                rep.error("merge.conflict",
                          "solape parcial en #%d fila %d: [%d,%d) de %s y [%d,%d) de %s"
                          % (ea.table, ea.row, sa[0], sa[1], a.label, sb[0], sb[1],
                             b.label))
            else:
                rep.warning("merge.same_row",
                            "misma fila #%d fila %d con offsets distintos (+%d y +%d): "
                            "se permite, revisa que no se pisen al aplicarse"
                            % (ea.table, ea.row, ea.offset, eb.offset))
    for ta in a.texts:
        for tb in b.texts:
            if ta.table != tb.table or ta.id != tb.id:
                continue
            if ta.slot == tb.slot:
                rep.error("merge.conflict",
                          "solape exacto de texto en #%d id %d slot %d: %s@%r y %s@%r"
                          % (ta.table, ta.id, ta.slot, a.label, ta.value, b.label,
                             tb.value))
            else:
                rep.warning("merge.same_row",
                            "mismo bloque de texto #%d id %d con slots distintos (%d y %d)"
                            % (ta.table, ta.id, ta.slot, tb.slot))


def _default_name(a: Mod, b: Mod) -> str:
    """Nombre valido (minusculas, digitos, . _ -) para el mod compuesto."""
    base = "%s--%s" % (a.name, b.name)
    slug = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-.")[:64].strip("-.")
    return slug or "merge"


def compose(a: Mod, b: Mod, *, name: str | None = None, version: str = "0.1.0") -> dict:
    """Documento `mod.json` compuesto (sin escribir)."""
    authors: list[str] = []
    for mod in (a, b):
        for author in mod.authors:
            if author not in authors:
                authors.append(author)
    requires = list(a.requires)
    for item in b.requires:
        if item not in requires:
            requires.append(item)
    doc = {
        "mod_format": 1,
        "name": name or _default_name(a, b),
        "version": version,
        "authors": authors or ["pkp merge"],
        "description": "composicion de %s y %s" % (a.label, b.label),
        "game": {
            "title": a.title or b.title,
            "version": a.game_version or b.game_version,
            "container_md5": dict(a.container_md5 or b.container_md5),
        },
        "requires": requires,
        "edits": [e.as_dict() for e in a.edits] + [e.as_dict() for e in b.edits],
        "text": [t.as_dict() for t in a.texts] + [t.as_dict() for t in b.texts],
        "files": list(a.files) + list(b.files),
        "merged_from": [{"name": a.name, "version": a.version},
                        {"name": b.name, "version": b.version}],
    }
    return doc


def merge_mods(path_a: str, path_b: str, out_dir: str | None = None, *,
               name: str | None = None, version: str = "0.1.0",
               container_dir: str | None = None,
               check_container: bool = True) -> MergeResult:
    """Compone dos mods. Si `out_dir` se da y no hay conflictos, escribe mod.json."""
    a = load_mod(path_a)
    b = load_mod(path_b)
    rep = Report()
    rep.extend(a.report)
    rep.extend(b.report)
    if not rep.ok:
        return MergeResult(None, rep)

    # Los ficheros de overlay no se componen: `merge` produce un unico `mod.json` y
    # cada mod trae sus propios ficheros. Instalarlos por separado deja el mismo
    # resultado y `pkp mod status` avisa si dos de ellos pisan la misma ruta.
    con_romfs = [mod.label for mod in (a, b) if mod.romfs]
    if con_romfs:
        rep.error("merge.romfs",
                  "%s declara ficheros en `romfs[]`: los ficheros de overlay no se "
                  "combinan, instala los dos mods en el almacen y deja que el orden de "
                  "`DM_ROMFS_OVERLAY` decida" % " y ".join(con_romfs))
        return MergeResult(None, rep)

    if a.container_md5 and b.container_md5 and a.container_md5 != b.container_md5:
        rep.error("merge.container_md5",
                  "los dos mods declaran contenedores distintos: %s y %s"
                  % (a.container_md5, b.container_md5))
        return MergeResult(None, rep)

    if check_container:
        container = paths.resolve_container(container_dir, must_exist=False)
        if os.path.isfile(container.idx):
            from .manifest import check_container_identity
            check_container_identity(a, container, rep)
            check_container_identity(b, container, rep)
            if not rep.ok:
                return MergeResult(None, rep)

    check_pair(a, b, rep)
    if not rep.ok:
        return MergeResult(None, rep)

    doc = compose(a, b, name=name, version=version)
    result = MergeResult(doc, rep)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        target = os.path.join(out_dir, "mod.json")
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        result.written = target
    return result
