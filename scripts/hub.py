"""Publicación y descarga de los artefactos RAG en repos privados del Hub.

Se usa la API de Python (`huggingface_hub`) y no el CLI `hf` a propósito: en la versión instalada
(1.16.1) el CLI arrastra una incompatibilidad typer/click que hace que `ctx.exit()` propague un
`click.exceptions.Exit(0)` como traceback y **devuelva código 1 aunque la operación haya ido
bien**. Eso es inservible dentro de un Makefile, donde un exit≠0 aborta la cadena.

Artefactos:
  - índice  (~70 MB): derivado de libros con licencia, contiene su texto troceado → repo PRIVADO.
  - libros (~226 MB): los PDF originales → repo PRIVADO, sólo necesarios para reingerir.

Uso:
    python scripts/hub.py publish-index
    python scripts/hub.py fetch-index
    python scripts/hub.py publish-books
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

RAIZ = Path(__file__).resolve().parents[1]
DIR_INDICE = RAIZ / "instance" / "rag_index"
DIR_LIBROS = RAIZ / "books"

REPO_INDICE = "blackmistcode/morphos-rag-index"
REPO_LIBROS = "blackmistcode/morphos-books"


def _asegurar_repo(api: HfApi, repo_id: str) -> None:
    """Crea el repo si falta. `private=True` sólo aplica en la creación: si el repo ya existe
    NO lo vuelve privado, así que se comprueba explícitamente y se aborta si es público."""
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    if not api.dataset_info(repo_id).private:
        sys.exit(
            f"ABORTADO: {repo_id} es PÚBLICO. Contiene material con licencia; hazlo privado "
            f"antes de subir nada."
        )


def _comprobar_manifiesto(manifiesto: dict) -> None:
    """Aborta si `manifest.json` no coincide con la tabla que se va a publicar.

    El manifiesto lo escribe la ingesta, pero `curar_indice.py` cambia el número de filas
    después. Publicar uno desfasado no rompe nada visible —y por eso es peligroso—: el mensaje
    de commit del Hub y lo que imprime `fetch-index` anuncian un recuento que no es el del
    índice que sirve, y a partir de ahí nadie sabe qué hay publicado.
    """
    try:
        import lancedb
    except ImportError:
        print("AVISO: sin lancedb no se puede verificar el manifiesto; se publica a ciegas.")
        return
    tabla = lancedb.connect(str(DIR_INDICE)).open_table("literatura")
    reales = tabla.count_rows()
    declarados = manifiesto.get("n_fragmentos")
    if declarados != reales:
        sys.exit(
            f"ABORTADO: manifest.json declara {declarados} fragmentos y la tabla tiene {reales}.\n"
            f"Ejecuta 'make curar-indice ARGS=--aplicar' para reconciliarlo antes de publicar."
        )


def publicar_indice() -> None:
    if not DIR_INDICE.exists():
        sys.exit(f"ERROR: no existe {DIR_INDICE}. Ejecuta 'make ingest' primero.")
    manifiesto = json.loads((DIR_INDICE / "manifest.json").read_text(encoding="utf-8"))
    hash_corpus = manifiesto.get("hash_corpus", "desconocido")
    _comprobar_manifiesto(manifiesto)
    api = HfApi()
    _asegurar_repo(api, REPO_INDICE)
    api.upload_folder(
        repo_id=REPO_INDICE,
        repo_type="dataset",
        folder_path=str(DIR_INDICE),
        commit_message=f"Índice RAG · corpus {hash_corpus} · {manifiesto.get('n_fragmentos')} fragmentos",
        # El remoto debe ser un ESPEJO del local, no una acumulación. LanceDB versiona por
        # ficheros: al compactar desaparecen los datos viejos, y sin esto se quedarían en el Hub
        # para siempre. Medido: el repo tenía 2 ficheros de datos y 2 índices FTS huérfanos de
        # versiones anteriores — 73 MB para servir 33 MB, que además se hornean en la imagen.
        delete_patterns="*",
    )
    print(f"OK: índice publicado en {REPO_INDICE} (corpus {hash_corpus})")


def descargar_indice() -> None:
    DIR_INDICE.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_INDICE,
        repo_type="dataset",
        local_dir=str(DIR_INDICE),
    )
    manifiesto = DIR_INDICE / "manifest.json"
    if manifiesto.exists():
        m = json.loads(manifiesto.read_text(encoding="utf-8"))
        print(f"OK: índice descargado · corpus {m.get('hash_corpus')} · {m.get('n_fragmentos')} fragmentos")
    else:
        print("AVISO: descargado sin manifest.json; el índice puede estar incompleto.")


def publicar_libros() -> None:
    pdfs = sorted(DIR_LIBROS.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"ERROR: no hay PDFs en {DIR_LIBROS}.")
    api = HfApi()
    _asegurar_repo(api, REPO_LIBROS)
    api.upload_folder(
        repo_id=REPO_LIBROS,
        repo_type="dataset",
        folder_path=str(DIR_LIBROS),
        allow_patterns=["*.pdf"],
        commit_message=f"Corpus veterinario con licencia ({len(pdfs)} PDF)",
    )
    print(f"OK: {len(pdfs)} libros publicados en {REPO_LIBROS}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=["publish-index", "fetch-index", "publish-books"])
    args = parser.parse_args()
    {
        "publish-index": publicar_indice,
        "fetch-index": descargar_indice,
        "publish-books": publicar_libros,
    }[args.accion]()


if __name__ == "__main__":
    main()
