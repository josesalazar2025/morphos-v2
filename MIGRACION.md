# Migración de Morphos — estado y guía

Modernización del stack según `PLAN_MODERNIZACION.md`. Decisiones: IA híbrida
(medGemma privado por defecto + Claude opcional), backend **Python/FastAPI con uv**,
frontend **incremental Vite + TypeScript**, despliegue en **HF Spaces** con índice RAG
horneado en la imagen (sin almacenamiento persistente de pago).

## Estructura nueva

```
frontend/          Vite + TS. Motor portado + suite de regresión (Vitest).
  src/analisis.ts    Puerto fiel de js/analisis.js (tipado).
  src/ia.ts          Cliente tipado de /api/interpret (render estructurado).
  tests/             27 pruebas dorada s del motor.
backend/           FastAPI (uv). IA estructurada, RAG, seguridad.
  app/schemas.py     Salida clínica estructurada (Pydantic) → elimina limpiarRespuesta.
  app/ai/            medgemma.py, claude.py, prompt.py, service.py.
  app/rag/           retriever.py (degrada sin índice), ingest.py.
  app/routers/       interpret.py, papers.py, auth.py.
  app/security/      authz, rate_limit, session, headers.
  tests/             15 pruebas (esquema, prompt, RAG, API+seguridad).
evals/             Dataset dorado + run_evals.py (puerta CI) + juez LLM + promptfoo.
books/             Corpus con licencia (gitignored). Ver books/README.md.
instance/          BD de usuarios + índice RAG (fuera del webroot; gitignored).
bridge/            Puente local (proyecto uv aparte): lee analizadores (ASTM/HL7 v2) en la
                   LAN de la clínica y reenvía a /api/lab/ingesta. Ver INTEGRACION_ANALIZADORES.md.
```

## Integración de analizadores de laboratorio

Fases 0-1 implementadas (ingesta de resultados de equipos → autorrelleno del formulario por
ID de muestra). Backend: `app/schemas_lab.py`, `app/lab/` (mapeo + almacén TTL),
`app/routers/lab.py`, `app/security/device.py` (auth por API key). Frontend: `lab-import.ts`
+ `form-inject.ts`. Puente: `bridge/`. Mapeos código→analito en `data/lab_mapeos/`. Detalle
y fases pendientes en **INTEGRACION_ANALIZADORES.md**.

## Cómo ejecutar

```bash
# Frontend: pruebas del motor y build
make frontend-install
make frontend-test          # 27/27
make frontend-build         # → dist/

# Backend: sync (uv) y pruebas
make backend-sync
make backend-test           # 15/15
make dev                    # uvicorn en :8000

# Evals (puerta de CI)
make evals                  # run_evals.py --simular → ✅/❌ + exit code

# RAG (cuando haya libros en books/)
make ingest                 # construye instance/rag_index con el grupo 'rag'

# Docker (multi-stage: build frontend + backend uv)
make docker-build
```

## Qué se ha implementado y verificado

- ✅ **Motor portado a TS** con 27 pruebas de regresión (parity con el JS original) y
  typecheck limpio. Es la red de seguridad de la migración.
- ✅ **Backend FastAPI** con **salida estructurada validada** (Pydantic) que sustituye la
  limpieza por regex; clientes **medGemma** (Ollama, plantilla de chat + `format` JSON
  Schema, sin inyección de `<unused95>`) y **Claude** (tool use). 15 pruebas verdes.
- ✅ **Seguridad**: `/api/interpret` y `/api/papers` requieren sesión (cerrado el acceso
  anónimo); CORS bloqueado; sesiones firmadas HttpOnly/SameSite/Secure; CSRF de doble
  token; throttling de login; validación de imágenes; cabeceras de seguridad; BD e índice
  RAG **fuera del webroot**. Verificado: 401 sin sesión, 403 sin CSRF, flujo completo OK.
- ✅ **RAG**: pipeline de ingesta + recuperador con citas que **degrada a modo sin-RAG**
  si faltan deps o índice (probado). Índice horneado en la imagen.
- ✅ **Evals**: dataset dorado, comprobaciones deterministas (recall diferenciales,
  cobertura, derivación, idioma, **seguridad tolerancia-cero**), juez LLM (Claude),
  promptfoo y **puerta de CI** (exit≠0 ante regresión) — verificado que bloquea.
- ✅ **Puente Node** que reusa `analisis.ts` como única fuente de verdad para generar los
  hallazgos deterministas en las evals.

## Hecho en el último incremento

- ✅ **Puerto TS de todos los módulos UI** (`ui`, `pdf-parser`, `main`, `auth`, `papers`,
  `tooltip`) + helper `dom.ts`. `auth.ts`/`papers.ts` usan los endpoints FastAPI.
- ✅ **`index.html` recableado** a `/frontend/src/main.ts` (Vite lo empaqueta). La app corre
  end-to-end sobre el stack nuevo — verificado en navegador: motor, PDF, registro/login
  real (sesión + CSRF) y el botón IA llamando a `/api/interpret`.

## Pendiente (siguiente incremento)

- **Retirar** `api/*.php` y `js/*.js` legacy: ya son código muerto (no se cargan). Borrado
  seguro cuando se confirme que no se necesitan de referencia.
- ✅ **Ruta de IA funcionando en vivo**: la ruta `medgemma` usa por defecto el HF Space
  (Gradio) donde está alojado el modelo — `app/ai/hf_space.py` porta el flujo de
  `hf_proxy.php` (upload → analyze → SSE) y envuelve el texto en el esquema. Verificado en
  navegador: interpretación real renderizada con el aviso de derivación. (Alternativas por
  config: Ollama local si se vacía `MORPHOS_HF_SPACE_URL`, o Claude con API key.)
- **Config ESLint/Prettier** (falta el archivo de configuración; ya está la dependencia).
- **Retriever RAG**: añadir búsqueda híbrida BM25 + rerank.
- **Ingesta real** de los libros con licencia (`make ingest`) y activar Ragas sobre el
  índice poblado.
- **Aumentar el dataset** de evals con más casos validados por veterinario.
- Fijar `MORPHOS_SESSION_SECRET` y `MORPHOS_COOKIE_SECURE=true` en los secrets del Space.
