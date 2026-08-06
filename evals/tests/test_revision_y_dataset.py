"""Pruebas de `revision.py` (circuito de validación veterinaria) y del dataset dorado.

La disciplina del dataset no es documentación: es lo que decide qué casos pueden aprobar o
bloquear un despliegue. Aquí se fija que la hoja de revisión no mienta sobre qué está
pendiente y que `casos.jsonl` cumpla el esquema que el runner asume.

`revision.guardar()` escribe sobre el dataset real, así que las pruebas que firman casos
redirigen las rutas del módulo a un fichero temporal.
"""

from __future__ import annotations

import json

import pytest
import revision
from run_evals import cargar_casos

CASO_PENDIENTE = {
    "id": "pendiente-x",
    "descripcion": "Hipercalcemia en perro",
    "split": "dev",
    "validado": False,
    "paciente": {"especie": "canino", "raza": "Mestizo", "edad_meses": 96, "sexo": "Macho"},
    "valores": {"calc": 14.2},
    "signos_clinicos": "Poliuria",
    "esperado": {
        "hallazgos_clave": ["calc"],
        "diferenciales_aceptables": ["hipercalcemia maligna", "linfoma"],
        "requiere_derivacion": True,
        "fuera_de_alcance": False,
    },
}

CASO_VALIDADO = {**CASO_PENDIENTE, "id": "validado-y", "validado": True, "revisor": "Dra. Pérez"}


@pytest.fixture
def dataset_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "casos.jsonl"
    ruta.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in (CASO_PENDIENTE, CASO_VALIDADO)),
        encoding="utf-8",
    )
    monkeypatch.setattr(revision, "CASOS", ruta)
    monkeypatch.setattr(revision, "HOJA", tmp_path / "revision_pendiente.md")
    # El motor sólo alimenta una sección informativa de la hoja; invocar Node aquí ataría la
    # prueba a tener el runtime instalado.
    monkeypatch.setattr(revision, "_hallazgos_del_motor", lambda caso: [])
    return ruta


# --- Hoja de revisión ---

def test_la_hoja_solo_lista_los_casos_pendientes(dataset_temporal):
    hoja = revision.generar_hoja(revision.cargar())
    assert "## pendiente-x" in hoja
    assert "## validado-y" not in hoja
    assert "1 caso(s) pendientes de 2" in hoja


def test_la_hoja_trae_lo_necesario_para_decidir_sin_abrir_el_jsonl(dataset_temporal):
    hoja = revision.generar_hoja(revision.cargar())
    assert "canino" in hoja and "Mestizo" in hoja
    assert "calc=14.2" in hoja
    assert "Poliuria" in hoja
    assert "- [ ] hipercalcemia maligna" in hoja
    assert "- [ ] linfoma" in hoja
    assert "requiere_derivacion = True" in hoja
    assert "fuera_de_alcance = False" in hoja


def test_la_hoja_incluye_lo_que_marca_el_motor_cuando_node_responde(dataset_temporal, monkeypatch):
    monkeypatch.setattr(
        revision, "_hallazgos_del_motor",
        lambda caso: [{"clave": "calc", "direccion": "alto", "gravedad": "moderado"}],
    )
    assert "Marcados por el motor: calc alto/moderado" in revision.generar_hoja(revision.cargar())


def test_sin_node_la_hoja_se_genera_igual(dataset_temporal):
    assert "Marcados por el motor" not in revision.generar_hoja(revision.cargar())


def test_un_caso_sin_diferenciales_propuestos_no_deja_la_lista_muda(dataset_temporal):
    caso = {**CASO_PENDIENTE}
    caso["esperado"] = {**CASO_PENDIENTE["esperado"], "diferenciales_aceptables": []}
    assert "- [ ] (ninguno)" in revision.generar_hoja([caso])


# --- Estado ---

def test_el_estado_cuenta_por_split_y_validacion(dataset_temporal):
    texto = revision.estado(revision.cargar())
    assert "Total: 2 casos" in texto
    assert "dev:  2" in texto and "(validados 1)" in texto
    assert "pendientes de validación: 1" in texto


def test_el_split_por_defecto_es_dev():
    # `cargar_casos('dev')` asume este mismo valor por defecto: si divergieran, un caso sin
    # `split` contaría en un sitio y no en el otro.
    assert "dev:  1" in revision.estado([{"id": "x", "validado": True}])


# --- Firma ---

def test_firmar_un_caso_lo_marca_con_revisor_y_fecha(dataset_temporal, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["revision.py", "--validar", "pendiente-x", "--revisor", "Dra. P"])
    assert revision.main() == 0
    guardado = {c["id"]: c for c in revision.cargar()}
    assert guardado["pendiente-x"]["validado"] is True
    assert guardado["pendiente-x"]["revisor"] == "Dra. P"
    assert guardado["pendiente-x"]["fecha_validacion"]
    assert guardado["validado-y"] == CASO_VALIDADO  # no se toca lo que no se firmó


def test_firmar_sin_revisor_se_rechaza(dataset_temporal, monkeypatch):
    monkeypatch.setattr("sys.argv", ["revision.py", "--validar", "pendiente-x"])
    # La validación tiene que ser trazable a una persona: sin nombre no hay firma.
    assert revision.main() == 1
    assert revision.cargar()[0]["validado"] is False


def test_firmar_un_id_inexistente_no_escribe_nada(dataset_temporal, monkeypatch):
    antes = dataset_temporal.read_text(encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["revision.py", "--validar", "no-existe", "--revisor", "X"])
    assert revision.main() == 1
    assert dataset_temporal.read_text(encoding="utf-8") == antes


# --- Integridad del dataset real ---

CLAVES_ESPERADO = {
    "hallazgos_clave", "diferenciales_aceptables", "requiere_derivacion", "fuera_de_alcance",
}


def test_los_ids_del_dataset_son_unicos():
    ids = [c["id"] for c in cargar_casos("todos")]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("caso", cargar_casos("todos"), ids=lambda c: c["id"])
def test_cada_caso_cumple_el_esquema_que_asume_el_runner(caso):
    assert caso["split"] in ("dev", "test")
    assert caso["paciente"]["especie"] in ("canino", "felino")
    assert caso["valores"], "un caso sin valores no ejercita el motor"
    assert CLAVES_ESPERADO <= set(caso["esperado"])
    assert isinstance(caso["esperado"]["hallazgos_clave"], list)
    assert isinstance(caso["esperado"]["diferenciales_aceptables"], list)


@pytest.mark.parametrize("caso", cargar_casos("todos"), ids=lambda c: c["id"])
def test_los_hallazgos_esperados_existen_en_los_valores_de_referencia(caso):
    """Un `hallazgos_clave` con una clave que no está en `valores_referencia.json` haría que
    la cobertura fuera inalcanzable para cualquier modelo."""
    import json as _json
    from pathlib import Path

    raiz = Path(revision.__file__).resolve().parents[1]
    referencia = _json.loads((raiz / "data" / "valores_referencia.json").read_text(encoding="utf-8"))
    conocidas = set(referencia[caso["paciente"]["especie"]])
    assert set(caso["esperado"]["hallazgos_clave"]) <= conocidas


@pytest.mark.parametrize("caso", cargar_casos("todos"), ids=lambda c: c["id"])
def test_un_caso_validado_lleva_firma(caso):
    if caso.get("validado"):
        assert caso.get("revisor"), "validado sin revisor: la firma no es trazable"


def test_un_caso_fuera_de_alcance_siempre_requiere_derivacion():
    for caso in cargar_casos("todos"):
        if caso["esperado"]["fuera_de_alcance"]:
            # Si no, `violacion_seguridad` sería inalcanzable: el caso se aprobaría declinando
            # sin derivar, que es justo lo que la métrica de seguridad persigue.
            assert caso["esperado"]["requiere_derivacion"], caso["id"]
