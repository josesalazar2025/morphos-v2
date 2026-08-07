"""GET /api/papers — búsqueda en PubMed con caché en disco.

Porta la lógica de papers_proxy.php (esearch + esummary + caché 30 min) pero ahora
protegida con sesión y rate limiting.
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
        if (time.time() - archivo.stat().st_mtime) >= _TTL_S:
            return None
        return json.loads(archivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        archivo.unlink(missing_ok=True)  # corrupta: que no se relea eternamente
        return None


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
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se pudo contactar PubMed.") from exc

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
