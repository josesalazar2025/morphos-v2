"""Endpoints de la integración de analizadores.

- POST /api/lab/ingesta   (puente local → backend, autenticado por API key de dispositivo)
- GET  /api/lab/resultados (navegador → backend, autenticado por sesión) — match por muestra

Dos zonas de confianza: la ingesta NO usa cookie/CSRF (el puente es headless, la API key es
la auth); la consulta usa la sesión existente. El mapeo código→analito ocurre aquí (backend),
única fuente de verdad.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .. import db
from ..config import obtener_config
from ..lab.almacen import almacen
from ..lab.mapeo import mapear_resultado
from ..schemas_lab import (
    RespuestaIngesta,
    ResultadoAnalizador,
    ResultadoMapeado,
    ResumenPendiente,
)
from ..security.authz import tenant_de_sesion, usuario_actual
from ..security.device import verificar_dispositivo
from ..security.rate_limit import limiter

router = APIRouter()


@router.post("/lab/ingesta", response_model=RespuestaIngesta)
@limiter.limit(obtener_config().limite_lab_ingesta)
async def post_ingesta(
    request: Request,  # requerido por slowapi
    cuerpo: ResultadoAnalizador,
    tenant: str = Depends(verificar_dispositivo),  # 503 sin keys / 401 sin Bearer válido
) -> RespuestaIngesta:
    mapeado = mapear_resultado(cuerpo)
    mapeado.tenant = tenant  # del servidor, a partir de la API key; nunca del cuerpo
    almacen.guardar(mapeado)
    if obtener_config().lab_persistir:
        # A un hilo como el resto de SQLite: el analizador manda en ráfaga
        # (`limite_lab_ingesta` = 120/minute) y esto corre por cada muestra.
        await asyncio.to_thread(
            db.guardar_resultado_lab,
            mapeado.muestra_id.strip().lower(),
            mapeado.momento.isoformat(),
            mapeado.model_dump_json(),
        )
    return RespuestaIngesta(
        muestra_id=mapeado.muestra_id,
        analitos_mapeados=len(mapeado.analitos),
        no_mapeados=mapeado.no_mapeados,
    )


@router.get("/lab/resultados", response_model=ResultadoMapeado)
@limiter.limit(obtener_config().limite_lab_consulta)
async def get_resultados(
    request: Request,
    muestra: str = Query(..., min_length=1, max_length=128),
    sesion: dict = Depends(usuario_actual),  # 401 si no hay sesión
) -> ResultadoMapeado:
    res = almacen.obtener(muestra, tenant_de_sesion(sesion))
    if res is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No hay resultados para esa muestra todavía.",
        )
    return res


@router.get("/lab/pendientes", response_model=list[ResumenPendiente])
@limiter.limit(obtener_config().limite_lab_consulta)
async def get_pendientes(
    request: Request,
    sesion: dict = Depends(usuario_actual),
) -> list[ResumenPendiente]:
    """Cola de resultados recibidos (más recientes primero) para elegir sin teclear el ID.

    Desactivada por defecto (`MORPHOS_LAB_PENDIENTES_HABILITADO`): el almacén no está
    segmentado, así que esto enumera las muestras de TODAS las clínicas y cada ID abre el panel
    completo en `/lab/resultados`. 404 —y no 403— para que apagada sea indistinguible de no
    existir. Ver el comentario en `config.py`: apagarla reduce el volcado masivo, no sustituye
    al filtrado por tenant.
    """
    if not obtener_config().lab_pendientes_habilitado:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No disponible.")
    return [
        ResumenPendiente(
            muestra_id=r.muestra_id,
            instrumento_id=r.instrumento_id,
            momento=r.momento,
            analitos=len(r.analitos),
            no_mapeados=len(r.no_mapeados),
        )
        for r in almacen.pendientes(tenant_de_sesion(sesion))
    ]
