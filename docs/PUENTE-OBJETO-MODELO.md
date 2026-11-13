# Puente objeto → modelo (registro `kidsobjdb` → `.g1m`)

Medido sobre el dump `655360` (juego 2.0.1a), **solo lectura**, el 11-nov-2026.
Scripts en `informes/t_2dd53849/`, todos con `PKP_ROMFS` apuntando a
`updates/655360/romfs`. Ninguno abre el dump en escritura.

> **v2 (mismo día, segunda vuelta).** La primera versión contaba con el lector
> tolerante *sembrado* (`{5:4}`) y se quedó corta: `paso56`–`paso61` aprenden
> los anchos de `kind` de los propios registros y rehacen los recuentos. Los
> números de abajo son los de ese lector final; donde una cifra cambia respecto
> a la v1 se dice explícitamente.

## La fórmula

```
registro A (type_hash 0x0fe035d1 | 0x7eda1fc0 | 0xc4b9b28d)
   └─ campo 0x0b6e1578 = id de otro registro  ──────────────┐
                                                            ▼
registro B (type_hash 0xd40b3c8f)  «registro-modelo»
   ├─ campo 0x8ab68b3f = name_hash del .g1m   ◄── el modelo
   └─ campo 0x7f0de9a3 = name_hash del .mtl   ◄── su material
                                                            ▼
name_hash → pokopia.fdata (fichero .fdata + entrada) → payload
```

Tercera vía suelta: registro `type_hash 0xaba56f34` (18 en todo el dump) lleva el
`g1m` en el **campo `0xda9051bb`**.

**Ese es el único enlace de A al modelo.** `paso61_crucesA.py` cruza los
**5.107 valores distintos** de *todos* los pares de los **6.036** registros A
contra los `name_hash` de `g1m` (3.204) / `mtl` (1.531) / `texinfo` (4.341) y
contra los `kt_hash` del catálogo (2.043): **0 coincidencias** en los cuatro
conjuntos (esperado al azar 0,004–0,005). La v1 lo había hecho con 2.059
registros A (`paso52_cruces.py` §C) y también dio 0.

Del campo `0x0b6e1578` salen **7.268 apuntadores**: **6.184 (85,1 %) a un
registro B**, 636 (8,8 %) a otro registro A (la cadena se encadena), y **448
(6,2 %) a ids que no existen** como registro en ninguna base (abierto:
`paso60_puentes.py`).

## Las dos cadenas, de punta a punta

| # | Registro A | → ref | Registro B | → `g1m` | Fichero concreto | Bytes | Vértices | Índices | Triángulos |
|---|---|---|---|---|---|---|---|---|---|
| 1 | id `13538356`, type `0x0fe035d1`, `0x2943e4da.fdata[4]@0xc5bc` | `0x0b6e1578` | id `2666648279`, type `0xd40b3c8f` | `0x131f769f` | `0x738d2a35.fdata[107]` | 32.252 | 383 | 1.908 | 636 |
| 2 | id `1843163`, type `0x7eda1fc0`, `0xe634eeb2.fdata[0]@0x794` | `0x0b6e1578` | id `1512077420`, type `0xd40b3c8f` | `0x77007c2a` | `0x99d71093.fdata[6]` | 21.584 | 325 | 1.488 | 496 |

Son **dos objetos de tipo A distinto** (`0x0fe035d1` y `0x7eda1fc0`), que es lo
que pedía el paso 5 del método: la regla se mantiene entre tipos.

Los dos `.g1m` están extraídos en `informes/t_2dd53849/g1m/` y pasan el parser
del repo (`tools/modelos/g1m.py`, el mismo que usa `pkp_modelo.py`), sin
reimplementar nada:

| fichero | bytes | sha256 | GM1G | vb/ib | subm. | `g1m.problemas()` |
|---|---|---|---|---|---|---|
| `0x738d2a35.fdata_107.g1m` | 32.252 | `a9d32d9f70c5ff55…` | `0400` | 1/1 | 1 | `[]` |
| `0x99d71093.fdata_6.g1m` | 21.584 | `6c704030098346bb…` | `2400` | 1/1 | 1 | `[]` |

Degenerados: **0** en ambos. Cabecera `_M1G` en el byte 0 y las cuatro secciones
canónicas `FM1G` (+24), `SM1G`, `MM1G`, `GM1G`. Números en
`informes/t_2dd53849/vertices.json` (`paso49_vertices.py`).

### Verificación (comandos ejecutados, salida literal)

```bash
export PKP_ROMFS=<romfs>
# el name_hash está en ese .fdata con ese tamaño:
python pkp.py fdata list $PKP_ROMFS/motor_asset_re/KIDS_PLATFORM_OUNCE/0x738d2a35.fdata | grep 131f769f
#   0x00307390 g1m              19150      19014        32252 0x131f769f 0x00400000
python pkp.py fdata list $PKP_ROMFS/motor_asset_re/KIDS_PLATFORM_OUNCE/MountPoint_1/0x99d71093.fdata | grep 77007c2a
#   0x00005210 g1m              14113      13977        21584 0x77007c2a 0x00400000
```

La columna `entry` de `fdata list` es el **tamaño** de la entrada
(`pokopia/cli.py:865`, `entry_size`), no su índice: el índice (107 / 6) sale de
`fdata.iter_entries` y lo fija `paso48_cadenas.py`.

> Corrección de la v1 de este documento: la línea que decía
> `pkp fdata list <romfs> --type g1m | grep …` **no existe**. Comprobado:
> `pkp: error: unrecognized arguments: --type g1m`. `fdata list` toma un
> `.fdata` concreto; `--type` es de `fdata extract` (y exige `--out`).

Y el verificador de punta a punta, que **no** confía en `cadenas.json` sino que
rehace el barrido (v2: además aprende los anchos de `kind` antes de barrer):

```bash
python informes/t_2dd53849/paso54_verifica.py
# anchos de kind: {5: 4, 1: 1, 8: 4, 4: 4, 0: 1, 2: 2, 3: 2}
# barrido: 475230 ids de registro
# cadena 1: A id=13538356 type=0x0fe035d1 … campo 0x0b6e1578 -> está
#           B id=2666648279 campo 0x8ab68b3f -> 0x131f769f   indice 0x738d2a35.fdata[107] 32252 B
#           .g1m: 32252 B, sha256 a9d32d9f…, vertices=383 indices=1908 triangulos=636, problemas=ninguno
#           -> CUADRA
# cadena 2: … -> CUADRA
# id del objeto del inventario como id de registro: 63/973/11301/2281/2284 -> no
# controles 64/974/11302/2282/2285 -> no
# TODO CUADRA (0 fallos)   [exit 0]
```

## El lector: qué fallaba y qué se corrigió (paso56–paso60)

`pokopia/objdb.py` (estricto) exige `4 B` por valor y **no parsea 1.508 de las
4.144 bases** `kidsobjdb`; parsea 2.636 y saca **353.905 registros**.
`paso40_tol.py` añade un lector que infiere el ancho por `kind` y, si algo no
cuadra, reanuda en la siguiente firma `IDOK0000`. Pero venía *sembrado* con
`{5:4}` y eso perdía registros:

| medición | estricto | tolerante sembrado `{5:4}` | tolerante con anchos aprendidos |
|---|---|---|---|
| bases leídas / con error | 2.636 / 1.508 | — | — |
| registros | 353.905 | 581.449 | **618.949** |
| ids distintos | — | 466.997 | **475.230** |

- `paso56_lectores.py` + `paso56b_diag.py`: la entrada
  `0x2943e4da.fdata/0xea857d14` (1.752 B) la lee el **estricto** (1 registro,
  `id 3786843783`, `type 0x97af26fd`, 101 pares, 11 valores `== 63`) y el
  tolerante sembrado devuelve **0**: ese registro mezcla los `kind` 4 y 8 y el
  lector solo infiere el ancho cuando falta **uno**.
- `paso57_cobertura.py`: pasando el mapa devuelto de una entrada a la siguiente
  se aprende **`{5:4, 1:1, 8:4, 4:4, 0:1, 2:2, 3:2}`** y con él **0 entradas**
  quedan con registros del estricto y cero del tolerante (antes, al menos esa
  una); 1.497 entradas quedan solo al tolerante; 1.482 bases no dan ni un
  registro con ninguno de los dos (cabeceras vacías o ajenas al formato).
- `paso59_contra.py`: **control duro** — en las 2.636 entradas que los dos
  parsean, estricto y tolerante dan **353.905 = 353.905 registros y 0
  diferencias de `type_hash`**. Ahí no se inventa nada. **Cuidado:** los tipos
  del puente están **todos a 0** en esas entradas: viven en las 1.508 que el
  estricto no parsea, así que para ellos no hay ground truth independiente; lo
  que sí tienen es el cierre aritmético del propio registro y que sus cadenas
  resuelven a ficheros reales (abajo).

> Corrección de medición (v1): `paso17_quien_cita_g1m.py` informó «0 hits:
> nadie cita a g1m». Era **falso**: comparaba `set(dict)` (claves en `str`) con
> enteros. Descartado; el barrido bueno es `paso35_grafo.py` (16,4 GB de
> payloads, 79.710 entradas), que da `kidsobjdb->g1m 3257`, `kidsobjdb->mtl
> 1533`, y `g1t->g1m 110`, `g1m->g1s 164`. Ni el contenedor (`paso11`,
> `paso19`, `paso21`) ni los `oid`/`grp` citan `g1m`.

## Mapa de las bases (`paso50_tipos.py`, `paso58_analisis.py`)

4.144 blobs `kidsobjdb` en **11 ficheros .fdata**. La tabla de abajo es de
`paso50` (lector sembrado); con el lector final los totales son **618.949
registros / 475.230 ids distintos** (`paso58`), y los tipos del puente así:

| type_hash | v1 (sembrado) | v2 (anchos aprendidos) |
|---|---|---|
| `0x0fe035d1` | 824 | **824** |
| `0x7eda1fc0` | 1.232 | **1.232** |
| `0xc4b9b28d` | 3 | **3.980** |
| → registros A (apariciones / ids) | 2.059 / 1.647 | **6.036 / 5.258** |
| `0xd40b3c8f` (B, apariciones / ids) | 3.444 / 3.394 | **3.445 / 3.395** |
| `0xaba56f34` | 18 | **18** |

Los 3.977 registros `0xc4b9b28d` de más son exactamente los que el lector
sembrado se saltaba por tener dos `kind` sin ancho; los 824 y los 1.232 no
cambian, y **todos los 6.036 llevan el campo `0x0b6e1578`** (`paso60`).

| fdata | blobs | registros (v1) | tipos principales |
|---|---|---|---|
| `0x52482d03.fdata` | 36 | 296.017 | `0x18eb1e56` ×258.043, `0xab9c4087` ×13.791 |
| `0x2943e4da.fdata` | 84 | 170.937 | `0x11a85121` ×39.546, `0x34f2ec8b` ×36.102 |
| `0xe634eeb2.fdata` | 3 | 74.078 | `0xff7dbfd4` ×39.928, **`0xd40b3c8f` ×3.311**, **`0x7eda1fc0` ×1.232** |
| `0xacd220a8.fdata` | 713 | 35.800 | `0xf7c0d0f0` ×16.743 |
| `0xed675d0e.fdata` | 21 | 1.691 | `0x79991e79` ×1.452 |
| `0x514c644e.fdata` | 1.939 | 1.278 | `0xd186ceeb` ×638, `0x22a5e641` ×638 |
| `0xed66e8af.fdata` | 21 | 762 | `0xf7c0d0f0` ×513 |
| `0xe80c0628.fdata` | 639 | 426 | `0xd186ceeb` ×213 |
| `0x4b13d561.fdata` | 520 | 348 | `0xd186ceeb` ×172 |
| `0xe1d3773b.fdata` | 165 | 110 | `0xd186ceeb` ×55 |
| `0xaced3bfa.fdata` | 3 | 2 | `0xd186ceeb` ×1 |

Los tipos A viven en `0x2943e4da.fdata` (`0x0fe035d1`, `0xc4b9b28d`) y en
`0xe634eeb2.fdata` (`0x7eda1fc0`); los B sobre todo en `0xe634eeb2.fdata`.
**Ahí está el motivo por el que `pkp objdb` no los ve**: el CLI solo lee una
entrada de `0x52482d03.fdata` (`name_hash 0x718ccb8b`, 294.939 registros
declarados en su cabecera), y ahí no hay ni un registro A. Comprobado:
`pkp fdata list 0x52482d03.fdata` imprime **36** entradas `kidsobjdb` y
`pkp objdb stat` imprime **un solo bloque**.

## Cifras que lo sostienen (lector final)

- `paso60_puentes.py`: **6.036** registros A, todos con campo `0x0b6e1578`;
  4.263 ids objetivo distintos (3.298 B, 519 A, 446 desconocidos) y 7.268
  apuntadores repartidos 6.184 / 636 / 448. **3.445** registros B, **todos**
  con campo `0x8ab68b3f` (3.361 hashes distintos) y con campo `0x7f0de9a3`
  (1.627); **3.190 de esos 3.361 hashes** están en `indice.json`, que tiene
  **3.204** entradas `g1m`.
- `paso61_crucesA.py`: 5.107 valores distintos de A × 4 conjuntos de hashes →
  **0** coincidencias.
- `paso54_verifica.py`: las dos cadenas del informe, rehechas desde el barrido
  con el lector final: **0 fallos** (exit 0).
- `paso50_tipos.py` / `paso41_puente.py`: campo a campo, `0x8ab68b3f` →
  hashes `g1m`, `0x7f0de9a3` → `mtl`, `0xda9051bb` → 18 hashes `g1m`;
  `paso43_quien.py` da quién apunta al registro-modelo (2.464 = 1.232 × 2
  valores: los A de tipo `0x7eda1fc0` apuntan a **dos** modelos);
  `paso48_cadenas.py` resuelve **824 cadenas** con `g1m` en el índice.

## El tramo del objeto: dónde se buscó y qué se midió

El objetivo era llegar desde el objeto que ya se pinta en el juego (el del hueco
0 de la bolsa, `item_id 63` de los `ejemplos/a*`) hasta un registro A. **No se
encontró.** Todo lo que se probó, con su salida:

1. **`pkp objdb id` con los ids del objeto** (63, 973, 11301, 2281, 2284):
   `ERROR: ningun registro con id …` para los cinco. Y `pkp objdb dump --type
   0x0fe035d1` da `ningun registro con type_hash …`: el CLI solo mira una
   entrada de un fichero (ver el mapa de arriba), donde no hay registros A.
2. **`paso54_verifica.py` + `paso58_analisis.py`, lector final sobre las 4.144
   bases**: ninguno de esos cinco ids existe como **id de registro** (controles
   64, 974, 11302, 2282, 2285: tampoco), y **ninguno de los 6.036 registros A
   lleva esos cinco ids —ni los controles— en ninguno de sus campos**
   (`paso58`: `valores de objeto dentro de registros A: (ninguno)`).
3. **`paso15_valores.py`** (lector estricto): los ids del objeto no aparecen
   como **valor** de ninguna pareja en las bases parseables. Ojo: en el lector
   final esos cinco sí son valores frecuentes (45.444 registros los contienen,
   `paso57`) — es decir, **aparecer no es señal**; lo que no aparece es en los
   registros A.
4. **`paso47_ids.py`**: 475.230 ids de registro vs 2.044 nombres (catálogo +
   identificadores `XX00000_…` del contenedor) con `kt_hash` → **1
   coincidencia** (`BP02595_A07_HANADA_TESURI00_00`, tipo `0x18eb1e56`),
   compatible con azar (1 en ~9,5×10⁸ pares).
5. **`paso45_ref.py`**: el campo `0x0b6e1578` **no** contiene hashes de entidad
   del catálogo; solo ids de otros registros.
6. **`paso51_hashes.py`**: tablas del contenedor `#40` piezas, `#41`
   variaciones, `#42` dimensiones, `#44` modelos, `#983` items — **cero**
   `u32` perteneciente a `g1m`/`mtl`/`texinfo`/catálogo en las cinco (279.240
   `u32` barridos). La fila 63 de `#983`, campo a campo, tampoco lleva ningún
   hash.
7. **`paso53_distintos.py`**: colisiones de esas tablas con los ids de
   registro, **por valor distinto**: `#40` 0 (esperado 0,53), `#41` 1
   (`0x27c00000`, 0,33), `#42` 0 (0,02), `#44` 0 (0,25), `#983` 1
   (`0x2e400000`, 0,99) → **2 colisiones frente a 2,12 esperadas**: azar.
8. **`paso52_cruces.py`** (v1) y **`paso61_crucesA.py`** (v2): (A) ids de
   registro × `g1m`/`mtl`/`texinfo`/catálogo → 1/1/0/1, con controles del
   mismo tamaño 0–1: azar. (B) `kt_hash` del **nombre** de cada uno de los
   3.585 items con nombre × ids de registro → **1 hash distinto**
   (`0x278aec64`, dos items que comparten nombre), tipo `0xff7dbfd4` (ni A ni
   B), esperado 0,39: azar. (C) pares de registros A × esos hashes → **0**
   con 2.059 registros A y **0** con 6.036.

> **Lección de método (por qué el control es por valor distinto).** El primer
> control de `paso51` contaba **ocurrencias** y dio 0 frente a 8,5 esperadas
> por tabla. No era un fallo del conjunto control: las tablas están llenas de
> constantes (el `0` ocupa 39.477 de los 78.216 `u32` de `#983`), así que la
> media está dominada por si unos pocos valores muy frecuentes caen o no en el
> control. Diez semillas de control dieron **9 ocurrencias frente a 85
> esperadas** (`paso51c_seeds.py`). Contando **valores distintos**, el esperado
> es `n_distintos × |ids| / 2³²` y ahí sí cuadra (`paso53`).

## Qué NO está resuelto (y dónde se buscó)

1. **El tramo objeto real (el ítem 63 → registro A).** No existe en lo barrido:
   ids del objdb, valores de las parejas (incluidos los 6.036 registros A),
   `kt_hash` de nombres de item y catálogo, y las cinco tablas del contenedor
   (apartados 1–8 de arriba). O el enlace es **por índice y no por hash/id**
   (el `ref_a` de la fila 63 vale 10 y apunta a `#41`, que no lleva ningún
   hash), o vive en `oid`/`grp`, que es la tarjeta hermana.
2. **Los 448 apuntadores de `0x0b6e1578` que apuntan a ids inexistentes**
   (6,2 %): o son ids de registros en bases que ni el lector final abre, o son
   ids de otra tabla. `paso60_puentes.py`.
3. **El nombre del `.g1m`**: el `name_hash` no se puede invertir (las cadenas
   de nombre de los ficheros viven en los bundles de nombres que faltan; ver
   `docs/NOMBRES-DE-FICHERO-EN-RDB.md`). Se nombra por `fichero .fdata +
   entrada + name_hash`, verificable con las líneas de arriba.
4. **Qué dibuja cada `.g1m`**: los dos ficheros son plausibles (malla entera,
   sin problemas del parser), pero **no se ha confirmado en el juego** que
   pinten el objeto 63 — ni siquiera se ha podido decir qué objeto es el de la
   cadena 1. Ninguna tarjeta arranca el juego (D-021).

## Reproducir

```bash
export PKP_ROMFS=<romfs>
python informes/t_2dd53849/paso54_verifica.py     # aprende anchos y verifica las 2 cadenas (exit 0)
python informes/t_2dd53849/paso57_cobertura.py     # cobertura estricto vs tolerante, anchos aprendidos
python informes/t_2dd53849/paso58_analisis.py      # recuento final de tipos A/B y objeto en A
python informes/t_2dd53849/paso59_contra.py        # control duro: 353.905 = 353.905
python informes/t_2dd53849/paso60_puentes.py       # apuntadores A->B, campo g1m del B
python informes/t_2dd53849/paso61_crucesA.py       # A x g1m/mtl/texinfo/catalogo -> 0
python informes/t_2dd53849/paso48_cadenas.py       # 2 cadenas + .g1m extraidos
python informes/t_2dd53849/paso49_vertices.py      # vertices/indices/triangulos
python informes/t_2dd53849/paso50_tipos.py         # mapa de bases (lector sembrado)
python informes/t_2dd53849/paso51_hashes.py        # tablas del contenedor vs hashes
python informes/t_2dd53849/paso53_distintos.py     # colisiones por valor distinto
python informes/t_2dd53849/paso52_cruces.py        # ids x hashes, nombres x ids
python informes/t_2dd53849/paso47_ids.py           # id de registro == kt_hash(nombre)?
python informes/t_2dd53849/paso35_grafo.py         # grafo de referencias (16 GB)
python informes/t_2dd53849/paso41_puente.py        # campo que lleva g1m/mtl
python informes/t_2dd53849/paso43_quien.py         # quien apunta al registro-modelo
```

## Siguiente paso natural

Dos vías, por orden de baratura:

1. **`ref_a` → `#41` → … por índice.** `#41` (4.096 filas × 16 B) no lleva
   ningún hash, así que la unión con los registros A tendría que ser posicional.
   Comprobarlo es un barrido de `#41` contra el orden de los registros A.
2. **`oid`/`grp`** (tarjeta hermana): los `.fdata` traen entradas de tipo `oid`
   y nadie ha mirado si citan ids de registro A.

Refutar con datos sigue siendo válido; esto ya dice dónde está el modelo, con
qué campo se nombra y en qué sitios **no** está el tramo del objeto.
