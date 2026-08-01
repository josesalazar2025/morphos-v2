# A/B de recuperación: consulta única vs multi-consulta — 2026-07-31

**Pregunta:** `construir_consulta()` concatena todos los patrones y hallazgos en UNA cadena
que se embebe en un único vector. ¿Recuperar mejor separando el caso en una consulta por
patrón y fusionando por rango (RRF) los resultados?

**Contexto:** sale del análisis de si convenía un enfoque *agéntico* de RAG (que el modelo
decida qué recuperar). Se descartó: los fallos de la corrida del
[2026-07-28](../2026-07-28/comparativa_modelos.md) son de guarda y de juicio del generador, no
de recuperación, y el A/B de patrones ya mostró que delegar más juicio en el modelo degrada.
La descomposición SÍ era aprovechable, pero es determinista: la hace el motor de patrones, sin
ninguna llamada a un modelo generativo.

**Juez:** heurístico de solape de palabras clave (`--keyword`). Es el único disponible sin
coste: en la máquina sólo hay `bge-m3` (embeddings) en Ollama, y el juez LLM de pago queda
fuera por la política del proyecto. **Es una salvedad grande, no una nota al pie** — ver abajo.

**Corpus:** índice real (`instance/rag_index`), 17 casos dorados, k=6.

## Resultados

| Config | precision@k | hit_rate | MRR |
|---|---|---|---|
| Consulta única (producción) | **0.814** | 0.941 | **0.912** |
| Multi-consulta | 0.500 | 0.941 | 0.858 |
| Multi-consulta, sin cuota de diversidad | 0.471 | 0.941 | 0.850 |
| Consulta única, sin cuota de diversidad | **0.814** | 0.941 | **0.912** |

## Lectura

1. **No se activa la multi-consulta.** `MORPHOS_RAG_MULTICONSULTA=false` por defecto. El
   código está implementado y cubierto por tests, pero una función que empeora la única
   métrica disponible no entra en producción por lo bien que suena.
2. **La cuota de diversidad (`rag_max_por_libro=2`) es neutra aquí**: los mismos números con y
   sin ella en ambas ramas. Se deja activada porque su efecto es sobre el presupuesto del
   prompt (no gastar 1800 caracteres en dos páginas del mismo capítulo), que esta eval no
   mide.
3. **El `hit_rate` no se mueve (0.941 en las cuatro).** Las dos configuraciones encuentran
   literatura relevante en los mismos 16 de 17 casos; lo que cambia es cuánta del top-6 lo es.

## Por qué el resultado no es concluyente

El juez de palabras clave **favorece por construcción a la consulta concatenada**: esa consulta
lleva descripción + analitos + signos, así que los fragmentos que recupera comparten vocabulario
con el diagnóstico esperado casi por definición. Las sub-consultas de un solo analito traen
pasajes mecanísticos que el heurístico marca como no relevantes aunque lo sean.

Inspección manual de tres casos (`anemia-ferropenica-canino`, `erc-felino`,
`hipoadrenocorticismo-canino`; solapamiento 1/6 entre ambas ramas):

- `hipoadrenocorticismo-canino` — la multi-consulta trae *«Na:K ratio < 27 … is diagnostic of
  hypoadrenocorticism»*; la única trae una tabla de valores de un caso clínico y un párrafo de
  anemia normocítica.
- `anemia-ferropenica-canino` — la multi trae *«the anemia is classically microcytic»* y
  *«microcytic anemia that appears nonregenerative»*; la única trae *«hemocytometer chamber»*,
  *«Akitas with low-K⁺ RBCs»* y *«traumatic collection»*, que son ruido del saco de términos.

Es decir: en los casos mirados a mano la multi-consulta parecía mejor y el heurístico dice lo
contrario. n=3 mirados a ojo no derrota a n=17 medidos, aunque sea con un juez tosco — pero
tampoco al revés.

## Siguiente paso para cerrarlo

Un juez LLM **local y gratuito** basta: `ollama pull qwen2.5:7b` (o cualquier generativo de
propósito general) y

```bash
cd backend
uv run --group rag python ../evals/run_retrieval_eval.py --juez ollama --etiqueta unica
uv run --group rag python ../evals/run_retrieval_eval.py --juez ollama --multiconsulta --etiqueta multi
```

Si la multi-consulta gana con ese juez, activar `MORPHOS_RAG_MULTICONSULTA=true` y confirmar en
generación con `run_evals.py`.
