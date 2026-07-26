"""Transporte serie (RS-232 / USB-serial) para Abaxis/Horiba (ASTM).

Lee el puerto con pyserial en un hilo (para no bloquear el loop asyncio) y acumula bytes en
tramas ASTM. El protocolo de bajo nivel real (ENQ/ACK, STX…ETX+checksum) es específico del
equipo y se afina con capturas: aquí se acumula el texto entre bloques y se emite un mensaje
completo al ver EOT (0x04) o tras un silencio. `pyserial` se importa de forma perezosa para
que el resto del puente (parsers, tests) no dependa de él.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("bridge.serial")

STX = 0x02
ETX = 0x03
EOT = 0x04
ENQ = 0x05
ACK = 0x06


async def servir_serie(
    puerto: str,
    baudios: int,
    al_recibir: Callable[[str], Awaitable[None]],
    silencio_s: float = 2.0,
) -> None:
    import serial  # import perezoso: sólo se necesita en la máquina de la clínica

    loop = asyncio.get_running_loop()
    con = serial.Serial(puerto, baudios, timeout=0.5)
    log.info("serie abierta en %s @ %s", puerto, baudios)
    buffer = bytearray()
    ultimo = loop.time()

    try:
        while True:
            data = await loop.run_in_executor(None, con.read, 256)
            ahora = loop.time()
            if data:
                for b in data:
                    if b in (STX, ETX):
                        continue  # descarta marcas de bloque
                    if b == ENQ:
                        con.write(bytes([ACK]))  # handshake ASTM mínimo
                        continue
                    if b == EOT:
                        await _emitir(buffer, al_recibir)
                        continue
                    buffer.append(b)
                ultimo = ahora
            elif buffer and (ahora - ultimo) > silencio_s:
                await _emitir(buffer, al_recibir)
    finally:
        con.close()


async def _emitir(buffer: bytearray, al_recibir: Callable[[str], Awaitable[None]]) -> None:
    if not buffer:
        return
    texto = bytes(buffer).decode("latin-1", "replace")
    buffer.clear()
    try:
        await al_recibir(texto)
    except Exception:  # noqa: BLE001
        log.exception("fallo procesando trama serie")
