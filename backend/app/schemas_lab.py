"""Modelos Pydantic de la integración de analizadores de laboratorio.

Se mantienen fuera de schemas.py (enfocado en la interpretación IA) porque son un
contrato distinto: lo que el puente local (bridge/) envía por HTTPS a /api/lab/ingesta
tras leer un analizador, y lo que el navegador consulta en /api/lab/resultados.

Flujo: el puente normaliza la salida nativa del equipo (ASTM de Abaxis/Horiba, HL7 v2.6
PCD-01 de Bionote) a `ResultadoAnalizador` con los códigos de prueba EN CRUDO; el backend
los mapea a las claves canónicas de la app (las mismas de valores_referencia.json) en
`ResultadoMapeado`, que es lo único que el frontend inyecta en el formulario.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DireccionMensaje(StrEnum):
    """Sentido del mensaje. Sólo `entrada` (resultados) está implementado; `salida`
    (órdenes de trabajo hacia el analizador) queda reservado para no rehacer el esquema."""

    entrada = "entrada"
    salida = "salida"


class PacientePistas(BaseModel):
    """Pistas de paciente que el analizador pueda acarrear. Se usan para prerrellenar
    los campos `pt-*`, NUNCA por encima de lo que teclea el veterinario. Texto libre."""

    nombre_mascota: str | None = Field(default=None, max_length=120)
    especie_texto: str | None = Field(default=None, max_length=60)
    raza: str | None = Field(default=None, max_length=60)
    sexo: str | None = Field(default=None, max_length=30)
    edad_texto: str | None = Field(default=None, max_length=30)


class ObservacionAnalizador(BaseModel):
    """Una observación (analito) tal como la reporta el equipo, SIN mapear.

    `valor` se mantiene como string en la ingesta: los analizadores mandan `"12.3"`,
    `"<0.1"`, `">1000"`, `"NEG"`, `"+++"`… La coerción numérica y la conversión de
    unidades ocurren en la capa de mapeo (lab/mapeo.py), no aquí.
    """

    codigo_prueba: str = Field(min_length=1, max_length=64)
    valor: str = Field(max_length=128)
    unidad: str = Field(default="", max_length=32)
    rango_referencia: str | None = Field(default=None, max_length=64)
    bandera: str | None = Field(default=None, max_length=16)  # H/L/HH/A del instrumento

    @field_validator("codigo_prueba", "valor", "unidad")
    @classmethod
    def _recortar(cls, v: str) -> str:
        return v.strip()


class ResultadoAnalizador(BaseModel):
    """Una corrida de un instrumento: el envelope que envía el puente a /api/lab/ingesta."""

    muestra_id: str = Field(min_length=1, max_length=128)  # clave de emparejamiento
    instrumento_id: str = Field(min_length=1, max_length=64)
    instrumento_modelo: str | None = Field(default=None, max_length=64)
    fabricante: str | None = Field(default=None, max_length=64)  # selecciona la tabla de mapeo
    pistas_paciente: PacientePistas | None = None
    observaciones: list[ObservacionAnalizador] = Field(min_length=1, max_length=200)
    momento: datetime  # timestamp del resultado en el equipo
    recibido_en: datetime = Field(default_factory=lambda: datetime.now(UTC))
    formato_origen: Literal["hl7v2", "astm", "json", "manual"] = "json"
    direccion: DireccionMensaje = DireccionMensaje.entrada

    @field_validator("muestra_id", "instrumento_id")
    @classmethod
    def _recortar(cls, v: str) -> str:
        return v.strip()


# --- Salida mapeada (lo que consume el navegador / el frontend inyecta) ---

class ValorAnalito(BaseModel):
    """Un analito ya mapeado a la clave canónica de la app, con la unidad nativa aplicada."""

    clave: str  # clave canónica (== atributo `name` del input == clave de valores_referencia.json)
    valor: float | str  # número para analitos numéricos; string para semicuantitativos (uri-*)
    unidad: str = ""  # unidad nativa de la app tras la conversión
    valor_original: str = ""  # lo que reportó el equipo, para trazabilidad
    unidad_original: str = ""
    es_semicuantitativo: bool = False


class ResultadoMapeado(BaseModel):
    """Resultado listo para el frontend: analitos por clave canónica + no reconocidos."""

    muestra_id: str
    instrumento_id: str
    momento: datetime
    analitos: dict[str, ValorAnalito] = Field(default_factory=dict)
    paciente: PacientePistas | None = None
    no_mapeados: list[str] = Field(default_factory=list)  # códigos de prueba sin correspondencia


class RespuestaIngesta(BaseModel):
    """Respuesta al puente tras una ingesta correcta."""

    ok: bool = True
    muestra_id: str
    analitos_mapeados: int
    no_mapeados: list[str] = Field(default_factory=list)


class ResumenPendiente(BaseModel):
    """Fila de la cola de resultados recibidos (sin el detalle de analitos)."""

    muestra_id: str
    instrumento_id: str
    momento: datetime
    analitos: int
    no_mapeados: int
