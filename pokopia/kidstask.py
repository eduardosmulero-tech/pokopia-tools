# -*- coding: utf-8 -*-
"""`kidstask` (`_TGK0000`): el grafo de tareas por frame del motor KTGL.

Medido en el build 655360 con las sondas de `informes/t_df5ad471/` y
documentado en `docs/KIDSTASK.md`: aqui solo esta el lector, sin rutas de
maquina y sin escribir nada. El dump se abre en `rb`.

Layout medido (resto = 0 en los 33 registros; `#01` es el unico con
`tamano` no multiplo de 4, y el siguiente registro arranca en `align4`):

    cabecera 32 B
        +0x00  8  b"_TGK0000"
        +0x08  u32  cabecera_tamano      = 32 (offset del primer registro)
        +0x0c  u32  cabecera_de_registro = 24 (firma + 4 u32)
        +0x10  u32  recuento             = 33
        +0x14  u32  campo_0x14           = 0x22704ebb (ver docs/KIDSTASK.md)
        +0x18  u32  campo_0x18           = 0
        +0x1c  u32  campo_0x1c           = tamano declarado (= len(datos))

    registro `INGK0000`
        +0x00  8  b"INGK0000"
        +0x08  u32  tamano  (incluida la firma; NO hace falta %4 == 0)
        +0x0c  u32  id
        +0x10  u32  tipo_hash  -> `TypeInfo::TaskNode::*` en kidstypeinfodb.yml
        +0x14  u32  reserva    (0 en los 33)
        +0x18  payload de `tamano - 24` bytes:
                 u32 N                   recuento de propiedades
                 u32 n + n x u32         enlaces: indices de otros registros
                 N x [u32 tipo][u32 len][u32 hash_prop]
                 valores de los descriptores, en orden, cada uno
                 `len x unidad(tipo)` bytes

    `unidad(tipo)`: solo aparecen dos valores en el fichero y ambos cascan
    con el `Type` de la propiedad en `kidstypeinfodb.yml`:

        tipo 1 -> 1 byte   (la propiedad `Flag` es `Type: Byte`)
        tipo 5 -> 4 bytes  (el resto son `Type: UInt32`)

    El siguiente registro empieza en `align4(offset + tamano)`.

Solo stdlib. Reutiliza `pokopia.fdata` del kit para localizar la entrada.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field

from . import fdata

FILE_MAGIC = b"_TGK0000"
RECORD_MAGIC = b"INGK0000"
HEADER_SIZE = 32
RECORD_HEADER_SIZE = 24
KIDSTASK_KTID = fdata.parse_type("kidstask")

#: bytes por unidad del campo `tipo` de un descriptor. Los dos valores que
#: existen en el fichero medido; un tercero es error, no se inventa.
UNIDAD = {1: 1, 5: 4}

#: donde suele estar el YAML de nombres tras el Paso 0 (build/ es ignorado
#: por git a proposito; se clona con el comando de docs/KIDSTASK.md).
YML_DEFECTO = "build/refs/fdata_dump/kidstypeinfodb.yml"


class KidstaskError(Exception):
    """Error de lectura de un `kidstask`."""


class KidstaskFormatError(KidstaskError):
    """El bytes no cuadra con el layout medido: falla antes que devolver a medias."""


@dataclass(frozen=True)
class Propiedad:
    """Un descriptor del payload: `tipo`, `len` y hash, mas sus valores."""

    tipo: int
    tamano: int
    hash: int
    valores: tuple[int, ...]

    @property
    def bytes_totales(self) -> int:
        return self.tamano * UNIDAD[self.tipo]


@dataclass(frozen=True)
class Nodo:
    """Un registro `INGK0000` con su payload ya parseado."""

    indice: int
    offset: int
    tamano: int
    id: int
    tipo_hash: int
    reserva: int
    enlaces: tuple[int, ...]
    propiedades: tuple[Propiedad, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Kidstask:
    """El fichero entero: cabecera, nodos y el recorrido que los valida."""

    cabecera: dict
    nodos: tuple[Nodo, ...]
    bytes_totales: int
    fin_recorrido: int
    origen: str | None = None

    @property
    def recuento(self) -> int:
        return self.cabecera["recuento"]

    @property
    def cubre_el_fichero(self) -> bool:
        return self.fin_recorrido == self.bytes_totales

    def aristas(self) -> list[tuple[int, int]]:
        """Todas las aristas `i -> j` de la lista de enlaces, en orden."""
        return [(n.indice, j) for n in self.nodos for j in n.enlaces]

    def nombre_de_tipo(self, tipo_hash: int, tipos: dict[int, str],
                       props: dict[int, str] | None = None) -> str | None:
        """Nombre de un hash de tipo: primero `FullName`, luego `LocalName`."""
        if tipo_hash in tipos:
            return tipos[tipo_hash]
        if props and tipo_hash in props:
            return props[tipo_hash]
        return None

    def as_dict(self, tipos: dict[int, str] | None = None,
                props: dict[int, str] | None = None) -> dict:
        """El fichero como dict para `--json`.

        Con `tipos`/`props` (el YAML del Paso 0) cada nodo lleva `tipo_nombre`
        y cada propiedad su `nombre`; sin el YAML van en `None`, que es lo que
        hay cuando solo se tienen los hashes.
        """
        return {
            "origen": self.origen,
            "cabecera": {k: (v if isinstance(v, int) and k in
                             ("cabecera_tamano", "cabecera_de_registro",
                              "recuento", "campo_0x18")
                             else ("0x%08x" % v if isinstance(v, int) else v))
                         for k, v in self.cabecera.items()},
            "bytes_totales": self.bytes_totales,
            "fin_recorrido": self.fin_recorrido,
            "cubre_el_fichero": self.cubre_el_fichero,
            "nodos": [
                {
                    "indice": n.indice,
                    "offset": "0x%x" % n.offset,
                    "tamano": n.tamano,
                    "id": "0x%08x" % n.id,
                    "tipo_hash": "0x%08x" % n.tipo_hash,
                    "tipo_nombre": self.nombre_de_tipo(n.tipo_hash, tipos or {},
                                                       props),
                    "reserva": "0x%08x" % n.reserva,
                    "enlaces": list(n.enlaces),
                    "propiedades": [
                        {
                            "tipo": p.tipo,
                            "tamano": p.tamano,
                            "hash": "0x%08x" % p.hash,
                            "nombre": (props or {}).get(p.hash),
                            "valores": ["0x%08x" % v if UNIDAD[p.tipo] == 4 else v
                                        for v in p.valores],
                        }
                        for p in n.propiedades
                    ],
                }
                for n in self.nodos
            ],
            "aristas": ["%02d->%02d" % (i, j) for i, j in self.aristas()],
        }


def _error(pos: int, mensaje: str) -> KidstaskFormatError:
    return KidstaskFormatError("en 0x%x: %s" % (pos, mensaje))


def parse(datos: bytes, origen: str | None = None) -> Kidstask:
    """Parsea un `kidstask` entero; falla en cuanto un byte no cuadra.

    Valida firma, cadena de registros `INGK0000`, que el recuento de la
    cabecera casa con los registros hallados, que el recorrido cubre el
    fichero byte a byte, que cada payload se agota exacto (resto = 0), que
    los `tipo` de los descriptores son de los conocidos y que cada enlace
    apunta a un indice existente. Nunca devuelve un fichero a medias.
    """
    if len(datos) < HEADER_SIZE:
        raise KidstaskFormatError(
            "corto: %d B, la cabecera sola mide %d" % (len(datos), HEADER_SIZE))
    if datos[:8] != FILE_MAGIC:
        raise _error(0, "firma %r, se esperaba %r"
                     % (datos[:8], FILE_MAGIC))

    cabecera_tamano, cabecera_de_registro, recuento = struct.unpack_from("<III", datos, 8)
    campo_0x14, campo_0x18, campo_0x1c = struct.unpack_from("<III", datos, 20)
    cabecera = {
        "firma": FILE_MAGIC.decode("ascii"),
        "cabecera_tamano": cabecera_tamano,
        "cabecera_de_registro": cabecera_de_registro,
        "recuento": recuento,
        "campo_0x14": campo_0x14,
        "campo_0x18": campo_0x18,
        "campo_0x1c": campo_0x1c,
    }
    if cabecera_de_registro != RECORD_HEADER_SIZE:
        raise _error(12, "cabecera_de_registro = %d, medido %d"
                     % (cabecera_de_registro, RECORD_HEADER_SIZE))
    if cabecera_tamano < HEADER_SIZE or cabecera_tamano % 4:
        raise _error(8, "cabecera_tamano = %d no arranca registros alineados"
                     % cabecera_tamano)

    nodos: list[Nodo] = []
    pos = cabecera_tamano
    while pos + 8 <= len(datos) and datos[pos:pos + 8] == RECORD_MAGIC:
        tamano, ident, tipo_hash, reserva = struct.unpack_from("<IIII", datos, pos + 8)
        if tamano < RECORD_HEADER_SIZE:
            raise _error(pos + 8, "tamano %d < cabecera de registro (%d)"
                         % (tamano, RECORD_HEADER_SIZE))
        if pos + tamano > len(datos):
            raise _error(pos + 8, "tamano %d se pasa del fichero (%d B)"
                         % (tamano, len(datos)))
        nodo = _parse_nodo(datos, pos, tamano, ident, tipo_hash, reserva,
                           len(nodos), recuento)
        nodos.append(nodo)
        siguiente = pos + tamano
        if siguiente % 4:
            siguiente += 4 - siguiente % 4
        if siguiente <= pos:
            raise _error(pos, "el registro no avanza")
        pos = siguiente

    if len(nodos) != recuento:
        raise _error(pos, "recuento de cabecera %d, registros hallados %d"
                     % (recuento, len(nodos)))
    if pos != len(datos):
        raise _error(pos, "el recorrido no cubre el fichero: quedan %d B (%s)"
                     % (len(datos) - pos, datos[pos:pos + 16].hex()))

    return Kidstask(cabecera=cabecera, nodos=tuple(nodos),
                    bytes_totales=len(datos), fin_recorrido=pos, origen=origen)


def _parse_nodo(datos: bytes, pos: int, tamano: int, ident: int, tipo_hash: int,
                reserva: int, indice: int, recuento: int) -> Nodo:
    """El payload de un registro: N, enlaces, descriptores y valores."""
    fin = pos + tamano
    pl = datos[pos + RECORD_HEADER_SIZE:fin]
    if len(pl) < 8:
        raise _error(pos, "payload de %d B: caben N y n?" % len(pl))

    n_props, n_enlaces = struct.unpack_from("<II", pl, 0)
    off = 8
    if off + 4 * n_enlaces > len(pl):
        raise _error(pos, "lista de %d enlaces no cabe en %d B"
                     % (n_enlaces, len(pl)))
    enlaces = tuple(struct.unpack_from("<%dI" % n_enlaces, pl, off)) if n_enlaces else ()
    off += 4 * n_enlaces

    descriptores = []
    for _ in range(n_props):
        if off + 12 > len(pl):
            raise _error(pos, "N=%d: faltan descriptores en %d B"
                         % (n_props, len(pl)))
        descriptores.append(struct.unpack_from("<III", pl, off))
        off += 12

    propiedades = []
    for tipo, ln, hash_prop in descriptores:
        if tipo not in UNIDAD:
            raise _error(pos, "descriptor tipo=%d desconocido (conocidos: %s)"
                         % (tipo, sorted(UNIDAD)))
        nbytes = ln * UNIDAD[tipo]
        if off + nbytes > len(pl):
            raise _error(pos, "descriptor tipo=%d len=%d: faltan %d B en el payload"
                         % (tipo, ln, off + nbytes - len(pl)))
        if UNIDAD[tipo] == 4:
            valores = tuple(struct.unpack_from("<%dI" % ln, pl, off)) if ln else ()
        else:
            valores = tuple(pl[off:off + nbytes])
        off += nbytes
        propiedades.append(Propiedad(tipo=tipo, tamano=ln, hash=hash_prop,
                                     valores=valores))

    if off != len(pl):
        raise _error(pos, "el payload no se agota: sobran %d B (%s)"
                     % (len(pl) - off, pl[off:off + 16].hex()))

    for j in enlaces:
        if j >= recuento:
            raise _error(pos, "enlace %d fuera del rango (recuento %d)"
                         % (j, recuento))

    return Nodo(indice=indice, offset=pos, tamano=tamano, id=ident,
                tipo_hash=tipo_hash, reserva=reserva, enlaces=enlaces,
                propiedades=tuple(propiedades))


def buscar_entrada(romfs: str) -> tuple[str, fdata.Entry]:
    """La unica entrada `kidstask` bajo `romfs`: su `.fdata` y su entrada.

    Si hay mas de una se niega: el dump 655360 tiene una y las medidas de
    este modulo son de esa.
    """
    hallada = None
    for ruta in fdata.find_fdata(romfs):
        for entry in fdata.iter_entries(ruta):
            if entry.type_ktid == KIDSTASK_KTID:
                if hallada is not None:
                    raise KidstaskError(
                        "hay mas de una entrada kidstask bajo %s; este lector "
                        "medido exige una" % romfs)
                hallada = (ruta, entry)
    if hallada is None:
        raise KidstaskError(
            "no hay entrada kidstask (tipo 0x%08x) bajo %s" % (KIDSTASK_KTID, romfs))
    return hallada


def leer_de_romfs(romfs: str) -> tuple[bytes, str]:
    """Los bytes descomprimidos del `kidstask` del romfs y de donde salen."""
    ruta, entry = buscar_entrada(romfs)
    return fdata.read_entry_from(ruta, entry), ruta


def leer_fichero(ruta: str) -> bytes:
    """Un `.kidstask` ya extraido (p. ej. con `pkp fdata extract`)."""
    if not os.path.isfile(ruta):
        raise KidstaskError("no existe el fichero: %s" % ruta)
    with open(ruta, "rb") as fh:
        return fh.read()


def cargar_nombres(ruta_yml: str) -> tuple[dict[int, str], dict[int, str]]:
    """Hashes a nombres desde `kidstypeinfodb.yml` (fdata_dump, GPL-3.0).

    Devuelve `(tipos, propiedades)`: `FullName -> hash` y `LocalName -> hash`,
    leidos con el mismo par `Name/Hash` del YAML que ya valido la sonda 6.
    """
    if not os.path.isfile(ruta_yml):
        raise KidstaskError("no existe el YAML de tipos: %s" % ruta_yml)
    with open(ruta_yml, encoding="utf-8", errors="replace") as fh:
        texto = fh.read()
    tipos = {int(m.group(2), 16): m.group(1)
             for m in re.finditer(r"FullName:\s*(\S+)\s*\n\s*Hash:\s*0x([0-9A-Fa-f]+)",
                                  texto)}
    props: dict[int, str] = {}
    for m in re.finditer(r"LocalName:\s*(\S+)\s*\n\s*Hash:\s*0x([0-9A-Fa-f]+)", texto):
        props.setdefault(int(m.group(2), 16), m.group(1))
    if not tipos:
        raise KidstaskFormatError(
            "el YAML no tiene ningun par FullName/Hash: %s" % ruta_yml)
    return tipos, props


__all__ = [
    "FILE_MAGIC",
    "HEADER_SIZE",
    "KIDSTASK_KTID",
    "RECORD_HEADER_SIZE",
    "RECORD_MAGIC",
    "UNIDAD",
    "YML_DEFECTO",
    "Kidstask",
    "KidstaskError",
    "KidstaskFormatError",
    "Nodo",
    "Propiedad",
    "buscar_entrada",
    "cargar_nombres",
    "leer_de_romfs",
    "leer_fichero",
    "parse",
]
