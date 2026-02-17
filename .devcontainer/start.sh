#!/bin/bash
set -e

echo "=== [1/2] Ajustando permisos del socket Docker ==="
sudo chmod 666 /var/run/docker.sock

echo "=== [2/2] Arrancando servicios con Docker Compose ==="
docker compose up -d

echo "=== Entorno listo ==="
