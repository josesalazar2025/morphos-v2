# Evaluación del asistente clínico

Suite de evals rigurosa para un asistente de diagnóstico veterinario: mide precisión,
groundedness y **seguridad**, y bloquea despliegues ante regresiones.

## Capas

1. **Regresión del motor determinista** (`frontend/tests`, Vitest) — fija el comportamiento
   de `analisis.ts`. Es la red de seguridad de la migración.
2. **Evals clínicas** (`run_evals.py`) — comprobaciones deterministas sobre la salida del
   modelo: recall de diferenciales, cobertura de hallazgos, acierto de derivación, idioma
   y **violaciones de seguridad** (tolerancia cero). Puerta de CI.
3. **Juez clínico LLM** (`judge/clinical_judge.py`) — rúbrica con Claude: corrección de
   diferenciales, hedging, seguridad, completitud. Se activa si hay `ANTHROPIC_API_KEY`.
4. **promptfoo** (`promptfooconfig.yaml`) — regresión declarativa del prompt (idioma, sin
   tokens de control, rúbricas).
5. **Ragas** (cuando el índice RAG esté poblado) — faithfulness, precisión/recall de
   contexto y corrección de citas.

## Ejecutar

```bash
# Tubería sin modelo (valida la mecánica y los umbrales)
make evals                       # → run_evals.py --simular

# Con el modelo real (genera interpretaciones vía backend)
cd backend && uv run python ../evals/run_evals.py --modelo medgemma

# Con salidas precomputadas
cd backend && uv run python ../evals/run_evals.py --predicciones preds.jsonl

# promptfoo
cd evals && npx promptfoo@latest eval
```

## Umbrales (puerta de CI)

Definidos en `run_evals.py` → `UMBRALES`. Salida con código ≠0 si alguna métrica cae por
debajo o si hay cualquier violación de seguridad. Ver `.github/workflows/evals.yml`.

## Ampliar el dataset

Añade casos validados por veterinario a `dataset/casos.jsonl` (esquema en
`dataset/README.md`). Prioriza casos límite, de seguridad y fuera de alcance. Mantén un
split de validación reservado y registra la revisión profesional de cada caso.
