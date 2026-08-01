"""Orquestación de la interpretación clínica.

Flujo: petición → recuperación RAG (si hay índice) → construcción de prompt endurecido
→ llamada al modelo elegido (medGemma/Claude) con salida estructurada → validación.
Un reintento ante fallo de validación; si persiste, error tipado (nunca texto crudo).
"""

from __future__ import annotations

import logging

from ..config import obtener_config
from ..rag.retriever import (
    Fragmento,
    construir_consulta,
    construir_consultas,
    recuperar,
    recuperar_multi,
)
from ..schemas import (
    Gravedad,
    InterpretacionClinica,
    PeticionInterpretacion,
    RespuestaInterpretacion,
)
from .alcance import motivo_fuera_de_alcance, respuesta_fuera_de_alcance
from .base import ClienteModelo, ErrorModelo
from .citas import aplicar_atribucion
from .coherencia import descartar_fabricados
from .prescripcion import detectar_prescripcion, encuadrar
from .prompt import (
    LARGO_FRAGMENTO_PROMPT,
    SISTEMA,
    SISTEMA_PROSA,
    construir_mensaje_usuario,
)

log = logging.getLogger("morphos.ia")


def recortar_a_presupuesto(fragmentos: list[Fragmento], max_chars: int) -> list[Fragmento]:
    """Los fragmentos mejor rankeados que caben en `max_chars` de literatura.

    Recortar en número de fragmentos completos, y no a media frase, mantiene cada cita
    verificable: un fragmento partido puede cambiar de sentido. Siempre se deja al menos uno
    —mejor poca literatura que ninguna— aunque exceda el presupuesto.
    """
    if max_chars <= 0:
        return fragmentos
    acumulado = 0
    cabidos: list[Fragmento] = []
    for fragmento in fragmentos:
        coste = len(fragmento.texto[:LARGO_FRAGMENTO_PROMPT])
        if cabidos and acumulado + coste > max_chars:
            break
        cabidos.append(fragmento)
        acumulado += coste
    return cabidos


def estructura_insuficiente(
    resultado: InterpretacionClinica, pet: PeticionInterpretacion
) -> str | None:
    """Nombre del campo que el modelo dejó vacío debiendo rellenarlo, o None.

    No se puede exigir a ciegas: en un panel normal es CORRECTO no listar hallazgos ni
    diferenciales. Lo que no vale es que un caso con alteraciones detectadas por el motor se
    resuelva con prosa y los campos estructurados en blanco, que es lo que hacía qwen2.5:7b.
    """
    if pet.hallazgos and not resultado.hallazgos_clave:
        return "hallazgos_clave"
    if (pet.hallazgos or pet.patrones) and not resultado.diferenciales:
        return "diferenciales"
    return None


def _derivacion_obligatoria(pet: PeticionInterpretacion) -> bool:
    """True si el motor determinista ve algo grave, sea cual sea la opinión del modelo."""
    return any(h.gravedad == Gravedad.grave for h in pet.hallazgos) or any(
        p.gravedad == Gravedad.grave for p in pet.patrones
    )


def _derivacion_en_ruta_de_prosa(pet: PeticionInterpretacion) -> bool:
    """Valor de `requiere_derivacion` para los backends que sólo devuelven prosa.

    Ahí el campo no lo escribe el modelo —el cliente construye el objeto con el default del
    esquema—, así que era CONSTANTE a true. Medido el 2026-07-31: en `normal-canino` eso
    contradecía al propio texto («los valores se encuentran dentro de los límites de
    referencia») y el juez lo penalizó como incoherencia con riesgo de alarma injustificada
    (seguridad 0.50). Peor aún, `acierto_derivacion` estaba midiendo este default.

    Criterio: si el motor determinista no marcó NADA —ni un hallazgo fuera de rango ni un
    patrón—, no hay nada que derivar. En cuanto hay algo, se deriva: en una herramienta de
    apoyo diagnóstico, el lado conservador es el que pide ojos de veterinario. El suelo de
    `_derivacion_obligatoria` sigue por encima para los casos graves.
    """
    return bool(pet.hallazgos or pet.patrones)


def _crear_cliente(backend: str, modelo_local: str | None = None) -> ClienteModelo:
    if backend == "claude":
        from .claude import ClaudeClient

        return ClaudeClient()

    cfg = obtener_config()

    # Modelo local elegido por el usuario. El nombre ya viene validado contra la lista blanca
    # por `PeticionInterpretacion`; aquí se revalida porque este camino también lo usan las
    # evals, que pueden construir la petición de otras formas. Tiene prioridad sobre el Space:
    # elegir un modelo en la UI y que el servidor llamara igualmente al Space sería mentirle al
    # usuario. Todo lo demás —RAG, prompt endurecido, atribución y suelos de seguridad— es
    # idéntico, porque vive en este servicio y no en el cliente.
    if modelo_local:
        permitidos = cfg.modelos_locales_permitidos()
        if modelo_local not in permitidos:
            raise ErrorModelo(
                f"Modelo local no permitido: {modelo_local!r}.", reintentable=False
            )
        from .medgemma import MedGemmaClient

        return MedGemmaClient(modelo_local, prosa=permitidos[modelo_local])

    # Ruta 'medgemma' por defecto: el HF Space (donde vive medGemma); si no hay Space
    # configurado, cae a Ollama local.
    if cfg.hf_space_url:
        from .hf_space import HFSpaceClient

        return HFSpaceClient()
    from .medgemma import MedGemmaClient

    return MedGemmaClient()


async def interpretar(pet: PeticionInterpretacion) -> RespuestaInterpretacion:
    cfg = obtener_config()
    backend = pet.backend or cfg.ia_backend_defecto

    # 0) Guarda de alcance: determinista y ANTES de gastar una llamada al modelo. Mismo patrón
    # que `_derivacion_obligatoria`, por el mismo motivo: los tres modelos evaluados el
    # 2026-07-28 fallaron en abierto ante un paciente humano y fabricaron clínica sobre él.
    if (motivo := motivo_fuera_de_alcance(pet)) is not None:
        log.warning("Petición fuera de alcance (%s); no se llama al modelo.", motivo)
        return RespuestaInterpretacion(
            resultado=respuesta_fuera_de_alcance(motivo),
            modelo="guarda:alcance",
            fuentes_rag=0,
            fuentes=[],
        )

    # 1) Recuperación RAG basada en los patrones/hallazgos del paciente (degrada a []).
    # Con `rag_multiconsulta`, una consulta por patrón fusionadas con RRF en vez de una sola
    # cadena concatenada; OFF por defecto hasta que un juez LLM confirme la mejora (ver
    # config.py: el juez heurístico disponible la puntúa peor y está sesgado a favor de la
    # consulta concatenada).
    nombres_patrones = [p.nombre for p in pet.patrones]
    nombres_hallazgos = [h.nombre for h in pet.hallazgos]
    if cfg.rag_multiconsulta:
        fragmentos = recuperar_multi(
            construir_consultas(nombres_patrones, nombres_hallazgos),
            especie=pet.paciente.especie,
        )
    else:
        fragmentos = recuperar(
            construir_consulta(nombres_patrones, nombres_hallazgos),
            especie=pet.paciente.especie,
        )

    # 2-3) Prompt endurecido con contexto recuperado y llamada al modelo, con un reintento
    # ante salida malformada. El HF Space devuelve texto libre → system prompt de prosa.
    cliente = _crear_cliente(backend, pet.modelo_local)
    es_prosa = cliente.prosa
    sistema = SISTEMA_PROSA if es_prosa else SISTEMA
    # Los fragmentos ENVIADOS pueden ser menos que los recuperados —por presupuesto de prompt
    # aquí, o por el recorte del reintento más abajo— y son ésos, no los recuperados, los que
    # el modelo puede citar. Sólo la ruta de prosa paga el razonamiento descartado del modelo
    # con el mismo presupuesto que la respuesta; ver rag_max_chars_prompt en config.py.
    enviados = recortar_a_presupuesto(fragmentos, cfg.rag_max_chars_prompt) if es_prosa else fragmentos
    if len(enviados) < len(fragmentos):
        log.info(
            "Literatura recortada a %d de %d fragmentos por presupuesto de prompt.",
            len(enviados), len(fragmentos),
        )
    resultado: InterpretacionClinica | None = None
    ultimo_error: ErrorModelo | None = None
    for intento in range(2):
        mensaje = construir_mensaje_usuario(pet, enviados)
        try:
            resultado = await cliente.interpretar(sistema, mensaje, pet.imagenes)
            # La ruta de prosa no puede rellenar los campos estructurados; el resto sí, y un
            # JSON válido con los diferenciales vacíos deja al veterinario sin lo que vino a
            # buscar. Se trata como salida malformada: se vuelve a muestrear.
            vacio = None if es_prosa else estructura_insuficiente(resultado, pet)
            if vacio:
                resultado = None
                raise ErrorModelo(f"El modelo dejó '{vacio}' vacío pese a haber hallazgos.")
            break
        except ErrorModelo as exc:
            ultimo_error = exc
            if not exc.reintentable:
                # 429/cuota, rechazo por seguridad o configuración ausente: reintentar no puede
                # ayudar y, en el caso de la cuota, gasta otra reserva de GPU del pozo agotado.
                log.warning("Interpretación fallida sin reintento: %s", exc)
                break
            if exc.truncado and enviados:
                # El Space reparte un único presupuesto de 2048 tokens entre el razonamiento
                # que descarta y la respuesta. La generación es voraz (greedy), así que repetir
                # el mismo prompt devuelve el mismo recorte y gasta otra reserva de GPU para
                # nada: hay que cambiar la entrada. Menos literatura acorta el razonamiento y
                # deja más presupuesto para la respuesta.
                enviados = enviados[: max(1, len(enviados) // 3)]
                log.warning(
                    "Respuesta truncada; se reintenta con %d fragmento(s) de literatura.",
                    len(enviados),
                )
            log.warning("Interpretación fallida (intento %d): %s", intento + 1, exc)

    if resultado is None:
        raise ultimo_error or ErrorModelo("Fallo desconocido de interpretación.")

    # 4) Atribución: las fuentes salen de la recuperación, no del modelo, y las citas que no
    # se resuelven contra un fragmento real se descartan. Es lo que da citas verificables
    # también en la ruta de prosa del HF Space, que no puede rellenar `citas[]`.
    resultado, fuentes = aplicar_atribucion(resultado, enviados)

    # 4.5) En la ruta de prosa el modelo no ha podido opinar sobre `requiere_derivacion`: lo
    # decide el motor determinista en su lugar. Antes quedaba el default del esquema (true).
    # El suelo es de TODAS las rutas, no sólo de la prosa. La ruta estructurada devolvía la
    # decisión al modelo y medGemma la usó mal: el 2026-08-01, con salida estructurada,
    # `acierto_derivacion` cayó de 1.00 a 0.75 y aparecieron 4 violaciones de seguridad del
    # juez, todas en casos donde el modelo puso `false` sin haber ningún hallazgo `grave` que
    # disparara `_derivacion_obligatoria` — anemia moderada con melena, hipertiroidismo felino
    # geriátrico y panhipoproteinemia con ascitis. Si el motor determinista vio algo, se deriva.
    if _derivacion_en_ruta_de_prosa(pet):
        resultado.requiere_derivacion = True
    elif es_prosa:
        # Panel sin alteraciones: en prosa el modelo no puede opinar, así que se dice que no.
        resultado.requiere_derivacion = False

    # 4.6) Coherencia: un hallazgo estructurado sobre un analito que nadie envió es una
    # invención con formato de dato. Se descarta antes de que llegue a la tarjeta clínica.
    resultado = descartar_fabricados(resultado, pet)

    # 4.7) Guarda de prescripción. El modelo no debe indicar tratamientos; si aun así lo hace,
    # no se le borra el texto (mutilar prosa clínica es peor) sino que se antepone el encuadre
    # que faltaba y se fuerza la derivación. Medido el 2026-07-31: sin esto, una recomendación
    # de insulina en un paciente hipopotasémico pasó como buena.
    if (frases := detectar_prescripcion(resultado.interpretacion)):
        log.warning("Lenguaje prescriptivo en la salida (%s); se encuadra.", "; ".join(frases[:3]))
        resultado.interpretacion = encuadrar(resultado.interpretacion)
        resultado.requiere_derivacion = True

    # 5) Suelo de seguridad. `requiere_derivacion` es una marca clínica, no una opinión: si el
    # motor determinista ve algo grave, se deriva aunque el modelo diga que no. Medido: un 7B
    # general marcó `false` en una ERC felina avanzada (creat 4.8, BUN 68, isostenuria). Con
    # esto ese fallo es imposible por construcción, venga el modelo que venga.
    if _derivacion_obligatoria(pet) and not resultado.requiere_derivacion:
        log.warning("El modelo no marcó derivación con hallazgos graves; se fuerza.")
        resultado.requiere_derivacion = True

    # La etiqueta sale del propio cliente y no de la configuración: con un modelo elegido en la
    # UI, `cfg.medgemma_model` ya no es el que respondió, y la línea "Modelo:" de la tarjeta
    # clínica es lo único que le dice al veterinario con qué se generó lo que está leyendo.
    etiqueta = cliente.modelo

    return RespuestaInterpretacion(
        resultado=resultado,
        modelo=f"{cliente.nombre}:{etiqueta}",
        fuentes_rag=len(enviados),
        fuentes=fuentes,
    )
