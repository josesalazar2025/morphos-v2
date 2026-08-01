# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Morphos is a veterinary diagnostic support tool — a single-page application (SPA) that performs real-time clinical pattern detection from lab values and optionally calls an AI model (self-hosted medGemma, or Claude via the hybrid route) for clinical interpretation. It targets Canino and Felino patients.

## Migration in progress (see MIGRACION.md)

The project is being modernized from a static-JS + PHP-proxy app to:
- **frontend/** — Vite + TypeScript. The vet-validated engine is ported to
  `frontend/src/analisis.ts` with a Vitest regression suite (`frontend/tests/`).
- **backend/** — FastAPI service (managed with **uv**). Structured AI output (Pydantic),
  hybrid medGemma/Claude clients, RAG retrieval, and all security (auth guard on the AI
  endpoint, rate limiting, locked CORS, secure sessions, security headers).
- **evals/** — rigorous clinical eval harness with a CI gate (`.github/workflows/evals.yml`).
- **RAG** — LlamaIndex + LanceDB; index built offline from `books/` and baked read-only
  into the image (lives in `instance/`, outside the webroot).

El legacy `js/*.js` + `api/*.php` **ya se eliminó** (2026-07-26): `index.html` cargaba el bundle
TS desde antes, así que eran código muerto. Todo el trabajo va en la estructura nueva. Ver
`MIGRACION.md` para el estado completo y cómo ejecutar cada parte.

## Running the App

### New stack (target)
```bash
make frontend-install && make frontend-build   # build the SPA → dist/
make backend-sync && make dev                  # FastAPI on http://localhost:8000
```
Secrets come from `backend/.env` (see `backend/.env.example`) or HF Space secrets — never
from a file under the served root. For local AI, Ollama must run at
`http://localhost:11434` with a medGemma model pulled.

No hay stack legacy: `php -S localhost:8000` y el proxy PHP ya no existen.

## Architecture

### Data Flow

```
User form input
  → analisis.ts (real-time pattern detection, no server)
  → UI updates (color-coded fields, pattern cards)

User clicks "Análisis IA"
  → ia.ts (thin typed client, sends patient data + flagged values + CSRF token)
  → POST /api/interpret (FastAPI: sesión + CSRF + rate limit)
      → recuperación RAG (LanceDB, degrada a sin-RAG si no hay índice)
      → prompt endurecido (app/ai/prompt.py)
      → [ruta medgemma] → HF Space Gradio (texto libre) u Ollama (salida estructurada)
      → [ruta claude]   → Anthropic SDK con tool use (salida estructurada validada)
  → Render de la InterpretacionClinica en #salida-ia
```

### Key Files and Their Roles

- **`frontend/src/analisis.ts`** — Core engine (845 lines). Compares values against species-specific reference ranges, classifies severity (mild/moderate/severe), applies age/breed/sex adjustments, and identifies 50+ clinical patterns (anemia types, hepatic, renal, endocrine, etc.). Cubierto por 27 tests dorados en `frontend/tests/analisis.test.ts` — **es la red de regresión: no tocar sin ejecutarlos**.
- **`frontend/src/ia.ts`** — Cliente tipado de `POST /api/interpret`; renderiza la salida estructurada (hallazgos, diferenciales con citas, banner de derivación). No construye el prompt (eso vive en el backend).
- **`frontend/src/main.ts`** — Orquestación: carga los JSON, cablea eventos del formulario, dispara el análisis, exporta PDF.
- **`frontend/src/ui.ts`** — Tab navigation (8 panels, 4 exam sub-tabs), swipe gestures, mobile/desktop field sync, collapsible panels.
- **`frontend/src/pdf-parser.ts`** — Client-side PDF extraction using PDF.js. 47 regex patterns to identify analytes in Spanish/English. Runs fully in the browser.
- **`backend/app/ai/hf_space.py`** — Cliente del HF Space (Gradio) donde vive medGemma. El Space devuelve texto libre, así que va por la ruta de prosa: `ai/prosa.py` limpia los tokens del modelo, detecta salida defectuosa (razonamiento filtrado, bucle, frase cortada) y envuelve el resultado en el campo `interpretacion`. Es la ruta por defecto sin salida estructurada; un modelo local declarado `=prosa` usa la misma.
- **`backend/app/ai/claude.py`** — Ruta Claude vía tool use forzado: el `input_schema` es el JSON Schema de `InterpretacionClinica`, así que valida contra Pydantic sin regex.
- **`data/valores_referencia.json`** — Reference ranges for 90 analytes per species.
- **`data/alteraciones.json`** — 78 clinical entities used to enrich AI prompts with etiologic context.

### AI Backend Configuration

La selección de ruta se aplica **en el servidor** (`MORPHOS_IA_BACKEND_DEFECTO`: `medgemma` |
`claude`), no en `localStorage` como en el legacy. Dentro de `medgemma`, si
`MORPHOS_HF_SPACE_URL` está definida se usa el HF Space; si se vacía, cae a Ollama en
`MORPHOS_MEDGEMMA_BASE_URL`. Ambas rutas aceptan hasta 4 imágenes (validadas en servidor:
número, mime y tamaño).

**Modelos locales elegibles desde la UI.** `MORPHOS_MODELOS_LOCALES` declara una lista blanca
(`nombre[=prosa]`, vacía por defecto → selector oculto). Si el usuario elige uno, ese modelo
manda sobre el Space y recibe **exactamente el mismo tratamiento**: RAG, prompt endurecido,
atribución de citas y suelos de seguridad viven en `ai/service.py`, no en los clientes, así que
son agnósticos del modelo. Dos invariantes que no se tocan:

- **Nombres, nunca URLs.** La base_url se queda en `medgemma_base_url`; aceptar una del cliente
  convierte `/api/interpret` en un SSRF. El nombre se valida contra la lista blanca en el
  esquema (`PeticionInterpretacion`, → 422) y otra vez en `_crear_cliente` (para las evals).
- **El modo de salida se declara, no se infiere.** `=prosa` manda el modelo por
  `ai/prosa.py` (limpieza + envoltura) en vez de por la decodificación restringida de Ollama.
  Existe porque qwen2.5:7b acepta el `format` y devuelve JSON válido con `hallazgos_clave`,
  `diferenciales` y `siguientes_pruebas` vacíos. `cliente.prosa` —no el nombre del cliente— es
  lo que el servicio consulta para elegir system prompt y suplir `requiere_derivacion`.

Para la ruta Claude el modelo por defecto es `claude-opus-5`. No cambiar a `claude-fable-5`:
cuesta el doble, exige retención de datos de 30 días (incompatible con el posicionamiento de
privacidad) y sus clasificadores pueden rechazar trabajo clínico legítimo con
`stop_reason="refusal"` — ver el comentario en `backend/app/config.py`.

### Pattern Detection Logic (`analisis.ts`)

Severity thresholds are based on deviation from the reference range. Reference ranges are dynamically adjusted for:
- **Age**: puppies, adults, seniors, geriatric (age in months)
- **Breed**: Greyhounds (lower platelets normal), Akita/Shiba (different RBC ranges), etc.
- **Sex**: Male felines have a higher creatinine tolerance

The `analizarResultados()` function is called on every `input` event and returns flagged findings + matched clinical patterns.

### CSS Notes

Do not use `!important` — use specificity or cascade ordering instead. The stylesheet is `css/styles.css` (2742 lines). The desktop grid breakpoint is `>1100px`.

### Distribución del corpus RAG

Los libros con licencia y el índice **nunca** entran en git (`books/*` y `instance/` están en
`.gitignore`). Viven en dos datasets **privados** del Hub, declarados en `scripts/hub.py` y en
`backend/app/config.py`:

| Artefacto | Repo | Tamaño | Para qué |
|---|---|---|---|
| Índice LanceDB | `blackmistcode/morphos-rag-index` | 33 MB | Lo consume la app; se hornea en la imagen |
| PDFs originales | `blackmistcode/morphos-books` | 226 MB | Sólo para reingerir |

```bash
make ingest          # construye el índice desde books/ (local, requiere grupo rag)
# Añadir un documento nuevo sin reprocesar los libros grandes (OCR sobre cientos de MB):
#   uv run --group rag python -m app.rag.ingest --fuente ../books --salida ../instance/rag_index --anexar
make curar-indice    # descarta índices alfabéticos + reetiqueta especie (ARGS=--aplicar)
make publish-index   # sube instance/rag_index al dataset privado
make fetch-index     # lo descarga (clon limpio, otra máquina, CI)
make publish-books   # respalda los PDFs (no hace falta para desplegar)
```

Se usa la API de Python de `huggingface_hub`, **no el CLI `hf`**: en la versión instalada
(1.16.1) el CLI devuelve código 1 aunque la operación vaya bien, por una incompatibilidad
typer/click, y eso aborta cualquier Makefile o build.

### Alcance del corpus: qué entra y con qué especie

**`data/rag_alcance.json`** declara, por rangos de página, las dos decisiones que la ingesta y
`make curar-indice` aplican por igual (`app/rag/alcance_corpus.py`):

- **`descartes`** — rangos de página que no entran en el corpus: los preliminares (portada,
  créditos, índice general, colaboradores, prefacio; el contenido empieza en la p. 19 en ambos
  libros), el índice alfabético del final y la lista de casos que abre la SECTION VII.
- **`umbral_lideres_de_puntos`** — descarte por CONTENIDO: cualquier fragmento cuya fracción de
  líderes de puntos («Urine Samples . . . . . . 6») supere el umbral. Fundamentals repite un
  sumario al principio de cada capítulo, 23 bloques por todo el libro, que por rangos serían 23
  entradas a mano; la firma tipográfica los coge de una vez. El reparto real es bimodal (164
  fragmentos por encima de 0.20, 8 entre 0.05 y 0.18 con contenido real), así que 0.20 se
  equivoca por el lado de conservar.
- **`rangos`** — restringidos a una especie (abajo).

Total fuera: **571 fragmentos, 6772 → 6201 (8,4 %)**. Ninguno contiene prosa clínica.

`curar-indice` **compacta al terminar**, y no es cosmético: LanceDB versiona, así que
sobrescribir deja los datos viejos en disco y el índice *crece* al quitarle filas (medido:
73 MB → 140 MB → 33 MB tras compactar). Este artefacto se sube al Hub y se hornea en la imagen.

### Sólo canino y felino

Morphos atiende **sólo canino y felino**, pero los dos libros son de patología clínica
veterinaria **comparada** y traen secciones enteras de aves, reptiles y peces (5,7 % de los
fragmentos mencionan aves). `retriever.py` filtra por especie, pero sólo excluye un fragmento
si su metadato `especie` está relleno — y hasta el 2026-08-01 **los 6772 chunks lo tenían
vacío**, así que el filtro estaba inerte sobre el índice real aunque sus tests pasaran contra un
índice sintético que sí lo traía.

Sólo se etiquetan **secciones declaradas por el propio libro en su índice** (488 fragmentos,
7,2 %, como `no_domestico`). El material comparado que menciona caballo o vaca de pasada se deja
intacto: enseña el principio general y sirve igual para un perro. Etiquetar no es descartar —esas
secciones siguen en el corpus, sólo quedan fuera del alcance de un paciente canino o felino.

**Si se reingiere o se reetiqueta, hay que `make publish-index`**: si no, el arreglo se queda en
local y las builds siguen bajando el índice sin etiquetar. `test_alcance_corpus.py` comprueba el
índice REAL (se omite donde no está) precisamente porque un fixture sintético no puede ver este
fallo.

En Docker, `WITH_RAG=1` es el valor por defecto y los modelos (bge-m3 + bge-reranker-v2-m3,
~6.4 GB) se hornean en `/opt/hf` con `HF_HUB_OFFLINE=1` en runtime, para que un fallo de red no
degrade la recuperación en silencio. Si `instance/rag_index` no está en el contexto de build, la
imagen lo descarga usando `HF_TOKEN` como **secreto de build** (nunca `--build-arg`, que quedaría
en el historial de capas). Al arrancar, `_verificar_rag()` distingue en el log entre «RAG
desactivado a propósito», «faltan dependencias» y «falta el índice».

### Coding notes

All variables should be named in spanish unless they're referencing common technical names like tab, input, output, etc.
Always use descriptive names for variables and functions keeping legibility as a priority.
Don't use aligment spaces.
