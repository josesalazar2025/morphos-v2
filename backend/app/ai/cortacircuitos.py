"""Cortacircuitos de la ruta de IA (ARCHITECTURE_REVIEW §1.5).

Qué problema resuelve, y cuál NO.

La cuota de ZeroGPU es compartida, se agota entera y tarda minutos en volver. Cuando eso pasa,
el servicio ya hacía lo correcto por petición: `hf_space.py` marca el error como
`saturado=True` y `reintentable=False` —reintentar gastaría otra reserva del mismo pozo vacío—
y el router responde 503 con `Retry-After`. Pero eso es una SUGERENCIA al cliente y nada más:
el estado no sobrevivía a la petición, así que el siguiente usuario volvía a descubrir el
agotamiento pagando su propia llamada, y el siguiente, y el siguiente. Con la ruta Claude cada
uno de esos descubrimientos cuesta dinero real.

El cortacircuitos recuerda. Tras `fallos_para_abrir` saturaciones deja de salir a la red durante
`espera_s` y responde igual de rápido, sin gastar nada. Pasada la ventana deja pasar UNA
petición de sondeo: si vuelve saturada, otra ventana; si va bien, se cierra.

**Lo alimentan DOS modos de fallo, y ninguno más. Eso es lo importante del diseño.** Una salida
malformada, un razonamiento filtrado o un 500 puntual son problemas de ESA petición y el
reintento correctivo existe justo para ellos: contarlos aquí convertiría un modelo con un mal día
en una caída total de la funcionalidad. Lo que se protege es un recurso compartido y escaso, no
la disponibilidad en general. Los dos que sí cuentan:

- **saturación** (`saturado`): no queda cuota. Umbral bajo (2) — un 429 aislado puede ser una
  ráfaga ajena en la cuenta compartida, dos seguidos ya no.
- **tiempo agotado** (`tiempo_agotado`): el modelo no contesta. Umbral más alto (3), porque un
  timeout suelto es más común que un 429 suelto. Es el modo de fallo MÁS caro y era el único que
  el cortacircuitos no veía: 120 s de espera × 2 intentos por petición, repetidos para cada
  usuario que llegue, sin que nada abriera el circuito.

Los dos contadores son INDEPENDIENTES: cada uno describe un problema distinto y sumarlos daría
un número sin significado. Un saturado seguido de dos timeouts no abre, y está bien que no abra:
ninguna de las dos señales ha llegado a ser concluyente por sí sola.

Limitación conocida y heredada: el estado es de PROCESO, como el limitador de tasa y el almacén
de laboratorio (§3.2). Con dos workers habría dos cortacircuitos, cada uno con su cuenta. El
despliegue está fijado a uno solo; el día que deje de estarlo, esto se va a Redis con el resto.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from ..config import obtener_config
from .base import ErrorModelo

log = logging.getLogger("morphos.ia.cortacircuitos")


class Cortacircuitos:
    """Cerrado → abierto → (pasada la ventana) sondeo → cerrado o abierto otra vez.

    `reloj` se inyecta para que las pruebas puedan viajar en el tiempo en vez de dormir.
    """

    def __init__(
        self,
        fallos_para_abrir: int,
        espera_s: int,
        timeouts_para_abrir: int = 3,
        reloj=time.monotonic,
    ) -> None:
        self._umbrales = {"saturacion": fallos_para_abrir, "timeout": timeouts_para_abrir}
        self._espera_s = espera_s
        self._reloj = reloj
        self._fallos = {"saturacion": 0, "timeout": 0}
        self._reapertura: float | None = None
        self._sondeando = False

    @property
    def activo(self) -> bool:
        """Con `fallos_para_abrir <= 0` el mecanismo queda desconectado (válvula de escape)."""
        return self._umbrales["saturacion"] > 0

    def permitir(self) -> bool:
        """¿Se puede llamar al modelo? Muta el estado: un True en ventana vencida es EL sondeo.

        No lleva lock: todas las transiciones ocurren en código síncrono, sin `await` de por
        medio, así que dos corrutinas no pueden interleaveearse dentro de este método. El
        `_sondeando` sí cruza un await —lo limpia quien informe del resultado— y ése es
        precisamente su cometido: que no salgan cien sondeos a la vez al vencer la ventana.
        """
        if not self.activo or self._reapertura is None:
            return True
        if self._reloj() < self._reapertura:
            return False
        if self._sondeando:
            return False  # ya hay una petición comprobando si el recurso volvió
        self._sondeando = True
        log.info("Cortacircuitos IA: ventana vencida, se deja pasar una petición de sondeo.")
        return True

    def segundos_restantes(self) -> int:
        if self._reapertura is None:
            return 0
        return max(0, int(round(self._reapertura - self._reloj())))

    def registrar_exito(self) -> None:
        if any(self._fallos.values()) or self._reapertura is not None:
            log.info("Cortacircuitos IA: el modelo responde, se cierra.")
        self.reiniciar()

    def registrar_saturacion(self) -> None:
        """No queda cuota (429 del router de HF o del Space)."""
        self._registrar("saturacion")

    def registrar_timeout(self) -> None:
        """El modelo no contestó a tiempo. El fallo más caro y el que más tarda en notarse."""
        self._registrar("timeout")

    def _registrar(self, tipo: str) -> None:
        if not self.activo:
            return
        # Si esto era el sondeo, el recurso sigue sin volver: se reabre sin esperar a acumular
        # más fallos, porque ya se sabía que estaba mal.
        if self._sondeando:
            self._sondeando = False
            self._abrir(tipo)
            return
        self._fallos[tipo] += 1
        if self._fallos[tipo] >= self._umbrales[tipo]:
            self._abrir(tipo)

    def _abrir(self, tipo: str) -> None:
        self._reapertura = self._reloj() + self._espera_s
        log.warning(
            "Cortacircuitos IA ABIERTO por %s (%d): no se llama al modelo durante %d s.",
            tipo, self._fallos[tipo], self._espera_s,
        )

    def reiniciar(self) -> None:
        """Vuelve al estado inicial. Para las pruebas; en producción no hay motivo para llamarlo."""
        self._fallos = dict.fromkeys(self._fallos, 0)
        self._reapertura = None
        self._sondeando = False


@lru_cache(maxsize=1)
def cortacircuitos_ia() -> Cortacircuitos:
    cfg = obtener_config()
    return Cortacircuitos(
        cfg.ia_breaker_fallos, cfg.ia_breaker_espera_s, cfg.ia_breaker_timeouts
    )


# --- Aforo (bulkhead) ------------------------------------------------------------------------
#
# Un cortacircuitos por sí solo llega TARDE bajo carga, y ése es su fallo clásico. Nada limitaba
# cuántas interpretaciones había en vuelo: diez peticiones concurrentes se encolan en el Space
# —ZeroGPU serializa de todas formas— y agotan el timeout las diez a la vez. El circuito abre
# DESPUÉS de haber quemado 10 × 120 s. El aforo es lo que impide llegar a esa situación: se
# rechaza rápido lo que excede en vez de dejarlo esperar a un recurso que ya está lleno.
#
# El contador basta y no hace falta `asyncio.Semaphore`: comprobar e incrementar ocurre en código
# síncrono, sin `await` de por medio, así que dos corrutinas no pueden colarse entre medias. Y a
# diferencia de un semáforo, aquí NO se quiere esperar turno: esperar es exactamente lo que
# provoca la avalancha.
_en_vuelo = 0


@contextmanager
def reservar_plaza() -> Iterator[None]:
    """Ocupa una plaza mientras dure la interpretación, o lanza si no queda ninguna."""
    global _en_vuelo
    maximo = obtener_config().ia_max_en_vuelo
    if maximo > 0 and _en_vuelo >= maximo:
        log.warning("Aforo de IA lleno (%d en vuelo); se rechaza sin llamar al modelo.", _en_vuelo)
        raise ErrorModelo(
            "Hay demasiadas interpretaciones en curso. Inténtalo en unos segundos.",
            reintentable=False,
            saturado=True,  # 503 + Retry-After, no 502: es transitorio y por carga
            espera_s=30,
        )
    _en_vuelo += 1
    try:
        yield
    finally:
        _en_vuelo -= 1


def en_vuelo() -> int:
    """Para las pruebas y para poder exponerlo cuando haya métricas (§3.5)."""
    return _en_vuelo
