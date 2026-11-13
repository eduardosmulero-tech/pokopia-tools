# `kidstask`: el grafo de tareas por frame (`_TGK0000`)

Todo `[MEDIDO]` en el build **655360** (juego 2.0.1a) el 11-nov-2026, con las
sondas de `informes/t_df5ad471/probes/` y su salida en
`informes/t_df5ad471/evidencia/`. El dump se abre en **solo lectura**: ni el
save ni el juego se tocan. Fuente: la entrada `kidstask` (ktid `0x1FDCAA40`)
del `.fdata` `motor_asset_re/KIDS_PLATFORM_OUNCE/0x38f972af.fdata`.

## 0. Qué es (y qué no)

**No es un grafo de misiones.** Los 33 nodos son el **grafo de tareas de
actualización y render de cada frame** del motor KTGL — `TaskGraphFile`, el
nombre que le da Kissaki al ktid (`KtidExtension.cs`, línea 60:
`[0x1FDCAA40] = ".kidstask", // TaskGraphFile`). Evidencia `[MEDIDO]`:

1. **26 de 33** nodos tienen `h1` con nombre en `kidstypeinfodb.yml`, y todos
   son `TypeInfo::TaskNode::*` (`FrameSync`, `Behavior::Update`,
   `Physics::Simulate`, `EvaluateScript`, `RegisterLightByListContainer`,
   `CommitToNextRender`…).
2. El grafo **es un ciclo de frame**: `32 View::CommitToNextRender → 00 → 01
   FrameSync → … → 32`. No hay nodo raíz ni hoja: las 58 aristas forman un
   anillo con abanicos.
3. Las propiedades son de escena/vista (`ViewObjectNameHash`,
   `TargetViewMask`, `ListContainerObjectNameHash`), no de recompensa o
   requisito.
4. Ningún hash del fichero cae en el catálogo de 2.043 entidades ni es un
   objeto `kidsobjdb` (§7).

Si algún día aparece un grafo de misiones, **no es este fichero**: aquí solo
está el frame.

## 1. Cómo se obtiene

```bash
# extraido a un fichero (lectura del dump):
python pkp.py fdata extract \
  "$PKP_ROMFS/motor_asset_re/KIDS_PLATFORM_OUNCE/0x38f972af.fdata" \
  --type kidstask --out build/kidstask
#  -> build/kidstask/0xbd13a52e.kidstask  (3.868 B)

# o directamente desde el romfs, sin paso intermedio (§2):
python pkp.py kidstask
```

`build/` está ignorado por git a propósito.

## 2. El comando reproducible (criterio de éxito)

```bash
python pkp.py kidstask            # busca la unica entrada en --container/PKP_ROMFS
python pkp.py kidstask ruta/a.kidstask   # o un fichero ya extraido
python pkp.py kidstask --json     # machine-readable
python pkp.py kidstask --props    # anade las propiedades de cada nodo
```

Salida literal guardada en
`informes/t_df5ad471/evidencia/comando_pkp_kidstask.txt` (74 líneas): cabecera,
la tabla de los 33 nodos con sus enlaces y las 58 aristas. Con
`--tipos <kidstypeinfodb.yml>` (o el que haya en
`build/refs/fdata_dump/kidstypeinfodb.yml`, clonado en el Paso 0) cada nodo
sale con su nombre; sin él avisa por stderr y sigue sacando los hashes.

Implementación: `pokopia/kidstask.py` (lector estricto, stdlib) + subcomando
`kidstask` en `pokopia/cli.py` + `tests/test_kidstask.py` (14 pruebas con
blobs sintéticos + 2 contra el dump real, que se saltan con motivo si no
está).

## 3. Cabecera, campo a campo

Hexdump literal de los primeros bytes (`evidencia/hexdump_completo.txt`):

```
000000  5f 54 47 4b 30 30 30 30 20 00 00 00 18 00 00 00  _TGK0000 .......
000010  21 00 00 00 bb 4e 70 22 00 00 00 00 1c 0f 00 00  !....Np"........
```

| offset | u32 | valor | significado | marca |
|---|---|---|---|---|
| `+0x00` | — | `_TGK0000` | firma (el revés de `KGT`, familia `…K0000`) | `[MEDIDO]` |
| `+0x08` | `0x20` | 32 | `cabecera_tamano`: offset del primer registro | `[MEDIDO]` |
| `+0x0c` | `0x18` | 24 | `cabecera_de_registro`: magic + 4×u32 | `[MEDIDO]` |
| `+0x10` | `0x21` | 33 | `recuento` de registros (casa con los hallados) | `[MEDIDO]` |
| `+0x14` | `0x22704ebb` | 577.785.531 | `kt_hash("TechPreview.kidstask.kbt.ndb")` — probado con `probes/sondeo7` contra el vector del motor; en el dict de Kissaki la misma clave nombra `…kbt.ndb.name` | `[MEDIDO]` / significado `[HIPÓTESIS]`: identifica la base de nombres asociada al fichero |
| `+0x18` | `0x00` | 0 | sin interpretar (0 en este build) | `[MEDIDO]` |
| `+0x1c` | `0x0f1c` | 3868 | tamaño declarado = `len(fichero)` | `[MEDIDO]` |

## 4. Registro `INGK0000` y su payload

```
+0x00  8   b"INGK0000"
+0x08  u32 tamano          (incluida la firma; NO hace falta %4 == 0: el 1 vale 497)
+0x0c  u32 id              hash del nodo
+0x10  u32 h1              hash de tipo -> TypeInfo::TaskNode::* en el YAML
+0x14  u32 reserva         0 en los 33
+0x18  payload de tamano-24 bytes:
         u32 N             recuento de propiedades del nodo
         u32 n + n x u32   enlaces: indices de OTROS registros (0..32)
         N x [u32 tipo][u32 len][u32 hash_prop]
         valores, en orden de descriptor, cada uno len x unidad(tipo) bytes
```

`unidad(tipo)` — solo existen dos valores en el fichero y ambos cascan con el
`Type` de la propiedad en `kidstypeinfodb.yml` `[MEDIDO]`:

| tipo | bytes | ejemplo | por qué |
|---|---|---|---|
| `1` | 1 | `Flag` (0x05d92acc) | en el YAML, `Type: Byte` |
| `5` | 4 | `ViewObjectNameHash` (0x72db7ebd) | en el YAML, `Type: UInt32` |

Un `tipo` distinto de {1, 5} es **error del lector**, no se inventa tamaño.
El payload se agota **exacto** en los 33 registros (resto = 0); el lector
falla si sobra o falta un byte.

El siguiente registro arranca en `align4(offset + tamano)`. Solo el registro
`#01` es impar (497): deja un **hueco de 3 B (`00 00 00`)** antes de `#02`
`[MEDIDO]` (`evidencia/sondeo9_grafo.txt`).

## 5. Los 33 nodos

`N` = recuento de propiedades; enlaces = índices de los nodos a los que apunta
(el «recuento» por nodo es `N`, no el número de enlaces). Tabla completa;
también sale de `python pkp.py kidstask`:

| # | offset | tam | id | h1 | tipo (`kidstypeinfodb.yml`) | N | enlaces |
|---|---|---|---|---|---|---:|---|
| 00 | `0x020` | 36 | `0x102e0433` | `0x00000000` | — | 0 | 1 |
| 01 | `0x044` | 497 | `0xea0f6b8e` | `0xab5b4109` | `…::Util::FrameSync` | 19 | 2 |
| 02 | `0x238` | 36 | `0xbbe41fd8` | `0x9552cd99` | — | 0 | 3 |
| 03 | `0x25c` | 52 | `0x4016e111` | `0xc1e6200a` | — | 1 | 4 |
| 04 | `0x290` | 136 | `0x3d42423d` | `0xe947ec4a` | `…::Behavior::Update` | 4 | 5 |
| 05 | `0x318` | 68 | `0xaf3b583d` | `0x0fa8f324` | `…::Physics::Simulate` | 2 | 6 |
| 06 | `0x35c` | 136 | `0xe9efaa7f` | `0x44079ed0` | `…::Util::UpdateLevelEvent` | 4 | 7 |
| 07 | `0x3e4` | 116 | `0x55ea3f29` | `0xd4430275` | `…::Util::EvaluateScript` | 3 | 8 |
| 08 | `0x458` | 132 | `0x8aee28f6` | `0xe947ec4a` | `…::Behavior::Update` | 4 | 9 |
| 09 | `0x4dc` | 100 | `0xf5b7000d` | `0x90a2b799` | `…::Util::UpdatePlaceable` | 4 | 10 |
| 10 | `0x540` | 68 | `0x1be2bdec` | `0x56930c1c` | `…::Util::ApplicationCallback` | 2 | 11 |
| 11 | `0x584` | 180 | `0x4963672a` | `0xae91ca0f` | `…::View::3D::BeginRegisterLight` | 4 | 12,13,14,15,16,17 |
| 12 | `0x638` | 100 | `0x735bbec5` | `0x7dc268be` | `…::RegisterLightByListContainer` | 4 | 18 |
| 13 | `0x69c` | 100 | `0xffb90f6c` | `0x7dc268be` | `…::RegisterLightByListContainer` | 4 | 18 |
| 14 | `0x700` | 84 | `0x551ea26b` | `0xf048026c` | `…::RegisterWindByOctreeManager` | 3 | 18 |
| 15 | `0x754` | 100 | `0x8f1d14d8` | `0x7dc268be` | `…::RegisterLightByListContainer` | 4 | 18 |
| 16 | `0x7b8` | 100 | `0x8fc9c077` | `0x7dc268be` | `…::RegisterLightByListContainer` | 4 | 18 |
| 17 | `0x81c` | 100 | `0x90766c16` | `0x7dc268be` | `…::RegisterLightByListContainer` | 4 | 18 |
| 18 | `0x880` | 72 | `0xf0978b86` | `0x0296e56b` | `…::EndRegisterLightAndBeginRegisterPrimitive` | 2 | 19,20 |
| 19 | `0x8c8` | 140 | `0x72820852` | `0x2eb0d468` | — | 5 | 25,26,21,22,23,27,24 |
| 20 | `0x954` | 140 | `0x0d34f6e8` | `0x2eb0d468` | — | 5 | 26,24,25,23,21,22,27 |
| 21 | `0x9e0` | 136 | `0xe6352a4a` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 22 | `0xa68` | 136 | `0x14eddafc` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 23 | `0xaf0` | 136 | `0x6074b288` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 24 | `0xb78` | 136 | `0xdab43ac6` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 25 | `0xc00` | 136 | `0x9d9476a7` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 26 | `0xc88` | 136 | `0x2354ee69` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 27 | `0xd10` | 136 | `0x925404e0` | `0x8b983e31` | `…::RegisterScenePlaceableByListContainer` | 6 | 28,29 |
| 28 | `0xd98` | 116 | `0xda316eeb` | `0xf04e6101` | — | 5 | 30 |
| 29 | `0xe0c` | 116 | `0x93e31001` | `0xf04e6101` | — | 5 | 30 |
| 30 | `0xe80` | 36 | `0x3dfd1083` | `0x4ca4c271` | `…::System::Empty` | 0 | 31 |
| 31 | `0xea4` | 84 | `0x4fcec709` | `0x80d359ae` | `…::View::3D::EndRegisterPrimitive` | 3 | 32 |
| 32 | `0xef8` | 36 | `0x4b9285fb` | `0x30340faf` | `…::View::CommitToNextRender` | 0 | 0 |

`…` = prefijo `TypeInfo::TaskNode::`. Los 33 `id` y los `h1` sin nombre no
están en ningún diccionario del repo ni de los refs (`evidencia/sondeo8`,
§9).

## 6. El grafo (58 aristas)

```
00 → 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11
                                                          ├→ 12 13 14 15 16 17 ─┐
              (fan-in de 6)                             18 ← ─ ─ ─ ─ ─ ─ ─ ─ ─┘
18 → 19, 20
19 → 25 26 21 22 23 27 24      (los mismos 7, en este orden)
20 → 26 24 25 23 21 22 27      (los mismos 7, en otro orden)
21..27 → 28, 29                (cada uno a los dos)
28 → 30 ← 29
30 → 31 → 32 → 00             (cierre del ciclo de frame)
```

- **Sin padres**: ninguno (el ciclo los cubre a todos).
- **Con más de un padre**: 18, 21-30.
- Los dos nodos «fantasma» `19/20` comparten exactamente los mismos 7 hijos
  que `21..27`, en distinto orden; `19/20` y `28/29` emparejan por máscara
  (`0xffff0041` vs `0xffff0021`) y por `ListContainer` (`0xe65d70ae` /
  `0xc82dd3aa`) `[MEDIDO]` (`evidencia/sondeo9_grafo.txt`).

## 7. Resolución de hashes (catálogo y `kidsobjdb`)

`evidencia/sondeo10_resolver.txt`, 123 candidatos (33 `id` + 19 `h1` distintos
+ 71 valores de propiedades):

| dónde | resultado |
|---|---|
| `kidstypeinfodb.yml` (Paso 0) | **26/33** nodos con nombre (15 `h1` distintos); 10 hashes de propiedad sin nombre |
| catálogo `pkp catalog` (2.043 entidades) | **0/123** (0 ids, 0 h1, 0 valores) |
| `kidsobjdb`, 2.636 de 4.144 bases legibles (353.905 registros) | **1/123**: `0xe1b6a687` (valor de `ViewObjectNameHash`) es un registro de `type_hash 0x97af26fd` = `TypeInfo::Object::3D::View` |
| presencia en crudo en las 4.144 bases | 65/123 aparecen como bytes (casi todos en la base mayor, como **valores de pares**: referencias, no registros); **57 no están en ninguna base** (los 33 `id`, los 19 `h1` y 5 valores) |

Límite declarado: **1.508 bases** las rechaza el lector estricto de
`pokopia/objdb.py` (1.281 con `size` de registro no múltiplo de 4 — el propio
`pokopia/catalog.py` mide tamaños 37 y 381, así que la regla `%4` es del
`kidsobjdb` «de pares», no de todo `_DOK0000` —, 206 con pares que se salen,
11 con registro `RDOK0000`, 10 con cola). `RDOK0000` ya lo conocen
`pokopia/catalog.py` (`DOK_RECORD_MAGICS`) y `tools/cruce_objdb_catalogo.py`;
RDBExplorer lo documenta como *Koei Object Database Record*
(`KidsObjDbConstants.cs`). **Los resultados de «confirmado como id» cubren
las 2.636 bases legibles; en las otras, el crudo no distingue id de valor de
par.** Arreglar el lector para `RDOK` es otra tarjeta.

## 8. Hipótesis por nodo (con confianza)

| nodo(s) | hipótesis | confianza |
|---|---|---|
| 01, 04-18, 21-27, 30-32 (26) | lo que dice su nombre `TypeInfo::TaskNode::*`: sincronía de frame, behaviors, física, scripts, placeables, luces, primitivas, commit de render | **alta** (nombre en el YAML del juego) |
| 00 | marcador de arranque de frame: el ciclo entra por él (`32 → 00 → 01`) y es el único con `h1 = 0` | media (estructura) / baja (significado) |
| 02 | paso intermedio sin propiedades entre `FrameSync` y el callback | baja |
| 03 | nodo que invoca una función: su única propiedad es `FunctionHash = 0x8d9a712f` (el hash no está en ningún diccionario) | media-baja |
| 19, 20 | `BeginRegisterPrimitive` en dos variantes de grupo de render: van justo tras `EndRegisterLightAndBeginRegisterPrimitive` (18) y antes de los 7 `RegisterScenePlaceable`; `Opaque/Alpha/ShadowTargetViewMask` = `0xffff0041` / `0xffff0021` | media |
| 28, 29 | cierre simétrico de cada grupo (mismas máscaras y `ListContainer` que 19/20) antes de `System::Empty` (30) | media |

Los 4 `h1` sin nombre (`0x9552cd99`, `0xc1e6200a`, `0x2eb0d468`,
`0xf04e6101`) no aparecen en `kidstypeinfodb.yml` ni en ningún dict de los
refs: o el YAML es de otra versión del motor, o son tipos generados en
runtime. **No se inventan nombres.**

## 9. Paso 0: qué existía ya (y por qué hizo falta lo propio)

Clonados en `build/refs/` el 11-nov-2026 (commit y licencia del clone):

| repo | fichero / clase | qué implementa | licencia |
|---|---|---|---|
| [umin135/Kissaki](https://github.com/umin135/Kissaki) `91343b1` | `KissakiViewerApp/Core/Formats/KtidExtension.cs` (`static class KtidExtension`) | mapa ktid → extensión: `[0x1FDCAA40] = ".kidstask", // TaskGraphFile`. **No parsea el payload** | GPL-3.0 |
| ídem | `Core/Formats/KatanaCommonNames.cs` | constantes: `[0xbd13a52eu] = "TechPreview.kidstask"`, `[0xaceaddecu] = "TechPreview.kidstask.name"` | GPL-3.0 |
| ídem | `res/dict_rdb_names/*.csv` | diccionario hash→nombre de fichero; de nuestros 225 hashes solo casa `0x22704ebb` → `TechPreview.kidstask.kbt.ndb.name` (`evidencia/sondeo8`) | GPL-3.0 |
| [berichan/PokoHex](https://github.com/berichan/PokoHex) `e2f7089` | `PokoHex.Parsing/GameArchive.cs` | lector del contenedor (la referencia que ya citaba `.hermes.md`); sin `kidstask`/`_TGK`/`INGK` | GPL-3.0 |
| [MrIkso/RDBExplorer](https://github.com/MrIkso/RDBExplorer) `22e72d8` | `Core/Formats/ObjectDatabaseFile/KidsObjDbConstants.cs` | firmas `IDOK` = *Koei Object Database Index* y `RDOK` = *Koei Object Database Record* (§7) | MIT |
| ídem | `Databases/kidstypeinfodb.yml`, `rdb_names.csv`, `all_properties.csv` | volcados RDB: **cero** cobertura de `kidstask`; el YAML de tipos es copia idéntica al de fdata_dump (diff sin cambios) | MIT |
| [DeathChaos25/fdata_dump](https://github.com/DeathChaos25/fdata_dump) `7690d0c` | `kidstypeinfodb.yml` | **el diccionario de nombres**: `FullName`/`Hash` (1.374 tipos) y `LocalName`/`Hash` (3.583 propiedades). Sin parser `_TGK`/`INGK` en su C# | GPL-3.0 |
| ídem | `rdb_common.csv` | `bd13a52e,TechPreview.kidstask` / `aceaddec,TechPreview.kidstask.name` | GPL-3.0 |
| [umin135/KashiraModManager](https://github.com/umin135/KashiraModManager) `28e8f7f` | — | sin `kidstask`/`_TGK`/`TaskGraph` en todo el repo (y sin fichero LICENSE en el clone) | — |
| [eArmada8/yumia_fdata_tools](https://github.com/eArmada8/yumia_fdata_tools) `9d8dc1f` | `yumia_mod_lib.py` línea 104 | solo el mapa ktid→nombre (`0x1fdcaa40: "kidstask"`); sin parser | GPL-3.0 |

**Conclusión del Paso 0**: nadie publica un lector de `_TGK0000`/`INGK0000`.
Lo que sí hay —y se reutiliza— es el YAML de nombres de fdata_dump (leído en
runtime, sin copiar datos al repo) y las firmas IDOK/RDOK ya conocidas del
propio kit. Por eso las sondas propias (`sondeo1`…`sondeo10`) fueron
necesarias; su evidencia está en `informes/t_df5ad471/evidencia/`.

## 10. Reproducción

```bash
# 1) extraer (solo lectura del dump)
python pkp.py fdata extract "$PKP_ROMFS/motor_asset_re/KIDS_PLATFORM_OUNCE/0x38f972af.fdata" \
    --type kidstask --out build/kidstask

# 2) el grafo (el comando del criterio de exito)
python pkp.py kidstask

# 3) sondas del informe (salidas ya guardadas en evidencia/)
python informes/t_df5ad471/probes/sondeo9_grafo.py
PKP_ROMFS=<romfs> python informes/t_df5ad471/probes/sondeo10_resolver.py

# 4) suite (CPython 3.11 y zlib 1.3.2, los declarados en pyproject.toml)
python run-tests.py
#    -> 721 passed, 19 skipped  (2026-11-11, con PKP_ROMFS exportado)
```

## 11. Límites y cabos sueltos

- **Solo lectura**: no se escribe el dump, no se toca el save, no se lanza ni
  se cierra el juego.
- `campo_0x18` (=0) y el significado preciso de `campo_0x14` quedan como
  `[HIPÓTESIS]` (§3).
- 4 `h1` y 10 hashes de propiedad sin nombre (§8).
- 1.508 bases `kidsobjdb` sin leer por el lector estricto (§7) — tarjeta
  aparte para `RDOK`.
- `docs/VM-MUD-Y-SCRIPTS.md` §8 sigue diciendo «no se ha interpretado más»
  del `kidstask`: queda desactualizado respecto a este documento.
