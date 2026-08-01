"""Pipeline de ingesta RAG (offline / CI, no en tiempo de petición).

Uso:
    uv run --group rag python -m app.rag.ingest --fuente books/ --salida instance/rag_index

Convierte los PDF de la literatura con licencia en un índice LanceDB de fragmentos con
metadatos de procedencia (libro, edición, capítulo, página) para citar. El índice
resultante se hornea de sólo lectura en la imagen Docker.

Estrategia de troceo (Tier 1, ver PLAN_MODERNIZACION.md):
- Extracción con layout: `pymupdf4llm` produce Markdown conservando encabezados y TABLAS
  (críticas: los libros están llenos de tablas de rangos de referencia); doble columna
  ordenada. Cae a `pypdf` (texto plano) si pymupdf4llm no está disponible.
- Troceo ESTRUCTURAL y CRUZANDO PÁGINAS: se ensambla el documento completo y se trocea
  respetando encabezados y párrafos, con tamaño acotado por tokens reales del tokenizador
  de embeddings. Esto sustituye el troceo previo por-página con ventana de palabras fija,
  que fragmentaba conceptos clínicos en los saltos de página.
- Metadatos: `capitulo` se deriva del encabezado Markdown vigente; `pagina` (o rango) se
  rastrea por marcadores de página internos que no se almacenan en el texto.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .alcance_corpus import debe_descartarse, especie_de

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("morphos.rag.ingest")

# Objetivo por fragmento en tokens reales del tokenizador de embeddings. ~450 es un punto
# medio adecuado para interpretación clínica (256 favorece búsquedas puntuales; 512 el
# razonamiento narrativo). El solape preserva continuidad entre fragmentos contiguos.
CHUNK_TOKENS = 450
SOLAPE_TOKENS = 64

# Marcador de página interno: se inyecta al ensamblar y se consume al trocear (nunca se
# guarda). Sin espacios internos para que el troceo por oraciones no lo parta.
_MARCADOR_PAGINA = re.compile(r"〔p(\d+)〕")
_ENCABEZADO_MD = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_LINEA_RUIDO = re.compile(r"vetbooks\.ir|^\s*\d{1,4}\s*$", re.IGNORECASE)


@dataclass
class ChunkMeta:
    texto: str
    libro: str
    edicion: str
    capitulo: str
    pagina: str
    especie: str  # "", "canino" o "felino" si el capítulo es específico


@dataclass
class _Parrafo:
    texto: str
    capitulo: str
    pagina: int


@dataclass
class _FragTmp:
    """Fragmento intermedio con páginas como enteros para poder fusionar y formatear."""

    texto: str
    capitulo: str
    pmin: int
    pmax: int


# Fragmentos por debajo de este tamaño (p. ej. un encabezado suelto) se fusionan con el
# siguiente del mismo capítulo para no contaminar la recuperación con trozos triviales.
_MIN_TOKENS_FRAGMENTO = 25


def _limpiar_titulo(titulo: str) -> str:
    """Quita énfasis/tachado Markdown (**, *, _, `, ~~) de un título de encabezado."""
    return re.sub(r"[*_`~]+", "", titulo).strip()


def _titulo_valido(titulo: str) -> bool:
    """Filtra encabezados OCR-basura que pymupdf4llm detecta por tamaño de fuente
    (cabeceras de página, artefactos: 'va — yy e', 'ge', 'nRBC 100 WBC'). Un título válido
    es mayormente alfabético, tiene al menos una palabra real y no lleva números embebidos
    (salvo el número de capítulo al inicio)."""
    t = titulo.strip()
    if len(t) < 4:
        return False
    no_espacio = sum(1 for c in t if not c.isspace())
    letras = sum(1 for c in t if c.isalpha())
    if no_espacio == 0 or letras / no_espacio < 0.6:
        return False
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+", t)
    if not any(len(p) >= 4 for p in palabras):
        return False
    # Número embebido (no al inicio) → suele ser una cabecera de tabla/línea, no un capítulo.
    if re.search(r"\S\s+\d+\s+\S", t) and not re.match(r"^\d+\s", t):
        return False
    return True


def _extraer_paginas(ruta: Path) -> list[tuple[int, str]]:
    """Devuelve [(pagina, markdown)]. Usa pymupdf4llm (layout+tablas); cae a pypdf."""
    try:
        import pymupdf4llm  # type: ignore

        paginas = pymupdf4llm.to_markdown(str(ruta), page_chunks=True, show_progress=False)
        return [(i, d.get("text", "")) for i, d in enumerate(paginas, 1)]
    except ImportError:
        log.warning("pymupdf4llm no disponible; extracción de menor calidad con pypdf.")
        from pypdf import PdfReader  # type: ignore

        lector = PdfReader(str(ruta))
        return [(i + 1, (pag.extract_text() or "")) for i, pag in enumerate(lector.pages)]


def _limpiar(texto: str) -> str:
    """Quita líneas de ruido (marcas de agua, números de página sueltos) y une guiones
    de fin de línea (`palabra-\\npalabra` → `palabrapalabra`)."""
    lineas = [ln for ln in texto.splitlines() if not _LINEA_RUIDO.match(ln.strip())]
    limpio = "\n".join(lineas)
    limpio = re.sub(r"(\w)-\n(\w)", r"\1\2", limpio)
    return limpio


def _ensamblar_documento(paginas: list[tuple[int, str]]) -> str:
    """Une las páginas en un único Markdown, anteponiendo un marcador de página a cada una
    para poder atribuir páginas a los fragmentos tras trocear cruzando saltos de página."""
    return "\n\n".join(f"〔p{pagina}〕\n{_limpiar(md)}" for pagina, md in paginas)


def _cargar_contador_tokens(modelo_embeddings: str) -> Callable[[str], int]:
    """Contador de tokens del tokenizador de embeddings; cae a heurística por palabras."""
    try:
        from transformers import AutoTokenizer  # type: ignore

        tok = AutoTokenizer.from_pretrained(modelo_embeddings)
        return lambda s: len(tok.encode(s, add_special_tokens=False))
    except Exception as exc:  # noqa: BLE001
        log.warning("Tokenizador de %s no disponible (%s); heurística por palabras.", modelo_embeddings, exc)
        return lambda s: max(1, round(len(s.split()) * 1.3))


def _extraer_parrafos(documento: str) -> list[_Parrafo]:
    """Recorre el Markdown ensamblado y devuelve párrafos etiquetados con su capítulo
    (último encabezado de nivel ≤ 2 vigente) y su página (por marcadores internos).
    Los encabezados se emiten como su propio párrafo para que su texto sea recuperable."""
    parrafos: list[_Parrafo] = []
    capitulo = ""
    pagina = 1
    buffer: list[str] = []

    def vaciar() -> None:
        if buffer:
            texto = " ".join(buffer).strip()
            if texto:
                parrafos.append(_Parrafo(texto=texto, capitulo=capitulo, pagina=pagina))
            buffer.clear()

    for linea in documento.splitlines():
        marcador = _MARCADOR_PAGINA.fullmatch(linea.strip())
        if marcador:
            pagina = int(marcador.group(1))
            continue
        encabezado = _ENCABEZADO_MD.match(linea)
        if encabezado:
            titulo = _limpiar_titulo(encabezado.group(2))
            if not _titulo_valido(titulo):
                continue  # encabezado OCR-basura: ignorar (ni capítulo ni párrafo)
            vaciar()
            nivel = len(encabezado.group(1))
            if nivel <= 2:
                capitulo = titulo
            parrafos.append(_Parrafo(texto=titulo, capitulo=capitulo, pagina=pagina))
            continue
        if not linea.strip():
            vaciar()
            continue
        buffer.append(linea.strip())
    vaciar()
    return parrafos


def _cola_solape(texto: str, contar: Callable[[str], int]) -> str:
    """Últimas ~SOLAPE_TOKENS palabras de un fragmento, para sembrar el siguiente."""
    palabras = texto.split()
    cola: list[str] = []
    for palabra in reversed(palabras):
        cola.insert(0, palabra)
        if contar(" ".join(cola)) >= SOLAPE_TOKENS:
            break
    return " ".join(cola)


def _dividir_parrafo_largo(texto: str, contar: Callable[[str], int]) -> list[str]:
    """Divide un párrafo que excede CHUNK_TOKENS (p. ej. una tabla grande) por oraciones,
    y en último recurso por palabras."""
    oraciones = re.split(r"(?<=[.;:])\s+", texto)
    piezas: list[str] = []
    actual: list[str] = []
    for oracion in oraciones:
        if contar(oracion) > CHUNK_TOKENS:
            if actual:
                piezas.append(" ".join(actual))
                actual = []
            palabras = oracion.split()
            paso = max(1, int(len(palabras) * CHUNK_TOKENS / max(1, contar(oracion))))
            for inicio in range(0, len(palabras), paso):
                piezas.append(" ".join(palabras[inicio : inicio + paso]))
            continue
        if actual and contar(" ".join([*actual, oracion])) > CHUNK_TOKENS:
            piezas.append(" ".join(actual))
            actual = [oracion]
        else:
            actual.append(oracion)
    if actual:
        piezas.append(" ".join(actual))
    return piezas


def _trocear_estructural(parrafos: list[_Parrafo], contar: Callable[[str], int]) -> list[_FragTmp]:
    """Empaqueta párrafos en fragmentos acotados por tokens, sin mezclar capítulos y
    cruzando páginas. Cada fragmento anota su rango de páginas y su capítulo."""
    fragmentos: list[_FragTmp] = []
    buffer: list[str] = []
    paginas_buffer: list[int] = []
    capitulo_buffer = ""

    def vaciar() -> None:
        nonlocal buffer, paginas_buffer
        if not buffer:
            return
        texto = " ".join(buffer).strip()
        if texto:
            fragmentos.append(_FragTmp(texto=texto, capitulo=capitulo_buffer, pmin=min(paginas_buffer), pmax=max(paginas_buffer)))
        semilla = _cola_solape(texto, contar)
        buffer = [semilla] if semilla else []
        paginas_buffer = [max(paginas_buffer)] if buffer else []

    for parr in parrafos:
        cambio_capitulo = capitulo_buffer and parr.capitulo != capitulo_buffer and any(b for b in buffer)
        if cambio_capitulo:
            vaciar()
            buffer, paginas_buffer = [], []  # no arrastrar solape entre capítulos
        if not capitulo_buffer or not buffer:
            capitulo_buffer = parr.capitulo

        piezas = [parr.texto]
        if contar(parr.texto) > CHUNK_TOKENS:
            piezas = _dividir_parrafo_largo(parr.texto, contar)

        for pieza in piezas:
            candidato = " ".join([*buffer, pieza]).strip()
            if buffer and contar(candidato) > CHUNK_TOKENS:
                vaciar()
            buffer.append(pieza)
            paginas_buffer.append(parr.pagina)

    if any(b for b in buffer):
        vaciar()
    return _fusionar_pequenos(fragmentos, contar)


def _fusionar_pequenos(frags: list[_FragTmp], contar: Callable[[str], int]) -> list[_FragTmp]:
    """Fusiona fragmentos diminutos (encabezados sueltos) hacia el siguiente del mismo
    capítulo, uniendo su rango de páginas."""
    salida: list[_FragTmp] = []
    for frag in frags:
        if salida and contar(salida[-1].texto) < _MIN_TOKENS_FRAGMENTO and salida[-1].capitulo == frag.capitulo:
            previo = salida.pop()
            frag = _FragTmp(
                texto=f"{previo.texto} {frag.texto}".strip(),
                capitulo=frag.capitulo,
                pmin=min(previo.pmin, frag.pmin),
                pmax=max(previo.pmax, frag.pmax),
            )
        salida.append(frag)
    return salida


def _metadatos_desde_ruta(ruta: Path) -> dict[str, str]:
    """Deriva libro/edición/especie del nombre de archivo o de un sidecar .meta.json."""
    sidecar = ruta.with_suffix(".meta.json")
    if sidecar.exists():
        return json.loads(sidecar.read_text(encoding="utf-8"))
    m = re.search(r"ed(\d+)", ruta.stem, re.IGNORECASE)
    return {
        "libro": ruta.stem.replace("_", " "),
        "edicion": f"{m.group(1)}.ª ed." if m else "",
        "especie": "",
    }


def trocear_documento(ruta: Path, contar: Callable[[str], int]) -> list[ChunkMeta]:
    """Extrae, ensambla y trocea un PDF, dejando texto+capítulo+página; los metadatos de
    libro/edición/especie los completa el llamador."""
    paginas = _extraer_paginas(ruta)
    documento = _ensamblar_documento(paginas)
    parrafos = _extraer_parrafos(documento)
    fragmentos = _trocear_estructural(parrafos, contar)
    return [
        ChunkMeta(
            texto=f.texto,
            libro="",
            edicion="",
            capitulo=f.capitulo,
            pagina=str(f.pmin) if f.pmin == f.pmax else f"{f.pmin}–{f.pmax}",
            especie="",
        )
        for f in fragmentos
    ]


def _texto_contextualizado(contexto: str, texto: str) -> str:
    """Antepone la frase de contexto al fragmento (para embeber). Sin contexto, el original."""
    contexto = (contexto or "").strip()
    return f"{contexto}\n\n{texto}" if contexto else texto


def _contextualizar(chunks: list[ChunkMeta]) -> list[str]:
    """Genera con Claude una frase de contexto por fragmento y la antepone (para embeber).
    Degrada al texto original ante cualquier fallo; nunca rompe la ingesta."""
    from app.config import obtener_config

    cfg = obtener_config()
    try:
        from anthropic import Anthropic  # type: ignore

        cliente = Anthropic()
    except Exception as exc:  # noqa: BLE001
        log.warning("Claude no disponible para contextual retrieval (%s); se usa texto original.", exc)
        return [c.texto for c in chunks]

    salida: list[str] = []
    for i, c in enumerate(chunks):
        try:
            msg = cliente.messages.create(
                model=cfg.claude_model,
                max_tokens=80,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Libro: {c.libro}. Capítulo: {c.capitulo or 'NE'}.\n\n"
                        f"FRAGMENTO:\n{c.texto[:1500]}\n\n"
                        "En UNA sola frase en español, sitúa este fragmento en su contexto "
                        "clínico (tema y a qué se refiere) para mejorar su recuperación. "
                        "Devuelve SOLO la frase, sin preámbulo."
                    ),
                }],
            )
            contexto = msg.content[0].text.strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("Fallo generando contexto del fragmento %d (%s); texto original.", i, exc)
            contexto = ""
        salida.append(_texto_contextualizado(contexto, c.texto))
        if (i + 1) % 200 == 0:
            log.info("  contextualizados %d/%d", i + 1, len(chunks))
    return salida


def _libros_ya_indexados(salida: Path) -> set[str]:
    """Nombres de `libro` presentes en el índice, o conjunto vacío si aún no existe."""
    try:
        import lancedb  # type: ignore

        tabla = lancedb.connect(str(salida)).open_table("literatura")
        return {str(v) for v in tabla.to_pandas()["libro"].unique()}
    except Exception:  # noqa: BLE001 — sin índice o sin tabla: no hay nada indexado
        return set()


def ingerir(fuente: Path, salida: Path, anexar: bool = False) -> int:
    """Construye el índice desde cero, o (con `anexar`) añade sólo los libros que faltan.

    Reprocesar los dos libros grandes cuesta OCR sobre cientos de MB, así que incorporar una
    guía nueva no puede exigir reconstruirlo todo. En modo anexar se saltan los documentos cuyo
    `libro` ya está en la tabla, se añaden las filas nuevas y se REGENERA el índice FTS, que si
    no quedaría ciego a los fragmentos recién añadidos.
    """
    import lancedb  # type: ignore
    import pyarrow as pa  # type: ignore
    from sentence_transformers import SentenceTransformer  # type: ignore

    from app.config import obtener_config

    cfg = obtener_config()
    archivos = sorted([*fuente.glob("**/*.pdf")])
    if not archivos:
        log.warning("No se encontraron PDFs en %s. Nada que ingerir.", fuente)
        return 0

    if anexar:
        ya = _libros_ya_indexados(salida)
        nuevos = [a for a in archivos if _metadatos_desde_ruta(a).get("libro", a.stem) not in ya]
        if not nuevos:
            log.info("Todos los documentos de %s ya están indexados. Nada que anexar.", fuente)
            return 0
        log.info("Anexando %d documento(s): %s", len(nuevos), ", ".join(a.name for a in nuevos))
        archivos = nuevos

    contar = _cargar_contador_tokens(cfg.rag_embed_model)

    chunks: list[ChunkMeta] = []
    for archivo in archivos:
        meta = _metadatos_desde_ruta(archivo)
        log.info("Procesando %s…", archivo.name)
        descartados = 0
        for chunk in trocear_documento(archivo, contar):
            chunk.libro = meta.get("libro", archivo.stem)
            chunk.edicion = meta.get("edicion", "")
            # Índices, sumarios y preliminares no son literatura: son entradas con números
            # de página, y ocuparían sitio en el prompt sin decir nada clínico.
            if debe_descartarse(chunk.libro, chunk.pagina, chunk.texto):
                descartados += 1
                continue
            # La especie se resuelve por SECCIÓN, no por libro: estos textos son comparados y
            # traen secciones enteras de aves, reptiles y peces que Morphos no atiende. El
            # sidecar sigue valiendo como valor por defecto del tomo. Ver alcance_corpus.py.
            chunk.especie = especie_de(chunk.libro, chunk.pagina, meta.get("especie", ""))
            chunks.append(chunk)
        if descartados:
            log.info("  → %d fragmento(s) descartados (índices, sumarios y preliminares)", descartados)
        log.info("  → %d fragmentos acumulados", len(chunks))

    if not chunks:
        log.warning("No se extrajo texto. ¿PDFs escaneados sin OCR?")
        return 0

    # Tier 3 opcional: contextualiza el texto a embeber (se almacena el original).
    textos_embed = [c.texto for c in chunks]
    if cfg.rag_contextual:
        log.info("Contextual retrieval activo: generando cabeceras con Claude (coste por fragmento)…")
        textos_embed = _contextualizar(chunks)

    log.info("Cargando modelo de embeddings %s…", cfg.rag_embed_model)
    modelo = SentenceTransformer(cfg.rag_embed_model)
    log.info("Generando embeddings de %d fragmentos…", len(chunks))
    vectores = modelo.encode(textos_embed, normalize_embeddings=True, show_progress_bar=True)

    salida.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(salida))
    # strict=True: un desajuste chunks↔vectores indexaría el corpus incompleto en silencio, y el
    # índice se hornea en la imagen — mejor fallar la ingesta que servir citas de fragmentos mal
    # emparejados con su procedencia.
    filas = [
        {**asdict(c), "vector": vec.tolist()} for c, vec in zip(chunks, vectores, strict=True)
    ]
    if anexar:
        tabla = db.open_table("literatura")
        tabla.add(filas)
        log.info("Anexados %d fragmentos; la tabla queda con %d.", len(filas), tabla.count_rows())
    else:
        tabla = db.create_table("literatura", data=filas, mode="overwrite")

    # Índice de texto completo (BM25) sobre `texto` para la recuperación híbrida (Tier 2).
    # Si falla, la recuperación degrada a sólo-vectorial sin romper la ingesta.
    try:
        tabla.create_fts_index("texto", replace=True)
        log.info("Índice FTS (BM25) creado sobre 'texto'.")
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo crear el índice FTS (híbrido degradará a vectorial): %s", exc)

    # Manifiesto para reproducibilidad de evals (versión + hash del corpus + parámetros). En
    # modo anexar se recorre TODA la carpeta, no sólo lo añadido: el manifiesto describe el
    # corpus indexado, no la última operación.
    todos = sorted([*fuente.glob("**/*.pdf")])
    n_total = tabla.count_rows() if anexar else len(chunks)
    huella = hashlib.sha256()
    for archivo in todos:
        huella.update(archivo.name.encode())
        huella.update(str(archivo.stat().st_size).encode())
    (salida / "manifest.json").write_text(
        json.dumps(
            {
                "modelo_embeddings": cfg.rag_embed_model,
                "chunk_tokens": CHUNK_TOKENS,
                "solape_tokens": SOLAPE_TOKENS,
                "troceo": "estructural-markdown-cruzando-paginas",
                "contextual_retrieval": cfg.rag_contextual,
                "indice_fts": True,
                "n_fragmentos": n_total,
                "n_libros": len(todos),
                "libros": [a.name for a in todos],
                "hash_corpus": huella.hexdigest()[:16],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("Índice %s en %s (%d fragmentos).",
             "anexado" if anexar else "construido", salida, n_total)
    _ = pa  # pyarrow se importa para asegurar backend Arrow de LanceDB
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de literatura veterinaria al índice RAG")
    parser.add_argument("--fuente", type=Path, default=Path("books"))
    parser.add_argument("--salida", type=Path, default=Path("instance/rag_index"))
    parser.add_argument(
        "--anexar", action="store_true",
        help="añade sólo los documentos que aún no están en el índice, sin reconstruirlo",
    )
    args = parser.parse_args()
    ingerir(args.fuente, args.salida, anexar=args.anexar)


if __name__ == "__main__":
    main()
