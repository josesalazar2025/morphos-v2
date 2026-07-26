"""Interfaz común de los clientes de modelo.

Abstrae la ruta híbrida: medGemma auto-alojado (privado por defecto) y Claude (opcional,
mayor precisión). Ambos deben devolver una InterpretacionClinica validada; la validación
de esquema vive en cada cliente para poder reintentar ante salida malformada.
"""

from __future__ import annotations

from typing import Protocol

from ..schemas import InterpretacionClinica


class ErrorModelo(Exception):
    """Fallo recuperable/no recuperable al invocar un modelo o validar su salida."""


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
