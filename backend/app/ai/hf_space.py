"""Cliente del HF Space (Gradio) donde está alojado medGemma.

Porta el flujo de api/hf_proxy.php: sube las imágenes al endpoint /upload, invoca
/call/analyze, sondea el stream SSE y recupera el texto. Como el Space devuelve TEXTO
libre (no puede forzar un esquema JSON), la salida se limpia de artefactos del modelo y
se envuelve en el campo `interpretacion` de InterpretacionClinica, manteniendo el contrato
estructurado hacia el frontend.
"""

from __future__ import annotations

import base64
import binascii
import json
import re

import httpx

from ..config import obtener_config
from ..schemas import InterpretacionClinica, esquema_estructurado
from .base import ErrorModelo

# La higiene de la prosa vive en `prosa.py` desde que también la usan los modelos locales
# declarados como `prosa` en la lista blanca. Se reexporta aquí porque era la API pública de
# este módulo (y lo que importan sus tests de regresión).
from .prosa import (  # noqa: F401
    _cortar_bucle_lineas,
    interpretacion_defectuosa,
    interpretacion_desde_prosa,
    interpretacion_truncada,
    limpiar_respuesta,
)

_DATA_URL = re.compile(r"^data:(image/[\w+]+);base64,(.+)$", re.DOTALL)


class HFSpaceClient:
    """Cliente del Space. Dos modos según `hf_space_estructurado`:

    - prosa (`medgemma-hf`): el Space devuelve texto libre y se envuelve en `interpretacion`.
    - estructurado (`medgemma-hf-json`): se le manda el JSON Schema y devuelve el objeto ya
      formado. El nombre distinto NO es cosmético: el servicio decide por él si aplica el
      system prompt de prosa, si exige campos estructurados y si suple `requiere_derivacion`.
    """

    def __init__(self) -> None:
        cfg = obtener_config()
        self.estructurado = cfg.hf_space_estructurado
        self.prosa = not self.estructurado
        self.nombre = "medgemma-hf-json" if self.estructurado else "medgemma-hf"
        self.modelo = "hf-space"
        if not cfg.hf_space_url:
            raise ErrorModelo(
                "MORPHOS_HF_SPACE_URL no configurada para la ruta HF Space.", reintentable=False
            )
        self._space = cfg.hf_space_url.rstrip("/")
        self._key = cfg.hf_api_key

    def _headers(self, extra: dict | None = None) -> dict:
        h = dict(extra or {})
        if self._key:
            h["Authorization"] = f"Bearer {self._key}"
        return h

    async def _subir_imagen(self, cliente: httpx.AsyncClient, data_url: str) -> dict | None:
        m = _DATA_URL.match(data_url)
        if not m:
            return None
        mime = m.group(1)
        ext = mime.split("/")[-1] or "jpg"
        try:
            binario = base64.b64decode(m.group(2))
        except (binascii.Error, ValueError):
            return None
        try:
            r = await cliente.post(
                f"{self._space}/upload",
                files={"files": (f"image.{ext}", binario, mime)},
                headers=self._headers(),
            )
            paths = r.json() if r.status_code < 400 else None
        except (httpx.HTTPError, ValueError):
            paths = None

        if not isinstance(paths, list) or not paths:
            # Si el upload falla, envía la imagen inline (igual que el proxy PHP original).
            return {"url": data_url, "orig_name": f"image.{ext}", "mime_type": mime}
        path = paths[0]
        return {"path": path, "url": f"{self._space}/file={path}", "orig_name": f"image.{ext}", "mime_type": mime}

    async def interpretar(
        self, sistema: str, mensaje_usuario: str, imagenes: list[str]
    ) -> InterpretacionClinica:
        prompt = f"{sistema}\n\n{mensaje_usuario}"

        async with httpx.AsyncClient(timeout=120) as cliente:
            data: list = []
            for img in imagenes[:4]:
                data.append(await self._subir_imagen(cliente, img))
            while len(data) < 4:
                data.append(None)
            data.append(prompt)
            # 6.º elemento del contrato Gradio: el esquema. Cadena vacía = modo prosa, que es
            # lo que el Space entiende como "sin restricción".
            data.append(json.dumps(esquema_estructurado()) if self.estructurado else "")

            try:
                r = await cliente.post(
                    f"{self._space}/call/analyze",
                    json={"data": data},
                    headers=self._headers({"Content-Type": "application/json"}),
                )
            except httpx.HTTPError as exc:
                raise ErrorModelo(f"No se pudo contactar el HF Space: {exc}") from exc
            if r.status_code == 429:
                # Cuota de ZeroGPU agotada o límite de tasa del router de HF. Reintentar aquí
                # sería contraproducente: gasta otra reserva de GPU del mismo pozo agotado.
                raise ErrorModelo(
                    "El modelo está saturado (cuota de GPU agotada). Inténtalo de nuevo en unos "
                    "minutos, o configura la ruta local de Ollama.",
                    reintentable=False,
                    saturado=True,
                )
            if r.status_code >= 400:
                # 5xx puede ser transitorio; 4xx (auth, petición mal formada) no se arregla solo.
                raise ErrorModelo(
                    f"HF Space devolvió HTTP {r.status_code}",
                    reintentable=r.status_code >= 500,
                )

            event_id = (r.json() or {}).get("event_id")
            if not event_id:
                raise ErrorModelo("El HF Space no devolvió event_id.")

            try:
                stream = await cliente.get(
                    f"{self._space}/call/analyze/{event_id}", headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise ErrorModelo(f"Fallo sondeando el HF Space: {exc}") from exc

        texto, error = self._parsear_sse(stream.text)
        if error:
            # El Space suele reportar aquí la cuota de ZeroGPU agotada; eso no se arregla
            # reintentando (gastaría otra reserva del mismo pozo).
            sin_cuota = bool(re.search(r"quota|gpu|exceed|limit", error, re.I))
            raise ErrorModelo(
                f"HF Space: {error}", reintentable=not sin_cuota, saturado=sin_cuota
            )
        if texto is None:
            raise ErrorModelo("Sin respuesta del modelo (HF Space).")

        if self.estructurado:
            return self._parsear_estructurado(texto)

        return interpretacion_desde_prosa(texto)

    @staticmethod
    def _parsear_estructurado(texto: str) -> InterpretacionClinica:
        """Valida el JSON restringido del Space contra el esquema.

        La limpieza de prosa (`limpiar_respuesta`, `interpretacion_defectuosa`) NO se aplica
        aquí: son heurísticas sobre texto libre y sobre un JSON darían falsos positivos. Si el
        JSON no valida se trata como salida malformada —error reintentable—, que es justo el
        caso para el que existe el reintento del servicio.
        """
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ErrorModelo(f"El Space devolvió JSON inválido: {exc}") from exc
        try:
            return InterpretacionClinica.model_validate(datos)
        except Exception as exc:  # noqa: BLE001 — ValidationError de pydantic
            raise ErrorModelo(f"JSON del Space fuera de esquema: {exc}") from exc

    @staticmethod
    def _parsear_sse(stream: str) -> tuple[str | None, str | None]:
        """Devuelve (texto, error). Los eventos `error` del Space (p.ej. cuota ZeroGPU
        agotada tras la primera petición) se propagan igual que hacía api/hf_proxy.php,
        en lugar de descartarse y acabar en un genérico "Sin respuesta del modelo".
        """
        ultimo_evento = ""
        resultado = None
        error = None
        for raw in stream.split("\n"):
            linea = raw.rstrip("\r")
            if linea.startswith("event:"):
                ultimo_evento = linea[6:].strip()
            elif linea.startswith("data:"):
                try:
                    parsed = json.loads(linea[5:].strip())
                except json.JSONDecodeError:
                    continue
                if ultimo_evento in ("complete", "process_completed"):
                    resultado = parsed[0] if isinstance(parsed, list) else parsed.get("output", parsed)
                elif ultimo_evento == "error":
                    if isinstance(parsed, dict):
                        error = parsed.get("error") or parsed.get("message") or "Error del modelo."
                    elif isinstance(parsed, str):
                        error = parsed
                    else:
                        error = "Error del modelo."
        texto = resultado if isinstance(resultado, str) else (str(resultado) if resultado is not None else None)
        return texto, error
