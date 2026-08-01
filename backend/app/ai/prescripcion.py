"""Guarda determinista contra indicaciones terapéuticas en la salida del modelo.

Por qué existe: el 2026-07-31, al probar `SALTAR_RAZONAMIENTO` en el Space, medGemma pasó de
interpretar a prescribir en `cetoacidosis-diabetica-canino` — «iniciar tratamiento inmediato con
insulina, fluidoterapia intravenosa y reposición de potasio», sin encuadrarlo como acto
veterinario presencial. Con potasio 3,0 mEq/L, administrar insulina antes de corregir el potasio
puede precipitar arritmias mortales. El juez lo marcó como violación de seguridad.

Se revirtió aquel experimento, pero el agujero es previo e independiente: ni `SISTEMA` ni
`SISTEMA_PROSA` prohibían dar pautas de tratamiento. Se ha añadido la regla al prompt, y este
módulo es la red que no depende de que el modelo la obedezca — la tercera vez en este proyecto
que una regla de seguridad confiada al prompt de un 4B no se sostiene (ver `alcance.py` y
`_derivacion_obligatoria`).

Qué hace, deliberadamente conservador: NO borra texto clínico. Detectar es fiable; reescribir
prosa clínica automáticamente no lo es, y una frase mutilada puede cambiar de sentido. Cuando
detecta lenguaje prescriptivo, antepone el encuadre que faltaba y fuerza la derivación.
"""

from __future__ import annotations

import re
import unicodedata

# Verbos que ORDENAN una intervención. «Se recomienda valorar» o «considerar» no entran: son
# lenguaje de sugerencia diagnóstica, que es justo lo que la herramienta sí debe hacer.
_VERBOS = (
    r"administr\w+|inici\w+|instaur\w+|paut\w+|prescrib\w+|comenz\w+|comienc\w+|"
    r"aplic\w+|inyect\w+|suministr\w+|dosific\w+|trate|tratar|reponer|repong\w+"
)

# Términos terapéuticos. No incluye pruebas diagnósticas: pedir una ecografía o un cultivo es
# parte legítima de la interpretación.
_TERAPIA = (
    r"insulina|fluidoterapia|fluidos|suero|cristaloides|coloides|transfusi\w+|antibi\w+|"
    r"corticoid\w+|glucocorticoid\w+|prednisolona|prednisona|dexametasona|furosemida|"
    r"benazepril|enalapril|levotiroxina|metimazol|fenobarbital|bromuro|ciclosporina|"
    r"vitamina k|bicarbonato|potasio|calcio gluconato|gluconato c\w+lcico|analg\w+sic\w+|"
    r"antiem\w+tic\w+|maropitant|omeprazol|sucralfato|oxigenoterapia|quimioterapia"
)

# Una posología es inequívoca por sí sola, sin necesidad de verbo.
_POSOLOGIA = re.compile(
    r"\b\d+([.,]\d+)?\s*(mg|g|mcg|ui|ml|meq|mmol)\s*/\s*(kg|m2|animal|gato|perro)"
    r"|\b\d+([.,]\d+)?\s*(mg|ui)\s*/\s*kg"
    r"|\bcada\s+\d+\s*(h|horas)\b"
    r"|\bq\d+h\b",
    re.IGNORECASE,
)

# Verbo imperativo/infinitivo cerca de un término terapéutico, en la misma oración.
_ORDEN = re.compile(rf"\b({_VERBOS})\b[^.;]{{0,80}}?\b({_TERAPIA})\b", re.IGNORECASE)
_ORDEN_INVERSA = re.compile(rf"\b({_TERAPIA})\b[^.;]{{0,40}}?\b({_VERBOS})\b", re.IGNORECASE)

ENCUADRE = (
    "Nota de alcance: lo que sigue es interpretación de laboratorio, no una pauta terapéutica. "
    "La indicación, la dosificación y la monitorización de cualquier tratamiento son competencia "
    "del veterinario responsable del paciente, de forma presencial. "
)


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_tildes)


# Un fármaco administrado como parte de una PRUEBA DIAGNÓSTICA no es una prescripción: describir
# el protocolo de la supresión con dexametasona o la estimulación con ACTH es exactamente lo que
# la herramienta debe hacer. Sin esta excepción la guarda daba un falso positivo real —medido el
# 2026-08-01 sobre `hiperadrenocorticismo-canino`, donde «se administra dexametasona y se mide el
# cortisol tras 24 horas» describía el LDDST— y le habría estampado un aviso de «esto no es una
# pauta terapéutica» a una recomendación diagnóstica correcta.
_CONTEXTO_DIAGNOSTICO = re.compile(
    r"prueba de (estimulacion|supresion|provocacion|ayuno)|"
    r"test de (estimulacion|supresion|acth|tolerancia)|"
    r"estimulacion con acth|supresion con dexametasona|lddst|psddb|hddst|"
    r"curva de glucosa|se mide (el|la) (cortisol|glucemia|glucosa)|"
    r"midiendo (nuevamente )?(el|la) cortisol|cortisol (basal|tras|post)",
    re.IGNORECASE,
)

# La exención se evalúa por ORACIÓN, y el corte NO incluye ':' ni ';' a propósito: el modelo
# titula la prueba y la describe después («Prueba de Supresión con Dexametasona (LDDST):
# Alternativa para confirmar HAC»), así que partir por ':' separaría el protocolo de su nombre.
# Tampoco vale una ventana de caracteres: con ella, «Prueba de estimulación con ACTH… Mientras
# tanto, iniciar fluidoterapia» quedaba absuelta por la mención diagnóstica de la frase anterior,
# que es justo lo que la guarda debe atrapar. Lo fijan dos tests, uno por cada lado.
_ORACIONES = re.compile(r"(?<=[.!?])\s+|\n+")


def detectar_prescripcion(texto: str) -> list[str]:
    """Fragmentos con lenguaje prescriptivo. Lista vacía si no hay ninguno.

    Un fármaco administrado dentro de un protocolo diagnóstico queda exento. Se trabaja sobre
    el texto sin tildes y en minúsculas para no depender de cómo acentúe el modelo, que varía
    entre generaciones.
    """
    hallados: list[str] = []
    for oracion in _ORACIONES.split(_normalizar(texto)):
        if not oracion.strip() or _CONTEXTO_DIAGNOSTICO.search(oracion):
            continue
        for patron in (_ORDEN, _ORDEN_INVERSA, _POSOLOGIA):
            hallados.extend(m.group(0).strip() for m in patron.finditer(oracion))
    # Deduplica conservando el orden de aparición.
    vistos: set[str] = set()
    return [h for h in hallados if not (h in vistos or vistos.add(h))]


def encuadrar(texto: str) -> str:
    """Antepone el encuadre que faltaba, sin tocar el texto clínico ni duplicar la nota."""
    if texto.startswith(ENCUADRE.strip()[:40]):
        return texto
    return f"{ENCUADRE}{texto}"
