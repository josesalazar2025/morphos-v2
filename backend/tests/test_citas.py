"""Pruebas de la atribución verificable (app/ai/citas.py).

Cubre lo que hace posible citar en la ruta de PROSA del HF Space —marcadores [n] resueltos
contra los fragmentos realmente recuperados— y el descarte de citas que el modelo inventa
en las rutas estructuradas.
"""

from __future__ import annotations

from app.ai.citas import (
    aplicar_atribucion,
    construir_fuentes,
    indices_citados,
    limpiar_marcadores_invalidos,
    resolver_cita,
)
from app.rag.retriever import Fragmento
from app.schemas import InterpretacionClinica


def _fragmentos():
    return [
        Fragmento(
            texto="La anemia ferropénica cursa con microcitosis.",
            libro="Thrall Veterinary Hematology", edicion="3.ª ed.",
            capitulo="Anemia", pagina="210", score=0.9,
        ),
        Fragmento(
            texto="La ERC felina cursa con isostenuria.",
            libro="Ettinger Textbook of Veterinary Internal Medicine", edicion="8.ª ed.",
            capitulo="Nefrología", pagina="1812", score=0.7,
        ),
    ]


def _interpretacion(texto: str, citas: list[str] | None = None):
    return InterpretacionClinica(
        interpretacion=texto,
        diferenciales=[
            {"nombre": "Anemia ferropénica", "probabilidad": "alta", "evidencia": [], "citas": citas or []}
        ],
    )


def test_fuentes_se_numeran_como_en_el_prompt():
    fuentes = construir_fuentes(_fragmentos())
    assert [f.indice for f in fuentes] == [1, 2]
    assert fuentes[0].cita == "Thrall Veterinary Hematology, 3.ª ed., p. 210"


def test_prosa_marca_las_fuentes_citadas():
    interp, fuentes = aplicar_atribucion(
        _interpretacion("Patrón compatible con ferropenia [1]."), _fragmentos()
    )
    assert "[1]" in interp.interpretacion
    assert [f.citada for f in fuentes] == [True, False]


def test_marcador_fuera_de_rango_se_borra_del_texto():
    interp, fuentes = aplicar_atribucion(
        _interpretacion("Compatible con ferropenia [7] y con ERC [2]."), _fragmentos()
    )
    assert "[7]" not in interp.interpretacion
    assert "[2]" in interp.interpretacion
    assert [f.citada for f in fuentes] == [False, True]


def test_sin_recuperacion_no_queda_ningun_marcador():
    interp, fuentes = aplicar_atribucion(_interpretacion("Ferropenia probable [1]."), [])
    assert "[1]" not in interp.interpretacion
    assert fuentes == []


def test_limpieza_no_deja_espacio_antes_de_la_puntuacion():
    assert limpiar_marcadores_invalidos("Ferropenia [9] .", 0) == "Ferropenia."


def test_indices_citados_ignora_los_invalidos():
    assert indices_citados("a [1] b [3] c [2]", 2) == {1, 2}


def test_cita_por_titulo_se_resuelve_contra_la_fuente_real():
    fuentes = construir_fuentes(_fragmentos())
    assert resolver_cita("Ettinger, Textbook of Veterinary Internal Medicine, p. 1812", fuentes) == 2
    assert resolver_cita("[1]", fuentes) == 1


def test_cita_inventada_no_se_resuelve():
    fuentes = construir_fuentes(_fragmentos())
    assert resolver_cita("Nelson y Couto, Medicina Interna de Pequeños Animales, p. 55", fuentes) is None


def test_citas_estructuradas_no_verificables_se_descartan():
    interp, fuentes = aplicar_atribucion(
        _interpretacion(
            "Ferropenia probable.",
            citas=["[1]", "Nelson y Couto, Small Animal Internal Medicine, p. 55"],
        ),
        _fragmentos(),
    )
    assert interp.diferenciales[0].citas == ["Thrall Veterinary Hematology, 3.ª ed., p. 210"]
    assert [f.citada for f in fuentes] == [True, False]
