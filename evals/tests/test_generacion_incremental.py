"""La generación tiene que sobrevivir a que maten el proceso.

`generar_con_modelo` ya toleraba que fallara el modelo en un caso, pero escribía a disco sólo
al final: si el proceso moría, se perdía TODO lo generado. Medido el 2026-08-03 contra el Space
local, 70 minutos tirados. Estas pruebas fijan las dos mitades del arreglo —escribir en caliente
y poder reanudar— sin llamar a ningún modelo.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import run_evals
from run_evals import cargar_predicciones, generar_con_modelo

CASOS = [
    {"id": "caso-1", "paciente": {"especie": "canino"}, "valores": {"creat": 4.0},
     "signos_clinicos": "", "esperado": {}},
    {"id": "caso-2", "paciente": {"especie": "felino"}, "valores": {"creat": 3.0},
     "signos_clinicos": "", "esperado": {}},
]


@pytest.fixture
def modelo_falso(monkeypatch):
    """Sustituye motor e inferencia; `registro` anota qué casos llegaron a generarse."""
    from app.ai import service
    from app.schemas import InterpretacionClinica, RespuestaInterpretacion

    registro: list[str] = []
    monkeypatch.setattr(run_evals, "_motor_determinista", lambda v, p: ([], []))

    async def interpretar_falso(pet):
        registro.append(pet.paciente.especie)
        return RespuestaInterpretacion(
            resultado=InterpretacionClinica(
                interpretacion=f"Interpretación para {pet.paciente.especie}.",
                idioma="es",
            ),
            backend="falso",
            modelo="falso",
        )

    monkeypatch.setattr(service, "interpretar", interpretar_falso)
    return registro


def test_cada_prediccion_se_escribe_en_cuanto_llega(tmp_path, modelo_falso):
    destino = tmp_path / "sub" / "preds.jsonl"
    asyncio.run(generar_con_modelo(CASOS, "medgemma", incremental=destino))
    guardadas = cargar_predicciones(destino)
    assert set(guardadas) == {"caso-1", "caso-2"}
    assert "canino" in guardadas["caso-1"]["interpretacion"]


def test_lo_generado_sobrevive_a_que_reviente_el_caso_siguiente(tmp_path, monkeypatch):
    """El escenario real: el proceso muere a mitad. Lo anterior tiene que estar en disco."""
    from app.ai import service
    from app.schemas import InterpretacionClinica, RespuestaInterpretacion

    monkeypatch.setattr(run_evals, "_motor_determinista", lambda v, p: ([], []))
    destino = tmp_path / "preds.jsonl"

    async def interpretar_falso(pet):
        if pet.paciente.especie == "felino":
            raise KeyboardInterrupt  # sustituto de un SIGKILL a mitad de corrida
        return RespuestaInterpretacion(
            resultado=InterpretacionClinica(interpretacion="Prosa canina.", idioma="es"),
            backend="falso",
            modelo="falso",
        )

    monkeypatch.setattr(service, "interpretar", interpretar_falso)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(generar_con_modelo(CASOS, "medgemma", incremental=destino))

    # Antes de este arreglo el fichero ni existía: se escribía al terminar.
    assert cargar_predicciones(destino).keys() == {"caso-1"}


def test_reanudar_no_regenera_lo_que_ya_esta_en_disco(tmp_path, modelo_falso):
    destino = tmp_path / "preds.jsonl"
    previas = {"caso-1": {"interpretacion": "Ya estaba.", "idioma": "es"}}
    salidas = asyncio.run(
        generar_con_modelo(CASOS, "medgemma", incremental=destino, ya_generados=previas)
    )
    assert salidas["caso-1"]["interpretacion"] == "Ya estaba."
    assert modelo_falso == ["felino"], "sólo debía generarse el caso que faltaba"
    # Y el que faltaba sí se anexa, sin duplicar el que ya estaba.
    assert cargar_predicciones(destino).keys() == {"caso-2"}


def test_sin_incremental_no_se_escribe_nada(tmp_path, modelo_falso):
    salidas = asyncio.run(generar_con_modelo(CASOS, "medgemma"))
    assert set(salidas) == {"caso-1", "caso-2"}
    assert list(tmp_path.iterdir()) == []


def test_cargar_predicciones_tolera_fichero_inexistente(tmp_path):
    assert cargar_predicciones(tmp_path / "no-existe.jsonl") == {}


def test_cargar_predicciones_ignora_lineas_en_blanco(tmp_path):
    ruta = tmp_path / "preds.jsonl"
    ruta.write_text(
        json.dumps({"id": "a", "interpretacion": {"interpretacion": "x"}}) + "\n\n",
        encoding="utf-8",
    )
    assert set(cargar_predicciones(ruta)) == {"a"}
