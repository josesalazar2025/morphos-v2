# syntax=docker/dockerfile:1

# ---------- Stage 1: build del frontend (Vite + TS) ----------
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package*.json frontend/
RUN cd frontend && npm ci
# Se necesita el HTML/CSS de la raíz y los datos para la build.
COPY frontend/ frontend/
COPY index.html ./
COPY css/ css/
COPY assets/ assets/
COPY data/ data/
RUN cd frontend && npm run build   # emite /build/dist

# ---------- Stage 2: runtime backend (FastAPI + uv) ----------
FROM python:3.12-slim AS runtime

# uv desde su imagen oficial (rápido y reproducible).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Instala dependencias con el lockfile (capa cacheable). RAG viene ACTIVADO por defecto: con
# WITH_RAG=0 el retriever degrada en silencio y las interpretaciones salen sin fundamentar, que
# es justo el fallo que no queremos que pase inadvertido en producción.
ARG WITH_RAG=1
COPY backend/pyproject.toml backend/uv.lock* backend/
RUN cd backend && if [ "$WITH_RAG" = "1" ]; then \
      uv sync --frozen --no-dev --group rag; \
    else \
      uv sync --frozen --no-dev; \
    fi

# Código del backend
COPY backend/ backend/

# Estáticos públicos: build del frontend + datos de referencia (servidos en /data)
COPY --from=frontend /build/dist ./dist
COPY data/ ./data/

# Índice RAG horneado de sólo lectura. Vive en instance/ (fuera del webroot); no requiere
# almacenamiento persistente. La BD de usuarios (instance/*.db) queda EXCLUIDA vía
# .dockerignore: nunca se hornea.
#
# Dos vías: si instance/rag_index existe en el contexto de build se copia; si no (clon limpio,
# CI), se descarga del dataset PRIVADO del Hub con HF_TOKEN pasado como secreto de build.
COPY instance* ./instance/

# Se usa la API de Python y NO el CLI `hf`: en huggingface_hub 1.16.1 el CLI devuelve código 1
# aunque la operación vaya bien (incompatibilidad typer/click), lo que abortaría la build.
ARG HF_INDEX_REPO=blackmistcode/morphos-rag-index
RUN --mount=type=secret,id=hf_token,required=false \
    if [ "$WITH_RAG" = "1" ] && [ ! -d /app/instance/rag_index ]; then \
      if [ -f /run/secrets/hf_token ]; then \
        HF_TOKEN="$(cat /run/secrets/hf_token)" backend/.venv/bin/python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download(repo_id='$HF_INDEX_REPO', repo_type='dataset', local_dir='/app/instance/rag_index')"; \
      else \
        echo "AVISO: sin instance/rag_index y sin secreto hf_token; la imagen quedará SIN RAG." >&2; \
      fi; \
    fi

# Modelos de embeddings y reranking horneados en la imagen (~6.4 GB). Sin esto, la primera
# petición intentaría descargarlos de huggingface.co en caliente: lento en CPU-basic y, si la
# red falla, el reranker cae en silencio a orden RRF. Con HF_HUB_OFFLINE=1 en runtime, una
# descarga que faltase falla de forma ruidosa en vez de degradar sin avisar.
ARG RAG_EMBED_MODEL=BAAI/bge-m3
ARG RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ENV HF_HOME=/opt/hf
RUN if [ "$WITH_RAG" = "1" ]; then \
      backend/.venv/bin/python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('$RAG_EMBED_MODEL'); CrossEncoder('$RAG_RERANKER_MODEL')"; \
    fi

ENV MORPHOS_ENTORNO=prod \
    MORPHOS_COOKIE_SECURE=true \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    PATH="/app/backend/.venv/bin:$PATH"

# HF Spaces expone el 7860.
EXPOSE 7860

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "7860"]
