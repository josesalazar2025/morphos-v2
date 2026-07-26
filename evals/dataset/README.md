# Dataset dorado de evaluación clínica

Casos validados por veterinario, en `casos.jsonl` (un caso JSON por línea).

> **Origen de los casos.** Se construyen a partir de los resultados de laboratorio y
> citologías reales aportados por veterinarios ejercientes (ver `USO_DE_IA.md`). Cada caso
> debe llevar sus diferenciales aceptables revisados por un profesional antes de entrar al
> set. Hay **17 casos**: los **7 primeros** son la semilla validada; los **10 siguientes**
> (imha, hipertiroidismo, cushing, pancreatitis, leucocitosis inflamatoria, trombocitopenia,
> hipercalcemia, enteropatía perdedora, hepatocelular agudo, gammapatía) fueron **redactados
> con IA como borrador y están PENDIENTES de validación veterinaria** — clínicamente
> plausibles y con claves/valores verificados contra `valores_referencia.json`, pero un
> profesional debe revisar sus `diferenciales_aceptables` antes de tratarlos como oro.
> Amplíalo continuamente y mantén un split de validación reservado.

## Esquema de cada caso

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string | Identificador estable (kebab-case) |
| `descripcion` | string | Resumen del caso |
| `paciente` | objeto | `especie`, `raza`, `edad_meses`, `sexo` |
| `valores` | objeto | Analitos crudos (misma clave que `valores_referencia.json`) |
| `signos_clinicos` | string | Texto clínico libre |
| `esperado.hallazgos_clave` | string[] | Claves de analito que deben marcarse alteradas |
| `esperado.diferenciales_aceptables` | string[] | Conjunto de diferenciales correctos (se acepta cualquier solapamiento) |
| `esperado.requiere_derivacion` | bool | Si el caso debe marcar derivación al veterinario |
| `esperado.fuera_de_alcance` | bool | Si el modelo debe declinar (fuera del dominio) |

## Métricas y umbrales

`run_evals.py` evalúa, por caso y agregado:

- **Cobertura de hallazgos** — recall de `hallazgos_clave` frente al motor determinista.
- **Recall de diferenciales** — el modelo propone al menos un diferencial aceptable.
- **Seguridad** — `requiere_derivacion` correcto y `fuera_de_alcance` respetado
  (violaciones de seguridad deben ser **0**).
- **Idioma** — la interpretación está en español.
- **Groundedness / citas** — (con RAG) las afirmaciones se apoyan en la literatura citada;
  se puntúa con Ragas y con el juez clínico.

Los umbrales de aprobado están en `run_evals.py` (`UMBRALES`). La CI bloquea el merge si
alguna métrica cae por debajo o si hay cualquier violación de seguridad.
