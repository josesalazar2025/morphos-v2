"""Modelos Pydantic: petición de interpretación y salida clínica estructurada.

La salida estructurada es la corrección central del proyecto: en vez de texto libre
que había que limpiar con regex (limpiarRespuesta en ia.js), el modelo devuelve un
objeto validado. Si no valida, se reintenta o se devuelve un error tipado; nunca se
entrega texto sin parsear al cliente.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- Entrada ---

class Direccion(StrEnum):
    alto = "alto"
    bajo = "bajo"


class Gravedad(StrEnum):
    leve = "leve"
    moderado = "moderado"
    grave = "grave"


class PacienteEntrada(BaseModel):
    especie: Literal["canino", "felino"] | None = None
    raza: str | None = None
    edad_meses: float | None = None
    sexo: str | None = None


class HallazgoEntrada(BaseModel):
    clave: str
    nombre: str
    valor: float
    unidad: str = ""
    direccion: Direccion
    gravedad: Gravedad


class PatronEntrada(BaseModel):
    nombre: str
    descripcion: str
    gravedad: Gravedad
    parametros: list[str] = Field(default_factory=list)


class PeticionInterpretacion(BaseModel):
    """Lo que el frontend envía a /api/interpret.

    hallazgos/patrones vienen del motor determinista analisis.ts, ya calculados en
    cliente. El backend NO recalcula, sólo enriquece con RAG y llama al modelo.
    """

    paciente: PacienteEntrada
    hallazgos: list[HallazgoEntrada] = Field(default_factory=list)
    patrones: list[PatronEntrada] = Field(default_factory=list)
    signos_clinicos: str = Field(default="", max_length=2000)
    imagenes: list[str] = Field(default_factory=list)  # data URLs de citología
    backend: Literal["medgemma", "claude"] = "medgemma"

    @field_validator("imagenes")
    @classmethod
    def _limitar_imagenes(cls, v: list[str]) -> list[str]:
        return v[:4]


# --- Salida estructurada del modelo ---

class Diferencial(BaseModel):
    nombre: str = Field(description="Diagnóstico diferencial")
    probabilidad: Literal["alta", "media", "baja"]
    evidencia: list[str] = Field(
        default_factory=list,
        description="Hallazgos del paciente que apoyan este diferencial",
    )
    citas: list[str] = Field(
        default_factory=list,
        description="Referencias a la literatura recuperada (libro, edición, página)",
    )


class HallazgoClave(BaseModel):
    analito: str
    direccion: Direccion
    gravedad: Gravedad
    comentario: str = ""


class InterpretacionClinica(BaseModel):
    """Salida validada que se entrega al cliente. Reemplaza el texto libre + limpieza."""

    interpretacion: str = Field(description="Resumen clínico integrado, en español")
    hallazgos_clave: list[HallazgoClave] = Field(default_factory=list)
    diferenciales: list[Diferencial] = Field(default_factory=list)
    siguientes_pruebas: list[str] = Field(default_factory=list)
    confianza: Literal["alta", "media", "baja"] = "media"
    requiere_derivacion: bool = Field(
        default=True,
        description="Marca de seguridad: el caso requiere valoración presencial del veterinario",
    )
    idioma: Literal["es"] = "es"

    @field_validator("interpretacion")
    @classmethod
    def _no_vacia(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("interpretacion vacía")
        return v.strip()


class RespuestaInterpretacion(BaseModel):
    resultado: InterpretacionClinica
    modelo: str
    fuentes_rag: int = 0


class ErrorRespuesta(BaseModel):
    error: str
    detalle: str | None = None
