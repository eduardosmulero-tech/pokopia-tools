# a7-cantidad-hueco0 — vehículo de la unidad **A7**

**Qué prueba:** un valor del **save** (la cantidad de un objeto del inventario) se puede cambiar y se
ve en el juego. Hueco **0**, cantidad **22 → 99**, sobre **copia**.

**No es un `mod.json`** y no puede serlo: el formato de mod escribe en el contenedor
(`LD_C0_R.BIN`/`LI_C0_R.IDX`), no en el save. Lo dice `docs/MOD-FORMAT.md` §5 («What `apply` does not
do: … write to the save»). El vehículo de una unidad del save es **el comando**, y su validación es el
`--dry-run`. Los datos del cambio están en `vehiculo.json`.

```bash
COPIA=<copia del save>/A-save

# 1) ensayo: no escribe nada (md5 igual antes y después)
pkp save write --save "$COPIA" --page G00 --slot 0 --count 99 --dry-run

# 2) escritura de verdad, con copia de seguridad automática
pkp save write --save "$COPIA" --page G00 --slot 0 --count 99 --yes

# 3) ver lo que hay ahora
pkp save read  --save "$COPIA" --page G00        # hueco 0 -> cant 99

# 4) deshacer (el paso 2 imprime la ruta exacta del manifiesto)
pkp save undo <manifiesto> --yes                 # md5 vuelve al de partida
```

**Nunca** se apunta a la partida real del emulador o del port nativo: `save write` la rechaza sin
`--allow-live-save`, y ese flag no se usa aquí.
