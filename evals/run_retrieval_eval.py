"""Evaluación de RECUPERACIÓN RAG (aislada de la generación) para decidir por datos.

Objetivo: comparar configuraciones de recuperación (modelo de embeddings × idioma de
consulta) sobre los casos dorados, midiendo si los fragmentos recuperados son relevantes
al diagnóstico esperado. Permite el A/B bge-m3(ES) vs bge-m3(EN) vs MedCPT(EN) antes de
invertir en el reranking del Tier 2.

Uso (el índice debe existir para la config activa):
    # 1) baseline actual
    MORPHOS_RAG_EMBED_MODEL=BAAI/bge-m3 MORPHOS_RAG_QUERY_LANG=es \
        cd backend && make ingest && cd ../evals && uv run --group evals python run_retrieval_eval.py --etiqueta bge-m3-es
    # 2) misma indexación, consulta en inglés (no requiere reindexar)
    MORPHOS_RAG_QUERY_LANG=en uv run --group evals python run_retrieval_eval.py --etiqueta bge-m3-en

La relevancia se juzga con Claude si hay ANTHROPIC_API_KEY (robusto a ES-concepto/EN-corpus);
si no, cae a un heurístico de solape de palabras clave (aproximado, se marca como tal).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ / "backend"))


def cargar_casos() -> list[dict]:
    lineas = (AQUI / "dataset" / "casos.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lineas if ln.strip()]


def construir_query_eval(caso: dict) -> str:
    """Arma la consulta desde los HALLAZGOS del caso (no desde la respuesta, para no filtrar):
    descripción + analitos clave + signos clínicos."""
    partes = [caso.get("descripcion", "")]
    partes.extend(caso.get("esperado", {}).get("hallazgos_clave", []))
    if caso.get("signos_clinicos"):
        partes.append(caso["signos_clinicos"])
    return " ; ".join(p for p in partes if p)[:512]


# --- Métricas (puras, testeables sin índice) ---

def precision_en_k(relevancias: list[bool]) -> float:
    return sum(relevancias) / len(relevancias) if relevancias else 0.0


def rango_reciproco(relevancias: list[bool]) -> float:
    for i, rel in enumerate(relevancias, 1):
        if rel:
            return 1.0 / i
    return 0.0


def hubo_acierto(relevancias: list[bool]) -> bool:
    return any(relevancias)


def resumen(relevancias_por_caso: list[list[bool]]) -> dict:
    if not relevancias_por_caso:
        return {"n_casos": 0, "precision@k": 0.0, "hit_rate": 0.0, "mrr": 0.0}
    n = len(relevancias_por_caso)
    return {
        "n_casos": n,
        "precision@k": round(sum(precision_en_k(r) for r in relevancias_por_caso) / n, 3),
        "hit_rate": round(sum(hubo_acierto(r) for r in relevancias_por_caso) / n, 3),
        "mrr": round(sum(rango_reciproco(r) for r in relevancias_por_caso) / n, 3),
    }


# --- Juez de relevancia ---

def _juez_keyword(caso: dict, textos: list[str]) -> list[bool]:
    """Heurístico: traduce los conceptos esperados a inglés y busca solape de palabras."""
    from app.rag.traduccion_consulta import traducir_consulta

    aceptables = caso.get("esperado", {}).get("diferenciales_aceptables", [])
    claves = set()
    for concepto in aceptables:
        for palabra in traducir_consulta(concepto, "en").lower().split():
            if len(palabra) > 4:
                claves.add(palabra)
    return [any(c in t.lower() for c in claves) for t in textos]


def _juez_claude(caso: dict, textos: list[str]) -> list[bool]:
    """Juez LLM: ¿cada fragmento es clínicamente relevante al diagnóstico esperado del caso?"""
    from anthropic import Anthropic

    cliente = Anthropic()
    dx = ", ".join(caso.get("esperado", {}).get("diferenciales_aceptables", []))
    relevancias: list[bool] = []
    for texto in textos:
        msg = cliente.messages.create(
            model=os.environ.get("MORPHOS_CLAUDE_MODEL", "claude-fable-5"),
            max_tokens=5,
            messages=[{
                "role": "user",
                "content": (
                    f"Diagnóstico(s) esperado(s): {dx}\n\nFRAGMENTO:\n{texto[:1200]}\n\n"
                    "¿Es este fragmento clínicamente relevante para razonar ese diagnóstico? "
                    "Responde SOLO 'si' o 'no'."
                ),
            }],
        )
        relevancias.append(msg.content[0].text.strip().lower().startswith("si"))
    return relevancias


def evaluar(k: int, usar_claude: bool) -> int:
    from app.config import obtener_config
    from app.rag.retriever import recuperar

    cfg = obtener_config()
    casos = cargar_casos()
    juez = _juez_claude if usar_claude else _juez_keyword

    relevancias_por_caso: list[list[bool]] = []
    for caso in casos:
        query = construir_query_eval(caso)
        frags = recuperar(query, especie=caso.get("paciente", {}).get("especie"), top_k=k)
        if not frags:
            print(f"  ⚠ {caso['id']}: 0 fragmentos (¿índice construido para esta config?)")
            relevancias_por_caso.append([])
            continue
        rel = juez(caso, [f.texto for f in frags])
        relevancias_por_caso.append(rel)
        print(f"  {caso['id']}: {sum(rel)}/{len(rel)} relevantes")

    met = resumen(relevancias_por_caso)
    print("\n=== RESUMEN RECUPERACIÓN ===")
    print(f"config: embed={cfg.rag_embed_model} query_lang={cfg.rag_query_lang} "
          f"hibrido={cfg.rag_hibrido} rerank={cfg.rag_rerank} k={k} "
          f"juez={'claude' if usar_claude else 'keyword(aprox)'}")
    print(json.dumps(met, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval de recuperación RAG (A/B de configs)")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--etiqueta", default="", help="etiqueta informativa de la config")
    parser.add_argument("--keyword", action="store_true", help="fuerza el juez heurístico (sin Claude)")
    args = parser.parse_args()
    usar_claude = bool(os.environ.get("ANTHROPIC_API_KEY")) and not args.keyword
    if args.etiqueta:
        print(f"# config: {args.etiqueta}")
    sys.exit(evaluar(args.k, usar_claude))


if __name__ == "__main__":
    main()
