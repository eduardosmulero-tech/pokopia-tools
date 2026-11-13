"""Nombre de un objeto: del id del inventario al texto de la tabla de nombres.

La cadena esta medida y contrastada en `docs/SPEC-NAMES.md` (§9, §6.3 y §6); aqui no
se añade ninguna regla nueva, solo se recorre:

    id de inventario (13 bits, `save.items.ITEM_ID_MASK`)
      -> fila `id` de `#983`                       (header 64, stride 68, 4.600 filas)
        -> u16 en +34 = `nameIndex`                [verified, SPEC-NAMES §6.3]
          -> id de texto `r = nameIndex + 3`       <- el campo guarda `r - 3`
            -> bloque de 6 slots: `k = 6*(r-4)`…`k+5` en la tabla de nombres
              -> slot `k` = **el nombre**          (singular, SPEC-NAMES §6.1)

**Cual de los seis slots es «el nombre»: el `+0` (`k`), el singular.** Es la decision que
pide la tarjeta y se resuelve asi:

- `+0` es el **singular** y es el unico slot no vacio en las nueve lenguas: en `jp` el
  bloque tiene un solo slot lleno (`0x01`) y en las otras ocho la mascara es `0x2D`, que
  deja llenos `+0`, `+2`, `+3` y `+5` (SPEC-NAMES §6.1, medido). Un lector que quisiera
  «el nombre» pasando por `+2` se quedaria sin nombre en japones.
- `+2` es el **plural**: la forma de varias unidades, no el nombre del objeto.
- `+3` y `+5` son las formas del otro grupo (`<singular'>`, `<plural'>`). En `de` la
  mascara es `0x3F` y `+1`, `+3` y `+4` repiten el singular (SPEC-NAMES §12.2).

Por tanto el nombre impreso es `slots[6*(r-4)]` decodificado en UTF-8, sin normalizar y
sin recortar (el pool no tiene relleno: cada slot acaba en su NUL, SPEC-NAMES §5).

**Frontera de contenido** (`docs/NORMA-CONTENIDO-Y-PUBLICACION.md` §1): este modulo
devuelve el texto para que la CLI lo imprima en tiempo de ejecucion. No lo escribe en
ningun fichero, no lo cachea en disco y no lo registra. Los tests y la documentacion no
llevan nombres del juego: usan marcadores.

**Un id raro no rompe la herramienta.** Si `id` no tiene fila en `#983`, si `nameIndex`
se sale del pool o si el bloque de ese id esta vacio (732 ids no tienen texto, §8), se
devuelve `SIN_NOMBRE`; nunca se lanza una excepcion por el contenido de un registro. Lo
que si falla —con `tables.TableError`— es que el contenedor no cuadre con su geometria:
eso es un dump equivocado, no un inventario raro.
"""

from __future__ import annotations

import struct

from . import paths, tables
from .mod.manifest import ContainerView

#: Tabla de items: la unica con un campo demostrado (`+34 u16 nameIndex`).
ITEM_TABLE = 983

#: Tablas de nombres por idioma (SPEC-NAMES §3.1), en el orden de `tables.NAMES_LANGS`.
TEXT_TABLES: dict[str, int] = {lang: 4645 + i
                               for i, lang in enumerate(tables.NAMES_LANGS)}

#: Idioma por defecto: el del save de Edu y el que mide la spec.
IDIOMA_POR_DEFECTO = "es"

#: Lo que se imprime cuando no hay nombre. **No** es un nombre del juego.
SIN_NOMBRE = "<sin nombre>"

#: Desplazamiento del `nameIndex` dentro de la fila de `#983` (SPEC-NAMES §6.3).
NAME_INDEX_OFFSET = 34


class NameIndex:
    """Indice `id de inventario -> nombre`, construido **una vez** por ejecucion.

    Recibe los dos payloads ya descomprimidos (el llamante lee cada entrada del
    contenedor una sola vez) y trocea el pool de nombres una sola vez con
    `tables.parse_pool`. Cada `nombre()` posterior es un corte de 68 B mas una
    consulta al pool; no vuelve a tocar el contenedor ni el disco.
    """

    __slots__ = ("items_spec", "text_spec", "blob_items", "slots", "_cache")

    def __init__(self, blob_items: bytes, blob_text: bytes, *,
                 item_table: int = ITEM_TABLE,
                 text_table: int = TEXT_TABLES[IDIOMA_POR_DEFECTO],
                 modificado: bool = False):
        items_spec = tables.get(item_table)
        text_spec = tables.get(text_table)
        if items_spec is None or text_spec is None:
            raise tables.TableError(
                "#%d/#%d: sin geometria declarada para resolver nombres"
                % (item_table, text_table))
        # Un dump de otra version falla aqui, y debe: count/version del header no
        # coinciden con la geometria declarada. `modificado=True` es para un
        # contenedor derivado del dump que anadio filas (docs/AÑADIR-FILAS.md):
        # se admite la deriva del `count`, nunca la del `version`, y la
        # geometria (records_end y pool_start) se deriva del count real.
        count_items, _ = tables.check_header(items_spec, blob_items,
                                             modificado=modificado)
        count_text, _ = tables.check_header(text_spec, blob_text,
                                            modificado=modificado)
        items_spec = tables.con_conteo(items_spec, count_items)
        text_spec = tables.con_conteo(text_spec, count_text)
        self.items_spec = items_spec
        self.text_spec = text_spec
        self.blob_items = blob_items
        self.slots = tables.parse_pool(text_spec, blob_text)[0]
        self._cache: dict[int, str | None] = {}

    # -- construccion ------------------------------------------------------
    @classmethod
    def desde_contenedor(cls, container_path: str | None = None, *,
                         language: str = IDIOMA_POR_DEFECTO,
                         modificado: bool = False) -> "NameIndex":
        """Abre el contenedor (`--container` / `PKP_ROMFS`) y lee las dos tablas.

        `ContainerView` cachea los payloads descomprimidos, asi que `#983` y la tabla
        de nombres se descomprimen una vez cada una. `modificado=True` admite un
        contenedor derivado con `count` por encima del declarado.
        """
        if language not in TEXT_TABLES:
            raise tables.TableError(
                "idioma %r sin tabla de nombres (hay: %s)"
                % (language, ", ".join(TEXT_TABLES)))
        container = paths.resolve_container(container_path)
        view = ContainerView(container)
        return cls(view.payload(ITEM_TABLE), view.payload(TEXT_TABLES[language]),
                   item_table=ITEM_TABLE, text_table=TEXT_TABLES[language],
                   modificado=modificado)

    # -- resolucion ------------------------------------------------------
    def text_id(self, item_id: int) -> int | None:
        """`r = nameIndex + 3`, o `None` si el id no tiene fila o se sale del pool."""
        if not 0 <= item_id < self.items_spec.count:
            return None
        fila = tables.read_row(self.items_spec, self.blob_items, item_id)
        name_index = struct.unpack_from("<H", fila, NAME_INDEX_OFFSET)[0]
        r = name_index + 3
        if not tables.TEXT_FIRST_ID <= r <= self.text_spec.count + 3:
            return None
        return r

    def resolver(self, item_id: int) -> str | None:
        """El nombre, o `None` si no se puede resolver (sin excepciones)."""
        if item_id in self._cache:
            return self._cache[item_id]
        r = self.text_id(item_id)
        texto = None
        if r is not None:
            k = (tables.SLOTS_PER_BLOCK * (r - tables.TEXT_FIRST_ID)
                 + tables.SINGULAR_SLOT)
            if 0 <= k < len(self.slots) and self.slots[k]:
                texto = self.slots[k].decode("utf-8", "replace")
        self._cache[item_id] = texto
        return texto

    def nombre(self, item_id: int) -> str:
        """El nombre listo para imprimir: `SIN_NOMBRE` cuando no se resuelve."""
        texto = self.resolver(item_id)
        return SIN_NOMBRE if texto is None else texto
