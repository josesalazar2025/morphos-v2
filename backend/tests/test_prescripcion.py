"""Guarda contra indicaciones terapéuticas en la salida del modelo.

Lo motiva un caso real: el 2026-07-31 medGemma recomendó «iniciar tratamiento inmediato con
insulina, fluidoterapia intravenosa y reposición de potasio» en un paciente con potasio
3,0 mEq/L —donde dar insulina antes de corregir el potasio puede matar— y el juez lo marcó como
violación de seguridad. Como con el alcance y la derivación, la regla no puede vivir sólo en el
prompt de un 4B.
"""

from __future__ import annotations

import pytest

from app.ai.prescripcion import detectar_prescripcion, encuadrar
from app.ai.service import interpretar
from app.schemas import InterpretacionClinica, PeticionInterpretacion


@pytest.mark.parametrize(
    "texto",
    [
        "Se recomienda iniciar tratamiento inmediato con insulina y fluidoterapia intravenosa.",
        "Administrar bicarbonato si el pH no mejora.",
        "Pautar antibióticos de amplio espectro.",
        "Dosificar levotiroxina a 0,02 mg/kg cada 12 horas.",
        "Reponer potasio antes de la insulina.",
        "Comenzar con prednisolona 1 mg/kg.",
    ],
)
def test_detecta_lenguaje_prescriptivo(texto):
    assert detectar_prescripcion(texto)


@pytest.mark.parametrize(
    "texto",
    [
        # Lenguaje diagnóstico legítimo: es lo que la herramienta SÍ debe hacer.
        "Se recomienda repetir la analítica en 2-4 semanas y realizar ecografía abdominal.",
        "Considerar hipoadrenocorticismo; confirmar con test de estimulación con ACTH.",
        "La hipopotasemia puede perpetuar la hipocalcemia refractaria.",
        "Los hallazgos son compatibles con cetoacidosis diabética.",
        "Valorar remisión a un centro con hospitalización 24 horas.",
        # Menciona un fármaco como CAUSA, no como indicación.
        "El fenobarbital puede inducir la fosfatasa alcalina.",
    ],
)
def test_no_marca_lenguaje_diagnostico(texto):
    assert detectar_prescripcion(texto) == []


def test_el_encuadre_no_borra_texto_clinico():
    original = "Se recomienda iniciar insulina. El resto del cuadro es compatible con CAD."
    resultado = encuadrar(original)
    assert original in resultado
    assert resultado.startswith("Nota de alcance")


def test_el_encuadre_no_se_duplica():
    assert encuadrar(encuadrar("Administrar fluidoterapia.")).count("Nota de alcance") == 1


class ClientePrescriptor:
    nombre = "medgemma-hf"

    async def interpretar(self, *_a, **_k):
        return InterpretacionClinica(
            interpretacion=(
                "Cuadro compatible con cetoacidosis diabética. Se recomienda iniciar "
                "tratamiento inmediato con insulina, fluidoterapia intravenosa y reposición "
                "de potasio. " * 2
            ),
        )


async def test_el_servicio_encuadra_y_deriva(monkeypatch):
    import app.ai.service as S

    for nombre in ("recuperar", "recuperar_multi"):
        monkeypatch.setattr(S, nombre, lambda *_a, **_k: [])
    monkeypatch.setattr(S, "_crear_cliente", lambda _b: ClientePrescriptor())

    pet = PeticionInterpretacion(
        paciente={"especie": "canino"},
        hallazgos=[{"clave": "gluc", "nombre": "Glucosa", "valor": 480, "unidad": "mg/dL",
                    "direccion": "alto", "gravedad": "grave"}],
    )
    resp = await interpretar(pet)

    assert resp.resultado.interpretacion.startswith("Nota de alcance")
    assert "cetoacidosis diabética" in resp.resultado.interpretacion
    assert resp.resultado.requiere_derivacion is True


# --- Contextos diagnósticos: no son prescripción (falso positivo real, 2026-08-01) ---

@pytest.mark.parametrize(
    "texto",
    [
        # Texto literal de `hiperadrenocorticismo-canino` que disparaba la guarda.
        "Prueba de Supresión con Dexametasona de Baja Dosis (LDDST): Alternativa para confirmar "
        "HAC. Se administra dexametasona y se mide el cortisol tras 24 horas.",
        "Prueba de estimulación con ACTH: se mide el cortisol basal y luego se administra ACTH "
        "sintético, midiendo nuevamente el cortisol después de 30-60 minutos.",
    ],
)
def test_un_protocolo_diagnostico_no_es_prescripcion(texto):
    assert detectar_prescripcion(texto) == []


def test_sigue_detectando_prescripcion_junto_a_una_prueba_diagnostica():
    """La exención es por oración, no por texto: una frase diagnóstica no absuelve al resto."""
    texto = (
        "Prueba de estimulación con ACTH para confirmar el diagnóstico. "
        "Mientras tanto, iniciar fluidoterapia intravenosa y administrar prednisolona."
    )
    assert detectar_prescripcion(texto)
