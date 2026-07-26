# Morphos — tareas de desarrollo y despliegue

.PHONY: help frontend-install frontend-test frontend-build backend-sync backend-test \
        ingest dev lint evals retrieval-eval docker-build \
        publish-index fetch-index publish-books

# Los repos del Hub se declaran en scripts/hub.py (y deben coincidir con rag_index_repo /
# rag_books_repo en backend/app/config.py).

help:
	@echo "Objetivos disponibles:"
	@echo "  frontend-install  Instala dependencias del frontend (npm)"
	@echo "  frontend-test     Ejecuta la suite de regresión del motor (vitest)"
	@echo "  frontend-build    Compila el frontend a dist/"
	@echo "  backend-sync      Sincroniza dependencias del backend (uv)"
	@echo "  backend-test      Ejecuta pytest del backend"
	@echo "  ingest            Construye el índice RAG desde books/ (grupo rag, local)"
	@echo "  publish-index     Sube instance/rag_index al dataset privado del Hub"
	@echo "  fetch-index       Descarga el índice del Hub a instance/rag_index"
	@echo "  publish-books     Sube books/*.pdf al dataset privado (sólo para reingerir)"
	@echo "  evals             Ejecuta la suite de evaluación clínica"
	@echo "  dev               Levanta el backend FastAPI en local"
	@echo "  lint              Ruff (backend) + eslint (frontend)"
	@echo "  docker-build      Construye la imagen de despliegue"

frontend-install:
	cd frontend && npm install

frontend-test:
	cd frontend && npm test

frontend-build:
	cd frontend && npm run build

backend-sync:
	cd backend && uv sync

backend-test:
	cd backend && uv run pytest -q

# Requiere el grupo pesado 'rag'. Coloca los PDFs con licencia en books/ primero.
ingest:
	cd backend && uv sync --group rag && uv run --group rag python -m app.rag.ingest --fuente ../books --salida ../instance/rag_index

# --- Distribución del índice y del corpus (Hub privado) -----------------------------------
#
# El índice es un artefacto derivado de libros con licencia: contiene su texto troceado, así que
# se publica SIEMPRE en un repo privado (--private) y nunca se comitea (instance/ está en
# .gitignore). Los libros viven en su propio repo privado y sólo hacen falta para reingerir.

publish-index:
	cd backend && uv run --group rag python ../scripts/hub.py publish-index

fetch-index:
	cd backend && uv run --group rag python ../scripts/hub.py fetch-index

# Los PDFs no entran nunca en git ni en la imagen; este repo privado es sólo su respaldo y la
# fuente para reingerir.
publish-books:
	cd backend && uv run --group rag python ../scripts/hub.py publish-books

# NOTA: la ingesta en infra HF con GPU (`hf jobs uv run`) queda pendiente. Requiere que el
# paquete `app` esté disponible en el runner (publicar el backend como paquete o construir una
# imagen con las dependencias del grupo rag); no es un one-liner. Como reingerir sólo hace falta
# cuando cambia el corpus (dos veces al año), `make ingest` en local cubre el caso hoy.

evals:
	cd evals && uv run --group evals python run_evals.py

# Eval de recuperación RAG (A/B de embeddings × idioma de consulta). Requiere índice
# construido para la config activa (MORPHOS_RAG_EMBED_MODEL / MORPHOS_RAG_QUERY_LANG).
retrieval-eval:
	cd evals && uv run --group evals python run_retrieval_eval.py

dev:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

# Cubre backend (app + tests) y scripts/. evals/ y bridge/ quedan fuera a propósito: aún no
# están saneados bajo estas reglas y meterlos ahora dejaría el lint en rojo permanente.
lint:
	cd backend && uv run ruff check . ../scripts
	cd frontend && npm run lint

# Si instance/rag_index existe en local, se hornea directamente. Si no (clon limpio o CI), la
# build lo descarga del dataset privado: exporta HF_TOKEN y se pasa como secreto de build (no
# como --build-arg, que quedaría grabado en el historial de capas de la imagen).
docker-build:
	@if [ -n "$$HF_TOKEN" ]; then \
		printf '%s' "$$HF_TOKEN" | docker build --secret id=hf_token,src=/dev/stdin -t morphos:latest . ; \
	else \
		echo "AVISO: HF_TOKEN no definido; la build sólo tendrá RAG si instance/rag_index existe en local."; \
		docker build -t morphos:latest . ; \
	fi
