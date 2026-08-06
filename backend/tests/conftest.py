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

# Debe fijarse ANTES de importar la config (que se cachea con lru_cache).
os.environ["MORPHOS_IGNORAR_ENV_FILE"] = "1"
_TMP = Path(tempfile.mkdtemp(prefix="morphos_test_"))
os.environ.setdefault("MORPHOS_DB_PATH", str(_TMP / "test.db"))
os.environ.setdefault("MORPHOS_SESSION_SECRET", "x" * 40)
os.environ.setdefault("MORPHOS_ENTORNO", "dev")
