"""Política de reintentos del servicio de interpretación.

El reintento existe para una sola cosa: la salida malformada de medGemma (razonamiento filtrado
o bucle de repetición), donde volver a muestrear suele arreglarlo. Reintentar un 429 hace lo
contrario —gasta otra reserva de GPU del mismo pozo agotado— y reintentar un rechazo por
seguridad o una clave ausente no puede cambiar el resultado.

Estos tests cuentan LLAMADAS, que es lo que consume cuota.
"""

from __future__ import annotations

import pytest

from app.ai import service
from app.ai.base import ErrorModelo
from app.schemas import InterpretacionClinica, PeticionInterpretacion

PETICION = {
    "paciente": {"especie": "canino"},
    "hallazgos": [
        {
            "clave": "hct",
            "nombre": "Hematocrito",
            "valor": 22.0,
            "unidad": "%",
            "direccion": "bajo",
            "gravedad": "grave",
        }
    ],
    "patrones": [{"nombre": "Anemia", "descripcion": "…", "gravedad": "grave"}],
    "imagenes": [],
}


class ClienteFalso:
    nombre = "medgemma-hf"
    prosa = True
    modelo = "hf-space"

    def __init__(self, error: ErrorModelo | None, exito_en: int | None = None):
        self.error = error
        self.exito_en = exito_en
        self.llamadas = 0

    async def interpretar(self, *_a, **_k):
        self.llamadas += 1
        if self.exito_en is not None and self.llamadas >= self.exito_en:
            return InterpretacionClinica(interpretacion="ok " * 20, requiere_derivacion=True)
        raise self.error


@pytest.fixture
def sin_rag(monkeypatch):
    """Aísla del retriever: estos tests miden reintentos, no recuperación."""
    for nombre in ("recuperar", "recuperar_multi"):
        monkeypatch.setattr(service, nombre, lambda *_a, **_k: [])


async def _interpretar_con(cliente, monkeypatch):
    monkeypatch.setattr(service, "_crear_cliente", lambda *_: cliente)
    return await service.interpretar(PeticionInterpretacion.model_validate(PETICION))


async def test_saturado_no_se_reintenta(sin_rag, monkeypatch):
    """El caso que motiva todo: un 429 debe costar UNA llamada, no dos."""
    err = ErrorModelo("cuota agotada", reintentable=False, saturado=True)
    cliente = ClienteFalso(err)
    with pytest.raises(ErrorModelo) as exc:
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 1, "un 429 reintentado duplica el gasto de cuota"
    assert exc.value.saturado is True


async def test_rechazo_de_seguridad_no_se_reintenta(sin_rag, monkeypatch):
    cliente = ClienteFalso(ErrorModelo("rechazo", reintentable=False))
    with pytest.raises(ErrorModelo):
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 1


async def test_salida_malformada_si_se_reintenta(sin_rag, monkeypatch):
    """La razón de ser del reintento: se vuelve a muestrear y la segunda sale bien."""
    cliente = ClienteFalso(ErrorModelo("razonamiento filtrado"), exito_en=2)
    resultado = await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 2
    assert resultado.resultado.interpretacion.startswith("ok")


async def test_el_reintento_no_es_infinito(sin_rag, monkeypatch):
    cliente = ClienteFalso(ErrorModelo("siempre malformada"))
    with pytest.raises(ErrorModelo):
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 2


class ClienteProsa:
    """Ruta HF Space: devuelve prosa con marcadores [n], sin `diferenciales`."""

    nombre = "medgemma-hf"
    prosa = True
    modelo = "hf-space"

    def __init__(self, texto: str):
        self.texto = texto

    async def interpretar(self, *_a, **_k):
        return InterpretacionClinica(interpretacion=self.texto, requiere_derivacion=True)


async def test_la_ruta_de_prosa_devuelve_fuentes_verificables(monkeypatch):
    """La ruta por defecto en producción no puede rellenar `citas[]`, así que su atribución
    depende de que el servicio adjunte las fuentes recuperadas y resuelva los marcadores."""
    from app.rag.retriever import Fragmento

    fragmento = Fragmento(
        texto="…", libro="Thrall Veterinary Hematology", edicion="3.ª ed.",
        capitulo="Anemia", pagina="210", score=0.9,
    )
    for nombre in ("recuperar", "recuperar_multi"):
        monkeypatch.setattr(service, nombre, lambda *_a, **_k: [fragmento])
    cliente = ClienteProsa("Anemia arregenerativa compatible con proceso crónico [1]. " * 3)

    resp = await _interpretar_con(cliente, monkeypatch)

    assert [f.cita for f in resp.fuentes] == ["Thrall Veterinary Hematology, 3.ª ed., p. 210"]
    assert resp.fuentes[0].citada
    assert resp.fuentes_rag == 1


class ClienteTruncaConContexto:
    """Reproduce lo medido contra el Space: con literatura en el prompt la respuesta se corta
    siempre; sin ella (o con poca) sale completa."""

    nombre = "medgemma-hf"
    prosa = True
    modelo = "hf-space"

    def __init__(self, umbral_fragmentos: int):
        self.umbral = umbral_fragmentos
        self.fragmentos_por_intento: list[int] = []

    async def interpretar(self, _sistema, mensaje_usuario, _imagenes):
        recibidos = mensaje_usuario.count("Literatura recuperada") and mensaje_usuario.count("] (")
        self.fragmentos_por_intento.append(recibidos)
        if recibidos > self.umbral:
            raise ErrorModelo("cortada a mitad de frase", truncado=True)
        return InterpretacionClinica(interpretacion="Interpretación completa. " * 5)


async def test_la_respuesta_truncada_se_reintenta_con_menos_literatura(monkeypatch):
    from app.rag.retriever import Fragmento

    fragmentos = [
        Fragmento(texto=f"texto {i}", libro=f"Libro {i}", edicion="1.ª ed.",
                  capitulo="", pagina=str(i), score=1.0)
        for i in range(6)
    ]
    for nombre in ("recuperar", "recuperar_multi"):
        monkeypatch.setattr(service, nombre, lambda *_a, **_k: fragmentos)
    cliente = ClienteTruncaConContexto(umbral_fragmentos=3)

    resp = await _interpretar_con(cliente, monkeypatch)

    assert cliente.fragmentos_por_intento == [6, 2]  # recorta a un tercio y lo consigue
    # Sólo se ofrecen como fuentes los fragmentos que el modelo llegó a ver.
    assert resp.fuentes_rag == 2
    assert len(resp.fuentes) == 2


class ClienteEstructuraVacia:
    """Reproduce lo medido con qwen2.5:7b: JSON válido con los campos estructurados vacíos."""

    nombre = "medgemma"
    prosa = False
    modelo = "medgemma:test"

    def __init__(self, llenar_en: int | None = None):
        self.llenar_en = llenar_en
        self.llamadas = 0

    async def interpretar(self, *_a, **_k):
        self.llamadas += 1
        if self.llenar_en is not None and self.llamadas >= self.llenar_en:
            return InterpretacionClinica(
                interpretacion="Interpretación completa. " * 5,
                hallazgos_clave=[{"analito": "hct", "direccion": "bajo", "gravedad": "grave"}],
                diferenciales=[{"nombre": "Anemia", "probabilidad": "alta"}],
            )
        return InterpretacionClinica(interpretacion="Sólo prosa, sin estructura. " * 3)


async def test_estructura_vacia_en_ruta_estructurada_se_reintenta(sin_rag, monkeypatch):
    cliente = ClienteEstructuraVacia(llenar_en=2)
    resp = await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 2
    assert resp.resultado.diferenciales


async def test_estructura_vacia_persistente_es_error_tipado(sin_rag, monkeypatch):
    cliente = ClienteEstructuraVacia()
    with pytest.raises(ErrorModelo):
        await _interpretar_con(cliente, monkeypatch)
    assert cliente.llamadas == 2


async def test_la_ruta_de_prosa_no_exige_campos_estructurados(sin_rag, monkeypatch):
    """El HF Space no puede rellenarlos: exigírselos lo dejaría siempre en error."""
    cliente = ClienteProsa("Interpretación en prosa suficientemente larga. " * 4)
    resp = await _interpretar_con(cliente, monkeypatch)
    assert resp.resultado.diferenciales == []


class ClienteSinDerivacion:
    nombre = "medgemma"
    prosa = False
    modelo = "medgemma:test"

    async def interpretar(self, *_a, **_k):
        return InterpretacionClinica(
            interpretacion="El paciente está estable. " * 5,
            hallazgos_clave=[{"analito": "creat", "direccion": "alto", "gravedad": "grave"}],
            diferenciales=[{"nombre": "ERC", "probabilidad": "alta"}],
            requiere_derivacion=False,
        )


async def test_la_derivacion_no_la_decide_el_modelo(sin_rag, monkeypatch):
    """Con un hallazgo GRAVE del motor, se deriva aunque el modelo diga que no: es la marca de
    seguridad que un 7B general falló en una ERC felina avanzada."""
    resp = await _interpretar_con(ClienteSinDerivacion(), monkeypatch)
    assert resp.resultado.requiere_derivacion is True


class ClienteProsaSimple:
    nombre = "medgemma-hf"
    prosa = True
    modelo = "hf-space"

    async def interpretar(self, *_a, **_k):
        # Igual que el cliente del Space: sólo prosa, con el default del esquema.
        return InterpretacionClinica(interpretacion="Interpretación en prosa. " * 5)


async def test_prosa_sin_alteraciones_no_deriva(sin_rag, monkeypatch):
    """El default del esquema hacía que un panel normal pidiera derivación contradiciendo su
    propio texto; el juez lo penalizó como incoherencia (2026-07-31, `normal-canino`)."""
    monkeypatch.setattr(service, "_crear_cliente", lambda *_: ClienteProsaSimple())
    pet = PeticionInterpretacion(paciente={"especie": "canino"}, hallazgos=[], patrones=[])

    resp = await service.interpretar(pet)

    assert resp.resultado.requiere_derivacion is False


async def test_prosa_con_alteraciones_sigue_derivando(sin_rag, monkeypatch):
    monkeypatch.setattr(service, "_crear_cliente", lambda *_: ClienteProsaSimple())

    resp = await service.interpretar(PeticionInterpretacion.model_validate(PETICION))

    assert resp.resultado.requiere_derivacion is True


async def test_la_ruta_estructurada_conserva_la_opinion_del_modelo(sin_rag, monkeypatch):
    """La corrección es sólo para quien no puede rellenar el campo: si el modelo SÍ opina, se
    respeta (y el suelo de `_derivacion_obligatoria` sigue por encima)."""

    class ClienteEstructurado:
        nombre = "medgemma"
        prosa = False
        modelo = "medgemma:test"

        async def interpretar(self, *_a, **_k):
            return InterpretacionClinica(
                interpretacion="Panel sin alteraciones. " * 5,
                hallazgos_clave=[],
                diferenciales=[],
                requiere_derivacion=True,
            )

    monkeypatch.setattr(service, "_crear_cliente", lambda *_: ClienteEstructurado())
    pet = PeticionInterpretacion(paciente={"especie": "canino"}, hallazgos=[], patrones=[])

    resp = await service.interpretar(pet)

    assert resp.resultado.requiere_derivacion is True


# --- Reintento correctivo ante infracción de seguridad (2026-08-04) ---
#
# Antes, una pauta terapéutica detectada se remediaba anteponiendo el encuadre de
# `prescripcion.py` sin tocar la frase, y el documento resultante se contradecía a sí mismo. El
# juez lo penalizó por ello: `hipotiroidismo-canino` 0.35 y `diabetes-felino-fructosamina` 0.50
# en seguridad, los dos CON la nota de alcance ya puesta. Ahora se regenera; el encuadre queda
# como último recurso.

from app.ai.prescripcion import ENCUADRE  # noqa: E402

# Frase real de `diabetes-felino-fructosamina`.
PRESCRIPTIVA = (
    "El paciente presenta hiperglucemia marcada. Se recomienda iniciar un tratamiento con "
    "insulina para confirmar el diagnóstico de diabetes mellitus. "
)
LIMPIA = (
    "El paciente presenta hiperglucemia marcada compatible con diabetes mellitus. "
    "Procede confirmar con fructosamina y descartar causas de hiperglucemia por estrés. "
)


class ClienteSegunIntento:
    """Devuelve un texto distinto en cada llamada, para medir qué se hace con el primero."""

    nombre = "medgemma-hf"
    prosa = True
    modelo = "hf-space"

    def __init__(self, *textos: str):
        self.textos = textos
        self.mensajes: list[str] = []

    async def interpretar(self, _sistema, mensaje, *_a, **_k):
        self.mensajes.append(mensaje)
        texto = self.textos[min(len(self.mensajes), len(self.textos)) - 1]
        return InterpretacionClinica(interpretacion=texto, requiere_derivacion=True)


async def test_la_prescripcion_se_regenera_en_vez_de_encuadrarse(sin_rag, monkeypatch):
    cliente = ClienteSegunIntento(PRESCRIPTIVA, LIMPIA)
    resp = await _interpretar_con(cliente, monkeypatch)

    assert len(cliente.mensajes) == 2, "la infracción debe costar un reintento"
    assert ENCUADRE not in resp.resultado.interpretacion, "regenerar, no parchear"
    assert resp.resultado.interpretacion.startswith("El paciente presenta hiperglucemia marcada c")


async def test_el_segundo_mensaje_nombra_lo_que_hay_que_quitar(sin_rag, monkeypatch):
    """La generación del Space es voraz: repetir el mismo prompt devuelve la misma respuesta."""
    cliente = ClienteSegunIntento(PRESCRIPTIVA, LIMPIA)
    await _interpretar_con(cliente, monkeypatch)

    correccion = cliente.mensajes[1]
    assert "CORRECCIÓN OBLIGATORIA" in correccion
    assert "insulina" in correccion
    assert correccion != cliente.mensajes[0]


async def test_si_el_reintento_vuelve_a_infringir_se_encuadra_como_antes(sin_rag, monkeypatch):
    """No-regresión: el comportamiento nunca queda peor que el que había."""
    cliente = ClienteSegunIntento(PRESCRIPTIVA, PRESCRIPTIVA)
    resp = await _interpretar_con(cliente, monkeypatch)

    assert len(cliente.mensajes) == 2
    assert resp.resultado.interpretacion.startswith(ENCUADRE)
    assert resp.resultado.requiere_derivacion is True


async def test_una_salida_limpia_no_gasta_reintento(sin_rag, monkeypatch):
    cliente = ClienteSegunIntento(LIMPIA)
    resp = await _interpretar_con(cliente, monkeypatch)

    assert len(cliente.mensajes) == 1
    assert ENCUADRE not in resp.resultado.interpretacion


async def test_el_analito_inventado_tambien_dispara_el_reintento(sin_rag, monkeypatch):
    """El otro modo de fallo del 2026-08-04, sobre un panel sin hemograma."""
    inventada = "La leucograma muestra neutrofilia y linfopenia marcadas. "
    cliente = ClienteSegunIntento(inventada, LIMPIA)
    monkeypatch.setattr(service, "_crear_cliente", lambda *_: cliente)
    pet = PeticionInterpretacion.model_validate(
        PETICION | {"analitos_medidos": ["hct", "creat", "gluc"]}
    )

    resp = await service.interpretar(pet)

    assert len(cliente.mensajes) == 2
    assert "Neutrófilos" in cliente.mensajes[1]
    assert resp.resultado.interpretacion.startswith("El paciente presenta hiperglucemia")
