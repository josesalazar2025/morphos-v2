"""Parámetros de scrypt versionados y migración del hash (ARCHITECTURE_REVIEW §2.7, 2ª mitad).

El formato antiguo era `scrypt$sal$hash`: n/r/p vivían SÓLO en el código. Con eso, subir el coste
—lo normal a medida que el hardware mejora— habría invalidado en bloque todas las contraseñas
existentes, porque el mismo `verificar_password` que las comprueba habría empezado a derivar con
otra n. Y ni siquiera se podía detectar cuáles estaban al coste viejo, así que tampoco había un
camino gradual.

El formato pasa a `scrypt$n$r$p$sal$hash` y cada hash se verifica con LOS SUYOS. Lo que estas
pruebas fijan es lo que hace utilizable el mecanismo:

1. Los hashes antiguos siguen entrando (si no, esto es un corte de servicio, no una migración).
2. Subir el coste no echa a nadie.
3. El parque converge: cada login correcto pone el hash al día, y sólo el correcto.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

_PASSWORD = "clave-segura-1"


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def _hash_antiguo(password: str) -> str:
    """Reproduce EXACTAMENTE el formato que se guardaba antes de este cambio."""
    import hashlib
    import secrets

    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=sal, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${sal.hex()}${dk.hex()}"


def _alta(cliente, email: str):
    r = cliente.post(
        "/api/auth/registro",
        json={"nombre": "V", "apellido": "Vet", "email": email, "password": _PASSWORD},
    )
    assert r.status_code == 200, r.text
    cliente.cookies.clear()


def _password_guardada(email: str) -> str:
    return db.buscar_usuario(email)["password"]


# --- Formato ---------------------------------------------------------------------------------

def test_el_hash_nuevo_declara_sus_parametros():
    almacenado = db.hash_password(_PASSWORD)

    algo, n, r, p, sal, _ = almacenado.split("$")
    assert (algo, int(n), int(r), int(p)) == ("scrypt", db._SCRYPT["n"], db._SCRYPT["r"], db._SCRYPT["p"])
    assert len(bytes.fromhex(sal)) == 16, "cada contraseña con su sal"


def test_los_hashes_antiguos_siguen_valiendo():
    """Sin esto la 'migración' sería un corte de servicio: todos fuera a la vez."""
    almacenado = _hash_antiguo(_PASSWORD)

    assert db.verificar_password(_PASSWORD, almacenado) is True
    assert db.verificar_password("otra-cosa", almacenado) is False


def test_ida_y_vuelta_del_formato_nuevo():
    almacenado = db.hash_password(_PASSWORD)

    assert db.verificar_password(_PASSWORD, almacenado) is True
    assert db.verificar_password("otra-cosa", almacenado) is False


@pytest.mark.parametrize(
    "almacenado",
    [
        "",
        "no-es-un-hash",
        "bcrypt$1$2$3$aa$bb",
        "scrypt$aa",
        "scrypt$1$2$3$4$5$6",
        "scrypt$no-numero$8$1$aa$bb",
        "scrypt$16384$8$1$zz$bb",  # sal que no es hex
    ],
)
def test_un_hash_ilegible_no_valida_ni_revienta(almacenado):
    assert db.verificar_password(_PASSWORD, almacenado) is False
    assert db.necesita_rehash(almacenado) is False


def test_una_n_absurda_se_rechaza_en_vez_de_agotar_la_memoria():
    """`hashlib.scrypt` reserva del orden de 128·n·r bytes: una fila manipulada con n gigante
    convertiría un intento de login en un OOM del proceso entero."""
    almacenado = f"scrypt${2**40}$8$1${'aa' * 16}${'bb' * 32}"

    assert db.verificar_password(_PASSWORD, almacenado) is False


# --- Detección de hashes desactualizados -----------------------------------------------------

def test_el_formato_antiguo_pide_migracion_aunque_el_coste_coincida():
    """Hoy los parámetros heredados son los vigentes, así que sólo el FORMATO los distingue.

    Se migra igual: interesa que el parque converja al formato autodescriptivo antes de que
    alguien suba la n, no a la vez.
    """
    assert db._SCRYPT_HEREDADO == db._SCRYPT, "si esto cambia, revisa el motivo de esta prueba"

    assert db.necesita_rehash(_hash_antiguo(_PASSWORD)) is True


def test_un_hash_al_dia_no_pide_migracion():
    assert db.necesita_rehash(db.hash_password(_PASSWORD)) is False


def test_subir_el_coste_marca_los_hashes_viejos(monkeypatch):
    almacenado = db.hash_password(_PASSWORD)
    assert db.necesita_rehash(almacenado) is False

    monkeypatch.setitem(db._SCRYPT, "n", 2**15)

    assert db.necesita_rehash(almacenado) is True
    # Y lo que de verdad importa: el usuario sigue pudiendo entrar mientras tanto.
    assert db.verificar_password(_PASSWORD, almacenado) is True


# --- Migración de verdad, por el endpoint ----------------------------------------------------

def test_el_login_pone_al_dia_un_hash_antiguo(cliente, alta_abierta):
    """El caso completo: cuenta con hash viejo, login correcto, hash nuevo en la BD."""
    email = "migra-antiguo@example.com"
    _alta(cliente, email)
    with db._conexion() as con:
        con.execute("UPDATE usuarios SET password = ? WHERE email = ?", (_hash_antiguo(_PASSWORD), email))
    assert _password_guardada(email).count("$") == 2

    r = cliente.post("/api/auth/login", json={"email": email, "password": _PASSWORD})

    assert r.status_code == 200, r.text
    migrado = _password_guardada(email)
    assert migrado.count("$") == 5, "el login no migró el hash"
    assert db.necesita_rehash(migrado) is False
    # La contraseña del usuario no ha cambiado: sigue siendo la suya.
    assert db.verificar_password(_PASSWORD, migrado) is True


def test_un_login_fallido_no_toca_el_hash(cliente, alta_abierta):
    """Sólo el login CORRECTO migra: es el único que prueba conocer la contraseña."""
    email = "migra-fallido@example.com"
    _alta(cliente, email)
    antiguo = _hash_antiguo(_PASSWORD)
    with db._conexion() as con:
        con.execute("UPDATE usuarios SET password = ? WHERE email = ?", (antiguo, email))

    r = cliente.post("/api/auth/login", json={"email": email, "password": "incorrecta"})

    assert r.status_code == 401
    assert _password_guardada(email) == antiguo


def test_un_login_ya_al_dia_no_reescribe_nada(cliente, alta_abierta):
    """Un UPDATE por login sería escritura gratis en cada entrada de cada usuario."""
    email = "migra-aldia@example.com"
    _alta(cliente, email)
    antes = _password_guardada(email)

    r = cliente.post("/api/auth/login", json={"email": email, "password": _PASSWORD})

    assert r.status_code == 200
    assert _password_guardada(email) == antes
