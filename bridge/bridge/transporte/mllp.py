"""Transporte MLLP (Minimal Lower Layer Protocol) para HL7 v2 sobre TCP.

Enmarcado: <VT> mensaje <FS><CR>. Escucha en un puerto (el analizador Bionote se configura
para enviar aquí) y entrega cada mensaje HL7 como str. Responde un ACK (MSH+MSA) porque
muchos analizadores esperan confirmación antes de enviar el siguiente mensaje.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

log = logging.getLogger("bridge.mllp")

VT = 0x0B  # start block
FS = 0x1C  # end block
CR = 0x0D


def _ack(mensaje: str) -> bytes:
    """Construye un ACK HL7 mínimo a partir de la cabecera MSH del mensaje recibido."""
    control = ""
    campos_msh = mensaje.split("\r", 1)[0].split("|")
    if len(campos_msh) > 9:
        control = campos_msh[9]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    msh = f"MSH|^~\\&|Morphos|Bridge|||{ts}||ACK|{control}|P|2.6"
    msa = f"MSA|AA|{control}"
    cuerpo = (msh + "\r" + msa + "\r").encode("utf-8")
    return bytes([VT]) + cuerpo + bytes([FS, CR])


async def servir_mllp(host: str, puerto: int, al_recibir: Callable[[str], Awaitable[None]]) -> None:
    async def _cliente(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        par = writer.get_extra_info("peername")
        log.info("conexión MLLP de %s", par)
        buffer = bytearray()
        try:
            while True:
                chunk = await reader.read(8192)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    inicio = buffer.find(VT)
                    fin = buffer.find(FS, inicio + 1) if inicio != -1 else -1
                    if inicio == -1 or fin == -1:
                        break
                    mensaje = bytes(buffer[inicio + 1 : fin]).decode("utf-8", "replace")
                    del buffer[: fin + 2]  # descarta hasta FS+CR
                    try:
                        await al_recibir(mensaje)
                    except Exception:  # noqa: BLE001 — no tumbar la conexión por un mensaje malo
                        log.exception("fallo procesando mensaje MLLP")
                    writer.write(_ack(mensaje))
                    await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(_cliente, host, puerto)
    log.info("MLLP escuchando en %s:%s", host, puerto)
    async with server:
        await server.serve_forever()
