"""Enumeración de cuentas por tiempo en el login (ARCHITECTURE_REVIEW §2.7).

El mensaje de error del login SIEMPRE fue genérico («Email o contraseña incorrectos»), pero el
reloj lo desmentía: si el email no existía en la BD no se derivaba ningún hash y la respuesta
salía en sub-milisegundo, mientras que un email existente pagaba scrypt (n=2**14, decenas de ms).
Medir esa diferencia desde fuera es trivial, así que el 401 genérico no ocultaba nada.

Importa más de lo normal aquí porque el alta está CERRADA con lista blanca
(`registro_allowlist`, §2.2): la lista de emails válidos ES el control de admisión, y un oráculo
que la revele es el primer paso para atacarla.

La prueba de referencia NO es la del cronómetro —un runner de CI compartido mide lo que quiere—
sino la determinista: comprobar que la rama del email inexistente ejecuta scrypt, y con los
MISMOS parámetros. El cronómetro va después, con margen ancho, sólo como comprobación de humo.
"""

from __future__ import annotations

import hashlib
import statistics
import time

import pytest
from fastapi.testclient import TestClient

from app.db import _SCRYPT, hash_password, simular_verificacion_password, verificar_password
from app.main import app

_PASSWORD = "clave-segura-1"
_EXISTE = "timing-existe@example.com"
_NO_EXISTE = "timing-no-existe@example.com"


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def usuario(cliente, alta_abierta):
    """Deja creada la cuenta `_EXISTE` y devuelve el cliente sin sesión."""
    r = cliente.post(
        "/api/auth/registro",
        json={"nombre": "V", "apellido": "Vet", "email": _EXISTE, "password": _PASSWORD},
    )
    assert r.status_code in (200, 409), r.text
    cliente.cookies.clear()
    return cliente


def _espiar_scrypt(monkeypatch) -> list[dict]:
    """Registra cada llamada a scrypt con sus parámetros de coste."""
    llamadas: list[dict] = []
    original = hashlib.scrypt

    def espia(password, *, salt, n, r, p, dklen, **resto):
        llamadas.append({"n": n, "r": r, "p": p, "dklen": dklen})
        return original(password, salt=salt, n=n, r=r, p=p, dklen=dklen, **resto)

    monkeypatch.setattr(hashlib, "scrypt", espia)
    return llamadas


def test_el_login_deriva_un_hash_aunque_el_email_no_exista(usuario, monkeypatch):
    """El corazón del arreglo: la rama del email inexistente ya no sale gratis."""
    llamadas = _espiar_scrypt(monkeypatch)

    r = usuario.post("/api/auth/login", json={"email": _NO_EXISTE, "password": _PASSWORD})

    assert r.status_code == 401
    assert len(llamadas) == 1, "sin hash señuelo, la rama inexistente no ejecuta scrypt"


def test_las_dos_ramas_usan_los_mismos_parametros_de_coste(usuario, monkeypatch):
    """Un señuelo más barato que el hash real reabre el agujero sin que nada falle."""
    llamadas = _espiar_scrypt(monkeypatch)

    usuario.post("/api/auth/login", json={"email": _EXISTE, "password": "incorrecta"})
    usuario.post("/api/auth/login", json={"email": _NO_EXISTE, "password": "incorrecta"})

    assert len(llamadas) == 2
    assert llamadas[0] == llamadas[1] == _SCRYPT


def test_la_respuesta_es_indistinguible(usuario):
    """Lo que ya estaba bien y no debe romperse al tocar la rama: mismo código y mismo cuerpo."""
    a = usuario.post("/api/auth/login", json={"email": _EXISTE, "password": "incorrecta"})
    b = usuario.post("/api/auth/login", json={"email": _NO_EXISTE, "password": "incorrecta"})

    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_el_senuelo_nunca_acierta():
    """Es un hash real de una contraseña aleatoria que se descarta: nada puede validarlo."""
    for intento in ("", _PASSWORD, "a" * 200, "scrypt$$"):
        assert simular_verificacion_password(intento) is False


def test_las_dos_ramas_tardan_parecido():
    """Comprobación de humo con margen ancho.

    Se cronometran las dos FUNCIONES, no el endpoint: por HTTP la medida no vale nada aquí,
    porque el rate limit (5/minute) y el throttle por email+IP cortan antes de llegar al hash y
    devuelven en sub-milisegundo, que es justo la señal que se quiere medir. El cableado del
    endpoint ya lo cubren las pruebas deterministas de arriba.

    No se afirma que los tiempos sean iguales —eso no se mide en un runner compartido— sino que
    la rama inexistente ya no es un orden de magnitud más rápida, que era el estado anterior
    (sub-milisegundo frente a decenas de ms). Medianas, para que un pico del planificador no
    tumbe la suite, y umbral en la mitad, que deja sitio de sobra al ruido.
    """
    real = hash_password(_PASSWORD)

    def medir(fn) -> float:
        return statistics.median(
            [_cronometrar(fn) for _ in range(5)],
        )

    con_usuario = medir(lambda: verificar_password("incorrecta", real))
    sin_usuario = medir(lambda: simular_verificacion_password("incorrecta"))

    assert sin_usuario > con_usuario * 0.5, (
        f"la rama del email inexistente sigue siendo mucho más rápida "
        f"({sin_usuario * 1000:.1f} ms vs {con_usuario * 1000:.1f} ms)"
    )


def _cronometrar(fn) -> float:
    inicio = time.perf_counter()
    fn()
    return time.perf_counter() - inicio
