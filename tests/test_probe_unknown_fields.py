"""Estadistica de los 15 campos `unknown` de `#983`: las piezas que no necesitan dump.

Todo sintetico. Lo que se fija aqui son **las dos trampas** que costaron medidas en la
tarjeta `t_a809f6ef`:

* la tasa de coincidencia ponderada por **masa** no mide relacion entre columnas (un campo
  con dos valores dominantes «acierta» el 92 % contra casi cualquier cosa): la buena es la
  contada por **valores distintos**, y `independence_baseline` es la que da el azar;
* la constancia de un campo dentro de un grupo hay que compararla con la que produce el azar
  (Σ p_v²), no con un umbral en porcentaje: un campo a cero en el 97 % de las filas es
  «constante» el 97 % de las veces sin decir nada.

Y una tercera, de mantenimiento: el conjunto de campos que analiza la sonda es **15 y no
depende del veredicto**, para que actualizar el estado de un campo (que es lo que hace la
tarjeta) no cambie el alcance del instrumento ni sus salidas.
"""

from __future__ import annotations

import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(RAIZ, "tools", "spec")
for _p in (RAIZ, SPEC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import probe_unknown_fields as probe  # noqa: E402


# --------------------------------------------------------------- estadistica
def test_la_base_de_independencia_suma_el_producto_de_marginales():
    # a y b identicas: P(coincidir) = sum p^2 = 1/4+1/4 = 1/2
    assert probe.independence_baseline([1, 1, 2, 2], [1, 1, 2, 2]) == pytest.approx(0.5)
    # conjuntos disjuntos: no hay valor comun, la base es 0
    assert probe.independence_baseline([1, 1, 2, 2], [3, 3, 4, 4]) == 0.0
    # columnas vacias: 0, no ZeroDivisionError
    assert probe.independence_baseline([], []) == 0.0


def test_el_azar_de_un_campo_casi_todo_cero_es_alto():
    """La trampa de P3: un campo con 97 ceros de 100 es 'constante' el 94 % por azar."""
    casi_cero = [0] * 97 + [1, 2, 3]
    azar = probe.independence_baseline(casi_cero, casi_cero)
    assert azar > 0.94, "con 97 ceros el azar ya da mas del 94 %: un umbral del 80 % no informa"


def test_spearman_detecta_monotonia_y_empates():
    assert probe.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert probe.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    # con todo empatado no hay correlacion definida: 0, no nan
    assert probe.spearman([5, 5, 5], [1, 2, 3]) == 0.0


def test_la_cola_normal_cuadra_con_la_tabla():
    assert probe.normal_two_sided(1.959964) == pytest.approx(0.05, abs=1e-6)
    assert probe.normal_two_sided(0.0) == pytest.approx(1.0, abs=1e-6)
    assert probe.normal_two_sided(-3.0) == pytest.approx(probe.normal_two_sided(3.0))


# ------------------------------------------------------------------- tiling
def test_la_tiling_del_mapa_de_campos_cubre_los_68_bytes_sin_huecos():
    cubierto = bytearray(probe.ROW)
    for off, width, _name, _conf in probe.FIELDS:
        for b in range(off, off + width):
            assert cubierto[b] == 0, "solape en el byte %d" % b
            cubierto[b] = 1
    assert all(cubierto), "hueco en la tiling"
    assert sum(w for _o, w, _n, _c in probe.FIELDS) == probe.ROW == 68


def test_el_alcance_de_la_sonda_son_los_15_campos_y_no_depende_del_veredicto():
    """`+26` esta `measured` en el mapa de campos y sigue en el alcance de la sonda."""
    assert "key_26" in probe.UNKNOWN
    assert len(probe.UNKNOWN) == 15
    # y el mapa de campos importado no se modifica: el cambio es local a la sonda
    from measure_item_row import FIELDS as ORIGINAL
    assert [c for _o, _w, n, c in ORIGINAL if n == "key_26"] == ["measured"]
