"""Recuperación RAG con citas verificables.

Diseñado para degradar con elegancia: si las dependencias pesadas (lancedb,
sentence-transformers) no están instaladas, o el índice aún no se ha construido
(los libros con licencia se ingieren después), devuelve una lista vacía y el
servicio de IA continúa en modo sin-RAG.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from ..config import obtener_config

log = logging.getLogger("morphos.rag")


@dataclass
class Fragmento:
    """Un fragmento recuperado con su procedencia para citar.

    `score` es una RELEVANCIA con orientación consistente «mayor = más relevante», tomada
    de la mejor señal disponible (rerank del cross-encoder > RRF > distancia densa negada).
    No mezclar como si fuera una distancia.
    """

    texto: str
    libro: str
    edicion: str
    capitulo: str
    pagina: str
    score: float

    def cita(self) -> str:
        partes = [self.libro]
        if self.edicion:
            partes.append(self.edicion)
        if self.pagina:
            partes.append(f"p. {self.pagina}")
        return ", ".join(partes)


def _relevancia(fila: dict) -> float:
    """Relevancia consistente (mayor = más relevante) desde la mejor señal disponible.
    Corrige el bug de mezclar `_relevance_score`/`_distance` (métricas incomparables)."""
    if "_rerank_score" in fila:
        return float(fila["_rerank_score"])
    if "_rrf_score" in fila:
        return float(fila["_rrf_score"])
    distancia = fila.get("_distance")
    return -float(distancia) if distancia is not None else 0.0


def _index_disponible() -> bool:
    cfg = obtener_config()
    # LanceDB guarda tablas como directorios .lance dentro de rag_index_dir.
    return cfg.rag_index_dir.exists() and any(cfg.rag_index_dir.glob("*.lance"))


def estado_rag() -> dict:
    """Estado del subsistema RAG para /api/health. Barato (lee el manifiesto, no carga
    modelos ni la tabla) y nunca lanza."""
    cfg = obtener_config()
    try:
        if not cfg.rag_habilitado or not _index_disponible():
            return {"disponible": False, "fragmentos": None, "modelo": cfg.rag_embed_model}
        fragmentos = None
        manifiesto = cfg.rag_index_dir / "manifest.json"
        if manifiesto.exists():
            fragmentos = json.loads(manifiesto.read_text(encoding="utf-8")).get("n_fragmentos")
        return {"disponible": True, "fragmentos": fragmentos, "modelo": cfg.rag_embed_model}
    except Exception as exc:  # noqa: BLE001 — health nunca debe fallar
        log.warning("estado_rag falló: %s", exc)
        return {"disponible": False, "fragmentos": None, "modelo": cfg.rag_embed_model}


@lru_cache
def _cargar_recursos():
    """Carga perezosa del modelo de embeddings y la tabla LanceDB.

    Se aísla en try/except para que la ausencia de dependencias no rompa el arranque.
    """
    cfg = obtener_config()
    try:
        import lancedb  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        log.info("Dependencias RAG no instaladas; modo sin-RAG.")
        return None

    if not _index_disponible():
        log.info("Índice RAG vacío en %s; modo sin-RAG.", cfg.rag_index_dir)
        return None

    modelo = SentenceTransformer(cfg.rag_embed_model)
    db = lancedb.connect(str(cfg.rag_index_dir))
    tabla = db.open_table("literatura")
    return modelo, tabla


@lru_cache
def _cargar_reranker():
    """Carga perezosa del cross-encoder de reranking; None si no está disponible."""
    cfg = obtener_config()
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        return CrossEncoder(cfg.rag_reranker_model)
    except Exception as exc:  # noqa: BLE001
        log.info("Reranker no disponible (%s); se usará el orden RRF.", exc)
        return None


def _clave_fila(fila: dict) -> str:
    """Clave estable para deduplicar/fusionar una fila entre búsquedas (densa y léxica)."""
    return f"{fila.get('libro', '')}|{fila.get('pagina', '')}|{fila.get('texto', '')[:64]}"


def fusion_rrf(listas: list[list[dict]], n: int, k_rrf: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: combina varias listas rankeadas en ranks (no en scores crudos,
    que son incomparables entre búsqueda densa y léxica). score = Σ 1/(k_rrf + rango)."""
    puntajes: dict[str, float] = {}
    filas_por_clave: dict[str, dict] = {}
    for lista in listas:
        for rango, fila in enumerate(lista):
            clave = _clave_fila(fila)
            puntajes[clave] = puntajes.get(clave, 0.0) + 1.0 / (k_rrf + rango)
            filas_por_clave.setdefault(clave, fila)
    ordenadas = sorted(puntajes, key=lambda c: puntajes[c], reverse=True)
    salida = []
    for c in ordenadas[:n]:
        fila = filas_por_clave[c]
        fila["_rrf_score"] = puntajes[c]  # se propaga a Fragmento.score si no hay rerank
        salida.append(fila)
    return salida


def _buscar_vectorial(tabla, modelo, consulta: str, n: int) -> list[dict]:
    vector = modelo.encode(consulta, normalize_embeddings=True).tolist()
    return tabla.search(vector).limit(n).to_list()


def _buscar_lexico(tabla, consulta: str, n: int) -> list[dict]:
    """Búsqueda léxica BM25 (FTS). Devuelve [] si no hay índice FTS en la tabla."""
    try:
        return tabla.search(consulta, query_type="fts").limit(n).to_list()
    except Exception as exc:  # noqa: BLE001
        log.info("FTS no disponible (%s); híbrido degrada a vectorial.", exc)
        return []


def _recuperar_candidatos(cfg, tabla, modelo, consulta: str, n: int) -> list[dict]:
    """Pozo de candidatos: densa + léxica fusionadas con RRF, o sólo densa si no hay híbrido."""
    densa = _buscar_vectorial(tabla, modelo, consulta, n)
    if not cfg.rag_hibrido:
        return densa
    lexica = _buscar_lexico(tabla, consulta, n)
    if not lexica:
        return densa
    return fusion_rrf([densa, lexica], n)


def _reordenar(consulta: str, filas: list[dict], k: int) -> list[dict]:
    """Reordena los candidatos con el cross-encoder y devuelve los k mejores; si el reranker
    no está disponible, conserva el orden de entrada (RRF)."""
    reranker = _cargar_reranker()
    if reranker is None or not filas:
        return filas[:k]
    try:
        pares = [(consulta, f.get("texto", "")) for f in filas]
        puntajes = reranker.predict(pares)
        # strict=True: `puntajes` sale de `pares`, que sale de `filas`, así que las longitudes
        # coinciden por construcción. Si el reranker devolviera menos puntajes, sin strict se
        # perderían fragmentos en silencio; con strict el except de abajo cae al orden RRF.
        for fila, puntaje in zip(filas, puntajes, strict=True):
            fila["_rerank_score"] = float(puntaje)  # se propaga a Fragmento.score
        ordenadas = [
            f
            for _, f in sorted(
                zip(puntajes, filas, strict=True), key=lambda p: p[0], reverse=True
            )
        ]
        return ordenadas[:k]
    except Exception as exc:  # noqa: BLE001
        log.warning("Fallo en reranking (%s); se usa el orden RRF.", exc)
        return filas[:k]


def recuperar(
    consulta: str,
    especie: str | None = None,
    top_k: int | None = None,
) -> list[Fragmento]:
    """Devuelve fragmentos relevantes: recuperación híbrida (densa+léxica, RRF) + reranking
    cross-encoder, filtrada por especie.

    Nunca lanza: ante cualquier fallo o índice ausente, devuelve [].
    """
    cfg = obtener_config()
    if not cfg.rag_habilitado or not consulta.strip():
        return []

    recursos = _cargar_recursos()
    if recursos is None:
        return []

    modelo, tabla = recursos
    k = top_k or cfg.rag_top_k
    if cfg.rag_query_lang == "en":
        from .traduccion_consulta import traducir_consulta

        consulta = traducir_consulta(consulta, "en")

    try:
        candidatos = _recuperar_candidatos(cfg, tabla, modelo, consulta, cfg.rag_candidatos)
    except Exception as exc:  # noqa: BLE001 — la recuperación nunca debe tumbar la interpretación
        log.warning("Fallo en recuperación RAG: %s", exc)
        return []

    # Filtrado por especie ANTES de reordenar (metadato 'especie' opcional).
    if especie:
        candidatos = [
            f for f in candidatos
            if not (f.get("especie") or "") or (f.get("especie") or "").lower() == especie.lower()
        ]

    mejores = _reordenar(consulta, candidatos, k) if cfg.rag_rerank else candidatos[:k]

    return [
        Fragmento(
            texto=f.get("texto", ""),
            libro=f.get("libro", ""),
            edicion=f.get("edicion", ""),
            capitulo=f.get("capitulo", ""),
            pagina=str(f.get("pagina", "")),
            score=_relevancia(f),
        )
        for f in mejores
    ]


def construir_consulta(patrones: list[str], hallazgos: list[str]) -> str:
    """Arma la consulta de recuperación a partir de los patrones y hallazgos del paciente."""
    terminos = [*patrones, *hallazgos]
    return " ; ".join(t for t in terminos if t)[:512]
