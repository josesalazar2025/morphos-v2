"""GET /api/papers — búsqueda en PubMed con caché en disco.

Porta la lógica de papers_proxy.php (esearch + esummary + caché 30 min) pero ahora
protegida con sesión y rate limiting.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status

from ..config import obtener_config
from ..security.rate_limit import limiter

router = APIRouter()

_DIR_CACHE = Path(tempfile.gettempdir()) / "morphos_papers_cache"
_TTL_S = 1800
_CABECERAS = {"User-Agent": "Morphos/1.0 (mailto:ceo@equipamed.net)", "Accept": "application/json"}


def _leer_cache(clave: str) -> dict | None:
    archivo = _DIR_CACHE / f"{hashlib.md5(clave.encode()).hexdigest()}.json"
    if archivo.exists() and (time.time() - archivo.stat().st_mtime) < _TTL_S:
        return json.loads(archivo.read_text(encoding="utf-8"))
    return None


def _escribir_cache(clave: str, datos: dict) -> None:
    _DIR_CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
    archivo = _DIR_CACHE / f"{hashlib.md5(clave.encode()).hexdigest()}.json"
    archivo.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


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
