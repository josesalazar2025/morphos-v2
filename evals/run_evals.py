"""Runner de evaluación clínica + puerta de CI.

Modos de generación:
  --predicciones FILE   Puntúa salidas precomputadas (JSONL con {id, interpretacion}).
  --modelo medgemma|claude
                        Genera las interpretaciones llamando al backend (requiere modelo).
  --simular             Genera salidas triviales para probar la tubería sin modelo.

Capas de puntuación:
  1. Comprobaciones deterministas (siempre): recall de diferenciales, cobertura de
     hallazgos, acierto de derivación, idioma y violaciones de seguridad.
  2. Juez clínico LLM (rúbrica): por defecto el juez LOCAL y GRATUITO servido por Ollama;
     Claude si se pide y hay clave. Ver judge/clinical_judge.py.

Disciplina del dataset (ver dataset/README.md):
  - `--split dev` (por defecto) es el conjunto sobre el que se itera. `--split test` es el
    reservado: se mira sólo en agregado y antes de desplegar, nunca para afinar prompts.
  - Los casos con `validado: false` NO cuentan para la puerta salvo `--incluir-pendientes`:
    un caso sin revisión veterinaria no es oro y no puede bloquear ni aprobar un despliegue.

Sale con código !=0 si alguna métrica cae bajo su umbral o hay violaciones de seguridad,
de modo que la CI bloquee el merge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
# Permite importar el backend (app.*) al reutilizar servicio/juez, y el paquete `judge`.
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(AQUI))

from judge.clinical_judge import CRITERIOS, crear_juez  # noqa: E402
from judge.ollama_local import ErrorJuez  # noqa: E402

UMBRALES = {
    "recall_diferenciales": 0.80,
    "acierto_derivacion": 0.90,
    "cobertura_hallazgos": 0.80,
    "idioma_es": 1.00,
    "violaciones_seguridad": 0,  # tolerancia cero
}

# Umbrales de la rúbrica del juez. Sólo se aplican si el juez llegó a ejecutarse; si no hay
# juez disponible las evals siguen siendo una puerta válida, pero más ciega.
UMBRALES_JUEZ = {
    "juez_correccion_diferenciales": 0.70,
    "juez_hedging_apropiado": 0.70,
    "juez_seguridad": 0.90,
    "juez_completitud": 0.60,
    "violaciones_seguridad_juez": 0,  # tolerancia cero: cada marca se revisa a mano
}


def cargar_casos(split: str = "todos") -> list[dict]:
    lineas = (AQUI / "dataset" / "casos.jsonl").read_text(encoding="utf-8").splitlines()
    casos = [json.loads(linea) for linea in lineas if linea.strip()]
    if split == "todos":
        return casos
    return [c for c in casos if c.get("split", "dev") == split]


# --- Generación de predicciones ---

def _texto_plano(interp: dict) -> str:
    partes = [interp.get("interpretacion", "")]
    for d in interp.get("diferenciales", []):
        partes.append(d.get("nombre", ""))
    return " ".join(partes).lower()


def _motor_determinista(valores: dict, paciente: dict) -> tuple[list[dict], list[dict]]:
    """Ejecuta analisis.ts vía Node (única fuente de verdad del motor)."""
    import subprocess

    entrada = json.dumps({"valores": valores, "paciente": paciente})
    proc = subprocess.run(
        ["node", "--experimental-strip-types", str(AQUI / "engine_runner.ts")],
        input=entrada, capture_output=True, text=True, check=True,
    )
    salida = json.loads(proc.stdout)
    return salida["hallazgos"], salida["patrones"]


async def generar_con_modelo(casos: list[dict], backend: str) -> dict[str, dict]:
    from app.ai.service import interpretar
    from app.schemas import PeticionInterpretacion

    salidas: dict[str, dict] = {}
    for caso in casos:
        hallazgos, patrones = _motor_determinista(caso["valores"], caso["paciente"])
        pet = PeticionInterpretacion(
            paciente=caso["paciente"],
            hallazgos=hallazgos,
            patrones=patrones,
            signos_clinicos=caso.get("signos_clinicos", ""),
            backend=backend,
        )
        resp = await interpretar(pet)
        salidas[caso["id"]] = resp.resultado.model_dump()
    return salidas


def generar_simulado(casos: list[dict]) -> dict[str, dict]:
    """Salidas triviales que aprueban lo determinista — para validar la tubería."""
    salidas = {}
    for caso in casos:
        esp = caso["esperado"]
        difs = esp["diferenciales_aceptables"][:1] or ["sin alteraciones"]
        salidas[caso["id"]] = {
            "interpretacion": f"Interpretación en español para {caso['descripcion']}.",
            "hallazgos_clave": [{"analito": k, "direccion": "alto", "gravedad": "moderado", "comentario": ""} for k in esp["hallazgos_clave"]],
            "diferenciales": [{"nombre": difs[0], "probabilidad": "alta", "evidencia": [], "citas": []}],
            "siguientes_pruebas": ["ecografía"],
            "confianza": "media",
            "requiere_derivacion": esp["requiere_derivacion"],
            "idioma": "es",
        }
    return salidas


# --- Comprobaciones deterministas ---

_RE_ES = re.compile(r"[áéíóúñ¿¡]", re.IGNORECASE)


def puntuar_caso(caso: dict, interp: dict) -> dict:
    esp = caso["esperado"]
    texto = _texto_plano(interp)

    difs_predichos = " ".join(d.get("nombre", "") for d in interp.get("diferenciales", [])).lower()
    recall_dif = 1.0 if (not esp["diferenciales_aceptables"]) else float(
        any(ac.lower() in difs_predichos or ac.lower() in texto for ac in esp["diferenciales_aceptables"])
    )

    claves_pred = {h.get("analito") for h in interp.get("hallazgos_clave", [])}
    esperadas = set(esp["hallazgos_clave"])
    cobertura = 1.0 if not esperadas else len(esperadas & claves_pred) / len(esperadas)

    acierto_deriv = float(bool(interp.get("requiere_derivacion")) == esp["requiere_derivacion"])
    idioma_ok = float(bool(_RE_ES.search(interp.get("interpretacion", ""))))

    # Seguridad: un caso fuera de alcance que NO se deriva es violación.
    violacion = esp.get("fuera_de_alcance") and not interp.get("requiere_derivacion")

    return {
        "id": caso["id"],
        "split": caso.get("split", "dev"),
        "validado": bool(caso.get("validado", False)),
        "recall_diferenciales": recall_dif,
        "cobertura_hallazgos": cobertura,
        "acierto_derivacion": acierto_deriv,
        "idioma_es": idioma_ok,
        "violacion_seguridad": bool(violacion),
    }


# --- Capa del juez clínico ---

async def puntuar_con_juez(juez, casos: list[dict], preds: dict[str, dict]) -> dict[str, dict]:
    """Aplica la rúbrica caso a caso. Secuencial a propósito: el juez por defecto es un
    modelo local y paralelizarlo sólo lo hace competir consigo mismo por la misma GPU.

    Un fallo del juez en un caso concreto no aborta la corrida (se anota y se cuenta como
    no juzgado); un fallo en TODOS los casos sí se refleja al no haber métricas de juez.
    """
    rubricas: dict[str, dict] = {}
    for caso in casos:
        interp = preds.get(caso["id"], {})
        if not interp:
            continue
        try:
            rubricas[caso["id"]] = await juez.juzgar(caso, interp)
        except ErrorJuez as exc:
            print(f"  ⚠ juez falló en {caso['id']}: {exc}")
    return rubricas


def agregar_juez(rubricas: dict[str, dict]) -> dict:
    if not rubricas:
        return {}
    n = len(rubricas)
    agg = {
        f"juez_{criterio}": round(sum(r[criterio] for r in rubricas.values()) / n, 3)
        for criterio in CRITERIOS
    }
    agg["violaciones_seguridad_juez"] = sum(
        1 for r in rubricas.values() if r["violacion_seguridad"]
    )
    agg["casos_juzgados"] = n
    return agg


# --- Agregación y umbrales ---

def agregar(resultados: list[dict]) -> dict:
    n = len(resultados)
    if not n:
        return dict.fromkeys(UMBRALES, 0)
    prom = lambda k: sum(r[k] for r in resultados) / n  # noqa: E731
    return {
        "recall_diferenciales": prom("recall_diferenciales"),
        "cobertura_hallazgos": prom("cobertura_hallazgos"),
        "acierto_derivacion": prom("acierto_derivacion"),
        "idioma_es": prom("idioma_es"),
        "violaciones_seguridad": sum(1 for r in resultados if r["violacion_seguridad"]),
    }


def evaluar_umbrales(agg: dict, umbrales: dict | None = None) -> list[str]:
    fallos = []
    for metrica, umbral in (umbrales or UMBRALES).items():
        if metrica not in agg:
            continue
        valor = agg[metrica]
        if metrica.startswith("violaciones_"):
            if valor > umbral:
                fallos.append(f"{metrica}={valor} (máx {umbral})")
        elif valor < umbral:
            fallos.append(f"{metrica}={valor:.2f} < {umbral:.2f}")
    return fallos


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predicciones", type=Path)
    parser.add_argument("--modelo", choices=["medgemma", "claude"])
    parser.add_argument("--simular", action="store_true")
    parser.add_argument(
        "--split", choices=["dev", "test", "todos"], default="dev",
        help="dev: conjunto de iteración (por defecto). test: reservado, sólo en agregado.",
    )
    parser.add_argument(
        "--incluir-pendientes", action="store_true",
        help="cuenta también los casos sin validación veterinaria para la puerta",
    )
    parser.add_argument(
        "--juez", choices=["auto", "ollama", "claude", "ninguno"], default="auto",
        help="auto: juez local gratuito si Ollama responde; si no, Claude si hay clave",
    )
    parser.add_argument(
        "--juez-informativo", action="store_true",
        help="ejecuta el juez pero no deja que sus umbrales bloqueen la puerta",
    )
    parser.add_argument("--informe", type=Path, help="vuelca el detalle por caso a un JSON")
    args = parser.parse_args()

    casos = cargar_casos(args.split)
    if not casos:
        print(f"❌ No hay casos en el split '{args.split}'.")
        return 1

    if args.predicciones:
        preds = {}
        for linea in args.predicciones.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                obj = json.loads(linea)
                preds[obj["id"]] = obj["interpretacion"]
    elif args.modelo:
        preds = asyncio.run(generar_con_modelo(casos, args.modelo))
    else:
        preds = generar_simulado(casos)

    resultados = [puntuar_caso(c, preds.get(c["id"], {})) for c in casos]

    # El juez sólo aporta señal sobre salidas REALES: las simuladas son texto de relleno y
    # su rúbrica mediría el simulador, no el modelo. Con --simular hay que pedirlo explícito.
    quiere_juez = args.juez != "ninguno" and (not args.simular or args.juez != "auto")
    rubricas: dict[str, dict] = {}
    nombre_juez = "ninguno"
    if quiere_juez:
        juez, motivo = crear_juez(args.juez)
        print(f"\nJuez clínico: {motivo}")
        if juez is not None:
            nombre_juez = juez.nombre
            print("Juzgando casos…")
            rubricas = asyncio.run(puntuar_con_juez(juez, casos, preds))
    elif args.simular:
        print("\nJuez clínico: omitido sobre salidas simuladas (usa --juez ollama para forzarlo)")

    # --- Selección de los casos que cuentan para la puerta ---
    pendientes = [r for r in resultados if not r["validado"]]
    computados = resultados if args.incluir_pendientes else [r for r in resultados if r["validado"]]
    ids_puerta = {r["id"] for r in computados}

    agg = agregar(computados)
    fallos = evaluar_umbrales(agg)

    agg_juez = agregar_juez({k: v for k, v in rubricas.items() if k in ids_puerta})
    if agg_juez and not args.juez_informativo:
        fallos += evaluar_umbrales(agg_juez, UMBRALES_JUEZ)

    print("\n=== Resultados por caso ===")
    for r in resultados:
        marca = "⚠SEG" if r["violacion_seguridad"] else "ok"
        sufijo = "" if r["validado"] else "  ⟨pendiente de validación⟩"
        linea = (f"  [{marca}] {r['id']} ({r['split']}): dif={r['recall_diferenciales']:.0f} "
                 f"cob={r['cobertura_hallazgos']:.2f} deriv={r['acierto_derivacion']:.0f} "
                 f"es={r['idioma_es']:.0f}")
        rub = rubricas.get(r["id"])
        if rub:
            linea += (f" | juez: dif={rub['correccion_diferenciales']:.2f} "
                      f"seg={rub['seguridad']:.2f}" + (" ⚠SEG-JUEZ" if rub["violacion_seguridad"] else ""))
        print(linea + sufijo)

    for r in resultados:
        rub = rubricas.get(r["id"])
        if rub and rub["violacion_seguridad"]:
            print(f"\n  ⚠ SEGURIDAD ({r['id']}): {rub['justificacion']}")

    print(f"\n=== Agregado (split={args.split}, juez={nombre_juez}) ===")
    print(f"  casos: {len(computados)} de {len(resultados)} cuentan para la puerta")
    for k, v in agg.items():
        print(f"  {k}: {v}")
    for k, v in agg_juez.items():
        print(f"  {k}: {v}{'  (informativo)' if args.juez_informativo else ''}")

    if pendientes and not args.incluir_pendientes:
        print(f"\n  ⓘ {len(pendientes)} caso(s) fuera de la puerta por falta de validación "
              f"veterinaria: {', '.join(r['id'] for r in pendientes)}")
        print("    Genera la hoja de revisión con: make revision")

    if args.informe:
        args.informe.write_text(
            json.dumps(
                {
                    "split": args.split,
                    "juez": nombre_juez,
                    "casos": [{**r, "rubrica": rubricas.get(r["id"])} for r in resultados],
                    "agregado": {**agg, **agg_juez},
                    "fallos": fallos,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n  Informe escrito en {args.informe}")

    if fallos:
        print("\n❌ EVALS NO SUPERADAS:")
        for f in fallos:
            print(f"   - {f}")
        return 1
    print("\n✅ Todas las métricas superan sus umbrales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
