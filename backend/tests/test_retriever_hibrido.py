"""Regresión de la lógica de recuperación híbrida + reranking (Tier 2).

Prueba las piezas puras (RRF, reranking, fallback híbrido) con dobles de prueba; la
integración real con LanceDB/cross-encoder se valida tras `make ingest`.
"""

from __future__ import annotations

from app.rag import retriever as R


def _fila(libro, pagina, texto):
    return {"libro": libro, "pagina": pagina, "texto": texto, "especie": ""}


def test_rrf_prioriza_lo_alto_en_ambas_listas():
    a = _fila("L", "1", "anemia regenerativa reticulocitosis")
    b = _fila("L", "2", "colestasis hepatica")
    c = _fila("L", "3", "azotemia renal")
    densa = [a, b, c]
    lexica = [b, a, c]  # b y a arriba en ambas
    fus = R.fusion_rrf([densa, lexica], n=3)
    # 'a' o 'b' (altos en ambas) deben ir por delante de 'c'
    assert R._clave_fila(fus[-1]) == R._clave_fila(c)


def test_rrf_deduplica_por_clave():
    a = _fila("L", "1", "texto uno")
    fus = R.fusion_rrf([[a], [a]], n=5)
    assert len(fus) == 1


def test_rrf_respeta_n():
    filas = [_fila("L", str(i), f"t{i}") for i in range(10)]
    assert len(R.fusion_rrf([filas], n=4)) == 4


def test_reordenar_sin_reranker_conserva_orden(monkeypatch):
    monkeypatch.setattr(R, "_cargar_reranker", lambda: None)
    filas = [_fila("L", str(i), f"t{i}") for i in range(5)]
    assert R._reordenar("consulta", filas, k=3) == filas[:3]


def test_reordenar_con_reranker_ordena_por_score(monkeypatch):
    # Stub: puntúa por la posición del dígito en el texto (mayor = más relevante).
    class StubCE:
        def predict(self, pares):
            return [float(t.split("t")[-1]) for _, t in pares]

    monkeypatch.setattr(R, "_cargar_reranker", lambda: StubCE())
    filas = [_fila("L", str(i), f"t{i}") for i in range(5)]  # t0..t4
    top = R._reordenar("consulta", filas, k=2)
    assert [f["texto"] for f in top] == ["t4", "t3"]


def test_candidatos_sin_fts_cae_a_vectorial(monkeypatch):
    class Cfg:
        rag_hibrido = True

    densa = [_fila("L", "1", "densa")]
    monkeypatch.setattr(R, "_buscar_vectorial", lambda *a, **k: densa)
    monkeypatch.setattr(R, "_buscar_lexico", lambda *a, **k: [])  # sin FTS
    assert R._recuperar_candidatos(Cfg(), None, None, "q", 10) == densa
