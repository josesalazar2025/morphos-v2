# Morphos — tareas de desarrollo y despliegue

.PHONY: help frontend-install frontend-test frontend-build backend-sync backend-test \
        ingest curar-indice dev lint evals evals-test evals-unit ragas revision retrieval-eval \
        docker-build publish-index fetch-index publish-books

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
	@echo "  curar-indice      Descarta índices alfabéticos y reetiqueta especie (ARGS=--aplicar)"
	@echo "  publish-index     Sube instance/rag_index al dataset privado del Hub"
	@echo "  fetch-index       Descarga el índice del Hub a instance/rag_index"
	@echo "  publish-books     Sube books/*.pdf al dataset privado (sólo para reingerir)"
	@echo "  evals             Suite de evaluación clínica (split dev, casos validados)"
	@echo "  evals-test        Igual sobre el split reservado (sólo antes de desplegar)"
	@echo "  evals-unit        Pruebas unitarias de los propios scripts de evals/"
	@echo "  ragas             Groundedness RAG con juez local gratuito (ARGS=--modelo …)"
	@echo "  revision          Hoja de revisión veterinaria de los casos pendientes"
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

# Pruebas unitarias de los scripts de evaluación (métricas, rúbrica, umbrales, dataset). No
# necesitan modelo, juez ni índice: son puras. Corren con el venv del backend porque los
# scripts importan `app.*`.
evals-unit:
	cd backend && uv run pytest -q ../evals/tests

# Requiere el grupo pesado 'rag'. Coloca los PDFs con licencia en books/ primero.
ingest:
	cd backend && uv sync --group rag && uv run --group rag python -m app.rag.ingest --fuente ../books --salida ../instance/rag_index

# Aplica data/rag_alcance.json a un índice YA construido: descarta el índice alfabético de los
# libros y reetiqueta `especie`. No reingiere ni recalcula vectores. Sin ARGS es un simulacro;
# ARGS=--aplicar escribe. Después hace falta publish-index.
curar-indice:
	cd backend && uv run --group rag python ../scripts/curar_indice.py $(ARGS)

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

# Los objetivos de evals se ejecutan DESDE backend/: es donde vive el proyecto uv, y sólo ahí
# `--group` instala algo (fuera de un proyecto uv lo ignora con un warning y las evals corren
# sin ragas ni langchain).
#
# Puerta por defecto: split de iteración (dev) y sólo casos con validación veterinaria.
evals:
	cd backend && uv run python ../evals/run_evals.py --simular

# Split reservado. Se mira en agregado antes de desplegar, NO para afinar prompts.
evals-test:
	cd backend && uv run python ../evals/run_evals.py --simular --split test

# Eval de recuperación RAG (A/B de embeddings × idioma de consulta). Requiere índice
# construido para la config activa (MORPHOS_RAG_EMBED_MODEL / MORPHOS_RAG_QUERY_LANG).
retrieval-eval:
	cd backend && uv run --group rag python ../evals/run_retrieval_eval.py

# Groundedness con Ragas (faithfulness / context precision-recall). Juez local gratuito;
# necesita el índice RAG y un archivo de predicciones reales (o --modelo).
ragas:
	cd backend && uv run --group rag --group evals python ../evals/run_ragas.py $(ARGS)

# Hoja de revisión veterinaria de los casos aún no validados del dataset dorado.
revision:
	cd backend && uv run python ../evals/revision.py

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
