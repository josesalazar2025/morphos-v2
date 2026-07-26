"""Regresión del traductor determinista ES→EN de la consulta de recuperación."""

from __future__ import annotations

import pytest

from app.rag.traduccion_consulta import traducir_consulta


@pytest.mark.parametrize(
    "es,en",
    [
        ("Anemia", "anemia"),  # cognato: paso directo
        ("Azotemia", "azotemia"),  # cognato
        ("Eritrocitosis", "erythrocytosis"),  # raíz no-cognata (eritro→erythro)
        ("Leucocitosis neutrofílica", "leukocytosis neutrophilic"),
        ("Daño hepatocelular", "damage hepatocellular"),
        ("Patrón colestásico", "pattern cholestatic"),
        ("Hiperpotasemia", "hyperkalemia"),  # potasemia→kalemia
        ("Creatinina elevada", "creatinine elevated"),
        ("Déficit de hierro sérico", "deficiency of iron serum"),
    ],
)
def test_traducciones_clave(es, en):
    assert traducir_consulta(es, "en") == en


def test_idioma_es_es_identidad():
    consulta = "Anemia ; Daño hepatocelular ; Hiperpotasemia"
    assert traducir_consulta(consulta, "es") == consulta


def test_separador_de_consulta_se_conserva():
    # construir_consulta une términos con ' ; '
    salida = traducir_consulta("Anemia ; Azotemia", "en")
    assert ";" in salida
    assert "anemia" in salida and "azotemia" in salida


def test_siglas_en_mayuscula_se_conservan():
    assert traducir_consulta("BUN", "en") == "BUN"


def test_vacio_no_rompe():
    assert traducir_consulta("", "en") == ""


def test_cobertura_alteraciones():
    """Guarda de mantenimiento (recomendación de la revisión): toda palabra de contenido de
    data/alteraciones.json debe estar en el léxico o en la allowlist de cognados. Si se añade
    una alteración con un término no-cognado nuevo, este test falla y obliga a traducirlo."""
    import json
    import re
    from pathlib import Path

    from app.rag.traduccion_consulta import _LEXICO, COGNADOS_PERMITIDOS, _sin_acentos

    ruta = Path(__file__).resolve().parents[2] / "data" / "alteraciones.json"
    alt = json.loads(ruta.read_text(encoding="utf-8"))
    palabras: set[str] = set()
    for v in alt.values():
        if isinstance(v, dict):
            for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", v.get("nombre", "").lower()):
                palabras.add(_sin_acentos(w))
    sin_cubrir = {w for w in palabras if len(w) >= 5 and w not in _LEXICO and w not in COGNADOS_PERMITIDOS}
    assert not sin_cubrir, f"Términos sin traducir (añádelos al léxico o a COGNADOS_PERMITIDOS): {sorted(sin_cubrir)}"
