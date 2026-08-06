"""Autenticación: /api/auth (login, registro, logout) y estado de sesión.

Mejoras de seguridad frente a auth.php:
- Throttling de intentos de login por email+IP (fuerza bruta).
- Cookies de sesión firmadas, HttpOnly, SameSite=Strict, Secure en prod.
- Token CSRF de doble envío emitido al autenticar.
- Contraseña mínima de 8 caracteres.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from ..config import obtener_config
from ..db import (
    buscar_usuario,
    crear_usuario,
    intentos_recientes,
    limpiar_intentos,
    registrar_intento,
    verificar_password,
)
from ..security.authz import usuario_actual
from ..security.rate_limit import limiter
from ..security.session import (
    COOKIE_CSRF,
    COOKIE_SESION,
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


def _emitir_sesion(resp: Response, email: str, nombre: str) -> str:
    cfg = obtener_config()
    token = firmar_sesion({"email": email, "nombre": nombre})
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
    ip = request.client.host if request.client else "?"
    if intentos_recientes(body.email, ip, _VENTANA_THROTTLE_S) >= _MAX_INTENTOS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos. Espera unos minutos.")

    usuario = buscar_usuario(body.email)
    if not usuario or not verificar_password(body.password, usuario["password"]):
        registrar_intento(body.email, ip)
        # Mensaje genérico: no revela si el email existe.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos.")

    limpiar_intentos(body.email)
    csrf = _emitir_sesion(response, usuario["email"], usuario["nombre"])
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
    if buscar_usuario(body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese email.")
    crear_usuario(body.nombre, body.apellido, body.email, body.password)
    csrf = _emitir_sesion(response, body.email, body.nombre)
    return {"ok": True, "nombre": body.nombre, "csrf": csrf}


@router.post("/auth/logout")
async def logout(response: Response, _sesion: dict = Depends(usuario_actual)) -> dict:
    response.delete_cookie(COOKIE_SESION)
    response.delete_cookie(COOKIE_CSRF)
    return {"ok": True}
