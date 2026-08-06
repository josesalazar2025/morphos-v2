"""Aislamiento por clínica de los resultados de analizador (ARCHITECTURE_REVIEW §2.1).

El almacén era un dict global sin dueño: cualquier sesión autenticada podía leer la muestra de
cualquier clínica, y `/api/lab/pendientes` enumeraba TODAS. Cada `muestra_id` abre en
`/api/lab/resultados` el panel completo más las pistas de paciente (nombre de la mascota, raza,
sexo), así que el aislamiento es lo único que separa a una clínica de los datos de otra.

Dos cosas que estas pruebas fijan y no pueden relajarse: el tenant lo pone el SERVIDOR (de la API
key en la ingesta, de la cookie firmada en la lectura) y una muestra de otra clínica se comporta
como inexistente, no como prohibida.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import TENANT_POR_DEFECTO, obtener_config
from app.lab.almacen import almacen
from app.main import app

CLAVE_A = "clave-de-la-clinica-a"
CLAVE_B = "clave-de-la-clinica-b"

PAYLOAD = {
    "muestra_id": "M-1",
    "instrumento_id": "vetscan-1",
    "fabricante": "Abaxis",
    "observaciones": [{"codigo_prueba": "GLU", "valor": "5.0", "unidad": "mmol/L"}],
    "momento": "2026-07-25T10:00:00Z",
}


@pytest.fixture
def cliente():
    almacen._datos.clear()
    with TestClient(app) as c:
        yield c
    almacen._datos.clear()


@pytest.fixture
def dos_clinicas(monkeypatch):
    """Dos dispositivos y dos cuentas, cada uno en su clínica."""
    cfg = obtener_config()
    monkeypatch.setattr(cfg, "lab_api_keys", [f"clinica-a:{CLAVE_A}", f"clinica-b:{CLAVE_B}"])
    monkeypatch.setattr(
        cfg, "registro_allowlist", ["a@example.com=clinica-a", "b@example.com=clinica-b"]
    )
    monkeypatch.setattr(cfg, "lab_pendientes_habilitado", True)


def _ingerir(cliente, clave, muestra):
    return cliente.post(
        "/api/lab/ingesta",
        json={**PAYLOAD, "muestra_id": muestra},
        headers={"Authorization": f"Bearer {clave}"},
    )


def _sesion(cliente, email):
    """Sesión para ese email. La BD de pruebas se comparte, así que si la cuenta ya existe de
    otra prueba se entra en vez de darla de alta (el tenant quedó fijado al crearla)."""
    r = cliente.post(
        "/api/auth/registro",
        json={"nombre": "V", "apellido": "Vet", "email": email, "password": "clave-segura-1"},
    )
    if r.status_code == 409:
        r = cliente.post(
            "/api/auth/login", json={"email": email, "password": "clave-segura-1"}
        )
    assert r.status_code == 200, r.text
    return r


def test_una_clinica_no_ve_la_muestra_de_otra(cliente, dos_clinicas):
    """El hallazgo central de §2.1: cualquier sesión leía cualquier muestra."""
    assert _ingerir(cliente, CLAVE_A, "M-DE-A").status_code == 200

    _sesion(cliente, "b@example.com")
    r = cliente.get("/api/lab/resultados", params={"muestra": "M-DE-A"})

    # 404 y no 403: existir o no en otra clínica tampoco es información que se dé.
    assert r.status_code == 404


def test_la_propia_clinica_si_la_ve(cliente, dos_clinicas):
    """El complemento obligatorio: aislar no puede romper el caso legítimo."""
    assert _ingerir(cliente, CLAVE_A, "M-DE-A").status_code == 200

    _sesion(cliente, "a@example.com")
    r = cliente.get("/api/lab/resultados", params={"muestra": "M-DE-A"})

    assert r.status_code == 200
    assert r.json()["muestra_id"] == "M-DE-A"


def test_pendientes_solo_enumera_lo_propio(cliente, dos_clinicas):
    """`pendientes` era el volcado en una petición: ahora sólo lista la clínica de la sesión."""
    _ingerir(cliente, CLAVE_A, "M-DE-A")
    _ingerir(cliente, CLAVE_B, "M-DE-B")

    _sesion(cliente, "b@example.com")
    r = cliente.get("/api/lab/pendientes")

    assert r.status_code == 200
    ids = [x["muestra_id"] for x in r.json()]
    assert ids == ["M-DE-B"]


def test_el_puente_no_puede_declarar_su_clinica(cliente, dos_clinicas):
    """El tenant sale de la API key; si viniera del cuerpo, mentir bastaría para escribir en otra."""
    r = cliente.post(
        "/api/lab/ingesta",
        json={**PAYLOAD, "muestra_id": "M-MENTIRA", "tenant": "clinica-b"},
        headers={"Authorization": f"Bearer {CLAVE_A}"},
    )
    assert r.status_code == 200

    _sesion(cliente, "b@example.com")
    assert cliente.get("/api/lab/resultados", params={"muestra": "M-MENTIRA"}).status_code == 404


def test_clave_sin_clinica_declarada_cae_en_la_de_por_defecto(cliente, monkeypatch):
    """Compatibilidad: un despliegue de una sola clínica no declara tenants y sigue funcionando."""
    cfg = obtener_config()
    monkeypatch.setattr(cfg, "lab_api_keys", ["clave-suelta"])
    monkeypatch.setattr(cfg, "registro_abierto", True)
    monkeypatch.setattr(cfg, "lab_pendientes_habilitado", True)

    assert _ingerir(cliente, "clave-suelta", "M-SUELTA").status_code == 200
    _sesion(cliente, "suelto@example.com")

    r = cliente.get("/api/lab/resultados", params={"muestra": "M-SUELTA"})
    assert r.status_code == 200
    assert r.json()["tenant"] == TENANT_POR_DEFECTO


def test_clave_invalida_sigue_siendo_401(cliente, dos_clinicas):
    assert _ingerir(cliente, "no-es-una-clave", "M-X").status_code == 401


def test_el_tenant_de_la_clave_se_resuelve_bien():
    """Unidad sobre el parseo `tenant:clave`, que es lo que sostiene todo lo anterior."""
    cfg = obtener_config().model_copy(
        update={"lab_api_keys": ["clinica-a:secreta-a", "suelta-sin-tenant"]}
    )
    assert cfg.tenant_de_clave_dispositivo("secreta-a") == "clinica-a"
    assert cfg.tenant_de_clave_dispositivo("suelta-sin-tenant") == TENANT_POR_DEFECTO
    assert cfg.tenant_de_clave_dispositivo("clinica-a") is None  # el prefijo no es la clave
    assert cfg.tenant_de_clave_dispositivo("") is None
