"""Orquestación de la interpretación clínica.

Flujo: petición → recuperación RAG (si hay índice) → construcción de prompt endurecido
→ llamada al modelo elegido (medGemma/Claude) con salida estructurada → validación.
Un reintento ante fallo de validación; si persiste, error tipado (nunca texto crudo).
"""

from __future__ import annotations

import logging

from ..config import obtener_config
from ..rag.retriever import construir_consulta, recuperar
from ..schemas import InterpretacionClinica, PeticionInterpretacion, RespuestaInterpretacion
from .base import ClienteModelo, ErrorModelo
from .citas import aplicar_atribucion
from .prompt import SISTEMA, SISTEMA_PROSA, construir_mensaje_usuario

log = logging.getLogger("morphos.ia")


def _crear_cliente(backend: str) -> ClienteModelo:
    if backend == "claude":
        from .claude import ClaudeClient

        return ClaudeClient()

    # Ruta 'medgemma': por defecto el HF Space (donde vive medGemma); si no hay Space
    # configurado, cae a Ollama local.
    cfg = obtener_config()
    if cfg.hf_space_url:
        from .hf_space import HFSpaceClient

        return HFSpaceClient()
    from .medgemma import MedGemmaClient

    return MedGemmaClient()


async def interpretar(pet: PeticionInterpretacion) -> RespuestaInterpretacion:
    cfg = obtener_config()
    backend = pet.backend or cfg.ia_backend_defecto

    # 1) Recuperación RAG basada en los patrones/hallazgos del paciente (degrada a []).
    consulta = construir_consulta(
        [p.nombre for p in pet.patrones],
        [h.nombre for h in pet.hallazgos],
    )
    fragmentos = recuperar(consulta, especie=pet.paciente.especie)

    # 2) Prompt endurecido con contexto recuperado.
    mensaje = construir_mensaje_usuario(pet, fragmentos)

    # 3) Llamada al modelo con un reintento ante salida malformada.
    # El HF Space devuelve texto libre → se usa el system prompt de prosa.
    cliente = _crear_cliente(backend)
    sistema = SISTEMA_PROSA if cliente.nombre == "medgemma-hf" else SISTEMA
    resultado: InterpretacionClinica | None = None
    ultimo_error: ErrorModelo | None = None
    for intento in range(2):
        try:
            resultado = await cliente.interpretar(sistema, mensaje, pet.imagenes)
            break
        except ErrorModelo as exc:
            ultimo_error = exc
            if not exc.reintentable:
                # 429/cuota, rechazo por seguridad o configuración ausente: reintentar no puede
                # ayudar y, en el caso de la cuota, gasta otra reserva de GPU del pozo agotado.
                log.warning("Interpretación fallida sin reintento: %s", exc)
                break
            log.warning("Interpretación fallida (intento %d): %s", intento + 1, exc)

    if resultado is None:
        raise ultimo_error or ErrorModelo("Fallo desconocido de interpretación.")

    # 4) Atribución: las fuentes salen de la recuperación, no del modelo, y las citas que no
    # se resuelven contra un fragmento real se descartan. Es lo que da citas verificables
    # también en la ruta de prosa del HF Space, que no puede rellenar `citas[]`.
    resultado, fuentes = aplicar_atribucion(resultado, fragmentos)

    if backend == "claude":
        etiqueta = cfg.claude_model
    elif cliente.nombre == "medgemma-hf":
        etiqueta = "hf-space"
    else:
        etiqueta = cfg.medgemma_model

    return RespuestaInterpretacion(
        resultado=resultado,
        modelo=f"{cliente.nombre}:{etiqueta}",
        fuentes_rag=len(fragmentos),
        fuentes=fuentes,
    )
