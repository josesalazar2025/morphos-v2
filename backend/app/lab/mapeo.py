"""Mapeo de códigos de analizador → claves canónicas de la app + conversión de unidades.

Fuente única de verdad del vocabulario, compartida por todo formato de entrada (ASTM, HL7,
JSON). Es un port a Python de la lógica ya validada en `frontend/src/pdf-parser.ts`
(`CONVERSIONES_UNIDADES`, `aplicarConversion`, `extraerValorYUnidad`,
`parsearSemiCuantitativo`, y la derivación de porcentajes del diferencial). Los factores de
conversión se mantienen IDÉNTICOS a los del PDF para que ambas importaciones coincidan.

Las tablas código→analito viven en data/lab_mapeos/*.json (genérico + overrides por
fabricante), de modo que añadir un equipo es editar JSON, no código.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from functools import lru_cache

from ..config import RAIZ_REPO
from ..schemas_lab import ResultadoAnalizador, ResultadoMapeado, ValorAnalito

DIR_MAPEOS = RAIZ_REPO / "data" / "lab_mapeos"

# Claves que en el formulario son <select> semicuantitativos (no inputs numéricos).
CLAVES_SEMICUANTITATIVAS = {"uri-prot", "uri-gluc"}


# --- Conversión de unidades (port fiel de pdf-parser.ts) ---
# Cada regla: (regex sobre la cadena de unidad reportada, función que transforma el valor).
# La clave del diccionario es `claveConv` (si la observación la trae) o la clave canónica.

def _c(patron: str) -> re.Pattern:
    return re.compile(patron, re.IGNORECASE)


CONVERSIONES_UNIDADES: dict[str, list[tuple[re.Pattern, Callable[[float], float]]]] = {
    "hgb": [
        (_c(r"\bg/L\b"), lambda v: v / 10),
        (_c(r"\bmmol/L\b"), lambda v: v * 1.6113),
    ],
    "hct": [(_c(r"\bL/L\b"), lambda v: v * 100 if v < 1.5 else v)],
    "chcm": [
        (_c(r"\bg/L\b"), lambda v: v / 10),
        (_c(r"\bmmol/L\b"), lambda v: v * 0.6206),
    ],
    "pct": [(_c(r"\bL/L\b"), lambda v: v * 100 if v < 1.5 else v)],
    "wbc": [(_c(r"^\s*/[μµu]?[Ll]\b"), lambda v: v / 1000 if v > 100 else v)],
    "plt": [(_c(r"^\s*/[μµu]?[Ll]\b"), lambda v: v / 1000 if v > 1000 else v)],
    "bun": [(_c(r"\bmmol/L\b"), lambda v: v * 2.8)],
    "urea": [
        (_c(r"\bmmol/L\b"), lambda v: v * 2.8),
        (_c(r"\bmg/dL\b"), lambda v: v * 0.467),
    ],
    "creat": [(_c(r"\b[μµu]mol/L\b"), lambda v: v / 88.4)],
    "sdma": [
        (_c(r"\bnmol/L\b"), lambda v: v / 5.899),
        (_c(r"\b[μµu]g/L\b"), lambda v: v / 10),
    ],
    "gluc": [(_c(r"\bmmol/L\b"), lambda v: v * 18.016)],
    "prot": [(_c(r"\bg/L\b"), lambda v: v / 10)],
    "alb": [(_c(r"\bg/L\b"), lambda v: v / 10)],
    "glob": [(_c(r"\bg/L\b"), lambda v: v / 10)],
    "bili": [(_c(r"\b[μµu]mol/L\b"), lambda v: v / 17.1)],
    "bili_dir": [(_c(r"\b[μµu]mol/L\b"), lambda v: v / 17.1)],
    "fosf": [(_c(r"\bmmol/L\b"), lambda v: v * 3.097)],
    "calc": [
        (_c(r"\bmmol/L\b"), lambda v: v * 4.008),
        (_c(r"\bm[Ee]q/L\b"), lambda v: v * 2.004),
    ],
    "colest": [(_c(r"\bmmol/L\b"), lambda v: v * 38.67)],
    "trigli": [(_c(r"\bmmol/L\b"), lambda v: v * 88.57)],
    "cortisol_bas": [(_c(r"\bnmol/L\b"), lambda v: v / 27.59)],
    "cortisol_acth": [(_c(r"\bnmol/L\b"), lambda v: v / 27.59)],
    "t4_total": [
        (_c(r"\b[μµu]g/dL\b"), lambda v: v * 12.87),
        (_c(r"\bng/dL\b"), lambda v: v * 0.01287),
        (_c(r"\bng/mL\b"), lambda v: v * 0.1287),
    ],
    "insulina": [(_c(r"\bpmol/L\b"), lambda v: v / 6.945)],
}


def convertir_unidad(clave: str, clave_conv: str | None, valor: float, unidad: str) -> float:
    """Aplica la primera regla de conversión cuya unidad coincida; si no, devuelve el valor tal cual."""
    key = clave_conv or clave
    reglas = CONVERSIONES_UNIDADES.get(key)
    if not reglas:
        return valor
    for patron, factor in reglas:
        if patron.search(unidad):
            return round(factor(valor), 4)
    return valor


# --- Parseo de valores ---

_NUMERO = re.compile(r"[<>≤≥]?\s*(-?\d+(?:[.,]\d+)?)")


def parsear_valor_numerico(valor: str) -> float | None:
    """Extrae el número de un valor reportado (`"12.3"`, `"<0.1"`, `"1,5"`).

    A diferencia del PDF (que descartaba <=0 para evitar falsos positivos en texto libre),
    aquí el valor viene explícito de un feed estructurado: se aceptan 0 y negativos (p. ej.
    exceso de base). Sólo se rechazan valores no numéricos o no finitos.
    """
    m = _NUMERO.match(valor.strip())
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parsear_semicuantitativo(texto: str) -> str | None:
    """Port de parsearSemiCuantitativo: mapea a los valores de opción del <select> (neg/+/++/+++)."""
    t = texto.lower()
    if re.search(r"negati|nég|neg\b|ausente|absent|no\s+detect", t):
        return "neg"
    if re.search(r"\+{3}", t):
        return "+++"
    if re.search(r"\+{2}", t):
        return "++"
    if "+" in t:
        return "+"
    if re.search(r"traz|trace", t):
        return "+"
    return None


# --- Carga de tablas de mapeo ---

def _normalizar_fabricante(fabricante: str | None) -> str | None:
    if not fabricante:
        return None
    f = fabricante.lower()
    if "abaxis" in f or "vetscan" in f:
        return "abaxis"
    if "horiba" in f or "scil" in f:
        return "horiba"
    if "bionote" in f or "vcheck" in f:
        return "bionote"
    return None


def _cargar_json(nombre: str) -> dict:
    ruta = DIR_MAPEOS / f"{nombre}.json"
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=8)
def _indice(fabricante: str | None) -> dict[str, dict]:
    """Índice código(mayúsculas) → {clave, clave_conv, unidad_defecto}.

    Parte de generico.json; si hay tabla del fabricante, la superpone (gana el fabricante).
    """
    tablas = [_cargar_json("generico")]
    fab = _normalizar_fabricante(fabricante)
    if fab:
        tablas.append(_cargar_json(fab))

    indice: dict[str, dict] = {}
    for tabla in tablas:
        for clave_json, definicion in tabla.items():
            if not isinstance(definicion, dict):
                continue  # entradas de metadatos como "_comentario"
            # `clave` opcional permite varias definiciones para la misma clave canónica con
            # distinto claveConv (p. ej. BUN vs UREA, ambas → 'bun' pero con conversión distinta).
            entrada = {
                "clave": definicion.get("clave", clave_json),
                "clave_conv": definicion.get("claveConv"),
                "unidad_defecto": definicion.get("unidad_defecto", ""),
            }
            for codigo in definicion.get("codigos", []):
                indice[codigo.strip().upper()] = entrada
    return indice


# --- Mapeo ---

def mapear_observacion(obs, indice: dict[str, dict]) -> ValorAnalito | None:
    """Mapea una observación cruda a un ValorAnalito canónico, o None si no se reconoce."""
    entrada = indice.get(obs.codigo_prueba.strip().upper())
    if not entrada:
        return None
    clave = entrada["clave"]

    if clave in CLAVES_SEMICUANTITATIVAS:
        semis = parsear_semicuantitativo(obs.valor)
        if semis is None:
            return None
        return ValorAnalito(
            clave=clave,
            valor=semis,
            valor_original=obs.valor,
            unidad_original=obs.unidad,
            es_semicuantitativo=True,
        )

    num = parsear_valor_numerico(obs.valor)
    if num is None:
        return None
    unidad = obs.unidad or entrada.get("unidad_defecto", "")
    convertido = convertir_unidad(clave, entrada.get("clave_conv"), num, unidad)
    return ValorAnalito(
        clave=clave,
        valor=convertido,
        valor_original=obs.valor,
        unidad_original=obs.unidad,
    )


def _derivar_porcentajes(analitos: dict[str, ValorAnalito]) -> None:
    """Deriva % del diferencial de leucocitos desde absolutos y % de reticulocitos.

    Port de la derivación de parsearTextoLab: sólo rellena si el % no vino directamente.
    """
    def _num(clave: str) -> float | None:
        va = analitos.get(clave)
        return va.valor if va and isinstance(va.valor, (int, float)) else None

    wbc = _num("wbc")
    if wbc and wbc > 0:
        for f in ("neutro", "linfo", "mono", "eosino", "baso"):
            abs_val = _num(f"{f}_abs")
            if f not in analitos and abs_val is not None:
                pct = round((abs_val / wbc) * 100)
                if 0 <= pct <= 100:
                    analitos[f] = ValorAnalito(clave=f, valor=float(pct), valor_original="(derivado)")

    rbc = _num("rbc")
    reti_abs = _num("reti_abs")
    if rbc and rbc > 0 and "reti" not in analitos and reti_abs is not None:
        pct = reti_abs / (rbc * 10)
        if 0 <= pct <= 20:
            analitos["reti"] = ValorAnalito(clave="reti", valor=round(pct, 2), valor_original="(derivado)")


def mapear_resultado(res: ResultadoAnalizador) -> ResultadoMapeado:
    """Convierte un ResultadoAnalizador crudo en el ResultadoMapeado que consume el frontend."""
    indice = _indice(res.fabricante)
    analitos: dict[str, ValorAnalito] = {}
    no_mapeados: list[str] = []

    for obs in res.observaciones:
        va = mapear_observacion(obs, indice)
        if va is None:
            no_mapeados.append(obs.codigo_prueba)
            continue
        if va.clave not in analitos:  # primer match gana, como en el PDF
            analitos[va.clave] = va

    _derivar_porcentajes(analitos)

    return ResultadoMapeado(
        muestra_id=res.muestra_id,
        instrumento_id=res.instrumento_id,
        momento=res.momento,
        analitos=analitos,
        paciente=res.pistas_paciente,
        no_mapeados=no_mapeados,
    )
