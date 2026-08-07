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

**Sólo lo alimenta `saturado`, y es lo importante del diseño.** Una salida malformada, un
razonamiento filtrado o un 500 puntual son problemas de ESA petición y el reintento correctivo
existe justo para ellos: contarlos aquí convertiría un modelo con un mal día en una caída total
de la funcionalidad. Lo que se protege es un recurso compartido y escaso, no la disponibilidad
en general.

Limitación conocida y heredada: el estado es de PROCESO, como el limitador de tasa y el almacén
de laboratorio (§3.2). Con dos workers habría dos cortacircuitos, cada uno con su cuenta. El
despliegue está fijado a uno solo; el día que deje de estarlo, esto se va a Redis con el resto.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from ..config import obtener_config

log = logging.getLogger("morphos.ia.cortacircuitos")


class Cortacircuitos:
    """Cerrado → abierto → (pasada la ventana) sondeo → cerrado o abierto otra vez.

    `reloj` se inyecta para que las pruebas puedan viajar en el tiempo en vez de dormir.
    """

    def __init__(self, fallos_para_abrir: int, espera_s: int, reloj=time.monotonic) -> None:
        self._fallos_para_abrir = fallos_para_abrir
        self._espera_s = espera_s
        self._reloj = reloj
        self._fallos = 0
        self._reapertura: float | None = None
        self._sondeando = False

    @property
    def activo(self) -> bool:
        """Con `fallos_para_abrir <= 0` el mecanismo queda desconectado (válvula de escape)."""
        return self._fallos_para_abrir > 0

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
        if self._fallos or self._reapertura is not None:
            log.info("Cortacircuitos IA: el modelo responde, se cierra.")
        self._fallos = 0
        self._reapertura = None
        self._sondeando = False

    def registrar_saturacion(self) -> None:
        """Un fallo POR CUOTA. Cualquier otro tipo de error no llega hasta aquí."""
        if not self.activo:
            return
        # Si esto era el sondeo, el recurso sigue sin volver: se reabre sin esperar a acumular
        # más fallos, porque ya se sabía que estaba agotado.
        if self._sondeando:
            self._sondeando = False
            self._abrir()
            return
        self._fallos += 1
        if self._fallos >= self._fallos_para_abrir:
            self._abrir()

    def _abrir(self) -> None:
        self._reapertura = self._reloj() + self._espera_s
        log.warning(
            "Cortacircuitos IA ABIERTO tras %d saturación(es): no se llama al modelo durante %d s.",
            self._fallos, self._espera_s,
        )

    def reiniciar(self) -> None:
        """Vuelve al estado inicial. Para las pruebas; en producción no hay motivo para llamarlo."""
        self._fallos = 0
        self._reapertura = None
        self._sondeando = False


@lru_cache(maxsize=1)
def cortacircuitos_ia() -> Cortacircuitos:
    cfg = obtener_config()
    return Cortacircuitos(cfg.ia_breaker_fallos, cfg.ia_breaker_espera_s)
