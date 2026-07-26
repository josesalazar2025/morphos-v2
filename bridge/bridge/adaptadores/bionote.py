"""Adaptador Bionote Vcheck V200 — HL7 v2.6 PCD-01 sobre MLLP.

Envuelve el parser HL7 genérico fijando `fabricante="bionote"` para que el backend use
`data/lab_mapeos/bionote.json`. Los códigos OBX-3 exactos se confirman con una captura real
(ver checklist del README); mientras tanto, generico.json + bionote.json cubren lo habitual.
"""

from __future__ import annotations

from ..modelo import Resultado
from .hl7v2 import parsear_hl7


def parsear(trama: str, instrumento_id: str = "bionote") -> list[Resultado]:
    return parsear_hl7(trama, instrumento_id, fabricante="bionote")
