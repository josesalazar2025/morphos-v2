"""Lista blanca de modelos locales elegibles desde la UI.

Lo que aquí se fija es la frontera de confianza: el navegador puede decir CUÁL de los modelos
declarados por el servidor responde, y nada más. Ni una URL (sería un SSRF: el servidor haría
peticiones a donde diga el cliente) ni un nombre arbitrario (elegiría qué pesos se descargan en
la máquina que aloja el servicio). Y el modelo elegido recorre exactamente el mismo camino que
el Space: RAG, prompt endurecido, atribución y suelos de seguridad.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai import service
from app.config import Configuracion, obtener_config
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


@pytest.fixture
def lista_blanca(monkeypatch):
    """Config con dos modelos declarados: uno estructurado y otro de prosa."""
    cfg = obtener_config().model_copy(
        update={"modelos_locales": ["medgemma1.5:latest", "qwen2.5:7b=prosa"]}
    )
    # El validador del esquema importa `obtener_config` perezosamente desde `app.config`;
    # el servicio lo tiene ya resuelto en su propio espacio de nombres. Hay que parchear ambos.
    monkeypatch.setattr("app.config.obtener_config", lambda: cfg)
    monkeypatch.setattr(service, "obtener_config", lambda: cfg)
    return cfg


def test_parseo_de_la_lista_blanca():
    cfg = Configuracion(modelos_locales="medgemma1.5:latest, qwen2.5:7b=prosa , vacio=raro")
    permitidos = cfg.modelos_locales_permitidos()
    # El nombre lleva ':' propio, por eso el modo se separa con '='.
    assert permitidos == {
        "medgemma1.5:latest": False,
        "qwen2.5:7b": True,
        "vacio": False,  # sufijo desconocido → estructurado, sin reventar el arranque
    }


def test_sin_lista_blanca_no_se_acepta_ningun_modelo():
    """Estado por defecto (instancia pública): el selector no existe y nada se cuela."""
    with pytest.raises(ValidationError, match="no permitido"):
        PeticionInterpretacion.model_validate({**PETICION, "modelo_local": "medgemma1.5:latest"})


def test_modelo_fuera_de_la_lista_se_rechaza(lista_blanca):
    with pytest.raises(ValidationError, match="no permitido"):
        PeticionInterpretacion.model_validate({**PETICION, "modelo_local": "llama3:70b"})


def test_no_hay_forma_de_inyectar_una_url(lista_blanca):
    """El campo sólo admite nombres de la lista; una URL nunca llega a httpx."""
    for intento in ("http://attacker.example/api", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(ValidationError):
            PeticionInterpretacion.model_validate({**PETICION, "modelo_local": intento})


def test_cliente_estructurado_para_el_modelo_declarado_asi(lista_blanca, monkeypatch):
    monkeypatch.setattr("app.ai.medgemma.obtener_config", lambda: lista_blanca)
    cliente = service._crear_cliente("medgemma", "medgemma1.5:latest")
    assert cliente.modelo == "medgemma1.5:latest"
    assert cliente.prosa is False


def test_cliente_de_prosa_para_el_modelo_declarado_prosa(lista_blanca, monkeypatch):
    monkeypatch.setattr("app.ai.medgemma.obtener_config", lambda: lista_blanca)
    cliente = service._crear_cliente("medgemma", "qwen2.5:7b")
    assert cliente.modelo == "qwen2.5:7b"
    assert cliente.prosa is True


def test_el_modelo_local_gana_al_hf_space(lista_blanca, monkeypatch):
    """Con Space configurado, elegir un modelo en la UI debe llevar a Ollama igualmente.

    Si no, el selector mentiría: el veterinario cree estar usando su modelo y responde el Space.
    """
    assert lista_blanca.hf_space_url  # el defecto trae Space
    monkeypatch.setattr("app.ai.medgemma.obtener_config", lambda: lista_blanca)
    cliente = service._crear_cliente("medgemma", "medgemma1.5:latest")
    assert cliente.nombre.startswith("medgemma")
    assert "hf" not in cliente.nombre


def test_sin_modelo_local_decide_el_servidor(lista_blanca):
    """None = comportamiento de siempre; la lista blanca no cambia la ruta por defecto."""
    cliente = service._crear_cliente("medgemma", None)
    assert cliente.nombre == "medgemma-hf"


async def test_el_modelo_elegido_recibe_rag_y_se_reporta_en_la_respuesta(
    lista_blanca, monkeypatch
):
    """El punto de todo el ejercicio: un modelo local ve la misma literatura recuperada."""
    from app.rag.retriever import Fragmento

    fragmento = Fragmento(
        texto="La anemia arregenerativa en el perro…",
        libro="Fundamentals",
        edicion="7",
        capitulo="Anemia",
        pagina="120",
        score=1.0,
    )
    for nombre in ("recuperar", "recuperar_multi"):
        monkeypatch.setattr(service, nombre, lambda *_a, **_k: [fragmento])

    visto: dict = {}

    class ClienteLocal:
        nombre = "medgemma"
        prosa = False
        modelo = "medgemma1.5:latest"

        async def interpretar(self, _sistema, mensaje_usuario, _imagenes):
            visto["mensaje"] = mensaje_usuario
            return InterpretacionClinica(
                interpretacion="ok " * 20,
                hallazgos_clave=[
                    {
                        "analito": "Hematocrito",
                        "direccion": "bajo",
                        "gravedad": "grave",
                        "comentario": "anemia",
                    }
                ],
                diferenciales=[
                    {"nombre": "IMHA", "probabilidad": "alta", "evidencia": ["hct bajo"]}
                ],
                requiere_derivacion=True,
            )

    monkeypatch.setattr(service, "_crear_cliente", lambda *_: ClienteLocal())
    pet = PeticionInterpretacion.model_validate(
        {**PETICION, "modelo_local": "medgemma1.5:latest"}
    )
    resp = await service.interpretar(pet)

    assert "anemia arregenerativa" in visto["mensaje"].lower()
    assert resp.fuentes_rag == 1
    # La etiqueta debe nombrar el modelo QUE RESPONDIÓ, no el de la configuración.
    assert resp.modelo == "medgemma:medgemma1.5:latest"


def test_las_pruebas_no_heredan_el_env_del_desarrollador():
    """La lista blanca vacía por defecto sólo se sostiene si nadie lee el `.env` local.

    Este fichero afirma que sin declaración no hay modelos elegibles. Un
    `MORPHOS_MODELOS_LOCALES=…` en `backend/.env` —perfectamente legítimo para trabajar en
    local— hacía fallar esa afirmación en la máquina del desarrollador y pasarla en CI, que es
    la peor combinación posible: la prueba deja de describir el código y describe la máquina.
    """
    assert Configuracion.model_config["env_file"] is None
