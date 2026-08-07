"""Sesiones firmadas por cookie (itsdangerous) con flags seguros y protección CSRF.

Reemplaza las sesiones PHP sin flags. La cookie es HttpOnly + SameSite=Strict + Secure
(en prod). El token CSRF se entrega en una cookie legible por JS y debe reenviarse en la
cabecera X-CSRF-Token en peticiones mutantes.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from itsdangerous import BadData, URLSafeTimedSerializer

from ..config import obtener_config

COOKIE_SESION = "morphos_sesion"
COOKIE_CSRF = "morphos_csrf"
CABECERA_CSRF = "x-csrf-token"


def _serializer() -> URLSafeTimedSerializer:
    cfg = obtener_config()
    secreto = cfg.session_secret or "dev-inseguro-cambiar"  # sólo válido en entorno dev
    return URLSafeTimedSerializer(secreto, salt="morphos.sesion")


def firmar_sesion(datos: dict) -> str:
    """Firma la sesión añadiéndole identidad (`jti`) e instante de emisión (`emitida_en`).

    Sin `jti` no se puede revocar UNA sesión —no hay nada que nombrar—, y sin `emitida_en` no se
    puede cortar un conjunto de ellas por fecha. Se generan aquí, y no en quien llama, para que
    ninguna ruta pueda emitir por descuido una sesión irrevocable.
    """
    completos = {
        "jti": secrets.token_urlsafe(16),
        "emitida_en": datetime.now(UTC).isoformat(),
        **datos,
    }
    return _serializer().dumps(completos)


def caducidad_de(sesion: dict) -> str:
    """Cuándo deja de valer la firma por sí sola: hasta ahí hay que recordar una revocación."""
    cfg = obtener_config()
    emitida = sesion.get("emitida_en")
    try:
        base = datetime.fromisoformat(emitida) if emitida else datetime.now(UTC)
    except ValueError:
        base = datetime.now(UTC)
    return (base + timedelta(seconds=cfg.session_max_age_s)).isoformat()


def leer_sesion(token: str | None) -> dict | None:
    if not token:
        return None
    cfg = obtener_config()
    try:
        return _serializer().loads(token, max_age=cfg.session_max_age_s)
    except BadData:
        # BadData es el padre de BadSignature (firma inválida o falsificada), de
        # SignatureExpired (sesión caducada) y de BadPayload (token corrupto): las tres son
        # "cookie no válida" → sin sesión. NO se captura Exception: un TypeError o un fallo de
        # configuración deben propagarse, no disfrazarse de 401 y ocultar el bug real.
        return None


def nuevo_token_csrf() -> str:
    return secrets.token_urlsafe(32)
