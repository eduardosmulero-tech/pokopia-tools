"""Parte de progreso en cifras: solo magnitudes contables, ningun nombre del juego.

Cada magnitud sale de una `ProgressSpec` del layout, y el layout solo nombra regiones y
campos por geometria. Los evaluadores que hay aqui no saben offsets: piden la region al
layout y cuentan. Por eso añadir una version de save no obliga a tocar este fichero.

Evaluadores (`kind`):

  occupied       registros con algun byte no nulo en el rango [arg, arg2] del registro
  distinct_ids   valores distintos de `u32 & arg` leidos en el offset `arg2` del registro
  bit_set        registros cuyo byte `arg2` tiene puesto el bit `arg`

Hay una magnitud que **no** sale del payload: `zonas`, el numero de ficheros de zona
(`STGDATnn.BIN`) que la pagina tiene en disco. Se construye aparte (`zones.py`) y se
engancha al parte con `build_report(page, zones=...)`; su confianza es `inferred`
porque la semantica («zona con datos» = «zona desbloqueada») no esta demostrada dentro
del juego, solo el recuento de ficheros.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from . import items as items_mod
from . import zones as zones_mod
from .errors import SaveError
from .page import SavePage


@dataclass(frozen=True)
class ProgressValue:
    """Una cifra del parte."""

    key: str
    value: int
    total: int | None
    confidence: str
    evidence: str

    @property
    def percent(self) -> float | None:
        if not self.total:
            return None
        return 100.0 * self.value / self.total

    def as_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "total": self.total,
                "percent": None if self.percent is None else round(self.percent, 1),
                "confidence": self.confidence, "evidence": self.evidence}


@dataclass(frozen=True)
class ProgressReport:
    """Parte completo de una pagina, con lo que no se puede medir declarado.

    `zones` va aparte de `values` porque no sale del payload sino del directorio de la
    pagina (ficheros `STGDATnn.BIN`); puede ser `None` si no se pidio.
    """

    page: SavePage
    values: tuple[ProgressValue, ...]
    unmeasured: tuple[tuple[str, str], ...]
    zones: ProgressValue | None = None

    def get(self, key: str) -> ProgressValue | None:
        for v in self.values:
            if v.key == key:
                return v
        if self.zones is not None and self.zones.key == key:
            return self.zones
        return None

    def as_dict(self) -> dict:
        values = [v.as_dict() for v in self.values]
        if self.zones is not None:
            values.append(self.zones.as_dict())
        return {
            "page": self.page.page,
            "path": self.page.path,
            "md5": self.page.md5,
            "version": "%#010x" % self.page.version,
            "game": self.page.layout.game,
            "values": values,
            "unmeasured": [{"key": k, "reason": r} for k, r in self.unmeasured],
        }


# ---------------------------------------------------------------------------
# Evaluadores
# ---------------------------------------------------------------------------

def _count_occupied(page: SavePage, region: str, start: int, end: int) -> int:
    reg = page.layout.region(region)
    if start == 0 and end == 0:
        start, end = 0, reg.stride - 1
    if not 0 <= start <= end < reg.stride:
        raise SaveError("rango %d..%d fuera del registro de %d B (region %s)"
                        % (start, end, reg.stride, region))
    n = 0
    for i in range(reg.count):
        base = reg.offset + i * reg.stride
        if any(page.payload[base + o] for o in range(start, end + 1)):
            n += 1
    return n


def _count_distinct_ids(page: SavePage, region: str, mask: int, offset: int) -> int:
    reg = page.layout.region(region)
    seen = set()
    for i in range(reg.count):
        base = reg.offset + i * reg.stride + offset
        value = struct.unpack_from("<I", page.payload, base)[0] & mask
        if value:
            seen.add(value)
    return len(seen)


def _count_bit_set(page: SavePage, region: str, bit: int, offset: int) -> int:
    reg = page.layout.region(region)
    if not 0 <= bit <= 7:
        raise SaveError("bit %d fuera de 0..7" % bit)
    if not 0 <= offset < reg.stride:
        raise SaveError("offset %d fuera del registro de %d B (region %s)"
                        % (offset, reg.stride, region))
    flag = 1 << bit
    n = 0
    for i in range(reg.count):
        if page.payload[reg.offset + i * reg.stride + offset] & flag:
            n += 1
    return n


EVALUATORS = {
    "occupied": _count_occupied,
    "distinct_ids": _count_distinct_ids,
    "bit_set": _count_bit_set,
}


# ---------------------------------------------------------------------------
# Parte
# ---------------------------------------------------------------------------

def zone_value(save_dir: str, page: str = "G00") -> ProgressValue:
    """Magnitud `zonas`: ficheros de zona de la pagina. Sin denominador."""
    files = zones_mod.zone_files(save_dir, page)
    indices = [z.index for z in files]
    return ProgressValue(
        key="zonas", value=len(files), total=None, confidence="inferred",
        evidence=zones_mod.evidence_text(len(files), indices, page))


def build_report(page: SavePage, *, save_dir: str | None = None,
                 with_zones: bool = True) -> ProgressReport:
    """Parte de progreso de una pagina, segun su layout.

    Con `with_zones` (por defecto) se añade la cifra de ficheros de zona del directorio
    del save; si no se indica `save_dir` se deduce del propio `CMNDAT.BIN`.
    """
    values = []
    for spec in page.layout.progress:
        try:
            evaluator = EVALUATORS[spec.kind]
        except KeyError:
            raise SaveError("el layout %#010x declara el campo %r con un evaluador "
                            "desconocido %r (conocidos: %s)"
                            % (page.version, spec.key, spec.kind,
                               ", ".join(sorted(EVALUATORS))))
        if spec.kind == "occupied":
            n = evaluator(page, spec.region, spec.arg, spec.arg2)
        elif spec.kind == "distinct_ids":
            n = evaluator(page, spec.region, spec.arg, spec.arg2)
        else:
            n = evaluator(page, spec.region, spec.arg, spec.arg2)
        total = spec.total
        if total is None and spec.kind == "occupied":
            total = page.layout.region(spec.region).count
        values.append(ProgressValue(key=spec.key, value=n, total=total,
                                    confidence=spec.confidence,
                                    evidence=spec.evidence))
    zones = None
    if with_zones:
        base = save_dir
        if base is None:
            # .../<save>/<pagina>/CMNDAT.BIN -> .../<save>
            base = os.path.dirname(os.path.dirname(page.path))
        try:
            zones = zone_value(base, page.page)
        except (SaveError, OSError) as exc:  # fichero de zona roto: se declara
            zones = ProgressValue(
                key="zonas", value=0, total=None, confidence="inferred",
                evidence="no se pudo leer la carpeta de la pagina: %s" % exc)
    unmeasured = [(d.key, d.reason) for d in page.layout.discarded]
    return ProgressReport(page=page, values=tuple(values),
                          unmeasured=tuple(unmeasured), zones=zones)


def union_ids(*pages: SavePage) -> list[int]:
    """Ids distintos de varias paginas (para el 'G00 + B00' del parte)."""
    seen = set()
    for page in pages:
        seen.update(items_mod.distinct_ids(page))
    return sorted(seen)


def _short(reason: str, limit: int = 150) -> str:
    """Primera frase del motivo, recortada: el parte no es un informe."""
    corte = reason.find(". ")
    text = reason if corte < 0 else reason[:corte + 1]
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def format_report(report: ProgressReport, *, union: list[int] | None = None,
                  width: int = 12) -> list[str]:
    """Lineas del parte. Solo cifras, indices y etiquetas genericas.

    Lo que no se puede medir sale en su propia linea con el motivo, no en una lista
    de nombres: un renglon `sin medir: a, b, c` no dice por que.
    """
    lines = ["parte de progreso · save %s · pagina %s"
             % (report.page.layout.game, report.page.page)]
    keys = [v.key.replace("_", " ") for v in report.values]
    if report.zones is not None:
        keys.append(report.zones.key)
    keys.extend(k for k, _ in report.unmeasured)
    w = max([width] + [len(k) for k in keys])
    for value in report.values:
        label = value.key.replace("_", " ")
        if value.key == "bolsa_ids" and union is not None:
            lines.append("  %-*s: %5d distintos en G00+B00" % (w, label, len(union)))
            continue
        if value.total:
            lines.append("  %-*s: %5d / %-5d (%5.1f %%)"
                         % (w, label, value.value, value.total, value.percent or 0.0))
        else:
            lines.append("  %-*s: %5d" % (w, label, value.value))
    if report.zones is not None:
        lines.append("  %-*s: %5d zona(s) con fichero en la pagina"
                     % (w, report.zones.key, report.zones.value))
    for key, reason in report.unmeasured:
        lines.append("  %-*s: no medido — %s" % (w, key, _short(reason)))
    return lines


def confidence_lines(report: ProgressReport) -> list[str]:
    """Confianza y evidencia de cada cifra, para el revisor."""
    out = ["confianza:"]
    for value in report.values:
        out.append("  %-12s %-9s %s" % (value.key, value.confidence, value.evidence))
    if report.zones is not None:
        out.append("  %-12s %-9s %s" % (report.zones.key, report.zones.confidence,
                                        report.zones.evidence))
    for key, reason in report.unmeasured:
        out.append("  %-12s descartado %s" % (key, reason))
    return out
