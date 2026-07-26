"""Registro fabricante → parser. Permite que el supervisor elija el adaptador correcto por
configuración, sin ramas if/else por marca."""

from __future__ import annotations

from typing import Callable

from ..modelo import Resultado
from . import abaxis, bionote, horiba
from .astm_generico import parsear_astm
from .hl7v2 import parsear_hl7

Parser = Callable[[str, str], list[Resultado]]

_POR_FABRICANTE: dict[str, Parser] = {
    "abaxis": abaxis.parsear,
    "horiba": horiba.parsear,
    "scil": horiba.parsear,
    "bionote": bionote.parsear,
}


def obtener_parser(fabricante: str, transporte: str) -> Parser:
    """Devuelve el parser del fabricante; si no se reconoce, el genérico según el transporte
    (MLLP → HL7, serie → ASTM)."""
    p = _POR_FABRICANTE.get((fabricante or "").lower())
    if p is not None:
        return p
    if transporte == "mllp":
        return lambda trama, iid: parsear_hl7(trama, iid)
    return lambda trama, iid: parsear_astm(trama, iid)
