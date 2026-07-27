# Evaluación del asistente clínico

Suite de evals rigurosa para un asistente de diagnóstico veterinario: mide precisión,
groundedness y **seguridad**, y bloquea despliegues ante regresiones.

Principio de diseño: **toda la evaluación tiene que poder correr sin una clave de pago.**
Una puerta de calidad que depende de saldo se apaga el día que se acaba, y se apaga
justo cuando más falta hace. Por eso los jueces LLM corren por defecto en local sobre
Ollama, y Claude queda como opción explícita para auditorías puntuales.

## Capas

1. **Regresión del motor determinista** (`frontend/tests`, Vitest) — fija el comportamiento
   de `analisis.ts`. Es la red de seguridad de la migración.
2. **Evals clínicas** (`run_evals.py`) — comprobaciones deterministas sobre la salida del
   modelo: recall de diferenciales, cobertura de hallazgos, acierto de derivación, idioma
   y **violaciones de seguridad** (tolerancia cero). Puerta de CI.
3. **Juez clínico LLM** (`judge/clinical_judge.py`) — rúbrica de corrección, hedging,
   seguridad y completitud. Por defecto **local y gratuito** (Ollama); Claude con
   `--juez claude` si hay `ANTHROPIC_API_KEY`. Atrapa lo que ninguna comparación de strings
   ve: razonamiento incorrecto con las palabras clave correctas, sobreconfianza, consejo
   peligroso.
4. **Groundedness con Ragas** (`run_ragas.py`) — faithfulness y precisión/recall del
   contexto sobre el índice RAG real, con el mismo juez local.
5. **Eval de recuperación** (`run_retrieval_eval.py`) — aísla la recuperación de la
   generación para hacer A/B de configs (embeddings × idioma de consulta).
6. **promptfoo** (`promptfooconfig.yaml`) — regresión declarativa del prompt (idioma, sin
   tokens de control, rúbricas).

## Ejecutar

```bash
# Tubería sin modelo (valida la mecánica y los umbrales)
make evals                    # split dev, sólo casos validados
make evals-test               # split reservado

# Con el modelo real (genera interpretaciones vía backend)
cd backend && uv run python ../evals/run_evals.py --modelo medgemma

# Con salidas precomputadas + juez local explícito
cd backend && uv run python ../evals/run_evals.py --predicciones preds.jsonl --juez ollama

# Groundedness (requiere índice RAG y Ollama)
make ragas ARGS="--predicciones preds.jsonl"

# A/B de recuperación
make retrieval-eval

# promptfoo
cd evals && npx promptfoo@latest eval
```

## El juez gratuito

Corre sobre Ollama con salida estructurada nativa (`format` + JSON Schema), así que
devuelve una rúbrica validada, no prosa que haya que parsear.

```bash
ollama pull qwen2.5:7b        # modelo de juez por defecto
```

| Variable | Por defecto | Para qué |
|---|---|---|
| `MORPHOS_JUEZ_MODELO` | `qwen2.5:7b` | Modelo que juzga |
| `MORPHOS_JUEZ_BASE_URL` | `http://localhost:11434` | Dónde está Ollama |

Dos cosas que importan al elegir el modelo del juez:

- **No uses el modelo bajo evaluación.** Un modelo que se juzga a sí mismo se puntúa alto
  por sesgo de auto-preferencia y deja de detectar sus propias regresiones.
- **7B es el mínimo, no el ideal.** Con VRAM suficiente, `qwen2.5:14b-instruct` discrimina
  bastante mejor. Los umbrales de `UMBRALES_JUEZ` están puestos para un juez pequeño; si
  subes de modelo, súbelos.

Con `--simular` el juez se omite a propósito: puntuaría el simulador, no el modelo. Con
`--juez-informativo` corre pero no bloquea la puerta.

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
