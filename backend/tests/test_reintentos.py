"""Política de reintentos del servicio de interpretación.

El reintento existe para una sola cosa: la salida malformada de medGemma (razonamiento filtrado
o bucle de repetición), donde volver a muestrear suele arreglarlo. Reintentar un 429 hace lo
contrario —gasta otra reserva de GPU del mismo pozo agotado— y reintentar un rechazo por
seguridad o una clave ausente no puede cambiar el resultado.

Estos tests cuentan LLAMADAS, que es lo que consume cuota.
"""

from __future__ import annotations

import pytest

from app.ai import service
from app.ai.base import ErrorModelo
from app.schemas import InterpretacionClinica, PeticionInterpretacion

PETICION = {
    "paciente": {"especie": "canino"},
    "hallazgos": [
        {
            "clave": "hct",
            "nombre": "Hematocrito",
            "valor": 22.0,
            "unidad": "%",
            "direccion": "bajo",
            "gravedad": "grave",
        }
    ],
    "patrones": [{"nombre": "Anemia", "descripcion": "…", "gravedad": "grave"}],
    "imagenes": [],
}


class ClienteFalso:
    nombre = "medgemma-hf"

    def __init__(self, error: ErrorModelo | None, exito_en: int | None = None):
        self.error = error
        self.exito_en = exito_en
        self.llamadas = 0

    async def interpretar(self, *_a, **_k):
        self.llamadas += 1
        if self.exito_en is not None and self.llamadas >= self.exito_en:
            return InterpretacionClinica(interpretacion="ok " * 20, requiere_derivacion=True)
        raise self.error


@pytest.fixture
def sin_rag(monkeypatch):
    """Aísla del retriever: estos tests miden reintentos, no recuperación."""
    monkeypatch.setattr(service, "recuperar", lambda *_a, **_k: [])


async def _interpretar_con(cliente, monkeypatch):
    monkeypatch.setattr(service, "_crear_cliente", lambda _b: cliente)
    return await service.interpretar(PeticionInterpretacion.model_validate(PETICION))


async def test_saturado_no_se_reintenta(sin_rag, monkeypatch):
    """El caso que motiva todo: un 429 debe costar UNA llamada, no dos."""
    err = ErrorModelo("cuota agotada", reintentable=False, saturado=True)
    cliente = ClienteFalso(err)
    with pytest.raises(ErrorModelo) as exc:
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 1, "un 429 reintentado duplica el gasto de cuota"
    assert exc.value.saturado is True


async def test_rechazo_de_seguridad_no_se_reintenta(sin_rag, monkeypatch):
    cliente = ClienteFalso(ErrorModelo("rechazo", reintentable=False))
    with pytest.raises(ErrorModelo):
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 1


async def test_salida_malformada_si_se_reintenta(sin_rag, monkeypatch):
    """La razón de ser del reintento: se vuelve a muestrear y la segunda sale bien."""
    cliente = ClienteFalso(ErrorModelo("razonamiento filtrado"), exito_en=2)
    resultado = await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 2
    assert resultado.resultado.interpretacion.startswith("ok")


async def test_el_reintento_no_es_infinito(sin_rag, monkeypatch):
    cliente = ClienteFalso(ErrorModelo("siempre malformada"))
    with pytest.raises(ErrorModelo):
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 2


class ClienteProsa:
    """Ruta HF Space: devuelve prosa con marcadores [n], sin `diferenciales`."""

    nombre = "medgemma-hf"

    def __init__(self, texto: str):
        self.texto = texto

    async def interpretar(self, *_a, **_k):
        return InterpretacionClinica(interpretacion=self.texto, requiere_derivacion=True)


async def test_la_ruta_de_prosa_devuelve_fuentes_verificables(monkeypatch):
    """La ruta por defecto en producción no puede rellenar `citas[]`, así que su atribución
    depende de que el servicio adjunte las fuentes recuperadas y resuelva los marcadores."""
    from app.rag.retriever import Fragmento

    fragmento = Fragmento(
        texto="…", libro="Thrall Veterinary Hematology", edicion="3.ª ed.",
        capitulo="Anemia", pagina="210", score=0.9,
    )
    monkeypatch.setattr(service, "recuperar", lambda *_a, **_k: [fragmento])
    cliente = ClienteProsa("Anemia arregenerativa compatible con proceso crónico [1]. " * 3)

    resp = await _interpretar_con(cliente, monkeypatch)

    assert [f.cita for f in resp.fuentes] == ["Thrall Veterinary Hematology, 3.ª ed., p. 210"]
    assert resp.fuentes[0].citada
    assert resp.fuentes_rag == 1
