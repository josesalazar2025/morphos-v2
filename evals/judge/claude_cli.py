"""Transporte del juez servido por el CLI de Claude Code (`claude -p`).

Es la tercera vía entre las dos que ya había, y la que mejor encaja en este proyecto:

- El juez Ollama es gratis y corre headless, pero un 7B discrimina poco.
- El juez por SDK necesita ANTHROPIC_API_KEY y saldo de API — el requisito que dejó la capa
  de juez sin cablear durante toda la fase 3.
- Este usa la sesión de Claude Code que el desarrollador ya tiene abierta: sin clave de API,
  con un modelo grande detrás.

A cambio: sólo existe donde está el binario y hay sesión iniciada (es decir, en local, NO en
un runner de GitHub Actions), consume los límites de uso de la suscripción, y no expone
temperatura, así que es algo menos reproducible que la ruta Ollama. Por eso `crear_juez`
degrada solo a Ollama cuando el binario no está.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from . import ErrorJuez

# Sonnet como juez por defecto: la rúbrica es una tarea de clasificación corta y no justifica
# el coste de Opus en cada caso del dataset. Para una auditoría puntual, MORPHOS_JUEZ_CLI_MODELO=opus.
MODELO_DEFECTO = "sonnet"
TIMEOUT_S = 180


class ErrorJuezCLI(ErrorJuez):
    """Fallo al invocar el CLI o al interpretar su salida."""


def modelo_cli() -> str:
    return os.environ.get("MORPHOS_JUEZ_CLI_MODELO", MODELO_DEFECTO)


def disponible() -> tuple[bool, str]:
    """(disponible, motivo). Sólo comprueba el binario: verificar la sesión exigiría gastar
    una petición real, así que un fallo de autenticación se reporta en la primera llamada."""
    if shutil.which("claude") is None:
        return False, "el CLI `claude` no está en el PATH"
    return True, ""


def preguntar_json(sistema: str, mensaje: str) -> dict:
    """Una llamada de juicio. Lanza ErrorJuezCLI ante cualquier fallo."""
    orden = [
        "claude",
        "-p",
        "--system-prompt", sistema,
        "--output-format", "json",
        "--model", modelo_cli(),
        # El juez no necesita herramientas ni servidores MCP, y no debe arrastrar la
        # configuración del repo donde se ejecuta: sin MCP, sin sesión persistida y con un
        # solo turno. Las herramientas quedan denegadas por defecto en modo -p.
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-turns", "1",
    ]
    try:
        # El prompt va por stdin, no por argv: los casos con muchos hallazgos generan
        # mensajes de varios KB y argv tiene un límite de tamaño.
        proc = subprocess.run(
            orden, input=mensaje, capture_output=True, text=True, timeout=TIMEOUT_S
        )
    except FileNotFoundError as exc:
        raise ErrorJuezCLI("El CLI `claude` no está instalado.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErrorJuezCLI(f"El juez CLI no respondió en {TIMEOUT_S}s.") from exc

    if proc.returncode != 0:
        detalle = (proc.stderr or proc.stdout or "").strip()[:300]
        raise ErrorJuezCLI(f"`claude -p` falló (código {proc.returncode}): {detalle}")

    try:
        sobre = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ErrorJuezCLI(f"El CLI no devolvió el sobre JSON esperado: {exc}") from exc

    if sobre.get("is_error"):
        raise ErrorJuezCLI(f"El juez CLI devolvió error: {str(sobre.get('result'))[:300]}")

    return _extraer_json(str(sobre.get("result", "")))


def _extraer_json(texto: str) -> dict:
    """El modelo devuelve el JSON pedido, pero a veces envuelto en una valla de código.
    No hay `format` que forzar como en Ollama, así que se desenvuelve aquí."""
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(limpio)
    except json.JSONDecodeError as exc:
        error = exc
    # Último recurso: el primer objeto JSON del texto.
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio != -1 and fin > inicio:
        try:
            return json.loads(limpio[inicio : fin + 1])
        except json.JSONDecodeError as exc:
            error = exc
    raise ErrorJuezCLI(f"El juez no devolvió JSON válido: {error}") from error
