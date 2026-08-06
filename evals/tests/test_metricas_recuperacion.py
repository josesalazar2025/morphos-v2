"""Pruebas de `run_retrieval_eval.py`: métricas, construcción de consultas y elección de juez.

Estas métricas son las que deciden A/B de recuperación (consulta única vs multi-consulta,
embeddings, idioma). Un `precision@k` mal calculado no rompe nada visible: sólo hace tomar la
decisión contraria, y por eso se fija aquí. Nada de esto toca el índice.
"""

from __future__ import annotations

import pytest
import run_retrieval_eval as rre
from run_retrieval_eval import (
    construir_query_eval,
    elegir_juez,
    hubo_acierto,
    precision_en_k,
    rango_reciproco,
    resumen,
)


def test_precision_en_k_es_la_fraccion_de_relevantes():
    assert precision_en_k([True, False, True, False]) == 0.5
    assert precision_en_k([True, True]) == 1.0
    assert precision_en_k([False, False]) == 0.0


def test_precision_sin_fragmentos_es_cero_y_no_divide_por_cero():
    assert precision_en_k([]) == 0.0


def test_rango_reciproco_usa_la_primera_posicion_relevante():
    assert rango_reciproco([True, False, False]) == 1.0
    assert rango_reciproco([False, True, False]) == 0.5
    assert rango_reciproco([False, False, True]) == 1 / 3


def test_rango_reciproco_sin_aciertos_es_cero():
    assert rango_reciproco([False, False]) == 0.0
    assert rango_reciproco([]) == 0.0


def test_hubo_acierto_es_cualquier_relevante():
    assert hubo_acierto([False, True]) is True
    assert hubo_acierto([False, False]) is False
    assert hubo_acierto([]) is False


def test_resumen_promedia_las_tres_metricas_por_caso():
    met = resumen([[True, False], [False, True]])
    assert met["n_casos"] == 2
    assert met["precision@k"] == 0.5
    assert met["hit_rate"] == 1.0
    assert met["mrr"] == 0.75  # (1/1 + 1/2) / 2


def test_resumen_sin_casos_no_revienta():
    assert resumen([]) == {"n_casos": 0, "precision@k": 0.0, "hit_rate": 0.0, "mrr": 0.0}


def test_un_caso_sin_fragmentos_cuenta_como_fallo_y_no_se_descarta():
    """Un caso que no recuperó nada tiene que hundir la media, no desaparecer de ella:
    si se omitiera, una config que recupera menos parecería mejor."""
    met = resumen([[True, True], []])
    assert met["n_casos"] == 2
    assert met["precision@k"] == 0.5
    assert met["hit_rate"] == 0.5


# --- Construcción de la consulta de evaluación ---

CASO = {
    "id": "caso-x",
    "descripcion": "Azotemia en gato",
    "signos_clinicos": "Poliuria y polidipsia",
    "paciente": {"especie": "felino"},
    "valores": {"creat": 4.0, "bun": 60, "usg": 1.011},
    "esperado": {
        "hallazgos_clave": ["creat", "bun"],
        "diferenciales_aceptables": ["enfermedad renal crónica"],
    },
}


@pytest.fixture
def motor_falso(monkeypatch):
    """El motor real necesita Node; aquí basta con fijar lo que devolvería para este caso."""
    monkeypatch.setattr(
        "run_evals._motor_determinista",
        lambda valores, paciente: (
            [{"nombre": "Creatinina"}, {"nombre": "BUN/Urea"}, {"nombre": "Densidad (USG)"}],
            [{"nombre": "Azotemia"}, {"nombre": "Isostenuria"}],
        ),
    )


def test_la_consulta_es_la_que_emitiria_produccion(motor_falso):
    """Se arma con `construir_consulta` sobre la salida del motor: el mismo código y las
    mismas entradas que `ai/service.py`."""
    q = construir_query_eval(CASO).lower()
    assert "azotemia" in q and "isostenuria" in q
    assert "creatinina" in q and "bun" in q


def test_la_consulta_lleva_los_nombres_y_no_las_claves(motor_falso):
    # «Densidad (USG)» trae la sigla inglesa, que es lo que casa con el corpus en BM25;
    # la clave cruda `usg` sola no representaba la consulta real.
    assert "Densidad (USG)" in construir_query_eval(CASO)


def test_la_consulta_no_filtra_la_respuesta_esperada(motor_falso):
    # Meter `diferenciales_aceptables` en la consulta haría que el juez encontrara siempre
    # fragmentos "relevantes": la eval se aprobaría a sí misma.
    assert "enfermedad renal crónica" not in construir_query_eval(CASO)


def test_la_consulta_no_arrastra_metadatos_del_dataset(motor_falso):
    """`descripcion` es plantilla de corrección, no entrada del paciente: incluirla orientaba
    la recuperación hacia el diagnóstico esperado. `signos_clinicos` tampoco viaja en la
    consulta de producción."""
    q = construir_query_eval(CASO)
    assert "Azotemia en gato" not in q
    assert "Poliuria y polidipsia" not in q


def test_la_multiconsulta_reproduce_la_descomposicion_de_produccion(motor_falso):
    consultas = rre.construir_queries_eval(CASO)
    assert len(consultas) > 1
    unidas = " ".join(consultas).lower()
    assert "azotemia" in unidas
    assert "enfermedad renal" not in unidas  # tampoco aquí se filtra lo esperado


# --- Juez de relevancia ---

def test_el_heuristico_marca_relevante_lo_que_solapa_con_el_diagnostico():
    textos = [
        "Chronic kidney disease causes progressive azotemia in cats.",
        "Hemocytometer chamber loading technique for platelet counts.",
    ]
    assert rre._juez_keyword(CASO, textos) == [True, False]


def test_el_heuristico_traduce_el_concepto_esperado_al_idioma_del_corpus():
    # El corpus está en inglés y el caso dorado en español: sin traducción, 0 relevantes.
    assert rre._juez_keyword(CASO, ["Chronic kidney disease in the cat."]) == [True]


def test_el_juez_local_pregunta_una_vez_por_fragmento_con_el_diagnostico_esperado(monkeypatch):
    preguntas = []

    def falso(sistema, mensaje, esquema, **kw):
        preguntas.append(mensaje)
        return {"relevante": len(preguntas) == 1}

    monkeypatch.setattr("judge.ollama_local.preguntar_json", falso)
    assert rre._juez_ollama(CASO, ["frag A", "frag B"]) == [True, False]
    assert len(preguntas) == 2
    assert "enfermedad renal crónica" in preguntas[0]
    assert "frag A" in preguntas[0]


def test_una_respuesta_sin_el_campo_relevante_se_cuenta_como_no_relevante(monkeypatch):
    # No hay tercera opción: un fragmento que el juez no supo puntuar no puede subir la
    # precisión de la config que se está evaluando.
    monkeypatch.setattr("judge.ollama_local.preguntar_json", lambda *a, **k: {})
    assert rre._juez_ollama(CASO, ["frag"]) == [False]


def test_juez_keyword_se_elige_explicitamente_sin_tocar_transportes():
    juez, etiqueta = elegir_juez("keyword")
    assert juez is rre._juez_keyword
    assert etiqueta == "keyword(aprox)"


def test_una_preferencia_no_disponible_degrada_a_keyword_en_vez_de_fallar(monkeypatch):
    monkeypatch.setattr("judge.ollama_local.disponible", lambda: (False, "sin Ollama"))
    juez, etiqueta = elegir_juez("ollama")
    assert juez is rre._juez_keyword
    assert etiqueta == "keyword(aprox)"


def test_auto_prefiere_el_cli_cuando_esta_disponible(monkeypatch):
    monkeypatch.setattr("judge.claude_cli.disponible", lambda: (True, ""))
    monkeypatch.setattr("judge.claude_cli.modelo_cli", lambda: "sonnet")
    juez, etiqueta = elegir_juez("auto")
    assert juez is rre._juez_cli
    assert etiqueta == "claude-cli:sonnet"


def test_auto_cae_a_ollama_si_no_hay_cli(monkeypatch):
    monkeypatch.setattr("judge.claude_cli.disponible", lambda: (False, "sin binario"))
    monkeypatch.setattr("judge.ollama_local.disponible", lambda: (True, ""))
    monkeypatch.setattr("judge.ollama_local.modelo_juez", lambda: "qwen2.5:7b")
    juez, etiqueta = elegir_juez("auto")
    assert juez is rre._juez_ollama
    assert etiqueta == "ollama:qwen2.5:7b"


def test_auto_sin_ningun_transporte_acaba_en_keyword(monkeypatch):
    monkeypatch.setattr("judge.claude_cli.disponible", lambda: (False, "sin binario"))
    monkeypatch.setattr("judge.ollama_local.disponible", lambda: (False, "sin Ollama"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    juez, etiqueta = elegir_juez("auto")
    assert juez is rre._juez_keyword
    assert etiqueta == "keyword(aprox)"
