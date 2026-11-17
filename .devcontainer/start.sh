#!/bin/bash
set -e

echo "=== [1/4] Ajustando permisos del socket Docker ==="
sudo chmod 666 /var/run/docker.sock

echo "=== [2/4] Arrancando servicios con Docker Compose ==="
# La primera vez construye las imágenes de Flink (PyFlink), Prometheus y Grafana: tarda unos minutos
docker compose up -d --build

# Los pasos 3 y 4 no bloquean el arranque: si fallan se pueden repetir a mano
echo "=== [3/4] Creando topic y tablas ==="
bash scripts/init_infra.sh \
    || echo "AVISO: init_infra.sh falló; repítelo con: bash scripts/init_infra.sh"

echo "=== [4/4] Enviando el job de Flink (si no está ya en ejecución) ==="
# Al parar el Codespace el JobManager se reinicia y el job desaparece: aquí se relanza.
# Continúa desde los offsets guardados en Kafka, así que no se pierden ni duplican ventanas.
bash scripts/submit_flink_job.sh \
    || echo "AVISO: no se pudo enviar el job; repítelo con: bash scripts/submit_flink_job.sh"

echo "=== Entorno listo ==="
echo "Siguiente paso: python3 scripts/generator.py"
