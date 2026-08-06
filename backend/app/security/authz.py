"""Dependencias de autorización y CSRF para FastAPI.

Cierra el agujero crítico de la versión PHP: /api/interpret y /api/papers estaban
abiertos. Aquí requieren sesión válida. Las peticiones mutantes exigen doble-token CSRF.
"""

from __future__ import annotations

import hmac
from datetime import datetime

from fastapi import Cookie, Header, HTTPException, Request, status

from ..config import TENANT_POR_DEFECTO
from .session import CABECERA_CSRF, COOKIE_CSRF, COOKIE_SESION, leer_sesion


def usuario_actual(request: Request) -> dict:
    """Devuelve la sesión o 401. Usar como dependencia en rutas protegidas.

    La firma válida ya no basta: una cookie firmada valía hasta caducar mirándola sólo a ella,
    así que una copiada no se podía invalidar. Se comprueban además las dos revocaciones
    (`db.revocar_sesion` para una, `db.revocar_todas_las_sesiones` para las de una cuenta).

    Es `def` y no `async def` a propósito: FastAPI ejecuta las dependencias síncronas en un hilo,
    así que estas dos consultas no bloquean el bucle de eventos (ver §3.1).
    """
    token = request.cookies.get(COOKIE_SESION)
    sesion = leer_sesion(token)
    if not sesion or not sesion.get("email"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado.")
    if _revocada(sesion):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión revocada.")
    return sesion


def _revocada(sesion: dict) -> bool:
    from .. import db

    jti = sesion.get("jti")
    # Sin `jti` es una cookie anterior a la revocación. Se acepta hasta que caduque: invalidarlas
    # de golpe echaría a todo el mundo en el despliegue, y su vida máxima ya es acotada.
    if jti and db.sesion_revocada(jti):
        return True
    corte = db.sesiones_validas_desde(sesion["email"])
    if not corte:
        return False
    emitida = sesion.get("emitida_en")
    if not emitida:
        return True  # hay corte y la sesión no dice cuándo nació: se descarta
    # Ambas ISO-8601 UTC con microsegundos: a resolución de segundo, una sesión emitida en el
    # mismo segundo que el corte sobrevivía.
    try:
        return datetime.fromisoformat(emitida) < datetime.fromisoformat(corte)
    except ValueError:
        return True


def tenant_de_sesion(sesion: dict) -> str:
    """Clínica del usuario de la sesión.

    Las sesiones emitidas ANTES de que existiera el tenant no lo llevan en la cookie firmada, y
    duran hasta `session_max_age_s`. Caen al tenant por defecto, que es donde también viven los
    dispositivos que no declaran clínica: un despliegue de una sola clínica —el caso normal—
    sigue funcionando durante la transición sin que nadie tenga que volver a entrar.
    """
    return sesion.get("tenant") or TENANT_POR_DEFECTO


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
