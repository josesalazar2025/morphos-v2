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

_DATA_URL = re.compile(r"^data:(image/[\w+]+);base64,(.+)$", re.DOTALL)

# medGemma es un modelo con "pensamiento": de forma intermitente emite una cadena de
# razonamiento en inglés (etiquetada `thought` / "thinking process") en lugar de responder,
# y a veces degenera en un bucle de repetición que agota el presupuesto de tokens sin llegar
# a la respuesta. Estos marcadores permiten detectar y descartar esa salida defectuosa.
_MARCADOR_PENSAMIENTO = re.compile(
    r"(?im)^\s*(thought|thinking)\s*:?\s*$"
    r"|here'?s\s+(a|my)\s+thinking\s+process"
    r"|thinking\s+process\s+to\s+arrive"
    r"|proceso\s+de\s+(pensamiento|razonamiento)"
)


def limpiar_respuesta(text: str) -> str:
    """Versión compacta de la limpieza que antes vivía en ia.js (limpiarRespuesta).

    Sólo se aplica a la ruta HF Space (texto crudo de medGemma); las rutas Ollama/Claude
    usan salida estructurada y no la necesitan.
    """
    if "<start_of_turn>model" in text:
        text = text.split("<start_of_turn>model")[-1]
    if "<end_of_turn>" in text:
        text = text[: text.index("<end_of_turn>")]
    if "<unused95>" in text:
        text = text.split("<unused95>")[-1]
    elif "<unused94>" in text:
        text = "".join(text.split("<unused94>")[1:]).strip()
    text = re.sub(r"<unused\d+>", "", text)
    text = re.sub(r"<start_of_turn>\w+\n?", "", text)
    text = re.sub(r"^\d+\s+(medical assistant|assistant|model)\s*", "", text, flags=re.I)
    # LaTeX y bloques matemáticos
    text = re.sub(r"\$\\boxed\{[^}]*\}\$", "", text)
    text = re.sub(r"\\[a-zA-Z]+(\{[^}]*\})?", "", text)
    text = re.sub(r"\$[^$]*\$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = _cortar_bucle_lineas(text)
    # Corta al primer párrafo repetido (bucle del modelo)
    vistos: set[str] = set()
    sin_rep = []
    for p in re.split(r"\n\n+", text):
        clave = p.strip()[:80]
        if clave in vistos:
            break
        vistos.add(clave)
        sin_rep.append(p)
    return "\n\n".join(sin_rep).strip() or "Sin respuesta del modelo."


def _cortar_bucle_lineas(text: str) -> str:
    """Trunca en cuanto una línea sustantiva se repite por 3.ª vez (bucle a nivel de viñeta,
    que la deduplicación por párrafos `\\n\\n` no detecta)."""
    conteo: dict[str, int] = {}
    salida: list[str] = []
    for linea in text.split("\n"):
        clave = linea.strip()
        if len(clave) > 15:
            conteo[clave] = conteo.get(clave, 0) + 1
            if conteo[clave] >= 3:
                break
        salida.append(linea)
    return "\n".join(salida)


# Caracteres que pueden ir DESPUÉS del punto final sin que la frase esté cortada: énfasis
# markdown, comillas y cierres de paréntesis.
_ADORNOS_FINALES = "*_`\"'”»)]}"
_FIN_DE_FRASE = ".!?…:"
# Una línea final corta puede ser un ítem de lista o un encabezado legítimos sin puntuación
# ("- Ecografía abdominal"). Sólo una línea larga sin cierre delata una frase interrumpida.
_LARGO_MINIMO_TRUNCADO = 40


def interpretacion_truncada(text: str) -> bool:
    """True si la respuesta se corta a mitad de frase.

    El Space puede devolver una interpretación cortada en seco (visto en producción:
    «…los diferenciales incluyen la lip», justo antes de nombrar el diferencial clave). La
    limpieza no la toca —el corte viene de arriba— y el resto de comprobaciones no la ven:
    el texto es largo, no repite y no filtra razonamiento. Sin esto, una interpretación
    incompleta llega al veterinario con aspecto de completa, callando justo lo que importa.
    """
    limpio = text.rstrip()
    if not limpio:
        return True
    ultima_linea = limpio.split("\n")[-1].strip()
    if len(ultima_linea) < _LARGO_MINIMO_TRUNCADO:
        return False
    return limpio.rstrip(_ADORNOS_FINALES)[-1:] not in _FIN_DE_FRASE


def interpretacion_defectuosa(text: str) -> bool:
    """True si la salida limpiada no es una interpretación válida: demasiado corta, cadena de
    razonamiento filtrada, bucle de repetición o frase cortada. Se usa para forzar un
    reintento."""
    if len(text.strip()) < 40:
        return True
    if _MARCADOR_PENSAMIENTO.search(text[:500]):
        return True
    if interpretacion_truncada(text):
        return True
    conteo: dict[str, int] = {}
    for linea in text.split("\n"):
        clave = linea.strip()
        if len(clave) > 15:
            conteo[clave] = conteo.get(clave, 0) + 1
            if conteo[clave] >= 3:
                return True
    return False


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
        self.nombre = "medgemma-hf-json" if self.estructurado else "medgemma-hf"
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

        limpio = limpiar_respuesta(texto)
        # Salida defectuosa (razonamiento filtrado / bucle / frase cortada) → error
        # reintentable: el servicio vuelve a muestrear una vez y suele obtener una respuesta
        # correcta. Se distingue el motivo porque una respuesta truncada se ve completa y el
        # mensaje genérico despistaría al diagnosticar.
        if interpretacion_defectuosa(limpio):
            truncada = interpretacion_truncada(limpio)
            motivo = (
                "la respuesta llegó cortada a mitad de frase"
                if truncada
                else "el modelo devolvió razonamiento o texto repetido, no la interpretación"
            )
            raise ErrorModelo(
                f"Respuesta inutilizable del modelo: {motivo}.", truncado=truncada
            )

        # `requiere_derivacion=True` es un marcador de posición conservador, NO una lectura del
        # modelo: en esta ruta el Space devuelve prosa y no puede rellenar campos estructurados.
        # Quien le pone valor real es el servicio, desde el motor determinista
        # (`_derivacion_en_ruta_de_prosa`). Dejarlo constante hacía que `acierto_derivacion`
        # midiera este default y no al modelo, y contradecía al propio texto en un panel normal.
        return InterpretacionClinica(
            interpretacion=limpio,
            requiere_derivacion=True,
            idioma="es",
        )

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
