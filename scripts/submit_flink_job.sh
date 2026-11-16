#!/usr/bin/env bash
# Envía scripts/flink_job.py al clúster Flink.
#
#   bash scripts/submit_flink_job.sh            # lo lanza si no está ya en ejecución
#   bash scripts/submit_flink_job.sh --restart  # cancela el que haya y lo relanza
#   bash scripts/submit_flink_job.sh --cancel   # solo lo cancela
#
# Nunca lanza un segundo job si ya hay uno corriendo: dos jobs con el mismo
# consumer group escribirían ventanas duplicadas en PostgreSQL.
set -euo pipefail
cd "$(dirname "$0")/.."

JM=bigdata-flink-jobmanager
JOB_NAME=ventas-ventanas-30s
MODE=${1:-}

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

echo "== [1/4] Esperando al JobManager =="
for _ in $(seq 1 60); do
    docker exec "$JM" curl -sf http://localhost:8081/overview >/dev/null 2>&1 && break
    sleep 2
done
docker exec "$JM" curl -sf http://localhost:8081/overview >/dev/null \
    || { echo "ERROR: el JobManager no responde" >&2; exit 1; }

echo "== [2/4] Jobs en ejecución =="
JIDS=$(running_jobs)
if [[ -n "$JIDS" ]]; then
    if [[ "$MODE" == "--restart" || "$MODE" == "--cancel" ]]; then
        for jid in $JIDS; do
            echo "Cancelando $jid"
            docker exec "$JM" flink cancel "$jid"
        done
    else
        echo "El job '$JOB_NAME' ya está en ejecución ($JIDS). Usa --restart para relanzarlo."
        exit 0
    fi
else
    echo "Ninguno"
fi
[[ "$MODE" == "--cancel" ]] && exit 0

echo "== [3/4] Topic y tablas =="
bash scripts/init_infra.sh

echo "== [4/4] Enviando el job =="
docker cp scripts/flink_job.py "$JM":/opt/flink/usrlib/flink_job.py
docker exec "$JM" flink run -d -py /opt/flink/usrlib/flink_job.py

echo
echo "Job enviado. Compruébalo en la UI de Flink (puerto 8083) o con:"
echo "  docker exec $JM curl -s http://localhost:8081/jobs/overview | python3 -m json.tool"
