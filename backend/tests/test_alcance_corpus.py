"""Etiquetado de especie por rangos de página, y el filtro ejercido sobre el ÍNDICE REAL.

La última parte no es un extra. El filtro por especie de `retriever.py` llevaba tests desde su
implementación y los pasaba todos, pero montaban un índice sintético cuyas filas SÍ traían el
metadato `especie`. En el índice real los 6772 chunks lo tenían vacío, así que el filtro no
excluía nada nunca. Un test contra un fixture no puede ver eso; sólo puede verlo un test que
mire el índice que se despliega. Se omite (no falla) donde el índice no está —CI, clon limpio—,
que es la única forma de que sea ejecutable a la vez en local y en un runner sin los 73 MB.
"""

from __future__ import annotations

import json

import pytest

from app.rag.alcance_corpus import (
    RangoAlcance,
    cargar_descartes,
    cargar_rangos,
    debe_descartarse,
    es_listado_de_contenidos,
    especie_de,
    fraccion_lideres_de_puntos,
    numero_de_pagina,
)

LIBRO_HEMATO = "Veterinary Hematology, Clinical Chemistry, and Cytology, 3rd Edition"


# --- Lectura de páginas -------------------------------------------------------------------

@pytest.mark.parametrize(
    ("campo", "esperado"),
    [
        ("305", 305),
        ("305–306", 305),  # guion largo: es el que escribe la ingesta
        ("305-306", 305),
        ("", None),
        ("s/n", None),
    ],
)
def test_numero_de_pagina(campo, esperado):
    assert numero_de_pagina(campo) == esperado


# --- Resolución por rango -----------------------------------------------------------------

def test_seccion_no_domestica_se_etiqueta():
    assert especie_de(LIBRO_HEMATO, "300") == "no_domestico"


def test_seccion_domestica_queda_sin_etiquetar():
    """Vacío = «vale para cualquier especie». Es lo que debe pasarle a la mayoría del corpus."""
    assert especie_de(LIBRO_HEMATO, "200") == ""
    assert especie_de(LIBRO_HEMATO, "500") == ""


@pytest.mark.parametrize("pagina", ["253", "358", "605", "650"])
def test_los_limites_del_rango_son_inclusivos(pagina):
    assert especie_de(LIBRO_HEMATO, pagina) == "no_domestico"


@pytest.mark.parametrize("pagina", ["252", "359", "604", "651"])
def test_justo_fuera_del_rango_no_se_etiqueta(pagina):
    assert especie_de(LIBRO_HEMATO, pagina) == ""


def test_otro_libro_no_se_ve_afectado():
    """Los rangos son de UN libro: las mismas páginas de otro no significan lo mismo."""
    assert especie_de("Fundamentals of Veterinary Clinical Pathology", "300") == ""


def test_sin_pagina_se_conserva_el_valor_del_libro():
    assert especie_de(LIBRO_HEMATO, "", por_defecto="felino") == "felino"


def test_el_rango_gana_al_valor_del_libro():
    """En un texto comparado la sección es más específica que el tomo."""
    assert especie_de(LIBRO_HEMATO, "300", por_defecto="canino") == "no_domestico"


def test_sin_fichero_de_alcance_no_se_etiqueta_nada(tmp_path):
    """Que falte el mapa degrada al comportamiento anterior, no revienta la ingesta."""
    cargar_rangos.cache_clear()
    try:
        assert cargar_rangos(tmp_path / "no_existe.json") == ()
        assert especie_de(LIBRO_HEMATO, "300", ruta=tmp_path / "no_existe.json") == ""
    finally:
        cargar_rangos.cache_clear()


def test_se_leen_los_rangos_declarados(tmp_path):
    ruta = tmp_path / "alcance.json"
    ruta.write_text(
        json.dumps({"rangos": [
            {"libro_empieza_por": "Libro X", "desde": 10, "hasta": 20, "especie": "aves"}
        ]}),
        encoding="utf-8",
    )
    cargar_rangos.cache_clear()
    try:
        assert especie_de("Libro X, 2.ª ed.", "15", ruta=ruta) == "aves"
        assert especie_de("Libro X, 2.ª ed.", "25", ruta=ruta) == ""
    finally:
        cargar_rangos.cache_clear()


def test_cubre_exige_prefijo_de_libro():
    r = RangoAlcance("Veterinary Hematology", 1, 10, "no_domestico")
    assert r.cubre("Veterinary Hematology, 3rd Edition", 5)
    assert not r.cubre("Otra Cosa Veterinary Hematology", 5)


# --- Descarte del índice alfabético -------------------------------------------------------

LIBRO_FUNDAMENTALS = "Fundamentals of Veterinary Clinical Pathology, 3rd Edition"


@pytest.mark.parametrize(
    ("libro", "pagina"),
    [
        (LIBRO_HEMATO, "1026"),   # primera del índice final (página escaneada ilegible)
        (LIBRO_HEMATO, "1058"),   # última
        (LIBRO_FUNDAMENTALS, "1249"),
        (LIBRO_FUNDAMENTALS, "1296"),
        (LIBRO_HEMATO, "1"),      # preliminares: portada
        (LIBRO_HEMATO, "9"),      # índice general
        (LIBRO_HEMATO, "18"),     # última de preliminares
        (LIBRO_FUNDAMENTALS, "1"),
        (LIBRO_FUNDAMENTALS, "18"),
        (LIBRO_HEMATO, "793"),    # «Clinical Case Presentations: Contents»
        (LIBRO_HEMATO, "795"),
    ],
)
def test_los_indices_y_preliminares_se_descartan(libro, pagina):
    assert debe_descartarse(libro, pagina)


@pytest.mark.parametrize(
    ("libro", "pagina"),
    [
        (LIBRO_HEMATO, "1025"),        # último caso clínico, justo antes del índice
        (LIBRO_FUNDAMENTALS, "1248"),  # Appendix A
        (LIBRO_HEMATO, "300"),         # sección no doméstica: se etiqueta, NO se descarta
        (LIBRO_FUNDAMENTALS, "1026"),  # la página del otro libro no significa lo mismo
        (LIBRO_HEMATO, "19"),          # empieza el contenido en ambos libros
        (LIBRO_FUNDAMENTALS, "19"),
        (LIBRO_HEMATO, "796"),         # Caso 1, justo tras la lista de casos
    ],
)
def test_el_contenido_clinico_no_se_descarta(libro, pagina):
    assert not debe_descartarse(libro, pagina)


# --- Descarte por firma tipográfica (sumarios con líderes de puntos) -----------------------

SUMARIO = (
    "|I. Blood Samples . . . . . . . . . . . . . . . . . . . . . . . . 4| "
    "|II. Urine Samples . . . . . . . . . . . . . . . . . . . . . . . 6| "
    "|III. Reference Intervals . . . . . . . . . . . . . . . . . . . 18|"
)
PROSA_CLINICA = (
    "El paciente presenta una anemia regenerativa con reticulocitosis marcada. "
    "La hiperbilirrubinemia y la ictericia sugieren hemólisis... y conviene descartar IMHA."
)


def test_un_sumario_con_lideres_de_puntos_se_descarta():
    assert es_listado_de_contenidos(SUMARIO)
    # Sin depender del rango: un sumario de mitad del libro también cae.
    assert debe_descartarse(LIBRO_FUNDAMENTALS, "555", SUMARIO)


def test_la_prosa_clinica_no_es_un_sumario():
    """Una elipsis normal («hemólisis... y») no lleva los puntos espaciados."""
    assert not es_listado_de_contenidos(PROSA_CLINICA)
    assert not debe_descartarse(LIBRO_FUNDAMENTALS, "555", PROSA_CLINICA)


def test_una_tabla_con_algun_lider_suelto_se_conserva():
    """La cola de un sumario pegada al inicio del capítulo trae contenido real: se conserva.
    Fija el lado por el que debe equivocarse el umbral."""
    mixto = ". . . . . . . . . . . . 271| " + PROSA_CLINICA * 4
    assert not es_listado_de_contenidos(mixto)


def test_sin_texto_solo_deciden_los_rangos():
    assert not debe_descartarse(LIBRO_FUNDAMENTALS, "555")
    assert debe_descartarse(LIBRO_FUNDAMENTALS, "1250")


def test_fraccion_de_lideres_en_texto_vacio():
    assert fraccion_lideres_de_puntos("") == 0.0


def test_sin_pagina_no_se_descarta():
    """Ante la duda se conserva: perder literatura es peor que colar una entrada de índice."""
    assert not debe_descartarse(LIBRO_HEMATO, "")


def test_descartar_y_etiquetar_son_decisiones_independientes():
    """Una sección no doméstica se etiqueta para que el filtro la excluya, pero sigue en el
    corpus: si algún día Morphos atendiera aves, está ahí. El índice alfabético no vuelve."""
    assert especie_de(LIBRO_HEMATO, "300") == "no_domestico"
    assert not debe_descartarse(LIBRO_HEMATO, "300")


def test_sin_fichero_de_alcance_no_se_descarta_nada(tmp_path):
    cargar_descartes.cache_clear()
    try:
        assert cargar_descartes(tmp_path / "no_existe.json") == ()
        assert not debe_descartarse(LIBRO_HEMATO, "1030", ruta=tmp_path / "no_existe.json")
    finally:
        cargar_descartes.cache_clear()


# --- Contra el índice REAL ----------------------------------------------------------------

@pytest.fixture()
def tabla_real():
    lancedb = pytest.importorskip("lancedb")
    from app.config import obtener_config

    ruta = obtener_config().rag_index_dir
    if not ruta.exists():
        pytest.skip(f"sin índice RAG en {ruta} (usa `make fetch-index`)")
    db = lancedb.connect(str(ruta))
    # `table_names()` está deprecado pero devuelve una lista; `list_tables()` devuelve un objeto
    # paginado cuyos nombres viven en `.tables`. Se aceptan los dos para no atarse a la versión —
    # y porque dar por hecho que `list_tables()` era una lista hacía que este test se OMITIERA en
    # silencio, que en un test escrito para atrapar un fallo silencioso sería de chiste.
    listado = db.list_tables()
    nombres = getattr(listado, "tables", listado)
    if "literatura" not in nombres:
        pytest.skip("el índice no tiene la tabla 'literatura'")
    return db.open_table("literatura")


def test_el_indice_real_tiene_la_especie_poblada(tabla_real):
    """El fallo original, convertido en test: si vuelve a quedar todo vacío, el filtro está
    inerte otra vez y esto lo dice, en vez de descubrirse auditando a mano meses después."""
    especies = tabla_real.to_pandas()["especie"].fillna("")
    etiquetados = (especies != "").sum()
    assert etiquetados > 0, (
        "todos los fragmentos del índice real tienen `especie` vacía: el filtro por especie "
        "no excluye nada. ¿Se reingirió sin `data/rag_alcance.json` o falta `retag_especie.py`?"
    )


def test_la_seccion_no_domestica_esta_marcada_en_el_indice_real(tabla_real):
    df = tabla_real.to_pandas()
    seccion = df[
        df["libro"].str.startswith("Veterinary Hematology")
        & df["pagina"].str.match(r"(2[5-9]\d|3[0-4]\d|35[0-8])(\D|$)")
    ]
    if seccion.empty:
        pytest.skip("el índice no contiene la SECTION III de ese libro")
    sin_marcar = (seccion["especie"].fillna("") == "").sum()
    assert sin_marcar == 0, f"{sin_marcar} fragmentos de la sección no doméstica sin etiquetar"


def test_el_indice_real_no_conserva_indices_ni_sumarios(tabla_real):
    """Ni índices, ni sumarios, ni preliminares deben seguir en el corpus desplegado."""
    df = tabla_real.to_pandas()
    quedan = [
        f"{f.libro[:30]} p.{f.pagina}"
        for f in df.itertuples()
        if debe_descartarse(f.libro, f.pagina, f.texto)
    ]
    assert not quedan, f"{len(quedan)} fragmentos de índice/sumario siguen en el índice: {quedan[:3]}"


def test_el_material_canino_sigue_disponible(tabla_real):
    """La otra mitad del riesgo: etiquetar de más deja al modelo sin literatura."""
    df = tabla_real.to_pandas()
    disponibles = df[df["especie"].fillna("") == ""]
    assert len(disponibles) > 0.85 * len(df), (
        f"sólo {len(disponibles)}/{len(df)} fragmentos quedan disponibles para un paciente "
        "canino o felino: el etiquetado está recortando demasiado corpus"
    )
