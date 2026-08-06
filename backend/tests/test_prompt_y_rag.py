"""Pruebas del constructor de prompt y la degradación sin-RAG del recuperador."""

from __future__ import annotations

import pytest

from app.ai.prompt import SISTEMA, construir_mensaje_usuario
from app.rag.retriever import Fragmento, construir_consulta
from app.schemas import PeticionInterpretacion


def _peticion():
    return PeticionInterpretacion(
        paciente={"especie": "canino", "raza": "Labrador", "edad_meses": 96, "sexo": "Macho"},
        hallazgos=[
            {"clave": "hct", "nombre": "Hematocrito", "valor": 25, "unidad": "%", "direccion": "bajo", "gravedad": "moderado"},
        ],
        patrones=[
            {"nombre": "Anemia microcítica", "descripcion": "Parámetros eritrocitarios disminuidos.", "gravedad": "moderado", "parametros": ["hct"]},
        ],
        signos_clinicos="Letargia y mucosas pálidas",
    )


def test_sistema_exige_espanol_y_derivacion():
    assert "español" in SISTEMA.lower()
    assert "requiere_derivacion" in SISTEMA


def test_mensaje_incluye_paciente_hallazgos_y_patrones():
    msg = construir_mensaje_usuario(_peticion(), [])
    assert "canino" in msg
    assert "Hematocrito" in msg
    assert "Anemia microcítica" in msg
    assert "Letargia" in msg


def test_mensaje_incluye_bloque_rag_con_cita():
    frag = Fragmento(
        texto="La anemia ferropénica cursa con microcitosis e hipocromía.",
        libro="Thrall Veterinary Hematology", edicion="3.ª ed.", capitulo="Anemia", pagina="210", score=0.1,
    )
    msg = construir_mensaje_usuario(_peticion(), [frag])
    assert "Literatura recuperada" in msg
    assert "Thrall" in msg and "p. 210" in msg


def test_panel_normal_no_mete_lineas_de_relleno():
    """Regresión del 2026-07-28: con «Todos los valores dentro de rangos de referencia» y
    «Ninguno detectado…» en el prompt, qwen2.5:14b devolvió un hallazgo llamado literalmente
    «Todos los valores» (alto · leve) sobre una glucosa en rango. Los bloques vacíos se omiten.
    """
    pet = PeticionInterpretacion(
        paciente={"especie": "canino", "raza": "Labrador", "edad_meses": 36, "sexo": "Macho"},
        signos_clinicos="Chequeo rutinario, asintomático",
    )
    msg = construir_mensaje_usuario(pet, [])
    assert "Todos los valores" not in msg
    assert "Ninguno detectado" not in msg
    assert "Hallazgos de laboratorio" not in msg
    assert "ningún valor fuera de rango" in msg
    # Un panel normal no debe pedir diferenciales: eso es pedir que se invente patología.
    assert "NO inventes" in msg


def test_caso_con_hallazgos_sigue_pidiendo_diferenciales():
    msg = construir_mensaje_usuario(_peticion(), [])
    assert "Hallazgos de laboratorio" in msg
    assert "diferenciales ordenados por probabilidad" in msg


def test_construir_consulta_combina_terminos():
    q = construir_consulta(["Anemia microcítica"], ["Hematocrito"])
    assert "Anemia microcítica" in q and "Hematocrito" in q


def test_construir_consultas_separa_una_por_patron():
    """La consulta única promediaba patrones sin literatura común en un solo embedding."""
    from app.rag.retriever import construir_consultas

    qs = construir_consultas(
        ["Anemia regenerativa", "Azotemia renal"], ["Hematocrito", "Creatinina"]
    )
    assert qs[:2] == ["Anemia regenerativa", "Azotemia renal"]
    assert "Hematocrito" in qs[-1] and "Creatinina" in qs[-1]


def test_construir_consultas_sin_patrones_degrada_a_una():
    from app.rag.retriever import construir_consultas

    assert construir_consultas([], ["Hematocrito", "Creatinina"]) == ["Hematocrito ; Creatinina"]


def test_construir_consultas_no_repite_terminos():
    from app.rag.retriever import construir_consultas

    assert construir_consultas(["Anemia"], ["anemia"]) == ["Anemia"]


@pytest.fixture
def multiconsulta(monkeypatch, request):
    """Fija `MORPHOS_RAG_MULTICONSULTA` invalidando la config cacheada a la ida y a la vuelta."""
    from app.config import obtener_config

    monkeypatch.setenv("MORPHOS_RAG_MULTICONSULTA", request.param)
    obtener_config.cache_clear()
    yield request.param == "1"
    monkeypatch.undo()
    obtener_config.cache_clear()


@pytest.mark.parametrize("multiconsulta", ["0", "1"], indirect=True)
async def test_el_servicio_elige_la_ruta_de_recuperacion_segun_la_bandera(monkeypatch, multiconsulta):
    """Con la bandera apagada (defecto) se recupera con la consulta CONCATENADA. Delegar el
    caso en `recuperar_multi` sin más lo dejaría recuperando sólo por el primer patrón."""
    from app.ai import service
    from app.ai.base import ErrorModelo

    vistas: dict[str, object] = {}

    def _anotar(clave):
        def _registrar(consulta, **_k):
            vistas[clave] = consulta
            return []

        return _registrar

    monkeypatch.setattr(service, "recuperar", _anotar("unica"))
    monkeypatch.setattr(service, "recuperar_multi", _anotar("multi"))

    class ClienteQueNoResponde:
        nombre = "medgemma"
        prosa = False
        modelo = "medgemma:test"

        async def interpretar(self, *_a, **_k):
            raise ErrorModelo("no importa: sólo se mira la recuperación", reintentable=False)

    monkeypatch.setattr(service, "_crear_cliente", lambda *_: ClienteQueNoResponde())
    with pytest.raises(ErrorModelo):
        await service.interpretar(_peticion())

    if multiconsulta:
        assert vistas["multi"] == ["Anemia microcítica", "Hematocrito"]
        assert "unica" not in vistas
    else:
        assert vistas["unica"] == "Anemia microcítica ; Hematocrito"
        assert "multi" not in vistas


def test_recuperar_degrada_sin_indice(monkeypatch):
    # Contrato de degradación: sin recursos RAG (deps ausentes o índice no construido),
    # recuperar devuelve [] sin lanzar. Se fuerza vía monkeypatch para no depender de si
    # existe un índice real en el entorno de pruebas.
    import app.rag.retriever as R

    monkeypatch.setattr(R, "_cargar_recursos", lambda: None)
    assert R.recuperar("anemia ferropénica", especie="canino") == []


def _frags(n: int, largo: int = 600):
    from app.rag.retriever import Fragmento

    return [
        Fragmento(texto="x" * largo, libro=f"Libro {i}", edicion="1.ª ed.",
                  capitulo="", pagina=str(i), score=1.0 - i / 100)
        for i in range(n)
    ]


def test_presupuesto_recorta_manteniendo_los_mejor_rankeados():
    """El Space reparte 2048 tokens entre el razonamiento que descarta y la respuesta: pasarle
    los 6 fragmentos cortaba la interpretación a mitad de frase."""
    from app.ai.service import recortar_a_presupuesto

    recortados = recortar_a_presupuesto(_frags(6), 1800)
    assert len(recortados) == 3
    assert [f.libro for f in recortados] == ["Libro 0", "Libro 1", "Libro 2"]


def test_presupuesto_nunca_deja_la_respuesta_sin_literatura():
    from app.ai.service import recortar_a_presupuesto

    assert len(recortar_a_presupuesto(_frags(4), 10)) == 1


def test_presupuesto_desactivado_no_recorta():
    from app.ai.service import recortar_a_presupuesto

    assert len(recortar_a_presupuesto(_frags(6), 0)) == 6


# --- Bloque de panel completo (2026-08-04) ---

def test_el_panel_nombra_lo_medido_en_rango_y_cierra_la_lista():
    """`hallazgos` sólo trae lo alterado, así que sin esto el modelo no distingue «no se midió»
    de «se midió y salió normal» y rellena el hueco (leucograma inventado, corrida 2026-08-04)."""
    pet = _peticion().model_copy(update={"analitos_medidos": ["hct", "plt", "gluc"]})
    msg = construir_mensaje_usuario(pet, [])
    assert "DENTRO de rango" in msg
    assert "Plaquetas" in msg and "Glucosa" in msg
    assert "Hematocrito (Hct)" not in msg, "el alterado ya va en su propio bloque"
    assert "panel COMPLETO" in msg


def test_sin_analitos_medidos_el_bloque_desaparece_entero():
    """Cliente antiguo: anunciar un «panel completo» vacío sería peor que no decir nada, y el
    relleno se lee como contenido (mismo motivo que test_panel_normal_no_mete_lineas_de_relleno)."""
    msg = construir_mensaje_usuario(_peticion(), [])
    assert "DENTRO de rango" not in msg
    assert "panel COMPLETO" not in msg


def test_el_panel_sin_ninguno_en_rango_conserva_el_cierre():
    """Todo lo medido salió alterado: no hay lista que enseñar, pero sí que decir que no hay más."""
    pet = _peticion().model_copy(update={"analitos_medidos": ["hct"]})
    msg = construir_mensaje_usuario(pet, [])
    assert "DENTRO de rango" not in msg
    assert "panel COMPLETO" in msg
