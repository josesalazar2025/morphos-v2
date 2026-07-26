"""Dependencias de autorización y CSRF para FastAPI.

Cierra el agujero crítico de la versión PHP: /api/interpret y /api/papers estaban
abiertos. Aquí requieren sesión válida. Las peticiones mutantes exigen doble-token CSRF.
"""

from __future__ import annotations

import hmac

from fastapi import Cookie, Header, HTTPException, Request, status

from .session import CABECERA_CSRF, COOKIE_CSRF, COOKIE_SESION, leer_sesion


def usuario_actual(request: Request) -> dict:
    """Devuelve la sesión o 401. Usar como dependencia en rutas protegidas."""
    token = request.cookies.get(COOKIE_SESION)
    sesion = leer_sesion(token)
    if not sesion or not sesion.get("email"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado.")
    return sesion


def verificar_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias=CABECERA_CSRF),
    morphos_csrf: str | None = Cookie(default=None, alias=COOKIE_CSRF),
) -> None:
    """Double-submit cookie: la cabecera debe coincidir con la cookie CSRF."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # Comparación en tiempo constante: el token es un secreto de sesión, así que se compara con
    # compare_digest por costumbre defensiva (no con `!=`, que corta en el primer byte distinto).
    if not x_csrf_token or not morphos_csrf or not hmac.compare_digest(x_csrf_token, morphos_csrf):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF inválido.")
