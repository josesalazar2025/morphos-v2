"""Normalización/validación de un Resultado antes de reenviarlo.

Acota longitudes al contrato del backend (muestra_id ≤128, codigo_prueba ≤64, valor ≤128),
recorta espacios y descarta observaciones sin código o sin valor. Devuelve el Resultado
saneado o None si no queda nada útil.
"""

from __future__ import annotations

from typing import Optional

from .modelo import Resultado


def normalizar(res: Resultado) -> Optional[Resultado]:
    res.muestra_id = res.muestra_id.strip()[:128]
    res.instrumento_id = res.instrumento_id.strip()[:64] or "desconocido"
    if not res.muestra_id:
        return None

    limpias = []
    for o in res.observaciones:
        o.codigo_prueba = o.codigo_prueba.strip()[:64]
        o.valor = o.valor.strip()[:128]
        o.unidad = (o.unidad or "").strip()[:32]
        if o.codigo_prueba and o.valor:
            limpias.append(o)
    res.observaciones = limpias

    return res if res.observaciones else None
