"""Versionado del esquema de la BD de usuarios.

Antes era un único `CREATE TABLE IF NOT EXISTS`: creaba el esquema en una BD vacía y no hacía
NADA sobre una existente. Añadir una columna era una operación manual sobre un fichero al que,
en HF Spaces, nadie puede llegar.

Lo que hay que sostener: los pasos se aplican una sola vez, se aplican en orden, y una BD creada
ANTES de este mecanismo (versión 0 con las tablas del paso 1 ya dentro) se pone al día sin
romperse. Ese último es el caso real de la instancia desplegada.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import db


@pytest.fixture
def bd(tmp_path, monkeypatch):
    """BD temporal aislada de la del resto de la suite."""
    ruta = tmp_path / "prueba.db"
    monkeypatch.setattr(db.obtener_config(), "db_path", ruta)
    return ruta


def _version(ruta) -> int:
    con = sqlite3.connect(ruta)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


def _tablas(ruta) -> set[str]:
    con = sqlite3.connect(ruta)
    try:
        filas = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {f[0] for f in filas}
    finally:
        con.close()


def test_bd_nueva_queda_en_la_ultima_version(bd):
    db.inicializar_db()
    assert _version(bd) == len(db._MIGRACIONES)
    assert {"usuarios", "intentos_login", "resultados_lab"} <= _tablas(bd)


def test_reejecutar_es_idempotente(bd):
    """Arrancar dos veces no debe reaplicar nada ni fallar."""
    db.inicializar_db()
    db.inicializar_db()
    assert _version(bd) == len(db._MIGRACIONES)


def test_bd_anterior_al_versionado_se_pone_al_dia(bd):
    """El caso real: tablas del paso 1 ya presentes y `user_version` en 0.

    Si los pasos no fueran reejecutables sobre lo ya existente, esto reventaría con
    «table usuarios already exists» y la app no arrancaría contra la BD desplegada.
    """
    con = sqlite3.connect(bd)
    con.executescript(db._MIGRACIONES[0])  # esquema viejo, sin tocar user_version
    con.commit()
    con.close()
    assert _version(bd) == 0

    db.inicializar_db()

    assert _version(bd) == len(db._MIGRACIONES)
    assert {"usuarios", "intentos_login", "resultados_lab"} <= _tablas(bd)


def test_los_datos_sobreviven_a_la_migracion(bd):
    """Migrar no puede perder cuentas: es exactamente lo que se está intentando dejar de hacer."""
    con = sqlite3.connect(bd)
    con.executescript(db._MIGRACIONES[0])
    con.execute(
        "INSERT INTO usuarios (nombre, apellido, email, password) VALUES (?,?,?,?)",
        ("Ana", "Vet", "ana@example.com", "scrypt$x$y"),
    )
    con.commit()
    con.close()

    db.inicializar_db()

    assert db.buscar_usuario("ana@example.com") is not None


def test_se_aplica_un_paso_nuevo_sobre_una_bd_ya_migrada(bd, monkeypatch):
    """Comprueba el mecanismo, no un paso concreto: sin esto, sólo se probaría el estado final."""
    db.inicializar_db()
    ya = len(db._MIGRACIONES)

    monkeypatch.setattr(
        db, "_MIGRACIONES", [*db._MIGRACIONES, "CREATE TABLE IF NOT EXISTS futura (x INTEGER);"]
    )
    db.inicializar_db()

    assert _version(bd) == ya + 1
    assert "futura" in _tablas(bd)


def test_el_indice_del_throttle_existe(bd):
    """Paso 2: `intentos_recientes` filtra por email+ip+momento en cada intento de login."""
    db.inicializar_db()
    con = sqlite3.connect(bd)
    try:
        indices = {f[0] for f in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
    finally:
        con.close()
    assert "idx_intentos_email_ip_momento" in indices
