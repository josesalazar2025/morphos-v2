# Integración de analizadores de laboratorio en Morphos

> Plan de integración para que los equipos de laboratorio envíen resultados directamente
> a Morphos. Alcance actual: **Abaxis (VetScan), Scil/Horiba y Bionote Vcheck V200**.

## Estado de implementación

- ✅ **Fase 0 (contratos):** `backend/app/schemas_lab.py`, `backend/app/lab/mapeo.py` +
  `data/lab_mapeos/generico.json` (387 códigos) + 33 pruebas.
- ✅ **Fase 1 (MVP extremo-a-extremo):** auth de dispositivo (`security/device.py`), almacén
  TTL (`lab/almacen.py`), endpoints `POST /api/lab/ingesta` + `GET /api/lab/resultados`
  (`routers/lab.py`) + 6 pruebas; frontend `lab-import.ts` + `form-inject.ts` + campo de ID
  de muestra en `index.html` + 5 pruebas; puente `bridge/` (transportes MLLP/serie,
  adaptadores HL7 v2 y ASTM, reenviador con spool) + 8 pruebas. Verificado extremo-a-extremo:
  HL7 del puente → validación + mapeo del backend (p. ej. `GLU 5.0 mmol/L → gluc 90.08`).
- ✅ **Fase 2 (endurecimiento):** cola `GET /api/lab/pendientes` + UI "Ver resultados
  recibidos"; persistencia SQLite opcional (`lab_persistir`, tabla `resultados_lab`, recarga
  al arrancar); `no_mapeados` mostrados en el toast de importación; re-drenado periódico del
  spool en el puente (`spool_reintento_s`). +3 pruebas backend.
- ✅ **Fase 3 (listo para enchufar):** adaptadores por fabricante
  `bridge/bridge/adaptadores/{abaxis,horiba,bionote}.py` + registro que selecciona el parser
  por `fabricante`; tablas `data/lab_mapeos/{abaxis,horiba,bionote}.json` sembradas con los
  códigos reales de cada panel; configuración **multi-equipo** (`MORPHOS_BRIDGE_INSTRUMENTOS`)
  para varias máquinas en un puente. +3 pruebas backend, +5 puente.
  **Pendiente sólo con hardware:** confirmar códigos OBX-3/R-3 y parámetros serie con una
  captura real de cada equipo (ajuste = editar el JSON del fabricante).

## Contexto

Hoy el veterinario teclea los valores a mano (o importa un PDF). El objetivo es que los
analizadores físicos alimenten los resultados directamente en la app. Los equipos objetivo
(este alcance) son **Abaxis (VetScan), Scil/Horiba y Bionote Vcheck V200**. Decisiones del
usuario: topología **nube + puente local**, **emparejamiento por ID de muestra/accesión**,
**sólo entrada de resultados** (inbound).

**IDEXX queda explícitamente fuera de alcance por ahora** (su ruta propietaria vía VetLab
Station requeriría middleware/carpeta-drop y acceso al equipo real) — pero la capa de
adaptadores se mantiene *pluggable* por fabricante para poder añadir IDEXX u otros más
adelante sin rediseñar.

Dos realidades condicionan el diseño:

1. **Dos familias de protocolo entre los tres equipos.** Abaxis VetScan y Scil/Horiba
   emiten **ASTM E1381/E1394 (LIS2-A2) sobre RS-232 / USB-serial** (el **Abaxis VS2 admite
   ASCII Text / XML / ASTM**: se configura a **ASTM**, el formato que consume
   `astm_generico.py`; ASCII/XML quedan como respaldo si un sitio no puede activar ASTM). El **Bionote
   Vcheck V200 es estándar, no propietario: habla HL7 v2.6 PCD-01** (perfil IHE Patient
   Care Device "Communicate PCD Data", es decir ORU^R01 sobre MLLP/TCP) **y POCT1-A**
   (protocolo XML de punto de atención, CLSI POCT1-A2). Por tanto el puente necesita **dos
   transportes**: `serial` (`pyserial`) para el ASTM de Abaxis/Horiba, y `mllp` (TCP) para
   el HL7 v2.6 de Bionote. Un parser de registros ASTM se comparte entre Abaxis/Horiba; el
   adaptador HL7 v2 (`hl7v2.py`) cubre Bionote con un manejo del perfil PCD-01 — **HL7 v2 ya
   no es sólo "genérico/futuro", lo exige un equipo nombrado**. (POCT1-A queda como ruta
   alternativa de Bionote, XML, diferida salvo que se prefiera sobre HL7.) Se necesita una
   capa de adaptadores por analizador que normalice a un modelo de resultado canónico.
2. **Morphos se despliega en HF Spaces** (un único puerto HTTP, sin alcance a la LAN, disco
   efímero). El backend nunca debe abrir un listener TCP/MLLP crudo. En su lugar, un pequeño
   **puente local** corre en la LAN de la clínica, habla el protocolo nativo de cada
   analizador y reenvía los resultados normalizados al backend por HTTPS autenticado.

La clave de unión en toda la app es la **clave de analito** (atributo `name` del input ==
clave en `data/valores_referencia.json` == clave de entrada del motor de análisis; 90
claves, idénticas para canino/felino). `frontend/src/pdf-parser.ts` ya codifica el
vocabulario de alias + conversión de unidades y la ruta de inyección en el formulario
(`aplicarAFormulario` → `evaluar()`); lo reutilizamos.

```
LAN de la clínica (bridge/)             HF Spaces (FastAPI, un puerto HTTP)
 analizadores → adaptadores → normaliza --HTTPS--> POST /api/lab/ingesta  (API key equipo)
   (HL7 MLLP / ASTM / serial)   Bearer key         GET  /api/lab/resultados (cookie sesión)
                                                    almacén TTL en proceso (muestra_id → mapeado)
                                              navegador consulta por ID de muestra → inyecta → evaluar()
```

Dos zonas de confianza, dos mecanismos de auth: **puente→backend** usa una **API key** de
equipo (nunca la cookie del navegador); **navegador→backend** mantiene la cookie de sesión
+ CSRF existentes. El mapeo código→analito y la conversión de unidades ocurren **en el
backend** (una única fuente de verdad, compartida por todo formato de entrada, testeable en
pytest).

## Alcance de este plan

Las fases 0–1 (el MVP: contratos + extremo-a-extremo HL7 v2 / ASTM genérico → match por ID
de muestra → autorrelleno del formulario) están totalmente especificadas. Los adaptadores
por fabricante (fase 3) están estructurados pero cada uno depende de una captura del equipo
real, que no puede hacerse sólo desde código.

---

## Backend

### 1. Modelos canónicos — nuevo `backend/app/schemas_lab.py`
Mantener los esquemas de lab fuera del ya enfocado `schemas.py`. Identificadores en español,
mismas convenciones `str,Enum`/`Literal`/`Field`/`@field_validator` que `schemas.py`.

- `ObservacionAnalizador`: `codigo_prueba: str` (código/nombre de prueba del fabricante,
  crudo, sin mapear), `valor: str` (se mantiene como **string** en la ingesta — preserva
  `"<0.1"`, `">1000"`, `"NEG"`, `"+++"`), `unidad: str = ""`, `rango_referencia`, `bandera`
  (flag H/L de anormalidad, sólo informativo). `@field_validator` recorta + acota longitud.
- `PacientePistas`: opcionales libres `nombre_mascota`, `especie_texto`, `raza`, `sexo`,
  `edad_texto` (para prerrellenar `pt-*`, nunca por encima de lo que teclea el veterinario).
- `ResultadoAnalizador` (una corrida de un instrumento): `muestra_id: str`
  (`min_length=1, max_length=128` — la **clave de match**), `instrumento_id`,
  `instrumento_modelo`, `fabricante`, `pistas_paciente: Optional[PacientePistas]`,
  `observaciones: list[ObservacionAnalizador]`, `momento: datetime`,
  `recibido_en` (default_factory ahora), `formato_origen: Literal["hl7v2","astm","json","manual"]`.
- Extensibilidad hacia salida (outbound): añadir `DireccionMensaje(str,Enum) {entrada,salida}`
  + `direccion = entrada` en el envelope, y un stub comentado `OrdenTrabajo` — reserva el
  namespace `/api/lab/*` y el esquema de almacén para órdenes de trabajo sin construirlas.
- Modelos de respuesta para el navegador: `ValorAnalito {clave, valor, unidad,
  valor_original, unidad_original, es_semicuantitativo}` y `ResultadoMapeado {muestra_id,
  instrumento_id, momento, analitos: dict[str, ValorAnalito], paciente: PacientePistas|None,
  no_mapeados: list[str]}`. Esto es exactamente lo que inyecta el frontend.

### 2. Capa de mapeo — nuevo paquete `backend/app/lab/` + datos `data/lab_mapeos/`
Dirigida por datos, portada desde `frontend/src/pdf-parser.ts`; las claves de salida deben
ser un subconjunto de las 90 claves canónicas (+ los nombres de select semicuantitativos
`uri-*`).

- `backend/app/lab/mapeo.py`:
  - `mapear_observacion(obs, tabla)`: empareja `codigo_prueba` contra la tabla del fabricante
    (código exacto primero, luego alias) → `clave` canónica (+ opcional `claveConv`).
  - `convertir_unidad(clave, claveConv, valor_num, unidad)`: **port a Python de
    `aplicarConversion` + `CONVERSIONES_UNIDADES`** (`pdf-parser.ts:107-186`) — factores
    idénticos para que importación por PDF y por analizador coincidan.
  - `parsear_valor(valor_str)`: port de `extraerValorYUnidad`/`parsearSemiCuantitativo`
    (maneja `"<0.1"`, decimales con coma, `"NEG"`, `"+++"`→valores de opción `uri-*`);
    descarta no-finitos / `<= 0` como el original.
  - `mapear_resultado(res) -> ResultadoMapeado`: recorre observaciones, dedup primer-match-gana,
    deriva % del diferencial de leucocitos desde absolutos + % de reticulocitos cuando sólo
    hay absolutos (port del bloque de derivación en `parsearTextoLab`), recoge códigos
    desconocidos en `no_mapeados`.
- `data/lab_mapeos/generico.json` — tabla canónica sembrada de LOINC + las abreviaturas ya
  presentes en las regex de `DEFS_ANALITOS`. Forma: `{ "clave": {"codigos": ["GLU","GLUC"],
  "unidad_defecto": "mg/dL", "claveConv": "..."} }`.
- `data/lab_mapeos/{abaxis,horiba,bionote}.json` — overrides por fabricante. El fabricante se
  selecciona por `fabricante`/`instrumento_modelo`; desconocido → `generico.json`; código sin
  match → genérico → `no_mapeados` (degradación elegante, refleja la filosofía RAG). Añadir un
  equipo (incluido un futuro IDEXX) = soltar un nuevo JSON, no editar código. (Datos de
  referencia no-PII; se cargan del lado del servidor vía `RAIZ_REPO / "data" / "lab_mapeos"`.)

### 3. Almacén de resultados — nuevo `backend/app/lab/almacen.py`
**Almacén TTL en proceso**, no SQLite, para el MVP. Justificación: el disco de HF Spaces es
efímero, `instance/` se reconstruye al reiniciar, el Dockerfile corre **un único** worker de
uvicorn, y los resultados son de vida corta (se emparejan en minutos). Singleton
`AlmacenResultados` con `guardar`, `obtener`, `pendientes`, `_barrer` (TTL ~24 h + tope LRU),
`threading.Lock`. La clave es `muestra_id.strip().lower()` normalizada en lectura y escritura.
Importado como singleton de módulo por `routers/lab.py`; barrido periódico opcional vía una
tarea `asyncio` en `_lifespan` (`main.py` ya lo señala como el sitio para tareas de fondo).
- Durabilidad opcional (fase 2, tras `lab_persistir=False`): añadir una tabla `resultados_lab`
  al `_ESQUEMA` de `db.py` y doble-escritura vía el patrón `_conexion()` existente. OFF por
  defecto — sólo tiene sentido con un volumen persistente. Documentar el trade-off.

### 4. Endpoints — nuevo `backend/app/routers/lab.py`, registrar en `main.py`
Registrar como los demás: `from .routers import auth, interpret, lab, papers` +
`app.include_router(lab.router, prefix="/api")`.

- **`POST /api/lab/ingesta`** (puente → backend). Firma como `interpret.py`:
  `request: Request` primero, `cuerpo: ResultadoAnalizador`,
  `_disp = Depends(verificar_dispositivo)` (nuevo; §Seguridad). **Sin**
  `usuario_actual`/`verificar_csrf` (puente headless, sin cookie).
  `@limiter.limit(obtener_config().limite_lab_ingesta)` (p. ej. `"120/minute"`, ráfagas).
  Ejecuta `mapear_resultado` → `almacen.guardar` → devuelve `{ok, muestra_id,
  analitos_mapeados, no_mapeados}`. Rechaza `observaciones` vacías/desmesuradas con
  `HTTPException(422, "…español")`.
- **`GET /api/lab/resultados`** (navegador → backend). `request: Request`,
  `muestra: str = Query(..., min_length=1, max_length=128)`,
  `_sesion = Depends(usuario_actual)`, `@limiter.limit(...limite_lab_consulta)` (p. ej.
  `"60/minute"`). Devuelve el `ResultadoMapeado` más reciente para `muestra` o `404` "No hay
  resultados para esa muestra todavía."
- **`GET /api/lab/pendientes`** (opcional, fase 2, auth de sesión): recientes sin reclamar
  `{muestra_id, instrumento_id, momento}` para una UI de cola de selección.

**Polling, no SSE**: el stack es request/response, HF Spaces complica el SSE de larga vida, y
la UX es "arma un ID de muestra, espera segundos." El frontend consulta `GET …?muestra=<id>`
cada ~3 s durante ~90 s; 404 = seguir esperando, 200 = aplicar. Cero infra de servidor nueva.
(SSE anotado como optimización futura.)

### 5. Seguridad — `backend/app/config.py`, `backend/app/security/`
- Nueva dependencia `verificar_dispositivo(request, authorization: Header)` en `authz.py` (o
  hermano `security/device.py`): `hmac.compare_digest` de tiempo constante de un token Bearer
  contra las keys configuradas (misma disciplina que `verificar_password`).
- Añadidos en `config.py`: `lab_api_keys: list[str]` (desde `MORPHOS_LAB_API_KEYS`; soporta
  rotación/por-clínica), `limite_lab_ingesta`, `limite_lab_consulta`, `lab_persistir`.
  `validar_prod()` exige ≥1 key cuando la ingesta de lab está activada. La ingesta es
  sin-cookie/sin-CSRF **por diseño** — la API key es la auth, sólo por HTTPS.
- **No aflojar CORS ni CSP.** El puente es servidor-a-servidor (CORS gobierna navegadores); el
  navegador sólo llama a `/api/lab/*` del mismo origen con la cookie existente, así que
  `connect-src 'self'` ya lo cubre — sin nueva cabecera de navegador, sin cambio de preflight.
- Los valores del analizador son **datos, nunca instrucciones**: pueblan inputs numéricos y
  llegan al modelo sólo como los mismos `hallazgos` estructurados que ya produce el motor
  determinista. Acotar todas las longitudes de string en `schemas_lab.py`.

---

## Frontend — nuevo `frontend/src/lab-import.ts`, ediciones a `index.html` + `main.ts`
Reflejar `pdf-parser.ts` exactamente (clave de unión = `name` de analito; `evaluar()` es el
disparador reactivo). El mapeo es del lado del servidor, así que el lado TS es delgado.

- `frontend/src/lab-import.ts` exporta `inicializarImportLab(evaluar)`:
  - Input de ID de muestra + botón "Importar del analizador"; un lector de código de barras
    simplemente teclea en el campo + Enter. Al armar, consulta `GET
    /api/lab/resultados?muestra=<id>` con `fetch(..., {credentials:'include'})` cada 3 s hasta
    ~90 s.
  - En 200: inyecta `ResultadoMapeado.analitos` reusando la lógica de inyección —
    `document.querySelector('[name="${clave}"]').value = valor` para números, match de opción
    para selects `uri-*`, luego `evaluar()`; aplica las pistas `paciente` a `pt-*` como
    `aplicarPacienteAFormulario`. **Refactor pequeño recomendado:** extraer
    `aplicarAFormulario` + `aplicarPacienteAFormulario` de `pdf-parser.ts` a un
    `frontend/src/form-inject.ts` compartido e importar desde ambos, evitando duplicación.
    Reusar `mostrarToast` para "N valores importados del analizador."
  - Marcar los campos importados con un resaltado transitorio para que el veterinario vea qué
    cambió; el toast debe indicar que los valores se autorrellenaron y **deben verificarse**
    (refuerza la postura de seguridad existente `requiere_derivacion`).
- `index.html`: añadir un campo de ID de muestra + control de importación en el panel de
  paciente (`#panel-paciente`, junto a `pt-*`), siguiendo la convención existente
  `.btn-importar-pdf`/`data-panel`. Sin cambio de CSP.
- `frontend/src/main.ts`: importar y llamar `inicializarImportLab(evaluar)` junto a la línea
  existente `inicializarParserPdf(evaluar)` (~L169), pasando la misma referencia `evaluar`.

---

## Puente local — nuevo `bridge/` de nivel superior (proyecto uv separado)
Python + uv para coincidir con el tooling del repo y reusar las formas canónicas; su propio
`bridge/pyproject.toml` para que las deps de serial/HL7 nunca inflen la imagen de HF Spaces.

```
bridge/
  pyproject.toml            # uv: httpx, pyserial, python-hl7 (o hl7apy); pytest grupo dev
  bridge/config.py          # BridgeConfig(BaseSettings) env_prefix MORPHOS_BRIDGE_: morphos_url, api_key, instrumentos[]
  bridge/modelo.py          # forma canónica ResultadoAnalizador
  bridge/transporte/
      serial.py             # lector pyserial → tramas crudas (Abaxis/Horiba ASTM)             [FASE 1]
      mllp.py               # servidor MLLP TCP (\x0b..\x1c\x0d) → tramas crudas (Bionote HL7) [FASE 1]
  bridge/adaptadores/
      base.py               # AdaptadorBase: generador async → yields ResultadoAnalizador
      astm_generico.py      # ASTM E1381/E1394 (STX/ETX/checksum, registros H/P/O/R/L)         [FASE 1]
      hl7v2.py              # parsea ORU^R01 (v2.6 PCD-01) → canónico; requerido por Bionote    [FASE 1]
      registro.py           # fabricante → parser (selección automática)                        [HECHO]
      abaxis.py             # VetScan sobre astm_generico (fabricante=abaxis)                    [HECHO]
      horiba.py             # Scil/Horiba sobre astm_generico (fabricante=horiba)                [HECHO]
      bionote.py            # Vcheck V200 sobre hl7v2 (fabricante=bionote, PCD-01)               [HECHO]
  bridge/normalizador.py    # salida del adaptador → ResultadoAnalizador validado (+ pistas de paciente)
  bridge/reenviador.py      # httpx Bearer POST /api/lab/ingesta, backoff exp, cola spool en disco, idempotencia mensaje_id
  bridge/main.py            # supervisa adaptadores configurados → normalizador → reenviador
  bridge/tests/  bridge/README.md   # cableado por analizador + checklist de validación
```
- Separar **transporte** (serial / MLLP — cómo llegan los bytes) de **adaptador** (ASTM / HL7
  / fabricante — cómo las tramas se vuelven un `ResultadoAnalizador`), de modo que
  Abaxis/Horiba/Bionote reusen `transporte/serial.py` y difieran sólo en el parseo. Cada
  adaptador es un generador async que emite `ResultadoAnalizador`.
- `reenviador.py` es el núcleo de fiabilidad: spool local para no perder nada cuando HF esté
  brevemente inalcanzable; reintentos idempotentes vía `mensaje_id` de cliente (el almacén es
  último-gana por `muestra_id` de todos modos).
- **Cada uno de Abaxis / Horiba / Bionote necesita su propio adaptador + validación en sitio
  contra el instrumento físico**, pero el esfuerzo difiere: Abaxis y Horiba (ASTM sobre
  serie) requieren confirmar parámetros serie — baud/paridad/framing — y el layout de
  registros (y en el Abaxis VS2, seleccionar la salida **ASTM** frente a sus modos ASCII/XML);
  **Bionote (HL7 v2.6 PCD-01 sobre MLLP)** sólo requiere confirmar el transporte
  (puerto MLLP/IP), el juego de identificadores OBX-3 del perfil PCD-01 (a menudo LOINC o
  nomenclatura IEEE 11073/MDC) y las unidades — no hay que revertir ningún formato
  propietario. El README incluye un checklist por analizador (capturar 3–5 corridas reales,
  confirmar transporte + campo de ID de muestra + unidades, diff al JSON del fabricante).
  Abaxis y Horiba caen ambos en `astm_generico.py`; **Bionote se apoya en `hl7v2.py`** con un
  fino mapeo del perfil PCD-01.

---

## Entrega por fases
- **Fase 0 — Contratos (sólo backend, totalmente testeable):** `schemas_lab.py`,
  `data/lab_mapeos/generico.json`, `lab/mapeo.py` + tests unitarios.
- **Fase 1 — MVP extremo-a-extremo:** auth de equipo + config keys; `routers/lab.py`;
  `lab/almacen.py`; registrar en `main.py`; frontend `lab-import.ts` + campo de ID de muestra
  + cableado en `main.ts`; esqueleto del puente con `transporte/serial.py` +
  `transporte/mllp.py` + `adaptadores/astm_generico.py` + `adaptadores/hl7v2.py` +
  `reenviador.py`. Entregable: una máquina ASTM genérico (serial) o HL7 v2 → match por ID de
  muestra → autorrelleno.
- **Fase 2 — Endurecimiento:** durabilidad del spool, UI de cola `/api/lab/pendientes`, flag
  opcional de persistencia SQLite, exponer `no_mapeados` al veterinario.
- **Fase 3 — Adaptadores por fabricante:** `abaxis.py`, `horiba.py`, `bionote.py` + sus JSON,
  cada uno condicionado a captura del equipo real. (IDEXX diferido, fuera de alcance.)

## Riesgos
1. **Dialectos ASTM de Abaxis/Horiba (el mayor, ahora reducido).** Quitar IDEXX elimina el
   riesgo de middleware propietario, y confirmar que Bionote es HL7 v2.6 PCD-01 estándar (no
   propietario) elimina el riesgo de revertir un formato de línea. Riesgo residual principal:
   los dialectos ASTM de Abaxis/Horiba varían en layout de registro y parámetros serie
   (baud/paridad), y necesitan una captura del equipo real para cerrarse. Para Bionote el
   riesgo es menor y acotado: confirmar el transporte (puerto MLLP) y el juego de códigos
   OBX-3 del perfil PCD-01. El JSON dirigido por datos + la separación transporte/adaptador
   contienen el radio de impacto, pero el framing/las unidades aún se validan con capturas
   físicas.
2. **Efimeridad de HF Spaces:** el almacén en proceso pierde resultados al reiniciar.
   Aceptable (resultados de vida corta + reenviables desde el spool del puente) pero debe
   documentarse; no prometer historial durable sin un volumen persistente.
3. **Disciplina de ID de muestra:** el match depende de que el mismo ID esté en la máquina y
   en la UI; el escaneo de código de barras mitiga typos; normalización centralizada en
   `almacen.py`.
4. **Suposición de un solo worker:** el almacén en proceso sólo es correcto con un worker de
   uvicorn (actualmente cierto). Si se añaden workers, mover el almacén a SQLite/caché
   compartida — señalarlo en `almacen.py`.
5. **Deriva en conversión de unidades:** los factores viven en `pdf-parser.ts` y en
   `mapeo.py` — mitigar con tests de paridad.

## Verificación
- **pytest backend** (`TestClient(app)` + `monkeypatch`, reflejando `backend/tests/test_api.py`):
  - `test_lab_mapeo.py`: código de fabricante → clave canónica; conversiones de unidad
    aseverando **paridad** con los factores de `pdf-parser.ts` (p. ej. glucosa `mmol/L→mg/dL
    ×18.016`, creatinina `µmol/L ÷88.4`); semicuant `"+++"→"+++"`; derivación del diferencial
    de leucocitos; `no_mapeados`.
  - `test_lab_ingesta.py`: ingesta con Bearer key válida → 200 + almacenado; key errónea/sin
    key → 401; ingesta y luego `GET /api/lab/resultados?muestra=…` con cookie de sesión →
    analitos mapeados; consulta sin sesión → 401; muestra desconocida → 404.
  - Fixtures: tramas HL7 ORU^R01 (incl. una v2.6 PCD-01 estilo Bionote) + ASTM crudas y sus
    dicts canónicos esperados en `backend/tests/fixtures/lab/`.
- **pytest puente** (`bridge/tests/`): fixture HL7/ASTM cruda → `ResultadoAnalizador`
  normalizado; lógica de reintento/idempotencia del `reenviador` con transporte httpx mockeado.
- **Vitest frontend** (`frontend/src/lab-import.test.ts`, fixture de formulario jsdom como los
  tests del motor): un JSON `ResultadoMapeado` fija los inputs `[name=…]` + selects `uri-*`
  correctos y llama `evaluar` una vez.
- **Extremo-a-extremo manual (MVP):** correr backend (`make dev`) + una instancia del puente
  local; enviar una muestra HL7/ASTM capturada a través del puente; en la UI teclear el ID de
  muestra y confirmar que el formulario se autorrellena, los campos se resaltan y el análisis
  se re-ejecuta. Comandos: `make backend-test`, `make frontend-test`, `make frontend-build`.
- **Fuera de alcance automatizado (explícito):** validación con equipo real de
  Abaxis/Horiba/Bionote — la suite automatizada usa fixtures capturadas; la corrección final
  de parámetros serie/campo/unidad/ID de muestra sólo se confirma contra los instrumentos
  físicos en la LAN de la clínica.
