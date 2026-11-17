#!/usr/bin/env bash
# Envía scripts/flink_job.py al clúster Flink.
#
#   bash scripts/submit_flink_job.sh                 # lo lanza si no está ya en ejecución
#   bash scripts/submit_flink_job.sh --restart       # lo para con savepoint y lo relanza desde él
#   bash scripts/submit_flink_job.sh --restart-clean # lo cancela y lo relanza sin estado
#   bash scripts/submit_flink_job.sh --cancel        # lo para (con savepoint)
#
# --restart conserva las ventanas a medio calcular. Si has cambiado mucho las
# consultas SQL y el job falla al arrancar desde el savepoint, usa --restart-clean:
# continúa desde los offsets guardados en Kafka y, como el destino es upsert,
# tampoco duplica ventanas.
#
# Nunca lanza un segundo job si ya hay uno corriendo.
set -euo pipefail
cd "$(dirname "$0")/.."

JM=bigdata-flink-jobmanager
JOB_NAME=ventas-ventanas-30s
SAVEPOINT_DIR=file:///opt/flink/checkpoints/savepoints
MODE=${1:-}

case "$MODE" in
    ""|--restart|--restart-clean|--cancel) ;;
    *) echo "Uso: $0 [--restart | --restart-clean | --cancel]" >&2; exit 2 ;;
esac

running_jobs() {
    # Ojo: /jobs/overview usa el campo "state" (/jobs usa "status")
    docker exec "$JM" curl -sf http://localhost:8081/jobs/overview | python3 -c '
import json, sys
name = sys.argv[1]
jobs = json.load(sys.stdin).get("jobs", [])
active = {"INITIALIZING", "CREATED", "RUNNING", "RESTARTING"}
print(" ".join(j["jid"] for j in jobs if j["name"] == name and j["state"] in active))
' "$JOB_NAME"
}

# Para el job tomando un savepoint; imprime la ruta del savepoint (vacío si falla)
stop_with_savepoint() {
    local jid=$1 out
    if out=$(docker exec "$JM" flink stop --savepointPath "$SAVEPOINT_DIR" "$jid" 2>&1); then
        echo "$out" | sed -n 's/.*Savepoint completed\. Path: \([^ ]*\).*/\1/p' | tail -1
    else
        echo "$out" >&2
    fi
}

echo "== [1/4] Esperando al JobManager =="
for _ in $(seq 1 60); do
    docker exec "$JM" curl -sf http://localhost:8081/overview >/dev/null 2>&1 && break
    sleep 2
done
docker exec "$JM" curl -sf http://localhost:8081/overview >/dev/null \
    || { echo "ERROR: el JobManager no responde" >&2; exit 1; }

echo "== [2/4] Jobs en ejecución =="
SAVEPOINT=""
JIDS=$(running_jobs)
if [[ -n "$JIDS" ]]; then
    case "$MODE" in
        "")
            echo "El job '$JOB_NAME' ya está en ejecución ($JIDS). Usa --restart para relanzarlo."
            exit 0 ;;
        --restart-clean)
            for jid in $JIDS; do echo "Cancelando $jid"; docker exec "$JM" flink cancel "$jid"; done ;;
        --restart|--cancel)
            for jid in $JIDS; do
                echo "Parando $jid con savepoint..."
                SAVEPOINT=$(stop_with_savepoint "$jid")
                if [[ -n "$SAVEPOINT" ]]; then
                    echo "Savepoint: $SAVEPOINT"
                else
                    echo "AVISO: no se pudo tomar el savepoint; se cancela sin estado"
                    docker exec "$JM" flink cancel "$jid" || true
                fi
            done ;;
    esac
else
    echo "Ninguno"
fi
[[ "$MODE" == "--cancel" ]] && exit 0

echo "== [3/4] Topic y tablas =="
bash scripts/init_infra.sh

echo "== [4/4] Enviando el job =="
docker cp scripts/flink_job.py "$JM":/opt/flink/usrlib/flink_job.py
if [[ -n "$SAVEPOINT" ]]; then
    # -n (--allowNonRestoredState): tolera operadores del savepoint que ya no existen
    docker exec "$JM" flink run -d -s "$SAVEPOINT" -n -py /opt/flink/usrlib/flink_job.py
else
    docker exec "$JM" flink run -d -py /opt/flink/usrlib/flink_job.py
fi

echo
echo "Job enviado. Compruébalo en la UI de Flink (puerto 8083) o con:"
echo "  docker exec $JM curl -s http://localhost:8081/jobs/overview | python3 -m json.tool"
