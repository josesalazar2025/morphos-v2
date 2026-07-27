"""Circuito de revisión veterinaria del dataset dorado (human-in-the-loop).

Un caso sin firma profesional no es oro: `run_evals.py` lo deja fuera de la puerta. Este
script es el puente entre ese estado y el veterinario que puede resolverlo.

    python revision.py                      # hoja de revisión de los casos pendientes
    python revision.py --validar id1 id2 --revisor "Dra. Pérez"   # firma los casos
    python revision.py --estado             # recuento por split y validación

La hoja incluye, por caso, lo que el veterinario necesita para decidir sin abrir el JSONL:
señalamiento, valores fuera de rango según el motor determinista, signos y los
diferenciales aceptables propuestos. Se escribe en dataset/revision_pendiente.md, que NO
se comitea: es un documento de trabajo (ver .gitignore).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CASOS = AQUI / "dataset" / "casos.jsonl"
HOJA = AQUI / "dataset" / "revision_pendiente.md"


def cargar() -> list[dict]:
    lineas = CASOS.read_text(encoding="utf-8").splitlines()
    return [json.loads(linea) for linea in lineas if linea.strip()]


def guardar(casos: list[dict]) -> None:
    CASOS.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in casos), encoding="utf-8"
    )


def _hallazgos_del_motor(caso: dict) -> list[dict]:
    """Pasa el caso por analisis.ts para mostrar QUÉ marca el motor, no lo que dice el JSONL.
    Si Node no está disponible, la hoja se genera igual sin esta sección."""
    try:
        proc = subprocess.run(
            ["node", "--experimental-strip-types", str(AQUI / "engine_runner.ts")],
            input=json.dumps({"valores": caso["valores"], "paciente": caso["paciente"]}),
            capture_output=True, text=True, check=True,
        )
        return json.loads(proc.stdout)["hallazgos"]
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return []


def generar_hoja(casos: list[dict]) -> str:
    pendientes = [c for c in casos if not c.get("validado")]
    lineas = [
        "# Hoja de revisión veterinaria — dataset dorado de Morphos",
        "",
        f"Generada el {dt.date.today().isoformat()}. {len(pendientes)} caso(s) pendientes de "
        f"{len(casos)}.",
        "",
        "Para cada caso, confirma o corrige los **diferenciales aceptables** y si el caso debe "
        "marcar derivación. Cuando un caso quede conforme, fírmalo con:",
        "",
        "```bash",
        "python evals/revision.py --validar <id> --revisor \"Tu nombre\"",
        "```",
        "",
        "Mientras un caso siga pendiente NO cuenta para la puerta de evals: no puede aprobar "
        "ni bloquear un despliegue.",
        "",
    ]
    for caso in pendientes:
        p = caso["paciente"]
        esp = caso["esperado"]
        lineas += [
            f"## {caso['id']}  ·  split `{caso.get('split', 'dev')}`",
            "",
            f"**{caso['descripcion']}**",
            "",
            f"- Paciente: {p.get('especie', '?')}, {p.get('raza', 'NE')}, "
            f"{p.get('edad_meses', '?')} meses, {p.get('sexo', 'NE')}",
            f"- Signos clínicos: {caso.get('signos_clinicos') or '—'}",
            f"- Valores: {', '.join(f'{k}={v}' for k, v in caso['valores'].items())}",
        ]
        hallazgos = _hallazgos_del_motor(caso)
        if hallazgos:
            marcados = ", ".join(
                f"{h['clave']} {h['direccion']}/{h['gravedad']}" for h in hallazgos
            )
            lineas.append(f"- Marcados por el motor: {marcados}")
        lineas += [
            f"- Hallazgos clave esperados: {', '.join(esp['hallazgos_clave']) or '—'}",
            "",
            "Diferenciales aceptables propuestos (corrige, añade o elimina):",
            "",
        ]
        lineas += [f"- [ ] {d}" for d in esp["diferenciales_aceptables"]] or ["- [ ] (ninguno)"]
        lineas += [
            "",
            f"- [ ] `requiere_derivacion = {esp['requiere_derivacion']}` es correcto",
            f"- [ ] `fuera_de_alcance = {esp['fuera_de_alcance']}` es correcto",
            "",
        ]
    return "\n".join(lineas)


def estado(casos: list[dict]) -> str:
    def contar(pred) -> int:
        return sum(1 for c in casos if pred(c))

    return "\n".join([
        f"Total: {len(casos)} casos",
        f"  dev:  {contar(lambda c: c.get('split', 'dev') == 'dev')}"
        f"  (validados {contar(lambda c: c.get('split', 'dev') == 'dev' and c.get('validado'))})",
        f"  test: {contar(lambda c: c.get('split') == 'test')}"
        f"  (validados {contar(lambda c: c.get('split') == 'test' and c.get('validado'))})",
        f"  pendientes de validación: {contar(lambda c: not c.get('validado'))}",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Revisión veterinaria del dataset dorado")
    parser.add_argument("--validar", nargs="+", metavar="ID", help="marca casos como validados")
    parser.add_argument("--revisor", default="", help="nombre del veterinario que firma")
    parser.add_argument("--estado", action="store_true", help="sólo muestra el recuento")
    args = parser.parse_args()

    casos = cargar()

    if args.estado:
        print(estado(casos))
        return 0

    if args.validar:
        if not args.revisor:
            print("❌ --revisor es obligatorio: la validación tiene que ser trazable a una persona.")
            return 1
        por_id = {c["id"]: c for c in casos}
        desconocidos = [i for i in args.validar if i not in por_id]
        if desconocidos:
            print(f"❌ Ids inexistentes: {', '.join(desconocidos)}")
            return 1
        hoy = dt.date.today().isoformat()
        for id_caso in args.validar:
            por_id[id_caso].update(validado=True, revisor=args.revisor, fecha_validacion=hoy)
            print(f"✅ {id_caso} validado por {args.revisor} ({hoy})")
        guardar(casos)
        print("\n" + estado(casos))
        return 0

    HOJA.write_text(generar_hoja(casos), encoding="utf-8")
    print(f"Hoja de revisión escrita en {HOJA.relative_to(AQUI.parent)}")
    print(estado(casos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
