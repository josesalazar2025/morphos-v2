"""Modelo canónico del puente. Espeja el esquema `ResultadoAnalizador` del backend.

Los adaptadores (ASTM, HL7) producen estos objetos; `reenviador` los serializa a JSON y los
envía a POST /api/lab/ingesta. Se mantienen los códigos de prueba EN CRUDO: el mapeo a claves
canónicas ocurre en el backend (única fuente de verdad).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Observacion:
    codigo_prueba: str
    valor: str
    unidad: str = ""
    rango_referencia: Optional[str] = None
    bandera: Optional[str] = None


@dataclass
class PistasPaciente:
    nombre_mascota: Optional[str] = None
    especie_texto: Optional[str] = None
    raza: Optional[str] = None
    sexo: Optional[str] = None
    edad_texto: Optional[str] = None

    def vacio(self) -> bool:
        return not any(asdict(self).values())


@dataclass
class Resultado:
    muestra_id: str
    instrumento_id: str
    observaciones: list[Observacion]
    momento: datetime
    fabricante: Optional[str] = None
    instrumento_modelo: Optional[str] = None
    pistas_paciente: Optional[PistasPaciente] = None
    formato_origen: str = "json"  # hl7v2 | astm | json

    def payload(self) -> dict:
        """Diccionario JSON que consume POST /api/lab/ingesta."""
        cuerpo: dict = {
            "muestra_id": self.muestra_id,
            "instrumento_id": self.instrumento_id,
            "observaciones": [asdict(o) for o in self.observaciones],
            "momento": self.momento.astimezone(timezone.utc).isoformat(),
            "formato_origen": self.formato_origen,
        }
        if self.fabricante:
            cuerpo["fabricante"] = self.fabricante
        if self.instrumento_modelo:
            cuerpo["instrumento_modelo"] = self.instrumento_modelo
        if self.pistas_paciente and not self.pistas_paciente.vacio():
            cuerpo["pistas_paciente"] = {
                k: v for k, v in asdict(self.pistas_paciente).items() if v is not None
            }
        return cuerpo
