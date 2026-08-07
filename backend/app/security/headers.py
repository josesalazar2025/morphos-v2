"""Middleware de cabeceras de seguridad.

Añade CSP, HSTS (en prod), X-Content-Type-Options, Referrer-Policy y X-Frame-Options,
ausentes en la versión PHP.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..config import obtener_config

# CSP estricta: sólo mismo origen, SIN 'unsafe-inline' en ninguna directiva.
#
# `style-src` lo tuvo hasta el 2026-08-07 «por si hiciera falta», y era el único hueco de la
# política: con él, cualquier marcado que se colara en la página podía traer estilos, y el
# vector clásico es la exfiltración por selectores CSS (`input[value^="a"] {background:url(…)}`).
# No hacía falta: `index.html` no tiene ni un `style="…"` ni un `<style>`, y todo el estilo
# dinámico del frontend se aplica por CSSOM (`el.style.height = …`, `style.setProperty`), que la
# CSP NO restringe —sólo bloquea el atributo `style` en el marcado y los bloques `<style>`.
# Si algún día algo necesita estilo inline, la respuesta es una clase en `css/styles.css` o un
# hash/nonce, nunca devolver 'unsafe-inline'. `test_csp.py` lo fija.
#
# worker-src incluye blob: porque PDF.js crea su worker desde un blob URL
# (URL.createObjectURL + new Worker); sin ello el parseo de PDF en cliente falla.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "script-src 'self'; "
    "worker-src 'self' blob:; "
    "child-src 'self' blob:; "
    "style-src 'self'; "
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
