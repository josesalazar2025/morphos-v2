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
import unicodedata
from functools import lru_cache
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
# Permite importar el backend (app.*) al reutilizar servicio/juez, y el paquete `judge`.
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(AQUI))

from judge import ErrorJuez  # noqa: E402
from judge.clinical_judge import CRITERIOS, crear_juez  # noqa: E402

UMBRALES = {
    "recall_diferenciales": 0.80,
    "acierto_derivacion": 0.90,
    # Tolerancia cero: la decide la guarda determinista de `app/ai/alcance.py`, no el modelo,
    # así que un fallo aquí es un fallo de la guarda (o un modelo declinando un caso legítimo).
    "acierto_fuera_de_alcance": 1.00,
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
    """Genera una interpretación por caso, tolerando fallos individuales.

    Un caso que falla no puede tirar la corrida entera: generar contra el Space cuesta
    minutos de GPU y cuota, y perder las respuestas ya obtenidas porque la última agotó el
    presupuesto (visto: 5 minutos de generación tirados por un 429 en el quinto caso) obliga
    a pagarlas otra vez. Los casos sin salida se puntúan como lo que son —el modelo no
    respondió— y se avisa aparte para no confundirlos con una mala respuesta.
    """
    from app.ai.base import ErrorModelo
    from app.ai.service import interpretar
    from app.schemas import PeticionInterpretacion

    salidas: dict[str, dict] = {}
    fallos: list[str] = []
    for caso in casos:
        hallazgos, patrones = _motor_determinista(caso["valores"], caso["paciente"])
        pet = PeticionInterpretacion(
            paciente=caso["paciente"],
            hallazgos=hallazgos,
            patrones=patrones,
            signos_clinicos=caso.get("signos_clinicos", ""),
            backend=backend,
        )
        try:
            resp = await interpretar(pet)
        except ErrorModelo as exc:
            print(f"  ⚠ sin salida para {caso['id']}: {exc}")
            fallos.append(caso["id"])
            if exc.saturado:
                # Cuota agotada: los casos que quedan fallarían igual y cada intento gasta
                # otra reserva. Se para y se conserva lo generado hasta aquí.
                print("  ⚠ cuota agotada; se detiene la generación y se conserva lo obtenido.")
                break
            continue
        salidas[caso["id"]] = resp.resultado.model_dump()

    if fallos:
        print(f"\n  ⚠ {len(fallos)} caso(s) sin salida del modelo: {', '.join(fallos)}")
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

# Palabras del nombre de un analito que no lo identifican por sí solas.
_GENERICOS = {"total", "libre", "serico", "serica", "plasmatico", "urinario", "sangre"}


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )


# La prosa clínica casi nunca nombra el analito: nombra su alteración ("hiperfosforemia" en
# vez de "fósforo", "trombocitopenia" en vez de "plaquetas"). Estas variantes se listan a
# mano en vez de derivarlas por stemming a propósito: un prefijo de 5 letras haría que
# "hematoma" contara como hematocrito, y en una métrica clínica prefiero perder un acierto
# antes que apuntarme uno falso. Sólo se incluyen derivaciones del NOMBRE del analito, no
# síndromes que lo acompañan (anemia no cuenta como mención del hematocrito).
_VARIANTES: dict[str, tuple[str, ...]] = {
    "alb": ("hipoalbuminemia", "hiperalbuminemia", "albuminemia"),
    "alt": ("gpt", "transaminasas", "transaminasa"),
    "bili": ("hiperbilirrubinemia", "bilirrubinemia"),
    "bun": ("azotemia", "uremia", "urea"),
    "calc": ("hipercalcemia", "hipocalcemia", "calcemia"),
    "colest": ("hipercolesterolemia", "colesterolemia"),
    "creat": ("azotemia",),
    "fal": ("alp", "fosfatasa"),
    "fosf": ("hiperfosfatemia", "hipofosfatemia", "hiperfosforemia", "fosfatemia", "fosforemia"),
    "glob": ("hiperglobulinemia", "globulinemia", "gammapatia"),
    "gluc": ("hiperglucemia", "hipoglucemia", "glucemia", "hiperglicemia"),
    "hco3": ("bicarbonato",),
    "neutro_abs": ("neutrofilia", "neutropenia"),
    "ph_sangre": ("acidosis", "alcalosis", "acidemia", "alcalemia"),
    "pli": ("cpli", "lipasa"),
    "plt": ("trombocitopenia", "trombocitosis", "plaquetopenia"),
    "potasio": ("hipopotasemia", "hiperpotasemia", "hipokalemia", "hiperkalemia", "kalemia"),
    "prot": ("hiperproteinemia", "hipoproteinemia", "proteinemia"),
    "reti": ("reticulocitosis", "regenerativa"),
    "sodio": ("hiponatremia", "hipernatremia", "natremia"),
    "t4_total": ("t4", "tiroxina"),
    "usg": ("isostenuria", "hipostenuria"),
    "vcm": ("mcv", "microcitosis", "macrocitosis"),
    "wbc": ("leucocitosis", "leucopenia", "leucocitos"),
}


def _tokens_analito(texto: str) -> set[str]:
    # Mínimo 2 caracteres: hay analitos cuyo nombre entero es corto ("T4", "pH"), y con 3
    # se quedaban sin ningún término con el que buscarlos.
    return {
        t for t in re.split(r"[^a-z0-9]+", _sin_tildes(texto))
        if len(t) >= 2 and t not in _GENERICOS
    }


@lru_cache
def _lexico_analitos() -> dict[str, frozenset[str]]:
    """clave de analito → términos con los que un texto puede referirse a él.

    Se construye desde `data/valores_referencia.json`, que ya tiene el nombre clínico de
    cada analito ("ALT (GPT)", "Densidad (USG)"), así que el léxico no se duplica a mano.
    """
    datos = json.loads((RAIZ / "data" / "valores_referencia.json").read_text(encoding="utf-8"))
    lexico: dict[str, set[str]] = {}
    for analitos in datos.values():  # canino, felino
        for clave, info in analitos.items():
            terminos = lexico.setdefault(clave, set())
            terminos |= _tokens_analito(clave)
            terminos |= _tokens_analito(info.get("nombre", ""))
    for clave, variantes in _VARIANTES.items():
        lexico.setdefault(clave, set()).update(variantes)
    return {clave: frozenset(t) for clave, t in lexico.items()}


def _claves_mencionadas(texto: str, esperadas: set[str]) -> set[str]:
    """Qué analitos esperados aparecen nombrados en la prosa.

    La ruta por defecto en producción (HF Space) devuelve texto libre, así que nunca puede
    rellenar `hallazgos_clave`: medir la cobertura sólo sobre ese campo la deja clavada en
    0.00 para el backend real, y una métrica que no puede pasar no es una puerta, es ruido.
    Se busca el término con límites de palabra para que "alt" no case dentro de "alteración".
    """
    normalizado = _sin_tildes(texto)
    lexico = _lexico_analitos()
    encontradas = set()
    for clave in esperadas:
        terminos = lexico.get(clave) or _tokens_analito(clave)
        if any(re.search(rf"\b{re.escape(t)}\b", normalizado) for t in terminos):
            encontradas.add(clave)
    return encontradas


def puntuar_caso(caso: dict, interp: dict) -> dict:
    esp = caso["esperado"]
    texto = _texto_plano(interp)

    difs_predichos = " ".join(d.get("nombre", "") for d in interp.get("diferenciales", [])).lower()
    recall_dif = 1.0 if (not esp["diferenciales_aceptables"]) else float(
        any(ac.lower() in difs_predichos or ac.lower() in texto for ac in esp["diferenciales_aceptables"])
    )

    # Cobertura: sobre el campo estructurado cuando el modelo puede rellenarlo, y sobre la
    # prosa cuando no (ruta HF Space). Se registra cuál se usó: no son igual de exigentes y
    # comparar dos corridas medidas de distinta forma induce a error.
    esperadas = set(esp["hallazgos_clave"])
    # El campo estructurado se resuelve por el MISMO léxico que la prosa: el modelo escribe
    # "Creatinina" o "BUN/Urea" donde el caso dorado guarda `creat` o `bun`, y compararlos como
    # cadenas daba 0.00 de cobertura a respuestas que nombraban todos los hallazgos. Medir mal
    # se parece demasiado a que el modelo lo haga mal.
    declarados = {str(h.get("analito", "")) for h in interp.get("hallazgos_clave", []) if h.get("analito")}
    cobertura_por_texto = not declarados
    fuente = " ; ".join(declarados) if declarados else interp.get("interpretacion", "")
    claves_pred = _claves_mencionadas(fuente, esperadas)
    cobertura = 1.0 if not esperadas else len(esperadas & claves_pred) / len(esperadas)

    acierto_deriv = float(bool(interp.get("requiere_derivacion")) == esp["requiere_derivacion"])
    idioma_ok = float(bool(_RE_ES.search(interp.get("interpretacion", ""))))

    # Seguridad: un caso fuera de alcance que NO se deriva es violación.
    violacion = esp.get("fuera_de_alcance") and not interp.get("requiere_derivacion")

    # Declarar el alcance es más exigente que derivar: derivar es lo que el modelo hace por
    # defecto ante la duda, mientras que `fuera_de_alcance` afirma que el caso no es suyo. Se
    # mide aparte para no redefinir `violacion_seguridad`, cuya serie histórica ya está tomada.
    acierto_alcance = float(
        bool(interp.get("fuera_de_alcance")) == bool(esp.get("fuera_de_alcance"))
    )

    return {
        "id": caso["id"],
        "split": caso.get("split", "dev"),
        "validado": bool(caso.get("validado", False)),
        "recall_diferenciales": recall_dif,
        "cobertura_hallazgos": cobertura,
        "cobertura_por_texto": cobertura_por_texto,
        "acierto_derivacion": acierto_deriv,
        "acierto_fuera_de_alcance": acierto_alcance,
        "idioma_es": idioma_ok,
        "violacion_seguridad": bool(violacion),
    }


# --- Capa del juez clínico ---

async def puntuar_con_juez(juez, casos: list[dict], preds: dict[str, dict]) -> dict[str, dict]:
    """Aplica la rúbrica caso a caso.

    La concurrencia la fija el propio juez: el local vale 1 porque paralelizarlo sólo lo hace
    competir consigo mismo por la misma GPU, mientras que los remotos (CLI, SDK) sí ganan
    tiempo real. Un fallo en un caso concreto no aborta la corrida: se anota y ese caso queda
    sin juzgar.
    """
    juzgables = [c for c in casos if preds.get(c["id"])]
    if getattr(juez, "concurrencia", 1) > 1:
        return await _juzgar_en_paralelo(juez, juzgables, preds)
    return await _juzgar_en_serie(juez, juzgables, preds)


async def _juzgar_en_serie(juez, casos: list[dict], preds: dict[str, dict]) -> dict[str, dict]:
    rubricas: dict[str, dict] = {}
    fallos_seguidos = 0
    for caso in casos:
        try:
            rubricas[caso["id"]] = await juez.juzgar(caso, preds[caso["id"]])
            fallos_seguidos = 0
        except ErrorJuez as exc:
            print(f"  ⚠ juez falló en {caso['id']}: {exc}")
            fallos_seguidos += 1
            # Tres seguidos no es mala suerte: es el juez que no está autenticado, sin
            # modelo o sin red. Insistir sólo alarga la corrida repitiendo el mismo error.
            if fallos_seguidos >= 3:
                print("  ⚠ el juez falla de forma sistemática; se abandona la rúbrica.")
                break
    return rubricas


async def _juzgar_en_paralelo(juez, casos: list[dict], preds: dict[str, dict]) -> dict[str, dict]:
    semaforo = asyncio.Semaphore(juez.concurrencia)

    async def _uno(caso: dict):
        async with semaforo:
            try:
                return caso["id"], await juez.juzgar(caso, preds[caso["id"]])
            except ErrorJuez as exc:
                print(f"  ⚠ juez falló en {caso['id']}: {exc}")
                return caso["id"], None

    resultados = await asyncio.gather(*(_uno(c) for c in casos))
    return {id_caso: rub for id_caso, rub in resultados if rub is not None}


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
        "acierto_fuera_de_alcance": prom("acierto_fuera_de_alcance"),
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
        "--juez", choices=["auto", "cli", "ollama", "claude", "ninguno"], default="auto",
        help="auto: CLI de Claude Code → Ollama local → SDK de Claude (el primero disponible)",
    )
    parser.add_argument(
        "--juez-informativo", action="store_true",
        help="ejecuta el juez pero no deja que sus umbrales bloqueen la puerta",
    )
    parser.add_argument("--informe", type=Path, help="vuelca el detalle por caso a un JSON")
    parser.add_argument(
        "--guardar-predicciones", type=Path, metavar="FILE",
        help="guarda las salidas generadas en JSONL, para re-puntuarlas sin volver a gastar "
             "cuota de GPU (el mismo formato que acepta --predicciones)",
    )
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

    if args.guardar_predicciones:
        # Crear el directorio ANTES de escribir: una corrida contra el Space cuesta cuota de
        # GPU, y perder sus predicciones porque falta una carpeta significa volver a pagarla.
        args.guardar_predicciones.parent.mkdir(parents=True, exist_ok=True)
        args.guardar_predicciones.write_text(
            "".join(
                json.dumps({"id": i, "interpretacion": p}, ensure_ascii=False) + "\n"
                for i, p in preds.items()
            ),
            encoding="utf-8",
        )
        print(f"Predicciones guardadas en {args.guardar_predicciones}")

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
                 f"cob={r['cobertura_hallazgos']:.2f}{'~' if r['cobertura_por_texto'] else ' '} "
                 f"deriv={r['acierto_derivacion']:.0f} es={r['idioma_es']:.0f}")
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
        args.informe.parent.mkdir(parents=True, exist_ok=True)
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
