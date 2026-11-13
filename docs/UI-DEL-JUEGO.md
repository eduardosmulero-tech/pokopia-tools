# La interfaz del juego es dato — inventario de pantallas reutilizables y qué es `srsa`

**Tarjeta:** `t_f70450e2` · **Fecha:** 2026-11-11 · **Autor:** worker
**Alcance:** solo medición sobre el dump en `rb`. Sin desensamblaje, sin lanzar el juego, save
intocado, nada escrito fuera de `build/`, `informes/` y `local-no-abrir/`.
**Norma de contenido:** los identificadores de interfaz (`0400_screen_craft`, `0000_btn_…`) se citan
como lo que son — nombres técnicos de recursos, igual que ya se hicieron en
`docs/RECETAS-DE-CRAFTEO.md` §10. Ningún texto, descripción ni objeto del juego se nombra aquí
(`docs/NORMA-CONTENIDO-Y-PUBLICACION.md` §1).

---

## 0 · Veredicto en una línea

**Dato en la definición, código en el comportamiento.** Todo lo que compone una pantalla —nombre,
orden, sprites, texturas, clips de transición— vive en los `.fdata` como dato legible; **ni un hash
ni un nombre de pantalla está compilado en el ejecutable** (0/50 con controles de azar al lado), y
los scripts `kscl` no llevan bytecode ni callbacks. Qué acción abre qué pantalla es comportamiento de
`game.dll`: **medirlo exige desensamblaje y aquí se para** (§9, con la opción).

Para la duda que abrió la tarjeta: el juego **trae interfaces** —**50 pantallas nombradas, 284 piezas
de interfaz, 9.112 sprites con nombre**— y la parte de arte/texto de esas interfaces **se puede
reutilizar sin tocar código** (§8). Crear una pantalla *desde cero* sigue en el eje E-8 y hoy es la
opción cara: no hay escritor de escenas (§3) ni enchufe medido de apertura (§9).

---

## 1 · Cómo se midió

Todo con las herramientas del kit sobre el dump del build **655360** (juego 2.0.1a). Las sondas están
versionadas en `informes/t_f70450e2/sondas/` y su salida literal en
`informes/t_f70450e2/evidencia/`:

| Qué | Sonda / comando | Evidencia |
|---|---|---|
| Magia de `srsa`, censo de ids, cadenas UI de `kscl`, hashes en `kscl` | `probe1.py srsa/ids/kscl-ui/hashlink/maquinas` | `sonda-01.txt` |
| Anatomía y censo de `texinfo`, ids en otros tipos, las 6 máquinas | `probe1.py texinfo`, `probe2.py estructura/censo`, `probe3.py ids-en/maquinas` | `sonda-02-03.txt` |
| Invariante, vecindario, control de pareo, índice de textura, desglose `kscl` | `probe9/10/12/13/15/16.py` | `sonda-04.txt` |
| Enlaces `texinfo`↔`kscl`↔`g1t` por nombre/hash, extensiones | `probe5/6/7.py` | `sonda-05.txt` |
| Censo `g1t`, catálogo de máquinas, censo del objdb | `pkp tex stat`, `pkp catalog find machine`, `pkp objdb stat` | `sonda-06-censos.txt` |
| Pareo por `name_hash` (negativo) | `probe2.py enlace` | `sonda-07-enlace.txt` |
| Registros objdb de máquina y de pantalla (negativo) | `probe4.py maquinas/pantallas` | `sonda-08-objdb.txt` |
| Hashes y nombres de interfaz en el ejecutable, con controles | `probe8.py` (reutiliza `tools/hashes_en_binario.py`) | `sonda-09-nso.txt` |
| Agujas de UI dentro de los 403 `srsa` (negativo) | `probe17.py` | `sonda-10-srsa-ui.txt` |

---

## 2 · `srsa`: es audio, no interfaz — cae el candidato de la tarjeta

La tarjeta lo planteaba como «403 ficheros, 199 MB, sin identificar». Ya está identificado y aquí se
re-verifica la cabecera:

```
$ python informes/t_f70450e2/sondas/probe1.py srsa -n 3
srsa #0 0x05d525ae.fdata @0x271517E0 rawSize=198624 magic=b'ASRS' head=4153525300000000e007030000000000
srsa #1 0x05d525ae.fdata @0x2717DBB0 rawSize=200224 magic=b'ASRS' ...
srsa #2 0x05d525ae.fdata @0x271AA2B0 rawSize=202224 magic=b'ASRS' ...
```

- Magia `ASRS` = banco de sonido Koei Tecmo (codec `ASRS`/`KTSR`, verificado externamente con
  `vgmstream` r2168): **403 bancos, 199.492.064 B** descomprimidos, `type_ktid 0xBBD39F2D`.
  Formato campo a campo en `docs/AUDIO-KTSR.md`; 19.297 streams dentro.
- **Nada de interfaz**: barrido de los **403 bancos / 199.492.064 B** con8 agujas de UI
  (`_screen_`, `parts_`, `icon_`, `btn_`, `_hud`, `balloon`, `cursor`, `dialog`) y con los **50
  ids de pantalla**: **0 y 0** (`sonda-10-srsa-ui.txt`). El recuento además cuadra exacto con
  `docs/AUDIO-KTSR.md` (403 / 199.492.064 B).

**Veredicto de `srsa`: audio puro. El mapa no cambia.**

---

## 3 · `kscl`: escena, no bytecode — cae el candidato nº 1

La tarjeta los describía como «361 ficheros, bytecode `LCSK2600DA`». Medido en
`docs/VM-MUD-Y-SCRIPTS.md` (361 ficheros leídos enteros) y reforzado aquí:

- **0 de 361** llevan nombre de binding y **0** bytecode identificable: son un grafo de nodos con
  nombres de assets y de animaciones (puesta en escena), no lógica.
- **0 de 371** ids de interfaz aparecen en ningún `kscl` como **hash** de4 B
  (`sonda-01.txt`: `ids cuyo hash aparece en algún kscl: 0 / 371`) — los scripts referencian por
  **cadena literal**, no por hash.
- Como cadena literal, los ids de interfaz aparecen **229 de 371** en los `kscl` (`sonda-04.txt`):

| segmento | en `kscl` | total |
|---|---|---|
| `parts` | **210** | 284 |
| `screen` | **4** | 50 |
| `item` | **8** | 10 |
| `area` | **2** | 4 |
| `log` / `mrk` | 1 / 1 | 2 / 1 |
| resto con segmento (`0216`, `0217`, `canvas`, `0000`, `0200`, `0300`, `0382`) | 3 | 9 |
| sin guion bajo | 0 | 11 |

- Tokens de UI en los pools de cadena de los361 `kscl` (`sonda-01.txt`, 2.838 coincidencias):
  `parts` 1.660 · `icon` 433 · `list` 162 · `cursor` 148 · `window` 112 · `tab` 67 · `dialog` 54 ·
  `balloon` 43 · `talk` 40 · `frame` 34 · `menu` 20 · `screen` 18 · `hud` 18 · `message` 14 ·
  `label` 11 · `button` 4. Hay además estilos de botón/texto reales, p. ej.
  `Window_0000_btn_focus_common_txt_36pt` (`local-no-abrir/ui/kscl-ui.jsonl`).
- Las 18 cadenas con «screen» reparten así (`sonda-04.txt`): **6** con prefijo `CL_`
  (4 de ellas contienen exactamente un id de la tabla, p. ej. `CL_0250_screen_talk`), **6** son clips
  de transición `In_/Loop_/Out_screen_*` (la animación de abrir/cerrar pantalla está definida **en
  dato**), y 6 sueltas (`off_screen`, `move_off_screen`, …).
- **0** cadenas con extensión de fichero (`.g1t`, `.g1m`, …) en todo `kscl` (`sonda-05.txt`), y
  hashear sus7.081 cadenas con las14 extensiones conocidas (99.134 hashes) contra el índice da
  **3 aciertos, con 2,3 esperados por azar** — los `kscl` no nombran ficheros.
- **0 callbacks, 0 nombres de función** en todo el tipo (medido en `docs/VM-MUD-Y-SCRIPTS.md` §3–4).

**Conclusión de §3: la pantalla, sus piezas y sus animaciones de transición son dato; el cable que
las abre es código.** Detalle: no hay escritor `LCSK` ni público ni del kit —modificar una escena hoy
no es una vía soportada (`docs/VM-MUD-Y-SCRIPTS.md`, primera línea).

---

## 4 · `texinfo`: la capa de nombres de los sprites (y su estructura medida)

**`texinfo` es la tabla de sprites con nombre que la tarjeta buscaba** — pero nombra *sprites*, no
*pantallas*.

**Estructura** (`sonda-02-03.txt`, entrada `0x00011c54.fdata @0x855A60`, 1.356 B):

```
+0x00  u32   count              nº de registros
+0x04  count × 104 B:
         char[64] nombre         NUL-terminado (p. ej. "0100_prt_copyright")
         u32     textura         índice de textura dentro del g1t (0-based)
         8 × f32 datos de UV     en la entrada medida: todos en [0,1], topan en 1.0
         u32     1               constante en los 470 registros de esa entrada
```

- **Invariante verificado en 4.341/4.341**: `tamaño == 4 + count × 104`, y todos los nombres con
  NUL dentro de su campo de 64 B (`sonda-04.txt`, `probe9`).
- Cifras: **4.341 entradas, 965.012 B en total**, min 108, mediana 108, máx 138.636; **9.112
  registros** (sprites con nombre) en total.

**Pareo con la textura: el `texinfo` describe al `g1t` inmediatamente anterior.** Tres medidas
(`sonda-04.txt`):

1. Adyacencia: **4.334 de 4.341** (99,8 %) tienen un `g1t` justo delante; **4.328** están encajados
   entre dos `g1t`.
2. Prueba decisiva — `máx(indice de textura)+1 == nº de texturas del g1t previo`:
   **4.334 de 4.334 (100 %)**, 0 fallos (`probe15`).
3. Control: la igualdad ingenua `regiones == texturas del previo` da 99,03 % contra **0,02 %**
   comparando con el `g1t` de dos posiciones atrás (`probe12`); ojo, ese99 % lo pega el caso trivial
   `1 × 1` (4.290 pares), por eso manda la prueba del índice.

El enlace **no** es por `name_hash`: `probe2.py enlace` da **0** coincidencias entre el `name_hash`
de un `texinfo` y el de cualquier `g1t`/`kscl`/`srsa`/`kidsobjdb`/`g1m` (`sonda-07-enlace.txt`) — el
pareo es **posicional** dentro del `.fdata`.

**Familias** (primer trozo del nombre del registro 0, `sonda-04.txt`):

| familia | entradas | regiones | qué pinta |
|---|---|---|---|
| `item_…` | 1.613 | 3.229 | iconos de objeto |
| `icon_…` | 1.257 | 2.692 | iconos de UI |
| `still_…` | 847 | 847 | imágenes fijas |
| `seal_…` | 410 | 410 | sellos |
| `shop_…` / `food_…` | 145 / 36 | 145 / 36 | tienda / comida |
| bloques `NNNN_` | **29** | 1.509 | piezas por número de pantalla (`0000_btn_common_0`, `8000_txt_…`) |
| resto (`furniture`, `habitat`, `common`) | 4 | 244 | suelto |

- **`texinfo` no contiene ni un nombre de pantalla: 0 de 50** (`sonda-02-03.txt`).
  De los 371 ids, solo **3** aparecen como cadena en algún `texinfo`.
- **28 de 4.341** nombres de `texinfo` sí aparecen literalmente en algún `kscl` (familias `8000` 7,
  `0000` 4, `icon` 4, bloques `0100`–`0900` …) — ese es el enlace cadena que pedía la tarjeta.

**Respuesta a la pregunta de `texinfo`:** es la puerta a **reetiquetar y reordenar sprites**
renombrando registros y moviendo UVs, no a reetiquetar pantallas enteras. Los bloques `NNNN_`
comparten numeración con los bloques de pantalla (§5), así que agrupan piezas *por* pantalla, pero el
nombre de la pantalla vive en el `kidsobjdb`, no aquí.

---

## 5 · Pantallas: 50 identificadores, dónde viven y a quién referencian

**Dónde:** tabla de identificadores de interfaz dentro de la entrada `@0x11E38D0` de
`motor_asset_re/KIDS_PLATFORM_OUNCE/0x2943e4da.fdata`, tramo `+0x15076` (localización de
`docs/BARRIDO-CATALOGOS.md` §2; aquí se re-extrae y sale la misma tabla). Con mi regex laxa salen
**371 cadenas**; los segmentos que se usan aquí cuadran **exactos** con el barrido oficial —
`parts` 284 · `screen` **48** · `item` 10 · `area` 4 · `log` 2 — y la diferencia de10 está en las
cadenas sueltas del final del tramo (23 por mi regex frente a13 con sus criterios; ninguna cifra de
este informe depende de ellas). Contando también las dos formas raras `02_0300_…` y
`03_0200_…`, las que contienen `_screen_` son **50**.

**Las 50 pantallas** (identificador técnico; volcado completo en
`local-no-abrir/ui/ids-interfaz.jsonl`):

```
0000_screen_chip_color_pattern_m_s_ss   0000_screen_general_purpose      0000_screen_input
0001_screen_load                        0001_screen_load_simple          0001_screen_load_takarajima
0002_screen_notice                      0005_screen_filter_sort
0020_screen_settings_common             0020_screen_settings_dex
0200_screen_hud                         0200_screen_inventory_00         0200_screen_list
0200_screen_report                      0205_screen_minigame
0230_screen_frame_filter                0230_screen_photo                0250_screen_talk
0270_screen_processed                   02_0300_screen_eshop
0300_screen_collection_camera           0300_screen_seamless_list        03_0200_screen_win_passcode
0310_screen_dex_top                     0336_screen_pokemondetail        0341_screen_skilllist
0342_screen_wheel_menu                  0360_screen_tutorial_base        0360_screen_tutorial_base_v2
0400_screen_craft                       0400_screen_dyeing_list          0410_screen_build
0440_screen_dyeing                      0500_screen_pokecen              0501_screen_pokesen_list_hanyou
0505_screen_areadetail_v2               0506_screen_devlv                0507_screen_pickup
0508_screen_stamp                       0509_screen_okurimono            0510_screen_gate_open
0540_screen_shop                        0570_screen_rotom_audio          0580_screen_certificate
0600_screen_characre                    0602_screen_characre_settings    0700_screen_dungeon
0800_screen_online                      0810_screen_load                 0900_screen_staffroll
```

**A quién referencian y quién las referencia** (todas las medidas en este trabajo):

| Cruce | Resultado | Evidencia |
|---|---|---|
| Pantalla como cadena en `kscl` | **4/50** (las otras46 no se nombran en escenas) | `sonda-04.txt` |
| Pantalla como hash en `kscl` | **0/50** | `sonda-01.txt` |
| Pantalla como cadena en `texinfo` | **0/50** | `sonda-02-03.txt` |
| Pantalla como hash en el objdb (valor de par, 294.939 registros) | **0/50** | `sonda-08-objdb.txt` |
| Pantalla como hash o nombre ASCII en el ejecutable (`text`/`rodata`/`data`) | **0/50** y **0** nombres | `sonda-09-nso.txt` |

Control del barrido en el binario (mismo método y semilla que `tools/hashes_en_binario.py`, NSO
`updates/655360/exefs/main`, md5 `216dd93e934fe47abaa44de4323788f0`, build `76a489f3bd3642fa…`,
segmentos con `sha256` de cabecera OK): `random` 11/10.000 en `text` (esperado 15,76), 7 en `rodata`
(6,66), 0 en `data` (0,77). **Los hashes de pantalla no están compilados**: el juego los calcula en
ejecución o los lee del dato — coherente con `docs/HASHES-DE-ENTIDAD-EN-EL-BINARIO.md` (0 de 88
hashes de entidad en el binario).

**Qué sí se mueve en dato:** las transiciones de pantalla (`In_/Loop_/Out_screen_*`) y las piezas
(210/284 `parts` nombrados en `kscl`) están en escena/animación — dato tocable *en teoría*, pero sin
escritor `LCSK` (§3).

---

## 6 · Las máquinas: ninguna pantalla propia, medido

Las 6 entidades de máquina del catálogo (`pkp catalog find machine`, `sonda-06-censos.txt`), con su
hash KT:

```
0xA676C31E  BP02377_A00_PUNCHI_MACHINE00_00      0xFAD160F3  BP02621_A06_BABBLE_MACHINE00_00
0x4F920AD8  BP02579_A06_GHOST_MACHINE00_00       0x38ADCA75  BP02622_A06_FLAME_MACHINE00_00
0xC5E24D39  BP02623_A06_FUBUKI_MACHINE00_00      0x6F3DAD19  BP02752_A08_SMOKE_MACHINE00_00
```

Cruces hechos con las6 (nombre literal y hash u32 LE):

| Dónde se busca | Resultado |
|---|---|
| Tabla de ids de interfaz (50 pantallas + 284 parts) | **0** — ninguna pantalla ni pieza nombrada por máquina |
| Identificador completo o sufijo de máquina en `kscl` / `texinfo` | **0 / 0** |
| Registros del objdb mayor (50.152.112 B, 294.939 registros) | **0 registros** contienen su hash (`sonda-08-objdb.txt`) |
| Ejecutable (`text`/`rodata`/`data`, 4 rejillas) | **0/6** (esperado 0,01 en `text`) |
| Catálogo (donde sí están) | **6/6**, nombre + hash juntos (`sonda-02-03.txt`) |

Notas de la fila de ids: los 6 identificadores dan **0** en `ids-interfaz.jsonl`, **0** en
`texinfo-nombres.txt` y **0** en `kscl-ui.jsonl` (`sonda-10`, greps al pie); la palabra suelta
`flame` sí aparece en 7 widgets de efecto (`0500_parts_balance_flame`) — vocabulario visual, no
identificador de máquina.

**Veredicto: ninguna de las 6 máquinas tiene pantalla propia en el dato.** Si en el juego una
máquina muestra UI, es por pantallas genéricas (`0200_screen_hud`, `0250_screen_talk`,
`0205_screen_minigame`…) y ese enlace **no está en lo medido**: el puente identificador→registro del
objdb sigue abierto (`docs/NOMBRES-DE-FICHERO-EN-RDB.md` §5.2, «siguiente paso natural, tarjeta
aparte»), y el save no se ha abierto. Sin ese puente no se puede decir cuál, y no se inventa.

---

## 7 · Inventario de texturas: qué hay para reutilizar

**Censo `g1t`** (`pkp tex stat`, `sonda-06-censos.txt`): **14.412 entradas `g1t`, 14.713 texturas, 0
ilegibles**; versiones `0600` 13.873 · `1600` 527 · `0500` 10 · `2600` 2; formatos dxt1 4.183 · dxt5
3.527 · bc7 3.235 · bc5 2.366 · bc4 908 · resto <500; **escribibles 14.691 de 14.713 (99,85 %)**.
Peso previo medido: `g1t` 6,30 GB (`docs/RECETAS-DE-CRAFTEO.md` §1).

**Cuántos `g1t` tienen nombre:** con el pareo del §4, **4.341 de 14.412 (30,1 %)** tienen su tabla
`texinfo` — esos son los identificables a distancia; los otros 10.071 solo se tocan por geometría.

**Agrupación por `.fdata`** (`sonda-04.txt`, `probe10`): el `0x00011c54.fdata` concentra 3.919 `g1t`
y 3.602 `texinfo` (99,8 % adyacentes); `0x0017d6e2` 726/703; `0x00176283` 51/35. El resto de ficheros
tiene `g1t` sin `texinfo` (p. ej. `0x738d2a35` con 4.510). **Ese es el agrupado natural de sprites:
por `.fdata`, no por pantalla.**

**Candidatas a «UI»** (criterio medido: familia de nombre, no intuición):

- **Iconos: `icon_…` 1.257 atlases / 2.692 regiones.**
- **Piezas por bloque de pantalla: 29 atlases `NNNN_` / 1.509 regiones** en 11 bloques
  (`0000`:4 · `0100`:1 · `0200`:2 · `0300`:3 · `0400`:2 · `0500`:2 · `0600`:1 · `0700`:1 · `0800`:2 ·
  `0900`:1 · `8000`:10). De esos11 bloques, **9 tienen pantalla** (los que no: `0100` y `8000`).
  Contenido típico medido: botones (`0000_btn_common_0`, 7 regiones), textos (`8000_txt_…`,
  `0800_txt_new_craft`), HUD (`0200_base_hud_challenge_flame` dentro de `kscl`), globos
  (`0400_base_balloon_material`).
- **Fondos: `still_…` 847** (1 región c/u) y **`seal_…` 410**.
- **Objeto/escena: `item_…` 1.613, `shop_…` 145, `food_…` 36** — no son UI de pantalla.
- Fuentes: **no hay familia `font`** (0 en `texinfo`, 0 en `kscl`); el texto de UI va como atlas
  (`…_txt_36pt`) y como tabla de cadenas en `LD_C0_R.BIN` (§8).

**Cobertura por bloque de pantalla** (pantallas con atlas `NNNN_` propio en `texinfo`): `0000` (3
pantallas / 4 atlases), `0200` (5/2), `0300` (3/3), `0400` (2/2), `0500` (1/2), `0600` (1/1),
`0700` (1/1), `0800` (1/2), `0900` (1/1). **Los bloques sin atlas propio** (pantallas `0001`,
`0002`, `0005`, `0020`, `0205`, `0230`, `0250`, `0270`, `0310`, `0336`, `0341`, `0342`, `0360`,
`0410`, `0440`, `0501`, `0505`–`0510`, `0540`, `0570`, `0580`, `0602`, `0810`) usan piezas de los
bloques vecinos o `icon_…` genéricos — medido por presencia, no por uso en runtime.

---

## 8 · Qué se puede cambiar sin tocar código, y qué no

### 8.1 Sí, solo dato (vía ya construida en el kit)

| Qué cambiar | Dónde | Vía |
|---|---|---|
| Píxeles de cualquier textura (mismo tamaño) | entradas `g1t` | `pkp tex inject` — round-trip byte a byte medido (`docs/G1T-FORMAT.md`, cabecera) |
| Textos de UI (etiquetas, descripciones) | `LD_C0_R.BIN`, tablas por idioma | kit de contenedor (`#4650` ES / `#4646` EN) |
| Nombre de un sprite, su UV o su índice de textura | entrada `texinfo` | `pkp fdata inject` sobre copia (`docs/ESCRITURA-FDATA.md`) — **estructuralmente igual que cualquier entrada; no se ha probado en concreto en esta tarjeta** |
| Contenido de una entrada entera de `.fdata` (clonar/reemplazar) | cualquier tipo | `pkp fdata inject` + repack con identidad |

Ojo al renombrar: **28 nombres de `texinfo` y 229 ids de interfaz están referenciados como cadena
dentro de `kscl`** — un renombrado rompe esa referencia y el efecto en runtime no está medido sin
ejecutar el juego (aquí no se ejecuta).

### 8.2 No, hoy

- **Comportamiento**: qué hace un botón, qué pantalla abre cada acción. Vive en `game.dll`; los
  hashes no están compilados (§5) y no hay VM de script (§3) → sin desensamblaje no hay medida.
- **Recomponer una escena `kscl`**: no hay escritor (`docs/VM-MUD-Y-SCRIPTS.md`, primera línea).
- **Añadir una pantalla nueva** (eje E-8): haría falta (a) atlas propio `g1t`+`texinfo` — resuelto;
  (b) piezas/escena — sin escritor; (c) el cable que la abre — en el binario. **Hoy es la opción
  cara**; reutilizar una pantalla existente (§5) es la barata.

### 8.3 Reutilizar una pantalla existente, en concreto

Para «usar las interfaces que el juego ya trae» sin código, el camino medido es: elegir de la lista
§5, tocar sus **piezas** (`210` de `284` están ya referenciadas en escena) y su **arte** (`texinfo` +
`g1t`, §7). Lo que no se puede prometer sin ejecutar el juego es el cambio de *asignación*
(pantalla A mostrando el contenido de B): eso es comportamiento (§8.2).

---

## 9 · Parada y reporte: el frente de código exige desensamblaje

La tarjeta ordena parar si un fichero requiere desensamblador. **Se para aquí.**

- Lo que queda por medir: **dónde se decide abrir cada pantalla** (buscador de hashes en runtime,
  dispatch de la UI). Eso está en `updates/655360/exefs/main` (NSO, `text` 41.194.624 B) y solo se
  responde con análisis estático/desensamblaje (Ghidra — el repo ya trae `ghidra_scripts/` — u
  otra herramienta; opcional).
- Opción A (la que pide la tarjeta): **desensamblar `game.dll`/`main`** — requiere aprobación
  explícita; no se monta por iniciativa propia.
- Opción B (más barata, sin desensamblar): seguir el enlace **identificador→registro** del objdb
  (`docs/NOMBRES-DE-FICHERO-EN-RDB.md` §5.2) y, si aparece el puente entidad→pantalla, responder §6
  mejor. Es una tarjeta de datos, no de binario.
- Opción C: sesión en juego (abrir y cerrar el emulador con confirmación de Edu) para observar qué
  pantalla abre cada máquina — sería la única prueba *de comportamiento*, y queda fuera de esta
  tarjeta («sin lanzar el juego»).

---

## 10 · Reproducción

```bash
export PKP_ROMFS="<romfs del update 655360>"
cd <repo>
S=informes/t_f70450e2/sondas; E=informes/t_f70450e2/evidencia

python $S/probe1.py srsa -n 3        # magia ASRS
python $S/probe1.py ids              # tabla de 371 ids (volcado a local-no-abrir/)
python $S/probe1.py kscl-ui          # tokens de UI en los 361 kscl
python $S/probe1.py hashlink         # 0/371 hashes en kscl
python $S/probe2.py estructura --tam 1356   # anatomía texinfo
python $S/probe9.py                  # invariante 4+count*104 en 4341/4341
python $S/probe15.py                 # índice de textura == g1t previo: 4334/4334
python $S/probe16.py                 # desglose de ids en kscl
python $S/probe3.py ids-en; python $S/probe3.py maquinas
python $S/probe4.py maquinas; python $S/probe4.py pantallas   # objdb: 0 y 0
python $S/probe8.py                  # hashes de interfaz en el NSO, con controles
python $S/probe17.py                 # agujas de UI en los 403 srsa: 0 y 0
python pkp.py tex stat "$PKP_ROMFS"  # censo g1t
python pkp.py catalog find machine   # las 6 máquinas
```

Salida literal de todo lo anterior: `informes/t_f70450e2/evidencia/sonda-01…10*.txt`. Volcados con
nombres de recursos: `local-no-abrir/ui/` (fuera del árbol versionado).

---

## 11 · Límites de este informe

- Todo medido sobre el build **655360** (2.0.1a); sin ejecutar el juego, sin escribir en el dump, sin
  abrir el save.
- **Sin desensamblaje**: §9 es la frontera, no una opinión sobre lo que hay detrás.
- El pareo `texinfo`→`g1t` es **posicional** (100 % por índice de textura); no se ha encontrado un
  enlace por `name_hash` (0/…). Los 7 `texinfo` sin `g1t` previo quedan sin parear.
- El bloque `NNNN_` de un sprite agrupa por número de pantalla, pero **el uso real en runtime de
  cada atlas no está observado** — solo presencia.
- «Máquinas sin pantalla propia» es un **negativo medido en 4 frentes** más los greps de
  `sonda-10` (§6), no una prueba de que no muestren UI: falta el enlace entidad→registro
  (opción B, §9).
- Nombres publicados: solo identificadores técnicos de interfaz, según el precedente de
  `docs/RECETAS-DE-CRAFTEO.md` §10 y la orden de la tarjeta («lista de candidatas a reutilizar»).
