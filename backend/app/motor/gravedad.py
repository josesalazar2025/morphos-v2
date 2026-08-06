"""Suelo de seguridad determinista, recalculado EN EL SERVIDOR (ARCHITECTURE_REVIEW §1.1).

Por qué existe: el motor determinista del que depende toda la historia de seguridad corre en el
NAVEGADOR (`frontend/src/analisis.ts`) y el backend aceptaba su veredicto como un hecho —los
`hallazgos` llegaban como campos de la petición y `PeticionInterpretacion` lo decía por escrito:
«El backend NO recalcula»—. Con eso, un cliente que mandara `hallazgos: []` desactivaba de una
sola petición el suelo de derivación obligatoria y la detección de analitos fabricados. No hacía
falta un ataque: era el contrato documentado de la API, y bastaba un bundle cacheado de ayer con
umbrales viejos para que el servidor aplicara una seguridad distinta de la que creía aplicar.

Alcance DELIBERADAMENTE estrecho: rangos de referencia ajustados (edad, raza) y clasificación de
GRAVEDAD. Eso es lo que sostiene `_derivacion_obligatoria`. La detección de patrones —las 50 y
pico reglas de `detectarPatrones`— se queda en el cliente: enriquece el prompt, pero ninguna
decisión de seguridad cuelga de ella. Portar 1062 líneas habría creado una segunda
implementación del motor validado por veterinario, con divergencia silenciosa garantizada.

Lo que hay aquí es un puerto FIEL de `analisis.ts` (líneas 24-290 y 1036-1056). Si cambian los
umbrales o los ajustes de allí, hay que cambiarlos aquí: `tests/test_gravedad_servidor.py`
compara ambos motores sobre los mismos casos precisamente para que la divergencia salte.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from ..config import RAIZ_REPO
from ..schemas import Direccion, Gravedad, HallazgoEntrada, PacienteEntrada

ESPECIES = ("canino", "felino")

# La desviación se mide en múltiplos del ancho del rango de referencia.
UMBRALES_GRAVEDAD = {"leve": 0.5, "moderado": 1.5}

# Cortes clínicos explícitos del lado BAJO. La regla genérica de anchos de rango no sabe
# expresar estos dos: con rango 24-45 un gato necesitaría hematocrito NEGATIVO para llegar a
# 'grave', así que ni una anemia felina ni una trombocitopenia disparaban nunca el suelo.
CORTES_BAJO: dict[str, dict[str, dict[str, float]]] = {
    "hct": {
        "canino": {"leve_hasta": 30, "moderado_hasta": 20},
        "felino": {"leve_hasta": 20, "moderado_hasta": 14},
    },
    "plt": {
        "canino": {"leve_hasta": 100, "moderado_hasta": 30},
        "felino": {"leve_hasta": 100, "moderado_hasta": 30},
    },
}

# Cortes del lado ALTO. Los renales salen del estadiaje IRIS de ERC: estadio 2 → leve,
# 3 → moderado, 4 → grave.
CORTES_ALTO: dict[str, dict[str, dict[str, float]]] = {
    "creat": {
        "canino": {"leve_hasta": 2.8, "moderado_hasta": 5.0},
        "felino": {"leve_hasta": 2.8, "moderado_hasta": 5.0},
    },
    "sdma": {
        "canino": {"leve_hasta": 35, "moderado_hasta": 54},
        "felino": {"leve_hasta": 25, "moderado_hasta": 38},
    },
    # La proteinuria IRIS no se subestadia más allá de "proteinúrico": nunca llega a 'grave'.
    "upc": {
        "canino": {"leve_hasta": 0.5, "moderado_hasta": math.inf},
        "felino": {"leve_hasta": 0.4, "moderado_hasta": math.inf},
    },
}

AJUSTES_EDAD: dict[str, dict[str, dict[str, dict[str, float]]]] = {
    "canino": {
        "cachorro": {"fal": {"superior": 3.0}, "wbc": {"superior": 1.25}, "fosf": {"superior": 1.8}},
        "adulto": {},
        "senior": {"bun": {"superior": 1.15}, "creat": {"superior": 1.15}},
        "geriatrico": {
            "bun": {"superior": 1.25}, "creat": {"superior": 1.25}, "fal": {"superior": 1.40}
        },
    },
    "felino": {
        "cachorro": {"fal": {"superior": 3.0}, "wbc": {"superior": 1.20}, "fosf": {"superior": 1.3}},
        "adulto": {},
        "senior": {"bun": {"superior": 1.20}, "creat": {"superior": 1.20}},
    },
}

# Grupos de raza; se combinan TODOS los que casan, no sólo el primero (un shiba inu pertenece a
# la vez al grupo de microcitosis y al de plaquetas bajas).
AJUSTES_RAZA: dict[str, list[tuple[tuple[str, ...], dict[str, dict[str, float]]]]] = {
    "canino": [
        (
            ("galgo", "greyhound", "whippet", "lebrel", "afgano", "afghan", "saluki", "sloughi"),
            {
                "rbc": {"inferior": 1.15, "superior": 1.15},
                "hgb": {"inferior": 1.12, "superior": 1.12},
                "hct": {"inferior": 1.12, "superior": 1.12},
                "plt": {"inferior": 0.75, "superior": 0.75},
                "t4_total": {"inferior": 0.5, "superior": 0.8},
                "t4_libre": {"inferior": 0.5, "superior": 0.8},
                "creat": {"superior": 1.15},
            },
        ),
        (
            ("shiba", "akita", "jindo", "chow", "shar pei", "shar-pei", "sharpei"),
            {"vcm": {"inferior": 0.85, "superior": 0.92}},
        ),
        (("shiba",), {"plt": {"inferior": 0.75, "superior": 0.9}}),
    ],
    "felino": [
        (("maine coon", "maine"), {"hct": {"inferior": 1.15}, "hgb": {"inferior": 1.15}}),
        (("birman", "sagrado de birmania"), {"creat": {"superior": 1.2}}),
    ],
}

# Sin ajustes por sexo: el que había (creatinina del gato macho) se retiró por falta de respaldo
# en el corpus. Se deja explícito para que no parezca un olvido.
AJUSTES_SEXO: dict[str, dict[str, dict[str, dict[str, float]]]] = {}


@lru_cache
def cargar_referencias() -> dict:
    ruta = Path(RAIZ_REPO) / "data" / "valores_referencia.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


def categorizar_edad(edad_meses: float | None, especie: str) -> str:
    if edad_meses is None:
        return "adulto"
    if especie == "canino":
        if edad_meses < 12:
            return "cachorro"
        if edad_meses < 84:
            return "adulto"
        if edad_meses < 120:
            return "senior"
        return "geriatrico"
    if edad_meses < 12:
        return "cachorro"
    if edad_meses < 120:
        return "adulto"
    return "senior"


def ajustes_de_raza(raza: str | None, especie: str) -> dict[str, dict[str, float]]:
    norm = (raza or "").lower().strip()
    combinados: dict[str, dict[str, float]] = {}
    for razas, ajustes in AJUSTES_RAZA.get(especie, []):
        if not any(r in norm for r in razas):
            continue
        for clave, factor in ajustes.items():
            acumulado = combinados.setdefault(clave, {"inferior": 1.0, "superior": 1.0})
            acumulado["inferior"] *= factor.get("inferior", 1.0)
            acumulado["superior"] *= factor.get("superior", 1.0)
    return combinados


def ajustar_referencias(paciente: PacienteEntrada) -> dict[str, dict]:
    """Rangos de la especie con los factores de edad, raza y sexo aplicados."""
    especie = (paciente.especie or "").lower()
    refs = cargar_referencias().get(especie, {})
    aj_edad = AJUSTES_EDAD.get(especie, {}).get(categorizar_edad(paciente.edad_meses, especie), {})
    aj_raza = ajustes_de_raza(paciente.raza, especie)
    aj_sexo = AJUSTES_SEXO.get(especie, {}).get(paciente.sexo or "", {})

    ajustadas: dict[str, dict] = {}
    for clave, ref in refs.items():
        f_edad, f_raza, f_sexo = (
            aj_edad.get(clave, {}), aj_raza.get(clave, {}), aj_sexo.get(clave, {})
        )
        ajustadas[clave] = {
            **ref,
            "inferior": ref["inferior"]
            * f_edad.get("inferior", 1.0) * f_raza.get("inferior", 1.0) * f_sexo.get("inferior", 1.0),
            "superior": ref["superior"]
            * f_edad.get("superior", 1.0) * f_raza.get("superior", 1.0) * f_sexo.get("superior", 1.0),
        }
    return ajustadas


def clasificar_gravedad(valor: float, ref: dict, clave: str, especie: str) -> Gravedad:
    cortes_bajo = CORTES_BAJO.get(clave, {}).get(especie)
    if cortes_bajo and valor < ref["inferior"]:
        if valor < cortes_bajo["moderado_hasta"]:
            return Gravedad.grave
        if valor < cortes_bajo["leve_hasta"]:
            return Gravedad.moderado
        return Gravedad.leve

    cortes_alto = CORTES_ALTO.get(clave, {}).get(especie)
    if cortes_alto and valor > ref["superior"]:
        if valor > cortes_alto["moderado_hasta"]:
            return Gravedad.grave
        if valor > cortes_alto["leve_hasta"]:
            return Gravedad.moderado
        return Gravedad.leve

    rango = ref["superior"] - ref["inferior"]
    if rango <= 0:
        return Gravedad.grave  # rango degenerado: no se puede medir la desviación, se es cauto
    desviacion = (
        (valor - ref["superior"]) / rango if valor > ref["superior"]
        else (ref["inferior"] - valor) / rango
    )
    if desviacion <= UMBRALES_GRAVEDAD["leve"]:
        return Gravedad.leve
    if desviacion <= UMBRALES_GRAVEDAD["moderado"]:
        return Gravedad.moderado
    return Gravedad.grave


def evaluar(valores: dict[str, float], paciente: PacienteEntrada) -> list[HallazgoEntrada]:
    """Hallazgos fuera de rango calculados AQUÍ, a partir de los valores crudos del paciente."""
    especie = (paciente.especie or "").lower()
    if especie not in ESPECIES:
        return []
    ajustadas = ajustar_referencias(paciente)

    hallazgos: list[HallazgoEntrada] = []
    for clave, ref in ajustadas.items():
        crudo = valores.get(clave)
        if crudo is None:
            continue
        try:
            valor = float(crudo)
        except (TypeError, ValueError):
            continue
        if math.isnan(valor):
            continue
        if valor > ref["superior"]:
            direccion = Direccion.alto
        elif valor < ref["inferior"]:
            direccion = Direccion.bajo
        else:
            continue
        hallazgos.append(
            HallazgoEntrada(
                clave=clave,
                nombre=ref.get("nombre", clave),
                valor=valor,
                unidad=ref.get("unidad", ""),
                direccion=direccion,
                gravedad=clasificar_gravedad(valor, ref, clave, especie),
            )
        )
    return hallazgos
