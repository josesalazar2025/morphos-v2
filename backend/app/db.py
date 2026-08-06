"""Capa de datos de usuarios.

Diferencias de seguridad frente a la versión PHP:
- La BD SQLite vive en instance/ FUERA del directorio servido (no es descargable).
- Esquema versionado con `PRAGMA user_version` (ver `_MIGRACIONES`).
- Hash de contraseña con scrypt (stdlib), sal aleatoria por usuario.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from .config import TENANT_POR_DEFECTO, VOLUMEN_PERSISTENTE, obtener_config

log = logging.getLogger("morphos.db")

# Migraciones versionadas con `PRAGMA user_version`. Antes esto era un único script de
# `CREATE TABLE IF NOT EXISTS`: creaba el esquema en una BD vacía y no hacía NADA sobre una
# existente, así que añadir una columna era una operación manual sobre un fichero al que, en
# Spaces, nadie puede llegar. Cada entrada de la lista es un paso; el índice+1 es la versión
# resultante, y sólo se aplican los pasos por encima de la versión actual.
#
# Reglas: nunca se edita un paso ya publicado (una BD que lo aplicó no volvería a ejecutarlo) y
# los pasos se añaden al final. La versión garantiza que cada paso corre UNA vez, así que no
# tienen por qué ser idempotentes —el 3 es un ALTER TABLE, que no lo es—. Los `IF NOT EXISTS`
# del paso 1 son por otro motivo: las BD creadas antes de este mecanismo están en la versión 0
# con esas tablas ya presentes, y hay que poder ponerlas al día sin borrarlas.
_MIGRACIONES: list[str] = [
    # 1 — esquema inicial (el que ya existía).
    """
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
""",
    # 2 — índice para el throttle de login: `intentos_recientes` filtra por email+ip+momento en
    # cada intento y hacía scan completo de la tabla.
    """
CREATE INDEX IF NOT EXISTS idx_intentos_email_ip_momento
    ON intentos_login (email, ip, momento);
""",
    # 3 — clínica dueña de cada cuenta. Los usuarios que ya existan quedan en el tenant por
    # defecto, que es donde también caen los dispositivos sin clínica declarada: un despliegue
    # de una sola clínica no nota el cambio.
    f"""
ALTER TABLE usuarios ADD COLUMN tenant TEXT NOT NULL DEFAULT '{TENANT_POR_DEFECTO}';
""",
]


def _migrar(con: sqlite3.Connection) -> int:
    """Aplica los pasos pendientes y devuelve la versión resultante."""
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for indice in range(version, len(_MIGRACIONES)):
        con.executescript(_MIGRACIONES[indice])
        # `PRAGMA` no admite parámetros; el valor es un índice entero nuestro, no entrada.
        con.execute(f"PRAGMA user_version = {indice + 1}")
    return len(_MIGRACIONES)


def inicializar_db() -> None:
    cfg = obtener_config()
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conexion() as con:
        version = _migrar(con)
    persistente = cfg.db_path.is_relative_to(VOLUMEN_PERSISTENTE)
    log.info("BD en %s (esquema v%d, %s).", cfg.db_path, version,
             "persistente" if persistente else "EFÍMERA: las cuentas no sobreviven al reinicio")
    if not persistente:
        log.warning(
            "La base de usuarios está en almacenamiento EFÍMERO (%s): cada reinicio borra "
            "cuentas, contraseñas e historial de intentos. Monta un volumen persistente o "
            "apunta MORPHOS_DB_PATH a uno.", cfg.db_path,
        )


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
            "SELECT id, nombre, apellido, email, password, tenant "
            "FROM usuarios WHERE email = ? LIMIT 1",
            (email,),
        )
        return cur.fetchone()


def crear_usuario(nombre: str, apellido: str, email: str, password: str, tenant: str) -> None:
    with _conexion() as con:
        con.execute(
            "INSERT INTO usuarios (nombre, apellido, email, password, tenant) "
            "VALUES (?, ?, ?, ?, ?)",
            (nombre, apellido, email, hash_password(password), tenant),
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
