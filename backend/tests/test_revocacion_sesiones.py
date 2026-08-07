"""Revocación de sesiones (ARCHITECTURE_REVIEW §2.3).

Las sesiones son cookies firmadas sin estado, y el logout se limitaba a borrar la cookie del
navegador: el token seguía siendo VÁLIDO allá donde se hubiera copiado, hasta
`session_max_age_s` (8h). No había forma de invalidar una sesión filtrada, ni de echar a nadie
tras un incidente, salvo rotar `MORPHOS_SESSION_SECRET` y tirar a todos los usuarios a la vez.

La prueba que importa no es «logout devuelve 200», sino que **la cookie de antes ya no sirve**.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def _alta(cliente, email):
    r = cliente.post(
        "/api/auth/registro",
        json={"nombre": "V", "apellido": "Vet", "email": email, "password": "clave-segura-1"},
    )
    if r.status_code == 409:
        r = cliente.post("/api/auth/login", json={"email": email, "password": "clave-segura-1"})
    assert r.status_code == 200, r.text
    return r


def test_la_cookie_deja_de_valer_tras_el_logout(cliente, alta_abierta):
    """El agujero concreto: una copia de la cookie sobrevivía al «cerrar sesión»."""
    _alta(cliente, "rev1@example.com")
    galleta = cliente.cookies.get("morphos_sesion")
    assert cliente.get("/api/auth").json()["autenticado"] is True

    cliente.post("/api/auth/logout")

    # Se reenvía la cookie a mano, como haría quien la hubiera copiado.
    r = cliente.get("/api/lab/pendientes", cookies={"morphos_sesion": galleta})
    assert r.status_code == 401


def test_logout_todas_corta_las_demas_sesiones(cliente, alta_abierta):
    """«Me han robado el portátil»: cierra las sesiones abiertas en otros dispositivos."""
    _alta(cliente, "rev2@example.com")
    portatil = cliente.cookies.get("morphos_sesion")

    # Segunda sesión (otro dispositivo) para la misma cuenta.
    otro = TestClient(app)
    r = otro.post("/api/auth/login", json={"email": "rev2@example.com", "password": "clave-segura-1"})
    assert r.status_code == 200

    otro.post("/api/auth/logout-todas")

    r = cliente.get("/api/lab/pendientes", cookies={"morphos_sesion": portatil})
    assert r.status_code == 401, "la sesión del otro dispositivo siguió viva"


def test_revocar_una_no_afecta_a_las_de_otras_cuentas(cliente, alta_abierta):
    """Aislar el corte: revocar no puede convertirse en una denegación de servicio ajena."""
    _alta(cliente, "rev3@example.com")
    ajena = TestClient(app)
    _alta(ajena, "rev4@example.com")

    cliente.post("/api/auth/logout-todas")

    assert ajena.get("/api/auth").json()["autenticado"] is True


def test_una_sesion_nueva_tras_el_corte_si_vale(cliente, alta_abierta):
    """El corte es por fecha de emisión: volver a entrar tiene que funcionar."""
    _alta(cliente, "rev5@example.com")
    cliente.post("/api/auth/logout-todas")

    r = cliente.post(
        "/api/auth/login", json={"email": "rev5@example.com", "password": "clave-segura-1"}
    )
    assert r.status_code == 200
    assert cliente.get("/api/auth").json()["autenticado"] is True


def test_el_logout_borra_las_cookies_con_sus_atributos(cliente, alta_abierta):
    """`delete_cookie()` a secas emite un Set-Cookie sin samesite/path y algunos navegadores lo
    tratan como una cookie distinta: la sesión se quedaba en el navegador."""
    _alta(cliente, "rev6@example.com")
    r = cliente.post("/api/auth/logout")

    borrados = [v for v in r.headers.get_list("set-cookie") if "morphos_sesion" in v]
    assert borrados, "el logout no intentó borrar la cookie de sesión"
    assert "Path=/" in borrados[0]
    assert "samesite=strict" in borrados[0].lower()
