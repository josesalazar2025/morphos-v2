"""Interfaz común de los clientes de modelo.

Abstrae la ruta híbrida: medGemma auto-alojado (privado por defecto) y Claude (opcional,
mayor precisión). Ambos deben devolver una InterpretacionClinica validada; la validación
de esquema vive en cada cliente para poder reintentar ante salida malformada.
"""

from __future__ import annotations

from typing import Protocol

from ..schemas import InterpretacionClinica


class ErrorModelo(Exception):
    """Fallo al invocar un modelo o validar su salida.

    `reintentable` decide si el servicio vuelve a muestrear. La distinción importa de verdad:
    el reintento existe para la salida malformada de medGemma (razonamiento filtrado o bucle de
    repetición), donde volver a muestrear suele funcionar. Reintentar un 429 hace lo contrario —
    duplica la presión sobre la cuota de ZeroGPU, que es justo el recurso agotado— y reintentar
    un rechazo por seguridad o una clave mal configurada no puede cambiar nada.

    `saturado` marca los casos de límite de tasa/cuota, para poder responder 503 + Retry-After
    en vez de un 502 genérico.

    `truncado` marca la respuesta cortada a mitad de frase. Es reintentable, pero repetir la
    misma petición no sirve: se ha medido que el corte es determinista y lo provoca el
    contexto RAG comiéndose el presupuesto de generación del Space. El servicio lo usa para
    reintentar con MENOS literatura en vez de con el mismo prompt.

    `espera_s` es cuánto falta para que valga la pena reintentar, cuando se sabe. Lo rellena el
    cortacircuitos, que es lo único que conoce el dato real; el resto de casos deja el valor por
    defecto del router. Sirve para no responder «vuelve en 5 minutos» cuando faltan 20 segundos.
    """

    def __init__(
        self,
        mensaje: str,
        *,
        reintentable: bool = True,
        saturado: bool = False,
        truncado: bool = False,
        espera_s: int | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.reintentable = reintentable
        self.saturado = saturado
        self.truncado = truncado
        self.espera_s = espera_s


class ClienteModelo(Protocol):
    nombre: str
    modelo: str
    # True si el cliente devuelve TEXTO libre envuelto en `interpretacion` en vez de rellenar
    # los campos estructurados. El servicio lo consulta para elegir el system prompt, para no
    # exigir campos que esta ruta no puede rellenar y para suplir `requiere_derivacion` desde
    # el motor determinista. Antes se deducía del nombre del cliente, que dejó de bastar en
    # cuanto la prosa pudo venir también de un modelo local.
    prosa: bool

    async def interpretar(
        self,
        sistema: str,
        mensaje_usuario: str,
        imagenes: list[str],
    ) -> InterpretacionClinica:
        """Devuelve una interpretación validada o lanza ErrorModelo."""
        ...
