"""Tests negativos del guardian: un guard que nunca ha fallado no es un guard.

Cada test construye un arbol temporal y **exige** el veredicto contrario al que
se quiere evitar. Se cubren los seis casos del encargo (sufijo prohibido, tope de
tamano, secreto, ruta local, enlace roto y ancla rota) mas el caso limpio, que
tiene que salir con 0, y tres trampas que el guardian ya se comio una vez:

  * un `https://` no es una ruta con letra de unidad;
  * `C:\\path\\to\\romfs` es un marcador de posicion de la guia, no una fuga;
  * el propio guardian y este fichero no pueden aparecer como hallazgo. Si el
    literal del fixture se escribe tal cual en el codigo, el guardian marca su
    propio test al revisar el repo: por eso los literales malos se **montan en
    tiempo de ejecucion** con trozos y `chr`/concatenacion.

`tools/` no viaja en la release, asi que dentro de la release este modulo se
salta entero con el motivo escrito (no falla).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
GUARDIAN = RAIZ / "tools" / "check_repo.py"

if not GUARDIAN.is_file():
    pytest.skip(
        "tools/ no viaja en la release: el guardian no esta en este arbol",
        allow_module_level=True,
    )

_spec = importlib.util.spec_from_file_location("check_repo_del_repo", GUARDIAN)
check_repo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_repo)  # type: ignore[union-attr]


#: La ruta de usuario del fixture, montada por trozos: el fichero se escribe con
#: una sola contrabarra (lo que marca el guardian) sin que este .py la contenga.
RUTA_DE_USUARIO = "C:" + "\\" + "Users" + "\\" + "fulano" + "\\" + "ficha.txt"
#: Token con forma de GitHub, tambien montado: 4 + 36 caracteres.
TOKEN_FALSO = "ghp" + "_" + "A" * 36


def ejecutar(capsys, raiz: Path) -> tuple[int, str]:
    codigo = check_repo.main([str(raiz)])
    return codigo, capsys.readouterr().out


# ---------------------------------------------------------------------------
# Los seis casos del encargo
# ---------------------------------------------------------------------------


def test_sufijo_prohibido(tmp_path, capsys):
    (tmp_path / "x.BIN").write_bytes(b"\0" * 10)
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "sufijo prohibido" in salida and "x.BIN" in salida, salida


def test_fichero_por_encima_del_tope(tmp_path, capsys):
    (tmp_path / "big.txt").write_bytes(b"a" * (6 * 1024 * 1024))
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "5 MB" in salida and "big.txt" in salida, salida


def test_secreto_en_un_markdown(tmp_path, capsys):
    (tmp_path / "nota.md").write_text(
        "# Nota\n\nclave: " + TOKEN_FALSO + "\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "token de GitHub" in salida and "nota.md" in salida, salida


def test_ruta_local_absoluta(tmp_path, capsys):
    (tmp_path / "script.py").write_text(
        'RUTA = "%s"\n' % RUTA_DE_USUARIO, encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "ruta absoluta de usuario de Windows" in salida, salida


def test_enlace_relativo_roto(tmp_path, capsys):
    (tmp_path / "nota.md").write_text(
        "# Nota\n\n[x](no-existe.md)\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "enlace relativo roto" in salida and "no-existe.md" in salida, salida


def test_ancla_que_no_existe(tmp_path, capsys):
    (tmp_path / "README.md").write_text("# Guia\n\n## Seccion\n", encoding="utf-8")
    (tmp_path / "nota.md").write_text(
        "# Nota\n\n[x](README.md#ancla-que-no-existe)\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "ancla inexistente" in salida and "ancla-que-no-existe" in salida, salida


def test_directorio_limpio_pasa(tmp_path, capsys):
    (tmp_path / "README.md").write_text(
        "# Guia\n\n[apendice](apendice.md)\n", encoding="utf-8"
    )
    (tmp_path / "apendice.md").write_text("# Apendice\n\ntexto\n", encoding="utf-8")
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida
    assert salida.startswith("OK - 2 ficheros"), salida


# ---------------------------------------------------------------------------
# Trampas que no pueden dar falso positivo (un guard que bloquea de mas se
# desactiva, y entonces no protege de nada)
# ---------------------------------------------------------------------------


def test_ancla_que_existe_pasa(tmp_path, capsys):
    (tmp_path / "README.md").write_text(
        "# Guia\n\n## Supported build\n", encoding="utf-8"
    )
    (tmp_path / "nota.md").write_text(
        "# Nota\n\n[build](README.md#supported-build)\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida


def test_una_url_no_es_una_ruta_local(tmp_path, capsys):
    (tmp_path / "nota.md").write_text(
        "# Nota\n\n[fuente](https://github.com/ejemplo/repo)\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida


def test_marcador_de_posicion_no_es_fuga(tmp_path, capsys):
    marcador = "C:" + "\\" + "path" + "\\" + "to" + "\\" + "romfs"
    (tmp_path / "nota.md").write_text(
        "# Nota\n\nset PKP_ROMFS=" + marcador + "\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida


def test_ruta_unc_de_red(tmp_path, capsys):
    """Una ruta de red tambien dice de que maquina salio el trabajo."""
    unc = chr(92) * 2 + "DESKTOP-PC" + chr(92) + "dump"
    (tmp_path / "nota.md").write_text(
        "# Nota\n\norigen: " + unc + "\n", encoding="utf-8"
    )
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 1, salida
    assert "ruta UNC de red" in salida, salida


def test_el_guardian_no_se_marca_a_si_mismo(capsys):
    """Con `--todo` el arbol falla por `informes/` y `tools/`, pero nunca por el guard.

    Este test es el que impide que el literal de un fixture acabe dentro del
    codigo versionado y el guardian empiece a marcar sus propios tests.
    """
    codigo = check_repo.main(["--todo"])
    salida = capsys.readouterr().out
    assert codigo == 1, "el cuaderno de trabajo lleva rutas locales: --todo tiene que fallar"
    assert "tools/check_repo.py" not in salida, salida
    assert "tests/test_check_repo.py" not in salida, salida


def test_arbol_por_defecto_solo_audita_lo_publicable(capsys):
    """El barrido por defecto del repo revisa lo que viaja, y lo dice.

    La omision del material interno (informes/, tools/, docs con fecha) tiene que
    ser **contada**: un guard silencioso que deja fuera el 70 % del arbol sin
    decirlo es peor que uno que falla.
    """
    codigo = check_repo.main([])
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert salida.startswith("OK - "), salida
    assert "fuera de alcance" in salida, salida
    assert "informes/" in salida and "tools/" in salida, salida
    assert "--todo" in salida, salida
    assert "tools/check_repo.py" not in salida, salida


def test_lista_blanca_se_lee_del_constructor_de_la_release():
    """Una sola fuente de verdad: el guard no mantiene su propia lista."""
    entradas = check_repo.lista_blanca_publicable()
    assert entradas, "no se pudo leer la WHITELIST de tools/build_release.py"
    assert "pokopia" in entradas and "README.md" in entradas, entradas
    assert "informes" not in entradas and "tools" not in entradas, entradas


# ---------------------------------------------------------------------------
# Aviso de texto en claro en un mod (no es un fallo: es un aviso)
# ---------------------------------------------------------------------------

SHA_INVENTADO = "a" * 64


def _mod_con_texto(tmp_path, edit: dict) -> None:
    doc = {
        "mod_format": 1, "name": "m", "version": "0.1.0", "authors": ["t"],
        "game": {"title": "pokopia", "version": "2.0.1a",
                 "container_md5": {"LD_C0_R.BIN": "0" * 32, "LI_C0_R.IDX": "1" * 32}},
        "edits": [], "text": [dict({"table": 4650, "id": 5, "slot": 0,
                                    "value": "MOD-INVENTADO-1", "why": "t"}, **edit)],
    }
    (tmp_path / "mod.json").write_text(json.dumps(doc), encoding="utf-8")


def test_aviso_de_texto_en_claro_en_un_mod(tmp_path, capsys):
    """Un `expect` con texto es el texto del juego pegado: se avisa, no se falla."""
    _mod_con_texto(tmp_path, {"expect": "TEXTO-INVENTADO"})
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida
    assert "AVISO" in salida, salida
    assert "text[0].expect no esta vacio" in salida, salida
    assert "expect_sha256" in salida, salida


def test_sin_aviso_con_expect_sha256(tmp_path, capsys):
    _mod_con_texto(tmp_path, {"expect_sha256": SHA_INVENTADO})
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida
    assert "AVISO" not in salida, salida


def test_sin_aviso_con_expect_vacio(tmp_path, capsys):
    """`expect: ""` no lleva contenido: es la forma legitima de un bloque vacio."""
    _mod_con_texto(tmp_path, {"expect": ""})
    codigo, salida = ejecutar(capsys, tmp_path)
    assert codigo == 0, salida
    assert "AVISO" not in salida, salida


def test_el_arbol_publicable_no_tiene_avisos(capsys):
    """Los ejemplos del repo usan `expect_sha256`: el arbol limpio no avisa."""
    codigo = check_repo.main([])
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "AVISO" not in salida, salida
