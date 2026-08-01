"""Recupera, para cada entidad de alteraciones.json, los fragmentos del corpus que deberían
sostener (o desmentir) lo que afirma su descripción."""
import json
import sys
from pathlib import Path

RAIZ = Path("/Users/josesalazar/morphos_rev/morphos")
sys.path.insert(0, str(RAIZ / "backend"))
from app.rag.retriever import recuperar  # noqa: E402

alt = json.loads((RAIZ / "data/alteraciones.json").read_text(encoding="utf-8"))
claves = sys.argv[1:]
LARGO = int(__import__("os").environ.get("LARGO", "560"))

for clave in claves:
    e = alt[clave]
    desc = e["descripcion"] if isinstance(e["descripcion"], str) else " ".join(e["descripcion"].values())
    print("=" * 108)
    print(f"[{clave}] {e['nombre']}")
    print(f"DICE: {desc[:700]}")
    consulta = f"{e['nombre']} {desc[:220]}"
    for f in recuperar(consulta, top_k=2):
        print(f"\n  --- {f.cita()} ({f.score:.2f})")
        print("  " + f.texto[:LARGO].strip().replace("\n", " "))
    print()
