"""Aplicación FastAPI de Morphos.

Sirve la API (auth, interpret, papers) y, en producción, los estáticos del frontend.
CORS bloqueado a los orígenes configurados (no '*'), rate limiting global, cabeceras de
seguridad y montaje de sólo los directorios públicos (nunca instance/ ni backend/.env).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from .config import RAIZ_REPO, obtener_config
from .db import inicializar_db
from .routers import auth, interpret, lab, papers
from .security.headers import CabecerasSeguridad
from .security.rate_limit import limiter

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    inicializar_db()
    _recargar_resultados_lab()
    _verificar_rag()
    yield


def _verificar_rag() -> None:
    """Comprueba el RAG al arrancar y distingue las causas de fallo.

    El retriever degrada a modo sin-RAG en silencio por diseño (para que la app funcione sin el
    corpus), pero eso hace indistinguible «no hay RAG a propósito» de «el RAG está roto y las
    interpretaciones van sin fundamentar». Aquí se rompe esa ambigüedad con un log explícito.
    """
    log = logging.getLogger("morphos.rag")
    cfg = obtener_config()

    if not cfg.rag_habilitado:
        log.info("RAG deshabilitado por configuración (MORPHOS_RAG_HABILITADO=false).")
        return

    faltan_deps = False
    try:
        import lancedb  # type: ignore  # noqa: F401
        import sentence_transformers  # type: ignore  # noqa: F401
    except ImportError:
        faltan_deps = True

    from .rag.retriever import estado_rag

    estado = estado_rag()

    if faltan_deps:
        log.error(
            "RAG ACTIVADO PERO SIN DEPENDENCIAS: falta el grupo 'rag' (lancedb / "
            "sentence-transformers). Las interpretaciones saldrán SIN fundamentar. "
            "Construye la imagen con --build-arg WITH_RAG=1 o ejecuta 'uv sync --group rag'."
        )
        return

    if not estado["disponible"]:
        log.error(
            "RAG ACTIVADO PERO SIN ÍNDICE en %s. Las interpretaciones saldrán SIN fundamentar. "
            "Ejecuta 'make fetch-index' (o 'make ingest' si tienes los libros).",
            cfg.rag_index_dir,
        )
        return

    log.info(
        "RAG listo: %s fragmentos, embeddings %s, híbrido=%s, rerank=%s.",
        estado["fragmentos"],
        estado["modelo"],
        cfg.rag_hibrido,
        cfg.rag_rerank,
    )


def _recargar_resultados_lab() -> None:
    """Si la persistencia de laboratorio está activa, recarga el almacén en proceso desde SQLite
    (útil sólo con volumen persistente; en HF Spaces la BD es efímera). Degrada en silencio."""
    if not obtener_config().lab_persistir:
        return
    try:
        from . import db
        from .lab.almacen import almacen
        from .schemas_lab import ResultadoMapeado

        for payload in db.cargar_resultados_lab():
            almacen.guardar(ResultadoMapeado.model_validate_json(payload))
    except Exception:  # noqa: BLE001 — nunca bloquear el arranque por esto
        logging.getLogger("morphos").warning("no se pudieron recargar resultados de laboratorio", exc_info=True)


def crear_app() -> FastAPI:
    cfg = obtener_config()
    app = FastAPI(title="Morphos API", version="1.0.0", lifespan=_lifespan)

    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _limite(_request, exc: RateLimitExceeded):  # noqa: ANN001
        return JSONResponse(
            status_code=429,
            content={"error": "Demasiadas peticiones. Inténtalo más tarde."},
            headers={"Retry-After": "60"},
        )

    # CORS bloqueado a orígenes conocidos, con credenciales (cookies de sesión).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.origenes_permitidos,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(CabecerasSeguridad)

    app.include_router(auth.router, prefix="/api")
    app.include_router(interpret.router, prefix="/api")
    app.include_router(lab.router, prefix="/api")
    app.include_router(papers.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict:
        from .rag.retriever import estado_rag

        return {"ok": True, "entorno": cfg.entorno, "rag": estado_rag()}

    # Estáticos: sólo directorios públicos. Los datos de referencia (data/*.json) se
    # sirven en /data; la build del frontend (dist/) en la raíz. instance/ (BD) y
    # backend/.env quedan SIEMPRE fuera de cualquier montaje.
    datos = RAIZ_REPO / "data"
    if datos.exists():
        app.mount("/data", StaticFiles(directory=str(datos)), name="data")

    dist = RAIZ_REPO / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")

    return app


app = crear_app()
