#!/usr/bin/env bash
# Prepara la infraestructura que necesitan los scripts (idempotente):
#   1. crea el topic ventas_topic en Redpanda si no existe
#   2. crea las tablas de resultados en PostgreSQL (sql/schema.sql)
set -euo pipefail
cd "$(dirname "$0")/.."

REDPANDA=bigdata-redpanda
POSTGRES=bigdata-postgres
TOPIC=ventas_topic

wait_for() {  # wait_for <descripción> <comando...>
    local desc=$1; shift
    for _ in $(seq 1 60); do
        if "$@" >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    echo "ERROR: $desc no responde tras 120 s" >&2
    return 1
}

echo "-> Esperando a Redpanda..."
wait_for "Redpanda" docker exec "$REDPANDA" rpk cluster info
if docker exec "$REDPANDA" rpk topic describe "$TOPIC" >/dev/null 2>&1; then
    echo "   Topic $TOPIC ya existe"
else
    docker exec "$REDPANDA" rpk topic create "$TOPIC" -p 1 -r 1
fi

echo "-> Esperando a PostgreSQL..."
wait_for "PostgreSQL" docker exec "$POSTGRES" pg_isready -U bigdata_user -d bigdata
docker exec -i "$POSTGRES" psql -q -v ON_ERROR_STOP=1 -U bigdata_user -d bigdata < sql/schema.sql
echo "   Tablas listas"
