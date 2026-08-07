"""Sesiones firmadas por cookie.

El caso importante aquí es el NEGATIVO: `leer_sesion` capturaba `(BadSignature, Exception)`, de
modo que cualquier error de programación se convertía en «no hay sesión» y salía como un 401
silencioso, ocultando el bug real. Estos tests fijan qué se traga y qué debe propagarse.
"""

from __future__ import annotations

import pytest

from app.security import session as ses


def test_ida_y_vuelta():
    token = ses.firmar_sesion({"email": "vet@example.com"})
    sesion = ses.leer_sesion(token)
    assert sesion["email"] == "vet@example.com"


def test_toda_sesion_nace_identificada_y_fechada():
    """`jti` y `emitida_en` los pone `firmar_sesion`, no quien llama.

    Son lo que hace revocable una sesión: sin `jti` no hay nada que nombrar para cerrar UNA, y
    sin `emitida_en` no se pueden cortar TODAS las de una cuenta por fecha. Si se generaran en
    quien llama, una ruta podría emitir por descuido una sesión irrevocable.
    """
    a = ses.leer_sesion(ses.firmar_sesion({"email": "vet@example.com"}))
    b = ses.leer_sesion(ses.firmar_sesion({"email": "vet@example.com"}))

    assert a["jti"] and b["jti"]
    assert a["jti"] != b["jti"], "dos sesiones con el mismo jti se revocarían juntas"
    assert a["emitida_en"]


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "no-es-un-token",
        "a.b.c",
        "eyJlbWFpbCI6ICJhdGFjYW50ZUBleGFtcGxlLmNvbSJ9.falsificado.firma",
    ],
)
def test_tokens_invalidos_devuelven_none(token):
    """Firma inválida, token corrupto o ausente → sin sesión, sin excepción."""
    assert ses.leer_sesion(token) is None


def test_firma_con_otro_secreto_no_valida(monkeypatch):
    """Una cookie firmada con otro secreto (p. ej. el fallback de dev) no debe abrir sesión:
    es exactamente el escenario de suplantación que evita MORPHOS_SESSION_SECRET."""
    token = ses.firmar_sesion({"email": "vet@example.com"})

    ses.obtener_config.cache_clear()
    monkeypatch.setenv("MORPHOS_SESSION_SECRET", "otro-secreto-completamente-distinto-1234567890")
    try:
        assert ses.leer_sesion(token) is None
    finally:
        ses.obtener_config.cache_clear()


def test_sesion_caducada_devuelve_none(monkeypatch):
    token = ses.firmar_sesion({"email": "vet@example.com"})

    ses.obtener_config.cache_clear()
    # -1 y no 0: itsdangerous compara `edad > max_age`, así que un token recién creado (edad 0)
    # con max_age=0 todavía es válido. Con -1 se dispara SignatureExpired, subclase de BadData,
    # que es la rama que interesa comprobar.
    monkeypatch.setenv("MORPHOS_SESSION_MAX_AGE_S", "-1")
    try:
        assert ses.leer_sesion(token) is None
    finally:
        ses.obtener_config.cache_clear()


def test_los_errores_de_programacion_se_propagan(monkeypatch):
    """El fallo que motiva estos tests: un error interno NO puede disfrazarse de «sin sesión».
    Si `loads` revienta por un bug, debe propagarse para que se vea, no devolver None."""

    class SerializadorRoto:
        def loads(self, *_args, **_kwargs):
            raise RuntimeError("fallo interno, no es una cookie inválida")

    monkeypatch.setattr(ses, "_serializer", lambda: SerializadorRoto())
    with pytest.raises(RuntimeError):
        ses.leer_sesion("cualquier-token")
