"""Aplica `data/rag_alcance.json` a un índice RAG ya construido, sin reingerir.

Dos pasadas, las mismas que hace la ingesta:

1. **Descartar** índices alfabéticos, sumarios y preliminares.
2. **Reetiquetar** `especie` en las secciones que no son de perro ni gato.

Reingerir cuesta OCR sobre cientos de MB de PDF; esto sólo toca metadatos y filas, deja los
vectores calculados intactos y corre en segundos. Ver `app/rag/alcance_corpus.py` para por qué
hace falta (el filtro de especie estaba inerte: todos los chunks con `especie` vacía).

    uv run --group rag python ../scripts/curar_indice.py            # simulacro, no escribe
    uv run --group rag python ../scripts/curar_indice.py --aplicar  # escribe

Tras aplicarlo hay que republicar el índice (`make publish-index`) para que las builds y las
demás máquinas se lo lleven; si no, sólo queda arreglado en local.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

from app.config import obtener_config  # noqa: E402
from app.rag.alcance_corpus import (  # noqa: E402
    cargar_descartes,
    cargar_rangos,
    debe_descartarse,
    especie_de,
)


def actualizar_manifiesto(ruta: Path, n_fragmentos: int) -> None:
    """Deja `manifest.json` de acuerdo con lo que hay realmente en la tabla."""
    destino = ruta / "manifest.json"
    if not destino.exists():
        print("⚠ Sin manifest.json: no se puede dejar constancia del recuento.")
        return
    datos = json.loads(destino.read_text(encoding="utf-8"))
    antes = datos.get("n_fragmentos")
    datos["n_fragmentos"] = n_fragmentos
    datos["curado"] = "data/rag_alcance.json"
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest.json actualizado: n_fragmentos {antes} → {n_fragmentos}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--aplicar", action="store_true",
        help="escribe los cambios; sin esta bandera sólo informa de qué haría",
    )
    parser.add_argument("--indice", type=Path, help="ruta del índice (por defecto, la de config)")
    args = parser.parse_args()

    import lancedb

    cfg = obtener_config()
    ruta = args.indice or cfg.rag_index_dir
    if not ruta.exists():
        print(f"❌ No hay índice en {ruta}. Usa `make fetch-index`.")
        return 1

    descartes, rangos = cargar_descartes(), cargar_rangos()
    if not descartes and not rangos:
        print("❌ data/rag_alcance.json no declara nada: no habría qué hacer.")
        return 1

    print(f"Índice: {ruta}")
    print(f"\nDescartes ({len(descartes)}):")
    for d in descartes:
        print(f"  · {d.libro_empieza_por[:42]}… pp. {d.desde}–{d.hasta}  ({d.motivo[:58]})")
    print(f"Rangos de especie ({len(rangos)}):")
    for r in rangos:
        print(f"  · {r.libro_empieza_por[:42]}… pp. {r.desde}–{r.hasta} → {r.especie}")

    db = lancedb.connect(str(ruta))
    tabla = db.open_table("literatura")
    df = tabla.to_pandas()
    total = len(df)

    fuera = df.apply(lambda f: debe_descartarse(f["libro"], f["pagina"], f["texto"]), axis=1)
    df_quedan = df[~fuera].copy()
    nueva = [especie_de(f.libro, f.pagina, "") for f in df_quedan.itertuples()]
    reetiquetados = sum(
        1 for antes, ahora in zip(df_quedan["especie"], nueva, strict=True) if antes != ahora
    )

    print(f"\nchunks: {total}")
    print(f"  a descartar (índices/sumarios/prelim.): {int(fuera.sum())}")
    print(f"  quedan:                                 {len(df_quedan)}")
    print(f"  cambian de especie:                     {reetiquetados}")
    print(f"  especies tras curar:                    {dict(Counter(nueva))}")

    manifiesto = ruta / "manifest.json"
    if manifiesto.exists():
        declarado = json.loads(manifiesto.read_text(encoding="utf-8")).get("n_fragmentos")
        if declarado != len(df_quedan):
            print(f"\n⚠ manifest.json declara {declarado} fragmentos y quedarían {len(df_quedan)}.")

    if not fuera.any() and not reetiquetados:
        if manifiesto.exists() and declarado != len(df_quedan):
            if not args.aplicar:
                print("Repite con --aplicar para corregir sólo el manifiesto.")
                return 0
            actualizar_manifiesto(ruta, len(df_quedan))
            return 0
        print("\nNada que hacer.")
        return 0
    if not args.aplicar:
        print("\nSimulacro. Repite con --aplicar para escribir.")
        return 0

    # Se reescribe la tabla entera desde el DataFrame: `mode='overwrite'` conserva el esquema y
    # los vectores ya calculados, que es justo lo que no queremos recomputar. El índice FTS sí
    # se reconstruye después, porque la sobrescritura lo invalida.
    df_quedan["especie"] = nueva
    db.create_table("literatura", data=df_quedan, mode="overwrite")
    tabla = db.open_table("literatura")
    try:
        tabla.create_fts_index("texto", replace=True)
        print("Índice FTS reconstruido.")
    except Exception as exc:  # noqa: BLE001 - informativo; el denso sigue sirviendo
        print(f"⚠ No se pudo reconstruir el FTS ({exc}). Reconstrúyelo antes de confiar en el híbrido.")

    # Compactar no es cosmético: LanceDB versiona, así que sobrescribir DEJA los datos viejos en
    # disco y el índice CRECE al quitarle filas (medido: 73 MB → 140 MB). Como este artefacto se
    # sube al Hub y se hornea en la imagen, publicarlo sin compactar multiplicaría su tamaño.
    import datetime

    tabla.optimize(cleanup_older_than=datetime.timedelta(0), delete_unverified=True)
    tamano = sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1e6
    print(f"Versiones antiguas purgadas. Tamaño en disco: {tamano:.0f} MB")

    # El manifiesto lo escribe la ingesta y aquí acaba de cambiar el número de fragmentos. Si no
    # se actualiza, miente: `fetch-index` lo imprime y `publish-index` lo usa como mensaje de
    # commit, así que el Hub anunciaría un recuento que no es el del índice que sirve.
    actualizar_manifiesto(ruta, len(df_quedan))

    print(f"\n✅ {total} → {len(df_quedan)} fragmentos. Recuerda `make publish-index`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
