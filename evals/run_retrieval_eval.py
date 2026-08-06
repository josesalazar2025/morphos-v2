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

La relevancia la juzga un LLM (robusto a ES-concepto/EN-corpus): por defecto el juez LOCAL y
GRATUITO servido por Ollama, y Claude si se pide con --juez claude y hay ANTHROPIC_API_KEY.
Sin ninguno de los dos cae a un heurístico de solape de palabras clave (aproximado, se marca
como tal en el resumen).
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
sys.path.insert(0, str(AQUI))  # para importar el paquete `judge`


def cargar_casos() -> list[dict]:
    lineas = (AQUI / "dataset" / "casos.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lineas if ln.strip()]


def _entradas_del_motor(caso: dict) -> tuple[list[str], list[str]]:
    """Nombres de patrón y de hallazgo TAL COMO los produce el motor para este caso.

    Pasa por `analisis.ts` (vía Node) igual que el servicio, porque la consulta de producción
    se arma con lo que el motor detecta, no con lo que el caso dorado declara.
    """
    from run_evals import _motor_determinista

    hallazgos, patrones = _motor_determinista(caso["valores"], caso["paciente"])
    return [p["nombre"] for p in patrones], [h["nombre"] for h in hallazgos]


def construir_query_eval(caso: dict) -> str:
    """La consulta EXACTA que emitiría producción para este caso.

    Antes se armaba a mano con `descripcion` + `esperado.hallazgos_clave` + `signos_clinicos`,
    y eso medía una recuperación que el servicio nunca ejecuta, en tres sentidos:

    1. **Claves en vez de nombres.** `hct`, `vcm`, `chcm` en lugar de «Hematocrito (Hct)»,
       «VCM (MCV)». Los nombres traen la SIGLA INGLESA, que es justo lo que casa con un corpus
       en inglés — sobre todo en la rama BM25, que es literal. La consulta medida era más pobre
       que la real.
    2. **Producción no manda `signos_clinicos`** en la consulta de recuperación: sólo patrones
       y hallazgos (`ai/service.py`).
    3. **`descripcion` es metadato del dataset y filtraba la respuesta.** «Anemia microcítica
       hipocrómica en perro» orienta la recuperación hacia el diagnóstico esperado, que es
       exactamente lo que el juez de relevancia luego premia. Misma familia de fuga que la que
       se corrigió en el juez clínico (ver resultados 2026-08-01, §4.5).

    Consecuencia: las cifras de recuperación anteriores al 2026-08-03 no son comparables con
    las de después, y el `precision@k` de aquel A/B no describía la recuperación de producción.
    """
    from app.rag.retriever import construir_consulta

    patrones, hallazgos = _entradas_del_motor(caso)
    return construir_consulta(patrones, hallazgos)


def construir_queries_eval(caso: dict) -> list[str]:
    """Versión multi-consulta de la anterior (una por patrón), para medir el A/B."""
    from app.rag.retriever import construir_consultas

    patrones, hallazgos = _entradas_del_motor(caso)
    return construir_consultas(patrones, hallazgos)


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


_PREGUNTA_RELEVANCIA = (
    "Diagnóstico(s) esperado(s): {dx}\n\nFRAGMENTO:\n{texto}\n\n"
    "¿Es este fragmento clínicamente relevante para razonar ese diagnóstico?"
)

_ESQUEMA_RELEVANCIA = {
    "type": "object",
    "properties": {"relevante": {"type": "boolean"}},
    "required": ["relevante"],
}


def _juez_cli(caso: dict, textos: list[str]) -> list[bool]:
    """Juez servido por el CLI de Claude Code: sin clave de API, con un modelo grande."""
    from judge.claude_cli import preguntar_json

    dx = ", ".join(caso.get("esperado", {}).get("diferenciales_aceptables", []))
    return [
        bool(
            preguntar_json(
                "Eres un patólogo clínico veterinario. Responde SOLO con el JSON pedido, "
                'con esta forma exacta: {"relevante": true|false}',
                _PREGUNTA_RELEVANCIA.format(dx=dx, texto=texto[:1200]),
            ).get("relevante", False)
        )
        for texto in textos
    ]


def _juez_ollama(caso: dict, textos: list[str]) -> list[bool]:
    """Juez LLM local y gratuito, con salida estructurada (booleano, sin parseo de prosa)."""
    from judge.ollama_local import preguntar_json

    dx = ", ".join(caso.get("esperado", {}).get("diferenciales_aceptables", []))
    return [
        bool(
            preguntar_json(
                "Eres un patólogo clínico veterinario. Responde SOLO con el JSON pedido.",
                _PREGUNTA_RELEVANCIA.format(dx=dx, texto=texto[:1200]),
                _ESQUEMA_RELEVANCIA,
                max_tokens=20,
            ).get("relevante", False)
        )
        for texto in textos
    ]


def _juez_claude(caso: dict, textos: list[str]) -> list[bool]:
    """Juez LLM de pago: ¿cada fragmento es relevante al diagnóstico esperado del caso?"""
    from anthropic import Anthropic

    cliente = Anthropic()
    # Sin fallback a Fable: cuesta el doble y exige retención de datos de 30 días (ver el
    # comentario en backend/app/config.py). El modelo lo fija la config del backend.
    modelo = os.environ.get("MORPHOS_CLAUDE_MODEL", "claude-opus-5")
    dx = ", ".join(caso.get("esperado", {}).get("diferenciales_aceptables", []))
    relevancias: list[bool] = []
    for texto in textos:
        msg = cliente.messages.create(
            model=modelo,
            max_tokens=5,
            messages=[{
                "role": "user",
                "content": _PREGUNTA_RELEVANCIA.format(dx=dx, texto=texto[:1200])
                + " Responde SOLO 'si' o 'no'.",
            }],
        )
        relevancias.append(msg.content[0].text.strip().lower().startswith("si"))
    return relevancias


def elegir_juez(preferencia: str):
    """Devuelve (funcion_juez, etiqueta). Mismo orden que el juez clínico: CLI de Claude
    Code → Ollama local → SDK de Claude → heurístico de palabras clave."""
    from judge import claude_cli
    from judge.ollama_local import disponible, modelo_juez

    if preferencia == "keyword":
        return _juez_keyword, "keyword(aprox)"
    if preferencia in ("auto", "cli"):
        ok, motivo = claude_cli.disponible()
        if ok:
            return _juez_cli, f"claude-cli:{claude_cli.modelo_cli()}"
        if preferencia == "cli":
            print(f"  ⚠ juez cli no disponible: {motivo}")
            return _juez_keyword, "keyword(aprox)"
    if preferencia in ("auto", "ollama"):
        ok, motivo = disponible()
        if ok:
            return _juez_ollama, f"ollama:{modelo_juez()}"
        if preferencia == "ollama":
            print(f"  ⚠ juez ollama no disponible: {motivo}")
            return _juez_keyword, "keyword(aprox)"
    if preferencia in ("auto", "claude") and os.environ.get("ANTHROPIC_API_KEY"):
        return _juez_claude, "claude"
    return _juez_keyword, "keyword(aprox)"


def evaluar(k: int, preferencia_juez: str, multiconsulta: bool = False) -> int:
    from app.config import obtener_config
    from app.rag.retriever import recuperar, recuperar_multi

    cfg = obtener_config()
    casos = cargar_casos()
    juez, etiqueta_juez = elegir_juez(preferencia_juez)

    relevancias_por_caso: list[list[bool]] = []
    for caso in casos:
        especie = caso.get("paciente", {}).get("especie")
        if multiconsulta:
            frags = recuperar_multi(construir_queries_eval(caso), especie=especie, top_k=k)
        else:
            frags = recuperar(construir_query_eval(caso), especie=especie, top_k=k)
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
          f"multiconsulta={multiconsulta} max_por_libro={cfg.rag_max_por_libro} "
          f"score_minimo={cfg.rag_score_minimo} juez={etiqueta_juez}")
    print(json.dumps(met, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval de recuperación RAG (A/B de configs)")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--etiqueta", default="", help="etiqueta informativa de la config")
    parser.add_argument(
        "--juez", choices=["auto", "cli", "ollama", "claude", "keyword"], default="auto",
        help="auto: CLI de Claude Code → Ollama local → SDK de Claude → keyword",
    )
    parser.add_argument("--keyword", action="store_true", help="atajo de --juez keyword")
    parser.add_argument(
        "--multiconsulta", action="store_true",
        help="descompone el caso en una consulta por entidad y fusiona con RRF (A/B del "
             "comportamiento de producción, controlado por MORPHOS_RAG_MULTICONSULTA)",
    )
    args = parser.parse_args()
    if args.etiqueta:
        print(f"# config: {args.etiqueta}")
    sys.exit(evaluar(args.k, "keyword" if args.keyword else args.juez, args.multiconsulta))


if __name__ == "__main__":
    main()
