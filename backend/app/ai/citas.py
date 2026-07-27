"""Atribución verificable, común a las tres rutas de modelo.

El problema que resuelve: sólo Ollama y Claude devuelven salida estructurada, así que sólo
ellas pueden rellenar `citas[]` por diferencial. La ruta por defecto en producción es el HF
Space, que devuelve PROSA — y con ella el usuario recibía texto fundamentado en la
literatura recuperada sin ninguna forma de saber en qué se apoyaba. Grounding sin
atribución.

La solución es no dejar las fuentes en manos del modelo:

- Las `Fuente` se construyen desde los fragmentos que la recuperación entregó realmente,
  numerados igual que en el prompt. El modelo no puede inventarlas porque no las escribe.
- En prosa, el modelo sólo aporta el MARCADOR `[n]`. Un marcador fuera de rango se borra
  del texto (apuntaría a una fuente inexistente).
- En las rutas estructuradas, cada cita del modelo se resuelve contra un fragmento real;
  la que no se puede resolver se descarta, porque una cita no verificable es peor que
  ninguna: parece respaldo y no lo es.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from ..rag.retriever import Fragmento
from ..schemas import Fuente, InterpretacionClinica

log = logging.getLogger("morphos.citas")

_MARCADOR = re.compile(r"\[(\d{1,2})\]")
# Palabras demasiado genéricas para identificar un libro ("manual de medicina interna…").
_VACIAS = {"de", "del", "la", "el", "los", "las", "and", "of", "the", "en", "y"}


def construir_fuentes(fragmentos: list[Fragmento]) -> list[Fuente]:
    """Numera los fragmentos recuperados igual que `prompt._bloque_contexto_rag` (base 1)."""
    return [
        Fuente(
            indice=i,
            libro=f.libro,
            edicion=f.edicion,
            capitulo=f.capitulo,
            pagina=f.pagina,
            cita=f.cita(),
        )
        for i, f in enumerate(fragmentos, 1)
    ]


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes).strip()


def _tokens_libro(libro: str) -> list[str]:
    return [t for t in _normalizar(libro).split() if len(t) > 2 and t not in _VACIAS]


def resolver_cita(cita: str, fuentes: list[Fuente]) -> int | None:
    """Índice (base 1) de la fuente a la que se refiere una cita libre, o None.

    Acepta el marcador `[n]` y también el título del libro escrito por el modelo, que es lo
    que suele emitir aunque el prompt pida el número.
    """
    texto = cita.strip()
    marcador = _MARCADOR.search(texto)
    if marcador:
        indice = int(marcador.group(1))
        return indice if 1 <= indice <= len(fuentes) else None

    normalizada = _normalizar(texto)
    if not normalizada:
        return None
    mejor_indice, mejor_cobertura = None, 0.0
    for fuente in fuentes:
        tokens = _tokens_libro(fuente.libro)
        if not tokens:
            continue
        cobertura = sum(t in normalizada for t in tokens) / len(tokens)
        if cobertura > mejor_cobertura:
            mejor_indice, mejor_cobertura = fuente.indice, cobertura
    # 0.6 del título presente: tolera "Ettinger, Textbook of Vet. Internal Medicine, p. 812"
    # pero rechaza una cita a un libro que nunca se recuperó.
    return mejor_indice if mejor_cobertura >= 0.6 else None


def indices_citados(texto: str, n_fuentes: int) -> set[int]:
    """Marcadores `[n]` válidos presentes en la prosa."""
    return {i for m in _MARCADOR.findall(texto) if 1 <= (i := int(m)) <= n_fuentes}


def limpiar_marcadores_invalidos(texto: str, n_fuentes: int) -> str:
    """Borra los `[n]` que apuntan fuera del conjunto recuperado (incluye el caso n_fuentes=0,
    donde el modelo cita literatura que nunca se le dio)."""

    def _sustituir(m: re.Match[str]) -> str:
        return m.group(0) if 1 <= int(m.group(1)) <= n_fuentes else ""

    return re.sub(r"[ \t]+([.,;:])", r"\1", _MARCADOR.sub(_sustituir, texto)).strip()


def aplicar_atribucion(
    resultado: InterpretacionClinica, fragmentos: list[Fragmento]
) -> tuple[InterpretacionClinica, list[Fuente]]:
    """Devuelve (interpretación con citas verificadas, fuentes marcadas como citadas o no).

    No lanza nunca: la atribución es una mejora de la respuesta, no un requisito para
    entregarla.
    """
    fuentes = construir_fuentes(fragmentos)
    citados: set[int] = set()
    descartadas = 0

    # 1) Prosa: marcadores [n] del texto libre (única señal de la ruta HF Space).
    texto = limpiar_marcadores_invalidos(resultado.interpretacion, len(fuentes))
    citados |= indices_citados(texto, len(fuentes))
    resultado.interpretacion = texto

    # 2) Rutas estructuradas: cada cita se resuelve contra una fuente real o se descarta.
    for diferencial in resultado.diferenciales:
        verificadas: list[str] = []
        for cita in diferencial.citas:
            indice = resolver_cita(cita, fuentes)
            if indice is None:
                descartadas += 1
                continue
            citados.add(indice)
            texto_cita = fuentes[indice - 1].cita
            if texto_cita not in verificadas:
                verificadas.append(texto_cita)
        diferencial.citas = verificadas

    for fuente in fuentes:
        fuente.citada = fuente.indice in citados

    if descartadas:
        log.info("Descartadas %d cita(s) no verificables contra la literatura recuperada.", descartadas)
    return resultado, fuentes
