"""Un caso que el juez no llegó a puntuar no puede desaparecer del informe.

Motivo: la corrida del 2026-08-04 contra el Space local decidió la puerta sobre 29 de 30 casos
—el juez falló en `cetoacidosis-felino-gases`, cuya predicción era perfectamente válida— y lo
único que lo delataba era un `casos_juzgados: 29` en el JSON. Como el promedio se calcula sobre
los que sobrevivieron, un fallo del juez en el peor caso SUBE la nota: exactamente al revés de
lo que debe hacer una puerta. Aquí se fija que el hueco se reintenta, se declara y bloquea.
"""

from __future__ import annotations

import asyncio

import pytest
from judge import ErrorJuez
from run_evals import puntuar_con_juez

CASOS = [
    {"id": "caso-1", "paciente": {"especie": "canino"}},
    {"id": "caso-2", "paciente": {"especie": "felino"}},
]
PREDS = {c["id"]: {"interpretacion": "texto"} for c in CASOS}

RUBRICA = {
    "correccion_diferenciales": 0.9, "hedging_apropiado": 0.9, "seguridad": 0.9,
    "completitud": 0.9, "violacion_seguridad": False, "justificacion": "ok",
}


class JuezFalso:
    """`fallos` es cuántas veces seguidas falla cada id antes de responder bien."""

    nombre = "falso"

    def __init__(self, fallos: dict[str, int] | None = None, concurrencia: int = 1):
        self.fallos = dict(fallos or {})
        self.concurrencia = concurrencia
        self.llamadas: list[str] = []

    async def juzgar(self, caso, pred):
        self.llamadas.append(caso["id"])
        if self.fallos.get(caso["id"], 0) > 0:
            self.fallos[caso["id"]] -= 1
            raise ErrorJuez("fallo simulado")
        return dict(RUBRICA)


@pytest.mark.parametrize("concurrencia", [1, 4])
def test_fallo_aislado_se_reintenta_y_no_deja_hueco(concurrencia):
    # Lo que se vio en producción fue un fallo suelto entre 29 casos buenos: casi seguro un
    # timeout. Un reintento lo recupera sin que nadie tenga que relanzar la corrida.
    juez = JuezFalso({"caso-2": 1}, concurrencia)
    rubricas, no_juzgados = asyncio.run(puntuar_con_juez(juez, CASOS, PREDS))
    assert set(rubricas) == {"caso-1", "caso-2"}
    assert no_juzgados == []
    assert juez.llamadas.count("caso-2") == 2


@pytest.mark.parametrize("concurrencia", [1, 4])
def test_fallo_persistente_devuelve_el_id_en_vez_de_tragarselo(concurrencia):
    juez = JuezFalso({"caso-2": 99}, concurrencia)
    rubricas, no_juzgados = asyncio.run(puntuar_con_juez(juez, CASOS, PREDS))
    assert set(rubricas) == {"caso-1"}
    assert no_juzgados == ["caso-2"]


def test_caso_sin_prediccion_no_cuenta_como_hueco_del_juez():
    # No hay nada que juzgar: el modelo no respondió, y eso ya lo penalizan las métricas
    # deterministas. Contarlo dos veces convertiría un fallo del modelo en uno del juez.
    juez = JuezFalso()
    rubricas, no_juzgados = asyncio.run(
        puntuar_con_juez(juez, CASOS, {"caso-1": PREDS["caso-1"]})
    )
    assert set(rubricas) == {"caso-1"}
    assert no_juzgados == []


def test_juez_sistematicamente_roto_deja_todos_los_pendientes_declarados():
    # En serie la corrida se abandona tras tres fallos seguidos para no repetir el mismo error
    # 30 veces; los casos que nunca se intentaron son huecos igual y tienen que salir.
    casos = [{"id": f"caso-{i}", "paciente": {}} for i in range(6)]
    preds = {c["id"]: {"interpretacion": "texto"} for c in casos}
    juez = JuezFalso({c["id"]: 99 for c in casos})
    rubricas, no_juzgados = asyncio.run(puntuar_con_juez(juez, casos, preds))
    assert rubricas == {}
    assert no_juzgados == [c["id"] for c in casos]
