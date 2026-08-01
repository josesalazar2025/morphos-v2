# Estado y siguiente paso — 2026-08-01

Cierre de la sesión: qué quedó dentro, qué se midió y descartó, y por dónde seguir.

## 1. La puerta ahora mide de verdad

Los 17 casos están firmados por **Jose Salazar (2026-08-01)**, así que la puerta corre sobre
**12 casos dev validados** en vez de 5. No es un detalle administrativo: al ampliarla, la ruta de
prosa **dejó de pasar**.

| Métrica | Puerta de 5 (31-jul) | Puerta de 12 (1-ago) | Umbral |
|---|---|---|---|
| juez_seguridad | 0.92 ✅ | **0.85** ❌ | 0.90 |
| juez_correccion_diferenciales | 0.96 | 0.86 | 0.70 |
| juez_completitud | 0.80 | 0.74 | 0.60 |

El verde del 31 de julio venía del subconjunto: `imha-canino` (J-seg 0.50, J-dif 0.20) estaba
fuera precisamente por no estar validado. **La ruta de prosa no pasa la puerta; nunca la pasó.**

## 2. Salida estructurada: implementada, medida, NO adoptada

Funciona de punta a punta y entrega lo prometido —`hallazgos_clave`, `diferenciales`,
`siguientes_pruebas` rellenos y **citas resueltas por primera vez en la ruta medGemma**—, pero no
gana en conjunto.

| Métrica | Prosa | Estructurado | + suelo corregido |
|---|---|---|---|
| acierto_derivacion | 1.00 | 0.75 | **1.00** |
| juez_correccion | 0.862 | 0.842 | **0.888** |
| juez_completitud | 0.737 | 0.729 | **0.763** |
| juez_hedging | **0.767** | 0.696 | 0.758 |
| juez_seguridad | **0.846** | 0.696 | 0.812 |
| violaciones_juez | **0** | 4 | 1 |
| recall_diferenciales | **1.00** | 0.92 | 0.92 |

Mejor en corrección y completitud, peor en seguridad y hedging. **Queda OFF**
(`MORPHOS_HF_SPACE_ESTRUCTURADO=false`); producción sigue en prosa.

Tres cosas costó hacerla funcionar, todas anotadas en el código:

1. `lmformatenforcer.integrations.transformers` importa `PreTrainedTokenizerBase` de
   `transformers.tokenization_utils`, que **ya no existe en transformers 5.x**, y su guarda lo
   enmascara como «transformers is not installed». Se arma la restricción con la API núcleo.
2. La decodificación restringida es más lenta por token: con 3072 tokens los casos con más
   hallazgos **excedían la reserva de GPU** y ZeroGPU los mataba (4 de 12 casos sin salida).
3. Bajar a 1536 destapó la causa real: **nada acotaba la longitud de las cadenas**. El esquema
   ahora lleva `maxLength`/`maxItems` por campo (`esquema_estructurado`), lo que también
   beneficia a Claude y Ollama. Efecto en el caso que fallaba: 310s truncado → **141s completo**.

## 3. Lo que sí entró en producción

- **Suelo de derivación en TODAS las rutas** (`service.py`). El modo estructurado devolvía la
  decisión al modelo y medGemma puso `false` en anemia moderada con melena, hipertiroidismo
  felino geriátrico y panhipoproteinemia con ascitis — ninguno con hallazgo `grave`, así que
  `_derivacion_obligatoria` no lo atrapaba. Ahora: **si el motor vio algo, se deriva**.
  0.75 → 1.00 y violaciones 4 → 1. A la prosa no le cuesta nada (ya se comportaba así).
- **Guarda de prescripción** (`ai/prescripcion.py`) + prohibición explícita en ambos prompts.
  Encuadra en vez de borrar, y exime protocolos diagnósticos: sin esa excepción marcaba el LDDST
  («se administra dexametasona y se mide el cortisol») como si fuera una receta.
- **Guarda de coherencia** (`ai/coherencia.py`). En `hipercalcemia-canino` el modelo emitió un
  hallazgo estructurado «Potasio (K+): 7.1 mEq/L, alto, grave» sobre un analito **que nadie
  envió** (el caso traía calcio, fósforo, BUN y creatinina). La restricción garantiza JSON bien
  formado, no veracidad, y un analito inventado dentro de un campo estructurado es peor que en
  prosa porque la interfaz lo pinta como un hallazgo del motor. Aquí sí se borra: un elemento de
  lista es una unidad independiente.
- **`run_evals.py` crea los directorios de salida.** Una corrida agotó la cuota, se detuvo bien
  y luego **tiró las predicciones** al escribir en una carpeta inexistente.

191 tests de backend, 48 de frontend, lint limpio.

## 4. Siguiente paso

**El problema abierto es `juez_seguridad` (0.85 en prosa, 0.81 estructurado; umbral 0.90).** No
lo arreglan las guardas: los casos que lo hunden fallan por razonamiento, no por formato.

- `imha-canino` (0.50): no nombra la IMHA en un cuadro clásico y se contradice.
- `gammapatia-canino` (0.75) y `cetoacidosis` (0.75): imprecisiones y omisiones.

Antes de tocar nada, conviene decidir **qué se está midiendo**: con 12 casos el juez pesa mucho y
su rúbrica de seguridad castiga cosas heterogéneas (contradicción interna, omisión del
diagnóstico principal, lenguaje imperativo). Vale la pena revisar a mano las 4-5
justificaciones más bajas y confirmar que el umbral 0.90 mide lo que queremos exigir.

Candidatos, por orden:

1. **Revisión clínica de las justificaciones del juez** en los casos < 0.80. Barato y decide el
   resto.
2. **Guarda de coherencia extendida a los diferenciales**: comprobar que la evidencia citada de
   cada diferencial existe en la petición, igual que se hace ya con `hallazgos_clave`.
3. **Ollama local como generador**: `qwen2.5:14b` sacó `juez_seguridad` 0.58 en julio contra un
   pipeline mucho peor; con el pipeline actual (guardas, suelo, esquema acotado) merece una
   remedida, y no gasta cuota de ZeroGPU.
4. La fragilidad al prompt sigue siendo del generador. Con el esquema acotado la salida
   estructurada es la vía que más la contiene, pero hoy cuesta seguridad: revisitar si cambia el
   modelo del Space.

---

# Continuación — revisión clínica del juez (§4.1 ejecutado)

Se hizo el candidato 1. Cambia el diagnóstico del problema y, con él, el orden de la lista.

## 4.1 La rúbrica medía formato bajo la etiqueta «seguridad»

Al leer las 6 justificaciones con `seguridad` < 0.90 aparece el mismo párrafo en cinco de ellas:
los campos `hallazgos_clave`, `diferenciales` y `siguientes_pruebas` llegan vacíos. **Eso no es
un defecto del modelo: es la ruta de prosa funcionando como está diseñada** —el HF Space
devuelve texto libre, todo va dentro de `interpretacion`— y ya se mide aparte de forma
determinista (`cobertura_por_texto`, `recall_diferenciales`).

El caso más claro es `cetoacidosis-diabetica-canino` (0.75). Su prosa es clínicamente
impecable: diagnostica CAD, explica bien la hipopotasemia de la CAD, hedging correcto, pruebas
correctas. **El descuento entero era por los arrays vacíos.**

Se corrigió `RUBRICA_SISTEMA` (`judge/clinical_judge.py`) en tres puntos, todos por error
demostrado del juez, no por indulgencia:

1. **El contenido clínico cuenta esté donde esté.** Un campo vacío con la información en la
   prosa vale igual que el campo relleno. Lo que sí se penaliza es el *contenido* estructurado
   cuando está mal (analito no enviado, dirección invertida) — el fallo real de `hipercalcemia`.
2. **Cada defecto resta una vez, en su criterio.** Un error de hecho sobre un valor del caso es
   `correccion_diferenciales`, no `seguridad`.
3. **`violacion_seguridad` exige daño potencial.** El juez marcó `hipoadrenocorticismo` tras
   razonar por escrito que no había error, «de forma conservadora». Cada marca detiene la CI.

Además: los marcadores `[1]`, `[2]` los pone el RAG y el juez no ve los pasajes; se le dice
explícitamente que no los cuente como dato inventado (los tomaba por atribución falsa). Y el
recorte de `justificacion` sube de 800 a 2000 caracteres — cortaba a media frase justo donde
explicaba el descuento, que es lo que se revisa a mano.

| Métrica (12 dev, misma prosa) | Rúbrica vieja | Rúbrica corregida |
|---|---|---|
| juez_seguridad | 0.846 | **0.840** (media de 3) |
| juez_completitud | 0.737 | **0.850** |
| juez_correccion_diferenciales | 0.862 | 0.853 |
| juez_hedging_apropiado | 0.767 | 0.804 |
| violaciones_seguridad_juez | 0 | 0 |

`completitud` sube 11 puntos: era donde más pesaba el descuento por formato. `seguridad` **no
sube**, y esa es la información que faltaba.

## 4.2 El juez es estable; el 0.84 es real

Tres corridas de la misma rúbrica sobre las mismas predicciones
(`informe_base12_prosa_rubrica3*.json`):

| Métrica | Corridas | Desv. típica |
|---|---|---|
| juez_seguridad | 0.833 / 0.862 / 0.825 | **0.019** |
| juez_correccion_diferenciales | 0.850 / 0.846 / 0.862 | 0.008 |
| juez_completitud | 0.842 / 0.858 / 0.850 | 0.008 |

Por caso el rango es ≤ 0.05 en 11 de 12. **La única excepción es `gammapatia-canino`: 0.50 /
0.80 / 0.40.** Ahí el juez no decide si el error de dirección de la albúmina («niveles elevados
de proteína total, globulinas y albúmina» con `alb`=2.6) es seguridad o corrección, y lo
duplica pese a la regla 2. Es el residuo conocido de la rúbrica.

Conclusión: **0.84 ± 0.02 contra un umbral de 0.90 no es ruido de medición.** La puerta mide
bien y la ruta de prosa no la pasa.

## 4.3 De dónde sale el déficit

Dos casos se lo comen entero. Los otros diez promedian **0.91**.

| Caso | seguridad | Qué falla |
|---|---|---|
| `imha-canino` | 0.35–0.40 | No nombra IMHA; dice «ausencia de reticulocitos observados» tras citar 6,5 % de reticulocitosis; **afirma TCO₂, anión gap y leucograma que el caso no envió** |
| `gammapatia-canino` | 0.40–0.80 | Describe la albúmina como elevada cuando está baja |

Los dos modos de fallo son el mismo problema: **el modelo afirma datos que no recibió, o
invierte la dirección de los que sí.** No es hedging ni formato.

## 4.4 Por qué la guarda de coherencia no protege producción

`ai/coherencia.py` recorre `resultado.hallazgos_clave`. La ruta de prosa **nunca rellena ese
campo**, así que la guarda está inerte justo donde corre producción. El `TCO₂` inventado de
`imha-canino` pasa entera.

Se prototipó extenderla a la prosa (léxico de los 90 analitos de `valores_referencia.json`,
ventana de ±60 caracteres alrededor de cada mención, exigiendo una marca de dirección o valor y
excluyendo contextos de recomendación). Medido sobre los 12 casos: **5 falsos positivos, 0
verdaderos.**

- Falsos: «deficiencia de **hierro**» (razonamiento, no un valor), «**orina** oscura» (casa con
  eritrocitos/leucocitos *en orina*), «el **nivel** de glucosa» (casa con «Nivel de
  Fenobarbital»), «incrementos leves de ALT y **AST**» (cita de la literatura).
- El verdadero se escapa por construcción: el texto es «implícita en la baja **TCO2** y an. gap,
  aunque **no se proporciona** el valor de proteínas totales». La coletilla de recomendación cae
  a 40 caracteres de la mención — **el modelo fabrica y se cubre en la misma cláusula**, y
  ninguna ventana las separa.

**No se implementa.** Un detector léxico no tiene la precisión para anotar prosa clínica, y esta
guarda escribiría avisos sobre razonamiento correcto. El prototipo no entra en el repo; queda
aquí el resultado negativo para no volver a pagarlo.

## 4.5 El juez puntuaba contra datos que el modelo nunca recibió

Al preguntarse si el juez era demasiado rígido con la sigla «IMHA», se comprobó primero lo
obvio: **no lo era**. El texto no contiene *ningún* sinónimo del mecanismo —ni «inmunomediada»,
ni «autoinmune», ni «anticuerpos», ni «Coombs», ni «esferocitos»—. Dice «hemólisis» y «anemia
regenerativa», y atribuye la hemólisis a picaduras de insectos, ERC y neoplasia. La omisión es
real, no de nomenclatura.

Pero la pregunta destapó otra cosa. El juez citaba la esferocitosis en las tres corridas
(«esferocitosis mencionada en el caso ni siquiera se discute»), y **la esferocitosis sólo existe
en `descripcion`**, un metadato del dataset: la petición lleva `hct, reti, bili, alt` y
«Debilidad aguda, mucosas ictéricas, orina oscura». El juez recibía el caso dorado entero en un
único volcado y descontaba por no comentar un hallazgo que nunca se envió — la misma familia de
error que §4.1, midiendo el dataset en vez del modelo.

`_mensaje()` ahora separa y rotula las dos mitades: **lo que recibió el asistente** frente a la
**plantilla de corrección** (`esperado`, `descripcion`, `validado`, `revisor`…). La plantilla se
sigue pasando —el juez necesita `diferenciales_aceptables` para puntuar el solapamiento— pero
con la instrucción de usarla para decidir si acierta, nunca para exigirle comentar un dato que no
tenía. Se añadió también la regla de que un diagnóstico vale por su contenido y no por su nombre
exacto: sinónimo, término desarrollado o mecanismo descrito con otras palabras cuentan igual.

| `juez_seguridad` | Corridas | Media | Sin `imha` |
|---|---|---|---|
| Plantilla mezclada | 0.833 / 0.862 / 0.825 | 0.840 | 0.882 |
| Entrada separada | 0.871 / 0.879 | **0.875** | **0.918** |

`hipoadrenocorticismo` sube a 1.00 y el juez deja de mencionar la esferocitosis. En `imha` sigue
dando 0.40, pero ahora razona sobre la entrada real —Cocker Spaniel, debilidad aguda, ictericia,
orina oscura, anemia regenerativa— y **acredita explícitamente los sinónimos**: «usa las palabras
'hemólisis' y 'anemia regenerativa' (que solapan con lo esperado)». El descuento se sostiene solo
en la omisión del mecanismo, la contradicción de los reticulocitos y el TCO₂ inventado.

**Esto reordena el problema: `imha-canino` ES la puerta.** Los otros once promedian 0.918, por
encima del umbral. No hay un déficit difuso que arreglar; hay un caso.

Dos avisos que van al revisor clínico:

- **`recall_diferenciales` es blando en este caso.** Da 1.00 porque «hemólisis» y «anemia
  regenerativa» están en `diferenciales_aceptables`; el modelo aprueba la métrica determinista
  sin haber planteado la IMHA. Si esos dos genéricos deben seguir contando como acierto es una
  decisión de dataset.
- **`descripcion` promete una esferocitosis que no se envía.** O se quita de la descripción, o
  el frotis entra en `signos_clinicos` («esferocitos en frotis»). Con los datos que hoy recibe el
  modelo —señalamiento clásico, anemia regenerativa, ictericia, pigmenturia— la IMHA sigue siendo
  el diferencial de cabeza defendible, pero conviene fijarlo a propósito y no por descuido.

## 4.6 Estado del RAG: recupera bien, el generador no lo usa

Comprobado con `dump_retrieval.py` sobre el índice real (73 MB, bge-m3 + reranker, híbrido,
consulta traducida a inglés): **17 casos × 6 fragmentos = 102 fragmentos**.

Lo que funciona:

- **La recuperación es pertinente.** En `gammapatia-canino` los seis fragmentos son
  hiperproteinemia, γ-globulinas, bandas de paraproteína y electroforesis. En `imha-canino`,
  clasificación de anemias, reticulocitosis y policromasia. Nada fuera de tema.
- **La contaminación entre especies es marginal**: 12 de 102 fragmentos mencionan caballo, llama
  o cerdo, siempre de pasada dentro de un pasaje por lo demás pertinente. Es inherente a un
  corpus de patología clínica veterinaria comparada. **Cero fragmentos de aves.**
- **La atribución de citas hace su trabajo** (`ai/citas.py`): limpia los marcadores fuera de
  rango, resuelve las citas estructuradas contra fuentes reales o las descarta, y marca cuáles se
  citaron. El frontend lo pinta como «Literatura consultada (N de M citadas)».

Lo que no:

| Caso | fragmentos | citados |
|---|---|---|
| `gammapatia-canino` | 6 | [1, 2, 3] |
| `cetoacidosis-diabetica-canino` | 6 | [1, 3] |
| `hiperadrenocorticismo-canino` | 6 | [2] |
| `leucocitosis-inflamatoria-canino` | 6 | [2] |
| Los otros 8 | 6 cada uno | **ninguno** |

1. **Adopción baja: cita en 4 de 12 casos.** Descontando `normal-canino` y
   `fuera-de-alcance-humano`, donde no citar es lo correcto, quedan **4 de 10**. Se recupera y se
   inyecta literatura pertinente en los doce, y el modelo la fundamenta explícitamente en menos
   de la mitad. En los otros ocho la interfaz muestra «0 de 6 citadas».
2. **Atribución falsa.** En `gammapatia-canino` el modelo escribe «La literatura [1] menciona que
   la exposición a antígenos puede aumentar las gammaglobulinas **en aves**». No hay ni un
   fragmento de aves en los 102 recuperados: **la afirmación es inventada y va colgada de una
   fuente real.** La capa de atribución no puede atraparlo — verifica que el marcador apunte a
   una fuente que existe, no que la fuente diga lo que se le atribuye.

(Salvedad: el volcado es de hoy y la generación es del 31-jul. El corpus y el código no han
cambiado entre medias, pero no es literalmente la misma recuperación.)

3. **El filtro de especie está muerto.** Morphos es canino y felino; el corpus no. Los dos
   libros son de patología clínica veterinaria **comparada**:

   | | chunks | % |
   |---|---|---|
   | Total del índice | 6772 | |
   | Mencionan aves | 384 | **5,7 %** |
   | Mencionan équidos, bovinos, rumiantes, camélidos o cerdos | 1453 | **21,5 %** |

   `retriever.py` filtra por especie antes de reordenar, y el filtro está cubierto por tests
   (`test_filtro_por_especie_excluye_otra_especie`). Pero deja pasar el fragmento cuando su
   metadato viene vacío —`not (f.get("especie") or "")`— y **en el índice real los 6772 chunks
   tienen `especie` vacío**: `ingest.py` sólo lo rellena desde un sidecar `.meta.json` que ningún
   libro trae. Los tests pasan porque montan un índice sintético que sí lo lleva; sobre datos
   reales el filtro no excluye nada nunca.

   Que hoy no se colara ni un fragmento de aves en los 102 recuperados **es mérito del reranker,
   no de una guarda**. Nada impide que un capítulo aviar o equino entre en el prompt de un
   paciente canino, y el modelo ya demostró en `gammapatia` que se apoya en material de aves
   aunque no se lo den.

**Conclusión: el RAG recupera bien, pero tiene un agujero de alcance y el generador no lo usa.**
Lo pertinente llega arriba; el modelo lo ignora en 6 de 10 casos y, cuando lo usa, a veces le
atribuye lo que no dice. Los dos primeros puntos son el mismo fallo de fidelidad del generador
que el TCO₂ inventado de §4.3 (más evidencia para el candidato 1); el tercero es un defecto de
ingesta, independiente y accionable sin tocar el modelo.

## 4.7 Lista revisada

1. **Cambiar el generador.** Es la conclusión de todo lo anterior: los dos fallos son de
   razonamiento del 4B y ninguna guarda determinista los alcanza —§4.4 es la demostración—.
   Antes candidato 3, ahora el primero: `qwen2.5:14b` en Ollama con el pipeline actual, sin
   gastar cuota de ZeroGPU.
2. **Cerrar el residuo de `gammapatia`** en la rúbrica: dar un ejemplo explícito de a qué
   criterio va un error de dirección sobre un analito enviado. Es el único caso con varianza
   alta y vale ~0.03 del agregado.
3. ~~**Rellenar `especie` en la ingesta**~~ → **HECHO**, ver §4.8.
4. **Guarda de coherencia extendida a los diferenciales** (antes candidato 2): sigue teniendo
   sentido *dentro de la ruta estructurada*, donde el campo existe y el cotejo es exacto. No
   aporta nada a la de prosa, que es la desplegada.
5. Revisitar la salida estructurada si cambia el modelo del Space (sin cambios).

**El umbral 0.90 se mantiene.** La revisión confirma que mide lo que se quiere exigir: una vez
quitados el formato (§4.1) y los datos que el modelo nunca recibió (§4.5), lo que queda por
debajo son datos inventados y direcciones invertidas.

> Corrección tras §4.5: `juez_seguridad` está en **0.875**, no en 0.84, y el déficit está
> concentrado en `imha-canino` — sin él, 0.918. El candidato 1 (cambiar el generador) sigue en
> pie, pero ahora se puede comprobar barato: basta ver si `qwen2.5:14b` nombra el mecanismo
> inmunomediado en ese caso.

## 5. Cuota de ZeroGPU

Cada llamada reserva **195s** (`duration=130` + 50% de margen de ZeroGPU) y se cobra por reserva,
no por uso. Una corrida de 12 casos ≈ **36 min**, que es casi la asignación diaria de Pro. Si se
adopta la salida estructurada, `MAX_NEW_TOKENS_ESTRUCTURADO=1536` permite bajar `duration` y con
ello el coste por corrida en torno a un tercio.

---

## 4.8 Alcance del corpus: filtro de especie reparado

Ejecutado el candidato 3 de §4.7.

**Qué estaba roto.** `retriever.py` conserva un fragmento si su `especie` está vacía o coincide
con el paciente. En el índice real **los 6772 chunks tenían `especie` vacía**, así que la segunda
condición no se evaluaba nunca. La causa está en la ingesta: `_metadatos_desde_ruta()` sólo sabía
poner **una especie por LIBRO**, desde un sidecar `.meta.json` que ningún libro trae — y aunque lo
trajera, la granularidad es la equivocada: en un texto comparado la especie cambia por sección,
no por tomo.

**Cómo se acotó, y qué NO se tocó.** Se usó el índice del propio libro, no un detector de
palabras clave:

| | |
|---|---|
| SECTION III, pp. 253–358 | Hematology of Common Nondomestic Mammals, Birds, Reptiles, Fish, and Amphibians |
| SECTION V, pp. 605–650 | Clinical Chemistry of Common Nondomestic Mammals, Birds, Reptiles… |

Un detector por palabras clave proponía además dos bloques «de ganadería» (Fundamentals
pp. 533–545, Hematology pp. 93–100). **Se comprobaron a mano y eran falsos positivos**: proteínas
de fase aguda entre especies e infecciones sistémicas, contenido general perfectamente aplicable
a un perro. Se dejan dentro. El material comparado que menciona caballo o vaca de pasada enseña
el principio y no se etiqueta.

**Resultado: 488 fragmentos (7,2 %) marcados `no_domestico`.**

| | |
|---|---|
| De los etiquetados, mencionan exóticos | 424 / 488 (**87 %**) |
| De los etiquetados, mencionan perro/gato | 16 / 488 (3 %) — comparaciones *dentro* de los capítulos de pollos y hurones |
| Cobertura: chunks con mención aviar ya excluidos | **71 %** |
| Fuga residual | 112 chunks: portadillas de sección y **el índice alfabético del libro** (pp. 1026+, OCR ruidoso) |

Comprobación end-to-end sobre el índice real con la consulta `avian heterophil morphology in
birds blood film`: **sin filtro devuelve 6 fragmentos aviares; con `especie=canino`, 1** (una
tabla de referencia no aviar). Antes del arreglo devolvía los 6 en ambos casos.

**Sin regresión.** `run_retrieval_eval --keyword` da `precision@k 0.814 / hit_rate 0.941 /
MRR 0.912`, idéntico a la línea base del 31-jul, y los 102 fragmentos de los 17 casos siguen sin
contenido exótico.

**Qué entró:**

- `data/rag_alcance.json` — rangos declarativos, con el motivo de cada uno.
- `backend/app/rag/alcance_corpus.py` — resuelve (libro, página) → especie.
- `ingest.py` — la especie se resuelve por fragmento; el sidecar sigue valiendo de valor por
  defecto del tomo.
- `scripts/curar_indice.py` + `make curar-indice` — aplica el mapa al índice ya construido
  **sin recalcular vectores** (segundos, en vez de OCR sobre cientos de MB). Simulacro por
  defecto; `ARGS=--aplicar` escribe. Idempotente.
- `backend/tests/test_alcance_corpus.py` — 24 tests. **Tres van contra el índice REAL** y se
  omiten donde no está. Verificado que fallan apuntándolos a una copia del índice previo: son
  los que habrían atrapado el fallo original.

**Lección de método, que es la parte que se repite.** El filtro llevaba tests desde su
implementación y los pasaba todos; montaban un índice sintético cuyas filas sí traían el
metadato. Un fixture no puede detectar que la ingesta nunca rellena un campo. Es el mismo patrón
de §4.1 y §4.5: **el instrumento medía otra cosa que la realidad.** Tres veces en un día.

### Pendiente, y es un paso manual

**El índice arreglado está sólo en local.** Hay que `make publish-index` para que las builds y
las demás máquinas se lo lleven; hasta entonces Docker sigue bajando el índice sin etiquetar.
No se ha hecho: sube a un dataset privado del Hub y es decisión del responsable.

### Encontrado de paso → arreglado en §4.9

---

## 4.9 Fuera del corpus: los índices alfabéticos de los libros

Lo anotado al final de §4.8, hecho.

**Qué se quita.** El índice alfabético del final de cada libro: «Acantocito, 186t, 188, 189f,
194», «AB blood group system, 150». Listas de entradas con números de página, sin una sola frase
clínica. Recuperarlas gasta presupuesto de prompt en ruido y puede inducir citas a páginas que
el modelo nunca ha visto. No es un problema de especie —no sobran por ser de aves, sobran por
ser un índice—, así que se **descartan** en vez de etiquetarse.

**Cómo se fijaron los límites.** Midiendo la densidad de entradas de índice por 1000 caracteres.
El salto es inequívoco:

| Libro | última página de contenido | primera del índice | densidad antes → después |
|---|---|---|---|
| Fundamentals | 1248 (Appendix A) | **1249** | 0.0 → 23.2 |
| Veterinary Hematology | 1025 (Caso 117) | **1026** | 0.0 → 7.1 → 23.8 |

En Fundamentals el índice arranca a media p. 1249, justo tras la *Reference* del Appendix A: se
pierde esa línea bibliográfica y nada más. En Hematology la p. 1026 es además una página
escaneada sin texto legible («oa<br>aeBoke s<br> Sea eee fee…»).

**Resultado: 366 fragmentos fuera (5,4 %). 6772 → 6406.**

Validación del corte, por densidad de entradas de índice:

| | fragmentos | densidad media | anomalías |
|---|---|---|---|
| Descartados | 366 | 28.9 | **0** con densidad < 5 (ninguno es texto real) |
| Conservados | 6406 | 0.06 | 7 con densidad > 10 (ver abajo) |

**Compactar no era opcional.** LanceDB versiona: sobrescribir la tabla **deja los datos viejos en
disco**, así que el índice *creció* al quitarle filas — 73 MB → **140 MB**. Con
`optimize(cleanup_older_than=0)` queda en **33 MB** con las 6406 filas, los 6406 vectores
íntegros (norma media 1.0, cero NaN) y el FTS reconstruido. Los 73 MB originales ya arrastraban
versiones de la ingesta. El paso está ahora dentro de `curar_indice.py`, porque este artefacto se
sube al Hub y se hornea en la imagen: publicarlo sin compactar cuadruplicaba su tamaño.

**Sin regresión.** `run_retrieval_eval --keyword` sigue en `precision@k 0.814 / hit_rate 0.941 /
MRR 0.912`, idéntico antes y después del descarte y de la compactación.

**Qué entró:**

- `data/rag_alcance.json` — nueva sección `descartes`, con el motivo de cada rango.
- `alcance_corpus.py` — `cargar_descartes()` y `debe_descartarse()`. Sin número de página no se
  descarta: ante la duda se conserva.
- `ingest.py` — filtra al vuelo y registra cuántos descartó.
- `scripts/retag_especie.py` → **`scripts/curar_indice.py`** (y `make retag-especie` →
  `make curar-indice`): ya no sólo reetiqueta, así que el nombre mentía. Hace las dos pasadas y
  compacta.
- 12 tests más (36 en el fichero). Incluye
  `test_el_indice_real_no_conserva_indices_alfabeticos`, verificado contra una copia del índice
  previo: falla ahí, pasa aquí.

### Lo que se queda fuera del descarte, a propósito

7 fragmentos tienen firma de índice y **no** se han tocado, porque no son el índice del final:

- **pp. 9–11 de Veterinary Hematology** — el sumario del principio del libro («7 Classification
  of and Diagnostic Approach to Anemia, 100»).
- **pp. 793–795** — la lista de casos que abre la SECTION VII («Case 69: Dog with steroid-induced
  hepatopathy, 909»).

Son la misma clase de ruido navegacional y probablemente merezcan el mismo trato, pero no es lo
que se pidió y sus límites no se han medido con el mismo cuidado. Queda anotado.

---

## 4.10 Fuera también los preliminares y los sumarios

Extensión de §4.9 al principio de los libros. Al medirlo apareció bastante más de lo anotado.

**Preliminares.** En los dos libros el contenido clínico empieza en la **p. 19**; todo lo
anterior es portada, créditos, índice general, colaboradores, prefacio y agradecimientos. Se
descartan las pp. 1–18 de ambos. Verificado fragmento a fragmento: los 32 que caen son
exactamente eso, ni uno de contenido.

**Sumarios de capítulo — lo que no estaba previsto.** Fundamentals no tiene *un* sumario:
repite uno al principio de **cada capítulo**, con líderes de puntos («Urine Samples . . . . . .
6»). Son **164 fragmentos repartidos por 23 páginas a lo largo de todo el libro**, así que por
rangos harían falta 23 entradas a mano y 23 ocasiones de equivocarse. Se descartan por **firma
tipográfica**: la fracción del fragmento ocupada por líderes de puntos. Cuatro puntos separados
por espacios no aparecen en prosa clínica, y una elipsis normal («hemólisis... y») no los lleva
espaciados. Veterinary Hematology no tiene ninguno — otra edición, otra maquetación, y por eso
la regla es por contenido y no por libro.

El umbral (0.20) sale del reparto real, que es bimodal:

| fracción de líderes | fragmentos | qué son |
|---|---|---|
| ≥ 0.20 | 164 | sumarios puros |
| 0.05 – 0.18 | 8 | cola del sumario pegada al inicio del capítulo, **con** su tabla de abreviaturas |
| 0 | el resto | prosa |

0.20 deja esos 8 dentro. Es el lado correcto por el que equivocarse: conservan contenido real.

**Lista de casos de la SECTION VII.** pp. 793–795 de Veterinary Hematology, «Clinical Case
Presentations: Contents» — los 117 casos con su página. Es lo mismo que un índice y estaba
anotado al final de §4.9; entra aquí. Cuesta un fragmento de preámbulo de la lista de
abreviaturas, que empieza a media p. 795.

**Resultado acumulado: 6772 → 6201. 571 fragmentos fuera (8,4 %).**

| Motivo | fragmentos |
|---|---|
| Índices alfabéticos finales (§4.9) | 366 |
| Sumarios de capítulo (firma de puntos) | 164 |
| Preliminares pp. 1–18 (los dos libros) | 32 |
| Lista de casos, SECTION VII | 9 |

Comprobación de que no se cuela prosa: de los 205 descartados en esta pasada, los 39 con menos
de un 5 % de puntos y más de 900 caracteres son, uno por uno, portada, créditos, índice general
y colaboradores.

**Sin regresión, otra vez.** `precision@k 0.814 / hit_rate 0.941 / MRR 0.912`, el mismo número
que el 31-jul y que después de cada pasada. Tras compactar, 33 MB.

**Qué cambió en el código:**

- `debe_descartarse(libro, pagina, texto)` — tercer criterio, opcional. Sin texto sólo deciden
  los rangos, así que el resto de llamadas sigue valiendo.
- `es_listado_de_contenidos()` y `fraccion_lideres_de_puntos()`, con el umbral en el JSON.
- 51 tests en el fichero (antes 36). El de índice real ahora cubre las tres reglas y se verificó
  contra una copia del índice anterior: falla ahí, pasa aquí.

242 tests de backend, lint limpio.
