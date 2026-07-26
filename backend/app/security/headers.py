"""Middleware de cabeceras de seguridad.

Añade CSP, HSTS (en prod), X-Content-Type-Options, Referrer-Policy y X-Frame-Options,
ausentes en la versión PHP.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..config import obtener_config

# CSP estricta: sólo mismo origen. El frontend inlinea lo mínimo; ajustar si se
# externalizan scripts. 'unsafe-inline' se evita salvo para estilos si fuese necesario.
# worker-src incluye blob: porque PDF.js crea su worker desde un blob URL
# (URL.createObjectURL + new Worker); sin ello el parseo de PDF en cliente falla.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "script-src 'self'; "
    "worker-src 'self' blob:; "
    "child-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


class CabecerasSeguridad(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        cfg = obtener_config()
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
        if cfg.entorno == "prod":
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp
