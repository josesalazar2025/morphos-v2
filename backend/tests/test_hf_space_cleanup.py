"""Regresión de la limpieza y detección de salida defectuosa del HF Space (medGemma).

medGemma es un modelo con "pensamiento" que de forma intermitente filtra su cadena de
razonamiento en inglés y/o entra en un bucle de repetición sin llegar a la respuesta. Estas
pruebas fijan que esa salida se detecte (para forzar un reintento) y no llegue al usuario.
"""

from __future__ import annotations

from app.ai.hf_space import (
    _cortar_bucle_lineas,
    interpretacion_defectuosa,
    limpiar_respuesta,
)

_SALIDA_CON_RAZONAMIENTO = """thought
Here's a thinking process to arrive at the clinical interpretation:
1. Understand the Goal: interpret canine labs.
Highly Recommended:
* Serum Chemistry (repeat): To monitor liver enzymes and bilirubin.
* Serum Chemistry (repeat): To monitor liver enzymes and bilirubin.
* Serum Chemistry (repeat): To monitor liver enzymes and bilirubin.
"""

_SALIDA_VALIDA = (
    "Los hallazgos muestran neutrofilia moderada y linfopenia leve, con enzimas hepáticas "
    "elevadas y bilirrubina alta que sugieren un patrón colestásico. Los diferenciales "
    "principales son hiperadrenocorticismo y hepatopatía. Se recomienda urianálisis, perfil "
    "bioquímico y ecografía abdominal para confirmar."
)


def test_detecta_razonamiento_filtrado():
    assert interpretacion_defectuosa(limpiar_respuesta(_SALIDA_CON_RAZONAMIENTO)) is True


def test_detecta_bucle_de_repeticion():
    bucle = "Introducción válida del caso.\n" + "\n".join(
        ["* Repetir esta recomendación diagnóstica concreta."] * 5
    )
    assert interpretacion_defectuosa(bucle) is True


def test_detecta_salida_trivial():
    assert interpretacion_defectuosa("ok") is True


def test_interpretacion_valida_no_se_marca():
    assert interpretacion_defectuosa(limpiar_respuesta(_SALIDA_VALIDA)) is False


def test_corte_de_bucle_a_nivel_de_linea():
    texto = "Intro.\n" + "\n".join(["* Item largo repetido de prueba clínica."] * 6) + "\nfinal"
    cortado = _cortar_bucle_lineas(texto)
    assert cortado.count("Item largo repetido") < 6


def test_limpieza_conserva_respuesta_valida():
    # La limpieza no debe destruir una respuesta correcta.
    assert "colestásico" in limpiar_respuesta(_SALIDA_VALIDA)
