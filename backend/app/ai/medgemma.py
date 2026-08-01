"""Cliente medGemma auto-alojado (ruta privada por defecto).

Habla con Ollama por su API nativa /api/chat usando SALIDA ESTRUCTURADA: se pasa el
JSON Schema de InterpretacionClinica en el campo `format`, de modo que el modelo emite
JSON que valida contra Pydantic. Esto sustituye la inyección del token <unused95> y toda
la limpieza por regex de limpiarRespuesta.

Nota: se usa la plantilla de chat propia de Ollama (rol system/user), no concatenación
manual de tokens de control.
"""

from __future__ import annotations

import re

import httpx

from ..config import obtener_config
from ..schemas import InterpretacionClinica, esquema_estructurado
from .base import ErrorModelo

_DATA_URL = re.compile(r"^data:image/(?:jpeg|png|gif|webp);base64,(.+)$", re.DOTALL)


def _base64_imagenes(imagenes: list[str]) -> list[str]:
    salida = []
    for img in imagenes:
        m = _DATA_URL.match(img)
        if m:
            salida.append(m.group(1))
    return salida


class MedGemmaClient:
    nombre = "medgemma"

    def __init__(self) -> None:
        cfg = obtener_config()
        self._url = cfg.medgemma_base_url.rstrip("/")
        self._modelo = cfg.medgemma_model
        self._timeout = cfg.medgemma_timeout_s
        self._esquema = esquema_estructurado()

    async def interpretar(
        self, sistema: str, mensaje_usuario: str, imagenes: list[str]
    ) -> InterpretacionClinica:
        mensaje_user: dict = {"role": "user", "content": mensaje_usuario}
        b64 = _base64_imagenes(imagenes)
        if b64:
            mensaje_user["images"] = b64

        payload = {
            "model": self._modelo,
            "messages": [{"role": "system", "content": sistema}, mensaje_user],
            "format": self._esquema,  # salida estructurada nativa de Ollama
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2, "num_predict": 1500},
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as cliente:
                resp = await cliente.post(f"{self._url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            # Se distingue del fallo de conexión a propósito: varias excepciones de httpx se
            # convierten a cadena vacía, así que "No se pudo conectar: " mandaba a revisar la
            # red cuando lo que pasaba era que Ollama estaba cargando el modelo.
            raise ErrorModelo(
                f"medGemma no respondió en {self._timeout}s ({type(exc).__name__}). Si el modelo "
                "acaba de cambiar, la primera petición carga pesos y tarda: sube "
                "MORPHOS_MEDGEMMA_TIMEOUT_S o precarga el modelo.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ErrorModelo(
                f"No se pudo conectar con medGemma en {self._url}: {type(exc).__name__} {exc}"
            ) from exc

        if resp.status_code >= 400:
            raise ErrorModelo(
                f"medGemma devolvió HTTP {resp.status_code}: {resp.text[:200]}",
                reintentable=resp.status_code >= 500,
                saturado=resp.status_code == 429,
            )

        contenido = resp.json().get("message", {}).get("content", "")
        try:
            return InterpretacionClinica.model_validate_json(contenido)
        except Exception as exc:  # noqa: BLE001
            raise ErrorModelo(f"Salida de medGemma no valida el esquema: {exc}") from exc
