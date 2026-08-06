"""IP de cliente detrás de un proxy inverso.

`request.client.host` detrás de un proxy es el PROXY. Con eso, `limite_login` (5/minute) y
`limite_papers` dejaban de ser por IP y pasaban a ser globales: bypass de la fuerza bruta (muchas
IPs, un solo contador) y auto-DoS (un cliente ruidoso agota el login de todos) a la vez.

La cabecera NO puede creerse a ciegas: la manda el cliente. Estas pruebas fijan las dos mitades
—se usa cuando el operador declara los saltos, se ignora cuando no— porque equivocarse en
cualquiera de ellas es un agujero.
"""

from __future__ import annotations

import pytest

from app.config import obtener_config
from app.security.rate_limit import ip_cliente


class _PeticionFalsa:
    """Lo mínimo que `ip_cliente` mira: cabeceras y peer directo."""

    def __init__(self, xff: str | None, peer: str = "10.0.0.1"):
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = type("C", (), {"host": peer})()


@pytest.fixture
def saltos(monkeypatch):
    def _fijar(n: int):
        monkeypatch.setattr(obtener_config(), "proxy_saltos_confiables", n)

    return _fijar


def test_sin_proxy_declarado_se_ignora_la_cabecera(saltos):
    """El defecto: `X-Forwarded-For` la pone cualquiera, así que sin declarar proxy no vale nada."""
    saltos(0)
    assert ip_cliente(_PeticionFalsa("1.2.3.4", peer="10.0.0.1")) == "10.0.0.1"


def test_un_salto_toma_la_ultima_entrada(saltos):
    """Con un proxy delante, la entrada que él añadió es la del cliente real."""
    saltos(1)
    assert ip_cliente(_PeticionFalsa("203.0.113.9", peer="10.0.0.1")) == "203.0.113.9"


def test_no_se_deja_falsificar_anteponiendo_entradas(saltos):
    """El atacante controla lo que va a la IZQUIERDA; sólo cuenta lo que escribió el proxy.

    Es el fallo clásico de coger `xff[0]`: bastaría mandar `X-Forwarded-For: <lo-que-sea>` para
    estrenar contador de rate limiting en cada petición.
    """
    saltos(1)
    falsa = _PeticionFalsa("6.6.6.6, 203.0.113.9", peer="10.0.0.1")
    assert ip_cliente(falsa) == "203.0.113.9"


def test_dos_saltos_saltan_el_cdn(saltos):
    """Cliente → CDN → proxy → app: el cliente es el penúltimo."""
    saltos(2)
    peticion = _PeticionFalsa("203.0.113.9, 198.51.100.7", peer="10.0.0.1")
    assert ip_cliente(peticion) == "203.0.113.9"


def test_cadena_mas_corta_de_lo_declarado_cae_al_peer(saltos):
    """La petición no vino por la cadena esperada: mejor el peer directo que un valor del cliente."""
    saltos(2)
    assert ip_cliente(_PeticionFalsa("203.0.113.9", peer="10.0.0.1")) == "10.0.0.1"
    assert ip_cliente(_PeticionFalsa(None, peer="10.0.0.1")) == "10.0.0.1"


def test_tolera_espacios_y_entradas_vacias(saltos):
    saltos(1)
    assert ip_cliente(_PeticionFalsa(" 6.6.6.6 ,  , 203.0.113.9 ")) == "203.0.113.9"
