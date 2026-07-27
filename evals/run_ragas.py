"""Evaluación RAG con Ragas: ¿la interpretación se sostiene en la literatura recuperada?

Cierra el hueco que ni run_evals.py ni run_retrieval_eval.py cubren:
  - run_evals.py mide si el diagnóstico es correcto.
  - run_retrieval_eval.py mide si la recuperación trae fragmentos relevantes.
  - este script mide la UNIÓN: si lo que el modelo afirma está realmente respaldado por los
    fragmentos que se le dieron (faithfulness) y si el contexto recuperado sirvió para la
    respuesta (context precision/recall).

Todo el juicio corre en LOCAL y GRATIS: LLM y embeddings servidos por Ollama, sin ninguna
clave de API. Requiere el índice RAG construido (`make fetch-index` o `make ingest`).

    cd backend && uv run --group evals python ../evals/run_ragas.py --modelo medgemma
    cd backend && uv run --group evals python ../evals/run_ragas.py --predicciones preds.jsonl

Por defecto es INFORMATIVO: el juez local es pequeño y sus puntuaciones tienen ruido, así
que no bloquea la CI salvo que se pase --puerta explícitamente.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path

# Ragas 0.4 avisa de que los envoltorios de LangChain están deprecados y propone factorías
# atadas a OpenAI. Aquí la ruta LangChain+Ollama es deliberada —es lo que mantiene el juez
# local y gratuito—, así que el aviso es ruido que tapa la salida real.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*(ragas\.metrics|LangchainLLMWrapper|LangchainEmbeddingsWrapper).*",
)

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(AQUI))

from judge.ollama_local import base_url_juez, disponible, modelo_juez  # noqa: E402
from run_evals import _motor_determinista, cargar_casos, generar_con_modelo  # noqa: E402

# Modelo de embeddings del juez. bge-m3 es el mismo que indexa el corpus, así que la
# similitud que calcula Ragas vive en el mismo espacio que la recuperación evaluada.
EMBED_DEFECTO = "bge-m3"

UMBRALES = {
    "faithfulness": 0.70,
    "llm_context_precision_without_reference": 0.60,
    "context_recall": 0.60,
}


def construir_muestras(casos: list[dict], preds: dict[str, dict]) -> list:
    """Una muestra por caso: consulta real de recuperación, contextos realmente recuperados
    y la respuesta del modelo. Se reconstruye con el MISMO código que usa el servicio para
    que la eval mida la tubería de producción, no una aproximación."""
    from ragas.dataset_schema import SingleTurnSample

    from app.rag.retriever import construir_consulta, recuperar

    muestras = []
    for caso in casos:
        interp = preds.get(caso["id"])
        if not interp:
            continue
        hallazgos, patrones = _motor_determinista(caso["valores"], caso["paciente"])
        consulta = construir_consulta(
            [p["nombre"] for p in patrones], [h["nombre"] for h in hallazgos]
        )
        fragmentos = recuperar(consulta, especie=caso["paciente"].get("especie"))
        if not fragmentos:
            print(f"  ⚠ {caso['id']}: 0 fragmentos recuperados; se omite de la eval RAG")
            continue

        # La respuesta incluye los diferenciales: son afirmaciones clínicas y deben estar
        # tan fundamentadas como la prosa.
        partes = [interp.get("interpretacion", "")]
        partes += [
            f"{d.get('nombre', '')}: {'; '.join(d.get('evidencia', []))}"
            for d in interp.get("diferenciales", [])
        ]
        muestras.append(
            SingleTurnSample(
                user_input=consulta,
                response="\n".join(p for p in partes if p),
                retrieved_contexts=[f.texto for f in fragmentos],
                reference="; ".join(caso["esperado"]["diferenciales_aceptables"]) or caso["descripcion"],
            )
        )
    return muestras


def construir_evaluadores(embed_modelo: str):
    """LLM y embeddings locales envueltos para Ragas."""
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    llm = LangchainLLMWrapper(
        ChatOllama(model=modelo_juez(), base_url=base_url_juez(), temperature=0)
    )
    embeddings = LangchainEmbeddingsWrapper(
        OllamaEmbeddings(model=embed_modelo, base_url=base_url_juez())
    )
    return llm, embeddings


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval RAG (Ragas) con juez local gratuito")
    parser.add_argument("--predicciones", type=Path)
    parser.add_argument("--modelo", choices=["medgemma", "claude"])
    parser.add_argument("--split", choices=["dev", "test", "todos"], default="dev")
    parser.add_argument("--embed", default=EMBED_DEFECTO, help=f"modelo de embeddings (def. {EMBED_DEFECTO})")
    # Ragas viene afinado para APIs remotas (16 trabajos en paralelo, 180 s). Contra un
    # Ollama local eso es contraproducente: los trabajos compiten por la misma GPU y todos
    # agotan el tiempo a la vez. Pocos trabajadores y más margen dan resultados, no NaN.
    parser.add_argument("--workers", type=int, default=2, help="trabajos concurrentes (def. 2)")
    parser.add_argument("--timeout", type=int, default=900, help="segundos por trabajo (def. 900)")
    parser.add_argument("--puerta", action="store_true", help="falla si alguna métrica cae bajo su umbral")
    args = parser.parse_args()

    if not args.predicciones and not args.modelo:
        print("❌ Hace falta --predicciones o --modelo: Ragas evalúa respuestas reales.")
        return 1

    ok, motivo = disponible()
    if not ok:
        print(f"❌ El juez local no está disponible: {motivo}")
        return 1

    try:
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithoutReference,
            LLMContextRecall,
        )
        from ragas.run_config import RunConfig
    except ImportError as exc:
        print(f"❌ Falta el grupo de dependencias 'evals' ({exc}).")
        print("   Instálalo con: cd backend && uv sync --group evals")
        return 1

    casos = cargar_casos(args.split)
    if args.predicciones:
        preds = {}
        for linea in args.predicciones.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                obj = json.loads(linea)
                preds[obj["id"]] = obj["interpretacion"]
    else:
        preds = asyncio.run(generar_con_modelo(casos, args.modelo))

    print(f"Construyendo muestras (split={args.split})…")
    muestras = construir_muestras(casos, preds)
    if not muestras:
        print("❌ Ninguna muestra utilizable: ¿está construido el índice RAG?")
        return 1

    llm, embeddings = construir_evaluadores(args.embed)
    print(f"Evaluando {len(muestras)} muestra(s) con {modelo_juez()} + {args.embed}…")
    resultado = evaluate(
        dataset=EvaluationDataset(samples=muestras),
        metrics=[
            Faithfulness(llm=llm),
            LLMContextPrecisionWithoutReference(llm=llm),
            LLMContextRecall(llm=llm),
        ],
        llm=llm,
        embeddings=embeddings,
        run_config=RunConfig(timeout=args.timeout, max_workers=args.workers),
    )

    print("\n=== RESUMEN RAGAS ===")
    print(resultado)

    puntuaciones = getattr(resultado, "_repr_dict", {})
    fallos, incalculables = [], []
    for metrica, umbral in UMBRALES.items():
        valor = puntuaciones.get(metrica)
        if valor is None:
            continue
        # Ragas devuelve NaN cuando el juez agotó el tiempo o no supo puntuar. Eso no es un
        # 0 (no significa "poco fundamentado"): es una métrica que no se midió, y hay que
        # decirlo en vez de dejar pasar la puerta con un agregado incompleto.
        if valor != valor:
            incalculables.append(metrica)
        elif valor < umbral:
            fallos.append(f"{metrica}={valor:.2f} < {umbral:.2f}")

    if incalculables:
        print(f"\n⚠ Métricas sin calcular (el juez no respondió a tiempo): {', '.join(incalculables)}")
        print(f"   Prueba con --timeout mayor que {args.timeout}s o un modelo de juez más rápido.")

    if fallos:
        print("\n" + ("❌ POR DEBAJO DEL UMBRAL:" if args.puerta else "⚠ Por debajo del umbral (informativo):"))
        for f in fallos:
            print(f"   - {f}")
        return 1 if args.puerta else 0
    print("\n✅ Métricas RAG dentro de umbral.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
