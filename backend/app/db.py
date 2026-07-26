"""Capa de datos de usuarios.

Diferencias de seguridad frente a la versión PHP:
- La BD SQLite vive en instance/ FUERA del directorio servido (no es descargable).
- Sin credenciales por defecto: si se configura MySQL, usuario/clave vienen de entorno.
- Hash de contraseña con scrypt (stdlib), sal aleatoria por usuario.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .config import obtener_config

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    apellido TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS intentos_login (
    email TEXT NOT NULL,
    ip TEXT NOT NULL,
    momento DATETIME DEFAULT CURRENT_TIMESTAMP
);
-- Persistencia OPCIONAL de resultados de analizador (sólo con lab_persistir=true; útil sólo
-- con volumen persistente). Clave = muestra_id normalizada; último gana (INSERT OR REPLACE).
CREATE TABLE IF NOT EXISTS resultados_lab (
    muestra_id TEXT PRIMARY KEY,
    momento DATETIME,
    recibido_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    payload_json TEXT NOT NULL
);
"""


def inicializar_db() -> None:
    cfg = obtener_config()
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conexion() as con:
        con.executescript(_ESQUEMA)


@contextmanager
def _conexion() -> Iterator[sqlite3.Connection]:
    cfg = obtener_config()
    con = sqlite3.connect(cfg.db_path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


# --- Hash de contraseñas (scrypt, stdlib) ---

def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=sal, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${sal.hex()}${dk.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        algo, sal_hex, hash_hex = almacenado.split("$")
        if algo != "scrypt":
            return False
        sal = bytes.fromhex(sal_hex)
        dk = hashlib.scrypt(password.encode(), salt=sal, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --- Operaciones de usuario ---

def buscar_usuario(email: str) -> sqlite3.Row | None:
    with _conexion() as con:
        cur = con.execute(
            "SELECT id, nombre, apellido, email, password FROM usuarios WHERE email = ? LIMIT 1",
            (email,),
        )
        return cur.fetchone()


def crear_usuario(nombre: str, apellido: str, email: str, password: str) -> None:
    with _conexion() as con:
        con.execute(
            "INSERT INTO usuarios (nombre, apellido, email, password) VALUES (?, ?, ?, ?)",
            (nombre, apellido, email, hash_password(password)),
        )


# --- Registro de intentos de login (para throttling) ---

def registrar_intento(email: str, ip: str) -> None:
    with _conexion() as con:
        con.execute("INSERT INTO intentos_login (email, ip) VALUES (?, ?)", (email, ip))
        # Poda oportunista: `limpiar_intentos` sólo corre tras un login correcto, así que los
        # intentos fallidos contra emails que nunca aciertan crecerían sin límite. Una hora cubre
        # de sobra cualquier ventana de throttling configurada.
        con.execute("DELETE FROM intentos_login WHERE momento < datetime('now', '-1 hour')")


def intentos_recientes(email: str, ip: str, ventana_s: int) -> int:
    with _conexion() as con:
        cur = con.execute(
            "SELECT COUNT(*) AS n FROM intentos_login "
            "WHERE (email = ? OR ip = ?) AND momento > datetime('now', ?)",
            (email, ip, f"-{ventana_s} seconds"),
        )
        return int(cur.fetchone()["n"])


def limpiar_intentos(email: str) -> None:
    with _conexion() as con:
        con.execute("DELETE FROM intentos_login WHERE email = ?", (email,))


# --- Persistencia opcional de resultados de laboratorio ---

def guardar_resultado_lab(muestra_id: str, momento: str, payload_json: str) -> None:
    with _conexion() as con:
        con.execute(
            "INSERT OR REPLACE INTO resultados_lab (muestra_id, momento, payload_json) VALUES (?, ?, ?)",
            (muestra_id, momento, payload_json),
        )


def cargar_resultados_lab(limite: int = 500) -> list[str]:
    """Devuelve los payloads JSON más recientes, para recargar el almacén en proceso al arrancar."""
    with _conexion() as con:
        cur = con.execute(
            "SELECT payload_json FROM resultados_lab ORDER BY recibido_en DESC LIMIT ?",
            (limite,),
        )
        return [row["payload_json"] for row in cur.fetchall()]
