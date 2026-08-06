"""El puerto Python del suelo de seguridad coincide con el motor TS validado por veterinario.

`app/motor/gravedad.py` es una SEGUNDA implementación de los rangos y la gravedad de
`frontend/src/analisis.ts`. Se aceptó esa duplicación a cambio de no meter Node en la imagen de
producción ni portar las 1062 líneas del motor entero (sólo se portó lo que sostiene el suelo de
derivación, ~250). El riesgo obvio de tener dos implementaciones es que diverjan en silencio:
alguien afina un umbral en el TS y el suelo del servidor se queda con el viejo, sin que nada falle.

Esta prueba es el guardarraíl de esa decisión: ejecuta el motor REAL por el puente que ya usan
las evals (`evals/engine_runner.ts`) y compara clave a clave con el puerto. Se omite donde no
haya Node —igual que las pruebas de RAG se omiten sin índice— porque ahí no puede afirmar nada.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app.config import RAIZ_REPO
from app.motor.gravedad import evaluar
from app.schemas import PacienteEntrada

RUNNER = RAIZ_REPO / "evals" / "engine_runner.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not RUNNER.exists(),
    reason="requiere Node y evals/engine_runner.ts",
)

# Casos elegidos por lo que DECIDEN, no por cubrir analitos: cada uno toca una regla que, si
# diverge, cambia si se deriva o no.
CASOS = [
    ({"hct": 12.0}, {"especie": "canino"}),                                  # corte bajo: grave
    ({"hct": 25.0}, {"especie": "canino"}),                                  # corte bajo: moderado
    ({"hct": 34.0}, {"especie": "canino"}),                                  # corte bajo: leve
    ({"plt": 25.0}, {"especie": "felino"}),                                  # trombocitopenia grave
    ({"creat": 6.0}, {"especie": "canino"}),                                 # IRIS 4 → grave
    ({"creat": 2.0}, {"especie": "canino"}),                                 # IRIS 2 → leve
    ({"fosf": 8.0}, {"especie": "canino", "edad_meses": 4}),                 # ajuste cachorro
    ({"fosf": 8.0}, {"especie": "canino", "edad_meses": 48}),                # sin ajuste
    ({"plt": 160.0}, {"especie": "canino", "raza": "Galgo"}),                # ajuste lebrel
    ({"plt": 160.0}, {"especie": "canino", "raza": "Mestizo"}),
    ({"t4_total": 1.0}, {"especie": "canino", "raza": "greyhound"}),         # falso hipotiroidismo
    ({"vcm": 58.0}, {"especie": "canino", "raza": "Shiba Inu"}),             # grupos combinados
    ({"bun": 40.0}, {"especie": "canino", "edad_meses": 130}),               # geriátrico
    ({"wbc": 30.0}, {"especie": "felino", "edad_meses": 5}),
    ({"hct": 20.0, "hgb": 6.0, "rbc": 3.0}, {"especie": "felino"}),          # panel múltiple
    ({"hct": 45.0, "creat": 1.0, "alt": 40.0}, {"especie": "canino"}),       # todo normal
    ({"upc": 1.2}, {"especie": "canino"}),                                   # tope en moderado
    ({"sdma": 60.0}, {"especie": "felino"}),
]


def _motor_ts(valores: dict, paciente: dict) -> dict[str, str]:
    entrada = json.dumps({
        "valores": valores,
        "paciente": {
            "especie": paciente.get("especie"),
            "raza": paciente.get("raza"),
            "edad_meses": paciente.get("edad_meses"),
            "sexo": paciente.get("sexo"),
        },
    })
    proc = subprocess.run(
        ["node", "--experimental-strip-types", str(RUNNER)],
        input=entrada, capture_output=True, text=True, cwd=RAIZ_REPO,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    return {h["clave"]: h["gravedad"] for h in json.loads(proc.stdout)["hallazgos"]}


@pytest.mark.parametrize(("valores", "paciente"), CASOS)
def test_el_puerto_coincide_con_el_motor_real(valores, paciente):
    esperado = _motor_ts(valores, paciente)
    obtenido = {
        h.clave: h.gravedad.value
        for h in evaluar(valores, PacienteEntrada.model_validate(paciente))
    }
    assert obtenido == esperado, (
        "el puerto Python y analisis.ts discrepan: si el cambio del TS es intencionado, "
        "replícalo en app/motor/gravedad.py"
    )
