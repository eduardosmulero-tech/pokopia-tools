# `g1s` y `g1n`: qué son las 26.137 piezas (8,48 GB) y los 6 ficheros de 211 MB

Tarjeta `t_bcadcd7e` · 11-nov-2026 · **solo lectura** sobre el dump de
referencia (build 655360, apuntado por `PKP_ROMFS`; rutas en este documento como
`<romfs>` para no meter rutas de esta máquina).

## 0. Respuesta corta

- **Un `g1s` es un recurso de shader del motor KTGL**: lleva un nombre de
  permutación (`PB2-AmtCcrtOfPkS2aTf00f`, `SKY2AEX`, `G1E-…`) y dentro, texto de
  reflexión de shader (`g_vSunDir`, `iovShadowPos0`, `ktglNormal0`, `GBuffer`,
  `FxPhysicallyBased2`). **No es una escena, ni un prefab, ni un esqueleto.**
- **Un `g1n` es una fuente de mapa de bits** (tabla de puntos de código Unicode,
  paleta con rampa alfa de 16 niveles, registros por glifo y atlas). **No es
  navegación ni malla de colisión.**
- **`g1s` NO contiene hashes de `g1m`/`g1t`**: barrido estadístico por debajo del
  azar (§5). La cadena real es al revés y por otro hash: el objdb → `g1s`.

Todo lo que sigue está etiquetado `[MEDIDO]` (comando y salida literal en §8) o
`[INFERENCIA]`.

---

## 1. Paso 0 — qué ya existía en la comunidad

Clonado en `build/refs/` (ignorado por git) antes de escribir una sonda propia:

| repo | commit | qué hace con `g1s`/`g1n` |
|---|---|---|
| [DeathChaos25/fdata_dump](https://github.com/DeathChaos25/fdata_dump) (GPL-3.0) | `7690d0c` (06-abr) | `kidstypeinfodb.yml:434-445` — nombre de tipo: `TypeInfo::Resource::KTGL::G1SFile` **Hash `0x7BCD279F`**, `G1NFile` **Hash `0x786DCD84`**. `Properties: []`: **no da layout**. |
| [MrIkso/RDBExplorer](https://github.com/MrIkso/RDBExplorer) | `22e72d8` (28-jun) | `Formats.md:19,21` — `G1NFile .g1n` «Font glyph data and font texure» magic `0x5f4e3147`; `G1SFile .g1s` «**Compiled shaders**» magic `0x5f533247`. `Utils/TypeIDHelper.cs:97,100` y `Utils/FileTypeDetector.cs:64,69` hacen el mapeo hash/magic→extensión. **Parser ❌ en ambos.** |
| [umin135/Kissaki](https://github.com/umin135/Kissaki) | `91343b1` (09-nov) | `KissakiViewerApp/Core/Formats/MetadataExtractor.cs:292 ExtractG1n` → «Bitmap Font (G1N)» con `atlasCount@0x10`, `atlasTotalSize@0x0C`, `paletteCount@0x18`, `tableCount@0x1C`; `:374 ExtractG1s` → **etiqueta «G1S Skeleton»** con magic `_S2G`+versión, `totalSize@0x08`, `name@0x10 (32 B)`. `KtidExtension.cs` (`0x7BCD279F→.g1s`, `0x786dcd84→.g1n`). `README.md:53` acredita [lehieugch68/G1N-Font-Editor](https://github.com/lehieugch68/G1N-Font-Editor). |
| [umin135/KashiraModManager](https://github.com/umin135/KashiraModManager) | `28e8f7f` (23-jul) | `src/Kashira.Core/Formats/AssetTypes.cs:6,28` — `g1s = 0x7BCD279F` («system.rdb에 주로 존재»), pero **su `g1n = 0xA1A36B1A`, que NO es nuestro tipo**: no mezclar. `PatchEngine.cs:253` enruta `typeKtid == G1s` al `system.rdb`. |
| [berichan/PokoHex](https://github.com/berichan/PokoHex) (GPL-3.0) | `e2f7089` | **cero** apariciones de `g1s`/`g1n` en su código (es editor de save). |

Dos cadenas independientes del propio tipo (`kidstypeinfodb.yml:1241` en fdata_dump
y `Databases/all_properties.csv` en RDBExplorer) nombran el campo
**`G1SFileResourceHash = 0x193025DF`** como propiedad de
`TypeInfo::Object::Render::State::3D::Shader::Effect*` → el `G1S` lo referencia
un **objeto de efecto/shader**, no un modelo.

**Lo que no sirve de lo existente** (por qué medimos nosotros): ninguno de los
cinco parsea el contenido. RDBExplorer declara `Parser ❌`; Kissaki saca 4 campos
para mostrar metadatos y su etiqueta «Skeleton» **no se sostiene** contra nuestro
payload (§4); fdata_dump solo nombra el tipo; Kashira solo lo enruta a un `.rdb`.
Lo que falta —y está aquí— es el **censo del 100 %**, la **cabecera medida** y la
**pregunta de las referencias**.

> Cuidado con las magics: en este juego `g1a` se mide `_A2G`/`_A1G` y `g1m` va
> `_M1G` a `+12` (`docs/MODELOS-G1M-Y-TEXTURAS-G1T.md`, `docs/ANIMACIONES-G2A.md`).
> Aquí las dos magics de la comunidad **sí** coinciden con el dump: `_S2G` y `_N1G`.

---

## 2. Punto de partida reproducido

```
python pkp.py fdata stat <romfs>/motor_asset_re
```

```
ficheros  : 24 .fdata, 5063190412 B
entradas  : 79710
  g1s          0x7bcd279f     26137       26137       8481193512
  g1a          0x6fa91671     17457       17457        697681192
  g1t          0xafbec60c     14412       14412       6296584324
  g1m          0x563bdef1      3204        3204        283331492
  g1n          0x786dcd84         6           6        211365748
```

Cifras idénticas a las de la tarjeta `[MEDIDO]`.

**Coste de E/S de esta tarjeta** (el aviso de 8,5 GB se respeta leyendo solo el
primer trozo zlib de cada entrada, `read_prefix` de `s1_cabeceras.py`):

| sonda | qué lee | B leídos |
|---|---|---|
| `s1` censo cabeceras | 26.137 + 6 prefijos (96/256 B) | 143.723.315 + 1.904 |
| `s2` referencias | 400 `g1s` enteros | 32.859.098 |
| `s4`+`s18` muestras | 3 `g1s` (8 MB del mayor) | ~8.600.000 |
| `s6` quien refiere | `sid`+`mtl`+`g1e`+`kidsrender` | ~4.750.000 |
| `s7` al reves | 400 `g1m` + 150 `g1t` | 31.572.602 |
| `s9`/`s16`/`s17` g1n | 6 `g1n` enteros | 211.365.748 |
| `s15` vocabulario | 300 `g1s` enteros | 79.819.464 |
| `s19`+`s21` barrido `LD_C0_R.BIN` | las 12.298 entradas, dos pasadas completas | 1.096.655.728 B descomprimidos (2 × 247.317.504 en disco) |
| `s22`+`s23` paquetes/totales `LD` | 4 entradas + el IDX | 4.758.068 B descomprimidos (1 × 247.317.504 en disco) |
| **total de `g1s`/`g1n`** | | **≈ 515 MB de 8.481.193.512 (6 %)** |
| **total con `LD_C0_R.BIN`** | | **≈ 2,4 GB** (742 MB de disco + 1,1 GB descomprimidos) |

---

## 3. `g1s`: cabecera `[MEDIDO]` (26.137/26.137 cabeceras leídas)

| Off | Tipo | Campo | Valor medido |
|---|---|---|---|
| `0x00` | `4s` | magic | `_S2G` **26.137/26.137** |
| `0x04` | `4s` | versión | `7000` **26.137/26.137** (una sola forma) |
| `0x08` | `u32` | `totalSize` | = payload sin comprimir **26.137/26.137** |
| `0x0C` | `u32` | desconocido | `0x00100003` **constante en 26.137** |
| `0x10` | `32s` | nombre (NUL-padded) | ver §3.2 |
| `0x30` | `8s` | código de variante | `0000Y` 24.684 · `2000Y` 1.108 · `1000Y` 280 · `0500Y` 18 · `8300Y` 15 · `0100Y` 14 · `8000Y` 7 · `3000Y` 4 · `0001Y` 3 · `0300Y` 1 `[INFERENCIA: variante/calidad]` |
| `0x38` | `u16` | desconocido | `89` **constante en 26.137** |
| `0x3C` | `u32` | recuento | `1` en 26.080; resto 2…311 |
| `0x40` | `u32` | flags/constantes | 135 valores distintos (p. ej. `0xbe8c0406` ×3.314, `0x00040006` ×2.673) |

Las 26.137 van **comprimidas** (`flag 0x400000`, 0 crudas) y **todas caben en
dos ficheros**: `0x38f972af.fdata` 24.957 y `0x05d525ae.fdata` 1.180.
Los 26.137 `name_hash` son **distintos** entre sí.

### 3.1 Tamaños `[MEDIDO]`

```
min 3.880 · p25 48.816 · mediana 183.348 · p75 450.464 · max 211.499.064
suma 8.481.193.512  (cuadra con pkp fdata stat)
<10 KB 71 · 10-50 KB 7.766 · 50-100 KB 4.867 · 100-500 KB 9.498 · 0,5-2 MB 3.825 · ≥2 MB 110
```

### 3.2 Nombres: 26.137 no son 26.137 cosas distintas `[MEDIDO]`

- **18.590 nombres distintos** (más 1 entrada sin nombre) de 26.137 → 7.547
  repeticiones. **14.994 ocupan los 32 B enteros**, así que el nombre está
  **truncado**: 18.590 es **cota inferior**.
- Familias (prefijo hasta el primer guion):

| familia | entradas | lectura |
|---|---|---|
| `PB2-` | 21.233 | permutaciones del pipeline principal |
| `PB2TREE2-` | 3.267 | árboles |
| `SM-` / `SMTREE2-` | 981 / 106 | sombras? `[INFERENCIA]` |
| `STD-` | 113 | estándar |
| `OLPB2-` | 65 | |
| `DEPTH-` | 61 | profundidad |
| `GRASS2-` / `PB2GRASS2-` | 50 / 26 | hierba |
| `G1E-` | 15 | efectos (contiene el de 211 MB) |
| `SOCEAN-` 9 · `SRIVER-` 7 · `HeightFog-` 4 · `PB2SNOW-` 4 · `KTF2-` 8 | | océano, río, niebla, nieve |
| `ARPSSSShader-` | 3 | el propio nombre lleva «Shader» |

- Repetidos: 3.668 nombres con >1 instancia (11.214 instancias); de ellos
  **3.283 tienen varios tamaños distintos** → no son copias byte a byte (o son
  nombres truncados que colisionan). Ej. `PB2-AlepmeAmtAtCcrdCllIra11IribN`
  con {399.040: 2, 398.056: 2, 510.360: 2, 511.608: 2, …}.
- Más instanciados: `PB2-AmtAtCllOfPtS2aSplsSslsSsmSt` ×59,
  `PB2-AmtCllOfPtS2aSplsSslsSsmStba` ×58, `PB2-AlepmaenAmtAtCcrdCllDiIraIri` ×56.

---

## 4. Qué lleva dentro un `g1s` `[MEDIDO]`

Volcados en `build/muestras/` (`s4_muestras.py`), tres tamaños distintos:

| muestra | B | nombre (`0x10`) | cadenas de ejemplo dentro |
|---|---|---|---|
| mínimo | 3.880 | `SKY2AEX` | `g_RwSunScale`, `cbSky2AtmoExtinction`, `g_vSunDir`, `g_vSunInfo`, `g_vAltitudeInfo` |
| mediano | 183.348 | `PB2-AmtCcrtOfPkS2aTf00f` | `OccFader`, `AmbientMapTransform`, `Scattering2FogAccel`, `ColorController`, `PB2TexPack`, `sCcrMapArr`, `sGxAmbLut`, `iovShadowPos0…3`, `ktglNormal0`, `ktglTexcoord0` (206 cadenas ≥8 B) |
| máximo | 211.499.064 | `G1E-CllCsDDomEEmeEtmFoHMMvNP2ale8300` | `FxNormalMap`, `FxPhysicallyBased2`, `ThinSurfaceBSDF`, `FxToneMap`, `FxEnvMap`, `FxRefraction`, `ClusterLightList` (13.768 cadenas en los primeros 8 MB) |

Son **nombres de uniforme/buffer/semántica de shader** (`g_v*` = global uniform,
`cb*` = constant buffer, `iov*` = input/output semantic, `ktgl*` = atributos del
motor, `s*` = sampler/constante de material, `Fx*` = feature de efecto).

Censo de vocabulario sobre 300 `g1s` aleatorios-ordenados por tamaño
(`s15_vocabulario.py`, 79.819.464 B, 96.983 cadenas ≥6 B):

```
  con vocabulario de shader : 300/300
  con '.g1t/.g1m/...'        :   0/300
  con ruta de fichero        :   0/300
```

Composición del cuerpo (fuera de los primeros 0x400 B) en el mediano:
`H = 3,75 bits/byte`, `53,4 %` ceros → binario **estructurado** (tablas, enteros
pequeños), no código denso `[INFERENCIA: el bytecode de GPU, si existe, va en
secciones concretas; no está demostrado]`.

**Etiqueta de la comunidad:** RDBExplorer dice «Compiled shaders» y nuestro
contenido lo confirma. La etiqueta **«G1S Skeleton» de Kissaki no se sostiene**:
un esqueleto no contiene `g_vSunDir` ni `GBuffer`. Sus **offsets** sí coinciden
con los nuestros (`magic`, `totalSize@0x08`, `name@0x10`).

### 4.1 Comparación con `g1m` y `g1a` (ya documentados)

| | `g1m` (`docs/MODELOS-G1M-Y-TEXTURAS-G1T.md`) | `g1a` (`docs/ANIMACIONES-G2A.md`) | `g1s` (este documento) | `g1n` (§6) |
|---|---|---|---|---|
| magic en disco | `_M1G` **a +12** (envoltorio 12 B) | `_A2G` (17.428) / `_A1G` (29) | `_S2G` en 0 | `_N1G` en 0 |
| versión | `7300` | `0400` / `2400` | `7000` | `0000` |
| cabecera | 24 B + 4 chunks `FM1G/SM1G/MM1G/GM1G` | 32 B | ≥ `0x44` B (medido) | ≥ `0x24` B + paleta |
| entradas en `.fdata` | 3.204 | 17.457 | 26.137 | 6 |
| B sin comprimir | 283.331.492 | 697.681.192 | 8.481.193.512 | 211.365.748 |
| qué es | malla + materiales + esqueleto interno | animación esquelética | **shader (permutación/pipeline)** | **fuente de mapa de bits** |

---

## 5. ¿Referencia `g1s` a `g1m`/`g1t` por hash? `[MEDIDO]` — **NO**

Método: se construye el conjunto de `name_hash` de las entradas `g1m`/`g1t` de
los 24 `.fdata` (solo cabeceras) y se barre el payload **entero** de una muestra
mirando u32 alineados. Control: el mismo barrido contra conjuntos aleatorios del
mismo tamaño, tomados del propio universo de 79.710 `name_hash` reales.

| barrido | leídos | B payload | u32 | aciertos | esperado por azar | control aleatorio |
|---|---|---|---|---|---|---|
| `g1s` → `g1m`+`g1t`+`g1t_new` | 400 | 32.859.098 | 26.229.321 | **21** | **107,581** | 1, 0, 1, 0, 29 |
| `g1s` → cualquier tipo | 400 | 32.859.098 | 26.229.321 | **50** | **486,788** | — |
| `g1m` → `g1s` | 400/3.204 | 18.879.261 | — | **25** | **52,499** | 37 |
| `g1t` → `g1s` | 150/14.412 | 12.693.341 | — | **9** | **86,254** | 6 |
| `sid` → `g1s` | 17 | 2.062.890 | — | 2 | 5,415 | 2 |
| `mtl` → `g1s` | 1.531 | 67.542 | — | 0 | 0,102 | 0 |
| `g1e` → `g1s` | 1.173 | 2.500.282 | — | 0 | 29,835 | 0 |
| `kidsrender` → `g1s` | 18 | 145.290 | — | 0 | 1,363 | 1 |

**Por debajo del azar en todos los casos**: dentro de un `g1s` no hay hashes de
modelo ni de textura de este contenedor. Se cierra la hipótesis de la tarjeta.

### 5.1 La cadena que sí existe (y no es colocación de objetos)

```
kidsobjdb (0x52482d03.fdata) → campo 0x193025df (== G1SFileResourceHash)
  294.920 registros con referencia
  108.909 resueltos (36,93 %) a name_hash de una entrada .fdata
  tipos referenciados: [('g1s', 108.909)]   ← 100 %
  control: 75.807 valores aleatorios → 1 coincidencia
```

Fuente: `informes/t_fb325da0/evidencia/cruce.txt` (también
`docs/NOMBRES-DE-FICHERO-EN-RDB.md` §5, con el TSV de 108.909 filas).
Traducción: **un objeto del mundo referencia su shader**, no su modelo. La
colocación de objetos en el mundo no está en `g1s` (está en las tablas `oid`/
`oidsq`, fuera de esta tarjeta).

---

## 6. `g1n`: 6 ficheros, 211.365.748 B `[MEDIDO]`

Los 6 están en el mismo `.fdata` (`0x05d525ae.fdata`).

| `name_hash` | B | `+0x0C`=`+0x20` | `+0x10` | `+0x14` | `+0x18`=`+0x1C` | ceros |
|---|---|---|---|---|---|---|
| `0xe876b7f0` | 133.232 | 100 | 10 | 131.184 | 1 | **99,9 %** (fuente vacía) |
| `0x8207d16b` | 2.243.692 | 236 | 10 | 409.196 | 3 | 82,6 % |
| `0xcd2c353f` | 22.983.036 | 236 | 10 | 602.492 | 3 | — |
| `0x7abb6ce2` | 51.863.752 | 304 | 10 | 1.071.816 | 4 | — |
| `0x881d39a5` | 52.507.168 | 304 | 10 | 1.077.792 | 4 | — |
| `0x4b9d5e80` | 81.634.868 | 304 | 10 | 1.347.636 | 4 | 61,4 % |

Cabecera: `0x00` `_N1G` · `0x04` `0000` (6/6) · `0x08` `totalSize` = payload
(6/6). Después:

- **Paleta en `+0x24`**: entradas RGBA `ff ff ff 00`, `ff ff ff 11`, …
  `ff ff ff ff` → **rampa alfa de 16 niveles** (0x00 a 0xFF de 16 en 16), el
  típico índice de suavizado de glifos.
- **Tabla de puntos de código** de `u16` **ascendente con huecos a cero** desde
  `0x1B4`, dentro del rango `U+0022 … U+00BF` (p. ej. `0x8207d16b`: `U+0044`…`U+005F`,
  salto, `` U+0060 ``…`U+00FF`). No-nulos dentro de `[0x1B4, 0x1B4+2·+0x0C)`:
  158/304, 124/236, 29/236, 63/304, 63/304, **0/100** (la de 133 KB está vacía).
  `crecientes=True` en los 6.
- **Registros de 12 B a partir de `0x20000`** (`offset u32` con paso `0x800` +
  dos `u32` empaquetados cuyo byte bajo varía `0x13…0x2a`) → métrica por glifo
  apuntando a un atlas de fila de 2048 B `[MEDIDO estructura / INFERENCIA significado]`.
- **El payload útil arranca en `0x20000` en los 6**; antes, cabecera + paleta +
  tablas y relleno a cero.

**No es navegación ni colisión.** La navegación en este ecosistema es otro tipo:
`FileTypeDetector.cs:63` de RDBExplorer asigna `MN1G` → `.g1nm`
(`NavMapDataObject`, `0x077CABC9`), y la colisión es `g1co`/`g1cox`
(`0x54738c76`/`0xa8d88566`, presentes en el mismo `.fdata` con 2 entradas cada
uno). El `g1n` coincide con la «Font glyph data and font texture» de RDBExplorer,
el «Bitmap Font (G1N)» de Kissaki, las propiedades `UseG1NFontIndex` /
`UseG1NColorIndex` / `G1NResorceNameHash` de `kidstypeinfodb.yml` y el editor
externo `lehieugch68/G1N-Font-Editor` que Kissaki acredita.

**Límite honesto:** el píxel del atlas **no se decodifica**. Renderizado a grises
(`s10_g1n_png.py`) se ve una **rejilla de celdas** (visión: «estructura de un
atlas de fuente») pero los glifos no se leen: faltan ancho de celda, tiling
(morton, como en `g1t`) y formato. Queda abierto.

---

## 7. ¿Y en `LD_C0_R.BIN`? `[MEDIDO]`

Barrido de las 12.298 entradas del contenedor principal, descomprimiendo todo
(`s21_ld_barrido.py`; suma `raw_size` del IDX medida con `s23_ld_totales.py` =
**548.327.864 B** descomprimidos, `packed_size` 246.615.606, 2.505 vacías):

```
totales de apariciones: {'_S2G': 129, '_N1G': 0}
entrada  offset IDX   payload    magic  veces    u32@+0
5907     0x5a58b00    1863044    _S2G   90       90
5909     0x5abc000    1076268    _S2G   23       23
5946     0x6398100     674704    _S2G   13       13
5947     0x63b9a00     145052    _S2G   3        3
```

- **129 `g1s` más** viven en el contenedor principal, **empaquetados en 4
  entradas** (90+23+13+3 = 129). La cabecera del paquete empieza por un `u32`
  que **es** el número de payloads (coincide en 4/4).
- **0 `g1n` en `LD_C0_R.BIN`**: las 6 fuentes están solo en los `.fdata`.
- Formato del paquete validado en 4/4 por `s22_ld_paquetes.py`:

```
entrada #5907 count=90  primera en 724 (4+8*90=724)    OK  offsets crecientes  ultima offset+size = 1863044 = payload  totalSize==size 90/90
entrada #5909 count=23  primera en 188 (4+8*23=188)    OK  ...                                                       23/23
entrada #5946 count=13  primera en 108 (4+8*13=108)    OK  ...                                                       13/13
entrada #5947 count=3   primera en 28  (4+8*3=28)      OK  ...                                                        3/3
```

  o sea `u32 count | count × (u32 offset, u32 size) | payloads _S2G7000`
  contiguos, y el `totalSize` de cada cabecera `+0x08` **cuadra con el `size`
  declarado en 129/129 filas**.
- Ejemplo de paquete (entrada #5947, 145.052 B):

```
0000  03 00 00 00   1c 00 00 00 64 b9 00 00 80 b9 00 00  ...
      count=3       | tabla (offset,size) x3            | _S2G7000 en +28
001c  5f 53 32 47 37 30 30 30 64 b9 00 00 03 00 10 00   _S2G 7000 totalSize=47460 ...
      50 42 32 44 53 2d 43 61 43 6c 6c ...             nombre "PB2DS-CaCllEmIra11IribOclOfPplSm"
```

---

## 8. Reproducción

```bash
cd <repo>
# censo de cabeceras (solo primer trozo zlib por entrada)
python informes/t_bcadcd7e/s1_cabeceras.py <romfs>/motor_asset_re --limite 96 --tipos g1s --out build/censo_g1s_cabeceras.json
python informes/t_bcadcd7e/s3_analiza.py build/censo_g1s_cabeceras.json
python informes/t_bcadcd7e/s12_familias.py build/censo_g1s_cabeceras.json
# referencias (payload entero de la muestra)
python informes/t_bcadcd7e/s2_hashrefs.py <romfs>/motor_asset_re --n 400 --out build/hashrefs_g1s.json
python informes/t_bcadcd7e/s7_g1m_g1t.py  <romfs>/motor_asset_re --out build/g1m_g1t_refieren_g1s.json
python informes/t_bcadcd7e/s6_quien_refiere.py <romfs>/motor_asset_re --out build/quien_refiere_g1s.json
# vocabulario
python informes/t_bcadcd7e/s15_vocabulario.py <romfs>/motor_asset_re --n 300 --out build/vocabulario_g1s.json
# g1n
python informes/t_bcadcd7e/s9_g1n_perfil.py <romfs>/motor_asset_re
python informes/t_bcadcd7e/s11_g1n_hex.py <romfs>/motor_asset_re --hash 0x8207d16b --rangos 0x1b4:256,0x20000:256
python informes/t_bcadcd7e/s17_g1n_tabla.py <romfs>/motor_asset_re
# contenedor principal (descomprime las 12.298 entradas, ~2 min)
python informes/t_bcadcd7e/s21_ld_barrido.py <romfs>
python informes/t_bcadcd7e/s22_ld_paquetes.py <romfs>
python informes/t_bcadcd7e/s23_ld_totales.py <romfs>   # solo el IDX: suma raw/packed
# tests del árbol (intérprete declarado >=3.11,<3.12)
py "-V:Astral\CPython3.11.15" run-tests.py     # -> 656 passed, 68 skipped in 27.67s
```

Los archivos de muestra volcados (`build/muestras/*.bin`) y los PNG
(`build/png/*.png`) son bytes del juego en bruto: entran en el informe solo como
referencia local y **no son entregables**.

Todo el trabajo es **solo lectura**: ningún script abre el dump en escritura y
ningún fichero del juego se modifica. Salidas intermedias en `build/` (ignorado
por git); los `.bin` de `build/muestras/` son bytes del juego y **no entran al
repo** (norma `docs/NORMA-CONTENIDO-Y-PUBLICACION.md`).

## 9. Límites declarados

1. **Atlas del `g1n` sin decodificar** (formato/tiling desconocidos) — §6.
2. **Espacio de hashes**: el test de §5 cubre el `name_hash` de las 79.710
   entradas de los `.fdata`. Otros espacios (p. ej. hash del nombre interno de
   una textura) no están medidos.
3. **Bytecode de GPU en `g1s`**: no demostrado (entropía 3,75; §4).
4. **Nombres truncados a 32 B** → «18.590 nombres distintos» es cota inferior.
5. **`+0x0C`, `+0x10`, `+0x14`, `+0x18`, `+0x30`, `+0x38` de `g1s`** están
   medidos pero sin significado asignado.
6. **No se ha tocado el save ni el juego**; no se ha ejecutado nada dentro del
   emulador.
