"""POST /api/interpret — interpretación clínica con IA.

Protegido con sesión, CSRF y rate limiting (cierra el agujero de hf_proxy.php, que era
anónimo y con CORS abierto). Valida las imágenes del lado servidor (número, tamaño, mime).
"""

from __future__ import annotations

import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..ai.base import ErrorModelo
from ..ai.service import interpretar
from ..config import obtener_config
from ..schemas import PeticionInterpretacion, RespuestaInterpretacion
from ..security.authz import usuario_actual, verificar_csrf
from ..security.rate_limit import limiter

router = APIRouter()

_DATA_URL = re.compile(r"^data:image/(jpeg|png|gif|webp);base64,(.+)$", re.DOTALL)


def _validar_imagenes(imagenes: list[str]) -> None:
    cfg = obtener_config()
    if len(imagenes) > cfg.max_imagenes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Demasiadas imágenes.")
    for img in imagenes:
        m = _DATA_URL.match(img)
        if not m:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Formato de imagen no permitido.")
        try:
            crudo = base64.b64decode(m.group(2), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Imagen base64 inválida."
            ) from exc
        if len(crudo) > cfg.max_bytes_imagen:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Imagen demasiado grande.")


@router.post("/interpret", response_model=RespuestaInterpretacion)
@limiter.limit(obtener_config().limite_interpret)
async def post_interpret(
    request: Request,
    pet: PeticionInterpretacion,
    _sesion: dict = Depends(usuario_actual),
    _csrf: None = Depends(verificar_csrf),
) -> RespuestaInterpretacion:
    _validar_imagenes(pet.imagenes)
    try:
        return await interpretar(pet)
    except ErrorModelo as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error del modelo: {exc}") from exc
