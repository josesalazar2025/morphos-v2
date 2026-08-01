"""Configuración central del backend.

Todos los secretos y rutas se leen de variables de entorno (o de un .env fuera del
webroot). No hay credenciales por defecto: el servicio falla de forma segura si falta
lo necesario para una función concreta.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del repo (…/morphos). La BD y el índice RAG viven FUERA del directorio servido.
RAIZ_REPO = Path(__file__).resolve().parents[2]


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(RAIZ_REPO / "backend" / ".env"),
        env_prefix="MORPHOS_",
        extra="ignore",
    )

    # --- Entorno ---
    entorno: str = Field(default="dev", description="dev | prod")

    # --- CORS / orígenes permitidos (bloqueado, no '*') ---
    origenes_permitidos: list[str] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
    )

    # --- Sesión ---
    session_secret: str = Field(default="")  # obligatorio en prod; validado al arrancar
    cookie_secure: bool = Field(default=False)  # True en prod (HTTPS)
    session_max_age_s: int = Field(default=60 * 60 * 8)

    # --- Base de datos (usuarios). Ruta fuera del webroot. ---
    db_path: Path = Field(default=RAIZ_REPO / "instance" / "morphos.db")
    mysql_dsn: str = Field(default="")  # si se define, se usa en vez de SQLite
    mysql_user: str = Field(default="")
    mysql_password: str = Field(default="")

    # --- Ruta IA por defecto y proveedores ---
    ia_backend_defecto: str = Field(default="medgemma")  # medgemma | claude

    # medGemma auto-alojado. Por defecto se usa el HF Space (Gradio) donde está alojado
    # medGemma; si se vacía `hf_space_url`, la ruta 'medgemma' cae a Ollama en `medgemma_base_url`.
    medgemma_base_url: str = Field(default="http://localhost:11434")
    medgemma_model: str = Field(default="medgemma:latest")
    # La PRIMERA petición a Ollama carga el modelo en memoria, y eso domina el tiempo: un 14B
    # cuantizado tarda minutos en frío y luego responde en segundos. Con 120 s la primera
    # llamada se caía por timeout y las evals lo veían como "no se pudo conectar".
    medgemma_timeout_s: int = Field(default=300)
    hf_space_url: str = Field(default="https://blackmistcode-morphos-medgemma.hf.space/gradio_api")
    # Salida ESTRUCTURADA del Space: se le manda el JSON Schema de InterpretacionClinica y el
    # Space restringe la decodificación a producirlo (como `format` en Ollama). Es la corrección
    # de raíz de la ruta de prosa —de ella salen los campos estructurados vacíos, la cobertura
    # medida sobre texto, la atribución reconstruida a mano y buena parte de la fragilidad al
    # prompt—, pero exige que el Space tenga `lm-format-enforcer` y activa el salto de
    # razonamiento (la restricción aplica desde el primer token). OFF hasta medirlo contra la
    # puerta: cambia de golpe el system prompt, el contrato del cliente y cómo se mide la
    # cobertura, así que no entra sin A/B.
    hf_space_estructurado: bool = Field(default=False)
    # Acepta tanto MORPHOS_HF_API_KEY como el HF_API_KEY sin prefijo (convención heredada
    # del proxy PHP), para no obligar a renombrar la variable en .env.
    hf_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MORPHOS_HF_API_KEY", "HF_API_KEY"),
    )

    # Claude (ruta híbrida opcional + juez de evals).
    # Opus 5 es el modelo por defecto recomendado. NO usar Fable 5 aquí: (a) cuesta el doble
    # ($10/$50 vs $5/$25 por millón de tokens), (b) exige retención de datos de 30 días — no
    # está disponible con retención cero, lo que choca con el posicionamiento de privacidad de
    # esta app, y (c) sus clasificadores de seguridad apuntan a biología de investigación y
    # pueden dar falsos positivos en trabajo clínico/biológico benigno, devolviendo
    # `stop_reason="refusal"` en una interpretación veterinaria legítima.
    anthropic_api_key: str = Field(default="")
    claude_model: str = Field(default="claude-opus-5")

    # --- RAG ---
    # Fuera de cualquier directorio servido: contiene fragmentos de texto de los libros
    # con licencia y no debe ser descargable. Se hornea de sólo lectura en la imagen.
    rag_index_dir: Path = Field(default=RAIZ_REPO / "instance" / "rag_index")
    # Repos privados del Hub. El índice (~70 MB) se publica y se descarga en la build de Docker;
    # los libros con licencia (~226 MB) NUNCA entran ni al repo git ni a la imagen: sólo se leen
    # al reingerir. Ambos deben ser privados: el índice contiene el texto de los libros troceado.
    rag_index_repo: str = Field(default="blackmistcode/morphos-rag-index")
    rag_books_repo: str = Field(default="blackmistcode/morphos-books")
    rag_embed_model: str = Field(default="BAAI/bge-m3")
    rag_top_k: int = Field(default=6)
    # Techo de literatura que se INCLUYE EN EL PROMPT de la ruta de prosa (HF Space), en
    # caracteres. No limita la recuperación (el reranking sigue eligiendo entre `rag_top_k`),
    # sólo cuánto se le enseña al modelo.
    #
    # Por qué existe: medGemma 1.5 razona antes de responder y el Space reparte un único
    # presupuesto de 2048 tokens entre ese razonamiento —que descarta— y la respuesta. Cuanta
    # más literatura entra, más largo es el razonamiento y menos presupuesto queda: con 6
    # fragmentos (~3.600 caracteres) la respuesta se cortaba a mitad de frase en ~220 tokens,
    # con 2 salía completa en ~950. Medido contra el Space el 2026-07-27.
    #
    # No se aplica a Ollama ni a Claude: ahí el razonamiento va desactivado o no comparte
    # presupuesto con la respuesta, y más contexto sólo mejora la fundamentación.
    rag_max_chars_prompt: int = Field(default=1800)
    rag_habilitado: bool = Field(default=True)
    # Idioma de la consulta de recuperación. "en" (por defecto) traduce el vocabulario clínico
    # controlado a inglés: el A/B con juez LLM mostró mejor precisión y, sobre todo, mejor
    # rango del primer fragmento relevante (MRR 0.92→1.0) frente a "es" cross-lingual, porque
    # empareja consulta↔corpus (inglés). "es" mantiene el comportamiento cross-lingual con
    # bge-m3. El índice es independiente del idioma de consulta (se traduce en tiempo de query).
    rag_query_lang: str = Field(default="en")
    # Tier 2 — recuperación híbrida + reranking. Se recupera un pozo de candidatos por
    # búsqueda densa (vector) y léxica (BM25/FTS), se fusiona con RRF y se reordena con un
    # cross-encoder multilingüe hasta `rag_top_k`. Degrada con elegancia: sin índice FTS →
    # sólo vectorial; sin el reranker → orden RRF. `bge-reranker-v2-m3` es multilingüe, así
    # que reordena bien aunque la consulta vaya en español y el corpus en inglés.
    rag_hibrido: bool = Field(default=True)
    rag_rerank: bool = Field(default=True)
    rag_candidatos: int = Field(default=30)  # tamaño del pozo antes de reordenar
    rag_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")
    # Multi-consulta: en vez de concatenar todos los patrones y hallazgos en UNA cadena —que
    # se embebe en un único vector donde "anemia regenerativa ; azotemia ; hipoalbuminemia" no
    # es ninguno de los tres—, se lanza una consulta por patrón más una agregada de hallazgos
    # y se fusionan por rango con RRF. El pozo de candidatos TOTAL no crece (se reparte entre
    # las consultas), así que el coste de reranking es el mismo. Sin llamadas a ningún modelo
    # generativo: la descomposición la da el motor determinista, que ya sabe qué patrones hay.
    #
    # OFF por defecto: medido el 2026-07-31 con `run_retrieval_eval.py --multiconsulta` sobre
    # los 17 casos dorados, EMPEORA — precision@k 0.81→0.50 y MRR 0.91→0.86, con hit_rate
    # intacto (0.94). Salvedad grande: el único juez disponible sin coste era el heurístico de
    # solape de palabras, que favorece a la consulta concatenada (lleva descripción + analitos
    # + signos, así que sus fragmentos comparten vocabulario con el diagnóstico esperado por
    # construcción) frente a consultas de un solo analito, que traen pasajes mecanísticos con
    # menos solape léxico. Inspeccionados a mano, varios de esos fragmentos eran mejores
    # (p. ej. «Na:K ratio < 27 is diagnostic of hypoadrenocorticism» donde la consulta única
    # traía una tabla de caso). Volver a medir con un juez LLM local (`ollama pull` de un
    # modelo generativo, gratis) antes de decidir; hasta entonces no se cambia el defecto.
    rag_multiconsulta: bool = Field(default=False)
    rag_max_consultas: int = Field(default=4)
    # Cuota de diversidad: preferencia (no límite duro) de fragmentos por libro, para no gastar
    # el presupuesto del prompt en varias páginas del mismo capítulo. Si no hay material de
    # otras fuentes, se rellena igualmente hasta `rag_top_k`. 0 la desactiva.
    rag_max_por_libro: int = Field(default=2)
    # Suelo de relevancia sobre la puntuación del cross-encoder: por debajo, el fragmento se
    # descarta en vez de rellenar `rag_top_k`. Un fragmento flojo gasta presupuesto de prompt e
    # invita a una cita que parece respaldo sin serlo. Por defecto None = desactivado: la escala
    # del reranker son logits sin calibrar y fijar un umbral a ojo puede vaciar la recuperación.
    # Calibrar con `evals/run_retrieval_eval.py` (mirar los scores de los juzgados relevantes)
    # antes de ponerle valor. Sólo se aplica cuando el reranker corrió.
    rag_score_minimo: float | None = Field(default=None)
    # Tier 3 (opcional, OFF por defecto; activar sólo si el A/B de evals muestra que Tier 2
    # se queda corto) — "contextual retrieval" estilo Anthropic: en la ingesta se antepone a
    # cada fragmento una frase de contexto generada con Claude ANTES de embeber (se almacena
    # el texto original; se embebe el enriquecido). Coste: una llamada a Claude por fragmento.
    rag_contextual: bool = Field(default=False)

    # --- Composición del prompt ---
    # Si los patrones del motor determinista se le enseñan al modelo. Ponerlo en False NO los
    # quita de la petición: se siguen usando para construir la consulta de recuperación
    # (`construir_consulta`) y para el suelo de derivación (`_derivacion_obligatoria`), que no
    # dependen del modelo. Sólo deja de mostrárselos, bajo la hipótesis de que un modelo
    # clínico ya deduce la correlación a partir de los valores alterados. Es una hipótesis
    # medible: A/B con `run_evals.py` antes de cambiar el valor por defecto.
    prompt_incluir_patrones: bool = Field(default=True)
    # Si cada hallazgo lleva su etiqueta de gravedad (leve/moderado/grave) en el prompt. La duda
    # es razonable: la gravedad es un JUICIO del motor, no un dato de laboratorio, y medido el
    # 2026-07-31 una sola palabra la mueve entera —cambiar 'moderado' por 'grave' en el Hct de
    # `imha-canino` hizo que el modelo dejara de nombrar la IMHA y alucinara analitos—. La
    # dirección (alto/bajo) sí es objetiva y se mantiene siempre. A/B con `run_evals.py` antes de
    # cambiar el valor por defecto.
    prompt_incluir_gravedad: bool = Field(default=True)

    # --- Límites de subida (citologías) ---
    max_imagenes: int = Field(default=4)
    max_bytes_imagen: int = Field(default=6 * 1024 * 1024)

    # --- Rate limiting ---
    limite_interpret: str = Field(default="10/minute")
    # Techo por USUARIO además del de IP. La cuota de ZeroGPU es por cuenta y compartida entre
    # todos los veterinarios que usan la instancia pública: sin este límite, uno solo puede
    # agotar la capacidad del día. Ajustar según la cuota real del plan.
    limite_interpret_usuario: str = Field(default="20/hour")
    limite_login: str = Field(default="5/minute")
    limite_papers: str = Field(default="30/minute")
    limite_lab_ingesta: str = Field(default="120/minute")  # el analizador puede enviar en ráfaga
    limite_lab_consulta: str = Field(default="60/minute")

    # --- Integración de analizadores de laboratorio ---
    # Claves de API de los puentes locales (dispositivos headless). Autoriza /api/lab/ingesta.
    # Si está vacía, la ingesta queda DESHABILITADA (falla cerrado con 503). Acepta lista JSON
    # o cadena separada por comas en MORPHOS_LAB_API_KEYS.
    lab_api_keys: list[str] = Field(default_factory=list)
    # Persistencia opcional de resultados en SQLite (sólo útil con volumen persistente).
    lab_persistir: bool = Field(default=False)

    @field_validator("lab_api_keys", mode="before")
    @classmethod
    def _dividir_keys(cls, v):
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v

    def validar_prod(self) -> None:
        """Requisitos que sólo aplican en producción; falla cerrado si faltan."""
        if self.entorno != "prod":
            return
        faltantes = []
        if len(self.session_secret) < 32:
            faltantes.append("MORPHOS_SESSION_SECRET (>=32 chars)")
        if not self.cookie_secure:
            faltantes.append("MORPHOS_COOKIE_SECURE=true")
        if faltantes:
            raise RuntimeError(
                "Configuración de producción incompleta: " + ", ".join(faltantes)
            )


@lru_cache
def obtener_config() -> Configuracion:
    cfg = Configuracion()
    cfg.validar_prod()
    return cfg
