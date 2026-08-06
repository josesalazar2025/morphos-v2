# Evaluación del asistente clínico

Suite de evals rigurosa para un asistente de diagnóstico veterinario: mide precisión,
groundedness y **seguridad**, y bloquea despliegues ante regresiones.

Principio de diseño: **toda la evaluación tiene que poder correr sin una clave de pago.**
Una puerta de calidad que depende de saldo se apaga el día que se acaba, y se apaga justo
cuando más falta hace. Por eso los jueces LLM usan el CLI de Claude Code (la sesión que ya
tienes) o un modelo local en Ollama; la ruta por SDK con `ANTHROPIC_API_KEY` queda como
opción explícita.

## Capas

1. **Regresión del motor determinista** (`frontend/tests`, Vitest) — fija el comportamiento
   de `analisis.ts`. Es la red de seguridad de la migración.
2. **Evals clínicas** (`run_evals.py`) — comprobaciones deterministas sobre la salida del
   modelo: recall de diferenciales, cobertura de hallazgos, acierto de derivación, idioma
   y **violaciones de seguridad** (tolerancia cero). Puerta de CI. La cobertura se mide
   sobre el campo estructurado o, si el backend devuelve prosa, sobre las menciones en el
   texto (marcado `~` en la salida): una métrica que la ruta de producción no puede pasar
   por construcción no es una puerta.
3. **Juez clínico LLM** (`judge/clinical_judge.py`) — rúbrica de corrección, hedging,
   seguridad y completitud, servida por el **CLI de Claude Code** o por un modelo **local en
   Ollama**, sin clave de API en ninguno de los dos casos. Atrapa lo que ninguna comparación
   de strings ve: razonamiento incorrecto con las palabras clave correctas, sobreconfianza,
   consejo peligroso.
4. **Groundedness con Ragas** (`run_ragas.py`) — faithfulness y precisión/recall del
   contexto sobre el índice RAG real, con el mismo juez local.
5. **Eval de recuperación** (`run_retrieval_eval.py`) — aísla la recuperación de la
   generación para hacer A/B de configs (embeddings × idioma de consulta).
6. **promptfoo** (`promptfooconfig.yaml`) — regresión declarativa del prompt (idioma, sin
   tokens de control, rúbricas).

## Quién evalúa al evaluador

`tests/` son las pruebas unitarias de estos scripts: métricas de recuperación, léxico de
cobertura, rúbrica del juez, umbrales de ambas puertas y esquema del dataset. Son puras —sin
modelo, sin juez, sin índice— y corren en CI **antes** que la puerta. La razón es simple: un
medidor roto no da un resultado malo, da un resultado sin significado, y el primer fallo que
atraparon fue justo eso (el simulador de `--simular` no declaraba `fuera_de_alcance` y
suspendía por su cuenta una métrica de tolerancia cero).

```bash
make evals-unit
```

## Ejecutar

```bash
# Tubería sin modelo (valida la mecánica y los umbrales)
make evals                    # split dev, sólo casos validados
make evals-test               # split reservado

# Con el modelo real (genera interpretaciones vía backend)
cd backend && uv run python ../evals/run_evals.py --modelo medgemma

# Con salidas precomputadas, eligiendo juez
cd backend && uv run python ../evals/run_evals.py --predicciones preds.jsonl --juez cli
cd backend && uv run python ../evals/run_evals.py --predicciones preds.jsonl --juez ollama

# Groundedness (requiere índice RAG y Ollama)
make ragas ARGS="--predicciones preds.jsonl"

# A/B de recuperación
make retrieval-eval

# promptfoo
cd evals && npx promptfoo@latest eval
```

## Los jueces

Tres transportes tras la misma rúbrica y el mismo esquema de salida. `--juez auto` (por
defecto) prueba en este orden y usa el primero disponible:

| `--juez` | Qué necesita | Coste | Notas |
|---|---|---|---|
| `cli` | El CLI `claude` con sesión iniciada | Límites de uso de tu suscripción | Mejor juicio. No existe en CI |
| `ollama` | Ollama con el modelo descargado | Ninguno | Reproducible (temp. 0). Mantiene viva la rúbrica en CI |
| `claude` | `ANTHROPIC_API_KEY` | Saldo de API | Explícito, para auditorías |

```bash
claude --version              # juez CLI: basta con tener sesión iniciada
ollama pull qwen2.5:7b        # juez local por defecto
```

| Variable | Por defecto | Para qué |
|---|---|---|
| `MORPHOS_JUEZ_CLI_MODELO` | `sonnet` | Modelo del juez CLI (`opus` para auditar) |
| `MORPHOS_JUEZ_MODELO` | `qwen2.5:7b` | Modelo del juez local |
| `MORPHOS_JUEZ_BASE_URL` | `http://localhost:11434` | Dónde está Ollama |

### El juez CLI

`judge/claude_cli.py` invoca `claude -p` con la rúbrica como system prompt y
`--output-format json`, sin MCP, sin sesión persistida y con un solo turno. Resuelve lo que
bloqueaba esta capa: **no hace falta clave de API**, basta la sesión que ya tienes. A cambio
no está en un runner de CI y no expone temperatura, así que es menos reproducible que la
ruta Ollama.

### Elegir modelo de juez

- **No uses el modelo bajo evaluación.** Un modelo que se juzga a sí mismo se puntúa alto
  por sesgo de auto-preferencia y deja de detectar sus propias regresiones.
- **Los umbrales dependen del juez.** `UMBRALES_JUEZ` está calibrado contra el juez local
  pequeño. Sobre las mismas salidas simuladas (deliberadamente pobres), qwen2.5:7b puntuó
  `hedging_apropiado` en 1.0 y el juez CLI en 0.4: el pequeño aprueba lo que el grande
  suspende. Si cambias de juez, recalibra los umbrales en vez de asumir que la escala es la
  misma.

Con `--simular` el juez se omite a propósito: puntuaría el simulador, no el modelo. Con
`--juez-informativo` corre pero no bloquea la puerta. Los jueces remotos se paralelizan
(4 casos a la vez); el local va en serie porque competiría consigo mismo por la GPU.

## Umbrales (puerta de CI)

Definidos en `run_evals.py` → `UMBRALES` (deterministas) y `UMBRALES_JUEZ` (rúbrica). Salida
con código ≠0 si alguna métrica cae por debajo o si hay cualquier violación de seguridad,
venga de la comprobación determinista o del juez. Ver `.github/workflows/evals.yml`.

## Disciplina del dataset

Dos reglas, ambas aplicadas por el runner y no sólo documentadas:

- **Split reservado.** `--split dev` (por defecto) es el conjunto sobre el que se itera;
  `--split test` sólo se mira en agregado y antes de desplegar. Mirar los fallos caso a caso
  del split reservado para afinar un prompt lo convierte en otro split de desarrollo.
- **Sin firma veterinaria no es oro.** Los casos con `validado: false` no cuentan para la
  puerta (salvo `--incluir-pendientes`): no pueden aprobar ni bloquear un despliegue.

```bash
make revision                                                   # hoja de revisión
python evals/revision.py --validar imha-canino --revisor "Dra. Pérez"
python evals/revision.py --estado
```

Esquema de los casos y estado de validación: `dataset/README.md`.
