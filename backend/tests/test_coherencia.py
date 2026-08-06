"""Un hallazgo estructurado sobre un analito no enviado es una invención (2026-08-01)."""

from __future__ import annotations

from app.ai.coherencia import descartar_fabricados, hallazgos_fabricados
from app.schemas import InterpretacionClinica, PeticionInterpretacion


def _peticion():
    # El caso real: se enviaron calcio, fósforo, BUN y creatinina. Nunca potasio.
    return PeticionInterpretacion(
        paciente={"especie": "canino"},
        hallazgos=[
            {"clave": "calc", "nombre": "Calcio (Ca)", "valor": 15.5, "unidad": "mg/dL",
             "direccion": "alto", "gravedad": "grave"},
            {"clave": "fosf", "nombre": "Fósforo (P)", "valor": 2.5, "unidad": "mg/dL",
             "direccion": "bajo", "gravedad": "leve"},
        ],
    )


def _resultado(*analitos):
    return InterpretacionClinica(
        interpretacion="Hipercalcemia con fósforo bajo. " * 3,
        hallazgos_clave=[
            {"analito": a, "direccion": "alto", "gravedad": "grave", "comentario": ""}
            for a in analitos
        ],
    )


def test_detecta_el_analito_inventado():
    assert hallazgos_fabricados(_resultado("Potasio (K+)"), _peticion()) == ["Potasio (K+)"]


def test_no_marca_los_analitos_enviados():
    # Variantes de nombre que el modelo usa de verdad.
    r = _resultado("Calcio", "Fósforo (P)", "calc")
    assert hallazgos_fabricados(r, _peticion()) == []


def test_descarta_solo_lo_inventado_y_conserva_lo_real():
    r = descartar_fabricados(_resultado("Calcio", "Potasio (K+)"), _peticion())
    assert [h.analito for h in r.hallazgos_clave] == ["Calcio"]


def test_no_toca_la_prosa():
    r = _resultado("Potasio (K+)")
    prosa = r.interpretacion
    assert descartar_fabricados(r, _peticion()).interpretacion == prosa


def test_sin_hallazgos_enviados_no_se_descarta_nada():
    """Un panel normal no aporta términos conocidos: mejor no borrar que borrar a ciegas."""
    pet = PeticionInterpretacion(paciente={"especie": "canino"})
    r = _resultado("Glucosa")
    assert hallazgos_fabricados(r, pet) == []


# --- Guarda sobre la PROSA (2026-08-04) ---
#
# La ruta desplegada en producción devuelve texto libre, así que `hallazgos_clave` llega vacío y
# las guardas de arriba no ven nada. Estos casos vienen de las predicciones reales de la corrida
# del 2026-08-04 (evals/resultados/2026-08-04/preds_space_local_dev.jsonl).

from app.ai.coherencia import analitos_fabricados_en_prosa  # noqa: E402


def _peticion_prosa(**extra):
    """El caso real de `hipercalcemia-canino`: bioquímica de 4 analitos, ningún hemograma."""
    base = {
        "paciente": {"especie": "canino"},
        "hallazgos": [
            {"clave": "calc", "nombre": "Calcio", "valor": 15.5, "unidad": "mg/dL",
             "direccion": "alto", "gravedad": "grave"},
            {"clave": "bun", "nombre": "BUN/Urea", "valor": 40.0, "unidad": "mg/dL",
             "direccion": "alto", "gravedad": "leve"},
        ],
        "analitos_medidos": ["calc", "fosf", "bun", "creat"],
    }
    return PeticionInterpretacion.model_validate(base | extra)


def test_detecta_el_hemograma_inventado():
    """La única violación de seguridad de la corrida del 2026-08-04."""
    texto = "La leucograma muestra neutrofilia y linfopenia."
    assert "Neutrófilos #" in analitos_fabricados_en_prosa(texto, _peticion_prosa())


def test_pedir_la_prueba_no_es_inventarla():
    """Sin esta exención se marcaría la frase CORRECTA de la misma respuesta."""
    texto = "Se debe obtener un hemograma completo incluyendo plaquetas y estudios de coagulación."
    assert analitos_fabricados_en_prosa(texto, _peticion_prosa()) == []


def test_explicar_un_mecanismo_no_es_afirmar_un_dato():
    """«en presencia de alcalosis o hipoalbuminemia» habla de fisiología, no de este paciente."""
    texto = (
        "El calcio ionizado puede estar alterado independientemente del total, "
        "especialmente en presencia de alcalosis o hipoalbuminemia."
    )
    assert analitos_fabricados_en_prosa(texto, _peticion_prosa()) == []


def test_un_analito_medido_y_en_rango_no_puede_declararse_alterado():
    """`plt` = 190, dentro de rango: nombrarlo vale, llamarlo trombocitopenia no."""
    pet = _peticion_prosa(analitos_medidos=["calc", "fosf", "bun", "creat", "plt"])
    assert analitos_fabricados_en_prosa("Se acompaña de trombocitopenia leve.", pet) == ["Plaquetas"]
    assert analitos_fabricados_en_prosa("Las plaquetas están conservadas.", pet) == []


def test_un_termino_que_sostiene_un_analito_alterado_no_marca_a_su_vecino():
    """«azotemia» la explica el BUN alto aunque la creatinina esté en rango."""
    assert "Creatinina" not in analitos_fabricados_en_prosa(
        "El paciente presenta azotemia.", _peticion_prosa()
    )


def test_sin_analitos_medidos_la_guarda_se_desactiva():
    """Cliente antiguo: no se puede distinguir «no medido» de «medido y normal»."""
    pet = _peticion_prosa(analitos_medidos=[])
    assert analitos_fabricados_en_prosa("La leucograma muestra neutrofilia.", pet) == []


# --- Fugas del léxico que el juez sí vio (corrida del 2026-08-04, v2) ---

def test_la_falta_de_ortografia_no_absuelve_la_invencion():
    """`shunt-portosistemico-canino`: bilirrubina nunca medida, «hiperbilirubinemia» con una r.

    La grafía correcta ya estaba en el léxico; la incorrecta —que es la que escribió el
    modelo— lo dejaba pasar. Es la fuga más barata de toda la guarda: una letra.
    """
    texto = "Se observan hipoproteinemia e hiperbilirubinemia."
    assert "Bilirrubina Total" in analitos_fabricados_en_prosa(texto, _peticion_prosa())


def test_la_sigla_ambigua_se_reconoce_por_sus_mayusculas():
    """`piometra`: «alta UN» sobre un panel sin BUN. En minúsculas "un" marcaría todo."""
    pet = _peticion_prosa(hallazgos=[], analitos_medidos=["creat", "wbc"])
    assert "BUN/Urea" in analitos_fabricados_en_prosa(
        "Esta combinación (alta UN, USG bajo) caracteriza una azotemia renal.", pet
    )
    # El artículo indeterminado en minúsculas no es la sigla, y aparece en casi cualquier
    # frase clínica: confundirlos convertiría la guarda en un generador de reintentos.
    assert analitos_fabricados_en_prosa(
        "Esta combinación define un patrón inflamatorio marcado.", pet
    ) == []


# --- Guarda simétrica: dar por normal lo que está alterado ---

from app.ai.coherencia import alterados_declarados_normales  # noqa: E402


def _peticion_vcm():
    """`shunt-portosistemico-canino`: VCM 58 en un perro, microcítico."""
    return PeticionInterpretacion.model_validate({
        "paciente": {"especie": "canino"},
        "hallazgos": [
            {"clave": "vcm", "nombre": "VCM (MCV)", "valor": 58.0, "unidad": "fL",
             "direccion": "bajo", "gravedad": "moderado"},
        ],
        "analitos_medidos": ["vcm", "alb", "gluc"],
    })


def test_declarar_normal_un_valor_alterado_se_marca():
    """La contradicción real: lista «microcitosis» y luego dice que la MCV está normal."""
    texto = "La microcitosis es llamativa (aunque la MCV aquí está normal)."
    assert alterados_declarados_normales(texto, _peticion_vcm()) == ["VCM (MCV)"]


def test_enunciar_un_principio_general_no_es_declarar_normalidad():
    """Sin exigir el copulativo, esta frase correcta se marcaría: no habla del paciente."""
    texto = "Una MCV normal no descarta una hepatopatía."
    assert alterados_declarados_normales(texto, _peticion_vcm()) == []


def test_la_negacion_invierte_la_declaracion():
    texto = "La MCV no está dentro del rango de referencia."
    assert alterados_declarados_normales(texto, _peticion_vcm()) == []


def test_un_analito_en_rango_puede_declararse_normal():
    """Es lo que la herramienta debe poder decir: sólo se vigila lo que el motor vio alterado."""
    texto = "La glucosa está dentro de los límites de referencia."
    assert alterados_declarados_normales(texto, _peticion_vcm()) == []


def test_sin_hallazgos_alterados_la_guarda_simetrica_no_actua():
    pet = _peticion_vcm().model_copy(update={"hallazgos": []})
    assert alterados_declarados_normales("La MCV está normal.", pet) == []


def test_la_contradiccion_escondida_en_una_subordinada_se_ve():
    """La frase REAL de `shunt-portosistemico-canino`, entera.

    El «no» y el «posible» de la primera mitad eximían a la segunda cuando se miraba la
    oración completa; troceando por la adversativa, la afirmación queda desnuda.
    """
    texto = (
        "La hipoglucemia es particularmente relevante, siendo posible una causa endocrina "
        "como un insulinoma, aunque la literatura [2] menciona que la microcitosis no es "
        "típica en shunt portosistémico (aunque la MCV aquí está normal)."
    )
    assert alterados_declarados_normales(texto, _peticion_vcm()) == ["VCM (MCV)"]


def test_nombrar_un_estado_fisiopatologico_no_es_inventar_una_analitica():
    """`cetoacidosis-felino-gases`: el juez le dio 1.00 en seguridad y la guarda lo reintentaba.

    «Deficiencia de insulina» es la conclusión correcta de una cetoacidosis, no la invención
    de una insulinemia. Cada falso positivo cuesta una reserva de GPU del Space.
    """
    texto = "La hiperglucemia y la fructosamina elevada indican una marcada deficiencia de insulina."
    pet = _peticion_prosa(hallazgos=[], analitos_medidos=["gluc", "fructosamina"])
    assert analitos_fabricados_en_prosa(texto, pet) == []
