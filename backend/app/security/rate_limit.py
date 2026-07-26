"""Limitación de tasa (slowapi) por IP.

Cubre el agujero de la versión PHP (sin rate limiting en ningún sitio): el endpoint de
IA (costoso, quema la cuota HF), el login (fuerza bruta) y papers (abuso de PubMed).
Los límites concretos son configurables en config.py.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .session import COOKIE_SESION, leer_sesion

limiter = Limiter(key_func=get_remote_address)


def clave_usuario(request: Request) -> str:
    """Clave de rate limiting por USUARIO, no por IP.

    En una herramienta gratuita el recurso escaso es la cuota de GPU compartida (ZeroGPU es por
    cuenta, no por Space): un solo usuario puede agotarla para todos los demás. El límite por IP
    no lo evita —una IP doméstica cambia, y varios veterinarios de una misma clínica comparten
    IP, penalizándose entre sí—. Con la sesión como clave, el coste se imputa a quien lo genera.

    Sin sesión se cae a la IP: /api/interpret exige sesión, así que ese caso sólo aparece si
    cambia la guarda de auth.
    """
    sesion = leer_sesion(request.cookies.get(COOKIE_SESION))
    if sesion and sesion.get("email"):
        return f"user:{sesion['email']}"
    return f"ip:{get_remote_address(request)}"
