"""Fiabilidad del reenviador: spool, éxito borra, error de red conserva, 422 aparta."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from bridge.modelo import Observacion, Resultado
from bridge.reenviador import Reenviador


def _resultado():
    return Resultado(
        muestra_id="M-1",
        instrumento_id="t-1",
        observaciones=[Observacion(codigo_prueba="GLU", valor="90", unidad="mg/dL")],
        momento=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )


def _reenviador(tmp_path, handler):
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Reenviador("http://x", "k", str(tmp_path), cliente=cliente)


async def test_exito_borra_del_spool(tmp_path):
    def handler(req):
        return httpx.Response(200, json={"ok": True})

    r = _reenviador(tmp_path, handler)
    await r.enviar(_resultado())
    await r.cerrar()
    assert list(tmp_path.glob("*.json")) == []


async def test_error_de_red_conserva_en_spool(tmp_path):
    def handler(req):
        raise httpx.ConnectError("sin red")

    r = _reenviador(tmp_path, handler)
    r._max = 1  # no esperar reintentos largos en el test
    await r.enviar(_resultado())
    await r.cerrar()
    assert len(list(tmp_path.glob("*.json"))) == 1  # sigue pendiente


async def test_422_se_aparta(tmp_path):
    def handler(req):
        return httpx.Response(422, json={"detail": "malo"})

    r = _reenviador(tmp_path, handler)
    await r.enviar(_resultado())
    await r.cerrar()
    assert list(tmp_path.glob("*.json")) == []
    assert len(list(tmp_path.glob("*.rechazado"))) == 1


async def test_drenar_spool_reenvia_pendientes(tmp_path):
    estado = {"fallar": True}

    def handler(req):
        if estado["fallar"]:
            raise httpx.ConnectError("sin red")
        return httpx.Response(200, json={"ok": True})

    r = _reenviador(tmp_path, handler)
    r._max = 1
    await r.enviar(_resultado())
    assert len(list(tmp_path.glob("*.json"))) == 1

    estado["fallar"] = False
    await r.drenar_spool()
    await r.cerrar()
    assert list(tmp_path.glob("*.json")) == []
