"""Pruebas de la API: guarda de autenticación, flujo de sesión y cabeceras de seguridad.

Verifican en concreto los arreglos del audit: /api/interpret ya NO es anónimo, la sesión
emite CSRF, y las cabeceras de seguridad se aplican.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import InterpretacionClinica, RespuestaInterpretacion


@pytest.fixture
def cliente():
    # El context manager dispara el lifespan (inicializa la BD).
    with TestClient(app) as c:
        yield c


def test_health(cliente):
    r = cliente.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_interpret_requiere_sesion(cliente):
    r = cliente.post("/api/interpret", json={"paciente": {"especie": "canino"}})
    assert r.status_code == 401


def test_cabeceras_seguridad_presentes(cliente):
    r = cliente.get("/api/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_flujo_registro_login_e_interpret(cliente, monkeypatch):
    # Registro emite sesión + CSRF.
    reg = cliente.post(
        "/api/auth/registro",
        json={"nombre": "Ana", "apellido": "Vet", "email": "ana@example.com", "password": "clave-segura-1"},
    )
    assert reg.status_code == 200
    csrf = reg.json()["csrf"]
    assert cliente.cookies.get("morphos_sesion")

    # Estado autenticado.
    est = cliente.get("/api/auth")
    assert est.json()["autenticado"] is True

    # Monkeypatch del servicio de IA para no depender de un modelo real.
    async def _fake_interpretar(pet):
        return RespuestaInterpretacion(
            resultado=InterpretacionClinica(interpretacion="Interpretación de prueba."),
            modelo="fake:test",
            fuentes_rag=0,
        )

    monkeypatch.setattr("app.routers.interpret.interpretar", _fake_interpretar)

    # Sin CSRF → 403.
    sin_csrf = cliente.post("/api/interpret", json={"paciente": {"especie": "canino"}})
    assert sin_csrf.status_code == 403

    # Con CSRF → 200 y salida estructurada.
    ok = cliente.post(
        "/api/interpret",
        json={"paciente": {"especie": "canino"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["resultado"]["idioma"] == "es"


def test_modelos_requiere_sesion(cliente):
    """La lista de modelos describe la configuración del servidor: no es pública."""
    assert cliente.get("/api/modelos").status_code == 401


def test_interpret_rechaza_modelo_fuera_de_la_lista_blanca(cliente):
    """422 (error del cliente) y no 502: la petición es inválida, el modelo ni se llama."""
    reg = cliente.post(
        "/api/auth/registro",
        json={"nombre": "Leo", "apellido": "Vet", "email": "leo@example.com", "password": "clave-segura-1"},
    )
    csrf = reg.json()["csrf"]

    assert cliente.get("/api/modelos").json()["locales"] == []  # nada declarado por defecto

    r = cliente.post(
        "/api/interpret",
        json={"paciente": {"especie": "canino"}, "modelo_local": "llama3:70b"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 422, r.text
    assert "no permitido" in r.text


def test_registro_rechaza_password_corta(cliente):
    r = cliente.post(
        "/api/auth/registro",
        json={"nombre": "B", "apellido": "C", "email": "b@example.com", "password": "corta"},
    )
    assert r.status_code == 422
