"""Autenticación: /api/auth (login, registro, logout) y estado de sesión.

Mejoras de seguridad frente a auth.php:
- Throttling de intentos de login por email+IP (fuerza bruta).
- Cookies de sesión firmadas, HttpOnly, SameSite=Strict, Secure en prod.
- Token CSRF de doble envío emitido al autenticar.
- Contraseña mínima de 8 caracteres.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from ..config import TENANT_POR_DEFECTO, obtener_config
from ..db import (
    actualizar_password_hash,
    buscar_usuario,
    crear_usuario,
    intentos_recientes,
    limpiar_intentos,
    necesita_rehash,
    registrar_intento,
    revocar_sesion,
    revocar_todas_las_sesiones,
    simular_verificacion_password,
    verificar_password,
)
from ..security.authz import usuario_actual
from ..security.rate_limit import ip_cliente, limiter
from ..security.session import (
    COOKIE_CSRF,
    COOKIE_SESION,
    caducidad_de,
    firmar_sesion,
    nuevo_token_csrf,
)

router = APIRouter()

_VENTANA_THROTTLE_S = 900
_MAX_INTENTOS = 8


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RegistroBody(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    apellido: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


def _emitir_sesion(resp: Response, email: str, nombre: str, tenant: str) -> str:
    cfg = obtener_config()
    # El tenant viaja en la cookie FIRMADA: el cliente no puede cambiarlo sin romper la firma,
    # y así leerlo no cuesta una consulta a la BD en cada petición.
    token = firmar_sesion({"email": email, "nombre": nombre, "tenant": tenant})
    csrf = nuevo_token_csrf()
    resp.set_cookie(
        COOKIE_SESION, token, httponly=True, secure=cfg.cookie_secure,
        samesite="strict", max_age=cfg.session_max_age_s,
    )
    # La cookie CSRF NO es HttpOnly: el JS la lee y la reenvía en la cabecera.
    resp.set_cookie(
        COOKIE_CSRF, csrf, httponly=False, secure=cfg.cookie_secure,
        samesite="strict", max_age=cfg.session_max_age_s,
    )
    return csrf


@router.get("/auth")
async def estado(request: Request) -> dict:
    from ..security.session import leer_sesion

    sesion = leer_sesion(request.cookies.get(COOKIE_SESION))
    return {"autenticado": bool(sesion), "nombre": sesion.get("nombre") if sesion else None}


@router.post("/auth/login")
@limiter.limit(obtener_config().limite_login)
async def login(request: Request, body: LoginBody, response: Response) -> dict:
    # Todo lo que toca SQLite o scrypt va a un hilo: son llamadas SÍNCRONAS dentro de un
    # endpoint `async`, así que en el bucle de eventos bloqueaban el proceso entero. scrypt es
    # además caro A PROPÓSITO (n=2**14, decenas de ms): es justo el trabajo que no puede vivir
    # en el bucle, y el login es el endpoint que más veces lo ejecuta.
    # `ip_cliente` y no `request.client.host`: detrás del proxy este último es el proxy, así
    # que el throttle por email+IP degeneraba en un contador global.
    ip = ip_cliente(request)
    if await asyncio.to_thread(intentos_recientes, body.email, ip, _VENTANA_THROTTLE_S) >= _MAX_INTENTOS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera unos minutos.")

    usuario = await asyncio.to_thread(buscar_usuario, body.email)
    # Las dos ramas cuestan lo mismo. Antes, un email inexistente saltaba scrypt entero y
    # respondía en sub-milisegundo frente a las decenas de ms de uno existente: el mensaje de
    # error era genérico, pero el reloj revelaba qué cuentas hay (ver `simular_verificacion_password`).
    if usuario:
        correcta = await asyncio.to_thread(verificar_password, body.password, usuario["password"])
    else:
        correcta = await asyncio.to_thread(simular_verificacion_password, body.password)
    if not correcta:
        await asyncio.to_thread(registrar_intento, body.email, ip)
        # Mensaje genérico: no revela si el email existe.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos.")

    await asyncio.to_thread(limpiar_intentos, body.email)
    # Migración oportunista del hash. Éste es el ÚNICO momento en que el servidor tiene la
    # contraseña en claro, así que es el único en que se puede volver a derivar con los
    # parámetros vigentes: de un hash no se sale. Cuesta un scrypt extra, una sola vez por
    # cuenta, y sin esto subir el coste dejaría a los usuarios antiguos en el viejo para siempre.
    if necesita_rehash(usuario["password"]):
        await asyncio.to_thread(actualizar_password_hash, body.email, body.password)

    csrf = _emitir_sesion(
        response, usuario["email"], usuario["nombre"], usuario["tenant"] or TENANT_POR_DEFECTO
    )
    return {"ok": True, "nombre": usuario["nombre"], "csrf": csrf}


@router.post("/auth/registro")
@limiter.limit(obtener_config().limite_login)
async def registro(request: Request, body: RegistroBody, response: Response) -> dict:
    # ANTES que la comprobación de existencia, a propósito: si se hiciera después, un email
    # fuera de la lista distinguiría «ya existe» (409) de «no existe» (403) y el alta se
    # convertiría en un oráculo de qué cuentas hay. Fuera de la lista, siempre 403.
    if not obtener_config().registro_permitido(body.email):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "El alta de cuentas está restringida. Solicita acceso al administrador.",
        )
    if await asyncio.to_thread(buscar_usuario, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese email.")
    # `crear_usuario` hashea con scrypt además de escribir: doble motivo para salir del bucle.
    # La clínica sale de la allowlist (`email=tenant`), no del cuerpo de la petición: dejar
    # elegir tenant al que se registra permitiría entrar en los datos de otra clínica.
    tenant = obtener_config().tenant_de_email(body.email)
    await asyncio.to_thread(
        crear_usuario, body.nombre, body.apellido, body.email, body.password, tenant
    )
    csrf = _emitir_sesion(response, body.email, body.nombre, tenant)
    return {"ok": True, "nombre": body.nombre, "csrf": csrf}


def _borrar_cookies(resp: Response) -> None:
    """Borra las cookies con los MISMOS atributos con que se pusieron.

    `delete_cookie()` a secas emite un Set-Cookie sin `samesite`/`secure`/`path`, y varios
    navegadores lo tratan como una cookie DISTINTA de la original: la sesión seguía en el
    navegador después de «cerrar sesión».
    """
    cfg = obtener_config()
    for nombre in (COOKIE_SESION, COOKIE_CSRF):
        resp.delete_cookie(nombre, path="/", samesite="strict", secure=cfg.cookie_secure)


@router.post("/auth/logout")
async def logout(response: Response, sesion: dict = Depends(usuario_actual)) -> dict:
    """Cierra ESTA sesión. Borrar la cookie no bastaba: el token seguía siendo válido allá
    donde se hubiera copiado, hasta `session_max_age_s` (8h por defecto)."""
    if jti := sesion.get("jti"):
        await asyncio.to_thread(revocar_sesion, jti, caducidad_de(sesion))
    _borrar_cookies(response)
    return {"ok": True}


@router.post("/auth/logout-todas")
async def logout_todas(response: Response, sesion: dict = Depends(usuario_actual)) -> dict:
    """Cierra la sesión en TODOS los dispositivos.

    Es la respuesta a «me han robado el portátil» o a un cambio de contraseña: sin esto, la
    única forma de invalidar una sesión filtrada era rotar `MORPHOS_SESSION_SECRET`, que echa a
    todos los usuarios de la instancia.
    """
    await asyncio.to_thread(revocar_todas_las_sesiones, sesion["email"])
    _borrar_cookies(response)
    return {"ok": True}
