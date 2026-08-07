"""La CSP no vuelve a llevar 'unsafe-inline', y el frontend no la necesita.

`style-src` lo tuvo hasta el 2026-08-07. Era el único hueco de una política por lo demás
estricta, y no es teórico: con estilo inline permitido, cualquier marcado que se cuele en la
página puede exfiltrar por selectores CSS (`input[value^="a"] {background: url(...)}`) sin
ejecutar un solo script, así que `script-src 'self'` no lo tapa.

Estas pruebas fijan las DOS mitades, porque quitar la directiva sin comprobar la precondición
rompería el estilo de la app en producción y sin error visible en desarrollo:

1. La cabecera que se sirve no contiene 'unsafe-inline' en ninguna directiva.
2. `index.html` no tiene estilo inline que dependiera de ella.

Lo que NO restringe la CSP —y por eso el frontend sigue funcionando— es el CSSOM:
`el.style.height = ...` y `style.setProperty(...)` están fuera de su alcance; sólo se bloquean
el atributo `style` del marcado y los bloques `<style>`.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import RAIZ_REPO
from app.main import crear_app


@pytest.fixture(scope="module")
def cliente() -> TestClient:
    return TestClient(crear_app())


def _directivas(csp: str) -> dict[str, str]:
    salida = {}
    for trozo in csp.split(";"):
        if trozo.strip():
            nombre, _, valor = trozo.strip().partition(" ")
            salida[nombre] = valor
    return salida


def test_ninguna_directiva_permite_inline(cliente: TestClient):
    csp = cliente.get("/api/health").headers["Content-Security-Policy"]

    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp


def test_style_src_solo_mismo_origen(cliente: TestClient):
    directivas = _directivas(cliente.get("/api/health").headers["Content-Security-Policy"])

    assert directivas["style-src"] == "'self'"


def test_el_worker_de_pdfjs_sigue_permitido(cliente: TestClient):
    """`worker-src blob:` es la excepción que SÍ hace falta: sin ella el import de PDF cae."""
    directivas = _directivas(cliente.get("/api/health").headers["Content-Security-Policy"])

    assert "blob:" in directivas["worker-src"]


def test_index_no_tiene_estilo_inline():
    """La precondición: si alguien añade un `style="..."`, esta prueba avisa ANTES de que la
    página salga a producción con el estilo silenciosamente bloqueado."""
    html = (RAIZ_REPO / "index.html").read_text(encoding="utf-8")

    assert 'style="' not in html
    assert "style='" not in html
    assert not re.search(r"<style[\s>]", html, re.IGNORECASE)


def test_el_frontend_no_escribe_el_atributo_style():
    """`el.style.x = ...` (CSSOM) es legal bajo la CSP; `setAttribute('style', ...)` NO.

    La distinción es sutil y se pierde fácil al refactorizar, así que se fija aquí.
    """
    infractores = []
    for ruta in (RAIZ_REPO / "frontend" / "src").rglob("*.ts"):
        texto = ruta.read_text(encoding="utf-8")
        if re.search(r"""setAttribute\(\s*['"]style['"]""", texto):
            infractores.append(ruta.name)

    assert infractores == []
