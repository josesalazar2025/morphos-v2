"""Cortacircuitos de la ruta de IA (ARCHITECTURE_REVIEW §1.5).

El servicio ya trataba bien cada petición saturada por separado —no reintenta, responde 503 con
`Retry-After`— pero no RECORDABA nada: el siguiente usuario volvía a descubrir la cuota agotada
pagando su propia llamada, y con la ruta Claude cada descubrimiento cuesta dinero.

Las dos mitades que importan y que se fijan aquí:

- que se abra ante saturación y deje de gastar, y
- que NO se abra ante ningún otro fallo. Un modelo con un mal día no puede convertirse en una
  caída completa de la funcionalidad; para eso está el reintento correctivo.

El reloj se inyecta en vez de dormir: una prueba que espera 300 s no es una prueba.
"""

from __future__ import annotations

import pytest

from app.ai.base import ErrorModelo
from app.ai.cortacircuitos import Cortacircuitos


class Reloj:
    """Reloj monótono manual."""

    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def breaker(reloj: Reloj) -> Cortacircuitos:
    return Cortacircuitos(fallos_para_abrir=2, espera_s=300, reloj=reloj)


# --- Apertura --------------------------------------------------------------------------------

def test_cerrado_deja_pasar(breaker):
    assert breaker.permitir() is True


def test_una_saturacion_aislada_no_abre(breaker):
    """Un 429 suelto puede venir de una ráfaga ajena en la cuenta compartida."""
    breaker.registrar_saturacion()

    assert breaker.permitir() is True


def test_dos_saturaciones_abren_el_circuito(breaker):
    breaker.registrar_saturacion()
    breaker.registrar_saturacion()

    assert breaker.permitir() is False
    assert breaker.segundos_restantes() == 300


def test_un_exito_por_medio_borra_la_cuenta(breaker):
    """Los fallos que cuentan son los que describen un recurso agotado AHORA."""
    breaker.registrar_saturacion()
    breaker.registrar_exito()
    breaker.registrar_saturacion()

    assert breaker.permitir() is True


def test_mientras_esta_abierto_no_pasa_nadie(breaker, reloj):
    breaker.registrar_saturacion()
    breaker.registrar_saturacion()

    reloj.avanzar(299)

    assert breaker.permitir() is False
    assert breaker.segundos_restantes() == 1


# --- Sondeo ----------------------------------------------------------------------------------

def test_pasada_la_ventana_entra_una_sola_peticion(breaker, reloj):
    """Sin esto, al vencer la ventana salen todas de golpe contra un recurso que quizá sigue
    agotado, que es la estampida que el mecanismo debe evitar."""
    breaker.registrar_saturacion()
    breaker.registrar_saturacion()
    reloj.avanzar(300)

    assert breaker.permitir() is True, "la primera es el sondeo"
    assert breaker.permitir() is False, "las demás siguen esperando el resultado del sondeo"
    assert breaker.permitir() is False


def test_un_sondeo_con_exito_cierra_el_circuito(breaker, reloj):
    breaker.registrar_saturacion()
    breaker.registrar_saturacion()
    reloj.avanzar(300)
    breaker.permitir()

    breaker.registrar_exito()

    assert breaker.permitir() is True
    assert breaker.segundos_restantes() == 0


def test_un_sondeo_fallido_reabre_sin_acumular_otra_vez(breaker, reloj):
    """El sondeo ya demostró que sigue agotado: esperar a un segundo fallo dejaría pasar una
    petición extra a la red por cada ventana."""
    breaker.registrar_saturacion()
    breaker.registrar_saturacion()
    reloj.avanzar(300)
    breaker.permitir()

    breaker.registrar_saturacion()

    assert breaker.permitir() is False
    assert breaker.segundos_restantes() == 300


# --- Válvula de escape -----------------------------------------------------------------------

def test_con_cero_fallos_el_mecanismo_queda_desconectado(reloj):
    """`MORPHOS_IA_BREAKER_FALLOS=0` para desactivarlo sin tocar código."""
    apagado = Cortacircuitos(fallos_para_abrir=0, espera_s=300, reloj=reloj)

    for _ in range(10):
        apagado.registrar_saturacion()

    assert apagado.permitir() is True


# --- Integración con el servicio -------------------------------------------------------------

@pytest.fixture
def breaker_limpio():
    """El cortacircuitos real es un singleton de proceso: hay que dejarlo como estaba."""
    from app.ai.cortacircuitos import cortacircuitos_ia

    cortacircuitos_ia().reiniciar()
    yield cortacircuitos_ia()
    cortacircuitos_ia().reiniciar()


async def _interpretar_con_cliente(monkeypatch, cliente_falso):
    """Ejecuta `interpretar` con un cliente de modelo sustituido y sin recuperación RAG."""
    from app.ai import service
    from app.schemas import PacienteEntrada, PeticionInterpretacion

    monkeypatch.setattr(service, "_crear_cliente", lambda *a, **k: cliente_falso)
    monkeypatch.setattr(service, "recuperar", lambda *a, **k: [])
    monkeypatch.setattr(service, "recuperar_multi", lambda *a, **k: [])
    pet = PeticionInterpretacion(
        paciente=PacienteEntrada(especie="canino", raza="mestizo", edad_meses=60, sexo="macho"),
        valores={"creat": 1.2},
    )
    return await service.interpretar(pet)


class ClienteSaturado:
    nombre = "falso"
    modelo = "falso"
    prosa = False

    def __init__(self) -> None:
        self.llamadas = 0

    async def interpretar(self, sistema, mensaje, imagenes):
        self.llamadas += 1
        raise ErrorModelo("cuota agotada", reintentable=False, saturado=True)


class ClienteMalformado(ClienteSaturado):
    async def interpretar(self, sistema, mensaje, imagenes):
        self.llamadas += 1
        raise ErrorModelo("salida malformada")


async def test_el_servicio_deja_de_llamar_al_modelo_cuando_se_abre(monkeypatch, breaker_limpio):
    """Lo que justifica el mecanismo: la tercera petición ya no sale a la red."""
    cliente = ClienteSaturado()

    for _ in range(3):
        with pytest.raises(ErrorModelo):
            await _interpretar_con_cliente(monkeypatch, cliente)

    assert cliente.llamadas == 2, "la tercera debió cortarse en el cortacircuitos"


async def test_una_salida_malformada_no_abre_el_circuito(monkeypatch, breaker_limpio):
    """La otra mitad: sólo `saturado` alimenta el cortacircuitos.

    Si un fallo cualquiera abriera, un modelo devolviendo basura durante un minuto dejaría la
    herramienta muerta cinco.
    """
    cliente = ClienteMalformado()

    for _ in range(3):
        with pytest.raises(ErrorModelo):
            await _interpretar_con_cliente(monkeypatch, cliente)

    # 3 peticiones × 2 intentos (el reintento correctivo del servicio) = 6 llamadas reales.
    assert cliente.llamadas == 6
    assert breaker_limpio.permitir() is True


async def test_el_error_del_circuito_abierto_dice_cuanto_falta(monkeypatch, breaker_limpio):
    """`espera_s` es lo que el router convierte en `Retry-After`: decir 300 cuando faltan 20
    hace que un cliente honesto reintente de más."""
    cliente = ClienteSaturado()
    for _ in range(2):
        with pytest.raises(ErrorModelo):
            await _interpretar_con_cliente(monkeypatch, cliente)

    with pytest.raises(ErrorModelo) as exc:
        await _interpretar_con_cliente(monkeypatch, cliente)

    assert exc.value.saturado is True
    assert exc.value.reintentable is False
    assert 0 < exc.value.espera_s <= 300
