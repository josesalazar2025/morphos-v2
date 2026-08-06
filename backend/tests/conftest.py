"""Configuración de pruebas: BD temporal, secreto determinista y cero herencia del entorno.

Las pruebas describen el comportamiento POR DEFECTO del servicio, así que no pueden leer el
`.env` del desarrollador: en CI ese fichero no existe y en local trae lo que cada uno tenga
puesto. Con `MORPHOS_IGNORAR_ENV_FILE` la config lo salta y sólo obedece a lo que se fije aquí,
que es lo que hace reproducible el resultado entre máquinas.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Debe fijarse ANTES de importar la config (que se cachea con lru_cache).
os.environ["MORPHOS_IGNORAR_ENV_FILE"] = "1"
_TMP = Path(tempfile.mkdtemp(prefix="morphos_test_"))
os.environ.setdefault("MORPHOS_DB_PATH", str(_TMP / "test.db"))
os.environ.setdefault("MORPHOS_SESSION_SECRET", "x" * 40)
os.environ.setdefault("MORPHOS_ENTORNO", "dev")


@pytest.fixture(autouse=True)
def _limitador_limpio():
    """Vacía el contador de rate limiting entre pruebas.

    El limitador es un almacén en memoria de proceso (`security/rate_limit.py`) compartido por
    toda la suite, y el TestClient sale siempre desde la misma IP ('testclient'), así que los
    contadores se acumulan de una prueba a otra: `limite_login` (5/minute) cubre también
    `/api/auth/registro`, y bastaba añadir pruebas de alta para que otras empezaran a recibir
    429 según el ORDEN en que corrieran. Resetear aquí hace que cada prueba mida lo suyo.
    """
    from app.security.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def alta_abierta(monkeypatch):
    """Abre el alta de cuentas para las pruebas que sólo necesitan una sesión.

    El alta está CERRADA por defecto y así se queda en el resto de la suite: eso es lo que
    comprueban las pruebas de `test_registro_cerrado.py`. Las que sólo quieren llegar a otro
    endpoint piden este fixture en vez de repetir el monkeypatch.
    """
    from app.config import obtener_config

    monkeypatch.setattr(obtener_config(), "registro_abierto", True)
