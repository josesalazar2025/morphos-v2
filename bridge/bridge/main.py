"""Supervisor del puente: arranca los transportes configurados y reenvía lo que llega.

Flujo por trama:  transporte → parser (HL7/ASTM) → normalizador → reenviador (HTTPS).
"""

from __future__ import annotations

import asyncio
import logging

from .adaptadores.registro import obtener_parser
from .config import BridgeConfig, Instrumento
from .normalizador import normalizar
from .reenviador import Reenviador
from .transporte.mllp import servir_mllp
from .transporte.serial_astm import servir_serie

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")


async def _redrenar_periodico(reenviador: Reenviador, intervalo: int) -> None:
    """Reintenta el spool pendiente cada `intervalo` s (por si Morphos estuvo caído)."""
    while True:
        await asyncio.sleep(intervalo)
        try:
            await reenviador.drenar_spool()
        except Exception:  # noqa: BLE001
            log.exception("fallo re-drenando spool")


async def _procesar(resultados, reenviador: Reenviador) -> None:
    for res in resultados:
        limpio = normalizar(res)
        if limpio is None:
            log.warning("resultado descartado (sin datos útiles)")
            continue
        await reenviador.enviar(limpio)


def _tarea_instrumento(inst: Instrumento, reenviador: Reenviador):
    """Construye la corrutina de transporte para un equipo, con su parser por fabricante."""
    parser = obtener_parser(inst.fabricante, inst.transporte)

    async def _al_recibir(trama: str) -> None:
        await _procesar(parser(trama, inst.instrumento_id), reenviador)

    if inst.transporte == "mllp":
        log.info("equipo %s (%s) → MLLP %s:%s", inst.instrumento_id, inst.fabricante or "genérico", inst.host, inst.puerto)
        return servir_mllp(inst.host, inst.puerto, _al_recibir)
    log.info("equipo %s (%s) → serie %s @ %s", inst.instrumento_id, inst.fabricante or "genérico", inst.serie_puerto, inst.baudios)
    return servir_serie(inst.serie_puerto, inst.baudios, _al_recibir)


async def ejecutar(cfg: BridgeConfig | None = None) -> None:
    cfg = cfg or BridgeConfig()
    if not cfg.api_key:
        raise SystemExit("Falta MORPHOS_BRIDGE_API_KEY (la clave de dispositivo del backend).")

    instrumentos = cfg.resolver_instrumentos()
    if not instrumentos:
        raise SystemExit(
            "No hay equipos configurados. Declara MORPHOS_BRIDGE_INSTRUMENTOS (JSON) o habilita "
            "un transporte de conveniencia (MORPHOS_BRIDGE_MLLP_HABILITADO / _SERIE_HABILITADO)."
        )

    reenviador = Reenviador(cfg.morphos_url, cfg.api_key, cfg.spool_dir, cfg.verify_tls)
    await reenviador.drenar_spool()  # reintenta lo que quedó pendiente de una ejecución previa

    tareas = [_tarea_instrumento(inst, reenviador) for inst in instrumentos]
    tareas.append(_redrenar_periodico(reenviador, cfg.spool_reintento_s))
    log.info("puente en marcha con %d equipo(s) → %s", len(instrumentos), cfg.morphos_url)
    try:
        await asyncio.gather(*tareas)
    finally:
        await reenviador.cerrar()


def main() -> None:
    asyncio.run(ejecutar())


if __name__ == "__main__":
    main()
