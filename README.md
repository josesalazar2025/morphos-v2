---
title: Morphos
emoji: 🐕
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---
# Morphos — Intérprete de analíticas veterinarias asistido por I.A

## Proyecto final — Curso de Desarrollo Web 2026

> El proyecto se entregó sobre un stack XAMPP (PHP + JS sin build) y desde entonces se
> migró a **Vite + TypeScript (`frontend/`) + FastAPI (`backend/`)**; `js/*.js`, `api/*.php`
> y `.htaccess` se eliminaron el 2026-07-26. Este README describe el estado **actual**. El
> detalle de la migración está en `MIGRACION.md` y la arquitectura viva en `CLAUDE.md`.

---

## Descripción

Morphos es una aplicación web de apoyo al diagnóstico veterinario. Detecta patrones clínicos en tiempo real a partir de valores de laboratorio con un motor propio que corre entero en el navegador, y permite interpretarlos con un modelo de IA especializado en medicina (medGemma multimodal de Google DeepMind, auto-alojado) o con Claude. Incluye búsqueda de artículos científicos en PubMed relacionados con los diagnósticos diferenciales del paciente.

Está orientada a caninos y felinos, con ajuste automático de rangos de referencia por especie, edad, raza y sexo.
Ataca una necesidad real del sector veterinario, que hoy no dispone de herramientas de este tipo
gratuitas, de uso sencillo y capaces de dar información complementaria relevante en muy poco tiempo.

**Qué sale del navegador y qué no.** El esquema de la petición (`PacienteEntrada`) admite
únicamente **especie, raza, edad y sexo**: no existe ningún campo para el nombre del animal ni
para datos del propietario, así que no es una política sino una imposibilidad estructural. A eso
se suman los valores de laboratorio y, si las hay, imágenes de citología o microscopía: campos de
microscopio, sin identificadores. El PDF original **nunca se sube**: se parsea entero en el
navegador.

El único campo de texto libre es «signos clínicos». Hoy viaja tal cual —el servidor lo inspecciona
para la guarda de alcance, pero no lo filtra—, así que es el único sitio donde alguien podría
teclear algo identificativo. Está previsto acotarlo a vocabulario clínico (ver *Mejoras futuras*).

Con la ruta auto-alojada (Ollama en la clínica) no sale nada en absoluto: ver más abajo.

Funcionalidades principales:

```text
Detección de patrones clínicos en tiempo real (motor determinista en el cliente)
Interpretación con IA: medGemma auto-alojado (HF Space u Ollama) o Claude
Respuesta clínica estructurada y validada, con citas a literatura veterinaria (RAG)
Importación de resultados desde PDF, sin subir el archivo a ningún servidor
Análisis de citologías mediante imágenes
Ingesta directa de resultados desde analizadores de laboratorio (ASTM/HL7)
Búsqueda de literatura científica en PubMed
Sistema de autenticación con registro e inicio de sesión
```

---

## Objetivo del proyecto

Integrar los conocimientos del curso en una aplicación web completa que además sea útil y
cubra una necesidad de mercado. El entregable del curso cubría HTML semántico, CSS
propio sin frameworks, JavaScript modular y PHP como backend; la evolución posterior
mantiene esos principios y sustituye la implementación:

```text
HTML semántico y accesible                → intacto
CSS personalizado (variables, grid)       → intacto, sin framework
JavaScript modular                        → TypeScript con build (Vite) y tipos estrictos
PHP como backend de API                   → FastAPI (Python 3.12, gestionado con uv)
```

Conceptos aplicados:

* Separación de responsabilidades por módulos
* Comunicación asíncrona con `fetch` (JSON y SSE)
* Sesiones firmadas y autenticación con contraseñas hasheadas (scrypt)
* Consultas parametrizadas para prevenir inyección SQL
* Detección de patrones mediante lógica clínica codificada
* Salida del modelo **estructurada y validada** (Pydantic) en lugar de texto libre
* Suite de regresión del motor y evals clínicas como puerta de CI

---

## Estructura del proyecto

```text
/frontend
    src/analisis.ts  → motor de detección de patrones clínicos (tiempo real, en el navegador)
    src/main.ts      → orquestación general, eventos y renderizado
    src/ia.ts        → cliente tipado de /api/interpret y render de la salida estructurada
    src/ui.ts        → navegación por tabs, gestos, sincronización móvil
    src/auth.ts      → modal de autenticación y validación en tiempo real
    src/papers.ts    → búsqueda y paginación de literatura científica
    src/pdf-parser.ts→ extracción de valores desde PDF en el navegador
    src/lab-import.ts→ importación desde analizadores (cola de muestras y emparejado)
    src/panel-vacio.ts→ estado vacío de los paneles de exámenes (escritorio)
    src/form-inject.ts→ base común de los importadores (PDF y analizador)
    tests/           → suite de regresión del motor y del parser de PDF (Vitest)

/backend
    app/main.py      → app FastAPI, CORS, cabeceras, montaje de estáticos
    app/config.py    → configuración por variables de entorno (sin secretos por defecto)
    app/schemas.py   → esquemas Pydantic: petición y salida clínica validada
    app/motor/       → suelo de seguridad recalculado en servidor (rangos y gravedad)
    app/ai/          → rutas de modelo (hf_space, medgemma/Ollama, claude), prompt y citas
    app/rag/         → ingesta e índice LanceDB + recuperación híbrida con reranking
    app/routers/     → interpret, auth, papers, lab
    app/security/    → sesión firmada, CSRF, rate limiting, cabeceras, auth de dispositivos
    tests/           → pruebas de esquema, prompt, RAG, citas, API y seguridad

/evals
    dataset/         → casos dorados (split dev/test + firma veterinaria)
    run_evals.py     → puerta de CI: métricas deterministas + juez clínico
    judge/           → juez LLM local y gratuito (Ollama) o Claude
    run_ragas.py     → groundedness del RAG (faithfulness, precisión/recall de contexto)

/bridge              → puente local que lee analizadores (ASTM/HL7) en la LAN de la clínica

/css
    styles.css       → estilos completos (tema claro/oscuro, grid, mobile)

/data
    valores_referencia.json → rangos de referencia por especie y analito
    ajustes_clinicos.json   → umbrales de gravedad, cortes clínicos, ajustes por edad/raza e IRIS
                              (única fuente de verdad: la leen los DOS motores)
    alteraciones.json       → descripciones clínicas de los patrones
    lab_mapeos/             → códigos de prueba → analito canónico, por fabricante
    rag_alcance.json        → qué páginas del corpus entran y con qué especie

/assets
    /fonts           → Inter y JetBrains Mono (carga local)
    /icons           → iconos SVG de la interfaz
    /lib/pdfjs       → librería PDF.js en local

/instance            → índice RAG y BD de usuarios si no hay volumen persistente; FUERA de la
                       raíz servida (gitignored)
index.html           → SPA principal (carga el bundle de frontend/)
Dockerfile           → imagen de despliegue (frontend + backend + índice RAG horneado)
```

---

## Flujo de la aplicación

```text
[ Formulario de valores ]
        |
        v
   analisis.ts
   (deteccion de patrones en tiempo real, sin servidor)
        |
        v
[ UI: campos coloreados + tarjetas de patron ]
        |
        v
  Usuario pulsa "Analisis IA"
        |
        v
   ia.ts  → POST /api/interpret  (sesion + CSRF + rate limit)
        |
        v
   Backend: recuperacion RAG (LanceDB) + prompt endurecido
        |
      ┌─┴───────────────┬────────────────┐
      v                 v                v
 HF Space           Ollama local      Claude
 (prosa)            (estructurada)    (estructurada)
      |                 |                |
      └────────┬────────┴────────────────┘
               v
   Validacion Pydantic + atribucion de fuentes
               |
               v
   [ Interpretacion estructurada en pantalla ]
   hallazgos · diferenciales con citas · derivacion
```

El prompt ya no se construye en el navegador: vive en el servidor (`app/ai/prompt.py`), que
es también quien decide la ruta de modelo y quien valida la respuesta antes de devolverla.

---

## Instalacion

### 1. Requisitos

* Node 22+ (frontend Vite + TypeScript)
* Python 3.12 y [uv](https://docs.astral.sh/uv/) (backend FastAPI)
* Opcional: [Ollama](https://ollama.com) para la ruta de IA auto-alojada

### 2. Variables de entorno

Copiar `backend/.env.example` a `backend/.env` y rellenarlo. Nunca va bajo la raiz servida
ni al repositorio; en HF Spaces se usan los *Secrets* del Space en su lugar.

### 3. Base de datos

Se crea sola al arrancar y el esquema se migra solo (`PRAGMA user_version`; ver `_MIGRACIONES`
en `backend/app/db.py`). Es SQLite, siempre fuera de la raiz servida:

* Si hay un **volumen persistente** montado en `/data`, la BD vive ahí y sobrevive a los reinicios.
* Si no, cae a `instance/morphos.db`, que en HF Spaces es **efímero**: cada reinicio borra
  cuentas, contraseñas e historial de intentos. Se avisa por log al arrancar.

Se puede forzar la ruta con `MORPHOS_DB_PATH`. **No hay soporte de MySQL/MariaDB**: existieron
variables `MORPHOS_MYSQL_*` que ningún código leía y se eliminaron.

### 4. Iniciar la aplicacion

```bash
make frontend-install && make frontend-build   # SPA → dist/
make backend-sync && make dev                  # FastAPI en http://localhost:8000
```

## Backend de IA

La ruta la decide el **servidor** (`MORPHOS_IA_BACKEND_DEFECTO`), no el navegador: asi la
eleccion de proveedor no depende del `localStorage` de cada cliente.

| Ruta                   | Como se activa                                | Salida        | Citas |
| ---------------------- | --------------------------------------------- | ------------- | ----- |
| medGemma en HF Space   | `medgemma` + `MORPHOS_HF_SPACE_URL` definida  | prosa libre   | Si, por marcador `[n]` |
| medGemma en Ollama     | `medgemma` + `MORPHOS_HF_SPACE_URL` vacia     | estructurada  | Si, por diferencial |
| Claude                 | `claude` + `MORPHOS_ANTHROPIC_API_KEY`        | estructurada  | Si, por diferencial |

En las tres, las **fuentes las construye el servidor** a partir de los fragmentos que la
recuperacion entrego de verdad; una cita que no se resuelve contra un fragmento real se
descarta antes de llegar al veterinario.

### Ruta auto-alojada con Ollama

Es la unica ruta que escala para una herramienta gratuita: el Space con ZeroGPU rinde del
orden de **4 analisis por dolar** de cuota, mientras que en local el coste marginal por
analisis es la electricidad. Ademas da salida **estructurada** (el Space solo puede devolver
prosa), que es lo que permite diferenciales con probabilidad, evidencia y citas por separado.

```bash
# 1. Instalar y arrancar Ollama
brew install ollama            # o https://ollama.com/download
ollama serve

# 2. Descargar el modelo clinico
ollama pull medgemma           # ajusta la etiqueta a la variante que uses

# 3. Apuntar el backend a Ollama vaciando la URL del Space
#    (en backend/.env)
MORPHOS_IA_BACKEND_DEFECTO=medgemma
MORPHOS_HF_SPACE_URL=
MORPHOS_MEDGEMMA_BASE_URL=http://localhost:11434
MORPHOS_MEDGEMMA_MODEL=medgemma:latest
```

Notas de despliegue:

* **Hardware**: una variante de 4B corre en CPU con paciencia; para tiempos de respuesta
  aceptables con imagenes de citologia conviene GPU con 8 GB+ de VRAM.
* **En red**: si Ollama corre en otra maquina de la LAN, arrancalo con
  `OLLAMA_HOST=0.0.0.0 ollama serve` y pon esa IP en `MORPHOS_MEDGEMMA_BASE_URL`. Ollama no
  tiene autenticacion: dejalo detras del firewall de la clinica, nunca expuesto a internet.
* **Contrato identico**: el cliente (`app/ai/medgemma.py`) pasa el JSON Schema de
  `InterpretacionClinica` en el campo `format`, asi que la respuesta valida contra Pydantic
  sin ninguna limpieza por regex.
* **Sin red durante la inferencia**: los datos del paciente no salen de la clinica, que es
  el argumento de privacidad de la herramienta.

El mismo Ollama sirve ademas de **juez gratuito** para las evals (ver `evals/README.md`).

---

## Motor de deteccion de patrones

`frontend/src/analisis.ts` compara cada valor ingresado contra los rangos de referencia del JSON,
ajustados dinamicamente segun:

* **Especie**: canino / felino
* **Edad**: cachorro, adulto, senior, geriatrico (p. ej. el fosforo del cachorro, sin el cual todo
  animal en crecimiento sale hiperfosforemico)
* **Raza**: lebreles —galgo, greyhound, whippet, saluki…— en serie roja, plaquetas, creatinina y
  T4 (sin ese ajuste, ~90 % de los galgos sanos salen hipotiroideos); razas asiaticas (shiba,
  akita, chow, shar pei) en **VCM**, que es microcitosis fisiologica **sin** anemia; Maine Coon y
  Birman en felinos
* **Sexo**: sin ajustes. El que habia —mas tolerancia a creatinina en el gato macho— se **retiro**
  por no tener respaldo en el corpus: toleraba un 15 % mas justo en la poblacion con mas ERC

La gravedad se mide como desviacion relativa al ancho del rango, **salvo** donde esa regla no sabe
expresar la clinica: hematocrito y plaquetas por lo bajo, y creatinina, SDMA y UP/C por lo alto,
tienen cortes explicitos (con rango 24-45, un gato necesitaria un hematocrito negativo para llegar
a «grave»). Con los hallazgos se identifican mas de 50 patrones clinicos (anemias, hepatopatias,
nefropatia, alteraciones endocrinas, electrolitos, entre otros) y el estadiaje IRIS de ERC.

**Las reglas clinicas son datos, no codigo.** Umbrales, cortes, limites de edad, factores por raza
y cortes IRIS viven en `data/ajustes_clinicos.json`, con su procedencia bibliografica, y los leen
por igual el motor del navegador y el del servidor. Un veterinario puede revisarlos y ajustarlos
sin desarrollador ni build.

El motor está congelado por una suite de regresión (`frontend/tests`, Vitest) que se ejecuta
con `make frontend-test`. Es la red que permite tocar el resto del stack sin cambiar
silenciosamente un criterio clínico.

---

## Calidad y evaluación

La parte clínica no se valida "a ojo": hay una puerta de CI que bloquea el merge ante una
regresión (`.github/workflows/evals.yml`).

```bash
make frontend-test    # regresión del motor determinista
make backend-test     # pruebas del backend (esquemas, prompt, RAG, citas, seguridad)
make evals            # evals clínicas: puerta con tolerancia cero a fallos de seguridad
make revision         # hoja de revisión veterinaria de los casos aún sin firmar
```

Las evals miden recall de diferenciales, cobertura de hallazgos, acierto de derivación,
idioma y seguridad, y añaden una rúbrica de juez LLM que corre **en local y gratis** sobre
Ollama. El dataset separa un split reservado y sólo cuenta para la puerta los casos con
validación veterinaria firmada. Detalle en `evals/README.md`.

---

## Seguridad aplicada

* Sesiones firmadas con cookie `HttpOnly` / `SameSite` / `Secure`, y CSRF de doble token
* Contraseñas hasheadas con **scrypt** y comparación en tiempo constante
* Consultas parametrizadas (sin interpolacion directa)
* `/api/interpret` exige sesión: no hay acceso anónimo al modelo. `/api/papers` **no** la exige
  a propósito (búsqueda en PubMed, ni sensible ni cara); lo acota el rate limiting
* Rate limiting por IP **y por usuario** (la cuota de GPU es compartida entre veterinarios)
* CORS restringido a orígenes conocidos, nunca `*`
* Cabeceras de seguridad: CSP estricta, HSTS en producción, `nosniff`, `frame-ancestors none`
* Claves de API sólo en el servidor (`backend/.env` o secrets del Space), jamás en el cliente
* BD de usuarios e índice RAG **fuera de la raíz servida** (`instance/`), no descargables
* Validación en servidor de las imágenes de citología (número, tipo MIME y tamaño)
* Texto del modelo y de APIs externas insertado con escapado, sin `eval` ni `document.write`
* **Alta de cuentas cerrada** por lista blanca de emails (`MORPHOS_REGISTRO_ALLOWLIST`): una
  cuenta alcanza el modelo, así que el alta abierta era una autorización de gasto para cualquiera
* **Resultados de analizador aislados por clínica**: el tenant lo pone el servidor —de la API key
  del dispositivo al ingerir, de la cookie firmada al leer—, nunca el cuerpo de la petición. Una
  muestra de otra clínica responde 404, no 403
* **Sesiones revocables**: el logout invalida el token de verdad (no sólo borra la cookie) y
  `/api/auth/logout-todas` cierra la sesión en todos los dispositivos
* **El suelo de seguridad se recalcula en el servidor**: los hallazgos y su gravedad se derivan de
  los valores crudos (`app/motor/gravedad.py`), así que omitir o falsear el veredicto del cliente
  ya no relaja la derivación obligatoria. Lo que afirma el navegador sólo puede endurecerla
* Rate limiting consciente del proxy inverso (`MORPHOS_PROXY_SALTOS_CONFIABLES`): detrás de un
  proxy, `request.client.host` es el proxy y los límites «por IP» serían en realidad globales

---

## Conceptos del curso aplicados

* HTML5 semantico
* CSS personalizado: variables, fuentes fluidas, grid, flexbox, media queries, temas claro/oscuro
* JavaScript/TypeScript: ES Modules, `fetch`, `async/await`, eventos, DOM API, tipos estrictos
* Python: FastAPI, Pydantic, `async`/`await`, gestión de dependencias con uv
* Bases de datos: creacion de tablas, consultas con parametros, indices unicos y migraciones versionadas (SQLite)

---

## Mejoras futuras

* Implementación de dashboard de administrador
* Desarrollo de extensión de navegador para captar datos del DOM de PIMS y obtener los datos de los analisis de los pacientes con intervención mínima del usuario
* Desarrollo de mobile app dedicada
* Integración con PIMS más utilizados en veterinaria
* Filtrado del campo «signos clínicos» contra una lista de términos clínicos permitidos, para que
  ni datos identificativos ni texto arbitrario lleguen al modelo
* Rankeo de papers basado en confiabilidad y relevancia
* Creación de Dataset específico para citologías de animales
* Hosting del modelo en VPS serverless para finetuning y menor latencia
* Ampliación de la base de alteraciones
* Parseo con OCR de fotografías de analíticas
* Incluir resultados de gasometría, coprologías, informes de histopatologías y tiempos de coagulación

## Retos

* Por la diversidad de unidades de medición que utilizan los diferentes fabricantes de equipos de laboratorio se incorporó una detección de unidades para su conversión y normalización
* El modelado del output de la I.A requirió muchísimas iteraciones de formateo del prompt y harness para evitar alucinaciones o que envíara su proceso de pensamiento, aún requiere de mucho trabajo extra de refinamiento
* Inicialmente quería usar proveedores de inferencia gratuita de medGemma (como featherless AI) pero fallaban continuamente, por eso decidí optar por hostear al modelo en Zero GPU de HF con la subscripción pro para la prueba de concepto
* Incluir las librería de parseo de pdf y las fuentes en el directorio del proyecto con la intención de reducir dependencias externas estaba generando problemas con las métricas de velocidad de lighthouse que no lograba solucionar. Claude planteó implementación de caché en htacesss y pre carga de las fuentes, lo cual llevó la puntuación de 60 a 90/100 sin mayores cambios estructurales
* Lograr una interfaz limpia y entendible requirío de muchos intentos hasta lograr un flujo de trabajo intuitivo y accsesible con la mínima friccion posible para los usuarios
* La API de PubMed sólo admite input en inglés, así que implementó un objeto con traducciones de los patrones clínicos más comúnes para poder realizar las peticiones

## Notas

* La base de datos se crea sola al arrancar; no hay ningún script de instalación que borrar
* El parser de PDF funciona completamente en el navegador (sin subida al servidor) para evitar enviar información privada al modelo de IA.
* La busqueda de literatura filtra los patrones detectados, los traduce al ingles y consulta PubMed via `esearch` + `esummary`
* El corpus de libros con licencia y el índice RAG nunca entran en git: se distribuyen por
  datasets privados del Hub (`make fetch-index`) y se hornean en la imagen de despliegue
