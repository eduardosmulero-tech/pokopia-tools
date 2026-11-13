# a1-texto-hueco0 — vehículo de la unidad **A1**

**Qué prueba:** un **texto que se lee en pantalla** se puede cambiar por otro mío. Se escribe el
marcador `MOD-PRUEBA` (sin contenido del juego) en el texto que pinta el objeto del **hueco 0** del
inventario.

**Cadena medida** (2026-11-10, contenedor `358a672d…` / `7e056a09…`):

```
save G00 hueco 0 -> id 63 -> #983 fila 63 -> +34 u16 = 2281 [verified]
                                  -> id de texto = 2281 + 3 = 2284
                                  -> #4650 slots 6*(2284-4) = 13680..13685
```

**Qué toca exactamente:** `#4650` (nombres ES), id **2284**, slots **0** (singular) y **2** (plural).
Bloque de **46 B**, `sha256 e300dd4b…cb29`; el mod lo identifica por ese hash, no por el texto, así que
no lleva ni una línea del juego (`docs/MOD-FORMAT.md` §3.1). Los slots 1, 3, 4 y 5 quedan como están.

**Cómo se aplica** (sobre copia del contenedor, nunca sobre el dump):

```bash
mkdir -p build/copia && cp "$PKP_ROMFS/LD_C0_R.BIN" "$PKP_ROMFS/LI_C0_R.IDX" build/copia/
pkp mod validate ejemplos/a1-texto-hueco0 --container build/copia    # 0 errores, 0 avisos
pkp mod apply    ejemplos/a1-texto-hueco0 --container build/copia --dry-run   # ensayo
pkp mod apply    ejemplos/a1-texto-hueco0 --container build/copia --yes
```

**Cómo se revierte:** `apply --yes` deja `build/copia/.pkp-backup/<fecha>/` con los dos ficheros e
imprime los `cp` exactos. Ejecutarlos y el contenedor vuelve a `LD_C0_R.BIN 358a672d506ce2b0399149ede64a6760`.

**Riesgo declarado (medido, no supuesto):** los slots **3 y 5** del bloque tienen el mismo contenido
que 0 y 2 (mismo `sha256` por slot: `64aafca717d6` y `f49d29cca914`), es decir, el bloque son dos grupos
de tres. Este vehículo escribe el **primer** grupo, como se decidió. Si el juego pinta el segundo, el
nombre en pantalla no cambia y el arreglo es un tercer y cuarto `text[]` sobre los slots 3 y 5 con el
**mismo** `expect_sha256`. Saber cuál lee el juego requiere una partida, no una medición estática.
