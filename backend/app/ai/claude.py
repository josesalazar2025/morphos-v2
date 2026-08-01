"""Cliente Claude (ruta híbrida opcional y juez de evals).

Usa salida estructurada vía 'tool use': se define una herramienta cuyo input_schema es
el JSON Schema de InterpretacionClinica y se fuerza su uso, de modo que el modelo
devuelve directamente un objeto que valida contra Pydantic. Sin regex de limpieza.
"""

from __future__ import annotations

import json
import re

from ..config import obtener_config
from ..schemas import InterpretacionClinica, esquema_estructurado
from .base import ErrorModelo

_HERRAMIENTA = {
    "name": "emitir_interpretacion",
    "description": "Emite la interpretación clínica veterinaria en formato estructurado.",
    "input_schema": esquema_estructurado(),
}

_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|gif|webp));base64,(.+)$", re.DOTALL)


def _bloques_imagen(imagenes: list[str]) -> list[dict]:
    bloques = []
    for img in imagenes:
        m = _DATA_URL.match(img)
        if not m:
            continue
        bloques.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)},
            }
        )
    return bloques


class ClaudeClient:
    nombre = "claude"

    def __init__(self) -> None:
        cfg = obtener_config()
        if not cfg.anthropic_api_key:
            raise ErrorModelo(
                "ANTHROPIC_API_KEY no configurada para la ruta Claude.", reintentable=False
            )
        # Import perezoso para no exigir el SDK cuando sólo se usa medGemma.
        from anthropic import AsyncAnthropic

        self._cliente = AsyncAnthropic(api_key=cfg.anthropic_api_key)
        self._modelo = cfg.claude_model

    async def interpretar(
        self, sistema: str, mensaje_usuario: str, imagenes: list[str]
    ) -> InterpretacionClinica:
        contenido: list[dict] = [*_bloques_imagen(imagenes), {"type": "text", "text": mensaje_usuario}]
        try:
            resp = await self._cliente.messages.create(
                model=self._modelo,
                max_tokens=1500,
                system=sistema,
                messages=[{"role": "user", "content": contenido}],
                tools=[_HERRAMIENTA],
                tool_choice={"type": "tool", "name": "emitir_interpretacion"},
            )
        except Exception as exc:  # noqa: BLE001
            raise ErrorModelo(f"Fallo llamando a Claude: {exc}") from exc

        # Los clasificadores de seguridad pueden rechazar la petición: llega un HTTP 200 con
        # `stop_reason="refusal"` y `content` vacío o parcial. Sin esta comprobación el bucle de
        # abajo no encuentra el bloque tool_use y el usuario recibe un error engañoso.
        if resp.stop_reason == "refusal":
            categoria = getattr(getattr(resp, "stop_details", None), "category", None)
            raise ErrorModelo(
                "El modelo rechazó la petición por sus filtros de seguridad"
                + (f" (categoría: {categoria})" if categoria else "")
                + ". Reformula el caso o usa la ruta medGemma.",
                reintentable=False,
            )

        for bloque in resp.content:
            if getattr(bloque, "type", None) == "tool_use":
                try:
                    return InterpretacionClinica.model_validate(bloque.input)
                except Exception as exc:  # noqa: BLE001
                    raise ErrorModelo(f"Salida de Claude no valida el esquema: {exc}") from exc
        raise ErrorModelo("Claude no devolvió el bloque tool_use esperado.")

    async def juzgar(self, sistema: str, mensaje: str) -> dict:
        """Utilidad para el juez de evals: devuelve JSON arbitrario del modelo."""
        resp = await self._cliente.messages.create(
            model=self._modelo,
            max_tokens=1200,
            system=sistema,
            messages=[{"role": "user", "content": mensaje}],
        )
        if resp.stop_reason == "refusal":
            raise ErrorModelo(
                "El juez rechazó el caso por sus filtros de seguridad.", reintentable=False
            )
        texto = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            # Un juez que devuelve prosa en vez de JSON debe fallar con un error tipado, no con
            # un JSONDecodeError crudo que el arnés de evals no distingue de un fallo de red.
            raise ErrorModelo(f"El juez no devolvió JSON válido: {exc}") from exc
