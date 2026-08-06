"""Caché en disco de /api/papers: atómica, tolerante a basura y acotada.

Tres fallos que tenía: `write_text` no es atómico (dos fallos de caché simultáneos sobre la
misma consulta se entrelazaban y un lector veía JSON truncado → 500 sin `try`), el TTL sólo se
miraba al LEER (una consulta que no se repite dejaba su fichero para siempre) y el directorio
en `gettempdir()` se reutilizaba aunque lo hubiera creado otro usuario del host.
"""

from __future__ import annotations

import json
import os
import time

from app.routers import papers


def _limpiar():
    if papers._DIR_CACHE.exists():
        for f in papers._DIR_CACHE.glob("*"):
            f.unlink(missing_ok=True)


def test_ida_y_vuelta():
    _limpiar()
    papers._escribir_cache("pm:anemia", {"resultados": [1, 2, 3]})
    assert papers._leer_cache("pm:anemia") == {"resultados": [1, 2, 3]}


def test_fichero_truncado_es_fallo_de_cache_no_un_500():
    """El caso real: `json.loads` sobre un fichero a medio escribir tumbaba la petición."""
    _limpiar()
    papers._escribir_cache("pm:x", {"a": 1})
    papers._ruta("pm:x").write_text('{"a": ', encoding="utf-8")  # JSON cortado

    assert papers._leer_cache("pm:x") is None
    # Y se borra: si no, se releería basura hasta que caduque.
    assert not papers._ruta("pm:x").exists()


def test_entrada_caducada_no_se_sirve():
    _limpiar()
    papers._escribir_cache("pm:viejo", {"a": 1})
    viejo = time.time() - papers._TTL_S - 10
    os.utime(papers._ruta("pm:viejo"), (viejo, viejo))
    assert papers._leer_cache("pm:viejo") is None


def test_la_poda_borra_lo_caducado():
    """El TTL se comprobaba sólo al leer, así que el directorio crecía sin tope."""
    _limpiar()
    for i in range(5):
        papers._escribir_cache(f"pm:{i}", {"i": i})
    viejo = time.time() - papers._TTL_S - 10
    for i in range(3):
        os.utime(papers._ruta(f"pm:{i}"), (viejo, viejo))

    papers._podar_cache()

    vivas = list(papers._DIR_CACHE.glob("*.json"))
    assert len(vivas) == 2


def test_la_escritura_no_deja_temporales():
    """`os.replace` mueve el temporal; si quedara, el directorio crecería igual."""
    _limpiar()
    papers._escribir_cache("pm:limpio", {"a": 1})
    assert list(papers._DIR_CACHE.glob("*.tmp")) == []
    assert len(list(papers._DIR_CACHE.glob("*.json"))) == 1


def test_un_lector_nunca_ve_un_json_a_medias(monkeypatch):
    """Con escritura atómica, mientras se escribe la nueva entrada se sigue leyendo la vieja.

    Se simula la ventana de entrelazado: durante `json.dump` del segundo escritor, un lector
    consulta la misma clave. Sin `os.replace` vería el fichero destino truncado.
    """
    _limpiar()
    papers._escribir_cache("pm:carrera", {"version": "vieja"})
    leido_durante_la_escritura = {}

    volcado_real = json.dump

    def _volcado_que_lee_a_la_vez(datos, fh, **kw):
        volcado_real(datos, fh, **kw)
        fh.flush()
        leido_durante_la_escritura["valor"] = papers._leer_cache("pm:carrera")

    monkeypatch.setattr(papers.json, "dump", _volcado_que_lee_a_la_vez)
    papers._escribir_cache("pm:carrera", {"version": "nueva"})

    assert leido_durante_la_escritura["valor"] == {"version": "vieja"}
    assert papers._leer_cache("pm:carrera") == {"version": "nueva"}


def test_el_directorio_es_privado_y_propio():
    """0700 y con el uid en el nombre: `exist_ok=True` sobre un directorio ajeno lo habría usado."""
    _limpiar()
    papers._escribir_cache("pm:permisos", {"a": 1})
    assert str(os.getuid()) in papers._DIR_CACHE.name
    assert (papers._DIR_CACHE.stat().st_mode & 0o777) == 0o700
