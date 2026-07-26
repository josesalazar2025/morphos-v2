"""Traducción ES→EN de la consulta de recuperación (vocabulario clínico controlado).

La consulta RAG no es texto libre: se arma con nombres de patrones/hallazgos que provienen
de un vocabulario ACOTADO (las 78 alteraciones de `alteraciones.json` + los analitos). Casi
todos son cognados grecolatinos; sólo un puñado de palabras conectivas/modificadoras difiere.
Por eso la traducción es un léxico determinista palabra-a-palabra (sin coste de LLM, auditable),
con paso directo (sin acentos) para los cognados no listados.

Motivación: encoders biomédicos de alto rendimiento (p. ej. MedCPT) son sólo-inglés. Traducir
la consulta a inglés permite evaluarlos, y además empareja mejor consulta↔corpus (inglés) incluso
con bge-m3. El troceo por embeddings/BM25 es en gran medida insensible al orden de palabras, así
que la traducción token-a-token (sin reordenar) es suficiente para recuperar.
"""

from __future__ import annotations

import re
import unicodedata

# Modificadores/conectores y raíces clínicas que NO son cognados limpios. Las claves están
# sin acentos y en minúsculas (así se normaliza el token antes de buscar). Ampliable.
_LEXICO: dict[str, str] = {
    # conectores / modificadores
    "de": "of", "del": "of", "en": "in", "y": "and", "o": "or", "con": "with", "sin": "without",
    "elevada": "elevated", "elevado": "elevated", "elevados": "elevated", "elevadas": "elevated",
    "elevacion": "elevation", "aumentada": "increased", "aumentado": "increased",
    "disminuida": "decreased", "disminuido": "decreased", "reducida": "reduced", "reducido": "reduced",
    "aislada": "isolated", "aislado": "isolated", "nivel": "level", "niveles": "levels",
    "bajo": "low", "baja": "low", "alto": "high", "alta": "high", "normal": "normal",
    "posible": "possible", "sospecha": "suspicion", "prolongado": "prolonged", "prolongada": "prolonged",
    "orina": "urine", "deficit": "deficiency", "hierro": "iron", "serico": "serum", "muy": "very",
    "concentracion": "concentration", "ratio": "ratio", "no": "non",
    "danio": "damage", "dano": "damage", "patron": "pattern", "toxico": "toxic",
    "subterapeutico": "subtherapeutic", "via": "route",
    # hematología
    "anemia": "anemia", "regenerativa": "regenerative", "regenerativo": "regenerative",
    "microcitica": "microcytic", "macrocitica": "macrocytic", "normocitica": "normocytic",
    "hipocromica": "hypochromic", "hemorragia": "hemorrhage", "sangrado": "bleeding",
    "eritrocitosis": "erythrocytosis", "eritrocitos": "erythrocytes",
    "leucocitosis": "leukocytosis", "leucopenia": "leukopenia", "leucocitos": "leukocytes",
    "neutrofilica": "neutrophilic", "neutrofilia": "neutrophilia", "neutropenia": "neutropenia",
    "linfocitica": "lymphocytic", "linfocitosis": "lymphocytosis", "linfopenia": "lymphopenia",
    "linfocitos": "lymphocytes", "eosinofilia": "eosinophilia", "monocitosis": "monocytosis",
    "trombocitopenia": "thrombocytopenia", "trombocitosis": "thrombocytosis",
    "reticulocitos": "reticulocytes", "reticulocitosis": "reticulocytosis",
    # hepático / pancreático
    "hepatocelular": "hepatocellular", "colestasico": "cholestatic", "colestasis": "cholestasis",
    "hiperbilirrubinemia": "hyperbilirubinemia", "hiperamylasemia": "hyperamylasemia",
    "pancreatitis": "pancreatitis", "hepatopatia": "hepatopathy",
    # renal / electrolitos
    "azotemia": "azotemia", "hiperuremia": "hyperuremia", "creatinina": "creatinine",
    "hiperglucemia": "hyperglycemia", "hipoglucemia": "hypoglycemia",
    "hiperproteinemia": "hyperproteinemia", "hipoproteinemia": "hypoproteinemia",
    "hipoalbuminemia": "hypoalbuminemia", "hiperalbuminemia": "hyperalbuminemia",
    "hipercalcemia": "hypercalcemia", "hipocalcemia": "hypocalcemia",
    "hipernatremia": "hypernatremia", "hiponatremia": "hyponatremia",
    "hiperpotasemia": "hyperkalemia", "hipopotasemia": "hypokalemia",
    "hiperfosforemia": "hyperphosphatemia", "hipofosforemia": "hypophosphatemia",
    "hipomagnesemia": "hypomagnesemia", "hipermagnesemia": "hypermagnesemia",
    "hiperuricemia": "hyperuricemia", "hiposthenuria": "hyposthenuria", "isosthenuria": "isosthenuria",
    # endocrino / otros
    "hipoadrenocorticismo": "hypoadrenocorticism", "hiperadrenocorticismo": "hyperadrenocorticism",
    "hipotiroidismo": "hypothyroidism", "hipertiroidismo": "hyperthyroidism",
    "coagulopatia": "coagulopathy", "acidosis": "acidosis", "alcalosis": "alkalosis",
    "respiratoria": "respiratory", "metabolica": "metabolic", "ionizada": "ionized",
    "fenobarbital": "phenobarbital", "ciclosporina": "cyclosporine", "insulina": "insulin",
    "cortisol": "cortisol",
    # descriptores clínicos no-cognados presentes en alteraciones.json (evita que pasen sin
    # traducir). Cubierto por test_traduccion_consulta::test_cobertura_alteraciones.
    "enfermedad": "disease", "aguda": "acute", "agudo": "acute", "agudas": "acute", "agudos": "acute",
    "libre": "free", "respuesta": "response", "estado": "state", "capacidad": "capacity",
    "diseminada": "disseminated", "diseminado": "disseminated", "intravascular": "intravascular",
    "suprimido": "suppressed", "suprimida": "suppressed", "deteriorada": "impaired", "deteriorado": "impaired",
    "multiples": "multiple", "multiple": "multiple", "primario": "primary", "primaria": "primary",
    "extrinseca": "extrinsic", "extrinseco": "extrinsic", "intrinseca": "intrinsic", "intrinseco": "intrinsic",
    "prolongados": "prolonged", "prolongadas": "prolonged", "cardiopatia": "cardiomyopathy",
    "miocardico": "myocardial", "potencialmente": "potentially", "protrombotico": "prothrombotic",
    "basal": "basal", "hematuria": "hematuria", "piuria": "pyuria", "proteinuria": "proteinuria",
    "progesterona": "progesterone", "troponina": "troponin", "antitrombina": "antithrombin",
    "hipoxemia": "hypoxemia", "hiperlactatemia": "hyperlactatemia",
    "hiperfibrinogenemia": "hyperfibrinogenemia", "hipofibrinogenemia": "hypofibrinogenemia",
    "coagulacion": "coagulation",
}

# Cognados/proper-nouns/acrónimos que pasan directos sin necesidad de entrada en el léxico
# (los usa el test de cobertura para no exigir traducción explícita de estos).
COGNADOS_PERMITIDOS: frozenset[str] = frozenset({
    "anion", "willebrand", "probnp", "addison", "cushing",
})


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _traducir_token(token: str) -> str:
    """Traduce un token conservando puntuación adyacente; cae a paso directo sin acentos."""
    m = re.match(r"^(\W*)(.*?)(\W*)$", token, re.DOTALL)
    pre, nucleo, post = m.group(1), m.group(2), m.group(3)
    if not nucleo:
        return token
    clave = _sin_acentos(nucleo).lower()
    traducido = _LEXICO.get(clave)
    if traducido is None:
        # Cognato no listado (anemia, azotemia…): paso directo sin acentos.
        traducido = _sin_acentos(nucleo)
        if nucleo.isupper():
            traducido = traducido.upper()
    return f"{pre}{traducido}{post}"


def traducir_consulta(consulta: str, idioma_destino: str = "en") -> str:
    """Traduce la consulta al idioma destino. Sólo 'en' está soportado; cualquier otro
    valor (incl. 'es') devuelve la consulta intacta."""
    if idioma_destino != "en" or not consulta.strip():
        return consulta
    return " ".join(_traducir_token(t) for t in consulta.split(" "))
