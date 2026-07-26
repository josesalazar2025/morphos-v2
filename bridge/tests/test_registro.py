"""Registro fabricante→parser y resolución multi-equipo de la configuración."""

from __future__ import annotations

from bridge.adaptadores import abaxis, bionote, horiba
from bridge.adaptadores.registro import obtener_parser
from bridge.config import BridgeConfig, Instrumento

HL7 = "\r".join([
    r"MSH|^~\&|VCHECK|BIONOTE|||20260725100000||ORU^R01|M1|P|2.6",
    r"OBR|1||S-1|^^^PANEL",
    r"OBX|1|NM|CORT^Cortisol^L||3.2|ug/dL||N|||F",
])


def test_registro_por_fabricante():
    assert obtener_parser("bionote", "mllp") is bionote.parsear
    assert obtener_parser("abaxis", "serie") is abaxis.parsear
    assert obtener_parser("scil", "serie") is horiba.parsear
    assert obtener_parser("horiba", "serie") is horiba.parsear


def test_registro_generico_por_transporte():
    assert callable(obtener_parser("", "mllp"))
    assert callable(obtener_parser("marca-rara", "serie"))


def test_adaptador_etiqueta_fabricante():
    r = bionote.parsear(HL7)[0]
    assert r.fabricante == "bionote"
    assert r.formato_origen == "hl7v2"


def test_resolver_instrumentos_desde_lista():
    cfg = BridgeConfig(api_key="k", instrumentos=[Instrumento(fabricante="bionote", transporte="mllp")])
    ins = cfg.resolver_instrumentos()
    assert len(ins) == 1 and ins[0].fabricante == "bionote"


def test_resolver_instrumentos_desde_conveniencia():
    cfg = BridgeConfig(api_key="k", mllp_habilitado=True, serie_habilitado=True, fabricante="abaxis")
    ins = cfg.resolver_instrumentos()
    assert {i.transporte for i in ins} == {"mllp", "serie"}
    assert all(i.fabricante == "abaxis" for i in ins)
