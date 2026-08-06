#!/usr/bin/env bash
# Réplica LOCAL del Space de medGemma (blackmistcode/morphos_medGemma).
#
# Para qué: las evals comparan modelos, pero la ruta de producción no es «el modelo» — es el
# modelo DENTRO de la envoltura del Space (presupuesto de 3072 tokens compartido entre el
# razonamiento y la respuesta, `extract_response` que tira el razonamiento, penalización de
# repetición 1.1). Medir el GGUF en Ollama mide otra cosa. Esto levanta el `app.py` REAL del
# Space en local, así que el cliente de producción (`app/ai/hf_space.py`) habla con él sin
# cambiar una línea:
#
#     MORPHOS_HF_SPACE_URL=http://127.0.0.1:7860/gradio_api
#
# Lo único que no se replica es el hardware (MPS en vez de ZeroGPU) y, con él, la muerte por
# reserva agotada. Todo lo demás es el mismo código.
#
# Uso:
#     scripts/space_local.sh            # monta si hace falta y arranca
#     scripts/space_local.sh --recrear  # rehace el venv desde cero
#
# TODO vive en el SSD externo (venv, caché de HF con los ~9 GB de pesos, caché de uv): el disco
# interno va justo de espacio y es la razón de que los modelos estén fuera.

set -euo pipefail

BASE="${MORPHOS_SPACE_LOCAL_DIR:-/Volumes/Extreme SSD/morphos-space}"
SPACE_REPO="${MORPHOS_SPACE_REPO:-blackmistcode/morphos_medGemma}"
PUERTO="${GRADIO_SERVER_PORT:-7860}"

# El modelo es gated: hace falta el token de HF (el mismo que ya usa `hf`). Se lee de
# ~/.cache/huggingface/token si no está en el entorno.
if [ -z "${HF_TOKEN:-}" ] && [ -f "$HOME/.cache/huggingface/token" ]; then
  HF_TOKEN="$(cat "$HOME/.cache/huggingface/token")"
  export HF_TOKEN
fi

echo "==> Base: $BASE"

# --- 1. El SSD tiene que estar montado Y ser escribible -----------------------------------
VOLUMEN="$(dirname "$BASE")"
if [ ! -d "$VOLUMEN" ]; then
  echo "ERROR: no está montado '$VOLUMEN'. Conecta el disco y repite." >&2
  exit 1
fi
if ! mkdir -p "$BASE" 2>/dev/null; then
  cat >&2 <<EOF
ERROR: no se puede escribir en '$VOLUMEN'.

El volumen está montado con la propiedad ACTIVADA y su raíz es de root:wheel, así que tu
usuario no puede crear nada arriba del todo. Se arregla una vez:

    sudo mkdir -p "$BASE" && sudo chown -R "\$(id -un):staff" "$BASE"

(o Finder → Cmd-I sobre el disco → «Ignorar permisos en este volumen»)

Si en cambio el error fuera «Operation not permitted» incluso con sudo, es TCC: ejecuta este
script desde Terminal.app, no desde el terminal integrado del editor.
EOF
  exit 1
fi

# --- 2. Todas las cachés al SSD ------------------------------------------------------------
export HF_HOME="$BASE/hf-cache"
export UV_CACHE_DIR="$BASE/uv-cache"
export GRADIO_SERVER_PORT="$PUERTO"
mkdir -p "$HF_HOME" "$UV_CACHE_DIR"

# --- 3. Entorno virtual --------------------------------------------------------------------
VENV="$BASE/venv"
if [ "${1:-}" = "--recrear" ]; then
  echo "==> Borrando venv anterior"
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> Creando venv en el SSD (uv)"
  uv venv --python 3.12 "$VENV"
fi

# Las dependencias se sincronizan SIEMPRE, no sólo al crear el venv. Cuando el requirements.txt
# del Space crece, un venv ya existente se saltaba la instalación y la réplica se quedaba corta
# en silencio: así apareció `lm-format-enforcer`, sin el cual `app.py` cae al modo prosa y
# anuncia «salida estructurada NO disponible» — midiendo justo lo que el Space no hace. Con
# todo satisfecho uv resuelve y sale, sin descargar nada.
echo "==> Sincronizando dependencias (torch para MPS, transformers, gradio…)"
# `spaces` es el paquete del decorador @spaces.GPU. Fuera de HF es un passthrough; se instala
# para no tener que tocar la firma de `analyze`.
# `lm-format-enforcer` es la decodificación restringida: va en el requirements.txt del Space, así
# que sin él la réplica NO es la réplica.
VIRTUAL_ENV="$VENV" uv pip install --python "$VENV/bin/python" \
  torch transformers gradio spaces pillow safetensors "lm-format-enforcer>=0.10"

# --- 4. app.py de upstream + parche mínimo -------------------------------------------------
# Se descarga cada vez a propósito: si el Space cambia, la réplica cambia con él. El parche se
# aplica sobre el fichero recién traído y falla ruidosamente si upstream ya no encaja, que es
# justo cuando hay que mirar en vez de seguir midiendo con una copia divergente.
echo "==> Descargando app.py de $SPACE_REPO"
curl -fsSL "https://huggingface.co/spaces/$SPACE_REPO/raw/main/app.py" -o "$BASE/app_upstream.py"

"$VENV/bin/python" - "$BASE/app_upstream.py" "$BASE/app_local.py" <<'PYPATCH'
"""Aplica a app.py los cambios mínimos para correr fuera de ZeroGPU.

Cada sustitución se verifica: si upstream deja de encajar, se aborta. Una réplica que se
parchea «a medias» mediría algo que no es el Space y no lo diría.
"""
import re
import sys

origen, destino = sys.argv[1], sys.argv[2]
codigo = open(origen, encoding="utf-8").read()
deltas = []


def sustituir(patron, reemplazo, descripcion, *, obligatorio=True):
    global codigo
    # re.M porque uno de los anclajes es a principio de línea (`^MODEL_ID`), no de fichero.
    nuevo, n = re.subn(patron, reemplazo, codigo, count=1, flags=re.M)
    if n:
        codigo = nuevo
        deltas.append(descripcion)
    elif obligatorio:
        raise SystemExit(f"ERROR: no encaja el parche «{descripcion}». ¿Cambió app.py upstream?")


# 1. ZeroGPU es CUDA; aquí hay Apple Silicon. Se resuelve el dispositivo en tiempo de arranque.
sustituir(
    r'\.to\("cuda"\)',
    '.to(_dispositivo())',
    'cuda → mps/cpu',
)

# 2. transformers 5.x retiró `torch_dtype` en favor de `dtype`.
sustituir(
    r'torch_dtype=torch\.bfloat16',
    'dtype=torch.bfloat16',
    'torch_dtype → dtype (transformers 5.x)',
    obligatorio=False,
)

# 3. El resolvedor de dispositivo, justo antes de cargar el modelo.
sustituir(
    r'^MODEL_ID = ',
    'def _dispositivo():\n'
    '    """MPS si existe; si no, CPU. bfloat16 va en ambos, sólo cambia la velocidad."""\n'
    '    import torch as _t\n'
    '    return "mps" if _t.backends.mps.is_available() else "cpu"\n'
    '\n'
    'MODEL_ID = ',
    'resolvedor de dispositivo',
)

open(destino, "w", encoding="utf-8").write(codigo)
print("    parches aplicados: " + "; ".join(deltas))
PYPATCH

# --- 5. Arranque ---------------------------------------------------------------------------
cat <<EOF

==> Listo. Arrancando Gradio en http://127.0.0.1:$PUERTO
    Pesos y caché:  $HF_HOME
    La primera vez descarga ~9 GB del modelo (gated: usa tu token de HF).

    Para que las evals lo usen, en OTRA terminal:
      export MORPHOS_HF_SPACE_URL=http://127.0.0.1:$PUERTO/gradio_api

EOF
cd "$BASE"
exec "$VENV/bin/python" app_local.py
