"""El alta de cuentas está cerrada por defecto y sólo la abre una allowlist de emails.

Por qué importa: una cuenta alcanza `/api/interpret`, que gasta cuota de ZeroGPU compartida y,
por la ruta Claude, dinero real. Mientras el alta fue abierta, el techo por usuario
(`limite_interpret_usuario`) protegía una identidad que costaba una petición HTTP acuñar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import obtener_config
from app.main import app

ALTA = {"nombre": "Ana", "apellido": "Vet", "password": "clave-segura-1"}


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def _alta(cliente, email):
    return cliente.post("/api/auth/registro", json={**ALTA, "email": email})


def test_alta_cerrada_por_defecto(cliente):
    """Sin tocar nada: el defecto del servicio rechaza el alta."""
    r = _alta(cliente, "desconocida@example.com")
    assert r.status_code == 403
    assert "restringida" in r.text


def test_email_en_la_allowlist_puede_darse_de_alta(cliente, monkeypatch):
    monkeypatch.setattr(obtener_config(), "registro_allowlist", ["permitida@example.com"])
    r = _alta(cliente, "permitida@example.com")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_allowlist_ignora_mayusculas_y_espacios(cliente, monkeypatch):
    """El email entra por un formulario; comparar crudo dejaría fuera a un aprobado."""
    monkeypatch.setattr(obtener_config(), "registro_allowlist", ["  Mixta@Example.COM "])
    assert _alta(cliente, "mixta@example.com").status_code == 200


def test_fuera_de_la_allowlist_no_revela_si_la_cuenta_existe(cliente, monkeypatch):
    """403 tanto si la cuenta existe como si no: el alta no puede ser un oráculo de cuentas.

    Si la comprobación de allowlist fuera DESPUÉS de la de existencia, un email no aprobado
    distinguiría 409 (existe) de 403 (no existe) y enumeraría la base de usuarios.
    """
    monkeypatch.setattr(obtener_config(), "registro_allowlist", ["existente@example.com"])
    assert _alta(cliente, "existente@example.com").status_code == 200  # ya existe a partir de aquí

    monkeypatch.setattr(obtener_config(), "registro_allowlist", [])
    existente = _alta(cliente, "existente@example.com")
    inexistente = _alta(cliente, "jamas-vista@example.com")
    assert existente.status_code == 403
    assert inexistente.status_code == 403
    assert existente.text == inexistente.text


def test_registro_abierto_deja_pasar_a_cualquiera(cliente, monkeypatch):
    """La vía de escape para desarrollo local sigue funcionando."""
    monkeypatch.setattr(obtener_config(), "registro_abierto", True)
    assert _alta(cliente, "cualquiera@example.com").status_code == 200


def test_allowlist_admite_cadena_separada_por_comas(monkeypatch):
    """Forma documentada en .env.example; la de lista JSON ya la cubre el validador compartido."""
    from app.config import Configuracion

    cfg = Configuracion(registro_allowlist="uno@example.com, dos@example.com")
    assert cfg.emails_registro_permitidos() == {"uno@example.com", "dos@example.com"}
    assert cfg.registro_permitido("dos@example.com")
    assert not cfg.registro_permitido("tres@example.com")
