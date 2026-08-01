"""Transporte compartido para los jueces LLM gratuitos servidos por Ollama.

Existe para que la capa de juez de las evals no dependa de una clave de pago. Ollama
soporta SALIDA ESTRUCTURADA nativa (campo `format` con un JSON Schema), así que el juez
devuelve un objeto validable igual que la ruta Claude: sin regex ni parseo defensivo de
prosa.

Lo usan tanto el juez clínico (`clinical_judge.py`) como el juez de relevancia de la eval
de recuperación (`run_retrieval_eval.py`).
"""

from __future__ import annotations

import json
import os

import httpx

from . import ErrorJuez

__all__ = ["ErrorJuez", "base_url_juez", "disponible", "modelo_juez", "preguntar_json"]

# Modelo por defecto del juez. Se elige a propósito uno de PROPÓSITO GENERAL y distinto del
# modelo bajo evaluación (medGemma): un juez que es el mismo modelo que genera la respuesta
# se puntúa a sí mismo demasiado alto (sesgo de auto-preferencia) y deja de detectar
# justamente las regresiones que debe atrapar. qwen2.5:7b es el mínimo razonable que corre en
# un portátil; con 16 GB de VRAM o más, `qwen2.5:14b-instruct` juzga bastante mejor.
MODELO_DEFECTO = "qwen2.5:7b"
BASE_URL_DEFECTO = "http://localhost:11434"


def modelo_juez() -> str:
    return os.environ.get("MORPHOS_JUEZ_MODELO", MODELO_DEFECTO)


def base_url_juez() -> str:
    return os.environ.get("MORPHOS_JUEZ_BASE_URL", BASE_URL_DEFECTO).rstrip("/")


def disponible() -> tuple[bool, str]:
    """(disponible, motivo). Comprueba que Ollama responde y que el modelo está descargado."""
    modelo = modelo_juez()
    try:
        r = httpx.get(f"{base_url_juez()}/api/tags", timeout=3)
        r.raise_for_status()
        etiquetas = [m.get("name", "") for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"Ollama no responde en {base_url_juez()} ({exc})"

    # Ollama nombra los modelos "familia:etiqueta"; aceptar que falte ":latest".
    normalizados = {e.removesuffix(":latest") for e in etiquetas}
    if modelo.removesuffix(":latest") not in normalizados:
        return False, f"el modelo '{modelo}' no está descargado (ollama pull {modelo})"
    return True, ""


def preguntar_json(sistema: str, mensaje: str, esquema: dict, *, max_tokens: int = 1200) -> dict:
    """Una llamada de juicio con salida estructurada. Lanza ErrorJuez ante cualquier fallo."""
    payload = {
        "model": modelo_juez(),
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": mensaje},
        ],
        "format": esquema,
        "stream": False,
        "think": False,
        # Temperatura 0: un juez debe ser reproducible; la variabilidad entre ejecuciones se
        # confundiría con una regresión del modelo bajo evaluación.
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    try:
        resp = httpx.post(f"{base_url_juez()}/api/chat", json=payload, timeout=180)
    except httpx.HTTPError as exc:
        raise ErrorJuez(f"No se pudo contactar con el juez en {base_url_juez()}: {exc}") from exc
    if resp.status_code >= 400:
        raise ErrorJuez(f"El juez devolvió HTTP {resp.status_code}: {resp.text[:200]}")

    contenido = resp.json().get("message", {}).get("content", "")
    try:
        return json.loads(contenido)
    except json.JSONDecodeError as exc:
        raise ErrorJuez(f"El juez no devolvió JSON válido: {exc}") from exc
