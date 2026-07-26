"""Pruebas del esquema estructurado y la validación que reemplaza a limpiarRespuesta."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    Diferencial,
    InterpretacionClinica,
    PeticionInterpretacion,
)


def test_interpretacion_valida():
    inter = InterpretacionClinica(
        interpretacion="Anemia microcítica compatible con ferropenia.",
        diferenciales=[
            Diferencial(nombre="Ferropenia", probabilidad="alta", evidencia=["VCM bajo"], citas=["Thrall, 3ª ed., p. 210"])
        ],
        siguientes_pruebas=["Perfil de hierro"],
        confianza="media",
        requiere_derivacion=True,
    )
    assert inter.idioma == "es"
    assert inter.diferenciales[0].probabilidad == "alta"


def test_interpretacion_rechaza_vacia():
    with pytest.raises(ValidationError):
        InterpretacionClinica(interpretacion="   ")


def test_probabilidad_invalida_rechazada():
    with pytest.raises(ValidationError):
        Diferencial(nombre="X", probabilidad="segurísima")


def test_peticion_limita_a_4_imagenes():
    pet = PeticionInterpretacion(
        paciente={"especie": "canino"},
        imagenes=[f"data:image/png;base64,AAAA{i}" for i in range(10)],
    )
    assert len(pet.imagenes) == 4


def test_json_schema_generable_para_tool_use():
    # El cliente Claude/medGemma pasa este schema como salida estructurada.
    esquema = InterpretacionClinica.model_json_schema()
    assert "diferenciales" in esquema["properties"]
    assert esquema["properties"]["requiere_derivacion"]["type"] == "boolean"
