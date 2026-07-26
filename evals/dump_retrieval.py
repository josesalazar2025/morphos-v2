"""Vuelca los fragmentos recuperados por caso (para juzgar la relevancia fuera de línea, p.
ej. por el propio asistente en sesión, sin API key). La config se toma del entorno."""

from __future__ import annotations

import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "backend"))

from run_retrieval_eval import cargar_casos, construir_query_eval  # noqa: E402

from app.config import obtener_config  # noqa: E402
from app.rag.retriever import recuperar  # noqa: E402


def main() -> None:
    salida = Path(sys.argv[1])
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    cfg = obtener_config()
    filas = []
    for caso in cargar_casos():
        query = construir_query_eval(caso)
        frags = recuperar(query, especie=caso.get("paciente", {}).get("especie"), top_k=k)
        filas.append({
            "id": caso["id"],
            "descripcion": caso.get("descripcion", ""),
            "diferenciales_esperados": caso.get("esperado", {}).get("diferenciales_aceptables", []),
            "query": query,
            "fragmentos": [
                {"n": i + 1, "capitulo": f.capitulo, "pagina": f.pagina, "texto": f.texto[:320]}
                for i, f in enumerate(frags)
            ],
        })
    meta = {"embed": cfg.rag_embed_model, "query_lang": cfg.rag_query_lang,
            "hibrido": cfg.rag_hibrido, "rerank": cfg.rag_rerank}
    salida.write_text(json.dumps({"config": meta, "casos": filas}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"escrito {salida} | config={meta}")


if __name__ == "__main__":
    main()
