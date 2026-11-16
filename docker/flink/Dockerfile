# Flink 1.18.1 + PyFlink + conectores Kafka y JDBC (PostgreSQL)
# La imagen base usa Ubuntu 22.04 (jammy) -> Python 3.10, soportado por PyFlink 1.18.
FROM flink:1.18.1-scala_2.12-java11

ARG KAFKA_CONNECTOR=3.1.0-1.18
ARG JDBC_CONNECTOR=3.1.2-1.18
ARG POSTGRES_DRIVER=42.7.4

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends python3 python3-pip curl procps \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir apache-flink==1.18.1

# Conectores en lib/ para que los vean el JobManager, el TaskManager y el cliente `flink run`
RUN cd /opt/flink/lib \
    && curl -fsSLO https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/${KAFKA_CONNECTOR}/flink-sql-connector-kafka-${KAFKA_CONNECTOR}.jar \
    && curl -fsSLO https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/${JDBC_CONNECTOR}/flink-connector-jdbc-${JDBC_CONNECTOR}.jar \
    && curl -fsSLO https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_DRIVER}/postgresql-${POSTGRES_DRIVER}.jar

# Reporter de métricas Prometheus: normalmente ya viene en plugins/; si no, se copia desde opt/
RUN if ! ls /opt/flink/plugins/metrics-prometheus/*.jar >/dev/null 2>&1; then \
        mkdir -p /opt/flink/plugins/metrics-prometheus \
        && cp /opt/flink/opt/flink-metrics-prometheus-*.jar /opt/flink/plugins/metrics-prometheus/; \
    fi

# usrlib: donde scripts/submit_flink_job.sh copia el job antes de lanzarlo.
# checkpoints: se monta como volumen compartido JobManager/TaskManager; al crearla
# aquí con dueño flink, el volumen nuevo hereda esos permisos.
RUN mkdir -p /opt/flink/usrlib /opt/flink/checkpoints/checkpoints /opt/flink/checkpoints/savepoints \
    && chown -R flink:flink /opt/flink/usrlib /opt/flink/checkpoints
