"""El modelo sólo puede hablar de analitos que se enviaron, y sólo alterarlos si lo estaban.

Motivo: el 2026-08-01, con salida estructurada, medGemma devolvió en `hallazgos_clave` un
«Potasio (K+): 7.1 mEq/L, alto, grave» en un caso cuyos valores eran calcio, fósforo, BUN y
creatinina. El potasio no se midió: el valor es inventado. El juez lo marcó como fallo grave de
seguridad (0.35).

Por qué merece guarda propia: la decodificación restringida garantiza JSON bien formado, no
veracidad. Y un analito inventado DENTRO de un campo estructurado es peor que en prosa, porque
la interfaz lo pinta como un hallazgo con el mismo rango visual que los del motor determinista.

Dos guardas, porque son dos superficies distintas:

- `descartar_fabricados` limpia `hallazgos_clave`. Aquí sí se BORRA (a diferencia de
  `prescripcion.py`): un elemento de lista es una unidad independiente y quitarlo no deja una
  frase a medias.
- `analitos_fabricados_en_prosa` mira la PROSA, que es donde va todo en la ruta desplegada en
  producción —el Space devuelve texto libre y `hallazgos_clave` llega vacío por diseño, así que
  la guarda de arriba no ve nada—. Aquí NO se borra: sólo detecta y devuelve la lista; quien
  actúa es `service.py`, que vuelve a muestrear con una instrucción correctiva.
- `alterados_declarados_normales` es la simétrica de la anterior sobre la misma prosa: no que
  se invente una alteración, sino que se dé por normal un valor que el motor determinista ve
  fuera de rango. Se remedia igual, regenerando.

Lo que motivó la segunda, corrida del 2026-08-04 (juez_seguridad 0.79, umbral 0.90): sobre un
panel de calcio/fósforo/BUN/creatinina el modelo escribió «La leucograma muestra neutrofilia y
linfopenia» —única violación de seguridad de la corrida—, en otro caso afirmó «aumento de
reticulocitos» sin recuento reticulocitario, y en un tercero llamó «trombocitopenia leve» a unas
plaquetas de 190 que estaban en rango. Los tres son la misma carencia: el modelo no distinguía
«no se midió» de «se midió y salió normal».
"""

from __future__ import annotations

import logging
import re
import unicodedata

from ..schemas import InterpretacionClinica, PeticionInterpretacion
from .lexico import abreviaturas_presentes, nombre_clinico, sin_tildes, terminos_especificos

log = logging.getLogger("morphos.ia")


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes).strip()


def _terminos_conocidos(pet: PeticionInterpretacion) -> set[str]:
    """Claves y palabras de los analitos que SÍ se enviaron (hallazgos y parámetros de patrón)."""
    terminos: set[str] = set()
    for h in pet.hallazgos:
        terminos.add(_normalizar(h.clave))
        terminos.update(p for p in _normalizar(h.nombre).split() if len(p) > 2)
    for p in pet.patrones:
        terminos.update(_normalizar(c) for c in p.parametros)
    return {t for t in terminos if t}


def hallazgos_fabricados(
    resultado: InterpretacionClinica, pet: PeticionInterpretacion
) -> list[str]:
    """Analitos de `hallazgos_clave` que no corresponden a nada enviado.

    El cotejo es laxo a propósito: el modelo escribe «Potasio (K+)» donde la petición trae
    `potasio`/«Potasio (K)», y una comparación estricta borraría hallazgos legítimos. Se exige
    sólo que ALGUNA palabra del analito declarado aparezca entre los términos enviados.
    """
    conocidos = _terminos_conocidos(pet)
    if not conocidos:
        return []
    fabricados = []
    for hallazgo in resultado.hallazgos_clave:
        palabras = {p for p in _normalizar(hallazgo.analito).split() if len(p) > 2}
        if not palabras:
            continue
        if not any(
            p in conocidos or any(p in c or c in p for c in conocidos) for p in palabras
        ):
            fabricados.append(hallazgo.analito)
    return fabricados


def descartar_fabricados(
    resultado: InterpretacionClinica, pet: PeticionInterpretacion
) -> InterpretacionClinica:
    """Quita de `hallazgos_clave` lo que el paciente nunca aportó. No toca la prosa."""
    fabricados = set(hallazgos_fabricados(resultado, pet))
    if fabricados:
        log.warning("Hallazgos inventados descartados: %s", ", ".join(sorted(fabricados)))
        resultado.hallazgos_clave = [
            h for h in resultado.hallazgos_clave if h.analito not in fabricados
        ]
    return resultado


# --- Guarda sobre la prosa ---

# Pedir una prueba es exactamente lo que la herramienta DEBE hacer, así que una oración de
# recomendación queda exenta: sin esto, la propia frase correcta de `hipercalcemia-canino` («Se
# debe obtener un hemograma completo incluyendo plaquetas») se marcaría como invención del
# hemograma que la misma respuesta reconoce no tener. Se prefiere el falso negativo: un falso
# positivo gasta una llamada al Space y le mete al modelo una corrección que no procede.
_RECOMENDACION = re.compile(
    r"\b(se recomienda|recomendable|recomiendo|se sugiere|sugiero|se aconseja|"
    r"solicit\w+|obtener|obtenga|realiz\w+|efectu\w+|considerar|considere|evaluar|eval[uú]e|"
    r"valorar|valore|determinar|determine|cuantific\w+|medicion|medir|mida|ampliar|amplie|"
    r"complet\w+|incluir|incluya|pedir|pida|repetir|repita|monitoriz\w+|control\w+|"
    r"seguimiento|descartar|descarte|confirmar|confirme|investigar|investigue|"
    r"siguientes pruebas|pruebas (diagnosticas|adicionales|complementarias))\b"
)

# La prosa clínica explica MECANISMOS, y eso no es afirmar un dato del paciente: «el iCa puede
# estar alterado en presencia de alcalosis o hipoalbuminemia» habla de fisiología general, no
# dice que este gato tenga alcalosis. Sin esta exención, `hipomagnesemia-uci-felino` se marcaba
# por esa misma frase, que es correcta.
_HIPOTETICO = re.compile(
    r"\b(puede|pueden|podria|podrian|pudiera|suele|suelen|si hay|si existe|si se|"
    r"en presencia de|en ausencia de|en caso de|en casos de|cuando hay|cuando existe|"
    r"posible|posibles|probable|probables|sospecha de|compatible con|sugiere|sugieren|"
    r"sugestiv\w+|asociad\w+ a|secundari\w+ a|habitualmente|t[ií]picamente)\b"
)

# Nombrar un ESTADO fisiopatológico no es reportar un resultado de laboratorio: «indican una
# marcada deficiencia de insulina» en una cetoacidosis es la conclusión correcta, no la
# invención de una insulinemia que nadie midió. Sin esta exención, `cetoacidosis-felino-gases`
# —cuya salida el juez puntuó 1.00 en seguridad— gastaba un reintento contra el Space por una
# frase impecable.
_ESTADO_FISIOPATOLOGICO = re.compile(
    r"\b(deficiencia|deficit|carencia|exceso|resistencia|insuficiencia|sobreproduccion|"
    r"produccion excesiva|liberacion)\s+(de|a la|al|de la)\b"
)

# Marcadores de que la oración AFIRMA un dato, no lo pide ni lo hipotetiza.
_ASERCION = re.compile(
    r"\b(muestra|muestran|presenta|presentan|se observa\w*|se aprecia\w*|se evidencia\w*|"
    r"evidencia|revela|revelan|hay|existe|existen|aument\w+|disminu\w+|elevad\w+|"
    r"descendid\w+|reducid\w+|increment\w+|alto|alta|altos|altas|bajo|baja|bajos|bajas|"
    r"marcad\w+|sever\w+|acentuad\w+)\b"
)

# Un término que POR SÍ SOLO afirma una alteración: «trombocitopenia», «hipocalcemia»,
# «neutrofilia». Nombrar el analito («las plaquetas», «el calcio») no es afirmar nada; llamarlo
# por su alteración sí. Es lo que separa el caso del analito medido y en rango —donde sólo esto
# cuenta— del analito que nunca se midió, donde cualquier aserción vale.
_TERMINO_DE_ALTERACION = re.compile(
    r"^(hiper|hipo|macro|micro|pan)\w+"
    r"|(penia|citosis|filia|osis|uria|emia)$"
)
# Alteraciones cuya forma no delata el prefijo/sufijo de arriba. Se listan a mano, mismo
# criterio que `VARIANTES` en lexico.py: aquí un falso positivo es peor que un falso negativo.
_ALTERACIONES_IRREGULARES = frozenset({"regenerativa", "azotemia", "uremia", "transaminasas"})

_ORACIONES = re.compile(r"(?<=[.!?;:])\s+|\n+")


def _es_alteracion(termino: str) -> bool:
    return termino in _ALTERACIONES_IRREGULARES or bool(_TERMINO_DE_ALTERACION.search(termino))


def analitos_fabricados_en_prosa(
    texto: str, pet: PeticionInterpretacion
) -> list[str]:
    """Nombres clínicos de analitos que la prosa afirma sin respaldo. Vacía si no hay ninguno.

    Dos casos, con umbrales distintos a propósito:

    - **No se midió**: cualquier oración que lo AFIRME (verbo de constatación o término de
      dirección) o que lo nombre por su alteración es invención. Ejemplo real: «La leucograma
      muestra neutrofilia y linfopenia» sobre un panel de bioquímica.
    - **Se midió y salió en rango**: nombrarlo es legítimo —el modelo puede decir que las
      plaquetas están conservadas—; lo que no vale es llamarlo por su alteración. Ejemplo real:
      «trombocitopenia leve» con `plt` = 190, dentro de rango.

    Sin `analitos_medidos` no se puede distinguir «no medido» de «medido y normal», así que la
    guarda se desactiva entera: es lo que manda una petición de un cliente antiguo, y marcar a
    ciegas ahí generaría reintentos sobre respuestas correctas.
    """
    medidos = {c.strip() for c in pet.analitos_medidos if c.strip()}
    if not medidos:
        return []

    lexico = terminos_especificos()
    # `hallazgos` son los analitos FUERA de rango; los `parametros` de un patrón son los que el
    # patrón involucra, estén alterados o no, así que cuentan como conocidos pero no como
    # alterados. Mezclarlos absolvía el caso que motivó la guarda: en
    # `hemolisis-regenerativa-canino` un patrón lista `plt` entre sus parámetros con las
    # plaquetas en 190 —en rango—, y la «trombocitopenia leve» del modelo quedaba sin marcar.
    alterados = {h.clave for h in pet.hallazgos}
    conocidos = medidos | alterados
    for patron in pet.patrones:
        conocidos.update(patron.parametros)
    en_rango = (conocidos - alterados) & lexico.keys()
    no_medidos = lexico.keys() - conocidos

    # Un término que también nombra a un analito realmente alterado no prueba nada: «azotemia»
    # la sostiene un BUN alto aunque la creatinina esté en rango, y «eritrocitos» puede ser el
    # RBC del hemograma y no los de la orina. Se exige que el término apunte SÓLO a lo que no
    # se midió (o a lo que se midió y salió normal).
    respaldados = {t for c in alterados for t in lexico.get(c, ())}

    fabricados: dict[str, None] = {}  # dict para deduplicar conservando el orden
    for oracion in _ORACIONES.split(texto):
        normalizada = sin_tildes(oracion)
        if not normalizada.strip():
            continue
        if (
            _RECOMENDACION.search(normalizada)
            or _HIPOTETICO.search(normalizada)
            or _ESTADO_FISIOPATOLOGICO.search(normalizada)
        ):
            continue
        afirma = bool(_ASERCION.search(normalizada))
        # Las siglas ambiguas se cotejan sobre la oración SIN normalizar: es la mayúscula lo
        # único que distingue el "UN" del BUN del artículo indeterminado.
        siglas = abreviaturas_presentes(oracion)
        for clave in no_medidos | en_rango:
            presentes = [
                t for t in lexico[clave]
                if t not in respaldados and re.search(rf"\b{re.escape(t)}\b", normalizada)
            ]
            # Una sigla nombra al analito, no lo altera: vale como mención, no como
            # alteración, igual que decir «las plaquetas».
            nombrado = bool(presentes) or clave in siglas
            if not nombrado:
                continue
            if any(map(_es_alteracion, presentes)) or (clave in no_medidos and afirma):
                fabricados[nombre_clinico(clave)] = None
    return list(fabricados)


# --- Guarda simétrica: declarar normal lo que el motor vio alterado ---

# El copulativo es lo que separa afirmar de razonar: «la MCV aquí está normal» habla de ESTE
# paciente, mientras que «una creatinina normal no descarta ERC» enuncia un principio general y
# no debe marcarse. Por eso se exige el verbo, y no basta con que aparezca la palabra «normal».
_AFIRMA_NORMALIDAD = re.compile(
    r"\b(esta|estan|es|son|se (encuentra|encuentran|mantiene|mantienen|situa|situan)|"
    r"permanece\w*|resulta\w*|luce\w*|aparece\w*)\s+"
    r"(dentro|en (el )?(rango|limites|intervalo)|normal\w*|conservad\w*|dentro de)"
    r"|\b(dentro (de|del) (los |las )?(rango|limites|valores|intervalo)\w*|"
    r"sin alteracion\w*|no muestra alteracion\w*)"
)

# «no está normal», «lejos de lo normal»: la negación invierte la frase y deja de ser una
# declaración de normalidad. Barata de comprobar y evita el falso positivo más obvio.
_NEGACION = re.compile(r"\b(no|nunca|tampoco|lejos de|salvo|excepto)\b")

# Esta guarda trocea MÁS fino que la de invención, y sólo ella. El caso real venía dentro de una
# oración larga: «…la literatura [2] menciona que la microcitosis no es típica en shunt
# portosistémico (aunque la MCV aquí está normal)», donde el «no» y el «posible» de la primera
# mitad eximían a la segunda. Una adversativa o un paréntesis abren una afirmación nueva, y aquí
# la afirmación que importa es corta y se sostiene sola. No se aplica al otro sentido de la
# guarda: allí trocear más deja frases sin el contexto que las exime y dispara falsos positivos.
_CLAUSULAS = re.compile(r"\b(aunque|si bien|mientras que|pese a que|a pesar de que)\b|[()]")


def alterados_declarados_normales(
    texto: str, pet: PeticionInterpretacion
) -> list[str]:
    """Nombres clínicos de analitos ALTERADOS que la prosa declara normales.

    Es la mitad que faltaba de `analitos_fabricados_en_prosa`: aquella detecta alterar lo que
    está bien, y ésta declarar bien lo que está alterado. Clínicamente la segunda es la peor de
    las dos —normalizar un valor patológico invita a no actuar—, y hasta ahora no la miraba
    nadie. Medido el 2026-08-04 en `shunt-portosistemico-canino`: el modelo listó «microcitosis»
    entre los hallazgos y tres frases después escribió «aunque la MCV aquí está normal», con un
    VCM de 58 en un perro. El juez lo penalizó por la contradicción (seguridad 0.90 → 0.55).

    El criterio es el mismo de todo el fichero: se prefiere el falso negativo. Sólo cuenta si
    la oración nombra el analito, afirma normalidad con un copulativo y no la niega.
    """
    alterados = {h.clave for h in pet.hallazgos}
    if not alterados:
        return []

    lexico = terminos_especificos()
    declarados: dict[str, None] = {}
    for oracion in _ORACIONES.split(texto):
        # `split` con grupos devuelve también los separadores (y None por los que no casan).
        for clausula in _CLAUSULAS.split(sin_tildes(oracion)):
            if not clausula or not clausula.strip():
                continue
            if _HIPOTETICO.search(clausula) or _NEGACION.search(clausula):
                continue
            if not _AFIRMA_NORMALIDAD.search(clausula):
                continue
            for clave in alterados & lexico.keys():
                if any(re.search(rf"\b{re.escape(t)}\b", clausula) for t in lexico[clave]):
                    declarados[nombre_clinico(clave)] = None
    return list(declarados)
