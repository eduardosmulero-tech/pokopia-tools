# b3-texto-nuevo — vehículo de la unidad **B3**

**Qué prueba:** un **texto nuevo se muestra donde el juego lo pinta**. Se escribe el marcador
`MOD-TEXT-NUEVO` (inventado, no es contenido del juego) en el bloque de texto del **objeto que ya
elegiste**, el del **hueco 0** de la bolsa, y se escribe en **los cuatro slots con contenido** de ese
bloque, no en dos: así sale se pinte el grupo que se pinte.

**Cadena medida** (2026-11-10, contenedor `358a672d…` / `7e056a09…`):

```
save G00 hueco 0 -> id 63 -> #983 fila 63 -> +34 u16 = 2281 [verified]
                                  -> id de texto = 2281 + 3 = 2284
                                  -> #4650 slots 6*(2284-4) = 13680..13685
```

**Por qué este bloque vale y el de `ejemplos/editar-texto` no:** un bloque **vacío** no lo
referencia nadie, así que el juego no tiene dónde pintarlo. Este está **poblado** y su id sale de la
fila del objeto que llevas en la bolsa, que es la cadena de arriba.

**Qué toca exactamente:** `#4650` (nombres ES), id **2284**, slots **+0, +2, +3 y +5**. Bloque de
**46 B**, `sha256 e300dd4b…cb29`; el mod lo identifica por ese hash, no por el texto, así que no
lleva ni una línea del juego (`docs/MOD-FORMAT.md` §3.1). En `#4650` la máscara de slots con
contenido es `0x2D`: **+1 y +4 están vacíos por diseño** y no se tocan.

## Pasos, en orden

1. **Copia del contenedor** (nunca sobre el dump):
   ```bash
   mkdir -p build/copia
   cp "$PKP_ROMFS/LD_C0_R.BIN" "$PKP_ROMFS/LI_C0_R.IDX" build/copia/
   md5sum build/copia/LD_C0_R.BIN build/copia/LI_C0_R.IDX
   # 358a672d506ce2b0399149ede64a6760  7e056a097f28a62f002ad961a611edf8
   ```
2. **Validar** (0 errores, 0 avisos):
   ```bash
   pkp mod validate ejemplos/b3-texto-nuevo --container build/copia
   ```
3. **Ensayo** (no escribe nada; esto es lo que hay que mirar: cuatro slots y `+10 B`, nada más):
   ```bash
   pkp mod apply ejemplos/b3-texto-nuevo --container build/copia --dry-run
   # tabla #4650: 298584 -> 298594 B
   #   slots totales: 18003 -> 18003; cambios:
   #     slot 13680  11 B -> 14 B
   #     slot 13682  12 B -> 14 B
   #     slot 13683  11 B -> 14 B
   #     slot 13685  12 B -> 14 B
   #   prefijo de texto identico: True
   ```
4. **Aplicar**:
   ```bash
   pkp mod apply ejemplos/b3-texto-nuevo --container build/copia --yes
   ```
   Deja `build/copia/.pkp-backup/<fecha>/` con los dos ficheros e **imprime los dos `cp` de vuelta**.
5. **Servir esa copia al juego** por el overlay (`DM_ROMFS_OVERLAY`, tarjeta `t_ae85bfab`) y
   arrancar. El juego lo cierras tú.
6. **Qué tienes que ver:** en la bolsa, el nombre del objeto que ya elegiste (hueco 0) pone
   **`MOD-TEXT-NUEVO`**. Si pone `MOD-TEXT-NUEVO` en la lista y en la ficha, B3 es **sí**.
7. **Cómo se quita:**
   ```bash
   # los dos cp que imprimió el paso 4, en este orden:
   cp build/copia/.pkp-backup/<fecha>/LD_C0_R.BIN build/copia/LD_C0_R.BIN
   cp build/copia/.pkp-backup/<fecha>/LI_C0_R.IDX build/copia/LI_C0_R.IDX
   md5sum build/copia/LD_C0_R.BIN   # 358a672d506ce2b0399149ede64a6760
   ```
   O simplemente deja de servir la copia por el overlay. El dump no se ha tocado en ningún paso.

## Dos cosas dichas por adelantado

* **No lo apliques encima de otro mod.** Este kit no apila mods sobre una copia ya modificada: el
  `container_md5` que declara el segundo ya no cuadra y lo rechaza (medido con `a1-texto-hueco0`
  aplicado antes: `exit 1`). Cada vehículo, sobre copia prístina.
* **`a1-texto-hueco0` y este escriben en el mismo objeto.** A1 escribe dos slots (0 y 2); B3 escribe
  los cuatro. Si alguna vez hay que elegir, B3 es el que cubre el caso de que el juego pinte el
  segundo grupo. Son pruebas distintas: A1 dice «se puede cambiar un texto que se lee»; B3 dice
  «un texto mío aparece donde el juego lo pinta, sin depender de qué grupo lea».

**Coste:** 10 minutos, sin build y sin abrir el juego hasta el paso 5.
