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


def test_el_esquema_estructurado_exige_contenido():
    """El esquema por defecto admite `{"interpretacion": "..."}` con todo lo demás vacío;
    el endurecido se lo pide explícitamente al modelo."""
    from app.schemas import esquema_estructurado

    esquema = esquema_estructurado()
    for campo in ("hallazgos_clave", "diferenciales", "siguientes_pruebas"):
        assert esquema["properties"][campo]["minItems"] == 1
        assert campo in esquema["required"]


def test_el_esquema_por_defecto_sigue_siendo_permisivo():
    """La ruta de prosa construye la interpretación sin campos estructurados y debe validar."""
    from app.schemas import InterpretacionClinica

    interp = InterpretacionClinica(interpretacion="Sólo prosa.")
    assert interp.diferenciales == []


def test_analitos_medidos_es_opcional():
    """Retrocompatible: una petición de un cliente que no lo manda sigue siendo válida, y el
    prompt y la guarda de invención se apagan solos ante la lista vacía."""
    pet = PeticionInterpretacion.model_validate({"paciente": {"especie": "canino"}})
    assert pet.analitos_medidos == []


def test_analitos_medidos_conserva_las_claves():
    pet = PeticionInterpretacion.model_validate(
        {"paciente": {"especie": "felino"}, "analitos_medidos": ["calc", "fosf", "creat"]}
    )
    assert pet.analitos_medidos == ["calc", "fosf", "creat"]
