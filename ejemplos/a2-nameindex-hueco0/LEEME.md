# a2-nameindex-hueco0 — vehículo de la unidad **A2**

**Qué prueba:** un **valor de una fila** (un número que el juego usa) se puede cambiar y se nota. Se
toca el **campo demostrado** de la tabla de ítems: el `nameIndex`.

**Qué toca exactamente:** `#983`, fila **63**, offset **+34**, tipo `u16`, `expect 2281` → `value 2282`
(`confidence: verified`; `docs/SPEC-NAMES.md` §6.3). La fila 63 es la que resuelve el objeto del hueco 0
del save, así que el cambio se ve sin tocar el inventario: el objeto del hueco 0 pasa a mostrar el
nombre del **siguiente** id de texto.

**Cómo se aplica** (sobre copia del contenedor, nunca sobre el dump):

```bash
mkdir -p build/copia && cp "$PKP_ROMFS/LD_C0_R.BIN" "$PKP_ROMFS/LI_C0_R.IDX" build/copia/
pkp mod validate ejemplos/a2-nameindex-hueco0 --container build/copia    # 0 errores, 0 avisos
pkp mod apply    ejemplos/a2-nameindex-hueco0 --container build/copia --dry-run
pkp mod apply    ejemplos/a2-nameindex-hueco0 --container build/copia --yes
```

El ensayo imprime un único tramo de **1 byte** en el payload (`+4382 = 64 + 68·63 + 34`, `0xe9 → 0xea`):
es el byte bajo del `u16`, y solo ese.

**Cómo se revierte:** `apply --yes` deja `build/copia/.pkp-backup/<fecha>/` e imprime los `cp` exactos;
el contenedor vuelve a `LD_C0_R.BIN 358a672d506ce2b0399149ede64a6760`.

**Orden de la prueba:** va **después** de A7 (decisión de Edu, 2026-11-10). Si A1 está aplicado, A2 lo
pisa funcionalmente (los dos cambian el nombre que se ve del hueco 0 por caminos distintos); se prueban
en partidas separadas para no atribuir el efecto al vehículo equivocado.
