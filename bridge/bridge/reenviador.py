"""Reenviador HTTPS: envía resultados a POST /api/lab/ingesta con fiabilidad.

- Cola en disco (spool): cada resultado se escribe a un fichero ANTES de intentar el envío,
  así nada se pierde si Morphos/HF está momentáneamente inalcanzable.
- Reintentos con backoff exponencial ante errores de red.
- Idempotencia: cada mensaje lleva un id de cliente; el almacén del backend es "último gana"
  por muestra, así que un reenvío no duplica.
- Códigos no recuperables por reintento inmediato: 401/403/503 se dejan en spool (se
  reintentan al re-drenar); 422 (payload inválido) se aparta a `.rechazado` para no repetir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

from .modelo import Resultado

log = logging.getLogger("bridge.reenviador")


class Reenviador:
    def __init__(
        self,
        morphos_url: str,
        api_key: str,
        spool_dir: str,
        verify_tls: bool = True,
        max_reintentos: int = 5,
        cliente: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._url = morphos_url.rstrip("/") + "/api/lab/ingesta"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._spool = Path(spool_dir)
        self._spool.mkdir(parents=True, exist_ok=True)
        self._max = max_reintentos
        self._cliente = cliente or httpx.AsyncClient(timeout=15.0, verify=verify_tls)

    async def cerrar(self) -> None:
        await self._cliente.aclose()

    async def enviar(self, res: Resultado) -> None:
        mensaje_id = uuid.uuid4().hex
        ruta = self._spool / f"{mensaje_id}.json"
        cuerpo = {"mensaje_id": mensaje_id, "payload": res.payload()}
        ruta.write_text(json.dumps(cuerpo, ensure_ascii=False), encoding="utf-8")
        await self._intentar(ruta)

    async def drenar_spool(self) -> None:
        for ruta in sorted(self._spool.glob("*.json")):
            await self._intentar(ruta)

    async def _intentar(self, ruta: Path) -> None:
        try:
            cuerpo = json.loads(ruta.read_text(encoding="utf-8"))
            payload = cuerpo["payload"]
        except (OSError, json.JSONDecodeError, KeyError):
            log.warning("spool ilegible, se aparta: %s", ruta.name)
            ruta.rename(ruta.with_suffix(".rechazado"))
            return

        espera = 1.0
        for intento in range(1, self._max + 1):
            try:
                r = await self._cliente.post(self._url, json=payload, headers=self._headers)
                if r.status_code == 200:
                    ruta.unlink(missing_ok=True)
                    log.info("ingesta OK muestra=%s", payload.get("muestra_id"))
                    return
                if r.status_code == 422:
                    log.warning("payload rechazado (422), se aparta: %s", ruta.name)
                    ruta.rename(ruta.with_suffix(".rechazado"))
                    return
                if r.status_code in (401, 403, 503):
                    log.warning("ingesta %s (auth/config); queda en spool para reintentar", r.status_code)
                    return
                log.warning("respuesta inesperada %s: %s", r.status_code, r.text[:200])
            except httpx.HTTPError as exc:
                log.warning("error de red (intento %s/%s): %s", intento, self._max, exc)
            await asyncio.sleep(espera)
            espera = min(espera * 2, 30)
        log.warning("agotados los reintentos; queda en spool: %s", ruta.name)
