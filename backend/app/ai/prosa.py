"""Higiene de la salida de los modelos que devuelven TEXTO libre.

Vivía dentro de `hf_space.py` cuando el Space era la única ruta de prosa. Ahora también la
usa `medgemma.py` cuando el modelo local elegido está declarado como `prosa` en la lista
blanca: no todo modelo que corre en Ollama sabe respetar una decodificación restringida
—medido con qwen2.5:7b, que devolvía JSON válido con los tres campos estructurados
vacíos—, y para ésos es mejor pedir prosa y envolverla que aceptar un objeto hueco.

Los marcadores de `<unused95>` y `<start_of_turn>` son de la familia Gemma, pero el resto
(razonamiento filtrado, bucle de repetición, frase cortada) son modos de fallo genéricos de
cualquier modelo pequeño, así que se aplican a las dos rutas por igual.
"""

from __future__ import annotations

import re

from ..schemas import InterpretacionClinica
from .base import ErrorModelo

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

    Sólo se aplica a las rutas de PROSA (texto crudo del modelo); las rutas con salida
    estructurada validan contra el esquema y no la necesitan.
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


def interpretacion_desde_prosa(texto: str) -> InterpretacionClinica:
    """Limpia el texto crudo y lo envuelve en el contrato estructurado, o lanza ErrorModelo.

    Salida defectuosa (razonamiento filtrado / bucle / frase cortada) → error reintentable:
    el servicio vuelve a muestrear una vez y suele obtener una respuesta correcta. Se
    distingue el motivo porque una respuesta truncada se ve completa y el mensaje genérico
    despistaría al diagnosticar.

    `requiere_derivacion=True` es un marcador de posición conservador, NO una lectura del
    modelo: en esta ruta el modelo devuelve prosa y no puede rellenar campos estructurados.
    Quien le pone valor real es el servicio, desde el motor determinista
    (`_derivacion_en_ruta_de_prosa`). Dejarlo constante hacía que `acierto_derivacion`
    midiera este default y no al modelo, y contradecía al propio texto en un panel normal.
    """
    limpio = limpiar_respuesta(texto)
    if interpretacion_defectuosa(limpio):
        truncada = interpretacion_truncada(limpio)
        motivo = (
            "la respuesta llegó cortada a mitad de frase"
            if truncada
            else "el modelo devolvió razonamiento o texto repetido, no la interpretación"
        )
        raise ErrorModelo(f"Respuesta inutilizable del modelo: {motivo}.", truncado=truncada)

    return InterpretacionClinica(
        interpretacion=limpio,
        requiere_derivacion=True,
        idioma="es",
    )
