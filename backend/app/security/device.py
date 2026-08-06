"""Autenticación del puente local (dispositivo headless) para la ingesta de laboratorio.

El puente no es un navegador: no tiene cookie de sesión ni CSRF. Se autentica con una API
key por Bearer sobre HTTPS. Comparación en tiempo constante (misma disciplina que
verificar_password en db.py). Falla cerrado: sin keys configuradas, la ingesta no existe.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from ..config import obtener_config


def verificar_dispositivo(authorization: str | None = Header(default=None)) -> str:
    """Dependencia para /api/lab/ingesta: devuelve el TENANT dueño de la clave.

    Antes devolvía None y la clave era anónima: cualquier dispositivo escribía en un almacén
    global y cualquier sesión lo leía. El tenant sale de la configuración del servidor, nunca
    del cuerpo de la petición: si el puente pudiera declarar su clínica, bastaría mentir en un
    campo para escribir en la de otro.
    """
    cfg = obtener_config()
    if not cfg.lab_api_keys:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Ingesta de laboratorio no configurada.",
        )
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    tenant = cfg.tenant_de_clave_dispositivo(token) if token else None
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Dispositivo no autorizado.")
    return tenant
