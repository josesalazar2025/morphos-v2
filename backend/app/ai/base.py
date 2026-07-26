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
    """

    def __init__(self, mensaje: str, *, reintentable: bool = True, saturado: bool = False) -> None:
        super().__init__(mensaje)
        self.reintentable = reintentable
        self.saturado = saturado


class ClienteModelo(Protocol):
    nombre: str

    async def interpretar(
        self,
        sistema: str,
        mensaje_usuario: str,
        imagenes: list[str],
    ) -> InterpretacionClinica:
        """Devuelve una interpretación validada o lanza ErrorModelo."""
        ...
