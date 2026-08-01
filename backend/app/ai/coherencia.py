"""Los hallazgos estructurados sólo pueden hablar de analitos que se enviaron.

Motivo: el 2026-08-01, con salida estructurada, medGemma devolvió en `hallazgos_clave` un
«Potasio (K+): 7.1 mEq/L, alto, grave» en un caso cuyos valores eran calcio, fósforo, BUN y
creatinina. El potasio no se midió: el valor es inventado. El juez lo marcó como fallo grave de
seguridad (0.35).

Por qué merece guarda propia: la decodificación restringida garantiza JSON bien formado, no
veracidad. Y un analito inventado DENTRO de un campo estructurado es peor que en prosa, porque
la interfaz lo pinta como un hallazgo con el mismo rango visual que los del motor determinista.

A diferencia de `prescripcion.py`, aquí sí se BORRA: un elemento de lista es una unidad
independiente y quitarlo no deja una frase a medias.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from ..schemas import InterpretacionClinica, PeticionInterpretacion

log = logging.getLogger("morphos.ia")


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes).strip()


def _terminos_conocidos(pet: PeticionInterpretacion) -> set[str]:
    """Claves y palabras de los analitos que SÍ se enviaron (hallazgos y parámetros de patrón)."""
    terminos: set[str] = set()
    for h in pet.hallazgos:
        terminos.add(_normalizar(h.clave))
        terminos.update(p for p in _normalizar(h.nombre).split() if len(p) > 2)
    for p in pet.patrones:
        terminos.update(_normalizar(c) for c in p.parametros)
    return {t for t in terminos if t}


def hallazgos_fabricados(
    resultado: InterpretacionClinica, pet: PeticionInterpretacion
) -> list[str]:
    """Analitos de `hallazgos_clave` que no corresponden a nada enviado.

    El cotejo es laxo a propósito: el modelo escribe «Potasio (K+)» donde la petición trae
    `potasio`/«Potasio (K)», y una comparación estricta borraría hallazgos legítimos. Se exige
    sólo que ALGUNA palabra del analito declarado aparezca entre los términos enviados.
    """
    conocidos = _terminos_conocidos(pet)
    if not conocidos:
        return []
    fabricados = []
    for hallazgo in resultado.hallazgos_clave:
        palabras = {p for p in _normalizar(hallazgo.analito).split() if len(p) > 2}
        if not palabras:
            continue
        if not any(
            p in conocidos or any(p in c or c in p for c in conocidos) for p in palabras
        ):
            fabricados.append(hallazgo.analito)
    return fabricados


def descartar_fabricados(
    resultado: InterpretacionClinica, pet: PeticionInterpretacion
) -> InterpretacionClinica:
    """Quita de `hallazgos_clave` lo que el paciente nunca aportó. No toca la prosa."""
    fabricados = set(hallazgos_fabricados(resultado, pet))
    if fabricados:
        log.warning("Hallazgos inventados descartados: %s", ", ".join(sorted(fabricados)))
        resultado.hallazgos_clave = [
            h for h in resultado.hallazgos_clave if h.analito not in fabricados
        ]
    return resultado
