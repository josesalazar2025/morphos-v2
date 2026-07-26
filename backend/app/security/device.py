"""Autenticación del puente local (dispositivo headless) para la ingesta de laboratorio.

El puente no es un navegador: no tiene cookie de sesión ni CSRF. Se autentica con una API
key por Bearer sobre HTTPS. Comparación en tiempo constante (misma disciplina que
verificar_password en db.py). Falla cerrado: sin keys configuradas, la ingesta no existe.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from ..config import obtener_config


def verificar_dispositivo(authorization: str | None = Header(default=None)) -> None:
    """Dependencia para /api/lab/ingesta. 503 si no hay keys; 401 si la Bearer no coincide."""
    cfg = obtener_config()
    if not cfg.lab_api_keys:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Ingesta de laboratorio no configurada.",
        )
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not any(hmac.compare_digest(token, k) for k in cfg.lab_api_keys):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Dispositivo no autorizado.")
