# Dataset dorado de evaluación clínica

Casos validados por veterinario, en `casos.jsonl` (un caso JSON por línea).

> **Origen de los casos.** Se construyen a partir de los resultados de laboratorio y
> citologías reales aportados por veterinarios ejercientes (ver `USO_DE_IA.md`). Cada caso
> debe llevar sus diferenciales aceptables revisados por un profesional antes de entrar al
> set. Hay **43 casos** en tres tandas:
>
> | Tanda | N | Estado |
> |---|---|---|
> | Semilla original | 7 | ✅ validada (`semilla-veterinaria`) |
> | Ampliación 2026-07 (imha, cushing, pancreatitis…) | 10 | ✅ firmada por Jose Salazar el 2026-08-01 |
> | **Ampliación 2026-08-03 (cobertura de analitos)** | **26** | ⏳ **PENDIENTES de validación** |
>
> La tercera tanda se redactó **con IA como borrador** para cubrir los 58 analitos que ningún
> caso ejercitaba (coagulación, gasometría, hormonas, urianálisis, fármacos, SDMA). Está
> verificada de tres formas —claves y rangos contra `valores_referencia.json`, hallazgos
> confirmados uno a uno contra el motor real, y afirmaciones clínicas contrastadas con el
> corpus RAG y las guías IRIS— pero **eso no la convierte en oro**: un profesional debe
> revisar sus `diferenciales_aceptables` antes de que cuenten para la puerta.

Ese estado ya no vive sólo en este README: cada caso lleva su `validado` y su `split`, y
`run_evals.py` los respeta. Un caso pendiente se puntúa y se muestra, pero **no cuenta para
la puerta**. Estado actual: **17 validados / 26 pendientes**, **30 dev / 13 test**.

## Cobertura de analitos

Con la ampliación del 2026-08-03 el dataset ejercita **los 90 analitos** de
`valores_referencia.json` (antes 32). La comprobación es reproducible: cada `hallazgos_clave`
declarado se contrastó contra lo que el motor marca de verdad, porque declarar como clave un
analito que el motor no señala deja la métrica de cobertura inalcanzable por construcción.

Dos casos documentan a propósito comportamientos del motor que no son erratas:

- **`erc-canino-sdma-discordante`** — la creatinina (1,6) está en rango y **no** se marca; la
  SDMA (24) sí. Es el escenario de discordancia que la guía IRIS describe para escalar de
  estadio, y por eso `creat` no figura entre los hallazgos clave.
- **`ciclosporina-monitorizacion-canino`** — los valores renales tuvieron que subirse porque el
  motor **ensancha los rangos en pacientes senior**: una azotemia leve en un perro de 7 años no
  se marca.

## Esquema de cada caso

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string | Identificador estable (kebab-case) |
| `descripcion` | string | Resumen del caso |
| `split` | `dev` \| `test` | `dev`: conjunto de iteración. `test`: reservado, sólo se mira en agregado y antes de desplegar |
| `validado` | bool | Firmado por un veterinario. Si es `false`, el caso queda fuera de la puerta |
| `revisor` | string | Quién lo firmó (obligatorio para validar) |
| `fecha_validacion` | string | ISO-8601 de la firma |
| `paciente` | objeto | `especie`, `raza`, `edad_meses`, `sexo` |
| `valores` | objeto | Analitos crudos (misma clave que `valores_referencia.json`) |
| `signos_clinicos` | string | Texto clínico libre |
| `esperado.hallazgos_clave` | string[] | Claves de analito que deben marcarse alteradas |
| `esperado.diferenciales_aceptables` | string[] | Conjunto de diferenciales correctos (se acepta cualquier solapamiento) |
| `esperado.requiere_derivacion` | bool | Si el caso debe marcar derivación al veterinario |
| `esperado.fuera_de_alcance` | bool | Si el modelo debe declinar (fuera del dominio) |

## Métricas y umbrales

`run_evals.py` evalúa, por caso y agregado:

- **Cobertura de hallazgos** — recall de `hallazgos_clave`. Se mide sobre el campo
  estructurado cuando el modelo puede rellenarlo y sobre la prosa (menciones del analito o de
  su alteración: «hiperfosforemia» cuenta como fósforo) cuando no, porque la ruta por defecto
  en producción devuelve texto libre y sólo con el campo estructurado la métrica quedaba
  clavada en 0.00. En la salida por caso, `cob=1.00~` marca la medición sobre prosa.
- **Recall de diferenciales** — el modelo propone al menos un diferencial aceptable.
- **Seguridad** — `requiere_derivacion` correcto y `fuera_de_alcance` respetado
  (violaciones de seguridad deben ser **0**).
- **Idioma** — la interpretación está en español.
- **Groundedness / citas** — (con RAG) las afirmaciones se apoyan en la literatura citada;
  se puntúa con Ragas (`run_ragas.py`) y con el juez clínico.

Los umbrales de aprobado están en `run_evals.py` (`UMBRALES` y `UMBRALES_JUEZ`). La CI
bloquea el merge si alguna métrica cae por debajo o si hay cualquier violación de seguridad.

## Circuito de validación (human-in-the-loop)

```bash
make revision                                                   # hoja de revisión en Markdown
python evals/revision.py --validar <id> --revisor "Tu nombre"   # firma un caso
python evals/revision.py --estado                               # recuento por split/validación
```

La hoja (`revision_pendiente.md`, no versionada) trae por caso el señalamiento, los valores,
lo que marca el motor determinista y los diferenciales propuestos, para que la revisión no
obligue a abrir el JSONL. `--revisor` es obligatorio: una validación sin persona detrás no
es trazable.
