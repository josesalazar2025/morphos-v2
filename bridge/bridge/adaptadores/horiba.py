"""Adaptador Scil/Horiba (ABX Micros / scil Vet abc) — ASTM E1394 sobre serie.

Envuelve el parser ASTM genérico fijando `fabricante="horiba"` (→ data/lab_mapeos/horiba.json).
Los equipos de hematología de 3 partes reportan el diferencial como LYM/MON/GRA (granulocitos
≈ neutrófilos): ese mapeo vive en horiba.json. Confirmar códigos con una captura real.
"""

from __future__ import annotations

from ..modelo import Resultado
from .astm_generico import parsear_astm


def parsear(trama: str, instrumento_id: str = "horiba") -> list[Resultado]:
    return parsear_astm(trama, instrumento_id, fabricante="horiba")
