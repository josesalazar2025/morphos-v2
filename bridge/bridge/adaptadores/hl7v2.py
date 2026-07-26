"""Parser HL7 v2 ORU^R01 (perfil PCD-01) — Bionote Vcheck V200 y cualquier equipo HL7.

Segmentos relevantes (campos por `|`, componentes por `^`):
  MSH = cabecera        → MSH-3 app emisora (instrumento), MSH-7 fecha/hora
  PID = paciente        → PID-5 nombre, PID-8 sexo, PID-3 id
  OBR = petición        → OBR-3 (filler order) lleva el ID de muestra/accesión
  OBX = observación     → OBX-3 `codigo^texto^sistema`, OBX-5 valor, OBX-6 unidad, OBX-8 bandera

Parseo mínimo sin dependencias externas (suficiente para PCD-01); para dialectos raros se
puede sustituir por python-hl7/hl7apy. Un mensaje = un Resultado (primer OBR). Varios OBR se
tratan como muestras distintas.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ..modelo import Observacion, PistasPaciente, Resultado


def _parsear_fecha(cadena: str) -> datetime:
    # HL7/ASTM: AAAAMMDDHHMMSS (con posible zona/decimales que ignoramos).
    digitos = re.sub(r"\D", "", cadena or "")
    for fmt, n in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(digitos) >= n:
            try:
                return datetime.strptime(digitos[:n], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def parsear_hl7(mensaje: str, instrumento_id: str = "hl7", fabricante: Optional[str] = None) -> list[Resultado]:
    segmentos = [s for s in mensaje.replace("\r\n", "\r").replace("\n", "\r").split("\r") if s.strip()]
    if not segmentos or not segmentos[0].startswith("MSH"):
        return []

    modelo: Optional[str] = None
    momento = datetime.now(timezone.utc)
    pistas = PistasPaciente()
    resultados: list[Resultado] = []
    actual: Optional[Resultado] = None

    for seg in segmentos:
        campos = seg.split("|")
        tipo = campos[0][:3].upper()

        if tipo == "MSH":
            # OJO: en MSH el campo 1 es el separador, así que MSH-3 = campos[2] y MSH-7 = campos[6].
            modelo = campos[2].split("^", 1)[0].strip() if len(campos) > 2 else None
            if len(campos) > 6 and campos[6].strip():
                momento = _parsear_fecha(campos[6])

        elif tipo == "PID":
            if len(campos) > 5 and campos[5].strip():
                pistas.nombre_mascota = campos[5].replace("^", " ").strip() or None
            if len(campos) > 8 and campos[8].strip():
                pistas.sexo = campos[8].strip()

        elif tipo == "OBR":
            muestra = ""
            if len(campos) > 3 and campos[3].strip():
                muestra = campos[3].split("^", 1)[0].strip()
            elif len(campos) > 2 and campos[2].strip():
                muestra = campos[2].split("^", 1)[0].strip()
            actual = Resultado(
                muestra_id=muestra or (pistas.nombre_mascota or "SIN-ID"),
                instrumento_id=instrumento_id,
                observaciones=[],
                momento=momento,
                fabricante=fabricante,
                instrumento_modelo=modelo,
                pistas_paciente=pistas,
                formato_origen="hl7v2",
            )
            resultados.append(actual)

        elif tipo == "OBX" and actual is not None:
            codigo = campos[3].split("^", 1)[0].strip() if len(campos) > 3 else ""
            valor = campos[5].split("^", 1)[0].strip() if len(campos) > 5 else ""
            unidad = campos[6].split("^", 1)[0].strip() if len(campos) > 6 else ""
            crudo_bandera = campos[8].strip().upper() if len(campos) > 8 else ""
            bandera = crudo_bandera if crudo_bandera and crudo_bandera != "N" else None  # 'N'=normal → None
            if codigo and valor:
                actual.observaciones.append(
                    Observacion(codigo_prueba=codigo, valor=valor, unidad=unidad, bandera=bandera)
                )

    return [r for r in resultados if r.observaciones]
