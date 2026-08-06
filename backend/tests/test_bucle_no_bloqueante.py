"""El trabajo síncrono y caro no puede correr en el bucle de eventos.

`interpretar` es `async`, pero sus dos operaciones más caras son SÍNCRONAS: la recuperación RAG
(embedding bge-m3 + LanceDB + cross-encoder sobre hasta `rag_candidatos` filas, segundos en
cpu-basic) y todo SQLite/scrypt en los endpoints de auth. Llamadas directamente desde una
corrutina, bloquean el proceso ENTERO mientras duran: ni health check, ni el login de otro
veterinario, ni una ingesta del puente. La concurrencia efectiva era 1 en una app que se
anuncia multiusuario.

Estas pruebas miden la propiedad, no la implementación: si alguien sustituye un
`await asyncio.to_thread(...)` por la llamada directa, vuelven a fallar. Los márgenes son
holgados a propósito —miden concurrencia, no latencia— para que no parpadeen en CI.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.ai import service
from app.ai.base import ErrorModelo  # noqa: F401  (documenta la superficie que se falsea)
from app.schemas import InterpretacionClinica, PeticionInterpretacion

BLOQUEO_S = 0.4

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


class ClienteInstantaneo:
    """Cliente de modelo que responde sin coste: aquí se mide la recuperación, no la generación."""

    nombre = "medgemma-hf"
    prosa = True
    modelo = "hf-space"

    async def interpretar(self, *_a, **_k):
        return InterpretacionClinica(interpretacion="ok " * 20, requiere_derivacion=True)


@pytest.fixture
def rag_lento(monkeypatch):
    """Retriever síncrono y lento, como el real: `time.sleep` bloquea el hilo que lo ejecute."""

    def _recuperar_bloqueante(*_a, **_k):
        time.sleep(BLOQUEO_S)
        return []

    for nombre in ("recuperar", "recuperar_multi"):
        monkeypatch.setattr(service, nombre, _recuperar_bloqueante)
    monkeypatch.setattr(service, "_crear_cliente", lambda *_: ClienteInstantaneo())


async def _contar_latidos(tarea: asyncio.Task, intervalo: float = 0.005) -> int:
    """Cuántas veces consigue despertarse el bucle mientras `tarea` está en curso.

    Es la medición directa de «¿puede el servidor atender a alguien más?». Con el trabajo
    bloqueante en el bucle, el contador se queda en ~0.
    """
    latidos = 0
    while not tarea.done():
        await asyncio.sleep(intervalo)
        latidos += 1
    return latidos


async def test_la_recuperacion_no_congela_el_bucle(rag_lento):
    """Durante una interpretación, el bucle sigue despertándose para atender otras cosas."""
    tarea = asyncio.create_task(service.interpretar(PeticionInterpretacion.model_validate(PETICION)))
    latidos = await _contar_latidos(tarea)
    await tarea

    # Con to_thread caben ~80 latidos de 5 ms en 0.4 s; en el bucle serían 0 o 1.
    assert latidos > 10, (
        f"sólo {latidos} latidos durante la recuperación: el bucle estuvo bloqueado, "
        "la recuperación volvió a ejecutarse sin asyncio.to_thread"
    )


async def test_dos_interpretaciones_se_solapan(rag_lento):
    """Dos peticiones concurrentes no se serializan: comparten el tiempo de recuperación."""
    inicio = time.perf_counter()
    await asyncio.gather(
        service.interpretar(PeticionInterpretacion.model_validate(PETICION)),
        service.interpretar(PeticionInterpretacion.model_validate(PETICION)),
    )
    transcurrido = time.perf_counter() - inicio

    # Serializadas costarían >= 2*BLOQUEO_S; solapadas, algo más de BLOQUEO_S.
    assert transcurrido < BLOQUEO_S * 1.7, (
        f"{transcurrido:.2f}s para dos interpretaciones de {BLOQUEO_S}s: se serializaron"
    )


async def test_el_alta_no_congela_el_bucle(alta_abierta):
    """scrypt (n=2**14) es caro A PROPÓSITO; en el bucle, cada alta congela el servicio."""
    import httpx

    from app import db
    from app.main import app

    # ASGITransport no dispara el lifespan (TestClient sí), así que la tabla no existiría.
    db.inicializar_db()

    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://test") as cliente:
        tarea = asyncio.create_task(
            cliente.post(
                "/api/auth/registro",
                json={
                    "nombre": "Hilo",
                    "apellido": "Vet",
                    "email": "hilo@example.com",
                    "password": "clave-segura-1",
                },
            )
        )
        latidos = await _contar_latidos(tarea, intervalo=0.002)
        resp = await tarea

    assert resp.status_code == 200, resp.text
    assert latidos > 3, (
        f"sólo {latidos} latidos durante el alta: scrypt volvió a correr en el bucle de eventos"
    )
