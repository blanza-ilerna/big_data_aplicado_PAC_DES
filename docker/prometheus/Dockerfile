# La configuración va dentro de la imagen (COPY) y no en un bind mount:
# en Codespaces el daemon Docker no ve la carpeta del workspace en la misma ruta.
FROM prom/prometheus:v2.48.1
COPY prometheus.yml /etc/prometheus/prometheus.yml
