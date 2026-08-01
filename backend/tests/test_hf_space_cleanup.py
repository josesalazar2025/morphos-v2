"""Regresión de la limpieza y detección de salida defectuosa del HF Space (medGemma).

medGemma es un modelo con "pensamiento" que de forma intermitente filtra su cadena de
razonamiento en inglés y/o entra en un bucle de repetición sin llegar a la respuesta. Estas
pruebas fijan que esa salida se detecte (para forzar un reintento) y no llegue al usuario.
"""

from __future__ import annotations

import pytest

from app.ai.hf_space import (
    _cortar_bucle_lineas,
    interpretacion_defectuosa,
    interpretacion_truncada,
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


# El corte a mitad de frase es el único defecto que se ve completo: texto largo, sin
# repeticiones y sin razonamiento filtrado. Visto en producción (colestasis-felino).
_SALIDA_TRUNCADA = (
    "El paciente presenta elevación de ALT, ALP y bilirrubina, compatible con un patrón "
    "mixto de daño hepatocelular y colestasis. Las principales diferencias diagnósticas "
    "a considerar incluyen la lip"
)


def test_detecta_respuesta_cortada_a_mitad_de_frase():
    assert interpretacion_truncada(_SALIDA_TRUNCADA) is True
    assert interpretacion_defectuosa(_SALIDA_TRUNCADA) is True


def test_respuesta_completa_no_se_marca_como_truncada():
    assert interpretacion_truncada(_SALIDA_VALIDA) is False


def test_cierre_con_adornos_markdown_no_es_truncamiento():
    assert interpretacion_truncada(_SALIDA_VALIDA + "**") is False
    assert interpretacion_truncada(_SALIDA_VALIDA[:-1] + '.")') is False


def test_lista_final_corta_sin_punto_no_es_truncamiento():
    """Falso positivo a evitar: una recomendación en viñeta no lleva punto y es válida."""
    texto = _SALIDA_VALIDA + "\n- Ecografía abdominal\n- Perfil de coagulación"
    assert interpretacion_truncada(texto) is False


# --- Modo estructurado (hf_space_estructurado) ---

def _cliente(monkeypatch, estructurado: bool):
    """Instancia el cliente con el flag puesto, invalidando la config cacheada."""
    from app.ai.hf_space import HFSpaceClient
    from app.config import obtener_config

    monkeypatch.setenv("MORPHOS_HF_SPACE_ESTRUCTURADO", "1" if estructurado else "0")
    obtener_config.cache_clear()
    try:
        return HFSpaceClient()
    finally:
        monkeypatch.undo()
        obtener_config.cache_clear()


def test_el_nombre_distingue_el_modo(monkeypatch):
    # El servicio decide por el nombre si aplica el prompt de prosa y si exige estructura.
    assert _cliente(monkeypatch, False).nombre == "medgemma-hf"
    assert _cliente(monkeypatch, True).nombre == "medgemma-hf-json"


def test_parsea_json_del_space(monkeypatch):
    import json as _json

    from app.ai.hf_space import HFSpaceClient

    payload = _json.dumps({
        "interpretacion": "Anemia microcítica hipocrómica compatible con ferropenia.",
        "hallazgos_clave": [{"analito": "hct", "direccion": "bajo", "gravedad": "moderado", "comentario": ""}],
        "diferenciales": [{"nombre": "ferropenia", "probabilidad": "alta", "evidencia": [], "citas": []}],
        "siguientes_pruebas": ["sangre oculta en heces"],
        "confianza": "media",
        "requiere_derivacion": True,
    })
    r = HFSpaceClient._parsear_estructurado(payload)
    assert r.diferenciales[0].nombre == "ferropenia"
    assert r.hallazgos_clave[0].analito == "hct"


def test_json_invalido_es_error_reintentable():
    from app.ai.base import ErrorModelo
    from app.ai.hf_space import HFSpaceClient

    with pytest.raises(ErrorModelo) as exc:
        HFSpaceClient._parsear_estructurado("{no es json")
    assert exc.value.reintentable


def test_json_fuera_de_esquema_es_error_reintentable():
    from app.ai.base import ErrorModelo
    from app.ai.hf_space import HFSpaceClient

    # `interpretacion` vacía viola el validador del esquema.
    with pytest.raises(ErrorModelo):
        HFSpaceClient._parsear_estructurado('{"interpretacion": ""}')
