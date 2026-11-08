#!/usr/bin/env python3
"""Catalogo de entidades del juego: los 2.043 nombres de objeto y su hash KT.

**Que es.** Dentro de un `.fdata` (`motor_asset_re/KIDS_PLATFORM_OUNCE/`) hay un
contenedor propio del motor (`_DOK0000`) con un registro `IDOK` que guarda la
lista de nombres de objeto del juego. Medido sobre el dump 2.0.1a:

    entrada del .fdata    132.348 B descomprimidos, 82 registros `IDOK`
    registro de la tabla  101.880 B
    nombres               2.043, NUL-separados, formato `[A-Z]{2}\\d{5}_[A-Z0-9_]{3,40}`
    reparto por prefijo   BP 1473, PM 399, BI 87, PC 73, AP 11
    hashes                los 2.043 calculados con `kt_hash` estan en el registro

**El hash.** `kt_hash` es el hash de nombres del motor KTGL (Koei Tecmo). Se
verifico por cuatro vias independientes; la firma de este modulo lo deja como
funcion pura porque el resto del kit lo va a necesitar (nombres de objeto,
nombres de fichero, tipos). No se toca.

**Como se localiza la tabla.** No por offset fijo: se recorre el `.fdata`
conocido, se descomprime cada entrada y se busca el registro que contiene el
tramo NUL-separado mas largo de nombres con el formato de arriba. Asi el modulo
sigue funcionando si el build cambia los offsets, y si el build cambia el
contenido lo dice en vez de devolver basura: `build_catalog()` **falla** si el
recuento no es 2.043 o si algun hash calculado no aparece en el registro.

**Lo que este modulo NO hace.** No decide a que objeto del inventario
corresponde cada nombre: ese puente (`catalog` <-> `save`) no esta resuelto y
su alcance medido esta en `docs/CATALOGO-Y-SAVE.md`. Aqui solo hay diccionario.

Solo stdlib y solo lectura.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from typing import Iterator

from . import fdata

#: Recuento medido de nombres en el registro. Es la huella del build: si cambia,
#: el contenido no es el que este modulo entiende y hay que volver a medir.
EXPECTED_NAMES = 2043

#: Reparto medido por prefijo (informativo: no se exige, se publica).
EXPECTED_BY_PREFIX: dict[str, int] = {"BP": 1473, "PM": 399, "BI": 87, "PC": 73, "AP": 11}

#: Un nombre de objeto: dos letras de categoria, cinco digitos y el resto.
NAME_RE = re.compile(rb"[A-Z]{2}\d{5}_[A-Z0-9_]{3,40}")

#: Ejemplo del formato, sintetico: no es un nombre del juego.
NAME_EXAMPLE = "XX00000_A00_PALABRA00_00"

#: Un tramo se considera tabla a partir de dos nombres seguidos: asi un nombre
#: suelto dentro de otro bloque no se confunde con el diccionario.
MIN_RUN = 2

#: Ruta del `.fdata` que lleva el diccionario, relativa a la raiz del romfs.
CATALOG_FDATA = os.path.join("motor_asset_re", "KIDS_PLATFORM_OUNCE", "0x2943e4da.fdata")

#: Firma del contenedor propio (`_DOK0000`) y de sus registros. Los registros
#: llevan dos prefijos con la misma cabecera de 24 B: `IDOK0000` (200.295 en el
#: `.fdata` del catalogo) y `RDOK0000` (18). Se aceptan los dos.
DOK_MAGIC = b"_DOK0000"
DOK_RECORD_MAGICS = (b"IDOK0000", b"RDOK0000")

#: Cabecera de `_DOK0000`: magic + 4 x u32 (offset del primer registro, tamano
#: de la cabecera de registro, numero de registros, 2 campos medidos sin nombre).
DOK_HEADER = struct.Struct("<8s5I")

#: Cabecera de un registro `IDOK`: magic + 4 x u32 (tamano total, 3 campos).
DOK_RECORD = struct.Struct("<8s4I")

#: Los registros se alinean a 4 B (medido: hay tamanos 37 y 381).
DOK_ALIGN = 4


class CatalogError(Exception):
    """El catalogo no esta, no se puede leer o no cuadra con lo medido."""

    exit_code = 1


# --------------------------------------------------------------------------
# El hash del motor
# --------------------------------------------------------------------------

def kt_hash(nombre: str) -> int:
    """Hash KTGL de un nombre (u32). Funcion pura; no lee ni escribe nada.

    Es la version verificada del algoritmo: primer caracter por separado y, en
    el resto, un acumulador que multiplica por 0x1F en cada paso y suma
    `0x1F * k_anterior * byte_firmado`. El byte se interpreta con signo (el
    juego compila el `char` como firmado en x86); con nombres ASCII el signo no
    cambia nada, pero se mantiene para no divergir del motor.
    """
    if not nombre:
        raise CatalogError("kt_hash de una cadena vacia no esta definido")
    datos = nombre.encode("utf-8")
    valor = (datos[0] * 0x1F) & 0xFFFFFFFF
    k = 0x1F
    for byte in datos[1:]:
        anterior = k
        k = (k * 0x1F) & 0xFFFFFFFF
        con_signo = byte - 256 if byte > 127 else byte
        valor = (valor + 0x1F * anterior * con_signo) & 0xFFFFFFFF
    return valor


# --------------------------------------------------------------------------
# Contenedor `_DOK0000`
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DokRecord:
    """Un registro `IDOK` dentro de un `_DOK0000`: donde empieza y que mide."""

    index: int
    offset: int
    size: int
    tag: int
    kind: int
    label: int


def parse_dok(data: bytes) -> tuple[dict, list[DokRecord]]:
    """Cabecera y lista de registros de un contenedor `_DOK0000`.

    La cabecera declarada dice cuantos registros hay; se comprueba que estan
    todos y que cada uno empieza por `IDOK0000`. Cualquier desvio es error: es
    preferible un fallo claro a leer nombres de un sitio que no toca.
    """
    if len(data) < DOK_HEADER.size:
        raise CatalogError(
            "contenedor _DOK0000 truncado: %d B, la cabecera sola mide %d"
            % (len(data), DOK_HEADER.size))
    magic, first, header_size, count, h1, h2 = DOK_HEADER.unpack_from(data, 0)
    if magic != DOK_MAGIC:
        raise CatalogError("no empieza por _DOK0000 (empieza por %r)" % data[:8])
    if first != DOK_HEADER.size:
        raise CatalogError(
            "cabecera _DOK0000 con offset de primer registro %d (esperado %d)"
            % (first, DOK_HEADER.size))
    header = {"first_record": first, "record_header_size": header_size,
              "count": count, "field_20": h1, "field_24": h2}
    registros: list[DokRecord] = []
    pos = first
    for index in range(count):
        if pos + DOK_RECORD.size > len(data):
            raise CatalogError(
                "registro %d de %d: se sale del contenedor (pos 0x%x de %d B)"
                % (index, count, pos, len(data)))
        magic, size, tag, kind, label = DOK_RECORD.unpack_from(data, pos)
        if magic not in DOK_RECORD_MAGICS:
            raise CatalogError(
                "registro %d: en 0x%x se esperaba %s y hay %r"
                % (index, pos, " o ".join(m.decode() for m in DOK_RECORD_MAGICS), magic))
        if size < DOK_RECORD.size or pos + size > len(data):
            raise CatalogError(
                "registro %d: tamano %d no cabe (pos 0x%x, contenedor %d B)"
                % (index, size, pos, len(data)))
        registros.append(DokRecord(index, pos, size, tag, kind, label))
        fin = pos + size
        resto = fin % DOK_ALIGN
        pos = fin if resto == 0 else fin + (DOK_ALIGN - resto)
    return header, registros


def iter_dok(data: bytes) -> Iterator[tuple[DokRecord, bytes]]:
    """Recorre `(registro, bytes del registro)` de un contenedor `_DOK0000`."""
    _header, registros = parse_dok(data)
    for registro in registros:
        yield registro, data[registro.offset:registro.offset + registro.size]


# --------------------------------------------------------------------------
# La tabla de nombres
# --------------------------------------------------------------------------

def name_table(record: bytes) -> tuple[int, list[str]]:
    """Los nombres de objeto de un registro: (offset del primero, nombres).

    Devuelve `(-1, [])` si el registro no tiene ninguno. Se buscan las
    coincidencias de `NAME_RE` en orden, no un tramo NUL-separado perfecto: el
    volcado medido tiene un salto de formato en medio de la tabla (ver
    `docs/CATALOGO-Y-SAVE.md` §2.3), de modo que exigir contiguidad perfecta
    perderia nombres. La tabla se valida despues: recuento y hashes.
    """
    coincidencias = list(NAME_RE.finditer(record))
    if not coincidencias:
        return -1, []
    return coincidencias[0].start(), [m.group().decode("ascii") for m in coincidencias]


def _u32_windows(data: bytes) -> set[int]:
    """Todos los u32 little-endian de `data`, a cualquier alineacion."""
    vistos: set[int] = set()
    for k in range(4):
        fin = len(data) - ((len(data) - k) % 4)
        if fin > k:
            vistos.update(v[0] for v in struct.iter_unpack("<I", data[k:fin]))
    return vistos


@dataclass(frozen=True)
class Catalog:
    """Diccionario medido: nombre de objeto -> hash KT, y la vuelta."""

    names: tuple[str, ...]
    hashes: dict[str, int]
    by_hash: dict[int, str]
    record: int
    table_offset: int
    entry_offset: int
    source: str = ""
    by_prefix: dict[str, int] = field(default_factory=dict)

    # -- consultas ------------------------------------------------------
    def hash_for(self, name: str) -> int:
        """Hash de un nombre del catalogo (falla si no esta)."""
        try:
            return self.hashes[name]
        except KeyError:
            raise CatalogError(
                "nombre fuera del catalogo: %r\n"
                "  %d nombres cargados; prueba `pkp catalog find <texto>`"
                % (name, len(self.names))) from None

    def name_for(self, value: int) -> str:
        """Nombre de un hash del catalogo (falla si no esta)."""
        try:
            return self.by_hash[value & 0xFFFFFFFF]
        except KeyError:
            raise CatalogError(
                "hash fuera del catalogo: 0x%08X\n"
                "  %d hashes cargados; el diccionario no es exhaustivo"
                % (value & 0xFFFFFFFF, len(self.by_hash))) from None

    def names_with_prefix(self, prefix: str | None = None) -> list[str]:
        """Nombres ordenados, opcionalmente filtrados por prefijo de dos letras."""
        if prefix is None:
            return list(self.names)
        clave = prefix.upper()
        return [n for n in self.names if n[:2] == clave]

    def find(self, text: str) -> list[str]:
        """Nombres que contienen `text`, sin distinguir mayusculas."""
        aguja = text.upper()
        return [n for n in self.names if aguja in n.upper()]

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "entry_offset": self.entry_offset,
            "record": self.record,
            "table_offset": self.table_offset,
            "names": len(self.names),
            "by_prefix": dict(self.by_prefix),
        }


def build_catalog(names: list[str], record: bytes, *, record_index: int = -1,
                  table_offset: int = -1, entry_offset: int = -1,
                  source: str = "") -> Catalog:
    """Construye y **verifica** el catalogo a partir de un registro `IDOK`.

    Tres comprobaciones, todas obligatorias (un fallo es error, no aviso):

    1. el recuento es `EXPECTED_NAMES` (2.043);
    2. no hay nombres repetidos (con dos iguales, `name_for` seria ambiguo);
    3. el hash de cada nombre aparece como bytes en el mismo registro — es la
       comprobacion que ata la lista al motor y que ya se hizo a mano.

    Levanta `CatalogError` con el detalle de lo que no cuadra.
    """
    if len(names) != EXPECTED_NAMES:
        raise CatalogError(
            "el catalogo tiene %d nombres y el build medido tiene %d: "
            "no es la tabla que este modulo entiende\n"
            "  registro %d, tabla en +0x%x, %s"
            % (len(names), EXPECTED_NAMES, record_index, max(table_offset, 0),
               source or "(sin origen)"))
    if len(set(names)) != len(names):
        repetidos = sorted({n for n in names if names.count(n) > 1})[:5]
        raise CatalogError(
            "el catalogo tiene nombres repetidos (%s%s): el diccionario no seria "
            "invertible" % (", ".join(repetidos), "..." if len(repetidos) == 5 else ""))
    hashes = {nombre: kt_hash(nombre) for nombre in names}
    if len(set(hashes.values())) != len(hashes):
        raise CatalogError("dos nombres del catalogo comparten hash: no se puede invertir")

    vistos = _u32_windows(record)
    ausentes = [n for n, h in hashes.items() if h not in vistos]
    if ausentes:
        raise CatalogError(
            "%d de %d hashes calculados no aparecen en el registro "
            "(p. ej. %s = 0x%08X): la lista de nombres no se corresponde con "
            "las tablas del motor" % (len(ausentes), len(hashes), ausentes[0],
                                      hashes[ausentes[0]]))

    reparto: dict[str, int] = {}
    for nombre in names:
        reparto[nombre[:2]] = reparto.get(nombre[:2], 0) + 1
    return Catalog(names=tuple(names), hashes=hashes,
                   by_hash={h: n for n, h in hashes.items()},
                   record=record_index, table_offset=table_offset,
                   entry_offset=entry_offset, source=source, by_prefix=reparto)


def _candidates(ruta: str) -> list[tuple[int, int, int, bytes, list[str]]]:
    """Recorre el `.fdata` y devuelve los tramos de nombres que encuentra.

    Cada candidato es `(offset_entrada, indice_registro, offset_tabla, registro,
    nombres)`. El filtro barato (`NAME_NUL_RE.search`) se hace en C, de modo que
    solo los registros que llevan nombres pagan el recorrido de tokens.
    """
    salida = []
    with open(ruta, "rb", buffering=0) as fh:
        for entry in fdata.iter_entries(ruta):
            datos = fdata.read_entry(fh, entry)
            if not datos.startswith(DOK_MAGIC):
                continue
            _header, registros = parse_dok(datos)
            for registro in registros:
                trozo = datos[registro.offset:registro.offset + registro.size]
                if NAME_RE.search(trozo) is None:
                    continue
                offset, nombres = name_table(trozo)
                if len(nombres) >= MIN_RUN:
                    salida.append((entry.offset, registro.index, offset, trozo, nombres))
    return salida


def read_catalog(fdata_path: str) -> Catalog:
    """Lee y verifica el catalogo de un `.fdata` concreto."""
    candidatos = _candidates(fdata_path)
    if not candidatos:
        raise CatalogError(
            "no hay ningun tramo de nombres de objeto en %s\n"
            "  se esperaban al menos %d seguidos con formato [A-Z]{2}\\d{5}_[A-Z0-9_]+"
            % (fdata_path, MIN_RUN))
    candidatos.sort(key=lambda c: len(c[4]), reverse=True)
    mejor = candidatos[0]
    empatados = [c for c in candidatos if len(c[4]) == len(mejor[4])]
    if len(empatados) > 1:
        raise CatalogError(
            "ambiguo: %d tramos con %d nombres en %s (entradas 0x%x y 0x%x)\n"
            "  sin un criterio de desempate medido no se elige ninguno"
            % (len(empatados), len(mejor[4]), os.path.basename(fdata_path),
               empatados[0][0], empatados[1][0]))
    entry_offset, record_index, table_offset, registro, nombres = mejor
    return build_catalog(nombres, registro, record_index=record_index,
                         table_offset=table_offset, entry_offset=entry_offset,
                         source=fdata_path)


_CACHE: dict[str, Catalog] = {}


def catalog_path(romfs: str | None = None) -> str:
    """Ruta del `.fdata` del diccionario dentro del romfs (existe o no)."""
    from . import paths  # local: `paths` importa el entorno, no el formato

    return os.path.join(os.path.abspath(romfs or paths.configured_romfs()), CATALOG_FDATA)


def load(romfs: str | None = None) -> Catalog:
    """Catalogo completo (con procedencia) del romfs indicado. Se cachea."""
    ruta = catalog_path(romfs)
    cacheado = _CACHE.get(ruta)
    if cacheado is not None:
        return cacheado
    if not os.path.isfile(ruta):
        raise CatalogError(
            "no encuentro el .fdata del catalogo: %s\n"
            "  el kit no incluye el romfs: apunta a la carpeta del juego con\n"
            "  PKP_ROMFS=<carpeta> (o pasa --container <carpeta>)"
            % ruta)
    catalogo = read_catalog(ruta)
    _CACHE[ruta] = catalogo
    return catalogo


def clear_cache() -> None:
    """Olvida los catalogos cargados (lo usan los tests)."""
    _CACHE.clear()


def load_catalog(romfs: str | None = None) -> dict[str, int]:
    """`nombre -> hash` del diccionario, verificado (contrato de la tarjeta).

    Devuelve un `dict` normal; para la vuelta (`hash -> nombre`) y la
    procedencia, `load()` devuelve el objeto `Catalog`.
    """
    return dict(load(romfs).hashes)


def hash_for(name: str) -> int:
    """Hash de un nombre. No necesita el romfs: el algoritmo es puro."""
    return kt_hash(name)


def name_for(value: int) -> str:
    """Nombre del hash, buscando en el catalogo del romfs configurado."""
    return load().name_for(value)


__all__ = [
    "CATALOG_FDATA",
    "DOK_MAGIC",
    "DOK_RECORD_MAGIC",
    "EXPECTED_BY_PREFIX",
    "EXPECTED_NAMES",
    "MIN_RUN",
    "NAME_RE",
    "Catalog",
    "CatalogError",
    "DokRecord",
    "build_catalog",
    "catalog_path",
    "clear_cache",
    "hash_for",
    "iter_dok",
    "kt_hash",
    "load",
    "load_catalog",
    "name_for",
    "name_table",
    "parse_dok",
    "read_catalog",
]
