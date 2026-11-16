# Datasources y dashboard dentro de la imagen (COPY) en lugar de bind mounts,
# que en Codespaces no funcionan. Tras editar un archivo de provisioning/:
#   docker compose up -d --build grafana
FROM grafana/grafana:10.2.3
COPY provisioning/ /etc/grafana/provisioning/
