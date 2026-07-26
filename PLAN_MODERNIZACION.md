# Morphos — Modernization, AI/RAG, Evals & Security Plan

> ## Estado de implementación (auditoría 2026-07-26)
>
> Leyenda: ✅ hecho y verificado · 🟡 parcial (núcleo hecho, falta un subpunto) · ⬜ pendiente
>
> | Fase | Estado | Resumen |
> |---|---|---|
> | 1 — Frontend (Vite/TS) | ✅ | **Todos** los módulos portados a TS (analisis, ui, pdf-parser, auth, papers, main, tooltip, ia); `index.html` recableado al bundle TS; 32 tests ✅. Menor: falta archivo de config ESLint/Prettier. |
> | 2 — Capa IA (FastAPI) | ✅ | Endpoints, salida estructurada, clientes medGemma/Claude, prompt endurecido, validación imágenes. Orquestación con `ClienteModelo` propio (no la librería Pydantic AI). |
> | 3 — RAG | ✅ | Ingesta + retriever con citas + degradación ✅. **Nuevo:** búsqueda híbrida (denso + BM25/FTS fusionados con RRF) + rerank cross-encoder `bge-reranker-v2-m3`, ambos conmutables; traducción ES→EN de consulta. **Corpus real ingerido**: 6763 fragmentos de 2 libros en `instance/rag_index/` (LanceDB, 69 MB, bge-m3). |
> | 4 — Evals | 🟡 | Dataset dorado (17 casos), juez clínico, promptfoo, puerta CI ✅ (bloqueo verificado), arnés de evaluación de recuperación aislada (`run_retrieval_eval.py`). Faltan: **código Ragas (0 líneas)**, human-in-the-loop, split reservado, informe por-ruta/por-corpus. |
> | 5 — Seguridad | ✅ | Guarda auth, rate limit, CORS, CSRF, BD/RAG fuera del webroot, cabeceras, validación imágenes — verificado. Menor: rate limit por-usuario y redirección HTTP→HTTPS. |
>
> **Verificado ejecutando (2026-07-26):** 32 tests frontend (Vitest), **97 tests backend**
> (pytest, incluye retriever híbrido + integración con índice real + ingesta/troceo +
> traducción de consulta), ruff limpio, typecheck limpio. Previamente verificado en el
> navegador contra el backend FastAPI: motor de patrones (anemia microcítica), import de PDF
> (parser TS portado), registro/login real (sesión + CSRF), y el botón "Análisis IA"
> llamando a `POST /api/interpret` con token CSRF. Puerta de evals bloquea (exit≠0), 401 sin
> sesión, 403 sin CSRF. **No verificado en vivo:** salida estructurada renderizada con un
> modelo real (falta `ollama pull` de medGemma), promptfoo ejecutado, rechazo CORS de
> orígenes externos, 429 bajo carga, `/security-review`.
>
> **Fuera de este plan:** la integración de analizadores de laboratorio (ASTM/HL7) ha
> avanzado en paralelo — `backend/app/routers/lab.py`, `bridge/`, `data/lab_mapeos/`,
> `tests/test_lab_*.py`, `frontend/tests/lab-import.test.ts`. Ver `INTEGRACION_ANALIZADORES.md`.
>
> **Legacy pendiente de retirar:** los 8 `js/*.js` y los 5 `api/*.php` siguen en el repo pero
> YA NO se cargan (`index.html` no referencia ninguno). Son código muerto a eliminar.
>
> ### Lo que queda, en orden sugerido
> 1. **Borrar el legacy** `js/` + `api/` — riesgo cero, ya es código muerto.
> 2. **Ragas + split reservado**, y ejecutar la suite completa de evals contra el índice real
>    — el mayor valor pendiente, y ya desbloqueado por el corpus ingerido.
> 3. Config ESLint/Prettier; rate limit por-usuario en `/api/interpret`; informe de evals
>    por-ruta-de-modelo y por-versión-de-corpus.
> 4. Human-in-the-loop (mayor alcance, requiere decisiones de producto).
>
> Ver detalle marcado por tarea abajo y `MIGRACION.md` para el siguiente incremento.

## Context

Morphos is a veterinary diagnostic-support SPA (canine/feline) that detects clinical
patterns from lab values in real time and optionally asks an AI model (medGemma 1.5 4B
via a HuggingFace Gradio Space, or local Ollama) for a clinical interpretation. It ships
as vanilla JS (no build step) + thin PHP proxies, deployed as Docker on HF Spaces.

The app works, but three things block it from being a trustworthy diagnostic assistant:

1. **The AI layer fights the model instead of controlling it.** `js/ia.js` builds the
   prompt by string concatenation, injects a raw `<unused95>` control token, and post-
   processes output through `limpiarRespuesta()` — ~70 lines of regex hacks stripping
   control tokens, English-only reasoning, LaTeX, and looped paragraphs. These are
   symptoms of an uncontrolled inference path (raw Gradio Space, no chat template, no
   structured output, no grounding).
2. **There are zero evals.** For a tool that suggests differentials on real patients,
   there is no measurement of accuracy, groundedness, or safety. This is the highest-risk
   gap.
3. **Security holes**: the AI and papers proxies are unauthenticated with open CORS
   (anyone can call `api/hf_proxy.php` and burn the HF key), there is no rate limiting
   anywhere, the SQLite DB with password hashes may be web-reachable, and MySQL defaults
   to `root`/empty-password.

The vet-validated pattern engine (`js/analisis.js`, `data/*.json`) is the crown jewel and
must be preserved exactly through the migration.

### Decisions (confirmed with the user)

- **AI model strategy: Hybrid.** Keep self-hosted medGemma/Ollama as the private default;
  add an optional hosted frontier-model (Claude) route for higher accuracy. The eval judge
  always uses a strong model.
- **Backend: Python FastAPI** for the AI/RAG/eval service (best ecosystem).
- **Frontend: Incremental.** Add Vite + TypeScript, port modules (especially `analisis.js`)
  to typed TS with unit tests, keep the existing DOM UI. No React rewrite.
- **Hosting: stay on HF Spaces (PRO).** Because the RAG corpus is static licensed books,
  build the vector index offline and bake it read-only into the Docker image — **no paid
  persistent storage needed**. App Space (CPU-basic, FastAPI + static assets) + the existing
  ZeroGPU medGemma Space + optional Claude route.

> **HF hosting check:** Free Spaces have an ephemeral filesystem; persistent storage is a
> paid add-on ($5/mo for 20 GB up). PRO ($9/mo) gives 10 ZeroGPU/Docker Spaces + 1 TB repo
> storage. Since the RAG corpus is static, the vector index is baked into the image and
> needs no persistent-storage purchase — the plan fits inside the PRO subscription.

---

## Target Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  App Space (HF, CPU-basic, Docker)                               │
│                                                                  │
│  Frontend (Vite build → static)          Backend (FastAPI)       │
│  ├─ analisis.ts  (ported engine, tested) ├─ /api/auth   (session)│
│  ├─ ui.ts / pdf-parser.ts / papers.ts    ├─ /api/interpret (AI)  │
│  └─ ia.ts (calls /api/interpret)         ├─ /api/papers  (PubMed)│
│                                          ├─ RAG retriever        │
│                                          │   └─ baked vector idx │
│                                          └─ rate limit + authz   │
│                                                                  │
│  Persistence: SQLite (users) outside webroot                     │
└───────────────┬──────────────────────────────┬──────────────────┘
                │ hybrid route                  │
     ┌──────────▼─────────┐          ┌──────────▼──────────┐
     │ medGemma ZeroGPU   │          │ Claude API (opt.)   │
     │ Space (private)    │          │ (higher accuracy)   │
     └────────────────────┘          └─────────────────────┘
```

Monorepo layout after migration:

```
morphos/
├── frontend/         # Vite + TS; ported js/ modules, unit tests (Vitest)
├── backend/          # FastAPI: auth, interpret, papers, rag, security
│   ├── app/
│   │   ├── main.py            # FastAPI app, middleware (CORS, rate limit)
│   │   ├── routers/           # auth.py, interpret.py, papers.py
│   │   ├── ai/                # model clients (medgemma, claude), prompt, schema
│   │   ├── rag/               # ingestion, chunking, embeddings, retriever
│   │   └── security/          # authz deps, rate limiter, session
│   └── tests/
├── evals/            # golden dataset, promptfoo + Ragas configs, CI gate
├── data/             # valores_referencia.json, alteraciones.json (unchanged)
│   └── rag_index/    # baked vector index (built in CI, shipped read-only)
├── Dockerfile        # multi-stage: build frontend + index, run FastAPI+static
└── docker-entrypoint.sh
```

---

## Phase 1 — Frontend modernization (incremental, low risk) — ✅ (salvo config ESLint)

Goal: add tooling and types **without changing behavior**. The engine is vet-validated;
migration must be behavior-preserving and proven so by tests.

- 🟡 Introduce `frontend/` with **Vite + TypeScript + Vitest**. Add `package.json`,
  `tsconfig.json`, ESLint/Prettier. Keep Spanish naming per `CLAUDE.md`; no alignment
  spaces; no `!important` in CSS.
  — *Vite + TS + Vitest ✅ (`frontend/package.json`, `tsconfig.json`, `vite.config.ts`).
  Falta: no hay archivo de config ESLint/Prettier (sólo la dependencia y el script `lint`).*
- ✅ Port `js/analisis.js` → `frontend/src/analisis.ts` first. It is pure/stateless (single
  export `analizarResultados`), so it types cleanly and is fully unit-testable. **Write a
  golden test suite** that pins current behavior (severity classification, age/breed/sex
  adjustments, all ~60 pattern rules) using fixtures derived from `data/*.json`. This suite
  doubles as the regression net for the whole migration.
  — *`analisis.ts` + `tipos.ts` + 27 tests Vitest (32 en total con `lab-import.test.ts`),
  typecheck limpio. Verificado.*
- ✅ Port remaining modules (`main.js`, `ui.js`, `ia.js`, `pdf-parser.js`, `auth.js`,
  `papers.js`, `tooltip.js`) to `.ts`. Preserve the getter-callback wiring in `main.js` and
  the `imagenesDataUrl` / `capturasMicroscopio` shared arrays in `ui.js`.
  — *Todos portados (`frontend/src/*.ts`) + helper `dom.ts`. Typecheck limpio; verificados
  en el navegador (motor, PDF, auth). `auth.ts`/`papers.ts` apuntan a los endpoints nuevos.*
- ✅ Keep `index.html` markup and `css/styles.css` as-is initially; wire the Vite-built bundle
  in place of the `?v=N` module tag. Remove the leftover `console.log` debug blocks in
  `ia.js`.
  — *`index.html` carga `/frontend/src/main.ts` (Vite lo empaqueta). El `ia.js` legacy ya no
  se carga (código muerto); el nuevo `ia.ts` no tiene `console.log`.*
- ✅ Update stale `CLAUDE.md` facts (analisis.js is 817 lines / 90 analytes / 78 clinical
  entities; auth + papers layers exist).

Files: new `frontend/**`; modify `index.html` script tag; delete debug logging in `ia.js`.

---

## Phase 2 — AI layer rebuilt on FastAPI (replaces the PHP proxy + regex cleanup) — ✅

Goal: a controlled, model-agnostic inference path with **structured, validated output**,
so `limpiarRespuesta()` becomes unnecessary.

- ✅ New FastAPI service (`backend/`). Replace `api/hf_proxy.php` with `POST /api/interpret`
  and `api/papers_proxy.php` with `GET /api/papers`. Keep the PubMed disk-cache logic
  (port `papers_proxy.php` behavior). Keep `api/auth.php` semantics but reimplement in
  FastAPI (Phase 5 hardens it).
  — *Endpoints creados; caché de PubMed portada; auth reimplementada. Los `.php` legacy aún
  no se han borrado (siguen en `api/`) — retirada pendiente hasta migrar la UI.*
- 🟡 **Orchestration: Pydantic AI** (model-agnostic, typed, structured outputs). Define a
  `ModelClient` interface with two implementations: `MedGemmaClient` (self-hosted default;
  talk to the ZeroGPU Space / Ollama using the **proper chat template**, not raw
  `<unused95>` injection) and `ClaudeClient` (hybrid opt-in via the Anthropic SDK). Backend
  selection replaces the current `localStorage` `mx-ia-backend` toggle and is enforced
  server-side.
  — *Desviación: se implementó un protocolo `ClienteModelo` propio (`app/ai/base.py`) con
  `MedGemmaClient` + `ClaudeClient` y selección server-side, en vez de la librería Pydantic
  AI. Cumple el objetivo (salida tipada/validada) con menos dependencias.*
- ✅ **Structured output schema** (Pydantic) — the core fix. Instead of free text, the model
  returns:
  `interpretacion` (es), `hallazgos_clave[]` (analyte, direccion, gravedad),
  `diferenciales[]` (nombre, probabilidad, evidencia[], citas[] → RAG sources),
  `siguientes_pruebas[]`, `confianza`, `requiere_derivacion` (safety flag), `idioma="es"`.
  Enforce with structured/JSON output; validate server-side; on validation failure, retry
  or return a typed error — **never** ship unparsed model text. This deletes the entire
  `limpiarRespuesta` regex pile.
  — *`app/schemas.py::InterpretacionClinica`; reintento + error tipado en `service.py`.*
- ✅ Prompt construction moves server-side into `backend/app/ai/prompt.py`, assembled from
  patient data + flagged findings + detected patterns (reuse the enrichment already in
  `construirPrompt`) + **retrieved RAG context** (Phase 3). System prompt hardened: Spanish-
  only, scope limits, mandatory hedging/deferral language, citation requirement,
  injection resistance for free-text `signos-clinicos` and citology images.
- ✅ Vision path preserved: medGemma multimodal for citology images; keep the 1024px client
  resize and ≤4 images limit, but validate size/count/mime server-side (Phase 5).
- ✅ Frontend `ia.ts` becomes a thin typed client of `/api/interpret` that renders the
  structured result (findings, ranked differentials **with citations**, next steps, a
  visible "requiere derivación veterinaria" banner when flagged).
  — *Código completo (`frontend/src/ia.ts`), cableado vía el bundle TS y ejercitado en el
  navegador. Falta ver el render con salida de un modelo real (`ollama pull` pendiente).*

Files: new `backend/app/ai/**`, `backend/app/routers/interpret.py`, `.../papers.py`;
rewrite `frontend/src/ia.ts`; remove `api/hf_proxy.php`, `api/papers_proxy.php`.

---

## Phase 3 — RAG layer (structure now; books ingested later) — ✅

Goal: ground interpretations in the licensed veterinary literature with **verifiable
citations**, built so the corpus can be dropped in when provided.

- ✅ **Stack:** LlamaIndex for ingestion/retrieval; **LanceDB** (embedded, file-based → bakes
  cleanly into the image, zero runtime services) as the vector store. Embeddings via a
  **self-hosted multilingual model** (e.g. BGE-M3 through `sentence-transformers`) to keep
  the privacy positioning — no document content leaves the box at index time.
  — *Dependencias en el grupo `rag` de `pyproject.toml`; ingesta usa pypdf +
  sentence-transformers + lancedb directamente (llama-index-core disponible).*
- ✅ **Ingestion pipeline** (`backend/app/rag/ingest.py`, run offline/CI, not at request time):
  PDF/EPUB → text extraction → **structure-aware chunking** (section/heading, ~512–1024
  tokens, overlap) → metadata per chunk (`libro`, `edicion`, `capitulo`, `pagina`,
  `especie?`) → embed → write LanceDB table under `data/rag_index/`. A manifest records
  corpus version + hash for eval reproducibility.
  — *Escribe en `instance/rag_index/` (no `data/`, por seguridad — ver Fase 5). Manifiesto ✅.*
- ✅ **Retriever** (`backend/app/rag/retriever.py`): hybrid search (dense + BM25/keyword),
  metadata filtering by species, top-k with a rerank step; returns chunks **with source
  metadata** so the interpret schema's `citas[]` point to `libro/edicion/página`. Retrieval
  is triggered by detected patterns + flagged analytes (reuse `ultimoAnalisis`), so it
  targets the patient's actual findings.
  — *Denso + BM25/FTS fusionados con RRF + rerank con cross-encoder `bge-reranker-v2-m3`,
  filtro por especie y citas ✅. Conmutables por `rag_hibrido`/`rag_rerank` (`config.py`), con
  degradación en cascada: rerank → RRF → sólo denso. Añadido `traduccion_consulta.py`
  (consulta ES → corpus EN). Cubierto por `test_retriever_hibrido.py` +
  `test_retriever_integracion.py`.*
- ✅ **Copyright safety:** retrieval returns short grounding snippets to the model only; the
  API never exposes full book text to the client, and the endpoint is auth-gated.
- ✅ **Ship path:** index built in CI and copied into the Docker image read-only. No HF
  persistent storage required. Rebuild only when the corpus changes.
  — *Dockerfile copia `instance/` de sólo lectura.*
- ✅ **Placeholder now:** commit the full pipeline + an empty/sample index and a
  `books/README.md` describing the expected input layout, so ingesting the real books later
  is a single `make ingest` step. The interpret path must degrade gracefully to no-RAG when
  the index is empty.
  — *Superado: ya no es un placeholder. **Corpus real ingerido** con `make ingest` — 6763
  fragmentos de 2 libros (Fundamentals of Veterinary Clinical Pathology 3e; Veterinary
  Hematology, Clinical Chemistry, and Cytology 3e) en `instance/rag_index/` (LanceDB 69 MB,
  bge-m3, chunks 450 tok / solape 64, troceo estructural markdown, índice FTS, manifiesto con
  `hash_corpus`). Degradación a sin-RAG sigue probada. El índice NO se comitea (queda fuera
  del repo; se construye en CI y se copia a la imagen).*

Files: new `backend/app/rag/**` (`ingest.py`, `retriever.py`, `traduccion_consulta.py`),
`instance/rag_index/` (artefacto construido, gitignored — **no** `data/`, por seguridad),
`books/README.md`, `Makefile` (`ingest`, `retrieval-eval`).

---

## Phase 4 — Rigorous evals (the core requirement for a diagnostic tool) — 🟡

Goal: measure accuracy, groundedness, and safety continuously, and gate deploys on it.

- 🟡 **Golden dataset** (`evals/dataset/`): curate expert-validated cases. The user already has
  real lab results + citologies from practicing vets (per `USO_DE_IA.md`) — turn these into
  labeled cases: patient signalment + lab values → expected key findings, expected
  differentials (acceptable set), red-flag/safety expectations, and out-of-scope cases the
  model must decline. Version the dataset; keep a held-out split.
  — *`casos.jsonl` ampliado de 7 a **17 casos** (IMHA, hipertiroidismo, HAC, pancreatitis,
  trombocitopenia, hipercalcemia, enteropatía perdedora, gammapatía, hepatocelular agudo,
  leucocitosis inflamatoria… + el caso fuera-de-alcance) + README con esquema ✅.
  Falta: **split reservado** (ningún caso lleva campo `split`) y casos reales del veterinario.*
- **Frameworks (layered):**
  - ✅ **promptfoo** — config-driven prompt/response regression in CI: deterministic assertions
    (language = es, valid schema, required derivation flag present when expected, no
    forbidden claims), plus LLM-rubric graders.
    — *`evals/promptfooconfig.yaml` presente (no ejecutado aquí, requiere modelo).*
  - ⬜ **Ragas** — RAG-specific metrics: faithfulness/groundedness (no claims beyond retrieved
    context), context precision/recall, answer relevance, **citation correctness**.
    — *Dependencia en el grupo `evals` (`pyproject.toml`) y mencionada en los READMEs, pero
    **cero líneas de código Ragas** en el repo. Ya está desbloqueado: el índice está poblado.
    Es el hueco más grande que queda del plan.*
  - ✅ **Evaluación de recuperación aislada** (no estaba en el plan original, añadida para
    decidir por datos): `evals/run_retrieval_eval.py` + `dump_retrieval.py` miden si los
    fragmentos recuperados son relevantes al diagnóstico esperado, permitiendo A/B de
    modelo de embeddings × idioma de consulta (bge-m3 ES vs EN vs MedCPT) antes de invertir
    en rerank. Juzga con Claude si hay `ANTHROPIC_API_KEY`, si no con heurístico de solape.
    Expuesto como `make retrieval-eval`.
  - ✅ **Custom clinical rubric** (`evals/judge/`) — LLM-as-judge (strong model, e.g. Claude)
    scoring: differential correctness vs. expected set, appropriate hedging, safety
    (no dangerous/overconfident recommendations), completeness.
    — *`evals/judge/clinical_judge.py` (se activa con ANTHROPIC_API_KEY).*
- 🟡 **Metrics & thresholds:** per-metric pass bars (e.g. groundedness ≥ X, differential
  recall ≥ Y, safety violations = 0). Track per model route (medGemma vs Claude) and per
  corpus version so RAG changes are attributable.
  — *Umbrales + agregación en `run_evals.py` ✅. Falta: informe explícito por-ruta/por-versión-de-corpus.*
- ✅ **CI gate:** GitHub Actions runs the eval suite on PRs touching `backend/app/ai`,
  `backend/app/rag`, prompts, or the index; **block merge/deploy on regression** or any
  safety failure. Store run artifacts/scorecards.
  — *`.github/workflows/evals.yml`; bloqueo verificado (exit=1 ante violación de seguridad).*
- ⬜ **Human-in-the-loop:** a lightweight review workflow for a veterinarian to accept/correct
  model outputs, feeding new cases back into the golden set. Log (privacy-safe) production
  interpretations for periodic expert audit.
  — *No implementado.*

Files: new `evals/**`, `.github/workflows/evals.yml`.

---

## Phase 5 — Security audit & rate limiting — ✅

Findings from the current code, severity-ranked, each with the fix folded into the new
FastAPI backend.

**Critical**
1. ✅ **Unauthenticated AI/papers proxies + open CORS** (`api/hf_proxy.php`, `papers_proxy.php`
   send `Access-Control-Allow-Origin: *`, no session check). Anyone can call them directly
   and burn the HF key / abuse PubMed. → Require an authenticated session on `/api/interpret`
   (and rate-limit papers); lock CORS to the app origin.
   — *`Depends(usuario_actual)` en **interpret** (401 verificado en producción). **Corrección
   (2026-07-26): papers NO lleva guarda de auth** — `/api/papers?query=…` responde 200 sin
   sesión; sólo está limitado a 30/min por IP. Coincide con lo que pide el punto («auth en
   interpret, rate-limit en papers»), pero la anotación anterior decía «interpret/papers» y era
   falsa. No hay clave de API en juego (eutils se consulta sin credencial), así que el riesgo se
   limita a abuso del proxy. CORS a orígenes fijos: verificado en local — un origen no listado no
   recibe `Access-Control-Allow-Origin`. **Ojo en producción**: el proxy de HF Spaces añade por su
   cuenta `Access-Control-Allow-Origin: <origen>` y `expose-headers: *` por encima de la app, así
   que el bloqueo de CORS queda neutralizado en la plataforma. Lo que sostiene la defensa ahí es
   `SameSite=Strict` en las cookies de sesión y CSRF: una petición cross-site no las lleva.*
2. ✅ **Password-hash DB may be web-served.** SQLite fallback writes `data/morphos.db` under the
   web root; `.htaccess` only denies `.env`/`setup.php`, so `/data/morphos.db` may be
   downloadable, and `.htaccess` is Apache-only. → Move the DB **outside** the served root;
   in FastAPI nothing under the DB path is a static route. Never rely on `.htaccess` for
   secret protection.
   — *BD en `instance/` (fuera del webroot); sólo `dist/` y `/data` (JSON) se montan.*

**High**
3. 🟡 **No rate limiting anywhere.** → Add **slowapi** (or Redis-backed) limits: per-IP + per-
   user on `/api/interpret` (expensive), per-IP on `/api/auth` login (brute force) and
   `/api/papers`. Return 429 with retry-after.
   — *slowapi por-IP en interpret/login/papers + manejador 429 con Retry-After ✅.
   Falta: límite adicional por-usuario (actualmente sólo por-IP).*
4. ✅ **Login brute force** — no throttling/lockout. → Per-account + per-IP attempt throttling
   with backoff; keep the already-generic "email o contraseña incorrectos" message.
   — *Tabla `intentos_login` + throttle por email+IP; mensaje genérico.*
5. ✅ **MySQL `root` / empty password default** (`conexion.php`). → Require DB credentials from
   env; no hardcoded defaults; fail closed if unset.
   — *El backend nuevo no tiene credenciales por defecto (config por entorno); SQLite por defecto.*

**Medium**
6. ✅ **Secrets via `.env` in webroot** guarded only by `.htaccess`. → Load secrets from real
   env vars (HF Spaces secrets); keep `.env` out of any served directory.
   — *pydantic-settings; `backend/.env` gitignored; nada bajo el root servido.*
7. ✅ **No CSRF protection** on session POSTs. → `SameSite=Strict` + `Secure` + `HttpOnly`
   session cookies, plus a CSRF token (or move to short-lived bearer tokens).
   — *Cookie firmada HttpOnly/SameSite/Secure + CSRF de doble token (403 verificado).*
8. ✅ **Server-side upload validation missing** for citology images (base64 decoded with no
   size/count/mime cap → memory DoS). → Enforce ≤4 images, max bytes, allowed mime, safe
   decode server-side.
   — *`interpret.py::_validar_imagenes` (nº, mime, tamaño, decode seguro).*
9. ✅ **Prompt-injection surface** via free-text `signos-clinicos` and citology images. →
   Harden system prompt, treat user text as data, validate structured output, cap output
   scope.
   — *System prompt endurecido (trata el texto como datos) + salida estructurada validada.*

**Low**
10. ✅ Remove `console.log` prompt/PII leakage in `ia.js`.
    — *El nuevo `ia.ts` (ya en uso) no registra el prompt. El `ia.js` legacy es código muerto
    (no se carga) pendiente de borrar junto al resto de `js/*.js`.*
11. 🟡 Raise password min length (6 → ≥8) + optional breach check; registration keeps 409 but
    is now rate-limited (acceptable enumeration risk).
    — *Mínimo 8 ✅ (`RegistroBody`). El chequeo de brechas (opcional) no se implementó.*
12. 🟡 Add security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy) and enforce
    HTTPS.
    — *Cabeceras ✅ (`headers.py`; HSTS en prod). Falta: redirección explícita HTTP→HTTPS
    (se delega en la plataforma). Nota: CSP ajustada a `worker-src blob:` para PDF.js.*

**New surface introduced by RAG:** ✅ licensed book text must never be exfiltratable —
retrieval returns only short grounding snippets to the model, the API never serves full
book content, and the corpus lives read-only in the image. — *Índice en `instance/`, endpoint auth-gated.*

Files: `backend/app/security/**`, `backend/app/routers/auth.py`, DB path change in the
connection layer, `Dockerfile`/entrypoint (secrets, DB location, headers).

---

## Verification

- ✅ **Engine parity (Phase 1):** the `analisis.ts` golden test suite (Vitest) passes with
  outputs identical to the current JS engine across fixture cases spanning both species and
  all pattern rules. This is the gate that the migration preserved validated behavior.
  — *27/27 verde (32/32 con los tests de import de laboratorio). Reejecutado 2026-07-26.*
- 🟡 **AI path (Phase 2):** integration test that `/api/interpret` returns schema-valid
  structured output for representative cases on both the medGemma and Claude routes; confirm
  `limpiarRespuesta` is gone and no unparsed text can reach the client. Drive the real UI
  to confirm findings, ranked differentials with citations, and the derivation banner render.
  — *UI real verificada: el botón "Análisis IA" llama a `POST /api/interpret` con CSRF y el
  backend alcanza el modelo (Ollama). Salida estructurada validada por test de integración;
  `limpiarRespuesta` no existe en el código nuevo. Falta: `ollama pull` del modelo para ver
  el render de diferenciales/citas con datos reales, y la ruta Claude ejercitada en vivo.*
- ✅ **RAG (Phase 3):** with a small sample corpus, verify retrieved citations resolve to the
  correct `libro/página` and that an empty index degrades gracefully to no-RAG.
  — *Degradación a sin-RAG ✅. Resolución de citas ✅: `test_retriever_integracion.py` construye
  un índice LanceDB real (con FTS) y comprueba recuperación end-to-end y filtro por especie;
  el corpus real de 2 libros está ingerido. 97 tests backend verde (2026-07-26).*
- 🟡 **Evals (Phase 4):** `promptfoo eval` + Ragas + the clinical rubric run green locally and
  in CI; deliberately regress a prompt and confirm the CI gate blocks it; confirm a safety-
  violation case fails the suite.
  — *Puerta CI: bloqueo por violación de seguridad verificado (exit=1). Falta: ejecutar
  promptfoo (requiere modelo) y Ragas (sin implementar).*
- 🟡 **Security (Phase 5):** confirm unauthenticated `/api/interpret` returns 401; CORS
  rejects foreign origins; rate limits return 429 under load; the DB path is not reachable
  as a static route; MySQL refuses to start without credentials. Run `/security-review` on
  the diff.
  — *401 sin sesión ✅, 403 sin CSRF ✅, BD fuera del webroot ✅. Falta verificar en vivo:
  rechazo CORS de orígenes externos, 429 bajo carga, y ejecutar `/security-review`.*

---

## Sequencing & risk notes

- Ship in order: **Phase 1 → 5 → 2 → 3 → 4**. Rationale: lock behavior with tests first
  (1), close the exploitable holes early (5), then rebuild the AI path (2), add grounding
  (3), and stand up evals (4) — though the golden dataset from Phase 1 tests and the eval
  dataset should be gathered in parallel from the start.
- Biggest risk is **regressing the vet-validated engine**; the Phase 1 golden suite mitigates
  it and must exist before any TS port lands.
- ~~The real licensed books are pending~~ — **resuelto (2026-07-26)**: 2 libros ingeridos
  (6763 fragmentos). Los PDF con licencia viven en `books/` **sin comitear** y el índice en
  `instance/` (gitignored); ambos se reconstruyen con `make ingest`. Queda pendiente medir
  con evals la mejora de exactitud que aporta el corpus (bloqueado por Ragas + promptfoo sin
  ejecutar).
- Hybrid model routing and the eval judge may use a hosted model; confirm a DPA covers any
  patient data sent on the Claude route (the medGemma route stays fully self-hosted for the
  privacy-default positioning).
