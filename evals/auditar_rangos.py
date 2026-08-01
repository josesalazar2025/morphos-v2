"""Cosecha TODOS los intervalos de referencia impresos en los dos libros del índice RAG y los
compara con data/valores_referencia.json.

No usa recuperación semántica: escanea las 6763 filas de la tabla LanceDB y extrae filas de
tabla markdown con forma `|Analito (unidad)|valor|lo–hi|`. La especie se infiere del texto del
propio fragmento (señalamiento del caso) y la clave del analito se decide POR UNIDAD, para no
confundir un recuento relativo (%) con uno absoluto (×10³/µL).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path("/Users/josesalazar/morphos_rev/morphos")
sys.path.insert(0, str(RAIZ / "backend"))

import lancedb  # noqa: E402

from app.config import obtener_config  # noqa: E402

# nombre normalizado -> (clave si la unidad es absoluta/propia, clave si la unidad es %)
ANALITOS: dict[str, tuple[str | None, str | None]] = {
    "pcv": ("hct", None), "hct": ("hct", None), "hematocrit": ("hct", None),
    "hgb": ("hgb", None), "hemoglobin": ("hgb", None),
    "rbc": ("rbc", None), "rbcs": ("rbc", None),
    "mcv": ("vcm", None), "mchc": ("chcm", None), "mch": ("hcm", None), "rdw": ("rdw", None),
    "wbc": ("wbc", None), "nucleated cells": ("wbc", None), "ncc": ("wbc", None),
    "segs": ("neutro_abs", "neutro"), "segmented neutrophils": ("neutro_abs", "neutro"),
    "neutrophils": ("neutro_abs", "neutro"),
    "lymphs": ("linfo_abs", "linfo"), "lymphocytes": ("linfo_abs", "linfo"),
    "monos": ("mono_abs", "mono"), "monocytes": ("mono_abs", "mono"),
    "eos": ("eosino_abs", "eosino"), "eosinophils": ("eosino_abs", "eosino"),
    "platelets": ("plt", None), "plt": ("plt", None),
    "retics": ("reti_abs", "reti"), "reticulocytes": ("reti_abs", "reti"),
    "gluc": ("gluc", None), "glucose": ("gluc", None),
    "bun": ("bun", None), "urea": ("bun", None), "un": ("bun", None),
    "creat": ("creat", None), "creatinine": ("creat", None),
    "ca": ("calc", None), "calcium": ("calc", None), "tca": ("calc", None),
    "phos": ("fosf", None), "phosphorus": ("fosf", None),
    "tp": ("prot", None), "total protein": ("prot", None), "tp p": ("prot", None),
    "alb": ("alb", None), "albumin": ("alb", None),
    "glob": ("glob", None), "globulin": ("glob", None), "globulins": ("glob", None),
    "t. bili": ("bili", None), "tbili": ("bili", None), "bilirubin": ("bili", None),
    "chol": ("colest", None), "cholesterol": ("colest", None),
    "alt": ("alt", None), "ast": ("ast", None), "alp": ("fal", None), "sap": ("fal", None),
    "ggt": ("ggt", None), "ck": ("ck", None), "creatine kinase": ("ck", None),
    "amylase": ("amylasa", None), "lipase": ("lipasa", None),
    "na": ("sodio", None), "sodium": ("sodio", None),
    "cl": ("cloro", None), "chloride": ("cloro", None),
    "k": ("potasio", None), "potassium": ("potasio", None),
    "tco2": ("tco2", None), "mg": ("magnesio", None), "magnesium": ("magnesio", None),
    "t4": ("t4_total", None), "total t4": ("t4_total", None), "tt4": ("t4_total", None),
    "plasma protein": ("prot", None), "pp": ("prot", None),
}

PERRO = re.compile(r"\b(dog|canine|bitch|puppy|puppies|retriever|shepherd|terrier|poodle|beagle|dachshund|boxer|schnauzer|spaniel|rottweiler|collie|husky|greyhound)\b", re.I)
GATO = re.compile(r"\b(cat|feline|kitten|queen|DSH|DLH|domestic shorthair|domestic longhair|siamese|persian|abyssinian)\b", re.I)
OTRAS = re.compile(r"\b(horse|equine|foal|pony|cow|bovine|calf|cattle|sheep|ovine|goat|caprine|llama|alpaca|pig|porcine|ferret|rabbit|bird|avian|parrot|frog|reptile|snake|turtle)\b", re.I)

FILA = re.compile(
    r"\|\s*\*{0,2}~{0,2}([A-Za-z][^|]{0,34}?)~{0,2}\*{0,2}\s*\|"
    r"[^|]{0,40}?\|?"
    r"\s*\*{0,2}(\d[\d.,]*)\s*[–-]\s*(\d[\d.,]*)\*{0,2}\s*\|"
)


def limpiar(txt: str) -> tuple[str, str]:
    """(nombre normalizado, unidad en minúsculas)."""
    txt = re.sub(r"<[^>]+>", " ", txt)
    unidad = " ".join(re.findall(r"\(([^)]*)\)", txt)).lower()
    nombre = re.sub(r"\([^)]*\)", " ", txt)
    nombre = re.sub(r"[~_*]", " ", nombre)
    return re.sub(r"\s+", " ", nombre).strip().lower(), unidad


def especie_del_fragmento(texto: str) -> str | None:
    if OTRAS.search(texto):
        return None
    perro, gato = len(PERRO.findall(texto)), len(GATO.findall(texto))
    if perro and not gato:
        return "canino"
    if gato and not perro:
        return "felino"
    return None


def main() -> None:
    cfg = obtener_config()
    df = lancedb.connect(str(cfg.rag_index_dir)).open_table("literatura").to_pandas()

    cosecha: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for _, fila in df.iterrows():
        texto = fila["texto"]
        if "|" not in texto:
            continue
        especie = especie_del_fragmento(texto)
        if especie is None:
            continue
        libro = "Thrall" if "Hematology" in fila["libro"] else "Fundamentals"
        for m in FILA.finditer(texto):
            nombre, unidad = limpiar(m.group(1))
            par = ANALITOS.get(nombre)
            if not par:
                continue
            clave = par[1] if "%" in unidad and par[1] else par[0]
            if not clave:
                continue
            try:
                lo, hi = float(m.group(2).replace(",", "")), float(m.group(3).replace(",", ""))
            except ValueError:
                continue
            if lo >= hi or hi > 100000:
                continue
            cosecha[(especie, clave, libro)][(lo, hi)] += 1

    nuestros = json.loads((RAIZ / "data/valores_referencia.json").read_text(encoding="utf-8"))
    salida: dict = {}
    for (especie, clave, libro), cnt in cosecha.items():
        salida.setdefault(especie, {}).setdefault(clave, {})[libro] = {
            "modal": list(cnt.most_common(1)[0][0]),
            "n": sum(cnt.values()),
            "variantes": [[*k, v] for k, v in cnt.most_common()],
        }

    for especie in ("canino", "felino"):
        print(f"\n{'='*112}\n{especie.upper()}\n{'='*112}")
        print(f"{'analito':<11}{'Morphos':<15}{'Thrall (modal, n, variantes)':<42}{'Fundamentals':<30}{'¿coincide?'}")
        for clave in sorted(salida.get(especie, {})):
            ref = nuestros[especie].get(clave)
            mio = f"{ref['inferior']}-{ref['superior']}" if ref else "SIN RANGO"
            celdas = []
            for libro in ("Thrall", "Fundamentals"):
                d = salida[especie][clave].get(libro)
                if not d:
                    celdas.append("—")
                    continue
                var = "; ".join(f"{a:g}-{b:g}×{c}" for a, b, c in d["variantes"][:3])
                celdas.append(f"{d['modal'][0]:g}-{d['modal'][1]:g} (n={d['n']}) [{var}]")
            veredicto = ""
            d = salida[especie][clave].get("Thrall")
            if ref and d:
                mlo, mhi = d["modal"]
                veredicto = "=" if (mlo, mhi) == (ref["inferior"], ref["superior"]) else "DIFIERE"
            print(f"{clave:<11}{mio:<15}{celdas[0]:<42}{celdas[1]:<30}{veredicto}")

    Path("/Users/josesalazar/.claude/jobs/cf8c6f9d/tmp/cosecha_rangos.json").write_text(
        json.dumps(salida, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
