"""Tests del modulo de save sobre un save sintetico (nunca el real).

Cubren: lectura del inventario con la mascara 0x1FFF, ida y vuelta sin cambios, escritura
con un solo byte distinto en el crudo, copia de seguridad y deshacer, parte de progreso
sin nombres propios, y que una version nueva de save solo necesite una entrada de layout.
"""
from __future__ import annotations

import os
import re
import struct
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import save_fixture as fx  # noqa: E402
from pokopia import save as S  # noqa: E402
from pokopia.save import layout as L  # noqa: E402
from pokopia.cli import main as cli_main  # noqa: E402


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def test_lee_inventario_con_mascara(tmp_path):
    payload = fx.make_payload(items={0: (101, 5), 3: (4021, 200), 129: (7, 255)})
    # un registro con bits altos (variante/colocacion) para probar la mascara
    payload = bytearray(payload)
    fx.write_record(payload, L.LAYOUT_2_0_1, "inventory", 7,
                    struct.pack("<I", (0x1A2400 | 1500)) + bytes([9]))
    fx.make_save(str(tmp_path), payload=bytes(payload))
    page = S.open_page(str(tmp_path))
    items = S.read_items(page)
    assert len(items) == 130
    assert [r.item_id for r in items if r.occupied] == [101, 4021, 1500, 7]
    assert items[7].item_id == 1500
    assert items[7].variant == 0x1A2000
    assert items[7].count == 9
    assert len(S.distinct_ids(page)) == 4
    assert S.occupied(page) == 4


def test_version_desconocida_falla(tmp_path):
    fx.make_save(str(tmp_path), version=0x02000046)
    with pytest.raises(S.SaveVersionError):
        S.open_page(str(tmp_path))


def test_cabecera_invalida_falla(tmp_path):
    path = fx.make_save(str(tmp_path), magic=0x12345678)
    with pytest.raises(S.SaveFormatError):
        S.open_page(str(tmp_path))
    assert os.path.getsize(path) > 0


def test_longitud_declarada_fuera_de_rango_falla(tmp_path):
    fx.make_save(str(tmp_path), declared_delta=10 ** 6)
    with pytest.raises(S.SaveFormatError):
        S.open_page(str(tmp_path))


# ---------------------------------------------------------------------------
# Escritura: ida y vuelta
# ---------------------------------------------------------------------------

def test_ida_y_vuelta_sin_cambios_deja_el_fichero_identico(tmp_path):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}))
    page = S.open_page(str(tmp_path))
    mismo = S.items.with_item(page, 0, item_id=101, count=5)
    result = S.write_payload(page, mismo, dry_run=False)
    assert result.unchanged
    assert result.wrote is False
    assert result.md5_after == page.md5
    assert S.page.md5_file(page.path) == page.md5


def test_escritura_con_cambio_mueve_un_byte_del_crudo(tmp_path):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}))
    page = S.open_page(str(tmp_path))
    nuevo = S.items.with_item(page, 0, count=6)
    result = S.write_payload(page, nuevo, dry_run=True)
    assert result.payload_diff == 1
    assert result.payload_offsets == [L.LAYOUT_2_0_1.region("inventory").offset + 4]
    assert result.roundtrip_ok
    assert result.wrote is False
    assert S.page.md5_file(page.path) == page.md5


def test_invariante_del_cambio_es_el_payload_no_el_fichero(tmp_path):
    """1 byte en el payload; en el fichero, lo que cueste recomprimir (>= 1, informado)."""
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5), 1: (4021, 77),
                                                             2: (7, 200)}))
    page = S.open_page(str(tmp_path))
    for slot, cantidad in ((0, 6), (1, 78), (2, 201)):
        nuevo = S.items.with_item(page, slot, count=cantidad)
        result = S.write_payload(page, nuevo, dry_run=True)
        assert result.payload_diff == 1
        assert result.roundtrip_ok
        assert result.file_diff >= 1
    # el parte de una escritura sin cambios sigue diciendo 0/0
    mismo = S.items.with_item(page, 2, count=200)
    quieto = S.write_payload(page, mismo, dry_run=True)
    assert quieto.unchanged and quieto.file_diff == 0 and quieto.payload_diff == 0


def test_escritura_real_escribe_backup_y_se_puede_deshacer(tmp_path, monkeypatch):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}))
    monkeypatch.setenv("PKP_BACKUP_DIR", str(tmp_path / "backups"))
    page = S.open_page(str(tmp_path))
    nuevo = S.items.with_item(page, 0, item_id=102)
    result = S.write_payload(page, nuevo, dry_run=False)
    assert result.wrote and result.backup and os.path.isfile(result.backup)
    assert result.file_diff >= 1
    assert result.payload_diff == 1
    # el fichero escrito se puede volver a leer y trae el cambio
    after = S.open_page(str(tmp_path))
    assert after.payload != page.payload
    assert S.read_items(after)[0].item_id == 102
    assert S.read_items(after)[0].count == 5
    # deshacer
    doc = S.undo(result.backup, dry_run=True)
    assert doc["safe_to_undo"] and not doc["restored"]
    doc = S.undo(result.backup, dry_run=False)
    assert doc["restored"]
    assert S.page.md5_file(page.path) == page.md5


def test_escritura_en_el_save_configurado_esta_bloqueada_por_defecto(tmp_path, monkeypatch):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}))
    page = S.open_page(str(tmp_path))
    nuevo = S.items.with_item(page, 0, count=4)
    live = os.path.join(str(tmp_path), "save-vivo")
    os.makedirs(os.path.join(live, "G00"), exist_ok=True)
    target = os.path.join(live, "G00", "CMNDAT.BIN")
    with open(target, "wb") as fh:
        fh.write(page.raw)
    # el save protegido es el que diga PKP_SAVE (antes venia de una ruta fija de Windows)
    monkeypatch.setenv("PKP_SAVE", live)
    with pytest.raises(S.SaveReadOnlyError):
        S.write_payload(page, nuevo, target=target, dry_run=False)
    # con permiso explicito si escribe (es una copia de test, no el save real)
    result = S.write_payload(page, nuevo, target=target, dry_run=False,
                             allow_live_save=True)
    assert result.wrote


def test_valores_fuera_de_rango(tmp_path):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}))
    page = S.open_page(str(tmp_path))
    with pytest.raises(S.SaveError):
        S.items.with_item(page, 130, count=1)
    with pytest.raises(S.SaveError):
        S.items.with_item(page, 0, item_id=0x2000)
    with pytest.raises(S.SaveError):
        S.items.with_item(page, 0, count=256)


# ---------------------------------------------------------------------------
# Parte de progreso
# ---------------------------------------------------------------------------

def test_parte_de_progreso_cuenta_lo_que_hay(tmp_path):
    cats = {i: 0x43 for i in (101, 400, 1500)}
    payload = fx.make_payload(items={0: (101, 5), 1: (400, 1)}, villagers=7, homes=9,
                              catalogue=cats)
    fx.make_save(str(tmp_path), payload=payload)
    page = S.open_page(str(tmp_path))
    report = S.build_report(page)
    assert report.get("bolsa").value == 2
    assert report.get("bolsa").total == 130
    assert report.get("bolsa_ids").value == 2
    assert report.get("aldeanos").value == 7
    assert report.get("casas").value == 9
    assert report.get("catalogo").value == 3
    assert report.get("catalogo").total == 4600
    lineas = S.format_report(report)
    assert any("bolsa" in line and "2 / 130" in line for line in lineas)


def test_parte_no_imprime_nombres_propios(tmp_path, capsys):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}, villagers=3))
    assert cli_main(["progress", "--save", str(tmp_path)]) == 0
    salida = capsys.readouterr().out
    from vocabulario import PERMITIDAS
    palabras = set(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", salida.lower()))
    assert palabras <= PERMITIDAS, "palabras fuera de la lista: %s" % (palabras - PERMITIDAS)
    # El parte ya no publica un renglon con los tres nombres: cada cifra que no se
    # mide sale en su linea con el motivo.
    assert "sin medir" not in salida
    assert "no medido" in salida
    for clave in ("zona", "peticiones", "coleccionable"):
        linea = [l for l in salida.splitlines()
                 if l.strip().split(":", 1)[0].strip() == clave]
        assert linea and "no medido" in linea[0], "falta el motivo de %s" % clave


def test_json_del_parte(tmp_path, capsys):
    fx.make_save(str(tmp_path), payload=fx.make_payload(items={0: (101, 5)}))
    assert cli_main(["progress", "--save", str(tmp_path), "--json"]) == 0
    import json
    doc = json.loads(capsys.readouterr().out)
    assert doc["page"] == "G00"
    assert {v["key"] for v in doc["values"]} >= {"bolsa", "aldeanos", "catalogo"}
    assert {u["key"] for u in doc["unmeasured"]} == {"zona", "peticiones",
                                                    "coleccionable"}


# ---------------------------------------------------------------------------
# C4: una version nueva solo añade una entrada de layout
# ---------------------------------------------------------------------------

def test_version_nueva_solo_necesita_layout(tmp_path):
    """Mismo items.py y progress.py sirven para otra geometria sin tocarlos."""
    base = L.LAYOUT_2_0_1
    # La region se llama distinto a propósito: el codigo la pide por papel (`role`),
    # no por el nombre que tenga en cada version.
    inv = L.Region("bolsa_sintetica", 64, 4, 5, confidence="measured",
                   role="inventory")
    cat = L.Region("catalogue", 256, 16, 1, confidence="measured")
    nueva = L.Layout(
        version=0x0BADF00D, game="sintetica", payload_size=1024,
        regions=(inv, cat),
        progress=(
            L.ProgressSpec("bolsa", "bolsa_sintetica", "occupied", arg=0, arg2=3,
                           total=4),
            L.ProgressSpec("catalogo", "catalogue", "bit_set", arg=0, arg2=0, total=16),
        ),
        discarded=(L.Discarded("zona", "sin datos en la version sintetica"),),
    )
    L.LAYOUTS[nueva.version] = nueva
    try:
        payload = bytearray(nueva.payload_size)
        payload[64:69] = fx.item_record(7, 3)
        payload[256 + 5] = 0x01
        fx.write_page(str(tmp_path), bytes(payload), version=nueva.version)
        page = S.open_page(str(tmp_path))
        assert page.layout.game == "sintetica"
        assert S.occupied(page) == 1
        report = S.build_report(page)
        assert report.get("bolsa").value == 1
        assert report.get("catalogo").value == 1
        assert report.unmeasured[0][0] == "zona"
    finally:
        del L.LAYOUTS[nueva.version]
    assert base.payload_size > nueva.payload_size


def test_sin_nombres_del_juego_en_el_codigo():
    """El paquete save/ no cita contenido: solo formato, cifras e indices."""
    raiz = os.path.join(RAIZ, "pokopia", "save")
    texto = ""
    for name in sorted(os.listdir(raiz)):
        if name.endswith(".py"):
            with open(os.path.join(raiz, name), encoding="utf-8") as fh:
                texto += fh.read()
    assert "Pokémon" not in texto and "Pokemon" not in texto.replace("Pokemon Pokopia", "")
