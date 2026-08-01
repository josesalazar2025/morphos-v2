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


def test_diversidad_prefiere_no_repetir_libro():
    filas = [_fila("A", "1", "t1"), _fila("A", "2", "t2"), _fila("A", "3", "t3"),
             _fila("B", "1", "t4")]
    top = R._aplicar_diversidad(filas, k=3, max_por_libro=2)
    assert [f["libro"] for f in top] == ["A", "A", "B"]


def test_diversidad_es_preferencia_no_limite_duro():
    """Si no hay material de otras fuentes, se rellena igual: mejor 3 del mismo libro que 2."""
    filas = [_fila("A", str(i), f"t{i}") for i in range(4)]
    assert len(R._aplicar_diversidad(filas, k=3, max_por_libro=2)) == 3


def test_suelo_de_relevancia_descarta_los_flojos():
    fuerte, flojo = _fila("A", "1", "t1"), _fila("A", "2", "t2")
    fuerte["_rerank_score"], flojo["_rerank_score"] = 2.0, -3.0
    assert R._filtrar_por_score([fuerte, flojo], 0.0) == [fuerte]


def test_suelo_de_relevancia_no_toca_lo_que_no_pasó_por_el_reranker():
    """RRF y distancia densa están en otra escala: aplicarles el umbral sería mezclar métricas."""
    filas = [_fila("A", "1", "t1")]
    filas[0]["_rrf_score"] = 0.016
    assert R._filtrar_por_score(filas, 0.5) == filas


def test_suelo_desactivado_por_defecto_no_filtra():
    filas = [_fila("A", "1", "t1")]
    filas[0]["_rerank_score"] = -9.0
    assert R._filtrar_por_score(filas, None) == filas


def test_candidatos_sin_fts_cae_a_vectorial(monkeypatch):
    class Cfg:
        rag_hibrido = True

    densa = [_fila("L", "1", "densa")]
    monkeypatch.setattr(R, "_buscar_vectorial", lambda *a, **k: densa)
    monkeypatch.setattr(R, "_buscar_lexico", lambda *a, **k: [])  # sin FTS
    assert R._recuperar_candidatos(Cfg(), None, None, "q", 10) == densa
