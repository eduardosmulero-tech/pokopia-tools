# GRP y OID: tabla de piezas y tabla de enlace de huesos

Los dos tipos más pequeños del dump, abiertos. Son **323 `.grp` (35.296 B) y
581 `.oid` (499.244 B)**, ambos dentro de `motor_asset_re`, y ninguno de los dos
lleva posiciones: el `.grp` es la **lista de piezas de un modelo** y el `.oid`
es la **tabla que enlaza cada id global de hueso con el hash de su nombre**.

Todo lo que sigue está medido sobre el dump del update 655360 (juego 2.0.1a),
solo lectura. Cada campo lleva su confianza: `medido`, `inferido` o `supuesto`.

---

## 1. `.oid` — `OIDBindTableBinaryFile`

**Tipo `type_ktid = 0x1AB40AE8`**, 581 entradas, 499.244 B. (Existe un segundo
tipo con el mismo nombre de extensión, `0xDBCB74A9` «OIDFile», que **no aparece
en este dump**: 0 entradas.)

### 1.1 Cabecera y stride

Cabecera de **16 B** y luego entradas de **12 B**. **No hay campo de versión**:
el primer campo es el índice máximo, no un magic ni un `u16` de versión.
La cabecera se lee como **4 × `u32`**, el mismo desglose que el decodificador
de la comunidad que citamos como fuente de formato
(`build/refs/Kissaki/KissakiViewerApp/Core/Formats/OidDecoder.cs:33-36`:
`maxOidIndex` @+0x00, relleno 0 @+0x04, `constant` @+0x08, relleno 0 @+0x0C):

| offset | tipo | campo | confianza |
|---|---|---|---|
| `+0x00` | `u32` | `maxOidIndex` — último `globalOid` del fichero | `medido` |
| `+0x04` | `u32` | relleno, **0 en 581/581** ficheros | `medido` |
| `+0x08` | `u32` | constante `0x0696CA22`, igual en **581/581** | `medido` |
| `+0x0C` | `u32` | relleno, **0 en 581/581** ficheros | `medido` |
| `+0x10` | `u32` | `globalOid` — id global de hueso, estrictamente creciente | `medido` |
| `+0x14` | `u32` | `boneNameFk` — hash del nombre de hueso | `inferido` (ver §1.3) |
| `+0x18` | `u32` | relleno, **0 en 581/581** ficheros | `medido` |

Los cuatro campos de cabecera se midieron uno a uno en los 581 ficheros
(comprimidos incluidos) con
`informes/t_a918257a/probes/p24_cabecera_oid_u32.py`: relleno izquierdo
581/581, constante 581/581, relleno derecho 581/581, `maxOidIndex` == último
`globalOid` (o 0 sin entradas) 581/581. La lectura anterior como 2 × `u64`
daba los mismos números porque el `u32` alto vale **0 en 581/581** — eso está
medido. El tipo `u32` de cada campo procede de la fuente citada (Kissaki, §7):
con el alto siempre a 0 un `u64` y dos `u32` son indistinguibles en Pokopia,
así que el ancho se toma de la autoridad y los valores, de la medición.

`(tamaño − 16) % 12 == 0` y `entradas == (tamaño − 16) / 12` se cumple en
**581/581** ficheros. `globalOid` crece de forma estricta en todos y, cuando
hay entradas, el último valor es igual a `maxOidIndex` (579/581; las 2
excepciones son los ficheros sin entradas). La serie es corrida (`1..n`, sin
huecos) en **157** ficheros y **sparse** (huecos, `maxOidIndex > n`) en
**424**.

```
$ xxd -l 64 build/grpoid/oid/0x00093a63.oid      # 2164 B, el mayor
00000000: 6401 0000 0000 0000 22ca 9606 0000 0000  d.......\".......
00000010: 0100 0000 cc68 ee7a 0000 0000 0200 0000  .....h.z........
00000020: 5916 d737 0000 0000 0300 0000 1c2e f2a4  Y..7............
00000030: 0000 0000 0400 0000 7bd3 a3ac 0000 0000  ........{.......
```

Cabecera de ese volcado, campo a campo: `64 01 00 00` = `maxOidIndex = 356`,
`00 00 00 00` = relleno, `22 ca 96 06` = constante `0x0696CA22`,
`00 00 00 00` = relleno; 179 entradas de 12 B
(`16 + 179·12 = 2164`). Dos oid del dump no llevan ninguna entrada: son de
16 B y `maxOidIndex = 0` (`0x05907593` y `0x61f597e7`).

```
$ xxd build/grpoid/oid/0x05907593.oid
00000000: 0000 0000 0000 0000 22ca 9606 0000 0000  ........\".......
```

### 1.2 Ejemplo completo

`0x00093a63.oid` (2164 B), volcado entero en
`informes/t_a918257a/evidencia/oid_0x00093a63.tsv`:

| i | globalOid | boneNameFk |
|---|---|---|
| 0 | 1 | `0x7AEE68CC` |
| 1 | 2 | `0x37D71659` |
| 2 | 3 | `0xA4F22E1C` |
| 3 | 4 | `0xACA3D37B` |
| 4 | 5 | `0x517150B9` |
| … | … | … |
| 177 | 355 | `0xC4D16E24` |
| 178 | 356 | `0x76141B9C` |

179 entradas para `globalOid` 1..356 → **177 huecos**: la tabla es *sparse*.

### 1.3 Qué es `boneNameFk`

`boneNameFk` es el **hash del nombre de hueso**. Evidencia (medida en los 581
ficheros, comprimidos incluidos):

| hash | apariciones | en qué `globalOid` |
|---|---|---|
| `0x7AEE68CC` | 576 (en 576 ficheros) | **siempre `globalOid = 1`** (576/576) |
| `0x8630DCF5` | 80 (en 80 ficheros) | **siempre `globalOid = 2`** (80/80) |
| `0xF6BB7F79` | 58 (en 58 ficheros) | repartido: 66, 3, 4, 5, 21… |
| `0x90F79E3A` | 43 (en 43 ficheros) | repartido: 7, 13, 22… |
| `0x4FAE6099` | 77 (en 77 ficheros) | repartido: 9, 14, 10… |

Kissaki (`OidDecoder.cs:16-23`) publica, para DOA6, exactamente esos cinco
valores como nombres de hueso: `0x7AEE68CC = common_bone_01`,
`0x8630DCF5 = common_bone_02`, `0xF6BB7F79 = common_bone_03`,
`0x90F79E3A = part_bone_01`, `0x4FAE6099 = part_bone_02`. Que el
`common_bone_01` salga **siempre** en el id 1 y el `common_bone_02` **siempre**
en el id 2, con la misma coincidencia que en DOA6, es la mejor evidencia de
que `globalOid` es un **índice de hueso** y `boneNameFk` su nombre.

**No** se pudo reproducir el hash con `kt_hash("common_bone_01")` (da
`0xCBB46B08`, no `0x7AEE68CC`; 240 variantes de prefijo/extensión/mayúsculas
probadas, 0 aciertos): el nombre del *hint* de DOA6 no es la cadena exacta, o el campo usa otra función. Queda **abierto**; la semántica
(id → hash de nombre de hueso) se sostiene por el patrón y por la coincidencia
de los cinco hashes entre dos juegos del mismo motor.

---

## 2. `.grp` — tabla de enlace de piezas

**Tipo `type_ktid = 0x56EFE45C`** (323 entradas, 35.296 B). Existe también
`0xBBF9B49D` con la misma extensión, sin entradas en este dump.

### 2.1 Cabecera y stride: **no hay cabecera**

El fichero es un **array plano de registros de 32 B (8 × `u32`)**.
`len % 32 == 0` se cumple en **323/323** ficheros; 35.296 / 32 = 1.103
registros en total.

| offset | campo | confianza |
|---|---|---|
| `+0x00` | `partsNameHash` — hash del nombre de la pieza | `inferido` |
| `+0x04` | `partsId` | `inferido` |
| `+0x08` | `countT` | `inferido` |
| `+0x0C` | `countBigT` | `inferido` |
| `+0x10` | `countS` — **0 en 1.103/1.103** | `medido` |
| `+0x14` | `setCountT` | `inferido` |
| `+0x18` | `setCountBigT` | `inferido` |
| `+0x1C` | `setCountS` — **0 en 1.103/1.103** | `medido` |

El nombre de los campos y el orden vienen de Kissaki (`GrpDecoder.cs:18-26`,
«parses `.grp` (**parts group bind table**) files; headerless array of 0x20-byte
GRPEntry records») y coinciden con KashiraModManager (`GrpDoc.cs:9`: «grp = array
de GRPEntry de 0x20 B sin cabecera, cada uno 8×u32»).

`0x3057221F` **no es un magic de cabecera**: es un `partsNameHash` más
(KashiraModManager lo usa como valor por defecto al generar un grp de una
sola pieza). Coincide con el registro 0 en **247 de los 323** ficheros (las
247 apariciones de ese hash en todo el dump están en el registro 0); los
otros 76 empiezan por otro hash cualquiera.

Distribución medida de los campos (1.103 registros):

```
campo +00: distintos=412   top=[(811016735=0x3057221F, 247), (3909846565, 76), ...]
campo +04: distintos=4    top=[(0, 1094), (1, 5), (2, 3), (3, 1)]
campo +08: distintos=14   top=[(1, 637), (2, 228), (3, 76), (4, 65), (0, 25), (5, 24)]
campo +0C: distintos=3    top=[(0, 1046), (1, 53), (2, 4)]
campo +10: distintos=1    top=[(0, 1103)]
campo +14: distintos=14   top=[(1, 650), (2, 217), (3, 76), (4, 66), (0, 25), (5, 22)]
campo +18: distintos=3    top=[(0, 1046), (1, 54), (2, 3)]
campo +1C: distintos=1    top=[(0, 1103)]
```

`countT` y `setCountT` coinciden en 1.084 de 1.103 registros (19 excepciones,
17 de ellas con `countT = setCountT + 1`); igual `countBigT`/`setCountBigT`. Eso y
los nombres de campo apuntan a que son **conteos de malla e índices de la
pieza**, no a coordenadas: KashiraModManager los deriva del slicing del `.g1m`
(`G1mFile.cs:58,63`: «Sm1/Sm2 = nº de entradas de malla, CountT/CountBigT =
suma de idx_count»). Sin esa referencia sería `supuesto`.

### 2.2 Ejemplo completo

`0x26618a6f.grp` (1248 B = 39 registros), volcado entero en
`informes/t_a918257a/evidencia/grp_0x26618a6f.tsv`:

```
$ xxd -l 96 build/grpoid/grp/0x26618a6f.grp
00000000: 1f22 5730 0000 0000 0300 0000 0000 0000  .\"W0............
00000010: 0000 0000 0300 0000 0000 0000 0000 0000  ................
00000020: 9484 e677 0000 0000 0300 0000 0000 0000  ...w............
00000030: 0000 0000 0300 0000 0000 0000 0000 0000  ................
```

| i | partsNameHash | partsId | countT | countBigT | countS | setCountT | setCountBigT | setCountS |
|---|---|---|---|---|---|---|---|---|
| 0 | `0x3057221F` | 0 | 3 | 0 | 0 | 3 | 0 | 0 |
| 1 | `0x77E68494` | 0 | 3 | 0 | 0 | 3 | 0 | 0 |
| 2 | `0x0C2AF395` | 0 | 3 | 0 | 0 | 3 | 0 | 0 |
| 3 | `0xA06F6296` | 0 | 3 | 0 | 0 | 3 | 0 | 0 |
| 4 | `0x34B3D197` | 0 | 3 | 0 | 0 | 3 | 0 | 0 |
| 5 | `0x30859D81` | 0 | 3 | 0 | 0 | 3 | 0 | 0 |

39 piezas distintas (39 `partsNameHash` distintos en 39 registros).

---

## 3. Compresión propia: 10 B + zlib + `00 00`

**55 de los 323 `.grp` y 5 de los 581 `.oid`** van comprimidos. El resto va en
crudo (268 grp, 576 oid).

| offset | tipo | campo | confianza |
|---|---|---|---|
| `+0x00` | `u16` | longitud del stream zlib que empieza en `+0x0A` | `medido` |
| `+0x02` | `u32` | sin semántica demostrada | `supuesto` |
| `+0x06` | `u32` | sin semántica demostrada | `supuesto` |
| `+0x0A` | stream | zlib (`78 9C` en los 60) | `medido` |
| final | `u16` | `00 00` de relleno | `medido` |

`u16@0 == longitud del stream` se cumple en **60/60** (verificado con
`zlib.decompressobj`, que devuelve el tramo no consumido). Los dos `u32` de
medio **no** son `crc32` ni `adler32` del payload (0 coincidencias en 60), pero
tampoco son aleatorios: dos ficheros con payload distinto (un grp y un oid)
comparten los mismos 8 bytes.

```
$ xxd build/grpoid/grp/0x0167934a.grp        # 32 B comprimidos
00000000: 1400 9144 93bb 4b28 dfa0 789c 2b08 b75b  ...D..K(..x.+.[
00000010: c900 48c0 c080 80cc 0600 3336 01b1 0000  ..H........66....
```

`u16@0 = 20` (0x14), stream de 20 B en `+0x0A`, `adler32` del payload
(`0x333601B1`) como últimos 4 bytes del stream, y `00 00` al final. Al
descomprimir: 32 B = **1 registro**. Los 55 grp comprimidos descomprimen todos
a 32 B; los 5 oid, a 64 B (`16 + 4·12`, cuatro entradas).

Los 6 oid que empiezan por `14 00` **no** están comprimidos: es simplemente
`maxOidIndex = 20` (su constante `0x0696CA22` está donde toca y sus entradas
leen bien: `[1,2,10,11,12,20]` y series parecidas).

---

## 4. Cada `.grp` y cada `.oid` pertenecen a un `.g1m`

El pareado es exacto, con la misma constante que la comunidad midió en DOA6
(`OidDecoder.cs:39-42`):

| tipo | relación | aciertos | control (desplazamiento aleatorio) |
|---|---|---|---|
| `oid` | `name_hash(oid) + 0x0E05C687 = name_hash(g1m)` | **581/581** | 0 |
| `grp` | `name_hash(grp) + 0xF9106E82 = name_hash(g1m)` | **323/323** | 0 |

```
oid  +0x0E05C687 -> g1m: 581/581   control azar: 0
grp  +0xF9106E82 -> g1m: 323/323   control azar: 0
```

La constante `0xF9106E82` es **nueva** (la de DOA6 no sirve para `grp`: 0/323)
y es inequívoca: la segunda diferencia más común (`0x9BEBC0A6`) da 19
aciertos frente a 323.
Los demás compañeros (`ktid`, `mtl`, `swg`, `rigbin`) no usan ninguna de las
dos constantes: 0 aciertos con `0x0E05C687`.

Esto es el cruce que sí funciona: **del `.grp` o el `.oid` se llega al modelo
`.g1m` que los usa**, y de ahí a los `g1t` de sus texturas.

---

## 5. La hipótesis de partida, refutada

La tarjeta planteaba: *«`grp` = lista de instancias colocadas en el mundo (qué
objeto, qué posición, qué rotación)»*. **No se sostiene.**

1. **No hay posiciones.** De los 7.721 campos `u32` que no son el
   `partsNameHash` (1.103 registros × 7 campos), **0** tienen un valor que,
   leído como `float32`, caiga en un rango creíble de metros (1e-3 .. 1e6):
   son todos enteros de 0 a 14. Un registro de 32 B no da sitio para tres
   coordenadas además del hash y de los seis contadores.
2. **No hay rotación ni escala**, por el mismo motivo (mismo recuento).
3. **El formato ya está descrito por la comunidad** como *parts group bind
   table* (tabla de piezas), no como tabla de colocación (§2).

**Acotación del test `float32`** (p16 §4, línea 90): el rango comprobado es de
**magnitud** —`1e-3 < |float32| < 1e6`, el sondeo aplica `abs()`, así que
cubre también negativos de esa magnitud—. Quedan **fuera** del test
`|x| ≤ 1e-3`, `|x| ≥ 1e6`, `NaN` y cualquier codificación que no sea
`float32` (enteros a otra escala, punto fijo): por este test solo se afirma
que ninguno de los 7.721 campos cae en el rango creíble, no que no existan
coordenadas escritas de otra forma. El resto de la refutación (puntos 2 y 3 y
los cruces de abajo) no depende de ese rango.

Y la segunda parte del criterio —*«que `X` se pueda cruzar con `pkp catalog
find` o con `kidsobjdb`»*— tampoco se cumple:

```
$ python pkp.py catalog list | grep -i -E "3057221f|7aee68cc|0696ca22"
# 2043 entidades de 0x2943e4da.fdata
# reparto: BP 1473, PM 399, BI 87, PC 73, AP 11
        (sin ninguna línea de entidad: 0 coincidencias)

partsNameHash distintos = 412   en catálogo (2043) = 0
boneNameFk distintos    = 6305  en catálogo (2043) = 0
s0(grp) ∩ ids de kidsobjdb = 0      b(oid) ∩ ids de kidsobjdb = 1  (control: 1)
s0(grp) ∩ hashes de par     = 0      b(oid) ∩ hashes de par     = 0
s0(grp) ∩ valores objdb     = 0      b(oid) ∩ valores objdb     = 0
s0(grp) ∩ name_hash de entradas del fdata = 0     (99.710 valores)
```

El único cruce de `b` con el objdb (`0xBB04C886`) es azar: 6.305 valores contra
294.939 ids esperan 0,43 coincidencias por azar y salió 1.

### Lo que sí se puede imprimir

Con el formato real, la línea equivalente a la del criterio es:

```
GRP: el grupo 0x26618A6F (39 registros) lista las piezas del modelo 0x1F71F8F1;
     la primera es la pieza 0x3057221F con partsId=0, countT=3, setCountT=3

OID: el oid 0x00093A63 enlaza 179 ids de hueso (1..356) con sus hashes de nombre
     del modelo 0x0E0F00EA; el id 1 -> 0x7AEE68CC
```

---

## 6. Límites

- **Los nombres en claro no están en este dump.** Ni el nombre de la pieza
  (`partsNameHash`) ni el del hueso (`boneNameFk`) se pueden traducir a texto
  aquí: el volcado es solo el update y los `.name` viven en el romfs base
  (ver `docs/NOMBRES-DE-FICHERO-EN-RDB.md`). Hasta que entre ese romfs, los
  hashes son intraducibles, no desconocidos en origen.
- **Semántica de `countT`/`setCountT`**: `inferido` (nombres de campo de la
  comunidad + reparto medido), `supuesto` en cuanto a qué cuenta exactamente
  cuenta cada uno.
- **Cabecera de compresión**: el `u16` está medido (60/60); los dos `u32` son
  `supuesto` sin demostrar.
- **`kt_hash` de los nombres de hueso**: sin resolver (§1.3).
- Los `.grp` del tipo `0xBBF9B49D` y los `.oid` `0xDBCB74A9` no existen en este
  dump, así que su formato no está abierto aquí.

---

## 7. Procedencia de la especificación

El esqueleto de formato no es mío: sale de dos repositorios de la comunidad
que ya abrieron estos tipos en juegos del mismo motor (KTGL/Katana de Koei
Tecmo):

| fuente | fichero | licencia |
|---|---|---|
| `umin135/Kissaki` | `KissakiViewerApp/Core/Formats/GrpDecoder.cs`, `OidDecoder.cs`, `KtidExtension.cs` | GPL-3.0 |
| `DeathChaos25/fdata_dump` | `Program.cs` (extensión por `type_ktid`), `rdb_extensions.csv` | GPL-3.0 |

Ambos fijan `0x56EFE45C → .grp` y `0x1AB40AE8 → .oid` (el mismo `type_ktid` que
en Pokopia) y el orden de campos reproducido en §1.1 y §2.1. No se ha copiado
código: las sondas de este informe son Python propio y los campos se
reimplementaron a partir de la lectura.

`umin135/KashiraModManager` (sin `LICENSE` en el repositorio, consultado, sin
reutilizar código) añade la lectura de `0x3057221F` como `partsNameHash` por
defecto y el origen de los contadores en el slicing del `.g1m`.

La constante `0x0E05C687` de pareado `oid → g1m` es de Kissaki y aquí se
confirma (581/581); la de `grp → g1m` (`0xF9106E82`) es **nueva**, medida en
este dump.

---

## 8. Cómo verificar

```bash
# 1. extracción (solo lectura del dump)
python pkp.py fdata extract --type grp --out build/grpoid/grp "$PKP_ROMFS/motor_asset_re"
python pkp.py fdata extract --type oid --out build/grpoid/oid "$PKP_ROMFS/motor_asset_re"

# 2. stride y cabeceras: 581/581 oid con (len-16)%12==0 y constante 0x0696CA22
# 3. grp sin cabecera: 323/323 con len%32==0
# 4. pareado oid->g1m y grp->g1m con control de azar
# 5. refutacion de posiciones: 0 de 7721 campos como float32 creible
python informes/t_a918257a/probes/p16_evidencia_final.py
python informes/t_a918257a/probes/p14_verifica_kissaki.py
python informes/t_a918257a/probes/p19_cabecera_stream.py

# 6. todas las cifras de este documento (serie/sparse, pad, 0x3057221F en el
#    registro 0, countT vs setCountT, constante de pareado, variantes de
#    kt_hash, oid sin entradas)
python informes/t_a918257a/probes/p22_cifras_doc.py
python informes/t_a918257a/probes/p23_oid_vacios.py
```

Los volcados de los dos ejemplos completos están en
`informes/t_a918257a/evidencia/`.
