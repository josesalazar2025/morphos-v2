"""Configuración del puente (variables MORPHOS_BRIDGE_* o bridge/.env).

Dos formas de declarar equipos:
  1. Multi-equipo: MORPHOS_BRIDGE_INSTRUMENTOS = lista JSON de instrumentos (recomendado si hay
     varias máquinas).
  2. Un solo equipo: los campos MLLP_* / SERIE_* de conveniencia (se pliegan a la lista).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Instrumento(BaseModel):
    """Un analizador conectado. `fabricante` selecciona el parser y la tabla de mapeo del backend."""

    fabricante: str = ""  # abaxis | horiba | bionote (vacío = genérico según transporte)
    transporte: Literal["mllp", "serie"] = "mllp"
    instrumento_id: str = "analizador-1"
    # MLLP (HL7, p. ej. Bionote)
    host: str = "0.0.0.0"
    puerto: int = 2575
    # Serie (ASTM, Abaxis/Horiba)
    serie_puerto: str = "/dev/ttyUSB0"
    baudios: int = 9600


class BridgeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MORPHOS_BRIDGE_", env_file=".env", extra="ignore")

    # Destino: la API de Morphos (misma clave que MORPHOS_LAB_API_KEYS en el backend).
    morphos_url: str = Field(default="http://localhost:8000")
    api_key: str = Field(default="")
    verify_tls: bool = Field(default=True)  # NO desactivar en producción
    spool_dir: str = Field(default="spool")
    spool_reintento_s: int = Field(default=60)  # cada cuánto re-drenar el spool pendiente

    # --- Multi-equipo (recomendado) ---
    instrumentos: list[Instrumento] = Field(default_factory=list)

    # --- Un solo equipo (conveniencia; se ignora si `instrumentos` está poblado) ---
    fabricante: str = Field(default="")
    instrumento_id: str = Field(default="analizador-1")
    mllp_habilitado: bool = Field(default=False)
    mllp_host: str = Field(default="0.0.0.0")
    mllp_puerto: int = Field(default=2575)
    serie_habilitado: bool = Field(default=False)
    serie_puerto: str = Field(default="/dev/ttyUSB0")
    serie_baudios: int = Field(default=9600)

    def resolver_instrumentos(self) -> list[Instrumento]:
        """Lista efectiva de equipos: `instrumentos` si se declaró, o los construidos desde los
        campos de conveniencia."""
        if self.instrumentos:
            return self.instrumentos
        lista: list[Instrumento] = []
        if self.mllp_habilitado:
            lista.append(
                Instrumento(
                    fabricante=self.fabricante,
                    transporte="mllp",
                    instrumento_id=self.instrumento_id,
                    host=self.mllp_host,
                    puerto=self.mllp_puerto,
                )
            )
        if self.serie_habilitado:
            lista.append(
                Instrumento(
                    fabricante=self.fabricante,
                    transporte="serie",
                    instrumento_id=self.instrumento_id,
                    serie_puerto=self.serie_puerto,
                    baudios=self.serie_baudios,
                )
            )
        return lista
