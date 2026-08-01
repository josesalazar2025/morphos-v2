"""Integración real con LanceDB (recomendación de la revisión): construye un índice temporal
con FTS y ejercita recuperar() end-to-end — búsqueda densa+léxica, RRF, filtro de especie y
construcción de Fragmento con procedencia. Se omite si el grupo pesado `rag` no está instalado.
"""

from __future__ import annotations

import pytest

lancedb = pytest.importorskip("lancedb")
np = pytest.importorskip("numpy")

from app.rag import retriever as R  # noqa: E402


class _EmbedStub:
    """Codifica por presencia de palabras clave: vectores separables y deterministas."""

    _terminos = ["anemia", "renal", "higado"]

    def encode(self, texto, normalize_embeddings=True):
        t = texto.lower()
        base = [1.0 if term in t else 0.0 for term in self._terminos]
        return np.array(base + [0.1] * 5, dtype="float32")


@pytest.fixture()
def indice(tmp_path):
    filas = [
        {"texto": "regenerative anemia with reticulocytosis in the dog", "libro": "Thrall",
         "edicion": "3e", "capitulo": "", "pagina": "120", "especie": "",
         "vector": _EmbedStub().encode("anemia").tolist()},
        {"texto": "chronic renal disease causes azotemia in cats", "libro": "Thrall",
         "edicion": "3e", "capitulo": "", "pagina": "300", "especie": "felino",
         "vector": _EmbedStub().encode("renal").tolist()},
        {"texto": "hepatocellular injury raises ALT in the liver", "libro": "Thrall",
         "edicion": "3e", "capitulo": "", "pagina": "500", "especie": "canino",
         "vector": _EmbedStub().encode("higado").tolist()},
    ]
    db = lancedb.connect(str(tmp_path))
    tabla = db.create_table("literatura", data=filas, mode="overwrite")
    tabla.create_fts_index("texto", replace=True)
    return tabla


def test_recuperar_end_to_end(monkeypatch, indice):
    monkeypatch.setattr(R, "_cargar_recursos", lambda: (_EmbedStub(), indice))
    monkeypatch.setattr(R, "_cargar_reranker", lambda: None)  # sin cross-encoder pesado
    frags = R.recuperar("anemia", top_k=2)
    assert frags, "no recuperó nada del índice real"
    top = frags[0]
    assert "anemia" in top.texto.lower()
    assert top.libro == "Thrall" and top.pagina == "120"
    assert "Thrall" in top.cita() and "p. 120" in top.cita()
    assert isinstance(top.score, float)  # RRF (sin rerank), orientado mayor = más relevante


def test_multiconsulta_recupera_lo_de_cada_patron(monkeypatch, indice):
    """El fallo que arregla la multi-consulta: 'anemia ; higado' en un solo embedding es un
    vector que no es ninguno de los dos. Con una consulta por patrón, ambos aparecen."""
    monkeypatch.setattr(R, "_cargar_recursos", lambda: (_EmbedStub(), indice))
    monkeypatch.setattr(R, "_cargar_reranker", lambda: None)

    frags = R.recuperar_multi(["anemia", "higado"], top_k=2)
    textos = " ".join(f.texto.lower() for f in frags)
    assert "anemia" in textos and "hepatocellular" in textos


def test_multiconsulta_con_una_sola_consulta_equivale_a_recuperar(monkeypatch, indice):
    monkeypatch.setattr(R, "_cargar_recursos", lambda: (_EmbedStub(), indice))
    monkeypatch.setattr(R, "_cargar_reranker", lambda: None)

    uno = R.recuperar_multi(["anemia"], top_k=2)
    directo = R.recuperar("anemia", top_k=2)
    assert [f.texto for f in uno] == [f.texto for f in directo]


def test_multiconsulta_respeta_el_filtro_de_especie(monkeypatch, indice):
    monkeypatch.setattr(R, "_cargar_recursos", lambda: (_EmbedStub(), indice))
    monkeypatch.setattr(R, "_cargar_reranker", lambda: None)

    frags = R.recuperar_multi(["higado liver ALT", "renal"], especie="felino", top_k=5)
    textos = " ".join(f.texto.lower() for f in frags)
    assert "hepatocellular" not in textos, "el fragmento canino no fue filtrado por especie"


def test_filtro_por_especie_excluye_otra_especie(monkeypatch, indice):
    monkeypatch.setattr(R, "_cargar_recursos", lambda: (_EmbedStub(), indice))
    monkeypatch.setattr(R, "_cargar_reranker", lambda: None)
    # 'hepatocellular…' es de especie canino y además casa por FTS ('liver', 'ALT').
    # Con especie=felino DEBE quedar filtrado (aunque lo devuelva la búsqueda léxica).
    frags = R.recuperar("higado liver ALT", especie="felino", top_k=5)
    textos = " ".join(f.texto.lower() for f in frags)
    assert "hepatocellular" not in textos, "el fragmento canino no fue filtrado por especie"
