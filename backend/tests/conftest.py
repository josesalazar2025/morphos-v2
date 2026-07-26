"""Configuración de pruebas: BD temporal y secreto de sesión determinista."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Debe fijarse ANTES de importar la config (que se cachea con lru_cache).
_TMP = Path(tempfile.mkdtemp(prefix="morphos_test_"))
os.environ.setdefault("MORPHOS_DB_PATH", str(_TMP / "test.db"))
os.environ.setdefault("MORPHOS_SESSION_SECRET", "x" * 40)
os.environ.setdefault("MORPHOS_ENTORNO", "dev")
