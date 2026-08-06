"""Configuración de las pruebas unitarias de los scripts de evaluación.

Los scripts de `evals/` son ejecutables, no un paquete instalado: cada uno se apaña su
`sys.path` al arrancar (backend + el propio directorio) para poder importar `app.*` y
`judge.*`. Aquí se hace lo mismo antes de importarlos, para que las pruebas corran igual
desde `backend/` (donde vive pytest) que desde la raíz.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1]
RAIZ = EVALS.parent

for ruta in (str(RAIZ / "backend"), str(EVALS)):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

# Igual que backend/tests/conftest.py: la config se cachea con lru_cache, así que estas
# variables tienen que existir ANTES de que cualquier import arrastre `app.config`. Y por el
# mismo motivo que allí, el `.env` del desarrollador queda fuera: estas pruebas también corren
# en CI, donde no existe.
os.environ["MORPHOS_IGNORAR_ENV_FILE"] = "1"
_TMP = Path(tempfile.mkdtemp(prefix="morphos_evals_test_"))
os.environ.setdefault("MORPHOS_DB_PATH", str(_TMP / "test.db"))
os.environ.setdefault("MORPHOS_SESSION_SECRET", "x" * 40)
os.environ.setdefault("MORPHOS_ENTORNO", "dev")
