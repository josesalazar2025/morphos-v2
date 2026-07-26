"""Pruebas del constructor de prompt y la degradación sin-RAG del recuperador."""

from __future__ import annotations

from app.ai.prompt import SISTEMA, construir_mensaje_usuario
from app.rag.retriever import Fragmento, construir_consulta
from app.schemas import PeticionInterpretacion


def _peticion():
    return PeticionInterpretacion(
        paciente={"especie": "canino", "raza": "Labrador", "edad_meses": 96, "sexo": "Macho"},
        hallazgos=[
            {"clave": "hct", "nombre": "Hematocrito", "valor": 25, "unidad": "%", "direccion": "bajo", "gravedad": "moderado"},
        ],
        patrones=[
            {"nombre": "Anemia microcítica", "descripcion": "Parámetros eritrocitarios disminuidos.", "gravedad": "moderado", "parametros": ["hct"]},
        ],
        signos_clinicos="Letargia y mucosas pálidas",
    )


def test_sistema_exige_espanol_y_derivacion():
    assert "español" in SISTEMA.lower()
    assert "requiere_derivacion" in SISTEMA


def test_mensaje_incluye_paciente_hallazgos_y_patrones():
    msg = construir_mensaje_usuario(_peticion(), [])
    assert "canino" in msg
    assert "Hematocrito" in msg
    assert "Anemia microcítica" in msg
    assert "Letargia" in msg


def test_mensaje_incluye_bloque_rag_con_cita():
    frag = Fragmento(
        texto="La anemia ferropénica cursa con microcitosis e hipocromía.",
        libro="Thrall Veterinary Hematology", edicion="3.ª ed.", capitulo="Anemia", pagina="210", score=0.1,
    )
    msg = construir_mensaje_usuario(_peticion(), [frag])
    assert "Literatura recuperada" in msg
    assert "Thrall" in msg and "p. 210" in msg


def test_construir_consulta_combina_terminos():
    q = construir_consulta(["Anemia microcítica"], ["Hematocrito"])
    assert "Anemia microcítica" in q and "Hematocrito" in q


def test_recuperar_degrada_sin_indice(monkeypatch):
    # Contrato de degradación: sin recursos RAG (deps ausentes o índice no construido),
    # recuperar devuelve [] sin lanzar. Se fuerza vía monkeypatch para no depender de si
    # existe un índice real en el entorno de pruebas.
    import app.rag.retriever as R

    monkeypatch.setattr(R, "_cargar_recursos", lambda: None)
    assert R.recuperar("anemia ferropénica", especie="canino") == []
