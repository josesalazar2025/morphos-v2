#!/bin/sh
set -e

# La BD de usuarios y el índice RAG viven en instance/ (fuera del webroot).
# El backend crea el esquema al arrancar (lifespan). Aquí sólo garantizamos el
# directorio y avisamos si falta configuración de producción crítica.
mkdir -p /app/instance

if [ "${MORPHOS_ENTORNO}" = "prod" ]; then
  if [ -z "${MORPHOS_SESSION_SECRET}" ]; then
    echo "ERROR: MORPHOS_SESSION_SECRET no está definido en prod. Aborta." >&2
    exit 1
  fi
fi

exec "$@"
