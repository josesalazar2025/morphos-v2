#!/usr/bin/env bash
# Corre la suite de evals contra la réplica LOCAL del Space (scripts/space_local.sh).
#
# Existe porque la corrida real tarda y falla feo si el Space no está arriba: sin la espera
# de abajo, cada caso gasta sus dos reintentos contra un puerto cerrado y la corrida entera
# se pierde en «All connection attempts failed». Aquí se comprueba UNA vez, antes de empezar.
#
# Uso:
#     scripts/evals_space.sh                      # etiqueta por defecto, split dev
#     scripts/evals_space.sh space_local_bf16     # etiqueta explícita
#     scripts/evals_space.sh mi_prueba --split test --juez ninguno
#
# Todo lo que va después de la etiqueta se pasa tal cual a run_evals.py.
#
# Las predicciones se guardan caso a caso: si la corrida muere a mitad, repetir el MISMO
# comando la reanuda desde donde iba (--reanudar) en vez de volver a generarlo todo.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ETIQUETA="${1:-space_local}"
[ $# -gt 0 ] && shift

SPACE_URL="${MORPHOS_HF_SPACE_URL:-http://127.0.0.1:7860/gradio_api}"
SALIDA="$RAIZ/evals/resultados/$(date +%F)"
mkdir -p "$SALIDA"

# --- El Space tiene que estar escuchando ---------------------------------------------------
# Se pide la raíz de Gradio, no /gradio_api: el 404 de una ruta inexistente ya demostraría que
# hay alguien al otro lado, pero la raíz responde 200 y distingue «arrancando» de «arrancado».
BASE="${SPACE_URL%/gradio_api}"
if ! curl -fsS --max-time 5 "$BASE/" >/dev/null 2>&1; then
  cat >&2 <<EOF
ERROR: no responde el Space en $BASE

Si querías la réplica local, levántala primero en OTRA terminal (Terminal.app, no el terminal
del editor: el venv y los pesos viven en el SSD externo y TCC bloquea el acceso desde ahí):

    scripts/space_local.sh

Espera a que imprima «Running on local URL» y repite este comando.

Si en cambio querías el Space de producción:

    MORPHOS_HF_SPACE_URL=https://blackmistcode-morphos-medgemma.hf.space/gradio_api \\
      scripts/evals_space.sh $ETIQUETA
EOF
  exit 1
fi

PREDS="$SALIDA/preds_$ETIQUETA.jsonl"
INFORME="$SALIDA/informe_$ETIQUETA.json"

echo "==> Space:    $BASE"
echo "==> Preds:    $PREDS"
echo "==> Informe:  $INFORME"
[ -f "$PREDS" ] && echo "==> Reanudando: ya hay $(wc -l < "$PREDS" | tr -d ' ') casos generados"
echo

# Desde backend/ porque es donde vive el proyecto uv (ver el comentario del Makefile).
cd "$RAIZ/backend"
exec env MORPHOS_HF_SPACE_URL="$SPACE_URL" \
  uv run python ../evals/run_evals.py \
    --modelo medgemma \
    --guardar-predicciones "$PREDS" \
    --reanudar \
    --informe "$INFORME" \
    "$@"
