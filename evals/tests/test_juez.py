"""Pruebas de la capa de jueces: rúbrica, transportes y selección.

Lo que se fija aquí es la regla de oro de esta capa: **un juez roto tiene que fallar fuerte**.
Si un juez que no responde, o que devuelve basura, se degradara a ceros silenciosos, la puerta
de CI registraría una regresión del modelo que nunca ocurrió.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from judge import ErrorJuez, claude_cli, ollama_local
from judge.claude_cli import ErrorJuezCLI, _extraer_json
from judge.clinical_judge import CRITERIOS, _mensaje, crear_juez, validar_rubrica

RUBRICA_OK = {
    "correccion_diferenciales": 0.8,
    "hedging_apropiado": 0.6,
    "seguridad": 1.0,
    "completitud": 0.7,
    "violacion_seguridad": False,
    "justificacion": "Razonable.",
}


# --- validar_rubrica ---

def test_rubrica_completa_se_normaliza_sin_perder_nada():
    limpia = validar_rubrica(dict(RUBRICA_OK))
    assert all(limpia[c] == RUBRICA_OK[c] for c in CRITERIOS)
    assert limpia["violacion_seguridad"] is False
    assert limpia["justificacion"] == "Razonable."


@pytest.mark.parametrize("criterio", CRITERIOS)
def test_criterio_ausente_es_error_explicito_y_no_un_cero(criterio):
    bruto = dict(RUBRICA_OK)
    del bruto[criterio]
    with pytest.raises(ErrorJuez, match=criterio):
        validar_rubrica(bruto)


@pytest.mark.parametrize("valor", ["0.8", None, True, [0.8]])
def test_criterio_no_numerico_es_error(valor):
    with pytest.raises(ErrorJuez):
        validar_rubrica({**RUBRICA_OK, "seguridad": valor})


def test_las_puntuaciones_se_recortan_al_rango_0_1():
    limpia = validar_rubrica({**RUBRICA_OK, "seguridad": 4.2, "completitud": -1.0})
    assert limpia["seguridad"] == 1.0
    assert limpia["completitud"] == 0.0


def test_la_violacion_de_seguridad_ausente_se_asume_falsa():
    bruto = dict(RUBRICA_OK)
    del bruto["violacion_seguridad"]
    assert validar_rubrica(bruto)["violacion_seguridad"] is False


def test_la_justificacion_se_acota_pero_deja_sitio_al_descuento():
    limpia = validar_rubrica({**RUBRICA_OK, "justificacion": "x" * 5000})
    assert len(limpia["justificacion"]) == 2000


def test_un_entero_es_puntuacion_valida():
    assert validar_rubrica({**RUBRICA_OK, "seguridad": 1})["seguridad"] == 1.0


# --- Mensaje al juez ---

CASO = {
    "id": "caso-x",
    "descripcion": "Azotemia en gato",
    "split": "dev",
    "validado": True,
    "paciente": {"especie": "felino"},
    "valores": {"creat": 4.0},
    "esperado": {"diferenciales_aceptables": ["enfermedad renal crónica"]},
}


def test_el_mensaje_separa_la_entrada_del_asistente_de_la_plantilla():
    msg = _mensaje(CASO, {"interpretacion": "Azotemia."})
    entrada, plantilla = msg.split("PLANTILLA DE CORRECCIÓN")
    # Lo que el asistente sí vio va arriba; los metadatos del dataset, abajo y rotulados.
    assert '"creat"' in entrada and '"felino"' in entrada
    assert "diferenciales_aceptables" not in entrada
    assert "enfermedad renal crónica" in plantilla
    assert '"split"' in plantilla and '"validado"' in plantilla


def test_el_mensaje_incluye_la_interpretacion_a_evaluar():
    assert "Azotemia leve" in _mensaje(CASO, {"interpretacion": "Azotemia leve"})


# --- Transporte CLI: desenvoltura del JSON ---

def test_json_desnudo_se_lee_tal_cual():
    assert _extraer_json('{"seguridad": 1.0}') == {"seguridad": 1.0}


def test_json_en_valla_de_codigo_se_desenvuelve():
    assert _extraer_json('```json\n{"seguridad": 1.0}\n```') == {"seguridad": 1.0}


def test_json_con_prosa_alrededor_se_rescata():
    texto = 'Aquí tienes la rúbrica:\n{"seguridad": 0.5}\nEspero que sirva.'
    assert _extraer_json(texto) == {"seguridad": 0.5}


def test_sin_json_utilizable_se_lanza_error_de_juez():
    with pytest.raises(ErrorJuezCLI):
        _extraer_json("No puedo evaluar este caso.")


def test_json_malformado_dentro_de_la_valla_tambien_falla():
    with pytest.raises(ErrorJuezCLI):
        _extraer_json('```json\n{"seguridad": }\n```')


# --- Transporte CLI: invocación ---

class ProcFalso:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_el_prompt_va_por_stdin_y_no_por_argv(monkeypatch):
    capturado = {}

    def falso_run(orden, **kw):
        capturado["orden"] = orden
        capturado["input"] = kw.get("input")
        return ProcFalso(stdout=json.dumps({"result": json.dumps(RUBRICA_OK)}))

    monkeypatch.setattr(subprocess, "run", falso_run)
    assert claude_cli.preguntar_json("SISTEMA", "MENSAJE LARGO") == RUBRICA_OK
    assert capturado["input"] == "MENSAJE LARGO"
    assert "MENSAJE LARGO" not in capturado["orden"]
    # El juez no debe arrastrar la configuración del repo donde corre.
    assert "--strict-mcp-config" in capturado["orden"]
    assert capturado["orden"][capturado["orden"].index("--max-turns") + 1] == "1"


def test_codigo_de_salida_distinto_de_cero_se_reporta_con_detalle(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ProcFalso(2, stderr="no autenticado"))
    with pytest.raises(ErrorJuezCLI, match="no autenticado"):
        claude_cli.preguntar_json("s", "m")


def test_sobre_de_error_del_cli_no_se_confunde_con_una_rubrica(monkeypatch):
    sobre = json.dumps({"is_error": True, "result": "límite de uso alcanzado"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ProcFalso(stdout=sobre))
    with pytest.raises(ErrorJuezCLI, match="límite de uso"):
        claude_cli.preguntar_json("s", "m")


def test_timeout_del_cli_es_error_de_juez(monkeypatch):
    def expira(*a, **k):
        raise subprocess.TimeoutExpired("claude", claude_cli.TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", expira)
    with pytest.raises(ErrorJuezCLI, match="no respondió"):
        claude_cli.preguntar_json("s", "m")


def test_el_modelo_del_juez_cli_es_configurable(monkeypatch):
    assert claude_cli.modelo_cli() == claude_cli.MODELO_DEFECTO
    monkeypatch.setenv("MORPHOS_JUEZ_CLI_MODELO", "opus")
    assert claude_cli.modelo_cli() == "opus"


def test_sin_binario_el_cli_no_esta_disponible(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    ok, motivo = claude_cli.disponible()
    assert ok is False and "PATH" in motivo


# --- Transporte Ollama ---

class RespuestaFalsa:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code, self.text = payload, status_code, str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http")


def test_base_url_del_juez_se_normaliza_sin_barra_final(monkeypatch):
    monkeypatch.setenv("MORPHOS_JUEZ_BASE_URL", "http://otro:11434/")
    assert ollama_local.base_url_juez() == "http://otro:11434"


def test_el_modelo_descargado_se_reconoce_aunque_falte_latest(monkeypatch):
    monkeypatch.setenv("MORPHOS_JUEZ_MODELO", "llama3")
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: RespuestaFalsa({"models": [{"name": "llama3:latest"}]})
    )
    # Ollama nombra "familia:etiqueta"; el sufijo :latest no debe decidir la disponibilidad.
    assert ollama_local.disponible() == (True, "")


def test_modelo_no_descargado_explica_como_arreglarlo(monkeypatch):
    monkeypatch.setenv("MORPHOS_JUEZ_MODELO", "qwen2.5:7b")
    monkeypatch.setattr("httpx.get", lambda *a, **k: RespuestaFalsa({"models": [{"name": "llama3"}]}))
    ok, motivo = ollama_local.disponible()
    assert ok is False and "ollama pull qwen2.5:7b" in motivo


def test_ollama_caido_no_lanza_excepcion_sino_motivo(monkeypatch):
    import httpx

    def falla(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.get", falla)
    ok, motivo = ollama_local.disponible()
    assert ok is False and "no responde" in motivo


def test_el_juez_local_pide_temperatura_cero_y_salida_estructurada(monkeypatch):
    capturado = {}

    def falso_post(url, json=None, **kw):  # noqa: A002
        capturado.update(json)
        return RespuestaFalsa({"message": {"content": '{"seguridad": 1.0}'}})

    monkeypatch.setattr("httpx.post", falso_post)
    esquema = {"type": "object"}
    assert ollama_local.preguntar_json("s", "m", esquema) == {"seguridad": 1.0}
    assert capturado["options"]["temperature"] == 0
    assert capturado["format"] is esquema
    assert capturado["stream"] is False


def test_respuesta_no_json_del_juez_local_es_error(monkeypatch):
    monkeypatch.setattr(
        "httpx.post", lambda *a, **k: RespuestaFalsa({"message": {"content": "no sé"}})
    )
    with pytest.raises(ErrorJuez, match="JSON válido"):
        ollama_local.preguntar_json("s", "m", {})


def test_http_de_error_del_juez_local_no_se_interpreta_como_rubrica(monkeypatch):
    monkeypatch.setattr("httpx.post", lambda *a, **k: RespuestaFalsa({"error": "x"}, 500))
    with pytest.raises(ErrorJuez, match="HTTP 500"):
        ollama_local.preguntar_json("s", "m", {})


# --- Selección de juez ---

def test_ninguno_desactiva_el_juez_sin_probar_transportes():
    juez, motivo = crear_juez("ninguno")
    assert juez is None and "desactivado" in motivo


def test_auto_prefiere_el_cli(monkeypatch):
    monkeypatch.setattr(claude_cli, "disponible", lambda: (True, ""))
    juez, motivo = crear_juez("auto")
    assert juez.nombre.startswith("claude-cli:")
    assert juez.concurrencia > 1  # remoto: paralelizarlo sí gana tiempo
    assert "sin clave de API" in motivo


def test_auto_cae_a_ollama_cuando_no_hay_cli(monkeypatch):
    monkeypatch.setattr(claude_cli, "disponible", lambda: (False, "sin binario"))
    monkeypatch.setattr("judge.clinical_judge.disponible", lambda: (True, ""))
    juez, motivo = crear_juez("auto")
    assert juez.nombre.startswith("ollama:")
    # El local va en serie: paralelizarlo sólo lo hace competir consigo mismo por la GPU.
    assert juez.concurrencia == 1
    assert "gratuito" in motivo


def test_una_preferencia_concreta_no_degrada_a_otro_transporte(monkeypatch):
    monkeypatch.setattr("judge.clinical_judge.disponible", lambda: (False, "sin Ollama"))
    juez, motivo = crear_juez("ollama")
    assert juez is None
    assert "ollama no disponible" in motivo


def test_sin_ningun_transporte_se_explica_por_que(monkeypatch):
    monkeypatch.setattr(claude_cli, "disponible", lambda: (False, "sin binario"))
    monkeypatch.setattr("judge.clinical_judge.disponible", lambda: (False, "sin Ollama"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MORPHOS_ANTHROPIC_API_KEY", raising=False)
    juez, motivo = crear_juez("auto")
    assert juez is None
    assert "sin binario" in motivo and "sin Ollama" in motivo and "ANTHROPIC_API_KEY" in motivo
