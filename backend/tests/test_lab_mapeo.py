"""Pruebas de la capa de mapeo de analizadores (lab/mapeo.py).

Verifican: código de fabricante → clave canónica, PARIDAD de las conversiones de unidad con
pdf-parser.ts, semicuantitativos, derivación del diferencial, y recogida de no reconocidos.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.lab import mapeo
from app.schemas_lab import ObservacionAnalizador, ResultadoAnalizador


def _resultado(observaciones, fabricante=None, muestra="M-1"):
    return ResultadoAnalizador(
        muestra_id=muestra,
        instrumento_id="test-1",
        fabricante=fabricante,
        observaciones=observaciones,
        momento=datetime(2026, 7, 25, tzinfo=UTC),
        formato_origen="json",
    )


def _obs(codigo, valor, unidad=""):
    return ObservacionAnalizador(codigo_prueba=codigo, valor=valor, unidad=unidad)


# --- Conversión de unidades: paridad con pdf-parser.ts ---

@pytest.mark.parametrize(
    "clave, clave_conv, valor, unidad, esperado",
    [
        ("gluc", None, 5.0, "mmol/L", round(5.0 * 18.016, 4)),
        ("creat", None, 88.4, "umol/L", 1.0),
        ("creat", None, 176.8, "µmol/L", 2.0),
        ("bun", "urea", 10.0, "mmol/L", 28.0),
        ("bun", "urea", 50.0, "mg/dL", round(50.0 * 0.467, 4)),
        ("bun", "bun", 5.0, "mmol/L", 14.0),
        ("bili", None, 17.1, "umol/L", 1.0),
        ("calc", None, 2.0, "mmol/L", round(2.0 * 4.008, 4)),
        ("colest", None, 5.0, "mmol/L", round(5.0 * 38.67, 4)),
        ("t4_total", None, 2.0, "ug/dL", round(2.0 * 12.87, 4)),
        ("hgb", None, 150.0, "g/L", 15.0),
        ("gluc", None, 90.0, "mg/dL", 90.0),  # unidad nativa → sin cambio
        ("gluc", None, 90.0, "", 90.0),  # sin unidad → sin cambio
    ],
)
def test_conversion_unidad(clave, clave_conv, valor, unidad, esperado):
    assert mapeo.convertir_unidad(clave, clave_conv, valor, unidad) == esperado


# --- Parseo de valores ---

@pytest.mark.parametrize(
    "entrada, esperado",
    [("12.3", 12.3), ("1,5", 1.5), ("<0.1", 0.1), (">1000", 1000.0), ("  7 ", 7.0), ("NEG", None), ("", None)],
)
def test_parsear_valor_numerico(entrada, esperado):
    assert mapeo.parsear_valor_numerico(entrada) == esperado


def test_valor_negativo_aceptado():
    # Exceso de base puede ser negativo: NO se descarta (a diferencia del PDF).
    assert mapeo.parsear_valor_numerico("-3.5") == -3.5


@pytest.mark.parametrize(
    "entrada, esperado",
    [("+++", "+++"), ("++", "++"), ("+", "+"), ("Negativo", "neg"), ("trazas", "+"), ("25", None)],
)
def test_parsear_semicuantitativo(entrada, esperado):
    assert mapeo.parsear_semicuantitativo(entrada) == esperado


# --- Mapeo de resultados completos ---

def test_mapeo_panel_bioquimico():
    res = _resultado([
        _obs("GLU", "5.0", "mmol/L"),
        _obs("CREA", "1.2", "mg/dL"),
        _obs("ALB", "3.1", "g/dL"),
    ])
    mapeado = mapeo.mapear_resultado(res)
    assert set(mapeado.analitos) == {"gluc", "creat", "alb"}
    assert mapeado.analitos["gluc"].valor == round(5.0 * 18.016, 4)
    assert mapeado.analitos["creat"].valor == 1.2
    assert mapeado.no_mapeados == []


def test_semicuantitativo_orina():
    res = _resultado([_obs("UPRO", "+++")])
    mapeado = mapeo.mapear_resultado(res)
    assert mapeado.analitos["uri-prot"].valor == "+++"
    assert mapeado.analitos["uri-prot"].es_semicuantitativo is True


def test_derivacion_diferencial_desde_absolutos():
    # WBC 10, neutrófilos # 7 → neutro% derivado = 70
    res = _resultado([_obs("WBC", "10", "x10^3/uL"), _obs("NEU#", "7", "x10^3/uL")])
    mapeado = mapeo.mapear_resultado(res)
    assert mapeado.analitos["neutro"].valor == 70.0
    assert mapeado.analitos["neutro"].valor_original == "(derivado)"


def test_codigo_desconocido_va_a_no_mapeados():
    res = _resultado([_obs("XYZ_RARO", "1.0"), _obs("GLU", "90", "mg/dL")])
    mapeado = mapeo.mapear_resultado(res)
    assert "XYZ_RARO" in mapeado.no_mapeados
    assert "gluc" in mapeado.analitos


def test_primer_match_gana():
    res = _resultado([_obs("GLU", "90", "mg/dL"), _obs("GLUCOSA", "120", "mg/dL")])
    mapeado = mapeo.mapear_resultado(res)
    assert mapeado.analitos["gluc"].valor == 90.0  # el primero gana, como en el PDF


def test_vendor_bionote_codigos_especificos():
    res = _resultado([_obs("CPL", "150"), _obs("CORTISOL", "3.0", "ug/dL")], fabricante="bionote")
    m = mapeo.mapear_resultado(res)
    assert "pli" in m.analitos and "cortisol_bas" in m.analitos
    assert m.no_mapeados == []


def test_vendor_bionote_t4_convierte_ugdl_a_nmol():
    # Bionote reporta T4 en ug/dL; unidad_defecto lo convierte a nmol/L (×12.87) sin unidad explícita.
    res = _resultado([_obs("T4", "2.0")], fabricante="bionote")
    m = mapeo.mapear_resultado(res)
    assert m.analitos["t4_total"].valor == round(2.0 * 12.87, 4)


def test_vendor_horiba_diferencial_3partes():
    res = _resultado([_obs("GRA%", "65", "%"), _obs("MID%", "5", "%"), _obs("LY%", "30", "%")], fabricante="horiba")
    m = mapeo.mapear_resultado(res)
    assert m.analitos["neutro"].valor == 65.0
    assert m.analitos["mono"].valor == 5.0  # MID ≈ monocitos (sólo en la tabla de Horiba)
    assert m.analitos["linfo"].valor == 30.0


def test_pistas_paciente_se_propagan():
    res = ResultadoAnalizador(
        muestra_id="M-9",
        instrumento_id="test-1",
        observaciones=[_obs("GLU", "90", "mg/dL")],
        momento=datetime(2026, 7, 25, tzinfo=UTC),
        pistas_paciente={"especie_texto": "Canino", "nombre_mascota": "Fido"},
    )
    mapeado = mapeo.mapear_resultado(res)
    assert mapeado.paciente.especie_texto == "Canino"
