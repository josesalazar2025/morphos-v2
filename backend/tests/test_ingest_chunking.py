"""Regresión del troceo estructural (Tier 1 RAG).

Valida las invariantes del troceo sin depender del grupo pesado `rag`: las funciones de
troceo no importan pymupdf4llm/sentence-transformers a nivel de módulo, así que corren en
el entorno `dev` por defecto con el contador de tokens heurístico.
"""

from __future__ import annotations

from app.rag.ingest import (
    _MIN_TOKENS_FRAGMENTO,
    CHUNK_TOKENS,
    SOLAPE_TOKENS,
    _cargar_contador_tokens,
    _ensamblar_documento,
    _extraer_parrafos,
    _limpiar_titulo,
    _texto_contextualizado,
    _titulo_valido,
    _trocear_estructural,
)

contar = _cargar_contador_tokens("BAAI/bge-m3")  # cae a heurística por palabras


def _chunks_desde_paginas(paginas):
    doc = _ensamblar_documento(paginas)
    return _trocear_estructural(_extraer_parrafos(doc), contar)


def test_fragmentos_cruzan_saltos_de_pagina():
    paginas = [
        (10, "# Anemia Regenerativa\n\nLa anemia regenerativa cursa con reticulocitosis."),
        (11, "La respuesta medular continúa describiéndose aquí sin cambio de tema."),
    ]
    chunks = _chunks_desde_paginas(paginas)
    assert any(c.pmin < c.pmax for c in chunks), "ningún fragmento cruza el salto de página"


def test_capitulo_se_puebla_y_sin_markup():
    paginas = [(5, "# **Nonregenerative Anemia**\n\nAusencia de respuesta reticulocitaria clara.")]
    chunks = _chunks_desde_paginas(paginas)
    assert chunks and chunks[0].capitulo == "Nonregenerative Anemia"
    assert all("*" not in c.capitulo for c in chunks)


def test_se_filtra_ruido_de_marca_de_agua_y_numeros_sueltos():
    paginas = [(7, "vetbooks.ir\n7\n\nContenido clínico real sobre eritrocitos y anemia.")]
    chunks = _chunks_desde_paginas(paginas)
    assert chunks
    assert all("vetbooks" not in c.texto.lower() for c in chunks)
    assert all(c.texto.strip() != "7" for c in chunks)


def test_tamano_acotado_por_tokens():
    grande = "oración clínica de prueba. " * 400
    chunks = _chunks_desde_paginas([(1, f"# Capítulo\n\n{grande}")])
    assert len(chunks) > 1
    for c in chunks:
        assert contar(c.texto) <= CHUNK_TOKENS + SOLAPE_TOKENS + 5


def test_marcadores_de_pagina_no_se_almacenan():
    chunks = _chunks_desde_paginas([(3, "Texto normal de una página cualquiera.")])
    assert all("〔p" not in c.texto for c in chunks)


def test_no_fragmentos_triviales_cuando_hay_continuacion():
    # Un encabezado seguido de cuerpo del mismo capítulo debe fusionarse, no quedar suelto.
    cuerpo = ("Descripción amplia del hallazgo clínico con longitud más que suficiente para "
              "superar con holgura el umbral mínimo de tokens exigido a un fragmento del índice.")
    chunks = _chunks_desde_paginas([(2, f"# Hallazgos\n\n{cuerpo}")])
    assert len(chunks) == 1
    assert chunks[0].capitulo == "Hallazgos"
    assert chunks[0].texto.startswith("Hallazgos ")  # el encabezado se fusionó con el cuerpo
    assert contar(chunks[0].texto) >= _MIN_TOKENS_FRAGMENTO


def test_texto_contextualizado_antepone_contexto():
    assert _texto_contextualizado("Contexto clínico.", "Cuerpo.") == "Contexto clínico.\n\nCuerpo."
    # Sin contexto (fallo al generar) → texto original intacto.
    assert _texto_contextualizado("", "Cuerpo.") == "Cuerpo."


def test_titulo_valido_rechaza_basura_ocr():
    # Cadenas reales observadas en el volcado de recuperación.
    for basura in ["va — yy ~~e~~", "ge", "° ~~g~~ e ~~E~~ s", "nRBC 100 WBC", "yy", "e"]:
        assert _titulo_valido(_limpiar_titulo(basura)) is False, basura


def test_titulo_valido_acepta_capitulos_reales():
    for bueno in ["Nonregenerative Anemia", "9 Regenerative Anemia", "ERYTHROCYTES",
                  "Sodium to Potassium Ratio", "Hallazgos de Laboratorio"]:
        assert _titulo_valido(_limpiar_titulo(bueno)) is True, bueno


def test_encabezado_basura_no_contamina_capitulo():
    # Un encabezado basura entre capítulos válidos no debe sobrescribir el capítulo vigente.
    paginas = [(5, "# Anemia Regenerativa\n\nCuerpo clínico del capítulo válido y suficiente.\n\n"
                   "# nRBC 100 WBC\n\nMás cuerpo clínico que sigue tras la cabecera basura.")]
    chunks = _chunks_desde_paginas(paginas)
    assert all(c.capitulo == "Anemia Regenerativa" for c in chunks), [c.capitulo for c in chunks]
