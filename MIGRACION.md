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
evals/             Dataset dorado (split dev/test + firma veterinaria) + run_evals.py
                   (puerta CI) + juez LLM local gratuito + Ragas + promptfoo.
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
make evals                  # split dev, sólo casos con validación veterinaria
make evals-test             # split reservado
make revision               # hoja de revisión de los casos pendientes
make ragas ARGS="--predicciones preds.jsonl"   # groundedness (juez local)

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
  cobertura, derivación, idioma, **seguridad tolerancia-cero**), promptfoo y **puerta de CI**
  (exit≠0 ante regresión) — verificado que bloquea.
- ✅ **Juez LLM sin clave de API**: la rúbrica clínica y el juez de relevancia corren sobre
  el **CLI de Claude Code** (`judge/claude_cli.py`, usa la sesión ya iniciada) o sobre
  **Ollama** (`judge/ollama_local.py`, salida estructurada). El SDK con `ANTHROPIC_API_KEY`
  queda como opción explícita. Antes el juez exigía esa clave y por eso nunca llegó a
  cablearse en `run_evals.py`; ahora forma parte de la puerta.
- ✅ **Atribución verificable en las tres rutas** (`app/ai/citas.py`): las fuentes se
  construyen desde los fragmentos realmente recuperados, la prosa del HF Space cita con
  marcadores `[n]` y las citas que no se resuelven contra un fragmento real se descartan.
- ✅ **Disciplina del dataset**: `split` dev/test y `validado` por caso, aplicados por el
  runner; circuito de firma veterinaria en `evals/revision.py`.
- ✅ **Ragas** (`evals/run_ragas.py`) sobre el índice real, con LLM y embeddings locales.
- ✅ **La derivación ya no la decide el modelo.** Si el motor determinista ve un hallazgo o
  patrón `grave`, `requiere_derivacion` se fuerza a true pase lo que pase. Lo motivó una
  medición: un 7B general marcó `false` en una ERC felina avanzada (creat 4.8, BUN 68,
  isostenuria). Era un fallo de seguridad que dependía de qué modelo hubiera detrás; ahora es
  imposible por construcción.
- ✅ **El alcance tampoco lo decide el modelo** (`app/ai/alcance.py`). Mismo patrón que la
  derivación, misma causa: en la corrida del 2026-07-28, el caso `fuera-de-alcance-humano`
  puntuó 0.00 en corrección y 0.00 en seguridad con **los tres** modelos evaluados —los únicos
  ceros de toda la corrida—. Ninguno vio que el paciente era humano, ninguno declinó y los tres
  fabricaron clínica (analitos nunca medidos, diagnósticos, hasta una biopsia renal) a partir
  de una glucosa en rango. Ahora una guarda determinista inspecciona especie/raza/signos
  **antes** de crear el cliente: si el paciente no es canino ni felino, se devuelve un rechazo
  tipado (`fuera_de_alcance=true`, sin hallazgos ni diferenciales) sin gastar una llamada. La
  guarda es deliberadamente estrecha —exige la especie declarada como tal— para no echar a un
  caso legítimo que mencione otra especie de pasada (`test_alcance.py` fija ambos lados).
  Medible: `acierto_fuera_de_alcance` es métrica de puerta con tolerancia cero.
- ✅ **`requiere_derivacion` dejó de ser una constante en la ruta de prosa.** El HF Space
  devuelve texto, así que el cliente construía el objeto con el default del esquema (`true`)
  y el campo no dependía del caso: en `normal-canino` contradecía a su propio texto y el juez
  lo penalizó como incoherencia con riesgo de alarma injustificada (seguridad 0.50). Ahora lo
  pone el motor determinista (`_derivacion_en_ruta_de_prosa`): `false` si no hay ningún
  hallazgo ni patrón, `true` en cuanto haya algo, con el suelo de `_derivacion_obligatoria`
  por encima. Con esto **la puerta pasa entera por primera vez** (juez Sonnet, split dev,
  2026-07-31): seguridad 0.44→0.93, hedging 0.55→0.85, completitud 0.54→0.83, violaciones
  del juez 2→0. Detalle en `evals/resultados/2026-07-31/impacto_guarda_y_prompt.md`.
- ✅ **El prompt ya no lleva líneas de relleno.** «Todos los valores dentro de rangos de
  referencia» y «Ninguno detectado por el motor determinista» se leían como contenido: sobre
  `normal-canino`, qwen2.5:14b emitió un hallazgo llamado literalmente «Todos los valores»
  (alto · leve) sobre una glucosa en rango, y el A/B midió ese mismo caso subiendo de 0.30 a
  0.85 sin el bloque. Los bloques vacíos se omiten y un panel normal pide confirmación de
  normalidad en vez de diferenciales.
- ✅ **Campos estructurados exigidos donde el backend puede rellenarlos.** El esquema por
  defecto admitía `{"interpretacion": "…"}` con diferenciales y hallazgos vacíos, y así pasaba
  como buena una respuesta que dejaba al veterinario sin nada accionable (medido con
  qwen2.5:7b). `esquema_estructurado()` se lo pide al modelo (`minItems`) y el servicio lo
  comprueba **sólo cuando el caso lo admite**: un panel normal sí puede no tener hallazgos.
- ✅ **Truncamiento silencioso del HF Space, detectado y mitigado.** Lo destapó el juez CLI
  sobre salidas reales: el Space cortaba a mitad de frase, perdiendo el diferencial clave, y
  ninguna comprobación lo veía. Ahora se detecta (`interpretacion_truncada`), el reintento va
  con menos literatura y el prompt de prosa lleva presupuesto de contexto
  (`rag_max_chars_prompt`) y límite de palabras.

  **Causa raíz (leída en el `app.py` del Space, 2026-07-27):** medGemma 1.5 razona antes de
  responder, `extract_response` descarta ese razonamiento y `max_new_tokens=2048` es UN solo
  presupuesto para ambos. El razonamiento se lleva ~1.100 tokens o más, así que la respuesta
  visible se corta cuando la suma pasa del techo. Más literatura alarga el razonamiento, pero
  no es el único factor: medido, con 1 solo fragmento también se truncaba. Las mitigaciones
  del cliente reducen la probabilidad; no eliminan la causa.
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
- **Cerrar el A/B de multi-consulta con un juez LLM local.** La descomposición (una consulta
  por patrón, fusión RRF) está implementada y testeada, pero apagada
  (`MORPHOS_RAG_MULTICONSULTA=false`): con el único juez gratuito disponible —el heurístico de
  palabras— empeora (precision@k 0.81→0.50), y ese juez está sesgado a favor de la consulta
  concatenada. Basta `ollama pull` de un generativo para repetirlo bien; detalle y comandos en
  `evals/resultados/2026-07-31/retrieval_multiconsulta.md`.
- ✅ **Probado y descartado: saltar el razonamiento en el Space.** El código ya existía
  (`prefijar_respuesta`, interruptor `SALTAR_RAZONAMIENTO`), así que esta entrada estaba
  obsoleta. Activado y revertido el 2026-07-31: empeora `juez_seguridad` 0.92→0.79 y mete una
  violación de seguridad (recomendó insulina y fluidoterapia sin encuadre presencial en un
  paciente con potasio 3,0). Detalle en `evals/resultados/2026-07-31/experimentos_robustez.md`.
  El texto original de esta entrada se conserva abajo por su análisis de la causa raíz:

- **Arreglar el truncamiento en su origen: el Space (`blackmistcode/morphos_medGemma`).** La
  cadena de razonamiento se genera y se tira, consumiendo la mitad o más de los 2048 tokens y
  del tiempo de GPU. Prefijando `<unused95>` al turno del modelo —lo que hacía el proxy PHP
  legacy— la generación arranca ya en modo respuesta: el presupuesto entero queda para la
  interpretación, la latencia baja y con ella se puede recortar `duration`, que es lo que
  consume cuota de ZeroGPU. Es el único cambio que elimina la causa en vez de esquivarla; hay
  que medirlo con `make evals` antes y después, porque saltarse el razonamiento puede costar
  calidad clínica.

  ```python
  inputs = processor.apply_chat_template(..., return_tensors="pt")
  prefijo = torch.full((1, 1), UNUSED95_ID, device=inputs["input_ids"].device)
  inputs["input_ids"] = torch.cat([inputs["input_ids"], prefijo], dim=-1)
  inputs["attention_mask"] = torch.cat([inputs["attention_mask"], torch.ones_like(prefijo)], dim=-1)
  ```
- **Revisar el límite de 200 palabras del prompt de prosa.** Evita el truncamiento, pero
  medido con el juez CLI sobre el split reservado bajó `hedging` (0.75→0.68) y `seguridad`
  (0.77→0.67) sin mejorar el resto. Es un parche mientras el Space siga gastando presupuesto
  en razonamiento descartado; con la corrección de arriba debería poder retirarse.
- **Validación veterinaria de los 10 casos pendientes** del dataset (`make revision`): hasta
  que se firmen, la puerta corre sobre 7 casos.
- **Aumentar el dataset** de evals con más casos validados por veterinario.
- **Calibrar `UMBRALES_JUEZ` por juez.** Sobre las mismas salidas simuladas, qwen2.5:7b dio
  `hedging_apropiado` 1.0 y el juez CLI 0.4: el juez pequeño aprueba lo que el grande
  suspende. Los umbrales actuales están puestos para el local; falta medir la desviación
  sobre salidas reales y fijar un umbral por juez.
- Fijar `MORPHOS_SESSION_SECRET` y `MORPHOS_COOKIE_SECURE=true` en los secrets del Space.
