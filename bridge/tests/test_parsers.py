"""Parseo de tramas HL7 v2 (PCD-01) y ASTM crudas → modelo canónico del puente."""

from __future__ import annotations

from datetime import datetime, timezone

from bridge.adaptadores.astm_generico import parsear_astm
from bridge.adaptadores.hl7v2 import parsear_hl7

# --- HL7 v2 ORU^R01 estilo Bionote Vcheck (PCD-01) ---
HL7 = "\r".join([
    r"MSH|^~\&|VCHECK|BIONOTE|||20260725100000||ORU^R01|MSG0001|P|2.6",
    r"PID|1||PID123||Fido^^^^||||||||||||",
    r"OBR|1||SAMP-001|^^^PANEL",
    r"OBX|1|NM|CORT^Cortisol^L||3.2|ug/dL|1-6|N|||F",
    r"OBX|2|NM|CRP^C-Reactive Protein^L||8.5|mg/L|0-10|N|||F",
    r"L|1|N",
])

# --- ASTM E1394 estilo Abaxis VetScan ---
ASTM = "\r".join([
    r"H|\^&|||VetScan^VS2||||||||P|1",
    r"P|1||PID9||Michi|||F||||Felino",  # nombre=campo6, sexo=campo9, especie=campo13
    r"O|1|SAMP-042||^^^PANEL|R",
    r"R|1|^^^GLU|118|mg/dL||N||F",
    r"R|2|^^^CREA|1.4|mg/dL||H||F",
    r"L|1|N",
])


def test_hl7_extrae_muestra_y_observaciones():
    resultados = parsear_hl7(HL7, instrumento_id="bionote-1", fabricante="bionote")
    assert len(resultados) == 1
    r = resultados[0]
    assert r.muestra_id == "SAMP-001"
    assert r.formato_origen == "hl7v2"
    assert r.fabricante == "bionote"
    codigos = {(o.codigo_prueba, o.valor, o.unidad) for o in r.observaciones}
    assert codigos == {("CORT", "3.2", "ug/dL"), ("CRP", "8.5", "mg/L")}
    assert r.pistas_paciente.nombre_mascota == "Fido"
    assert r.momento == datetime(2026, 7, 25, 10, 0, 0, tzinfo=timezone.utc)  # MSH-7


def test_astm_extrae_muestra_y_observaciones():
    resultados = parsear_astm(ASTM, instrumento_id="vetscan-1", fabricante="abaxis")
    assert len(resultados) == 1
    r = resultados[0]
    assert r.muestra_id == "SAMP-042"
    assert r.formato_origen == "astm"
    obs = {o.codigo_prueba: (o.valor, o.unidad, o.bandera) for o in r.observaciones}
    assert obs["GLU"] == ("118", "mg/dL", None)
    assert obs["CREA"] == ("1.4", "mg/dL", "H")
    assert r.pistas_paciente.especie_texto == "Felino"


def test_payload_serializable():
    r = parsear_hl7(HL7)[0]
    payload = r.payload()
    assert payload["muestra_id"] == "SAMP-001"
    assert payload["formato_origen"] == "hl7v2"
    assert len(payload["observaciones"]) == 2
    assert "momento" in payload


def test_mensaje_no_hl7_devuelve_vacio():
    assert parsear_hl7("esto no es HL7") == []
