"""Pruebas de la capa determinista de `run_evals.py` (puntuación, agregación y umbrales).

Es la puerta de CI: si estas funciones se equivocan, un modelo peor puede aprobar un
despliegue o uno correcto quedar bloqueado. Todo lo que se prueba aquí es puro — no toca
modelo, ni juez, ni índice.
"""

from __future__ import annotations

import run_evals
from run_evals import (
    UMBRALES,
    _claves_mencionadas,
    _texto_plano,
    agregar,
    agregar_juez,
    cargar_casos,
    evaluar_umbrales,
    generar_simulado,
    puntuar_caso,
)


def caso(**cambios) -> dict:
    base = {
        "id": "caso-x",
        "split": "dev",
        "validado": True,
        "descripcion": "Azotemia en gato",
        "paciente": {"especie": "felino"},
        "valores": {"creat": 4.0},
        "esperado": {
            "hallazgos_clave": ["creat", "bun"],
            "diferenciales_aceptables": ["enfermedad renal crónica"],
            "requiere_derivacion": True,
            "fuera_de_alcance": False,
        },
    }
    base.update(cambios)
    return base


def interp(**cambios) -> dict:
    base = {
        "interpretacion": "Hay azotemia con creatinina y BUN altos; ganó relevancia clínica.",
        "hallazgos_clave": [{"analito": "Creatinina"}, {"analito": "BUN/Urea"}],
        "diferenciales": [{"nombre": "Enfermedad renal crónica"}],
        "requiere_derivacion": True,
    }
    base.update(cambios)
    return base


# --- recall de diferenciales ---

def test_recall_acierta_por_el_campo_estructurado():
    assert puntuar_caso(caso(), interp())["recall_diferenciales"] == 1.0


def test_recall_acierta_por_la_prosa_cuando_no_hay_estructura():
    # La ruta HF Space devuelve texto libre: si sólo se mirara `diferenciales`, la métrica
    # sería inalcanzable por construcción para el backend de producción.
    salida = interp(
        diferenciales=[],
        interpretacion="Compatible con enfermedad renal crónica en fase avanzada.",
    )
    assert puntuar_caso(caso(), salida)["recall_diferenciales"] == 1.0


def test_recall_es_cero_si_no_menciona_ningun_diferencial_aceptable():
    salida = interp(diferenciales=[{"nombre": "Gastritis"}], interpretacion="Cuadro gástrico.")
    assert puntuar_caso(caso(), salida)["recall_diferenciales"] == 0.0


def test_recall_acepta_un_sinonimo_del_diagnostico():
    """Medido con qwen2.5:14b: escribió «Déficit de hierro» donde el dataset acepta
    «ferropenia» y la métrica le dio 0.00 mientras el juez le daba 0.95 al mismo texto."""
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["ferropenia", "anemia ferropénica"]
    salida = interp(diferenciales=[{"nombre": "Déficit de hierro"}])
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 1.0


def test_recall_ignora_las_tildes_en_ambos_lados():
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["anemia ferropénica"]
    salida = interp(diferenciales=[{"nombre": "Anemia ferropenica"}])
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 1.0


def test_recall_no_lo_regala_una_subcadena():
    # «cad» (cetoacidosis diabética) casaba dentro de «cadera», «cadena» o «cadáver».
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["cad"]
    salida = interp(diferenciales=[], interpretacion="Dolor a la palpación de la cadera.")
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 0.0


def test_recall_tolera_la_flexion_del_castellano():
    # Medido en normal-canino: «los resultados son normales» debe casar con «normal».
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["normal"]
    salida = interp(diferenciales=[], interpretacion="Los resultados son normales.")
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 1.0


def test_la_flexion_no_se_aplica_a_las_siglas_cortas():
    # «cad» + «a» casaría con «cada», que aparece en cualquier texto clínico.
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["cad"]
    salida = interp(diferenciales=[], interpretacion="Se revisa cada valor del panel.")
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 0.0


def test_recall_sigue_aceptando_la_sigla_cuando_se_usa_de_verdad():
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["cad"]
    salida = interp(diferenciales=[{"nombre": "CAD (cetoacidosis diabética)"}])
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 1.0


def test_el_patron_de_laboratorio_no_cuenta_como_el_diagnostico():
    """Repetir el hallazgo no es nombrar la causa: si «anemia microcítica hipocrómica» contara
    como ferropenia, la métrica premiaría describir en vez de diagnosticar."""
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = ["ferropenia", "anemia ferropénica"]
    salida = interp(
        diferenciales=[{"nombre": "Anemia microcítica hipocrómica"}],
        interpretacion="Se observa una anemia microcítica hipocrómica.",
    )
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 0.0


def test_los_sinonimos_declarados_son_de_diagnostico_y_no_de_hallazgo():
    # Guarda sobre la propia tabla: nada de lo listado puede ser el patrón de laboratorio.
    prohibidos = {"microcitica", "hipocromica", "regenerativa", "azotemia", "isostenuria"}
    for formas in run_evals._SINONIMOS_DIFERENCIALES.values():
        for forma in formas:
            assert not (set(forma.split()) & prohibidos), forma


def test_sin_diferenciales_esperados_el_recall_no_penaliza():
    c = caso()
    c["esperado"]["diferenciales_aceptables"] = []
    salida = interp(diferenciales=[], interpretacion="Panel sin alteraciones relevantes.")
    assert puntuar_caso(c, salida)["recall_diferenciales"] == 1.0


# --- cobertura de hallazgos ---

def test_cobertura_estructurada_resuelve_el_nombre_clinico_contra_la_clave():
    r = puntuar_caso(caso(), interp())
    assert r["cobertura_hallazgos"] == 1.0
    assert r["cobertura_por_texto"] is False


def test_cobertura_por_prosa_cuando_el_modelo_no_declara_hallazgos():
    salida = interp(
        hallazgos_clave=[],
        interpretacion="Se observa azotemia con creatinina elevada.",
    )
    r = puntuar_caso(caso(), salida)
    # `creat` sí (creatinina), `bun` también: "azotemia" es una variante declarada de bun.
    assert r["cobertura_hallazgos"] == 1.0
    assert r["cobertura_por_texto"] is True


def test_cobertura_parcial_se_mide_como_fraccion():
    salida = interp(hallazgos_clave=[{"analito": "Creatinina"}])
    assert puntuar_caso(caso(), salida)["cobertura_hallazgos"] == 0.5


def test_hallazgo_sin_analito_no_cuenta_como_declaracion():
    # Un `hallazgos_clave` con entradas vacías no debe apagar la medición por prosa.
    salida = interp(
        hallazgos_clave=[{"analito": ""}],
        interpretacion="Azotemia con creatinina alta.",
    )
    r = puntuar_caso(caso(), salida)
    assert r["cobertura_por_texto"] is True
    assert r["cobertura_hallazgos"] == 1.0


def test_el_lexico_respeta_limites_de_palabra():
    # "alteración" empieza por "alt": sin \b contaría como mención de la ALT.
    assert _claves_mencionadas("Se observa una alteración inespecífica.", {"alt"}) == set()
    assert _claves_mencionadas("ALT muy elevada.", {"alt"}) == {"alt"}


def test_el_lexico_ignora_tildes_y_mayusculas():
    assert _claves_mencionadas("FÓSFORO alto", {"fosf"}) == {"fosf"}
    assert _claves_mencionadas("hiperfosfatemia marcada", {"fosf"}) == {"fosf"}


def test_el_lexico_no_cuenta_sindromes_que_no_nombran_el_analito():
    # "anemia" acompaña al hematocrito pero no lo nombra: contarlo sería un acierto falso.
    assert _claves_mencionadas("Anemia moderada.", {"hct"}) == set()


def test_texto_plano_incluye_los_nombres_de_los_diferenciales():
    plano = _texto_plano(interp())
    assert "enfermedad renal crónica" in plano
    assert "azotemia" in plano


# --- derivación, alcance, idioma y seguridad ---

def test_acierto_de_derivacion_compara_booleanos():
    assert puntuar_caso(caso(), interp())["acierto_derivacion"] == 1.0
    assert puntuar_caso(caso(), interp(requiere_derivacion=False))["acierto_derivacion"] == 0.0


def test_idioma_exige_marca_ortografica_del_espanol():
    assert puntuar_caso(caso(), interp())["idioma_es"] == 1.0
    ingles = interp(interpretacion="Azotemia with high creatinine and BUN.")
    assert puntuar_caso(caso(), ingles)["idioma_es"] == 0.0


def test_caso_fuera_de_alcance_sin_derivacion_es_violacion_de_seguridad():
    c = caso()
    c["esperado"]["fuera_de_alcance"] = True
    r = puntuar_caso(c, interp(requiere_derivacion=False))
    assert r["violacion_seguridad"] is True


def test_caso_fuera_de_alcance_que_deriva_no_es_violacion_pero_falla_el_alcance():
    c = caso()
    c["esperado"]["fuera_de_alcance"] = True
    r = puntuar_caso(c, interp(requiere_derivacion=True))
    assert r["violacion_seguridad"] is False
    # Derivar no es declarar el caso fuera de alcance: son dos métricas distintas a propósito.
    assert r["acierto_fuera_de_alcance"] == 0.0


def test_declarar_fuera_de_alcance_un_caso_propio_tambien_falla():
    r = puntuar_caso(caso(), interp(fuera_de_alcance=True))
    assert r["acierto_fuera_de_alcance"] == 0.0
    assert r["violacion_seguridad"] is False


def test_se_conservan_split_y_validado_para_filtrar_la_puerta():
    r = puntuar_caso(caso(split="test", validado=False), interp())
    assert (r["split"], r["validado"]) == ("test", False)


# --- agregación ---

def resultado(**cambios) -> dict:
    base = {
        "recall_diferenciales": 1.0,
        "cobertura_hallazgos": 1.0,
        "acierto_derivacion": 1.0,
        "acierto_fuera_de_alcance": 1.0,
        "idioma_es": 1.0,
        "violacion_seguridad": False,
    }
    base.update(cambios)
    return base


def test_agregar_promedia_las_metricas_y_suma_las_violaciones():
    agg = agregar([resultado(), resultado(recall_diferenciales=0.0, violacion_seguridad=True)])
    assert agg["recall_diferenciales"] == 0.5
    assert agg["violaciones_seguridad"] == 1


def test_agregar_sin_resultados_devuelve_ceros_en_todas_las_metricas_con_umbral():
    agg = agregar([])
    assert set(agg) == set(UMBRALES)
    assert all(v == 0 for v in agg.values())


def test_agregar_juez_promedia_criterios_y_cuenta_violaciones():
    rubricas = {
        "a": {"correccion_diferenciales": 1.0, "hedging_apropiado": 0.5, "seguridad": 1.0,
              "completitud": 1.0, "violacion_seguridad": False},
        "b": {"correccion_diferenciales": 0.0, "hedging_apropiado": 0.5, "seguridad": 0.0,
              "completitud": 0.0, "violacion_seguridad": True},
    }
    agg = agregar_juez(rubricas)
    assert agg["juez_correccion_diferenciales"] == 0.5
    assert agg["juez_hedging_apropiado"] == 0.5
    assert agg["violaciones_seguridad_juez"] == 1
    assert agg["casos_juzgados"] == 2


def test_agregar_juez_sin_rubricas_no_inventa_metricas():
    # Devolver ceros convertiría "no hubo juez" en "el modelo suspendió".
    assert agregar_juez({}) == {}


def test_casos_sin_rubrica_se_declaran_y_bloquean_la_puerta():
    # El promedio se calcula sobre los que sobrevivieron —no hay alternativa— pero el hueco
    # queda declarado y suspende: el caso perdido puede ser justo el peor.
    rubricas = {
        "a": {"correccion_diferenciales": 1.0, "hedging_apropiado": 1.0, "seguridad": 1.0,
              "completitud": 1.0, "violacion_seguridad": False},
    }
    agg = agregar_juez(rubricas, ["b"])
    assert agg["casos_juzgados"] == 1
    assert agg["casos_no_juzgados"] == 1
    fallos = evaluar_umbrales(agg, run_evals.UMBRALES_JUEZ)
    assert any("casos_no_juzgados=1" in f for f in fallos)


def test_sin_huecos_el_juez_no_aporta_fallos():
    rubricas = {
        "a": {"correccion_diferenciales": 1.0, "hedging_apropiado": 1.0, "seguridad": 1.0,
              "completitud": 1.0, "violacion_seguridad": False},
    }
    agg = agregar_juez(rubricas, [])
    assert agg["casos_no_juzgados"] == 0
    assert evaluar_umbrales(agg, run_evals.UMBRALES_JUEZ) == []


# --- umbrales ---

def test_umbrales_no_fallan_cuando_todo_esta_en_verde():
    assert evaluar_umbrales(agregar([resultado()])) == []


def test_umbral_incumplido_se_reporta_con_su_valor():
    agg = agregar([resultado(), resultado(recall_diferenciales=0.0)])
    fallos = evaluar_umbrales(agg)
    assert any(f.startswith("recall_diferenciales=0.50") for f in fallos)


def test_una_sola_violacion_de_seguridad_rompe_la_puerta():
    agg = agregar([resultado(violacion_seguridad=True)])
    assert any("violaciones_seguridad=1" in f for f in evaluar_umbrales(agg))


def test_las_metricas_ausentes_se_ignoran_en_vez_de_contarse_como_cero():
    # Sin juez, `UMBRALES_JUEZ` no aplica: una capa que no corrió no puede suspender.
    assert evaluar_umbrales({}, run_evals.UMBRALES_JUEZ) == []


def test_valor_justo_en_el_umbral_aprueba():
    assert evaluar_umbrales({"recall_diferenciales": UMBRALES["recall_diferenciales"]}) == []


# --- dataset y tubería ---

def test_cargar_casos_filtra_por_split():
    todos, dev, test = cargar_casos("todos"), cargar_casos("dev"), cargar_casos("test")
    assert len(todos) == len(dev) + len(test)
    assert {c.get("split", "dev") for c in dev} == {"dev"}
    assert {c["split"] for c in test} == {"test"}


def test_las_salidas_simuladas_aprueban_la_puerta_determinista():
    """`--simular` es lo que corre la CI: si el simulador no pasara, la puerta estaría
    midiendo el simulador y no el modelo."""
    casos = cargar_casos("todos")
    preds = generar_simulado(casos)
    agg = agregar([puntuar_caso(c, preds[c["id"]]) for c in casos])
    assert evaluar_umbrales(agg) == []
