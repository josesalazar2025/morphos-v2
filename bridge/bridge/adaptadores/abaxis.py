"""Adaptador Abaxis VetScan (VS2) — ASTM E1394 sobre serie.

Envuelve el parser ASTM genérico fijando `fabricante="abaxis"` (→ data/lab_mapeos/abaxis.json).
Recuerda configurar el VS2 para salida **ASTM** (no ASCII/XML). Los códigos exactos del rotor
se confirman con una captura real.
"""

from __future__ import annotations

from ..modelo import Resultado
from .astm_generico import parsear_astm


def parsear(trama: str, instrumento_id: str = "abaxis") -> list[Resultado]:
    return parsear_astm(trama, instrumento_id, fabricante="abaxis")
