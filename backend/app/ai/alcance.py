"""Guarda de alcance determinista, PREVIA a la llamada al modelo.

Por qué existe: en la corrida del 2026-07-28 (`evals/resultados/2026-07-28/`), el caso
`fuera-de-alcance-humano` puntuó 0.00 en corrección y 0.00 en seguridad con los TRES modelos
evaluados —medGemma 4b, qwen2.5:7b y qwen2.5:14b—. Fueron los únicos ceros de toda la corrida.
Ninguno detectó que el paciente era humano, ninguno declinó, y los tres fabricaron material
clínico (analitos nunca medidos, diagnósticos, hasta una biopsia renal) a partir de un único
valor en rango.

La conclusión de ese informe es que no es un problema de elección de modelo: una guarda con
consecuencias legales no puede vivir en un modelo generativo. Este módulo es el equivalente de
`_derivacion_obligatoria()` (`service.py`) para el alcance: se decide en el servidor, antes de
gastar una llamada, y el modelo no puede contradecirlo porque no llega a verlo.

Alcance de la guarda, deliberadamente estrecho: sólo la ESPECIE del paciente. Un falso positivo
aquí deja al veterinario sin herramienta, así que los patrones exigen que la especie aparezca
declarada como tal ("paciente humano", "se trata de un equino") y no sueltas en el relato
clínico —un perro puede convivir con un conejo o cazar ratones sin quedar fuera de alcance—.
Las peticiones de prescripción NO se filtran aquí: "prescripción de insulina" es indistinguible
del historial ("paciente con prescripción previa de insulina") sin entender la frase, y eso es
justo lo que no queremos delegar en un modelo.
"""

from __future__ import annotations

import re
import unicodedata

from ..schemas import InterpretacionClinica, PeticionInterpretacion

ESPECIES_SOPORTADAS = frozenset({"canino", "felino"})

# Especies fuera del dominio de la herramienta (rangos de referencia caninos/felinos).
_OTRAS_ESPECIES = (
    "equino|caballo|yegua|potro|bovino|vaca|ternero|becerro|ovino|oveja|cordero|caprino|cabra|"
    "porcino|cerdo|lechon|ave|aviar|gallina|pollo|loro|guacamayo|periquito|canario|"
    "conejo|cobayo|cobaya|cuy|huron|hamster|jerbo|chinchilla|raton|rata|"
    "reptil|tortuga|iguana|serpiente|camaleon|anfibio|pez|primate|mono"
)
_HUMANO = "humano|humana|persona|paciente humano"

# La especie tiene que venir DECLARADA como la del paciente, no sólo mencionada.
_DECLARACION = r"(?:paciente|especie|se trata de|es|era)\s+(?:un[ao]?\s+|el\s+|la\s+|:\s*)?"

_RE_HUMANO = re.compile(
    rf"\b(?:{_DECLARACION}(?:{_HUMANO})\b|soy\s+(?:un[ao]?\s+)?(?:humano|humana|persona)\b)"
)
_RE_OTRA_ESPECIE = re.compile(rf"\b{_DECLARACION}(?:{_OTRAS_ESPECIES})\b")


def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados: los patrones se escriben así."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_tildes)


def motivo_fuera_de_alcance(pet: PeticionInterpretacion) -> str | None:
    """Motivo por el que la petición queda fuera del dominio canino/felino, o None.

    Trata `signos_clinicos` como DATOS (igual que el prompt): se inspecciona, no se obedece.
    """
    especie = (pet.paciente.especie or "").lower()
    if especie and especie not in ESPECIES_SOPORTADAS:
        return f"la especie indicada ('{especie}') no es canina ni felina"

    # La raza es texto libre y a veces es donde se cuela la especie real.
    for campo in (pet.paciente.raza or "", pet.signos_clinicos):
        texto = _normalizar(campo)
        if not texto:
            continue
        if _RE_HUMANO.search(texto):
            return "el caso describe a un paciente humano"
        if (otra := _RE_OTRA_ESPECIE.search(texto)) is not None:
            return f"el caso describe a un paciente de otra especie ('{otra.group(0).strip()}')"
    return None


def respuesta_fuera_de_alcance(motivo: str) -> InterpretacionClinica:
    """Interpretación de rechazo, sin hallazgos ni diferenciales que puedan leerse como clínica."""
    return InterpretacionClinica(
        interpretacion=(
            "Esta herramienta interpreta analíticas de pacientes caninos y felinos y no puede "
            f"procesar este caso: {motivo}. No se emiten hallazgos, diagnósticos diferenciales "
            "ni recomendaciones diagnósticas. Si se trata de una persona, consulte a un médico; "
            "si es otra especie animal, a un veterinario con competencia en ella."
        ),
        hallazgos_clave=[],
        diferenciales=[],
        siguientes_pruebas=[],
        confianza="alta",
        requiere_derivacion=True,
        fuera_de_alcance=True,
    )
