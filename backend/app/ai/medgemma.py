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
from .prosa import interpretacion_desde_prosa

_DATA_URL = re.compile(r"^data:image/(?:jpeg|png|gif|webp);base64,(.+)$", re.DOTALL)


def _base64_imagenes(imagenes: list[str]) -> list[str]:
    salida = []
    for img in imagenes:
        m = _DATA_URL.match(img)
        if m:
            salida.append(m.group(1))
    return salida


class MedGemmaClient:
    """Cliente de Ollama. `modelo` lo puede fijar el usuario desde la UI, pero SÓLO con un
    nombre ya validado contra la lista blanca (`PeticionInterpretacion.modelo_local`); la
    base_url nunca sale de la configuración del servidor.

    `prosa` desactiva la decodificación restringida para los modelos que la aceptan pero la
    rellenan en hueco (ver `config.modelos_locales`). El nombre distinto NO es cosmético: el
    servicio decide por `prosa` si usa el system prompt de prosa, si exige campos
    estructurados y si suple `requiere_derivacion`.
    """

    def __init__(self, modelo: str | None = None, *, prosa: bool = False) -> None:
        cfg = obtener_config()
        self._url = cfg.medgemma_base_url.rstrip("/")
        self.modelo = modelo or cfg.medgemma_model
        self.prosa = prosa
        self.nombre = "medgemma-prosa" if prosa else "medgemma"
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
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema}, mensaje_user],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2, "num_predict": 1500},
        }
        if not self.prosa:
            payload["format"] = self._esquema  # salida estructurada nativa de Ollama

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
                tiempo_agotado=True,
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
        if self.prosa:
            return interpretacion_desde_prosa(contenido)
        try:
            return InterpretacionClinica.model_validate_json(contenido)
        except Exception as exc:  # noqa: BLE001
            raise ErrorModelo(f"Salida de {self.modelo} no valida el esquema: {exc}") from exc
