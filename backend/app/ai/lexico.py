"""Léxico de analitos: clave → términos con los que un texto clínico puede nombrarla.

Única fuente del mapeo. Vivía sólo en `evals/run_evals.py`, que lo usaba para medir la
cobertura de hallazgos sobre la prosa; ahora también lo necesita el backend en tiempo de
ejecución —`ai/coherencia.py` para detectar analitos inventados y `ai/prompt.py` para nombrar
en cristiano los que salieron en rango—, así que se ha traído aquí y `run_evals.py` lo importa.
Duplicarlo habría dejado la métrica y la guarda midiendo cosas distintas con el mismo nombre.

Se construye desde `data/valores_referencia.json`, que ya trae el nombre clínico de cada
analito ("ALT (GPT)", "Densidad (USG)"), así que el grueso del léxico no se escribe a mano.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache

from ..config import RAIZ_REPO

# Palabras del nombre clínico que no identifican al analito por sí solas: "T4 total" y
# "Proteínas totales" comparten "total", y buscarla marcaría cualquiera de los dos.
_GENERICOS = {"total", "libre", "serico", "serica", "plasmatico", "urinario", "sangre"}


def sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )


# La prosa clínica casi nunca nombra el analito: nombra su alteración ("hiperfosforemia" en
# vez de "fósforo", "trombocitopenia" en vez de "plaquetas"). Estas variantes se listan a
# mano en vez de derivarlas por stemming a propósito: un prefijo de 5 letras haría que
# "hematoma" contara como hematocrito, y aquí un falso positivo es peor que un falso negativo
# —tanto en la métrica como en la guarda, donde provoca un reintento inútil—. Sólo se incluyen
# derivaciones del NOMBRE del analito, no síndromes que lo acompañan (anemia no cuenta como
# mención del hematocrito).
VARIANTES: dict[str, tuple[str, ...]] = {
    "alb": ("hipoalbuminemia", "hiperalbuminemia", "albuminemia"),
    "alt": ("gpt", "transaminasas", "transaminasa"),
    # La grafía con UNA r es incorrecta y el modelo la usa igual: el 2026-08-04 escribió
    # «hiperbilirubinemia» en `shunt-portosistemico-canino`, sobre una bilirrubina que nunca
    # se midió, y la guarda de invención lo dejó pasar por esa letra. Un término de más aquí
    # no puede casar con otro analito, así que el coste de admitir la falta de ortografía es
    # cero y el de no admitirla ya se pagó.
    "bili": ("hiperbilirrubinemia", "bilirrubinemia", "hiperbilirubinemia", "bilirubinemia"),
    "bun": ("azotemia", "uremia", "urea"),
    "ca_ion": ("hipercalcemia", "hipocalcemia", "calcemia", "ica"),
    "calc": ("hipercalcemia", "hipocalcemia", "calcemia"),
    "colest": ("hipercolesterolemia", "colesterolemia"),
    "creat": ("azotemia",),
    "fal": ("alp", "fosfatasa"),
    "fosf": ("hiperfosfatemia", "hipofosfatemia", "hiperfosforemia", "fosfatemia", "fosforemia"),
    "glob": ("hiperglobulinemia", "globulinemia", "gammapatia"),
    "gluc": ("hiperglucemia", "hipoglucemia", "glucemia", "hiperglicemia"),
    "hco3": ("bicarbonato",),
    "neutro_abs": ("neutrofilia", "neutropenia"),
    "ph_sangre": ("acidosis", "alcalosis", "acidemia", "alcalemia"),
    "pli": ("cpli", "lipasa"),
    "plt": ("trombocitopenia", "trombocitosis", "plaquetopenia"),
    "potasio": ("hipopotasemia", "hiperpotasemia", "hipokalemia", "hiperkalemia", "kalemia"),
    "prot": ("hiperproteinemia", "hipoproteinemia", "proteinemia"),
    "reti": ("reticulocitosis", "regenerativa"),
    "sodio": ("hiponatremia", "hipernatremia", "natremia"),
    "t4_total": ("t4", "tiroxina"),
    "usg": ("isostenuria", "hipostenuria"),
    "vcm": ("mcv", "microcitosis", "macrocitosis"),
    "wbc": ("leucocitosis", "leucopenia", "leucocitos"),
}


# Siglas cuya versión en minúsculas es una palabra corriente del castellano. No pueden entrar
# en `VARIANTES`: todo el léxico se coteja sobre texto normalizado a minúsculas, y buscar "un"
# marcaría prácticamente cualquier oración. Se cotejan aparte, respetando las mayúsculas, sobre
# el texto ORIGINAL. Motivo: el 2026-08-04, en `piometra-progesterona-canino`, el modelo escribió
# «Esta combinación (alta UN, alta CT, USG bajo) caracteriza una azotemia renal» sobre un panel
# sin BUN; "azotemia" quedaba absuelta —la creatinina sí estaba alta— y la sigla era la única
# señal de que se había inventado el dato.
ABREVIATURAS_SENSIBLES: dict[str, tuple[str, ...]] = {
    "bun": ("UN", "BUN"),
}


def abreviaturas_presentes(texto: str) -> set[str]:
    """Claves cuya sigla ambigua aparece, con sus mayúsculas, en el texto tal cual se escribió."""
    return {
        clave for clave, siglas in ABREVIATURAS_SENSIBLES.items()
        if any(re.search(rf"\b{re.escape(s)}\b", texto) for s in siglas)
    }


def tokens_analito(texto: str) -> set[str]:
    # Mínimo 2 caracteres: hay analitos cuyo nombre entero es corto ("T4", "pH"), y con 3
    # se quedaban sin ningún término con el que buscarlos.
    return {
        t for t in re.split(r"[^a-z0-9]+", sin_tildes(texto))
        if len(t) >= 2 and t not in _GENERICOS
    }


@lru_cache
def _referencias() -> dict:
    ruta = RAIZ_REPO / "data" / "valores_referencia.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


@lru_cache
def lexico_analitos() -> dict[str, frozenset[str]]:
    """clave de analito → términos con los que un texto puede referirse a él."""
    lexico: dict[str, set[str]] = {}
    for analitos in _referencias().values():  # canino, felino
        for clave, info in analitos.items():
            terminos = lexico.setdefault(clave, set())
            terminos |= tokens_analito(clave)
            terminos |= tokens_analito(info.get("nombre", ""))
    for clave, variantes in VARIANTES.items():
        lexico.setdefault(clave, set()).update(variantes)
    return {clave: frozenset(t) for clave, t in lexico.items()}


@lru_cache
def nombres_clinicos() -> dict[str, str]:
    """clave → nombre clínico legible ("plt" → "Plaquetas"). La clave cruda si no hay nombre."""
    nombres: dict[str, str] = {}
    for analitos in _referencias().values():
        for clave, info in analitos.items():
            if nombre := info.get("nombre"):
                nombres.setdefault(clave, nombre)
    return nombres


def nombre_clinico(clave: str) -> str:
    return nombres_clinicos().get(clave, clave)


# Palabras que aparecen DENTRO del nombre clínico de algún analito pero que no lo identifican:
# calificadores ("directa", "ionizado", "arterial"), unidades de medida del propio nombre
# ("tiempo", "cociente", "índice") y sustantivos compartidos por varios ("proteína", "creatina").
# Sin este filtro «de» y «tiempo» —del "Tiempo de protrombina (TP)"— casan en casi cualquier
# frase clínica: medido sobre las 30 predicciones del 2026-08-04, el TP salía marcado en 27.
_NO_IDENTIFICAN = frozenset({
    "tiempo", "exceso", "nivel", "basal", "serico", "serica", "urinario", "orina", "sangre",
    "total", "libre", "parcial", "activada", "protrombina", "tromboplastina", "sanguineo",
    "relacion", "indice", "recuento", "absoluto", "estimulacion", "supresion", "post", "pre",
    "arterial", "saturacion", "cociente", "antigeno", "reactiva", "directa", "ionizado",
    "pancreatica", "acidos", "biliares", "creatina", "kinasa", "cardiaca", "amiloide",
    "proteina", "dimeros",
})
# Debajo de esto, un token del nombre es una abreviatura ("tp", "be", "ac", "at") que casa
# dentro de cualquier palabra o como partícula suelta. Las siglas que SÍ interesan ya entran
# por `VARIANTES`, que es una lista curada.
_LARGO_MINIMO_TERMINO = 6


@lru_cache
def terminos_especificos() -> dict[str, frozenset[str]]:
    """Subconjunto del léxico con la precisión que exige BUSCAR AL REVÉS.

    `claves_mencionadas` pregunta «¿aparece ESTE analito?» sobre un puñado de claves conocidas,
    y ahí un token flojo apenas molesta. La guarda de invención hace lo contrario: barre los 90
    analitos contra una prosa para ver cuál NO debería estar. Con el léxico completo eso es un
    generador de falsos positivos, y cada falso positivo cuesta una llamada al modelo y una
    corrección improcedente. Aquí sólo entran los términos curados a mano (`VARIANTES`) y las
    palabras del nombre clínico lo bastante largas y específicas como para no casar por azar.
    """
    especificos: dict[str, frozenset[str]] = {}
    for clave, terminos in lexico_analitos().items():
        utiles = set(VARIANTES.get(clave, ()))
        utiles |= {
            t for t in terminos
            if len(t) >= _LARGO_MINIMO_TERMINO and t not in _NO_IDENTIFICAN
        }
        if utiles:
            especificos[clave] = frozenset(utiles)
    return especificos


def claves_mencionadas(texto: str, claves: set[str]) -> set[str]:
    """Cuáles de `claves` aparecen nombradas en el texto.

    Se busca el término con límites de palabra para que "alt" no case dentro de "alteración".
    """
    normalizado = sin_tildes(texto)
    lexico = lexico_analitos()
    encontradas = set()
    for clave in claves:
        terminos = lexico.get(clave) or tokens_analito(clave)
        if any(re.search(rf"\b{re.escape(t)}\b", normalizado) for t in terminos):
            encontradas.add(clave)
    return encontradas
