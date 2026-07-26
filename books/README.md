# Corpus de literatura veterinaria (RAG)

Aquí van los libros con licencia que fundamentan las interpretaciones de la IA.
**Este directorio se ignora en git** (contenido con derechos de autor) — ver `.gitignore`.

## Layout esperado

```
books/
├── Thrall_Veterinary_Hematology_ed3.pdf
├── Thrall_Veterinary_Hematology_ed3.meta.json      (opcional, ver abajo)
├── Weiss_Schalms_Veterinary_Hematology_ed7.pdf
└── ...
```

## Convención de nombre

`Autor_Titulo_edN.pdf` — la edición (`edN`) se detecta automáticamente.

## Metadatos opcionales (sidecar)

Para citas más precisas, añade un archivo hermano `<nombre>.meta.json`:

```json
{
  "libro": "Thrall — Veterinary Hematology and Clinical Chemistry",
  "edicion": "3.ª ed. (2022)",
  "especie": ""
}
```

- `especie`: dejar `""` si el libro cubre ambas; `"canino"` o `"felino"` si es específico
  (permite filtrar la recuperación por especie del paciente).

## Construir el índice

Una vez colocados los PDFs:

```bash
make ingest        # equivale a: uv run --group rag python -m app.rag.ingest
```

Esto genera `instance/rag_index/` (LanceDB) con los fragmentos + embeddings y un
`manifest.json` con la versión del corpus (para reproducibilidad de las evals).

El índice se hornea de **sólo lectura** en la imagen Docker; no requiere almacenamiento
persistente en HF Spaces. Reconstruir sólo cuando cambie el corpus.

## Privacidad y copyright

- El texto de los libros **nunca** se sirve al cliente ni sale del contenedor: la API
  sólo pasa fragmentos cortos al modelo como contexto de fundamentación.
- El índice vive en `instance/` (fuera del webroot), nunca bajo `data/` (que sí se sirve).
- Los embeddings se generan con un modelo auto-alojado (`BAAI/bge-m3` por defecto), de modo
  que el contenido no se envía a terceros durante la ingesta.
