"""Almacén en proceso de resultados de analizador, emparejados por ID de muestra.

Segmentado por TENANT: cada resultado lleva la clínica dueña y las lecturas la exigen. Antes era
un dict global y cualquier sesión autenticada podía leer la muestra de cualquier clínica.

Deliberadamente NO es SQLite: HF Spaces tiene disco efímero, un único worker de uvicorn, y
los resultados son de vida corta (se emparejan con el formulario en minutos). Un dict con
TTL + tope LRU es la primitiva correcta. Clave normalizada (trim + minúsculas) en lectura y
escritura. Si algún día se añaden workers, este almacén deja de ser correcto y hay que
moverlo a SQLite/caché compartida (ver `lab_persistir` en config).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from ..schemas_lab import ResultadoMapeado

TTL_SEGUNDOS = 24 * 3600
MAX_ENTRADAS = 500


def _clave(muestra_id: str) -> str:
    return muestra_id.strip().lower()


class AlmacenResultados:
    def __init__(self, ttl: int = TTL_SEGUNDOS, max_entradas: int = MAX_ENTRADAS) -> None:
        self._ttl = ttl
        self._max = max_entradas
        self._lock = threading.Lock()
        # clave → (instante_monotónico, resultado). OrderedDict para desalojo LRU.
        self._datos: OrderedDict[str, tuple[float, ResultadoMapeado]] = OrderedDict()

    def guardar(self, res: ResultadoMapeado) -> None:
        with self._lock:
            k = _clave(res.muestra_id)
            self._datos[k] = (time.monotonic(), res)  # último gana
            self._datos.move_to_end(k)
            self._barrer_locked()
            while len(self._datos) > self._max:
                self._datos.popitem(last=False)  # desaloja el más antiguo

    def obtener(self, muestra_id: str, tenant: str) -> ResultadoMapeado | None:
        """Resultado de ESE tenant, o None. Un ID de otra clínica se comporta como inexistente.

        El tenant es obligatorio a propósito: si fuera opcional, olvidarlo en una llamada nueva
        devolvería datos de todas las clínicas en silencio, que es justo el fallo que esto cierra.
        """
        with self._lock:
            self._barrer_locked()
            item = self._datos.get(_clave(muestra_id))
            if item is None or item[1].tenant != tenant:
                return None
            return item[1]

    def pendientes(self, tenant: str) -> list[ResultadoMapeado]:
        """Cola de ESE tenant, más recientes primero."""
        with self._lock:
            self._barrer_locked()
            return [r for (_, r) in reversed(self._datos.values()) if r.tenant == tenant]

    def _barrer_locked(self) -> None:
        ahora = time.monotonic()
        expiradas = [k for k, (t, _) in self._datos.items() if ahora - t > self._ttl]
        for k in expiradas:
            del self._datos[k]


# Singleton de módulo importado por routers/lab.py.
almacen = AlmacenResultados()
