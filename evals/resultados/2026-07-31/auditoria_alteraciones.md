# Auditoría de `alteraciones.json` frente al corpus — 2026-07-31

Las 79 entidades de `data/alteraciones.json`, contrastadas una a una con los tres documentos
indexados: **Thrall** (*Veterinary Hematology, Clinical Chemistry, and Cytology*, 3.ª ed.),
**Fundamentals** (*Fundamentals of Veterinary Clinical Pathology*, 3.ª ed.) e **IRIS Staging of
CKD** (modificado 2026).

**Por qué importa más de lo que parece:** estas descripciones no son sólo texto de tarjeta. Son
el contexto etiológico que se inyecta en el prompt de la IA a través de los patrones detectados.
Un error aquí no se queda en la interfaz: se convierte en fundamento del que el modelo razona.

## Resumen

| Veredicto | N | Qué significa |
|---|---|---|
| **Confirmado** | 47 | El corpus sostiene lo que afirma la entidad |
| **Corregido** | 6 | El corpus contradecía o desordenaba lo afirmado → **aplicado** |
| **Enriquecido** | 9 | Correcto pero le faltaba algo que el corpus aporta → **aplicado** |
| **Sin cobertura** | 17 | Afirmaciones que estas obras no tratan; no verificables aquí |

**Ninguna entidad resultó clínicamente falsa en su tesis principal.** Lo corregido son matices,
inversiones de énfasis, unidades y un umbral. Es un buen resultado para un fichero de 79
entidades que nunca se había contrastado.

## 1. Correcciones aplicadas (el corpus decía otra cosa)

| Entidad | Decía | Dice el corpus | Fuente |
|---|---|---|---|
| `alt_aislada` | «la ALT también se encuentra en músculo esquelético, **especialmente en felinos**» | Al revés: en el **perro** la ALT muscular es ~5% (esquelético) y ~**25%** (cardíaco) de la hepática; en el **gato** ambas son ~5% | Thrall p. 516 |
| `isosthenuria` | Nombre: «USG **1.008**–1.013» | Isosteinuria = **1.007**–1.013 en perro y gato | Thrall Tabla 24.8; Fundamentals p. 565 |
| `hiposthenuria` | Nombre: «USG < **1.008**» | Hiposteinuria = **< 1.007** | ídem |
| `hipocalcemia` | Listaba la hipoalbuminemia en 4.º lugar y recomendaba «calcio ionizado **corregido**» | La hipoalbuminemia es «the most common cause **by a large margin** in all species»; y se recomienda medir **iCa directo**, no fórmulas corregidas por proteínas | Thrall p. 589 y 580–581 |
| `hematuria_uri`, `piuria` | «> 5/**μL**» | La convención del sedimento manual es **por campo de gran aumento (/hpf)**; los analizadores informan /μL. Se explicitan ambas | Thrall p. 391 |

Los dos nombres de entidad estaban además **desincronizados con el motor**, que ya usa 1,007
desde la auditoría anterior: la tarjeta decía 1,008 y el código calculaba con 1,007.

## 2. Enriquecimientos aplicados

| Entidad | Qué se añadió | Fuente |
|---|---|---|
| `hipercalcemia` | **El fósforo discrimina**: P normal/bajo → sólo malignidad e hiperPTH primario; P alto → renal, Addison, vitamina D, granulomatosa. Estaba en el patrón desde la auditoría anterior, pero no en la entidad, así que no llegaba al prompt | Thrall p. 586, 997 |
| `eosinofilia` | **Hipoadrenocorticismo** como causa (está en la tabla de causas del libro y faltaba) | Fundamentals p. 128–129 |
| `trombocitosis` | **Pseudotrombocitosis**: eritrocitos microcíticos, células fantasma y gotas lipídicas contados como plaquetas | Fundamentals p. 325 |
| `leucocitosis_linfocitica` | Umbrales numéricos: > 12.000/μL en perro > 1 año, > 20.000/μL en gato | Thrall p. 173 |
| `deficit_vwf` | **No hay asociación predecible entre hipotiroidismo y vWD** — el vWF:Ag de perros hipotiroideos estaba dentro del RI y *bajó* tras levotiroxina. Desmonta un cribado habitual | Fundamentals p. 350–351 |
| `ratio_nak` | **Pseudo-Addison por *Trichuris vulpis***, sin hipoplasia adrenocortical ni hipoaldosteronismo | Fundamentals p. 695 |
| `hiperlactatemia` | En el paciente oncológico la hiperlactatemia **suele deberse a otros mecanismos**, no al efecto Warburg | Fundamentals p. 730–731 |
| `dano_miocardico` | Cautela analítica: no todos los inmunoensayos de troponina están validados en animales y **los valores no son comparables entre ensayos** | Thrall p. 516 |
| `creatinina_aislada` | Recomendar **SDMA** —más sensible en ERC temprana y menos afectado por pérdida de masa magra, que es justo el escenario que la entidad describe— y corregir «estadio I–II» por «estadio IRIS ≥ 2 si se confirma ERC» | IRIS 2026 |

## 3. Sin cobertura en el corpus (17)

No están mal: **están fuera del alcance de estas tres obras**. Son en su mayoría cifras
numéricas y recomendaciones terapéuticas, que es justo el tipo de afirmación que conviene poder
citar. No se ha tocado ninguna.

- **Monitorización de fármacos** — `fenobarbital_toxico`, `fenobarbital_subterapeutico`,
  `ciclosporina_toxica`, `ciclosporina_subterapeutica`: rangos terapéuticos y pautas (vitamina K,
  bromuro potásico, ketoconazol). Ninguno de los tres documentos es un texto de terapéutica.
- **Biomarcadores cardíacos** — `cardiopatia_bnp`: los cortes (> 900 y > 1500 pmol/L en perro,
  > 100 en gato) y el estadiaje ACVIM no aparecen. El corpus sí respalda el uso del NT-proBNP
  para distinguir causa cardíaca de no cardíaca en disnea.
- **Cifras de rendimiento diagnóstico** — `tsh_elevado` (sens. 60–85%, esp. > 95%),
  `hiperadrenocorticismo` (85% PDH / 15% ADH), `hipoadrenocorticismo_cortisol` (corte felino
  < 3,5 μg/dL), `antitrombina_baja` (< 70% de riesgo).
- **Umbrales de actuación** — `neutropenia` (< 1.000/μL y profilaxis antibiótica),
  `hiperpotasemia` (ECG si K > 6,5), `hiperlactatemia` (2,5 / 5 / 10 mmol/L),
  `inflamacion_aguda` (PCR > 10 y > 100 mg/L), `hipoxemia` (umbrales de oxigenoterapia).
- **Reproducción y otros** — `progesterona_elevada` (score de recuperación 0,37: el corpus no
  cubre endocrinología reproductiva), `ac_urico_elevado`, `hipermagnesemia`, `ldh_elevada`
  (las consultas devuelven AST/ALT, no LDH).

**Un matiz importante sobre `hipoadrenocorticismo_cortisol`:** el corpus aporta un dato que
nuestra entidad no tiene y que conviene no confundir — un **cortisol basal** < 2 μg/dL tiene
100% de sensibilidad pero sólo **78% de especificidad** (≈22% de falsos positivos)
(Thrall p. 553). Nuestra entidad habla del **post-ACTH** < 2 μg/dL, que es criterio diagnóstico,
no de cribado. No es un error, pero la distinción basal/post-ACTH merece explicitarse. **Lo dejo
a tu criterio** porque toca el umbral diagnóstico.

## 4. Confirmados sin cambios (47)

Serie roja y blanca: `eritrocitosis`, `leucocitosis_neutrofilica`, `leucopenia`, `neutropenia`,
`linfopenia`, `ferropenia_hierro`, `anemia`. Hígado y vía biliar: `dano_hepatocelular`,
`hiperbilirrubinemia`, `patron_colestasico`, `bun_disminuido`. Renal: `azotemia`,
`hiperuremia_bun`, `isosthenuria` (contenido), `proteinuria_upc`, `erc_iris`. Electrolitos y
ácido-base: `hiperproteinemia`, `hipoalbuminemia`, `hipernatremia`, `hiponatremia`,
`hiperpotasemia`, `hipopotasemia`, `hiperfosforemia`, `hipomagnesemia`, `acidosis_metabolica`,
`alcalosis_metabolica`, `acidosis_respiratoria`, `anion_gap_elevado`, `ca_ionizado_bajo`,
`hipoxemia`. Endocrino: `hipotiroidismo`, `t4_libre_baja`, `hiperglucemia`, `hipoglucemia`,
`deficit_insulina`, `hipertiroidismo`. Hemostasia: `cid`, `coagulopatia_extrinseca`,
`coagulopatia_mixta`, `hiperfibrinogenemia`, `hipofibrinogenemia`. Inflamación:
`inflamacion_aguda` (el corpus confirma que en perro las mayores son SAA y PCR, y en gato SAA y
αAG). Otros: `hipoproteinemia_hipoalbuminemia`, `pancreatitis`, `trombocitopenia`,
`hematuria_uri` (diferenciación hematuria/hemoglobinuria/mioglobinuria, exacta según la Tabla
3.13), `piuria`.

## 5. Verificación

48 tests de frontend, 164 de backend, lint limpio. Un test propio falló al aplicar los cambios y
señalaba algo real: al meter la regla del fósforo en la entidad, el patrón repetía parte del
texto. Se ajustaron las aserciones para distinguir la **regla general** (entidad, siempre en el
prompt) de la **conclusión aplicada** a ese paciente (patrón).

## 6. Método y límites

Una consulta por entidad construida con su nombre y el inicio de su descripción, recuperando los
2 mejores fragmentos. Límites que conviene tener presentes:

1. **«Sin cobertura» no es «incorrecto».** Sólo significa que estas tres obras no lo tratan.
2. **La recuperación puede fallar aunque el dato esté.** Ya pasó en la auditoría anterior con la
   tabla IRIS, que estaba en Fundamentals p. 573 y mis consultas no sacaron. Un veredicto de «sin
   cobertura» es una hipótesis razonable, no una certeza.
3. **No se auditaron las descripciones por especie** de las entidades que las tienen
   (`pancreatitis` y similares) más allá del texto canino.
