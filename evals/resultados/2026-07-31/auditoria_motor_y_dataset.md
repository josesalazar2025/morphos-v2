# Auditoría del motor determinista y el dataset dorado frente a la literatura

**Fecha:** 2026-07-31 · **Fuentes:** las dos obras indexadas en el RAG —
`Veterinary Hematology, Clinical Chemistry, and Cytology`, 3.ª ed. (en adelante **Thrall**) y
`Fundamentals of Veterinary Clinical Pathology`, 3.ª ed. (**Fundamentals**)— 6.763 fragmentos.

## 1. Resumen ejecutivo

Lo que se auditó: los 90 rangos de referencia de `data/valores_referencia.json`, la
clasificación de gravedad de `analisis.ts`, los ajustes por edad/raza/sexo, los umbrales de los
patrones y los 17 casos del dataset dorado.

**El núcleo hematológico está bien.** Hct, Hgb, RBC, WBC, plaquetas, neutrófilos y linfocitos
absolutos coinciden **exactamente** con los intervalos que Thrall imprime en sus casos, con n
alto (27–48 apariciones cada uno) en canino, y lo mismo en felino. Eso es una validación
fuerte, no una coincidencia.

Los hallazgos que sí importan, por orden de riesgo clínico:

| # | Hallazgo | Riesgo | Evidencia |
|---|---|---|---|
| 1 | **La gravedad no puede expresar una anemia grave.** La regla genérica mide desviación en anchos de rango: en felino `grave` exigiría un Hct negativo; en canino, < 10 %. | Un gato con Hct 8 % o un perro con Hct 12 % salen `moderado` y **no disparan el suelo de derivación**. | `analisis.ts:24-36` + umbral de transfusión PCV ≤ 20 % (Thrall p. 240) |
| 2 | **Mismo defecto en plaquetas.** `grave` exigiría plt < −250 ×10³/µL. | Trombocitopenia con sangrado activo se clasifica `moderado`. La literatura sitúa el riesgo hemorrágico en **< 30 ×10³/µL** (Fundamentals p. 310). | ídem |
| 3 | **CHCM canino 32–36 vs 34–38** (n=29, muy consistente). Nuestro límite inferior está 2 g/dL bajo. | **Infradetección de hipocromía** → se pierde el marcador clásico de ferropenia en perro. | Thrall, 29 tablas |
| 4 | **VCM superior 77 (canino) / 55 (felino) vs 72 / 50.** | **Infradetección de macrocitosis** (regeneración, FeLV en gato). | Thrall, n=36 / n=5 |
| 5 | **Sin ajuste de fósforo por edad.** En cachorros el RI es ~2× el del adulto (perro 5,7–10,8 vs 2,5–5,5; gato 5,0–10,0 vs 1,8–6,4). | **Falsa hiperfosforemia en todo cachorro**, y con ella patrones renales falsos. | Fundamentals p. 831 |
| 6 | **El ajuste de raza Akita/Shiba va en la dirección equivocada.** Subimos RBC/Hct/Hgb un 8–10 %; lo que la literatura documenta es **VCM bajo** (microcitosis sin anemia). | Falsa "anemia microcítica" en estas razas, o enmascaramiento de una real. | Fundamentals p. 221 |
| 7 | **El ajuste de sexo (creatinina ×1,15 en gato macho) no aparece en ninguna de las dos obras.** Lo documentado es masa muscular (galgos) y **raza Birman**. | Tolerancia de creatinina no justificada en gatos macho → azotemia felina infradetectada. | Thrall p. 363, Fundamentals p. 585 |
| 8 | **Hiposteinuria a < 1,008; la literatura la sitúa en < 1,007.** | Un USG de 1,0075 se etiqueta hiposteinuria en vez de isosteinuria. | Thrall Tabla 24.8, Fundamentals p. 565 |
| 9 | **RI de USG = 1,013–1,100.** El "esperado" del libro es 1,020–1,045 (perro y gato). | Un USG de 1,015 no se marca como bajo pese a ser subóptimo. | Thrall Tabla 24.8 |
| 10 | **La hipercalcemia no usa el fósforo para discriminar**, que es *el* discriminador. | Se pierde el filtro que separa malignidad/hiperPTH primario de las demás causas. | Thrall p. 586, p. 997 |

**El dataset dorado sale bien parado:** los 17 casos son clínicamente coherentes y sus
diferenciales aceptables están respaldados. Tres mejoras menores en §7.

## 2. Metodología y límites

**Rangos de referencia (§3):** no se usó recuperación semántica. Se escanearon las 6.763 filas
de la tabla LanceDB extrayendo con expresión regular las filas de tabla markdown con forma
`|Analito (unidad)|valor|inferior–superior|`, que es como los libros presentan los casos
clínicos. La especie se infiere del señalamiento del propio fragmento y se descarta todo
fragmento que mencione otra especie. La clave del analito se decide **por unidad**, para no
confundir un recuento relativo (%) con uno absoluto (×10³/µL).

**Límites que hay que tener presentes al leer las tablas:**

1. **No existe "el" intervalo de referencia de la literatura.** Los libros imprimen el RI del
   laboratorio de cada caso. Por eso la columna «variantes» importa: el Hct canino aparece con
   5 intervalos distintos y el TCO2 con 3. Un "discrepa" frente al valor modal **no significa
   que estemos equivocados**; significa que conviene revisar la elección.
2. **Fundamentals casi no aporta filas.** Sus tablas no siguen el formato caso-valor-RI, así
   que la columna sale casi vacía. Su contribución a esta auditoría es cualitativa (§5 y §6),
   donde es la fuente más rica.
3. **n bajo en felino** para bioquímica (a menudo n=1). Un solo caso no fija un RI.
4. Los apartados §5–§7 sí usan recuperación semántica; cada afirmación lleva su cita.

## 3. Rangos de referencia: Morphos vs literatura

Δ se expresa como porcentaje del ancho de NUESTRO rango, para que sea comparable entre
analitos. «Variantes» = cuántos intervalos distintos imprime la fuente para ese analito.

### Canino

| Analito | Morphos | Thrall (modal) | n | variantes | Δ inferior | Δ superior | Veredicto |
|---|---|---|---|---|---|---|---|
| alb | 2.7–3.8 | 2.7–4.5 | 5 | 3 | +0% | +64% | **discrepa** |
| alt | 10–100 | 10–120 | 3 | 1 | +0% | +22% | **discrepa** |
| amylasa | 500–2000 | 200–1200 | 2 | 2 | -20% | -53% | **discrepa** |
| ast | 10–50 | 16–40 | 2 | 2 | +15% | -25% | **discrepa** |
| bili | 0–0.3 | 0–0.4 | 3 | 2 | +0% | +33% | dentro del abanico |
| bun | 7–25 | 7–28 | 4 | 2 | +0% | +17% | **discrepa** |
| calc | 9–11.3 | 9–11.2 | 4 | 3 | +0% | -4% | trivial (<5%) |
| **chcm** | **32–36** | **34–38** | **29** | 6 | **+50%** | **+50%** | **discrepa** |
| ck | 10–200 | 43–234 | 1 | 1 | +17% | +18% | **discrepa** |
| cloro | 105–122 | 106–127 | 16 | 5 | +6% | +29% | **discrepa** |
| colest | 110–320 | 131–320 | 2 | 2 | +10% | +0% | **discrepa** |
| **creat** | **0.5–1.5** | **0.9–1.7** | 7 | 4 | **+40%** | +20% | **discrepa** |
| eosino_abs | 0.1–1.25 | 0.1–1.2 | 26 | 5 | +0% | -4% | trivial (<5%) |
| fal | 23–212 | 35–280 | 5 | 3 | +6% | +36% | **discrepa** |
| fosf | 2.5–6.2 | 2.8–6.1 | 6 | 3 | +8% | -3% | **discrepa** |
| ggt | 0–7 | 0–6 | 1 | 1 | +0% | -14% | **discrepa** |
| glob | 2.7–4.4 | 2–3.8 | 7 | 4 | -41% | -35% | **discrepa** |
| gluc | 70–143 | 65–122 | 6 | 4 | -7% | -29% | **discrepa** |
| hcm | 19.5–24.5 | 22.4–26.2 | 2 | 2 | +58% | +34% | dentro del abanico |
| **hct** | **37–55** | **37–55** | **33** | 5 | +0% | +0% | **idéntico** |
| **hgb** | **12–18** | **12–18** | **36** | 6 | +0% | +0% | **idéntico** |
| **linfo_abs** | **1–4.8** | **1–4.8** | **41** | 5 | +0% | +0% | **idéntico** |
| lipasa | 0–200 | 12–147 | 1 | 1 | +6% | -26% | **discrepa** |
| magnesio | 1.7–2.5 | 1.6–2.2 | 2 | 2 | -12% | -37% | **discrepa** |
| mono_abs | 0.15–1.35 | 0.1–1.3 | 40 | 8 | -4% | -4% | trivial (<5%) |
| **neutro_abs** | **3–11.5** | **3–11.5** | **30** | 3 | +0% | +0% | **idéntico** |
| **plt** | **200–500** | **200–500** | **48** | 6 | +0% | +0% | **idéntico** |
| potasio | 3.7–5.8 | 4.1–5.5 | 9 | 4 | +19% | -14% | dentro del abanico |
| prot | 5.4–8.2 | 6–8 | 49 | 8 | +21% | -7% | **discrepa** |
| **rbc** | **5.5–8.5** | **5.5–8.5** | **34** | 5 | +0% | +0% | **idéntico** |
| rdw | 11.9–14.2 | 12.9–19.4 | 2 | 2 | +43% | +226% | **discrepa** |
| reti_abs | 0–80 | 0–60 | 3 | 3 | +0% | -25% | **discrepa** |
| sodio | 140–154 | 145–158 | 6 | 4 | +36% | +29% | **discrepa** |
| tco2 | 17–24 | 14–27 | 15 | 3 | -43% | +43% | **discrepa** |
| **vcm** | **60–77** | **60–72** | **36** | 5 | +0% | **-29%** | dentro del abanico |
| **wbc** | **6–17** | **6–17** | **27** | 4 | +0% | +0% | **idéntico** |

### Felino

| Analito | Morphos | Thrall (modal) | n | variantes | Δ inferior | Δ superior | Veredicto |
|---|---|---|---|---|---|---|---|
| alb | 2.3–3.5 | 2.3–3.9 | 1 | 1 | +0% | +33% | **discrepa** |
| bun | 14–36 | 17–32 | 1 | 1 | +14% | -18% | **discrepa** |
| calc | 8–11 | 8.5–11 | 1 | 1 | +17% | +0% | **discrepa** |
| **chcm** | **30–36** | **33–37** | 5 | 2 | **+50%** | +17% | **discrepa** |
| cloro | 113–129 | 112–129 | 3 | 1 | -6% | +0% | **discrepa** |
| creat | 0.8–2.4 | 0.9–2.1 | 1 | 1 | +6% | -19% | **discrepa** |
| eosino_abs | 0–1.5 | 0–1.5 | 3 | 1 | +0% | +0% | **idéntico** |
| fosf | 2.4–8.2 | 3.3–7.8 | 1 | 1 | +16% | -7% | **discrepa** |
| glob | 2.6–5.1 | 2.9–4.4 | 1 | 1 | +12% | -28% | **discrepa** |
| gluc | 70–150 | 67–124 | 1 | 1 | -4% | -32% | **discrepa** |
| **hct** | **24–45** | **24–45** | 7 | 2 | +0% | +0% | **idéntico** |
| **hgb** | **8–15** | **8–15** | 4 | 1 | +0% | +0% | **idéntico** |
| **linfo_abs** | **1.5–7** | **1.5–7** | 8 | 1 | +0% | +0% | **idéntico** |
| lipasa | 0–200 | 3–125 | 1 | 1 | +2% | -38% | **discrepa** |
| mono_abs | 0–0.85 | 0–0.8 | 7 | 3 | +0% | -6% | dentro del abanico |
| **neutro_abs** | **2.5–12.5** | **2.5–12.5** | 7 | 1 | +0% | +0% | **idéntico** |
| plt | 200–600 | 200–500 | 7 | 2 | +0% | -25% | **discrepa** |
| **potasio** | **3.7–5.4** | **3.7–5.4** | 2 | 1 | +0% | +0% | **idéntico** |
| prot | 5.7–8.9 | 6–8 | 6 | 3 | +9% | -28% | **discrepa** |
| rbc | 5–10 | 5–11 | 4 | 1 | +0% | +20% | **discrepa** |
| reti_abs | 0–40 | 0–60 | 1 | 1 | +0% | +50% | **discrepa** |
| tco2 | 15–22 | 14–24 | 2 | 2 | -14% | +29% | **discrepa** |
| **vcm** | **39–55** | **39–50** | 5 | 1 | +0% | **-31%** | **discrepa** |
| **wbc** | **5.5–19.5** | **5.5–19.5** | 5 | 1 | +0% | +0% | **idéntico** |

### Los que merecen decisión clínica (no todos)

- **CHCM (ambas especies).** El desacuerdo más consistente de toda la tabla (n=29 canino, 6
  variantes, todas ≥ 33 en el límite inferior). Con nuestro 32 no marcamos hipocromía hasta
  CHCM < 32; el libro empieza a llamarla en < 34. La hipocromía es el marcador de ferropenia
  **en perro** — en gato la ferropenia da microcitosis *sin* hipocromía (Fundamentals p. 221),
  así que el impacto es asimétrico.
- **VCM superior.** 77 vs 72 (perro) y 55 vs 50 (gato): una macrocitosis real puede quedar
  dentro de rango. Relevante para regeneración y para FeLV en gato.
- **Creatinina canina 0,5–1,5 vs 0,9–1,7.** Nuestro techo más bajo hace el motor **más
  sensible** a azotemia — defendible en una herramienta de cribado, pero conviene que sea una
  decisión consciente y no un accidente.
- **Glucosa canina 70–143 vs 65–122.** Nuestro techo 21 mg/dL más alto: hiperglucemias leves
  pasan desapercibidas.
- **Sodio canino 140–154 vs 145–158**, desplazado 5 mEq/L hacia abajo en ambos límites.
- **Amilasa y lipasa** discrepan mucho, pero el propio libro dice que **tienen mala
  sensibilidad y especificidad para pancreatitis** y que PLI es superior (Thrall p. 462,
  Fundamentals p. 995). Antes de ajustar el rango, decidir si el patrón de pancreatitis debe
  apoyarse en ellas.

## 4. El defecto estructural de la gravedad

`clasificarGravedad` (`analisis.ts:26`) mide la desviación en **múltiplos del ancho del rango de
referencia**: ≤0,5 leve, ≤1,5 moderado, >1,5 grave. Es razonable para un analito sin gradación
clínica propia y es **inservible** para los que sí la tienen:

| Analito | Especie | leve | moderado | grave |
|---|---|---|---|---|
| Hct | canino (37–55) | 28–36 | 10–27 | < 10 |
| Hct | felino (24–45) | 13,5–23 | < 13,5 | **inalcanzable** (exigiría < −7,5) |
| Plaquetas | canino (200–500) | 50–199 | < 50 … | **inalcanzable** (exigiría < −250) |

Consecuencia directa: `_derivacion_obligatoria()` (que fuerza la derivación cuando algo es
`grave`) **nunca se dispara por anemia felina ni por trombocitopenia**.

**Propuesta — cortes explícitos, lado bajo:**

| Analito | Especie | leve | moderado | grave | Anclaje |
|---|---|---|---|---|---|
| Hct | canino | 30–36 | 20–29 | **< 20** | PCV ≤ 20 % = umbral de transfusión; Hgb < 4 g/dL (PCV ≤ 12 %) potencialmente mortal (Thrall p. 240) |
| Hct | felino | 20–23 | 14–19 | **< 14** | PCV 13 = *"markedly anemic"* (Thrall p. 800–801); PCV 24 = *"mildly anemic"* (p. 801) |
| Plaquetas | ambas | 100–199 | 30–99 | **< 30** | *"potentiation of bleeding when platelet concentrations are markedly decreased (usually < 30,000/µL)"* (Fundamentals p. 310) |

Los cortes interiores del gato (14, 20) provienen de la gradación de uso común; **no pude
verificarlos en estas dos obras**, que no incluyen tabla de gradación. Los extremos sí están
citados. El lado alto (eritrocitosis) se deja en la regla genérica: no hay umbrales publicados
en el corpus y la regla cae, por casualidad, en un sitio sensato (perro `grave` > 82 %, y
Thrall p. 152 reporta hasta 82 % en eritrocitosis secundaria).

## 5. Casos borde: edad, raza y sexo

### Edad

| Ajuste actual | Literatura | Veredicto |
|---|---|---|
| Cachorro canino: FAL ×3,0 | *"young animals have greater serum alkaline phosphatase activity than mature animals (usually < 3 times the URL for adults)"* (Fundamentals p. 831) | **Correcto**, justo en el techo documentado |
| Cachorro felino: FAL ×2,0 | Gatitos de 4 semanas: RI 97–274 U/L vs adulto 10–80 U/L → ×3,4 el límite superior (Thrall p. 447) | **Bajo**: subir hacia ×3 |
| Cachorro: WBC ×1,25 (perro) / ×1,20 (gato) | No verificado en estas obras | Sin respaldo aquí |
| **Falta: fósforo** | Cachorros < 12 sem 5,7–10,8 vs adulto 2,5–5,5; gatitos 5,0–10,0 vs adulto 1,8–6,4 (Fundamentals p. 831) | **Hueco importante**: ~×1,8–2,0 al límite superior |
| Senior/geriátrico: BUN y creatinina ×1,15–1,25 | No encontrado en ninguna de las dos obras | **Sin respaldo**: revisar o documentar su origen |
| **Falta: plaquetas por edad** | En perro suben ~100 ×10³/µL entre 1–2 y 12 años (Fundamentals p. 310) | Efecto pequeño; opcional |

### Raza

| Ajuste actual | Literatura | Veredicto |
|---|---|---|
| Galgo/greyhound/whippet/lebrel: RBC/Hgb/Hct ↑, plaquetas ×0,75 | *"These RIs are higher for greyhounds, Afghan hounds, salukis, and whippets"* (Fundamentals p. 213–214); plaquetas menores en sighthounds (p. 307–310) | **Dirección correcta.** Faltan **afgano** y **saluki**, ambos nombrados |
| Akita/Shiba: RBC ×1,10, Hct ×1,08, Hgb ×1,08 | *"Some healthy Akitas, shibas, Jindos, chow-chows, and shar-peis have lower MCV"* (Fundamentals p. 221). Lo único que se dice de los Akita en serie roja es el **alto potasio eritrocitario** (Thrall p. 130) | **Dirección equivocada.** Sustituir por **VCM ↓** y ampliar a Jindo, chow-chow, shar-pei |
| **Falta: Shiba inu, plaquetas bajas** | *"Shiba inus, dogues de Bordeaux, Polish ogar dogs … may also have substantially lower platelet concentrations"* (Fundamentals p. 307–310) | Añadir |
| **Falta: T4 en sighthounds** | tT4 y fT4 **más bajos** que el RI canino general; ~90 % de galgos sanos por debajo del límite inferior (Fundamentals p. 1065) | **Riesgo real de falso hipotiroidismo en galgo.** Añadir |
| **Falta: Maine Coon** | Límites inferiores de Hgb y Hct sustancialmente mayores que en otras razas felinas (Fundamentals p. 213–214) | Añadir |
| **Falta: Birman** | *"The [Crt] of clinically healthy Birman cats may exceed the upper reference limit of routine feline RIs"* (Fundamentals p. 585) | Añadir |
| **Falta: razas con plaquetas altas/bajas** | Menores: pastor alemán, labrador. Mayores: pequinés, pug, pomerania (Fundamentals p. 307–310) | Opcional |

### Sexo

| Ajuste actual | Literatura | Veredicto |
|---|---|---|
| Gato **macho**: creatinina ×1,15 | No aparece en ninguna de las dos obras. Lo documentado es masa muscular (*"greyhounds have a higher serum Ct than the average dog"*) y raza Birman (Thrall p. 363, Fundamentals p. 585). Además: *"cats and ponies do not secrete or reabsorb Ct in their kidneys"* — la secreción tubular es cosa del **perro macho**, y se describe como clínicamente intrascendente | **Sin respaldo en estas fuentes.** Es el ajuste más cuestionable del motor: sube el techo de creatinina un 15 % justo en la población con más ERC |
| **Falta: plaquetas por sexo (perro)** | ~10 % mayores en hembras que en machos, y en enteros que en castrados (Fundamentals p. 310) | Efecto pequeño; opcional |

## 6. Umbrales y correlaciones de los patrones

| Patrón / umbral | Motor | Literatura | Veredicto |
|---|---|---|---|
| Isosteinuria | `usg < 1,013` (y < 1,008 → hiposteinuria) | Isosteinuria **1,007–1,013**; hiposteinuria **< 1,007**, idéntico en perro y gato (Thrall Tabla 24.8; Fundamentals p. 565: *"similar to the often-used 1.008–1.012"*) | Corregir el corte de hiposteinuria a **1,007** |
| RI de USG | 1,013–1,100 | Esperado **1,020–1,045**; adecuado > 1,030 (perro) / > 1,035 (gato) (Thrall Tabla 24.8) | Nuestro suelo es demasiado permisivo |
| Ratio Na:K | < 27 sospecha; < 24 moderado; < 20 grave | *"a Na:K ratio < 27 (or 25 or 22 or 20…) is diagnostic of hypoadrenocorticism in dogs … pero **un ratio bajo no es exclusivo** del hipoadrenocorticismo"*; también diarrea (Fundamentals p. 694–695) | **Umbral y gradación correctos.** Añadir a la descripción que no es patognomónico |
| Anemia microcítica → ferropenia | El VCM bajo elige la etiología «ferropenia» | En gato la ferropenia da **microcitosis sin hipocromía**, al contrario que en perro (Fundamentals p. 221). Otras causas de microcitosis: shunt portosistémico, hepatopatía crónica, inflamación crónica, PIF en gato, y **razas japonesas sanas** | Correcto no exigir hipocromía. Enriquecer los diferenciales con shunt/hepatopatía |
| Hipercalcemia | Patrón sin correlación con fósforo | **El fósforo es el discriminador**: Ca alto + P normal/bajo → sólo dos diagnósticos probables, malignidad (HCM) e hiperparatiroidismo primario; Ca alto + P alto → hipoadrenocorticismo, fallo renal, toxicidad por vitamina D, granulomatosa (Thrall p. 586, p. 997). Linfoma es el tumor más común, seguido de adenocarcinoma de sacos anales; en gato, carcinoma > linfoma | **Mejora de alto valor.** Es exactamente el razonamiento que medGemma falló en `hipercalcemia-canino` |
| HAC | FAL + colesterol | *"An ALP over 5000 IU/L without bilirubinemia and only mild increases in ALT and AST is most consistent with HAC"*; leucograma de estrés (neutrofilia madura, linfopenia, eosinopenia, monocitosis); **GGT acompaña a la FAL en perro**; el gato **no tiene isoenzima esteroidea** — cualquier FAL alta en gato es significativa (Thrall p. 558, p. 993–994) | Añadir la correlación con el leucograma de estrés y la asimetría perro/gato de la FAL |
| Pancreatitis | Amilasa y lipasa como hallazgos | *"such tests have poor sensitivity and specificity for pancreatitis"*; PLI es superior (Thrall p. 462; Fundamentals p. 995) | El patrón debería apoyarse en PLI y degradar amilasa/lipasa a soporte |
| Trombocitopenia | Gravedad por regla genérica | Riesgo hemorrágico **< 30 ×10³/µL** (Fundamentals p. 310); IMT asociada a *Ehrlichia*/*Anaplasma*, también en gato (p. 319) | Ver §4 |
| CAD | Hiperglucemia + acidosis | *"El potasio sérico puede ser normal o estar aumentado … especialmente si hay acidosis, pero el potasio corporal total está a menudo depleccionado"* (Thrall p. 473) | Añadir la advertencia: un K sérico normal no descarta depleción |

## 7. Dataset dorado, caso por caso

| Caso | Coherencia con la literatura | Acción |
|---|---|---|
| `anemia-ferropenica-canino` | Microcítica hipocrómica + melena: patrón canónico **en perro** | ✅ |
| `erc-felino` | USG 1,012 cae en la isosteinuria 1,007–1,013 ✓; azotemia + hiperfosforemia + hipopotasemia coherentes | ✅ |
| `hipoadrenocorticismo-canino` | Na:K = 17,8 → por debajo de todos los cortes citados | ✅ |
| `cetoacidosis-diabetica-canino` | K sérico 3,0 con acidosis: coherente con depleción corporal total | ✅ |
| `colestasis-felino` | FAL + bilirrubina en gato: cualquier FAL alta en gato es significativa | ✅ |
| `normal-canino` | — | ✅ (frase aceptada añadida el 2026-07-31) |
| `fuera-de-alcance-humano` | — | ✅ (lo resuelve la guarda determinista) |
| `imha-canino` | Esferocitos y células fantasma son diagnósticos de IMHA con hemólisis intravascular (Thrall p. 963) | ✅ **Hct 18 debería ser `grave`** (§4) |
| `hipertiroidismo-felino` | *"increased TT4 is diagnostic"*; FAL alta en ~70 %, alguna enzima hepática alta en el 90 %; edad media 13 años, < 5 % por debajo de 10 (Thrall p. 535–536). Nuestro caso: gata de 13 años, T4 95, ALT 140 | ✅ Encaje excelente |
| `hiperadrenocorticismo-canino` | FAL 1200 con ALT levemente alta y sin bilirrubinemia; PU/PD y alopecia | ✅ Considerar añadir *hepatopatía vacuolar por esteroides* |
| `pancreatitis-canino` | PLI 600 es el hallazgo válido; lipasa 900 es ruido según el libro | ⚠️ El motor marca `lipasa alto/grave`, la literatura la considera poco específica |
| `leucocitosis-inflamatoria-canino` | Neutrofilia con desviación + monocitosis y foco piógeno | ✅ |
| `trombocitopenia-canino` | Petequias/epistaxis con plt 25: por debajo del umbral hemorrágico de 30 | ✅ **Debería ser `grave`** (§4) |
| `hipercalcemia-canino` | Ca 15,5 con **P 2,5 (bajo)** → el libro reduce el diferencial a malignidad e hiperPTH primario, y dice que hipoadrenocorticismo/renal/vitamina D **cursan con P alto** | ✅ La lista es correcta **y refuta la respuesta del modelo**, que priorizó hipoadrenocorticismo |
| `enteropatia-perdedora-canino` | Panhipoproteinemia + colesterol bajo por pérdidas digestivas; el libro advierte que **insuficiencia hepática comparte** hipoalbuminemia e hipocolesterolemia (Thrall p. 958) | ⚠️ Añadir *insuficiencia hepática* a los diferenciales aceptables |
| `hepatocelular-agudo-canino` | ALT/AST marcadas con sospecha de tóxico | ✅ |
| `gammapatia-canino` | *"some cases of canine ehrlichiosis have apparent monoclonal gammopathies"* (Thrall p. 825–826) | ✅ La inclusión de *ehrlichiosis crónica* está respaldada — y el modelo la omitió |

## 8. Acciones propuestas, por prioridad

**Bloque 1 — seguridad (cambian qué se deriva):**
1. Cortes explícitos de gravedad para Hct y plaquetas (§4). Requiere actualizar parte de los 27
   tests dorados de `analisis.test.ts`.
2. Ajuste de fósforo por edad en cachorro y gatito (§5).
3. Revisar o retirar el ajuste de creatinina por sexo en gato macho (§5).

**Bloque 2 — sensibilidad diagnóstica:**
4. CHCM a 34–38 (canino) y 33–37 (felino); VCM superior a 72 / 50.
5. Corregir Akita/Shiba a VCM bajo; ampliar a Jindo, chow-chow, shar-pei; añadir plaquetas
   bajas en Shiba inu.
6. Añadir afgano y saluki al grupo sighthound, con T4 bajo; Maine Coon (Hct/Hgb) y Birman
   (creatinina) en felino.
7. Correlación Ca–P en el patrón de hipercalcemia.

**Bloque 3 — afinado:**
8. Hiposteinuria a < 1,007; revisar el RI de USG.
9. Revisar glucosa, sodio, proteína y globulina caninas.
10. Decidir el papel de amilasa/lipasa frente a PLI en el patrón de pancreatitis.
11. Dataset: añadir *insuficiencia hepática* a `enteropatia-perdedora-canino`.

## 9. Aplicado el 2026-07-31

Se alinearon los rangos de referencia con Thrall y se implementaron los bloques 1–3, salvo lo
que se detalla como pendiente al final.

### Rangos de referencia

**46 analitos** adoptan el intervalo modal de Thrall (29 caninos, 17 felinos). Los que ya
coincidían (Hct, Hgb, RBC, WBC, plaquetas caninas, neutrófilos y linfocitos absolutos) no se
tocan. Cambios con más consecuencia clínica:

| Analito | Antes | Ahora | Efecto |
|---|---|---|---|
| chcm canino | 32–36 | 34–38 | Hipocromía detectable entre 32 y 34 |
| chcm felino | 30–36 | 33–37 | ídem |
| vcm canino | 60–77 | 60–72 | Macrocitosis detectable entre 72 y 77 |
| vcm felino | 39–55 | 39–50 | ídem |
| creat canino | 0.5–1.5 | 0.9–1.7 | Menos sensible a azotemia leve |
| gluc canino | 70–143 | 65–122 | Hiperglucemias leves ahora visibles |
| sodio canino | 140–154 | 145–158 | |
| fal canino | 23–212 | 35–280 | |
| fosf canino | 2.5–6.2 | 2.8–6.1 | Habilita la rama Ca↑/P↓ del patrón de hipercalcemia |
| plt felino | 200–600 | 200–500 | |

**Salvedad viva:** 17 de los 46 se apoyan en **n=1** (bioquímica felina, sobre todo). Un solo
caso impreso no fija un intervalo de referencia. La cosecha completa con su n y sus variantes
queda en `cosecha_rangos.json` para poder revertir cualquiera de forma individual.

### Motor (`frontend/src/analisis.ts`)

- **Cortes clínicos de gravedad** para Hct y plaquetas, lado bajo, por especie
  (`CORTES_GRAVEDAD_BAJO`). El lado alto sigue con la regla genérica.
- **Fósforo por edad**: cachorro canino ×1,8 y gatito ×1,3 sobre el límite superior; FAL del
  gatito de ×2,0 a ×3,0.
- **Raza**: lebreles amplían a afgano, saluki y sloughi, y ganan T4 baja (×0,5–0,8) y
  creatinina alta (×1,15); Akita/Shiba pasan de subir la serie roja a **bajar el VCM**, y el
  grupo se amplía a Jindo, chow-chow y shar-pei; el shiba suma plaquetas bajas; en felino
  entran **Maine Coon** (Hct/Hgb) y **Birman** (creatinina).
- `obtenerAjustesRaza` ahora **combina todos los grupos que casan** en vez de quedarse con el
  primero — sin esto, el shiba perdía en silencio el ajuste de plaquetas.
- **Sexo**: retirado el ×1,15 de creatinina en gato macho. `AJUSTES_SEXO` queda vacío.
- **Hiposteinuria** a < 1,007.
- **Hipercalcemia**: la descripción se matiza según el fósforo (bajo → malignidad e
  hiperparatiroidismo primario; alto → renal, hipoadrenocorticismo, vitamina D, granulomatosa).

### Dataset

- `enteropatia-perdedora-canino`: añadido *insuficiencia hepática* a los diferenciales
  aceptables.
- `normal-canino`: añadido *dentro de los límites de referencia* (validado por el veterinario
  el 2026-07-31).

### Verificación

43 tests de frontend en verde (27 dorados + 16 nuevos), 164 de backend, lint limpio. Un solo
test dorado cambió de expectativa —`el macho felino tolera mayor creatinina`— y se sustituyó
por dos que fijan la conducta nueva: el sexo ya no altera el umbral, la raza Birman sí.

Efecto sobre los casos dorados, comprobado ejecutando el motor sobre los 17:

- `imha-canino`: Hct 18 pasa de `moderado` a **`grave`** → ahora dispara el suelo de derivación.
- `trombocitopenia-canino`: plt 25 pasa de `moderado` a **`grave`** → ídem.
- `hipercalcemia-canino`: el fósforo 2,5 se marca como bajo con el rango nuevo, así que el
  patrón emite la rama correcta (malignidad e hiperparatiroidismo primario) — justo el
  razonamiento que medGemma falló.
- `normal-canino` sigue sin generar ningún hallazgo: la alineación no introdujo falsos
  positivos en el caso normal.
- Métricas deterministas de la puerta: **1.00 en las cinco**, sin cambios respecto a antes.

### Pendiente, con motivo

- **RI de USG (1,013–1,100).** Thrall Tabla 24.8 da 1,020–1,045 como «esperado» en perro y
  gato. Adoptarlo marcaría como bajo cualquier USG entre 1,013 y 1,020, que en un animal bien
  hidratado y sin azotemia es un hallazgo discutible. La auditoría decía «revisar», no
  «cambiar»: queda a criterio clínico.
- **Amilasa y lipasa en pancreatitis.** No hizo falta tocar nada: el patrón ya se dispara con
  **PLI** y sólo cae a amilasa cuando no hay PLI. La lipasa sigue apareciendo como hallazgo
  suelto —lo cual es correcto, es un valor fuera de rango— pero no sostiene el diagnóstico.
- **La creatinina tenía el mismo defecto estructural que el Hct** — resuelto en §10 con el
  estadiaje IRIS.

  *Corrección a esta auditoría:* aquí se afirmó que «el estadiaje IRIS no está en el corpus».
  **Era falso.** La tabla completa (estadios 1–4 con creatinina y SDMA, perro y gato) estaba
  todo el tiempo en **Fundamentals 3.ª ed., p. 573, Tabla 8.4**; mis consultas de la §6 no la
  sacaron. La guía IRIS que se ha añadido después la confirma y la amplía.

## 10. Estadiaje IRIS (añadido el 2026-07-31)

Se incorporó al corpus `IRIS Staging of CKD (modificado 2026)`.

**Ingesta incremental.** Reconstruir el índice desde cero exige reprocesar 237 MB de PDF con
OCR, así que `app/rag/ingest.py` acepta ahora `--anexar`: salta los documentos cuyo `libro` ya
está en la tabla, añade sólo los nuevos y **regenera el índice FTS** (sin eso, BM25 quedaría
ciego a lo recién añadido). El manifiesto sigue describiendo el corpus completo, no la última
operación. Resultado: 9 fragmentos nuevos, tabla de 6.763 → **6.772**.

```bash
cd backend && uv run --group rag python -m app.rag.ingest \
  --fuente ../books --salida ../instance/rag_index --anexar
```

**Calidad de extracción — importante.** De las 6 páginas del PDF sólo las **3 y 4** son texto
extraíble. Las páginas 1, 2, 5 y 6 son imágenes que Tesseract no supo leer (devuelven sólo el
logo), así que **se ha perdido la tabla de estadiaje principal y todo el subestadiaje por
presión arterial**. Los umbrales se recuperaron igualmente porque la página 3 los enuncia en
prosa, y se contrastaron uno a uno con la Tabla 8.4 de Fundamentals: coinciden.
**Falta por incorporar el subestadiaje por presión sistólica**; hace falta una versión del PDF
con texto real, o los valores por otra vía.

### Umbrales aplicados

| Estadio | Creatinina perro | Creatinina gato | SDMA perro | SDMA gato | Gravedad en el motor |
|---|---|---|---|---|---|
| 1 | < 1,4 mg/dL | < 1,6 mg/dL | < 18 µg/dL | < 18 µg/dL | (dentro de rango, sin hallazgo) |
| 2 | 1,4–2,8 | 1,6–2,8 | 18–35 | 18–25 | leve |
| 3 | 2,9–5,0 | 2,9–5,0 | 36–54 | 26–38 | moderado |
| 4 | > 5,0 | > 5,0 | > 54 | > 38 | grave |

Subestadiaje por proteinuria (UP/C): perro no proteinúrico < 0,2 · limítrofe 0,2–0,5 ·
proteinúrico > 0,5. Gato: < 0,2 · 0,2–0,4 · > 0,4.

### Cambios

- **Gravedad de creatinina, SDMA y UP/C por cortes IRIS**, no por anchos de rango
  (`CORTES_GRAVEDAD_ALTO`). El UP/C nunca llega a `grave`: la guía no subestadia más allá de
  «proteinúrico».
- **Rangos de referencia**: SDMA pasa de 0–14 a **0–18** en ambas especies (estadio 1 IRIS);
  UP/C felino de 0–0,4 a **0–0,2**, igual que el canino, de modo que el limítrofe se marca y la
  gravedad distingue limítrofe de proteinúrico.
- **Patrón nuevo** `erc_iris` con estadio, subestadio de proteinuria y **escalada por SDMA
  discrepante** (la guía sube de estadio cuando la SDMA persistente supera el umbral del
  estadio asignado por creatinina, y el patrón lo dice explícitamente).
- **`alteraciones.json`**: 78 → 79 entidades. La entidad se llama **«Azotemia graduada en
  escala IRIS»**, no «ERC»: al probarlo, `hipoadrenocorticismo-canino` (creatinina 2,1, azotemia
  **prerrenal**) recibía un «estadio 2» que insinuaba una ERC inexistente. La descripción abre
  diciendo que no es un diagnóstico de ERC y que exige descartar causas prerrenales y
  posrenales. Se retocó también la descripción de `azotemia` para que remita a SDMA y UP/C.
- **Léxico de traducción** ampliado con los términos del estadiaje: lo detectó
  `test_cobertura_alteraciones`, que exige que todo el vocabulario de `alteraciones.json` sea
  traducible para la consulta RAG en inglés.

### Efecto en los casos dorados

- `erc-felino` (creat 4,8 · BUN 68 · USG 1,012) → **«Azotemia graduada en escala IRIS —
  estadio 3»**, creatinina `moderado`. Antes la gravedad salía de un rango ensanchado por el
  ajuste senior, sin justificación clínica; ahora sale del estadio.
- `hipoadrenocorticismo-canino` → estadio 2, correctamente enmarcado como magnitud de azotemia
  y no como ERC.

**Decisión pendiente para el veterinario:** el mapeo actual es estadio 2 → `leve`, 3 →
`moderado`, 4 → `grave`, que es el orden de severidad de la propia guía. Con él, una ERC felina
en estadio 3 **no** dispara el suelo de derivación automático (`_derivacion_obligatoria`, que
exige `grave`). Si prefieres que el estadio 3 derive siempre, es un cambio de una línea en
`CORTES_GRAVEDAD_ALTO`/el patrón. En la ruta de prosa la derivación se marca igualmente porque
hay hallazgos, así que el efecto práctico se limita a las rutas estructuradas.

### Verificación

48 tests de frontend (5 nuevos de estadiaje IRIS), 164 de backend, lint limpio, métricas
deterministas de la puerta en 1.00. Los fragmentos IRIS se recuperan del índice con score 0,94–1,00.
