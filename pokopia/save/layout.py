"""Geometria del save por version.

**Regla de esta capa:** todo lo que depende de la version del save vive aqui. Un layout
es un dato, no codigo: `items.py` y `progress.py` no saben offsets, solo piden regiones y
campos al layout. Añadir una version nueva de save = añadir una entrada a `LAYOUTS` con
sus regiones y sus campos de progreso; no se toca ninguna otra pieza.

Vocabulario (nada de contenido del juego):

* **region**  tramo con registros de tamano fijo dentro del payload descomprimido.
* **progress** magnitud que se puede contar en una region (huecos ocupados, ids distintos,
  bits puestos). El evaluador que la cuenta vive en `progress.py` y se elige por `kind`.

Cada region y cada campo llevan `confidence`:

  measured    medido y reproducible con las herramientas de `tools/` o los tests
  inferred    geometria medida, semantica sin demostrar (se dice cual falta)
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import SaveVersionError

#: Marca de los ficheros CMNDAT.BIN.
SAVE_MAGIC = 0x31227687

#: Cabecera comun a todas las versiones conocidas.
HEADER_SIZE = 0x130

#: Version de save del juego 2.0.1 (medida en el save real, 2026-11-04).
VERSION_2_0_1 = 0x0200017D


@dataclass(frozen=True)
class Region:
    """Tramo de registros de tamano fijo dentro del payload descomprimido."""

    name: str
    offset: int
    count: int
    stride: int
    confidence: str = "measured"
    evidence: str = ""
    #: Bytes del registro que forman el identificador (para decidir si esta ocupado).
    id_offset: int = 0
    id_size: int = 0
    #: Papel de la region, independiente de como se llame en cada version (hoy solo
    #: `inventory`). Quien lee pide por papel, no por nombre: una version futura puede
    #: renombrar la region sin tocar `items.py`.
    role: str = ""

    @property
    def size(self) -> int:
        return self.count * self.stride

    @property
    def end(self) -> int:
        return self.offset + self.size

    def record(self, index: int) -> tuple[int, int]:
        """(inicio, fin) absolutos del registro `index`."""
        if not 0 <= index < self.count:
            raise IndexError("registro %d fuera de rango (0..%d) de la region %s"
                             % (index, self.count - 1, self.name))
        start = self.offset + index * self.stride
        return start, start + self.stride


@dataclass(frozen=True)
class ProgressSpec:
    """Magnitud contable dentro de una region.

    `kind` elige el evaluador de `progress.py`:

      occupied       registros con algun byte no nulo en [arg, arg2] (0,0 = todo el registro)
      distinct_ids   valores distintos de `u32 & arg` en el offset `arg2` del registro
      bit_set        registros cuyo byte `arg2` tiene puesto el bit `arg`
    """

    key: str
    region: str
    kind: str
    arg: int = 0
    arg2: int = 0
    total: int | None = None
    confidence: str = "measured"
    evidence: str = ""


@dataclass(frozen=True)
class Discarded:
    """Candidato de progreso que NO se declara: se guarda el motivo."""

    key: str
    reason: str


@dataclass(frozen=True)
class Layout:
    """Todo lo que depende de la version del save."""

    version: int
    game: str
    payload_size: int
    regions: tuple[Region, ...]
    progress: tuple[ProgressSpec, ...] = ()
    discarded: tuple[Discarded, ...] = ()
    header_size: int = HEADER_SIZE
    note: str = ""

    def region(self, name: str) -> Region:
        for reg in self.regions:
            if reg.name == name:
                return reg
        raise KeyError("la version %#010x no declara la region %r (tiene: %s)"
                       % (self.version, name, ", ".join(r.name for r in self.regions)))

    def region_by_role(self, role: str) -> Region:
        """Region por papel (no por nombre): lo que usan `items.py` y `progress.py`."""
        for reg in self.regions:
            if reg.role == role:
                return reg
        raise KeyError("la version %#010x no declara ninguna region con papel %r "
                       "(tiene: %s)"
                       % (self.version, role,
                          ", ".join("%s%s" % (r.name, ("/" + r.role) if r.role else "")
                                    for r in self.regions)))

    def region_opt(self, name: str) -> Region | None:
        for reg in self.regions:
            if reg.name == name:
                return reg
        return None

    def specs(self, region: str | None = None) -> tuple[ProgressSpec, ...]:
        if region is None:
            return self.progress
        return tuple(s for s in self.progress if s.region == region)


# ---------------------------------------------------------------------------
# Regiones medidas en el save 2.0.1
# ---------------------------------------------------------------------------
_VILLAGERS = Region(
    "villagers", 0x000000, 1050, 374, confidence="measured",
    evidence="el periodo 374 B se repite con 0,986 de coincidencia byte a byte en el "
             "tramo 0..0x5FD3C; el identificador ocupa los bytes +1..+16 del registro "
             "(973 registros a cero, 77 con identificador en la instantanea 'live')",
    id_offset=1, id_size=16)

_HOMES = Region(
    "homes", 0x079824, 1050, 21, confidence="measured",
    evidence="1050 registros de 21 B justo despues del bloque de aldeanos; en las tres "
             "instantaneas de G00 da 76/78/79 frente a 74/76/77 aldeanos con "
             "identificador, diferencia constante 2; en B00 da 27 frente a 26 (diferencia "
             "1). Dos tablas independientes midiendo la misma magnitud, con residuo "
             "constante por pagina",
    id_offset=0, id_size=21)

_PLAYER_NAMES = Region(
    "player_names", 0x46E0E5, 9, 25, confidence="inferred",
    evidence="9 ranuras de 25 B; la spec externa de referencia (PokoHex, GPL-3.0) la "
             "documenta como nombre del jugador y la region se confirma por geometria "
             "(9 x 25 B consecutivos). El modulo NO la lee: es contenido")

_INVENTORY = Region(
    "inventory", 0x46ECEA, 130, 5, confidence="measured",
    evidence="130 registros de 5 B; id = u32 & 0x1FFF (0 = vacio) y +4 = cantidad u8. "
             "Medido en t_e4f8d673 sobre las dos paginas del save real",
    id_offset=0, id_size=4, role="inventory")

_CATALOGUE = Region(
    "catalogue", 0x402ED9, 4600, 1, confidence="measured",
    evidence="array de 4600 B (un byte por fila de #983) localizado por busqueda "
             "exhaustiva con una condicion que no se cumple por azar: los 74 ids "
             "distintos de la bolsa (G00+B00) caen en bytes no nulos, y solo hay un "
             "offset en los 4,6 MB de payload que lo cumple. El bit 0 esta puesto en 289 "
             "entradas y en el 100%% de los ids de la bolsa; el valor 0 significa sin "
             "entrada. La semantica exacta (que significa cada bit) NO esta demostrada",
    id_offset=0, id_size=1)

LAYOUT_2_0_1 = Layout(
    version=VERSION_2_0_1,
    game="2.0.1",
    payload_size=4656365,
    header_size=HEADER_SIZE,
    regions=(_VILLAGERS, _HOMES, _PLAYER_NAMES, _INVENTORY, _CATALOGUE),
    progress=(
        ProgressSpec(
            "bolsa", "inventory", "occupied", arg=0, arg2=3, total=130,
            confidence="measured",
            evidence="registros con id != 0 (id = u32 & 0x1FFF)"),
        ProgressSpec(
            "bolsa_ids", "inventory", "distinct_ids", arg=0x1FFF, arg2=0,
            confidence="measured",
            evidence="ids distintos del mismo campo, mascara 0x1FFF"),
        ProgressSpec(
            "aldeanos", "villagers", "occupied", arg=1, arg2=16, total=1050,
            confidence="inferred",
            evidence="registros con identificador no nulo en +1..+16"),
        ProgressSpec(
            "casas", "homes", "occupied", arg=0, arg2=20, total=1050,
            confidence="inferred",
            evidence="registros con algun byte no nulo (control cruzado de 'aldeanos')"),
        ProgressSpec(
            "catalogo", "catalogue", "bit_set", arg=0, arg2=0, total=4600,
            confidence="inferred",
            evidence="entradas con el bit 0 puesto; superconjunto de los ids de la bolsa "
                     "y constante entre instantaneas mientras la bolsa cambia"),
    ),
    discarded=(
        Discarded(
            "zona",
            "nivel ambiental POR ZONA: no se localiza ni en CMNDAT ni en la cabecera "
            "de los STGDATnn.BIN. Lo que si se mide es el numero de zonas con fichero "
            "propio (magnitud 'zonas', de zones.py). Para el nivel hace falta la "
            "observacion que lo cierra: la MISMA zona en dos niveles distintos, con el "
            "nivel leido en el juego"),
        Discarded(
            "peticiones",
            "contadores de peticiones (hechas / disponibles): no se identifica ningun "
            "par de contadores. Prueba aplicada: las cuatro observaciones B00 < A <= B "
            "<= C (B00 va muy por detras: 26 aldeanos, catalogo 92) con anchos u8/u16/"
            "u32 alineados; los supervivientes son marcas de fecha (u16 2026 seguido de "
            "mes/dia), no contadores. Falta la observacion que lo cerraria: una lista de "
            "peticiones vista en el juego junto a su cifra en el save"),
        Discarded(
            "coleccionable",
            "contador de coleccionables: no aparece array ni bitmap de otro espacio de "
            "ids. Se probaron bitmaps de 4600 y 8192 bits, arrays de 4600 u8/u16/u32, "
            "ventanas de 1024/2048/3001/4600 B con banderas dispersas y tablas "
            "autoindexadas (registro i empieza por i) en todo el payload: el unico array "
            "por id es el de 'catalogo'"),
    ),
    note="offsets medidos sobre G00 y B00 con md5 998a8c85... / efbb5b24... (instantanea "
         "congelada) y contrastados con el save vivo; ver docs/SPEC-SAVE.md",
)

#: Version -> layout. Añadir una version es añadir una entrada aqui.
LAYOUTS: dict[int, Layout] = {
    LAYOUT_2_0_1.version: LAYOUT_2_0_1,
}


def get(version: int) -> Layout:
    """Layout de una version de save. Unica puerta que usan los demas modulos."""
    try:
        return LAYOUTS[version]
    except KeyError:
        raise SaveVersionError(version)


def known() -> tuple[Layout, ...]:
    return tuple(LAYOUTS[v] for v in sorted(LAYOUTS))
