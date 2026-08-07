"""Limitación de tasa (slowapi) por IP.

Cubre el agujero de la versión PHP (sin rate limiting en ningún sitio): el endpoint de
IA (costoso, quema la cuota HF), el login (fuerza bruta) y papers (abuso de PubMed).
Los límites concretos son configurables en config.py.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import obtener_config
from .session import COOKIE_SESION, leer_sesion


def ip_cliente(request: Request) -> str:
    """IP real del cliente, teniendo en cuenta los proxies de confianza declarados.

    `get_remote_address` devuelve `request.client.host`, que detrás de un proxy es el proxy: en
    HF Spaces eso convertía `limite_login` y `limite_papers` en límites GLOBALES compartidos por
    todo el mundo (bypass de la fuerza bruta y auto-DoS a la vez).

    `X-Forwarded-For` NO se lee a ciegas —la manda el cliente, y creérsela permite falsificar la
    IP en cada petición y saltarse cualquier límite—. Se usa sólo si el operador declaró cuántos
    proxies hay delante (`proxy_saltos_confiables`), y se toma el elemento -N: cada proxy añade
    la dirección de su par, así que ése es el último valor escrito por infraestructura de
    confianza. Lo de más a la izquierda es lo que dijo el cliente y se descarta.
    """
    saltos = obtener_config().proxy_saltos_confiables
    if saltos > 0:
        reenviada = request.headers.get("x-forwarded-for", "")
        partes = [p.strip() for p in reenviada.split(",") if p.strip()]
        if len(partes) >= saltos:
            return partes[-saltos]
        # Menos entradas de las declaradas: la petición no vino por la cadena esperada. Se cae
        # al peer directo en vez de coger un valor que el cliente controle.
    return get_remote_address(request)


limiter = Limiter(key_func=ip_cliente)


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
    return f"ip:{ip_cliente(request)}"
