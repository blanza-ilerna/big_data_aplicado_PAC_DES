# Flink 2.2.1 + PyFlink + conectores Kafka y JDBC (PostgreSQL)
#
# Etapa 1 (deps): Maven resuelve los conectores y sus dependencias (pom.xml).
# Etapa 2: imagen oficial de Flink + PyFlink en un entorno virtual + los jars.

FROM maven:3.9.16-eclipse-temurin-17 AS deps
COPY pom.xml /build/pom.xml
# slf4j-api y commons-logging ya los trae Flink: duplicarlos rompe el logging
RUN mvn -q -B -f /build/pom.xml dependency:copy-dependencies \
        -DincludeScope=runtime \
        -DexcludeArtifactIds=slf4j-api,commons-logging \
        -DoutputDirectory=/deps \
    && ls -1 /deps

# La imagen base usa Ubuntu 24.04 (noble) -> Python 3.12, soportado por PyFlink 2.2
FROM flink:2.2.1-scala_2.12-java17

# La imagen de Flink 2.x termina con USER flink: para instalar hace falta root.
# Al final se vuelve a USER flink, como en la imagen original.
USER root

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends python3 python3-venv curl procps \
    && rm -rf /var/lib/apt/lists/*

# Python 3.12 de Ubuntu no permite `pip install` en el sistema (PEP 668): venv propio.
# El PATH hace que `python` sea el del venv, también en `docker exec ... flink run -py`.
# Algunas dependencias de PyFlink (p. ej. crcmod, que usa apache-beam) solo se
# publican como código fuente: se instala el compilador para el pip y se quita después.
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends build-essential python3-dev \
    && python3 -m venv /opt/pyflink \
    && /opt/pyflink/bin/pip install --no-cache-dir apache-flink==2.2.1 \
    && /opt/pyflink/bin/python -c "import pyflink, pemja; print('PyFlink', pyflink.__file__)" \
    && apt-get purge -y build-essential python3-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/pyflink/bin:$PATH

# Conectores en lib/ para que los vean el JobManager, el TaskManager y el cliente `flink run`
COPY --from=deps /deps/ /opt/flink/lib/

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

USER flink
