"""Configuración central del backend.

Todos los secretos y rutas se leen de variables de entorno (o de un .env fuera del
webroot). No hay credenciales por defecto: el servicio falla de forma segura si falta
lo necesario para una función concreta.
"""

from __future__ import annotations

import hmac
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

log = logging.getLogger(__name__)

# Raíz del repo (…/morphos). La BD y el índice RAG viven FUERA del directorio servido.
RAIZ_REPO = Path(__file__).resolve().parents[2]

# Punto de montaje del almacenamiento persistente en HF Spaces.
VOLUMEN_PERSISTENTE = Path("/data")

# Clínica a la que pertenecen los dispositivos y usuarios que no declaran otra. Un despliegue de
# una sola clínica —el caso normal— se queda entero aquí y no nota el cambio; el aislamiento
# aparece en cuanto se declaran tenants distintos.
TENANT_POR_DEFECTO = "principal"


def _ruta_db_por_defecto() -> Path:
    """Volumen persistente si lo hay; si no, `instance/` (efímero) con aviso al arrancar.

    En HF Spaces `instance/` se pierde en cada reinicio y con él TODAS las cuentas. Si el Space
    tiene almacenamiento persistente contratado, se monta en /data y ahí sí sobreviven. Se elige
    solo en vez de exigir configuración porque el fallo del defecto anterior era silencioso: la
    app arrancaba igual y el problema sólo se veía cuando los usuarios ya no podían entrar.
    Siempre se puede forzar con MORPHOS_DB_PATH.
    """
    if VOLUMEN_PERSISTENTE.is_dir() and os.access(VOLUMEN_PERSISTENTE, os.W_OK):
        return VOLUMEN_PERSISTENTE / "morphos.db"
    return RAIZ_REPO / "instance" / "morphos.db"


# El `.env` del desarrollador NO debe filtrarse a las pruebas: son las mismas que corren en CI,
# donde ese fichero no existe, así que cualquier valor que se cuele hace que pasen o fallen según
# la máquina. Medido el 2026-08-04: un `MORPHOS_MODELOS_LOCALES=qwen2.5:14b` en local tumbaba
# `test_interpret_rechaza_modelo_fuera_de_la_lista_blanca`, que afirma la lista blanca vacía por
# defecto. Las pruebas ponen esta variable en su conftest; el resto del mundo lee el `.env`.
_SIN_ENV_FILE = os.environ.get("MORPHOS_IGNORAR_ENV_FILE") == "1"


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None if _SIN_ENV_FILE else str(RAIZ_REPO / "backend" / ".env"),
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

    # --- Alta de cuentas ---
    # El alta era ABIERTA: cualquiera podía POSTear /api/auth/registro y alcanzar
    # /api/interpret, que gasta cuota de ZeroGPU compartida y, por la ruta Claude, dinero real.
    # El techo por usuario (`limite_interpret_usuario`) protege una identidad que costaba una
    # petición HTTP acuñar, así que no era un techo.
    #
    # Por defecto CERRADA con lista blanca de emails. La lista (y no un simple booleano) es
    # deliberada: `instance/` es efímero en Spaces, así que las cuentas desaparecen en cada
    # reinicio. Con `registro_abierto=False` y sin lista, tras un reinicio no habría forma de
    # crear ninguna cuenta y la app quedaría inservible; con lista, los aprobados se vuelven a
    # dar de alta solos. Cuando los usuarios vivan en almacenamiento persistente, la lista pasa
    # a ser sólo el control de admisión.
    registro_abierto: bool = Field(default=False)
    registro_allowlist: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Base de datos (usuarios). Ruta fuera del webroot. ---
    # Se prefiere el volumen persistente si existe (ver `_ruta_db_por_defecto`). `instance/` NO
    # sobrevive a un reinicio en Spaces: allí cada rebuild se llevaba por delante las cuentas,
    # los hashes y el historial de throttling, y los usuarios tenían que volver a registrarse.
    db_path: Path = Field(default_factory=lambda: _ruta_db_por_defecto())

    # NO hay soporte de MySQL. Existían `mysql_dsn`/`mysql_user`/`mysql_password` con el
    # comentario «si se define, se usa en vez de SQLite», pero NADA en el código los leía: quien
    # los configurara seguiría sobre SQLite sin enterarse. Se eliminan en vez de dejarlos: una
    # opción de configuración que miente es peor que no tenerla. Para sacar los usuarios de
    # SQLite, el camino es un volumen persistente (MORPHOS_DB_PATH) o portar `db.py`.

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
    # Modelos locales que el usuario puede ELEGIR desde la UI. Lista blanca cerrada: vacía por
    # defecto, lo que deja el selector oculto y el comportamiento de siempre (la ruta 'medgemma'
    # la decide el servidor). Formato de cada entrada: `nombre[=prosa|=estructurado]`.
    #
    #   MORPHOS_MODELOS_LOCALES="medgemma1.5:latest, qwen2.5:7b=prosa"
    #
    # Por qué una lista blanca y no un campo de texto libre: el nombre viaja del navegador al
    # servidor y de ahí a Ollama, así que un campo libre deja al cliente decidir qué pesos se
    # descargan en la máquina que aloja el servicio. Y por eso NO hay campo de URL: la base_url
    # se queda en `medgemma_base_url`, del lado servidor. Aceptar una URL del cliente convierte
    # /api/interpret en un SSRF (el servidor haría peticiones a donde diga el navegador).
    #
    # El sufijo declara si el modelo sabe emitir salida ESTRUCTURADA (decodificación restringida
    # por JSON Schema) o hay que pedirle prosa y envolverla. No se infiere: qwen2.5:7b acepta el
    # `format` de Ollama y devuelve JSON válido con `hallazgos_clave`, `diferenciales` y
    # `siguientes_pruebas` VACÍOS, que valida el esquema y deja al veterinario sin lo que vino a
    # buscar. Por defecto se asume `estructurado`, que es lo que hace medGemma.
    #
    # Sólo tiene sentido donde el servicio tiene un Ollama alcanzable: "local" es local al
    # SERVIDOR, no al navegador. En el HF Space se deja vacía.
    # `NoDecode`: sin él, la fuente de entorno intenta json.loads() del valor ANTES de que corra
    # `_dividir_lista` y la forma separada por comas revienta el arranque con SettingsError.
    modelos_locales: Annotated[list[str], NoDecode] = Field(default_factory=list)
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
    # No se aplica a las rutas con salida estructurada (Ollama por defecto, Claude): ahí el
    # razonamiento va desactivado o no comparte presupuesto con la respuesta, y más contexto
    # sólo mejora la fundamentación. Sí se aplica a un modelo local declarado `prosa` en
    # `modelos_locales`: es el mismo modo de fallo (un modelo pequeño razonando en voz alta
    # dentro del mismo presupuesto de generación), aunque no se haya medido caso por caso.
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

    # --- Proxy inverso ---
    # Saltos de proxy DE CONFIANZA delante de la app. 0 = no confiar en `X-Forwarded-For`.
    #
    # Por qué existe: el limitador usaba `request.client.host`, que detrás de un proxy (HF
    # Spaces, cualquier CDN) es la dirección del PROXY, no la del cliente. Con eso,
    # `limite_login` (5/minute) y `limite_papers` dejaban de ser por IP y pasaban a ser
    # GLOBALES: a la vez un bypass (fuerza bruta desde muchas IPs no se limitaba por IP) y una
    # auto-denegación de servicio (un cliente ruidoso agotaba el login de todos).
    #
    # Se declara el número de saltos en vez de leer la cabecera a ciegas porque `X-Forwarded-For`
    # la pone el cliente: confiar en ella sin más permite falsificar la IP y saltarse cualquier
    # límite poniendo una distinta en cada petición. Cada proxy AÑADE la dirección de su par, así
    # que con N saltos de confianza el cliente real es el elemento -N de la lista; todo lo que
    # haya a la izquierda lo escribió alguien no confiable y se descarta.
    #
    # En HF Spaces detrás de su router: 1.
    proxy_saltos_confiables: int = Field(default=0)

    # --- Rate limiting ---
    limite_interpret: str = Field(default="10/minute")
    # Techo por USUARIO además del de IP. La cuota de ZeroGPU es por cuenta y compartida entre
    # todos los veterinarios que usan la instancia pública: sin este límite, uno solo puede
    # agotar la capacidad del día. Ajustar según la cuota real del plan.
    limite_interpret_usuario: str = Field(default="20/hour")
    limite_login: str = Field(default="5/minute")
    limite_papers: str = Field(default="30/minute")

    # --- Cortacircuitos de la ruta IA ---
    # Los límites de arriba frenan a UN cliente; esto protege el recurso COMPARTIDO cuando ya se
    # agotó. Sólo lo alimentan los errores de saturación (cuota de ZeroGPU / límite del router de
    # HF), nunca una salida malformada: ver `ai/cortacircuitos.py`.
    #
    # Dos y no uno: un 429 aislado puede venir de una ráfaga ajena en la cuenta compartida y no
    # significa que el pozo esté vacío. Dos seguidos ya no son casualidad.
    ia_breaker_fallos: int = Field(default=2)
    # Misma duración que el `Retry-After` que ya se le devolvía al cliente en ese caso, para no
    # decirle «vuelve en 5 minutos» y seguir gastando llamadas por dentro mientras tanto.
    ia_breaker_espera_s: int = Field(default=300)
    limite_lab_ingesta: str = Field(default="120/minute")  # el analizador puede enviar en ráfaga
    limite_lab_consulta: str = Field(default="60/minute")

    # --- Integración de analizadores de laboratorio ---
    # Claves de API de los puentes locales (dispositivos headless). Autoriza /api/lab/ingesta.
    # Si está vacía, la ingesta queda DESHABILITADA (falla cerrado con 503). Acepta lista JSON
    # o cadena separada por comas en MORPHOS_LAB_API_KEYS (`NoDecode`, ver `modelos_locales`:
    # sin él la forma con comas fallaba al arrancar pese a estar documentada).
    lab_api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Persistencia opcional de resultados en SQLite (sólo útil con volumen persistente).
    lab_persistir: bool = Field(default=False)
    # Cola de muestras recibidas (`GET /api/lab/pendientes`). DESACTIVADA por defecto: enumera
    # TODAS las muestras del almacén —que no está segmentado por clínica ni por usuario— y cada
    # `muestra_id` que devuelve abre `GET /api/lab/resultados`, o sea el panel completo de
    # analitos más las pistas de paciente (nombre de la mascota, raza, sexo). Cualquier sesión
    # la podía llamar.
    #
    # Apagarla NO cierra el agujero y no hay que venderlo así: el `muestra_id` lo pone el
    # analizador (el puente sólo lo recorta) y suele ser un correlativo corto, así que
    # `/api/lab/resultados` sigue siendo enumerable a fuerza bruta dentro de
    # `limite_lab_consulta`. Lo que se elimina es el volcado en UNA petición. El cierre real es
    # atar cada resultado a un tenant y filtrar por la sesión (ver ARCHITECTURE_REVIEW §2.1).
    #
    # Se enciende en despliegues de una sola clínica, donde el conjunto de sesiones es el
    # personal invitado. El frontend oculta el botón si el endpoint responde 404.
    lab_pendientes_habilitado: bool = Field(default=False)

    @field_validator("lab_api_keys", "modelos_locales", "registro_allowlist", mode="before")
    @classmethod
    def _dividir_lista(cls, v):
        """Acepta lista JSON o cadena separada por comas.

        El decodificado JSON lo hacía antes la fuente de entorno, pero se ejecutaba ANTES que
        este validador y hacía fallar el arranque con la forma de comas (que es la documentada).
        Con `NoDecode` el valor llega crudo y se decide aquí: JSON si lo parece, comas si no.
        """
        if isinstance(v, str):
            crudo = v.strip()
            if crudo.startswith("["):
                import json

                try:
                    return json.loads(crudo)
                except json.JSONDecodeError:
                    pass
            return [k.strip() for k in crudo.split(",") if k.strip()]
        return v

    def modelos_locales_permitidos(self) -> dict[str, bool]:
        """Lista blanca parseada: nombre del modelo → si hay que pedirle PROSA.

        Se separa por '=' y no por ':' porque el nombre de un modelo de Ollama ya lleva ':'
        (`medgemma1.5:latest`). Un sufijo desconocido se trata como `estructurado`, que es el
        valor por defecto; no se lanza, para que una errata en el .env no impida arrancar el
        servicio entero por un selector opcional.
        """
        permitidos: dict[str, bool] = {}
        for entrada in self.modelos_locales:
            nombre, _, modo = entrada.partition("=")
            nombre = nombre.strip()
            if nombre:
                permitidos[nombre] = modo.strip().lower() == "prosa"
        return permitidos

    def _allowlist_con_tenant(self) -> dict[str, str]:
        """email → tenant. Formato `email` o `email=tenant`; sin sufijo, TENANT_POR_DEFECTO."""
        mapa: dict[str, str] = {}
        for entrada in self.registro_allowlist:
            email, _, tenant = entrada.partition("=")
            email = email.strip().lower()
            if email:
                mapa[email] = tenant.strip() or TENANT_POR_DEFECTO
        return mapa

    def emails_registro_permitidos(self) -> set[str]:
        """Allowlist normalizada (minúsculas, sin espacios) para comparar con el email entrante."""
        return set(self._allowlist_con_tenant())

    def registro_permitido(self, email: str) -> bool:
        """Si este email puede darse de alta."""
        if self.registro_abierto:
            return True
        return email.strip().lower() in self.emails_registro_permitidos()

    def tenant_de_email(self, email: str) -> str:
        """Clínica a la que pertenece un email al darse de alta.

        Con el alta abierta (desarrollo) todo el mundo cae en el tenant por defecto: no hay
        ninguna declaración de la que deducir otra cosa.
        """
        return self._allowlist_con_tenant().get(email.strip().lower(), TENANT_POR_DEFECTO)

    def tenant_de_clave_dispositivo(self, token: str) -> str | None:
        """Tenant dueño de esta API key de dispositivo, o None si no es válida.

        Recorre TODAS las claves con `compare_digest` en vez de indexar un diccionario: un
        lookup por hash sobre un secreto filtra por tiempo si coincide el prefijo, y esta
        comparación es la única barrera de la ingesta.
        """
        encontrado: str | None = None
        for entrada in self.lab_api_keys:
            tenant, sep, clave = entrada.partition(":")
            if not sep:
                tenant, clave = TENANT_POR_DEFECTO, entrada
            if hmac.compare_digest(token, clave.strip()):
                encontrado = tenant.strip() or TENANT_POR_DEFECTO
        return encontrado

    def avisar_de_configuracion(self) -> None:
        """Avisos de arranque que no justifican fallar, pero sí que se vean en el log."""
        if self.registro_abierto:
            log.warning(
                "MORPHOS_REGISTRO_ABIERTO=true: cualquiera puede crear una cuenta y gastar "
                "cuota de modelo. Sólo para desarrollo local."
            )
        elif not self.emails_registro_permitidos():
            # El caso que deja la instancia inservible tras un reinicio con `instance/` efímero.
            log.warning(
                "Alta de cuentas cerrada y MORPHOS_REGISTRO_ALLOWLIST vacía: nadie puede "
                "registrarse. Si la base de usuarios está vacía, nadie podrá entrar."
            )

        if self.entorno == "prod" and self.proxy_saltos_confiables <= 0:
            # Silencioso y caro: los límites siguen "funcionando", sólo que compartidos por todo
            # el mundo, así que no se nota hasta que alguien agota el login de los demás.
            log.warning(
                "MORPHOS_PROXY_SALTOS_CONFIABLES=0 en producción: si hay un proxy delante "
                "(HF Spaces lo tiene), los límites por IP son en realidad GLOBALES. Declara "
                "cuántos saltos de confianza hay."
            )

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
    cfg.avisar_de_configuracion()
    return cfg
