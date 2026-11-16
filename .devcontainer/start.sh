#!/bin/bash
set -e

echo "=== [1/3] Ajustando permisos del socket Docker ==="
sudo chmod 666 /var/run/docker.sock

echo "=== [2/3] Arrancando servicios con Docker Compose ==="
# La primera vez construye las imágenes de Flink (PyFlink), Prometheus y Grafana: tarda unos minutos
docker compose up -d --build

echo "=== [3/3] Creando topic y tablas ==="
# No bloquea el arranque si algo tarda: se puede repetir con `bash scripts/init_infra.sh`
bash scripts/init_infra.sh || echo "AVISO: init_infra.sh falló; repítelo a mano cuando los servicios estén listos"

echo "=== Entorno listo ==="
echo "Siguiente paso: bash scripts/submit_flink_job.sh  y  python3 scripts/generator.py"
