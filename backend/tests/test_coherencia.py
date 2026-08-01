"""Un hallazgo estructurado sobre un analito no enviado es una invención (2026-08-01)."""

from __future__ import annotations

from app.ai.coherencia import descartar_fabricados, hallazgos_fabricados
from app.schemas import InterpretacionClinica, PeticionInterpretacion


def _peticion():
    # El caso real: se enviaron calcio, fósforo, BUN y creatinina. Nunca potasio.
    return PeticionInterpretacion(
        paciente={"especie": "canino"},
        hallazgos=[
            {"clave": "calc", "nombre": "Calcio (Ca)", "valor": 15.5, "unidad": "mg/dL",
             "direccion": "alto", "gravedad": "grave"},
            {"clave": "fosf", "nombre": "Fósforo (P)", "valor": 2.5, "unidad": "mg/dL",
             "direccion": "bajo", "gravedad": "leve"},
        ],
    )


def _resultado(*analitos):
    return InterpretacionClinica(
        interpretacion="Hipercalcemia con fósforo bajo. " * 3,
        hallazgos_clave=[
            {"analito": a, "direccion": "alto", "gravedad": "grave", "comentario": ""}
            for a in analitos
        ],
    )


def test_detecta_el_analito_inventado():
    assert hallazgos_fabricados(_resultado("Potasio (K+)"), _peticion()) == ["Potasio (K+)"]


def test_no_marca_los_analitos_enviados():
    # Variantes de nombre que el modelo usa de verdad.
    r = _resultado("Calcio", "Fósforo (P)", "calc")
    assert hallazgos_fabricados(r, _peticion()) == []


def test_descarta_solo_lo_inventado_y_conserva_lo_real():
    r = descartar_fabricados(_resultado("Calcio", "Potasio (K+)"), _peticion())
    assert [h.analito for h in r.hallazgos_clave] == ["Calcio"]


def test_no_toca_la_prosa():
    r = _resultado("Potasio (K+)")
    prosa = r.interpretacion
    assert descartar_fabricados(r, _peticion()).interpretacion == prosa


def test_sin_hallazgos_enviados_no_se_descarta_nada():
    """Un panel normal no aporta términos conocidos: mejor no borrar que borrar a ciegas."""
    pet = PeticionInterpretacion(paciente={"especie": "canino"})
    r = _resultado("Glucosa")
    assert hallazgos_fabricados(r, pet) == []
