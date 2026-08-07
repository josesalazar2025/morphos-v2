"""GET /api/papers — búsqueda en PubMed con caché en disco.

Porta la lógica de papers_proxy.php (esearch + esummary + caché 30 min) pero ahora
protegida con rate limiting.

La caché guarda también los FALLOS, con un TTL mucho más corto: sin eso, una caída de NCBI
hacía que cada petición pagara el timeout entero y volviera a salir a la red, justo cuando
menos conviene insistir.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status

from ..config import obtener_config
from ..security.rate_limit import limiter

router = APIRouter()

# El uid en el nombre evita el caso en que el directorio ya existe creado por OTRO usuario del
# host compartido: `mkdir(mode=0o700)` sólo protege si lo creamos nosotros, y con `exist_ok=True`
# un directorio ajeno (o un enlace simbólico plantado ahí) se habría usado tal cual.
_DIR_CACHE = Path(tempfile.gettempdir()) / f"morphos_papers_cache_{os.getuid()}"
_TTL_S = 1800
# TTL de los FALLOS, mucho más corto que el de los aciertos. Sólo se cacheaban los éxitos, así
# que con NCBI caído cada petición volvía a pagar el timeout de 15 s ENTERO y salía otra vez a
# la red: el peor momento para insistir, y encima el User-Agent lleva el correo de contacto del
# proyecto, así que el castigo de NCBI por machacarles recae sobre esa dirección.
#
# Un minuto es el compromiso: corta la ráfaga contra un servicio caído sin dejar la búsqueda
# rota un rato largo después de que NCBI vuelva. Un TTL de fallo largo convierte una caída de
# diez segundos en una avería de media hora, que es peor que el problema que resuelve.
_TTL_FALLO_S = 60
# Marca de entrada negativa. No colisiona con una respuesta real: el payload de éxito lo
# construye este módulo y sólo tiene `total` y `data`.
_CLAVE_FALLO = "_fallo"
_MAX_ENTRADAS = 500
_CABECERAS = {"User-Agent": "Morphos/1.0 (mailto:ceo@equipamed.net)", "Accept": "application/json"}


def _ruta(clave: str) -> Path:
    return _DIR_CACHE / f"{hashlib.sha256(clave.encode()).hexdigest()}.json"


def _leer_cache(clave: str) -> dict | None:
    """Entrada viva de la caché, o None. Un fichero ilegible es un fallo de caché, no un 500.

    Antes, `json.loads` sobre un fichero a medio escribir tumbaba la petición con 500. Con la
    escritura atómica de abajo eso ya no debería ocurrir, pero la caché vive en un directorio
    temporal que puede truncarse por otras razones (disco lleno, limpieza del host), y un fallo
    de caché siempre es recuperable: se vuelve a pedir a NCBI.
    """
    archivo = _ruta(clave)
    try:
        edad = time.time() - archivo.stat().st_mtime
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        archivo.unlink(missing_ok=True)  # corrupta: que no se relea eternamente
        return None
    if not isinstance(datos, dict):
        archivo.unlink(missing_ok=True)
        return None
    # El TTL depende del tipo de entrada, así que hay que leer el contenido para decidirlo. Un
    # fallo caduca mucho antes que un acierto: ver `_TTL_FALLO_S`.
    if edad >= (_TTL_FALLO_S if _CLAVE_FALLO in datos else _TTL_S):
        return None
    return datos


def _podar_cache() -> None:
    """Borra lo caducado y, si aún sobran entradas, lo más antiguo.

    Sin esto el directorio sólo crecía: el TTL se comprobaba al LEER, así que una consulta que
    no se repite nunca dejaba su fichero para siempre.
    """
    try:
        entradas = list(_DIR_CACHE.glob("*.json"))
    except OSError:
        return
    ahora = time.time()
    vivas = []
    for f in entradas:
        try:
            if ahora - f.stat().st_mtime >= _TTL_S:
                f.unlink(missing_ok=True)
            else:
                vivas.append(f)
        except OSError:
            continue
    if len(vivas) > _MAX_ENTRADAS:
        vivas.sort(key=lambda f: f.stat().st_mtime)
        for f in vivas[: len(vivas) - _MAX_ENTRADAS]:
            f.unlink(missing_ok=True)


def _escribir_cache(clave: str, datos: dict) -> None:
    """Escritura ATÓMICA: fichero temporal en el mismo directorio y `os.replace`.

    `write_text` no es atómico. Dos fallos de caché simultáneos sobre la misma consulta se
    entrelazaban y un lector veía un JSON truncado. `os.replace` dentro del mismo sistema de
    ficheros es atómico: el lector ve el contenido viejo o el nuevo, nunca uno a medias.
    """
    _DIR_CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
    destino = _ruta(clave)
    fd, temporal = tempfile.mkstemp(dir=_DIR_CACHE, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False)
        os.replace(temporal, destino)
    except OSError:
        Path(temporal).unlink(missing_ok=True)  # la caché es opcional: nunca romper la petición
        return
    _podar_cache()


# Sin guarda de sesión a propósito: la búsqueda en PubMed no es sensible ni consume la
# cuota de IA. Basta con rate limiting para evitar abuso (ver PLAN_MODERNIZACION.md, Fase 5).
@router.get("/papers")
@limiter.limit(obtener_config().limite_papers)
async def get_papers(
    request: Request,
    query: str = Query(..., min_length=1, max_length=300),
) -> dict:
    consulta = query.strip()
    clave = f"pm:{consulta}"
    if (cacheado := _leer_cache(clave)) is not None:
        if _CLAVE_FALLO in cacheado:
            # NCBI falló hace poco para esta misma consulta. Se responde igual que entonces, al
            # instante, sin pagar otra vez el timeout ni añadir una petición más a un servicio
            # que ya está teniendo un mal rato. `Retry-After` para que el cliente lo sepa.
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                cacheado[_CLAVE_FALLO],
                headers={"Retry-After": str(_TTL_FALLO_S)},
            )
        return cacheado

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    async with httpx.AsyncClient(timeout=15, headers=_CABECERAS) as cliente:
        try:
            r1 = await cliente.get(
                f"{base}/esearch.fcgi",
                params={"db": "pubmed", "retmode": "json", "retmax": 100, "term": consulta},
            )
            r1.raise_for_status()
            ids = r1.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                salida = {"total": 0, "data": []}
                _escribir_cache(clave, salida)
                return salida

            r2 = await cliente.get(
                f"{base}/esummary.fcgi",
                params={"db": "pubmed", "retmode": "json", "id": ",".join(ids)},
            )
            r2.raise_for_status()
        except httpx.HTTPError as exc:
            # Caché NEGATIVA. Cubre por igual timeout, error de conexión y respuesta de error de
            # NCBI (incluido su 429): en los tres casos repetir de inmediato no puede ir mejor y
            # sí empeora las cosas. Es la única escritura de caché que ocurre en el camino de
            # error, y se hace ANTES de levantar el 502 para que la siguiente petición ya la vea.
            mensaje = "No se pudo contactar PubMed."
            _escribir_cache(clave, {_CLAVE_FALLO: mensaje})
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, mensaje, headers={"Retry-After": str(_TTL_FALLO_S)}
            ) from exc

    resultado = r2.json().get("result", {})
    papers = []
    for uid in resultado.get("uids", ids):
        p = resultado.get(uid)
        if not p:
            continue
        anio = ""
        if p.get("pubdate"):
            m = re.search(r"\d{4}", p["pubdate"])
            anio = m.group(0) if m else ""
        doi = next((a["value"] for a in p.get("articleids", []) if a.get("idtype") == "doi"), "")
        papers.append(
            {
                "pmid": uid,
                "title": p.get("title", "Sin título"),
                "authors": [{"name": a["name"]} for a in p.get("authors", [])],
                "year": anio,
                "doi": doi,
                "journal": p.get("source", ""),
            }
        )

    salida = {"total": len(papers), "data": papers}
    _escribir_cache(clave, salida)
    return salida
