"""Qué partes de cada libro entran en el corpus RAG, y con qué especie, por rangos de página.

Dos decisiones, ambas declaradas en `data/rag_alcance.json`:

- **`descartes`** — páginas que no entran: el índice alfabético del final de cada libro. Son
  listas de entradas con números («Acantocito, 186t, 188, 189f, 194»), sin ninguna frase
  clínica. Recuperarlas gasta presupuesto de prompt en ruido. Los límites se fijaron midiendo
  la densidad de entradas de índice por 1000 caracteres: salta de ~0 a 23–32 en una página
  concreta de cada libro.
- **`rangos`** — páginas restringidas a una especie (abajo).

Por qué existe: el 2026-08-01 se midió el índice real y **los 6772 chunks tenían `especie`
vacía**. El filtro por especie de `retriever.py` conserva el fragmento cuando su metadato viene
vacío, así que no excluía nada nunca — estaba muerto sobre datos reales, aunque sus tests
pasaran contra un índice sintético que sí traía el metadato.

No es teórico. Morphos atiende canino y felino; el corpus es de patología clínica veterinaria
COMPARADA y el 5,7 % de los chunks habla de aves. Que aquel día no se colara ninguno en los 102
fragmentos recuperados fue mérito del reranker, no de una guarda. Y el generador ya había
demostrado el riesgo: en `gammapatia-canino` escribió «la literatura [1] menciona que la
exposición a antígenos puede aumentar las gammaglobulinas en aves».

`ingest.py` sólo sabía poner una especie por LIBRO (desde el sidecar `.meta.json`), que es la
granularidad equivocada para un texto comparado: la especie cambia por sección, no por tomo.

Qué se etiqueta y qué no, deliberadamente conservador: **sólo secciones que el propio libro
declara en su índice**. El material comparado que menciona caballo o vaca de pasada se deja
intacto: enseña el principio general y sirve igual para un perro. Un detector por palabras clave
marcaba en falso dos bloques que resultaron ser proteínas de fase aguda entre especies e
infecciones sistémicas — contenido perfectamente aplicable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import RAIZ_REPO

log = logging.getLogger("morphos.rag")

RUTA_ALCANCE = RAIZ_REPO / "data" / "rag_alcance.json"

# El campo `pagina` guarda «305» o «305–306» (guion largo). Se usa la primera. Un fragmento que
# cruza el límite de una sección queda del lado de donde empieza: medido sobre el índice real,
# eso afecta a un puñado de fragmentos de portadilla, y equivocarse por el lado de NO etiquetar
# es el seguro (conserva material, no lo esconde).
_PRIMERA_PAGINA = re.compile(r"\d+")


def numero_de_pagina(pagina: str) -> int | None:
    """Primera página de un campo «305» o «305–306». None si no hay ningún dígito."""
    m = _PRIMERA_PAGINA.search(str(pagina or ""))
    return int(m.group(0)) if m else None


@dataclass(frozen=True)
class RangoAlcance:
    libro_empieza_por: str
    desde: int
    hasta: int
    especie: str
    motivo: str = ""

    def cubre(self, libro: str, pagina: int) -> bool:
        return libro.startswith(self.libro_empieza_por) and self.desde <= pagina <= self.hasta


@dataclass(frozen=True)
class RangoDescarte:
    libro_empieza_por: str
    desde: int
    hasta: int
    motivo: str = ""

    def cubre(self, libro: str, pagina: int) -> bool:
        return libro.startswith(self.libro_empieza_por) and self.desde <= pagina <= self.hasta


@lru_cache
def cargar_descartes(ruta: Path | None = None) -> tuple[RangoDescarte, ...]:
    """Rangos que no entran en el corpus (índices alfabéticos del final de cada libro)."""
    destino = ruta or RUTA_ALCANCE
    if not destino.exists():
        return ()
    datos = json.loads(destino.read_text(encoding="utf-8"))
    return tuple(
        RangoDescarte(
            libro_empieza_por=d["libro_empieza_por"],
            desde=int(d["desde"]),
            hasta=int(d["hasta"]),
            motivo=d.get("motivo", ""),
        )
        for d in datos.get("descartes", [])
    )


# Líder de puntos de un sumario: «Urine Samples . . . . . . . . . . 6». Cuatro puntos separados
# por espacios ya no aparecen en prosa clínica; una elipsis («…» o «...») no los tiene espaciados.
_LIDER_DE_PUNTOS = re.compile(r"(?:\.\s){4,}\.")


@lru_cache
def _umbral_lideres(ruta: Path | None = None) -> float:
    destino = ruta or RUTA_ALCANCE
    if not destino.exists():
        return 1.1  # inalcanzable: sin config, no se descarta nada por contenido
    datos = json.loads(destino.read_text(encoding="utf-8"))
    return float(datos.get("umbral_lideres_de_puntos", 1.1))


def fraccion_lideres_de_puntos(texto: str) -> float:
    """Parte del fragmento ocupada por líderes de puntos. 0.0 en cualquier prosa."""
    if not texto:
        return 0.0
    return sum(len(m.group(0)) for m in _LIDER_DE_PUNTOS.finditer(texto)) / len(texto)


def es_listado_de_contenidos(texto: str, ruta: Path | None = None) -> bool:
    """True si el fragmento es un sumario con líderes de puntos.

    Va por firma tipográfica y no por rango de página porque Fundamentals repite un sumario al
    principio de CADA capítulo: 23 bloques repartidos por todo el libro que, por rangos, serían
    23 entradas a mano y otras tantas ocasiones de equivocarse.
    """
    return fraccion_lideres_de_puntos(texto) >= _umbral_lideres(ruta)


def debe_descartarse(
    libro: str, pagina: str, texto: str = "", ruta: Path | None = None
) -> bool:
    """True si el fragmento no debe entrar en el corpus, por rango de página o por contenido.

    Sin número de página no se descarta por rango: ante la duda se conserva. Perder literatura
    clínica es peor que colar una entrada de índice, que como mucho gasta presupuesto de prompt.
    """
    if texto and es_listado_de_contenidos(texto, ruta):
        return True
    numero = numero_de_pagina(pagina)
    if numero is None:
        return False
    return any(d.cubre(libro, numero) for d in cargar_descartes(ruta))


@lru_cache
def cargar_rangos(ruta: Path | None = None) -> tuple[RangoAlcance, ...]:
    """Lee `data/rag_alcance.json`. Si falta, no etiqueta nada y lo dice en el log.

    Un fichero ausente degrada al comportamiento anterior (todo sin etiquetar), no a un fallo:
    la ingesta no puede caerse porque falte un mapa de alcance.
    """
    destino = ruta or RUTA_ALCANCE
    if not destino.exists():
        log.warning("Sin mapa de alcance del corpus (%s); no se etiquetará la especie.", destino)
        return ()
    datos = json.loads(destino.read_text(encoding="utf-8"))
    return tuple(
        RangoAlcance(
            libro_empieza_por=r["libro_empieza_por"],
            desde=int(r["desde"]),
            hasta=int(r["hasta"]),
            especie=r["especie"],
            motivo=r.get("motivo", ""),
        )
        for r in datos.get("rangos", [])
    )


def especie_de(libro: str, pagina: str, por_defecto: str = "", ruta: Path | None = None) -> str:
    """Especie del fragmento. `por_defecto` es lo que ya trajera el libro (sidecar `.meta.json`).

    Un rango explícito gana al valor del libro: en un texto comparado la sección es más
    específica que el tomo.
    """
    numero = numero_de_pagina(pagina)
    if numero is None:
        return por_defecto
    for rango in cargar_rangos(ruta):
        if rango.cubre(libro, numero):
            return rango.especie
    return por_defecto
