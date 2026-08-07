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

    `valores` son los datos crudos y son la fuente de verdad del servidor: con ellos recalcula
    los hallazgos y su gravedad. `hallazgos`/`patrones` siguen llegando del motor del navegador
    (`analisis.ts`), pero YA NO deciden por sí solos: valen como PISTA para el prompt y sólo
    pueden endurecer el suelo de seguridad, nunca relajarlo. `patrones` no tiene equivalente
    servidor —las 50 y pico reglas viven en el cliente— y por eso no gobierna nada crítico.
    """

    paciente: PacienteEntrada
    # Valores CRUDOS del panel ({clave: valor}). Es lo único a partir de lo cual el servidor
    # puede decidir por sí mismo: con ellos recalcula hallazgos y gravedad (`motor/gravedad.py`)
    # en vez de fiarse del veredicto del navegador.
    valores: dict[str, float] = Field(default_factory=dict, max_length=200)
    hallazgos: list[HallazgoEntrada] = Field(default_factory=list)
    patrones: list[PatronEntrada] = Field(default_factory=list)
    # Claves de TODOS los analitos que el usuario introdujo, alterados o no. `hallazgos` sólo
    # trae los que salieron fuera de rango, así que sin esto el modelo no puede distinguir «no
    # se midió» de «se midió y salió normal» y rellena el hueco: medido el 2026-08-04, medGemma
    # afirmó un leucograma con neutrofilia sobre un panel de calcio/fósforo/BUN/creatinina, y
    # llamó «trombocitopenia leve» a unas plaquetas de 190 que estaban en rango.
    # Vacío = cliente antiguo que no lo manda; el prompt omite el bloque y se comporta como antes.
    analitos_medidos: list[str] = Field(default_factory=list, max_length=200)
    signos_clinicos: str = Field(default="", max_length=2000)
    imagenes: list[str] = Field(default_factory=list)  # data URLs de citología
    backend: Literal["medgemma", "claude"] = "medgemma"
    # Modelo local elegido por el usuario en la UI. Sólo se acepta si está en la lista blanca
    # `MORPHOS_MODELOS_LOCALES`; si lo está, sustituye a la ruta que el servidor usaría por
    # defecto para 'medgemma' (Space u Ollama). None = decide el servidor, como siempre.
    modelo_local: str | None = Field(default=None, max_length=100)

    @field_validator("imagenes")
    @classmethod
    def _limitar_imagenes(cls, v: list[str]) -> list[str]:
        return v[:4]

    @field_validator("modelo_local")
    @classmethod
    def _validar_lista_blanca(cls, v: str | None) -> str | None:
        """Rechaza cualquier modelo fuera de la lista blanca.

        Se valida en el ESQUEMA y no en el router para que valga igual para las evals, que
        llaman a `interpretar()` sin pasar por HTTP, y para que FastAPI conteste 422 (error del
        cliente) en vez del 502 al que el router traduce los ErrorModelo.
        """
        if v is None:
            return None
        from .config import obtener_config

        permitidos = obtener_config().modelos_locales_permitidos()
        if v not in permitidos:
            disponibles = ", ".join(sorted(permitidos)) or "ninguno"
            raise ValueError(
                f"Modelo local no permitido: {v!r}. Configurados: {disponibles}."
            )
        return v


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
    # La rellena la guarda determinista de `ai/alcance.py` ANTES de llamar al modelo; el modelo
    # también puede marcarla, pero no es de quien depende: medido el 2026-07-28, ninguno de los
    # tres modelos evaluados detectó un paciente humano ni declinó.
    fuera_de_alcance: bool = Field(
        default=False,
        description=(
            "El caso queda fuera del dominio de la herramienta (paciente no canino ni felino, "
            "o petición ajena a la interpretación de laboratorio veterinario)"
        ),
    )
    idioma: Literal["es"] = "es"

    @field_validator("interpretacion")
    @classmethod
    def _no_vacia(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("interpretacion vacía")
        return v.strip()


def esquema_estructurado() -> dict:
    """JSON Schema endurecido para los backends que SÍ pueden emitir salida estructurada.

    El esquema por defecto deja `hallazgos_clave`, `diferenciales` y `siguientes_pruebas` con
    lista vacía por defecto, así que un modelo puede devolver `{"interpretacion": "..."}` y
    validar sin problema. Medido: qwen2.5:7b hacía exactamente eso —JSON válido con los tres
    campos vacíos— y la respuesta pasaba como buena, dejando al veterinario sin diferenciales
    ni siguientes pasos.

    `minItems` se lo pide al modelo (Ollama lo aplica en la decodificación restringida, Claude
    lo lee como parte del contrato de la herramienta). La comprobación dura vive en el
    servicio, que es quien sabe si el caso admite listas vacías: un panel normal SÍ puede no
    tener hallazgos.
    """
    esquema = InterpretacionClinica.model_json_schema()
    for campo in ("hallazgos_clave", "diferenciales", "siguientes_pruebas"):
        esquema["properties"][campo]["minItems"] = 1
    esquema["required"] = sorted(
        set(esquema.get("required", []))
        | {"interpretacion", "hallazgos_clave", "diferenciales", "siguientes_pruebas"}
    )
    _acotar_longitudes(esquema)
    return esquema


# Techos de longitud del esquema. No son cosmética: en decodificación restringida el esquema es
# lo ÚNICO que limita cuánto escribe el modelo, y sin techos medGemma produjo entradas como una
# sola «siguiente prueba» de varias líneas con paréntesis sin cerrar, hasta agotar el presupuesto
# de tokens y devolver un JSON truncado a media cadena (medido el 2026-08-01). Acotar por campo
# hace la salida más compacta, más rápida de generar —la restricción cuesta por token— y de paso
# más legible en la tarjeta clínica.
_TECHOS: dict[str, int] = {
    "interpretacion": 1400,
    "analito": 60,
    "comentario": 200,
    "nombre": 90,
    "evidencia": 140,
    "citas": 200,
    "siguientes_pruebas": 130,
}
_MAX_ITEMS: dict[str, int] = {
    "hallazgos_clave": 8,
    "diferenciales": 6,
    "siguientes_pruebas": 6,
    "evidencia": 4,
    "citas": 4,
}


def _acotar_longitudes(nodo: object, clave: str = "") -> None:
    """Recorre el esquema (incluidos los `$defs`) aplicando techos de longitud y de nº de ítems."""
    if not isinstance(nodo, dict):
        return
    if nodo.get("type") == "string" and clave in _TECHOS:
        nodo["maxLength"] = _TECHOS[clave]
    if nodo.get("type") == "array":
        if clave in _MAX_ITEMS:
            nodo["maxItems"] = _MAX_ITEMS[clave]
        # El techo de cadena de una lista se aplica a sus elementos, no a la lista.
        if isinstance(nodo.get("items"), dict) and clave in _TECHOS:
            if nodo["items"].get("type") == "string":
                nodo["items"]["maxLength"] = _TECHOS[clave]
    for subclave, valor in nodo.items():
        if subclave in ("properties", "$defs"):
            for nombre, sub in (valor or {}).items():
                _acotar_longitudes(sub, nombre)
        elif isinstance(valor, dict):
            _acotar_longitudes(valor, clave)


class Fuente(BaseModel):
    """Un fragmento de literatura realmente recuperado, con su numeración del prompt.

    NO forma parte del esquema que ve el modelo: lo rellena el servidor desde la salida de
    la recuperación. Así la atribución es verificable en las tres rutas —incluida la del HF
    Space, que sólo devuelve prosa y no puede rellenar `Diferencial.citas`— y el modelo no
    puede inventarse una fuente que no se le dio.
    """

    indice: int = Field(description="Número con el que se presentó al modelo, base 1")
    libro: str
    edicion: str = ""
    capitulo: str = ""
    pagina: str = ""
    cita: str = Field(description="Cita formateada lista para mostrar")
    citada: bool = Field(
        default=False,
        description="El modelo se apoyó explícitamente en esta fuente ([n] o cita resuelta)",
    )


class RespuestaInterpretacion(BaseModel):
    resultado: InterpretacionClinica
    modelo: str
    fuentes_rag: int = 0
    fuentes: list[Fuente] = Field(
        default_factory=list,
        description="Literatura recuperada para esta respuesta, marcando cuál se citó",
    )


class ErrorRespuesta(BaseModel):
    error: str
    detalle: str | None = None
