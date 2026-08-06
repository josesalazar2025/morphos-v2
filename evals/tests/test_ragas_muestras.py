"""Pruebas de `run_ragas.py`: construcción de muestras y umbrales de groundedness.

La recuperación real y el juez local quedan fuera (uno necesita el índice, el otro Ollama):
lo que se fija aquí es que la muestra se arme con la MISMA consulta que produce el servicio
—si la eval midiera una consulta aproximada, mediría otra tubería— y que un NaN no se
confunda nunca con un cero.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import run_ragas
from run_ragas import UMBRALES, evaluar_umbrales

# --- Umbrales ---


def test_todo_por_encima_del_umbral_no_reporta_nada():
    assert evaluar_umbrales({m: u + 0.1 for m, u in UMBRALES.items()}) == ([], [])


def test_metrica_por_debajo_del_umbral_se_reporta_con_su_valor():
    fallos, incalculables = evaluar_umbrales({"faithfulness": 0.42})
    assert fallos == ["faithfulness=0.42 < 0.70"]
    assert incalculables == []


def test_nan_es_incalculable_y_no_un_suspenso():
    fallos, incalculables = evaluar_umbrales({"faithfulness": float("nan")})
    assert fallos == []
    assert incalculables == ["faithfulness"]


def test_metrica_ausente_se_ignora():
    assert evaluar_umbrales({}) == ([], [])


def test_valor_justo_en_el_umbral_aprueba():
    assert evaluar_umbrales({"context_recall": UMBRALES["context_recall"]}) == ([], [])


def test_las_metricas_ajenas_a_la_puerta_no_la_afectan():
    assert evaluar_umbrales({"answer_relevancy": 0.01}) == ([], [])


# --- Construcción de muestras ---

@dataclass
class FragmentoFalso:
    texto: str


CASO = {
    "id": "erc-felino",
    "descripcion": "Azotemia en gato",
    "paciente": {"especie": "felino"},
    "valores": {"creat": 4.0},
    "esperado": {"diferenciales_aceptables": ["enfermedad renal crónica"]},
}

INTERP = {
    "interpretacion": "Azotemia con isostenuria.",
    "diferenciales": [
        {"nombre": "ERC", "evidencia": ["creatinina 4.0", "USG 1.012"]},
        {"nombre": "Deshidratación", "evidencia": []},
    ],
}


@pytest.fixture
def tuberia(monkeypatch):
    """Sustituye motor y recuperación por dobles, y registra con qué se les llamó."""
    pytest.importorskip("ragas", reason="requiere el grupo de dependencias 'evals'")
    from app.rag import retriever

    registro = {}

    def motor_falso(valores, paciente):
        registro["motor"] = (valores, paciente)
        return [{"nombre": "creatinina alta"}], [{"nombre": "azotemia renal"}]

    def recuperar_falso(consulta, especie=None, **kw):
        registro["consulta"] = consulta
        registro["especie"] = especie
        return [FragmentoFalso("Chronic kidney disease in cats."), FragmentoFalso("USG < 1.035")]

    monkeypatch.setattr(run_ragas, "_motor_determinista", motor_falso)
    monkeypatch.setattr(retriever, "recuperar", recuperar_falso)
    return registro


def test_la_consulta_se_construye_con_el_codigo_de_produccion(tuberia):
    run_ragas.construir_muestras([CASO], {CASO["id"]: INTERP})
    # `construir_consulta` es la misma función que usa `ai/service.py`: la eval mide la
    # tubería real, no una aproximación escrita para la eval.
    assert "azotemia renal" in tuberia["consulta"].lower()
    assert "creatinina" in tuberia["consulta"].lower()


def test_la_especie_del_paciente_llega_al_filtro_de_recuperacion(tuberia):
    run_ragas.construir_muestras([CASO], {CASO["id"]: INTERP})
    assert tuberia["especie"] == "felino"


def test_la_respuesta_evaluada_incluye_prosa_y_diferenciales(tuberia):
    muestra = run_ragas.construir_muestras([CASO], {CASO["id"]: INTERP})[0]
    # Los diferenciales son afirmaciones clínicas: deben estar tan fundamentados como la prosa.
    assert "Azotemia con isostenuria." in muestra.response
    assert "ERC: creatinina 4.0; USG 1.012" in muestra.response
    assert "Deshidratación" in muestra.response


def test_los_contextos_son_los_fragmentos_recuperados(tuberia):
    muestra = run_ragas.construir_muestras([CASO], {CASO["id"]: INTERP})[0]
    assert muestra.retrieved_contexts == ["Chronic kidney disease in cats.", "USG < 1.035"]


def test_la_referencia_sale_de_los_diferenciales_aceptables(tuberia):
    muestra = run_ragas.construir_muestras([CASO], {CASO["id"]: INTERP})[0]
    assert muestra.reference == "enfermedad renal crónica"


def test_sin_diferenciales_aceptables_la_referencia_cae_a_la_descripcion(tuberia):
    caso = {**CASO, "esperado": {"diferenciales_aceptables": []}}
    muestra = run_ragas.construir_muestras([caso], {caso["id"]: INTERP})[0]
    assert muestra.reference == "Azotemia en gato"


def test_un_caso_sin_prediccion_se_omite(tuberia):
    assert run_ragas.construir_muestras([CASO], {}) == []


def test_un_caso_sin_fragmentos_se_omite_en_vez_de_puntuar_contra_nada(monkeypatch):
    pytest.importorskip("ragas", reason="requiere el grupo de dependencias 'evals'")
    from app.rag import retriever

    monkeypatch.setattr(run_ragas, "_motor_determinista", lambda v, p: ([], []))
    monkeypatch.setattr(retriever, "recuperar", lambda *a, **k: [])
    # Con 0 contextos, faithfulness sería 0 por falta de índice y no por el modelo.
    assert run_ragas.construir_muestras([CASO], {CASO["id"]: INTERP}) == []
