"""Capa de datos de usuarios.

Diferencias de seguridad frente a la versión PHP:
- La BD SQLite vive en instance/ FUERA del directorio servido (no es descargable).
- Esquema versionado con `PRAGMA user_version` (ver `_MIGRACIONES`).
- Hash de contraseña con scrypt (stdlib), sal aleatoria por usuario y parámetros de coste
  guardados JUNTO al hash, de modo que subirlos no invalide las contraseñas existentes: cada
  una se verifica con los suyos y se migra en su siguiente login correcto.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache

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
    # 4 — revocación de sesiones. Las cookies firmadas son válidas hasta que caducan mirándolas
    # sólo a ellas, así que no había forma de invalidar una copiada ni de echar a nadie tras un
    # incidente. Dos mecanismos, porque resuelven cosas distintas:
    #   - `sesiones_revocadas`: una sesión concreta (logout). Se guarda hasta su caducidad; a
    #     partir de ahí la firma ya no vale por sí sola y la fila sobra.
    #   - `usuarios.sesiones_validas_desde`: TODAS las de una cuenta a la vez (cambio de
    #     contraseña, robo). Un sello temporal en vez de un contador de versión porque la
    #     pregunta que hay que responder es «¿se emitió antes del corte?».
    """
CREATE TABLE IF NOT EXISTS sesiones_revocadas (
    jti TEXT PRIMARY KEY,
    expira_en DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sesiones_revocadas_expira ON sesiones_revocadas (expira_en);
ALTER TABLE usuarios ADD COLUMN sesiones_validas_desde DATETIME;
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
    # Se calcula aquí y no en el primer login fallido: si no, esa primera petición pagaría dos
    # scrypt en vez de uno y sería la única con un tiempo distinto.
    _hash_senuelo()
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
#
# Formato almacenado: `scrypt$n$r$p$sal$hash`, AUTODESCRIPTIVO.
#
# Antes era `scrypt$sal$hash` y los parámetros de coste vivían sólo en el código, con dos
# consecuencias: subir el coste habría invalidado en bloque todas las contraseñas existentes
# (el mismo `verificar_password` que las comprueba habría empezado a derivar con otra n), y ni
# siquiera se podía DETECTAR cuáles estaban al coste viejo. Guardar n/r/p junto al hash es lo
# que hace posible verificar cada uno con los suyos y migrarlos de a uno.
#
# `dklen` no se guarda: se deduce de la longitud del hash almacenado, que es exactamente lo que
# mide. Un número menos que pueda desincronizarse.
#
# Los parámetros vigentes viven en un solo sitio también porque el hash SEÑUELO de abajo tiene
# que costar lo mismo que uno real: si divergen, la defensa contra la enumeración por tiempo
# deja de funcionar sin que nada falle.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

# Parámetros IMPLÍCITOS de los hashes en formato antiguo. No son "los de antes" en el sentido de
# una constante que se actualiza: son los que se aplicaron de hecho a esas contraseñas, así que
# esta línea no se toca nunca aunque `_SCRYPT` suba.
_SCRYPT_HEREDADO = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

# Nota para cuando se suba `_SCRYPT`: mientras dure la migración, verificar un hash sin migrar
# costará MENOS que el señuelo de `simular_verificacion_password`, que se deriva con los
# parámetros vigentes. Durante esa ventana el reloj no distingue «existe» de «no existe» —para
# eso está el señuelo— pero sí «existe y aún no ha entrado desde la subida». Es una fuga menor y
# temporal; si algún día importa, la respuesta es derivar el señuelo con `_SCRYPT_HEREDADO`
# hasta que no queden hashes antiguos, no bajar el coste real.

# Techo de cordura al leer n de la BD. `hashlib.scrypt` reserva del orden de 128·n·r bytes, así
# que un valor absurdo en una fila corrupta o manipulada convierte un login en un agotamiento de
# memoria. El rango cubre de sobra cualquier coste razonable.
_N_MAXIMA = 2**20


def hash_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=sal, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${sal.hex()}${dk.hex()}"


def _parsear_hash(almacenado: str) -> tuple[dict, bytes, str, bool] | None:
    """(parámetros, sal, hash, es_formato_antiguo), o None si no se entiende."""
    try:
        partes = almacenado.split("$")
        if partes[0] != "scrypt":
            return None
        if len(partes) == 3:
            _, sal_hex, hash_hex = partes
            parametros = dict(_SCRYPT_HEREDADO)
            antiguo = True
        elif len(partes) == 6:
            _, n, r, p, sal_hex, hash_hex = partes
            parametros = {
                "n": int(n), "r": int(r), "p": int(p), "dklen": len(hash_hex) // 2,
            }
            if not 0 < parametros["n"] <= _N_MAXIMA:
                return None
            antiguo = False
        else:
            return None
        return parametros, bytes.fromhex(sal_hex), hash_hex, antiguo
    except (ValueError, AttributeError, IndexError):
        return None


def verificar_password(password: str, almacenado: str) -> bool:
    parseado = _parsear_hash(almacenado)
    if parseado is None:
        return False
    parametros, sal, hash_hex, _ = parseado
    try:
        # Con los parámetros DEL HASH, no con los vigentes: es lo que permite que una contraseña
        # guardada al coste viejo siga entrando después de subirlo.
        dk = hashlib.scrypt(password.encode(), salt=sal, **parametros)
    except ValueError:
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def necesita_rehash(almacenado: str) -> bool:
    """¿Este hash está al día? Se comprueba tras un login CORRECTO, que es el único momento en
    que existe la contraseña en claro para volver a derivarla.

    Devuelve True también para el formato antiguo aunque su coste coincida hoy con el vigente:
    interesa que el parque converja al formato autodescriptivo ANTES de que alguien suba la n, y
    no a la vez. Si no, la primera subida de coste tendría que lidiar con las dos cosas.

    Un hash ilegible devuelve False: no se puede arreglar re-derivando algo que no se entiende, y
    de todas formas `verificar_password` nunca lo dará por bueno.
    """
    parseado = _parsear_hash(almacenado)
    if parseado is None:
        return False
    parametros, _, _, antiguo = parseado
    return antiguo or parametros != _SCRYPT


@lru_cache(maxsize=1)
def _hash_senuelo() -> str:
    """Hash real de una contraseña aleatoria que nadie conoce.

    Es real y no una cadena fija a propósito: `verificar_password` tiene que recorrer el mismo
    camino que con un usuario existente —parsear, derivar la clave, comparar— y sólo entonces
    devolver False. La contraseña se genera al arranque y se descarta, así que ninguna entrada
    puede acertarla.
    """
    return hash_password(secrets.token_urlsafe(32))


def simular_verificacion_password(password: str) -> bool:
    """Gasta el mismo tiempo que verificar una contraseña, y siempre falla.

    Sin esto, el login era un oráculo de qué cuentas existen: si el email NO estaba en la BD no
    se calculaba ningún hash y la respuesta salía en sub-milisegundo, mientras que un email
    existente pagaba scrypt (n=2**14, decenas de ms). El mensaje de error ya era genérico, pero
    el reloj lo desmentía, y esa diferencia se mide trivialmente desde fuera.

    Enumerar cuentas importa aquí más de lo normal: el alta está cerrada con lista blanca
    (`registro_allowlist`), así que la lista de emails válidos ES el control de admisión.
    """
    return verificar_password(password, _hash_senuelo())


# --- Operaciones de usuario ---

def buscar_usuario(email: str) -> sqlite3.Row | None:
    with _conexion() as con:
        cur = con.execute(
            "SELECT id, nombre, apellido, email, password, tenant "
            "FROM usuarios WHERE email = ? LIMIT 1",
            (email,),
        )
        return cur.fetchone()


def actualizar_password_hash(email: str, password: str) -> None:
    """Vuelve a derivar el hash con los parámetros VIGENTES y lo guarda.

    Sólo se llama tras un login correcto: es el único instante en que el servidor tiene la
    contraseña en claro. Cualquier otro momento (una tarea de fondo, un script de migración) sólo
    tiene el hash, y de un hash no se sale.
    """
    with _conexion() as con:
        con.execute(
            "UPDATE usuarios SET password = ? WHERE email = ?", (hash_password(password), email)
        )


def crear_usuario(nombre: str, apellido: str, email: str, password: str, tenant: str) -> None:
    with _conexion() as con:
        con.execute(
            "INSERT INTO usuarios (nombre, apellido, email, password, tenant) "
            "VALUES (?, ?, ?, ?, ?)",
            (nombre, apellido, email, hash_password(password), tenant),
        )


# --- Revocación de sesiones ---

def _ahora_iso() -> str:
    """Instante actual en ISO-8601 UTC con microsegundos.

    Se genera en Python y NO con `datetime('now')` de SQLite por dos motivos: SQLite tiene
    resolución de SEGUNDO —una sesión emitida en el mismo segundo que un corte de revocación
    sobrevivía— y usa un espacio en vez de 'T', así que comparar sus cadenas con las ISO de las
    sesiones daba órdenes incorrectos.
    """
    return datetime.now(UTC).isoformat()


def revocar_sesion(jti: str, expira_en: str) -> None:
    """Invalida UNA sesión (logout) hasta que su firma caduque por sí sola."""
    with _conexion() as con:
        con.execute(
            "INSERT OR REPLACE INTO sesiones_revocadas (jti, expira_en) VALUES (?, ?)",
            (jti, expira_en),
        )
        # Poda oportunista: pasada su caducidad la firma ya no vale, así que la fila no aporta.
        # El corte va como parámetro, en el MISMO formato que lo guardado.
        con.execute("DELETE FROM sesiones_revocadas WHERE expira_en < ?", (_ahora_iso(),))


def sesion_revocada(jti: str) -> bool:
    with _conexion() as con:
        cur = con.execute("SELECT 1 FROM sesiones_revocadas WHERE jti = ? LIMIT 1", (jti,))
        return cur.fetchone() is not None


def revocar_todas_las_sesiones(email: str) -> None:
    """Corta TODAS las sesiones de una cuenta: las emitidas antes de ahora dejan de valer."""
    with _conexion() as con:
        con.execute(
            "UPDATE usuarios SET sesiones_validas_desde = ? WHERE email = ?",
            (_ahora_iso(), email),
        )


def sesiones_validas_desde(email: str) -> str | None:
    with _conexion() as con:
        cur = con.execute(
            "SELECT sesiones_validas_desde FROM usuarios WHERE email = ? LIMIT 1", (email,)
        )
        fila = cur.fetchone()
        return fila["sesiones_validas_desde"] if fila else None


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
