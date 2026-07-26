"""Pruebas de la API de laboratorio: auth de dispositivo, ingesta, y consulta por sesión."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import obtener_config
from app.main import app

PAYLOAD = {
    "muestra_id": "ABC-123",
    "instrumento_id": "vetscan-1",
    "fabricante": "Abaxis",
    "observaciones": [
        {"codigo_prueba": "GLU", "valor": "5.0", "unidad": "mmol/L"},
        {"codigo_prueba": "CREA", "valor": "1.2", "unidad": "mg/dL"},
    ],
    "momento": "2026-07-25T10:00:00Z",
}


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def _con_sesion(cliente, email="lab@example.com"):
    reg = cliente.post(
        "/api/auth/registro",
        json={"nombre": "Lab", "apellido": "Vet", "email": email, "password": "clave-segura-1"},
    )
    assert reg.status_code == 200, reg.text
    return reg.json()["csrf"]


def test_ingesta_sin_keys_configuradas_es_503(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "lab_api_keys", [])
    r = cliente.post("/api/lab/ingesta", json=PAYLOAD, headers={"Authorization": "Bearer x"})
    assert r.status_code == 503


def test_ingesta_sin_bearer_es_401(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "lab_api_keys", ["k-secreta"])
    r = cliente.post("/api/lab/ingesta", json=PAYLOAD)
    assert r.status_code == 401


def test_ingesta_bearer_erroneo_es_401(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "lab_api_keys", ["k-secreta"])
    r = cliente.post("/api/lab/ingesta", json=PAYLOAD, headers={"Authorization": "Bearer mala"})
    assert r.status_code == 401


def test_ingesta_y_consulta_completa(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "lab_api_keys", ["k-secreta"])

    # Ingesta con key válida.
    r = cliente.post("/api/lab/ingesta", json=PAYLOAD, headers={"Authorization": "Bearer k-secreta"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["muestra_id"] == "ABC-123"
    assert cuerpo["analitos_mapeados"] == 2
    assert cuerpo["no_mapeados"] == []

    # Consulta sin sesión → 401.
    sin_sesion = cliente.get("/api/lab/resultados", params={"muestra": "ABC-123"})
    assert sin_sesion.status_code == 401

    # Con sesión → 200 y analitos mapeados (match case-insensitive del ID).
    _con_sesion(cliente)
    q = cliente.get("/api/lab/resultados", params={"muestra": "abc-123"})
    assert q.status_code == 200, q.text
    analitos = q.json()["analitos"]
    assert "gluc" in analitos and "creat" in analitos
    assert analitos["gluc"]["valor"] == round(5.0 * 18.016, 4)

    # Muestra desconocida → 404.
    nope = cliente.get("/api/lab/resultados", params={"muestra": "NO-EXISTE"})
    assert nope.status_code == 404


def test_ingesta_rechaza_observaciones_vacias(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "lab_api_keys", ["k-secreta"])
    payload = {**PAYLOAD, "observaciones": []}
    r = cliente.post("/api/lab/ingesta", json=payload, headers={"Authorization": "Bearer k-secreta"})
    assert r.status_code == 422


def test_pendientes_requiere_sesion(cliente):
    assert cliente.get("/api/lab/pendientes").status_code == 401


def test_pendientes_lista_mas_reciente_primero(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "lab_api_keys", ["k-secreta"])
    for muestra in ("PEND-1", "PEND-2"):
        cliente.post(
            "/api/lab/ingesta",
            json={**PAYLOAD, "muestra_id": muestra},
            headers={"Authorization": "Bearer k-secreta"},
        )
    _con_sesion(cliente, email="pend@example.com")
    r = cliente.get("/api/lab/pendientes")
    assert r.status_code == 200
    ids = [x["muestra_id"] for x in r.json()]
    assert "PEND-1" in ids and "PEND-2" in ids
    assert ids.index("PEND-2") < ids.index("PEND-1")  # el último ingerido, primero


def test_persistencia_escribe_en_db(cliente, monkeypatch):
    from app import db

    monkeypatch.setattr(obtener_config(), "lab_api_keys", ["k-secreta"])
    monkeypatch.setattr(obtener_config(), "lab_persistir", True)
    r = cliente.post(
        "/api/lab/ingesta",
        json={**PAYLOAD, "muestra_id": "PERSIST-1"},
        headers={"Authorization": "Bearer k-secreta"},
    )
    assert r.status_code == 200
    assert any("PERSIST-1" in p for p in db.cargar_resultados_lab())
