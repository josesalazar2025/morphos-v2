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

Las REGLAS clínicas (umbrales, cortes, factores de edad y raza) NO están aquí: viven en
`data/ajustes_clinicos.json`, que leen igual este motor y el del navegador. Aquí sólo queda la
lógica de aplicarlas, que es lo que casi nunca cambia. `tests/test_paridad_motor.py` ejecuta el
motor TS real y compara, para que una divergencia entre las dos implementaciones salte.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from ..config import RAIZ_REPO
from ..schemas import Direccion, Gravedad, HallazgoEntrada, PacienteEntrada

ESPECIES = ("canino", "felino")


@lru_cache
def cargar_ajustes() -> dict:
    """Reglas clínicas compartidas con el motor del navegador (`data/ajustes_clinicos.json`).

    Antes estaban duplicadas como constantes aquí y en `analisis.ts`. Lo que se desincroniza no
    es la lógica de comparar —eso no cambia casi nunca— sino los umbrales y factores, que son
    justo lo que un veterinario querría ajustar. Ahora los dos motores leen el mismo fichero.
    """
    ruta = Path(RAIZ_REPO) / "data" / "ajustes_clinicos.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


@lru_cache
def cargar_referencias() -> dict:
    ruta = Path(RAIZ_REPO) / "data" / "valores_referencia.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


# Orden de las categorías: la primera cuyo límite no se supera es la que aplica; si se superan
# todas, la última. Los límites vienen del JSON compartido.
_ORDEN_EDAD = {
    "canino": ("cachorro", "adulto", "senior", "geriatrico"),
    "felino": ("cachorro", "adulto", "senior"),
}


def categorizar_edad(edad_meses: float | None, especie: str) -> str:
    if edad_meses is None:
        return "adulto"
    limites = cargar_ajustes().get("limites_edad_meses", {}).get(especie, {})
    for categoria in _ORDEN_EDAD.get(especie, ())[:-1]:
        if edad_meses < limites.get(categoria, float("inf")):
            return categoria
    return _ORDEN_EDAD.get(especie, ("adulto",))[-1]


def ajustes_de_raza(raza: str | None, especie: str) -> dict[str, dict[str, float]]:
    norm = (raza or "").lower().strip()
    combinados: dict[str, dict[str, float]] = {}
    grupos = cargar_ajustes().get("ajustes_raza", {}).get(especie, [])
    for grupo in grupos:
        if not any(r in norm for r in grupo.get("razas", [])):
            continue
        for clave, factor in grupo.get("ajustes", {}).items():
            acumulado = combinados.setdefault(clave, {"inferior": 1.0, "superior": 1.0})
            acumulado["inferior"] *= factor.get("inferior", 1.0)
            acumulado["superior"] *= factor.get("superior", 1.0)
    return combinados


def ajustar_referencias(paciente: PacienteEntrada) -> dict[str, dict]:
    """Rangos de la especie con los factores de edad, raza y sexo aplicados."""
    especie = (paciente.especie or "").lower()
    refs = cargar_referencias().get(especie, {})
    ajustes = cargar_ajustes()
    categoria = categorizar_edad(paciente.edad_meses, especie)
    aj_edad = ajustes.get("ajustes_edad", {}).get(especie, {}).get(categoria, {})
    aj_raza = ajustes_de_raza(paciente.raza, especie)
    aj_sexo = ajustes.get("ajustes_sexo", {}).get(especie, {}).get(paciente.sexo or "", {})

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
    ajustes = cargar_ajustes()

    cortes_bajo = ajustes.get("cortes_gravedad_bajo", {}).get(clave, {}).get(especie)
    if cortes_bajo and valor < ref["inferior"]:
        # `moderado_hasta: null` = ese analito nunca llega a 'grave' por este lado.
        tope = cortes_bajo.get("moderado_hasta")
        if tope is not None and valor < tope:
            return Gravedad.grave
        if valor < cortes_bajo["leve_hasta"]:
            return Gravedad.moderado
        return Gravedad.leve

    cortes_alto = ajustes.get("cortes_gravedad_alto", {}).get(clave, {}).get(especie)
    if cortes_alto and valor > ref["superior"]:
        tope = cortes_alto.get("moderado_hasta")
        if tope is not None and valor > tope:
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
    umbrales = ajustes.get("umbrales_gravedad", {})
    if desviacion <= umbrales["leve"]:
        return Gravedad.leve
    if desviacion <= umbrales["moderado"]:
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
