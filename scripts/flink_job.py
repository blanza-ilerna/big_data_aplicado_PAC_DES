"""
Job de Apache Flink (PyFlink, Table API + SQL).

Lee las compras de `ventas_topic` en Redpanda, las agrupa en ventanas *tumbling*
de 30 s por **tiempo de evento** (el campo `timestamp` de cada mensaje) y escribe
dos agregados en PostgreSQL:

    ventas_por_producto  (window_start, window_end, product, total_amount, num_transactions, avg_amount)
    ventas_por_usuario   (window_start, window_end, user_id, total_amount, num_transactions)

Este archivo NO se ejecuta con `python3` desde el devcontainer: se envía al clúster
con `bash scripts/submit_flink_job.sh`, que lo copia al JobManager y lanza
`flink run -d -py`. Las tablas se crean antes con `sql/schema.sql`.
"""
import os

from pyflink.table import EnvironmentSettings, TableEnvironment

JOB_NAME = "ventas-ventanas-30s"

# Dentro de la red Docker: listener interno de Redpanda y host del servicio postgres
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_INTERNAL", "redpanda:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "ventas_topic")
JDBC_URL = os.getenv("JDBC_URL", "jdbc:postgresql://postgres:5432/bigdata")
PG_USER = os.getenv("POSTGRES_USER", "bigdata_user")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "bigdata_pass")


def jdbc_options(table_name: str) -> str:
    return f"""
        'connector' = 'jdbc',
        'url' = '{JDBC_URL}',
        'driver' = 'org.postgresql.Driver',
        'table-name' = '{table_name}',
        'username' = '{PG_USER}',
        'password' = '{PG_PASSWORD}',
        'sink.buffer-flush.max-rows' = '100',
        'sink.buffer-flush.interval' = '2s',
        'sink.max-retries' = '3'
    """


def main() -> None:
    t_env = TableEnvironment.create(EnvironmentSettings.in_streaming_mode())
    conf = t_env.get_config()
    conf.set("pipeline.name", JOB_NAME)
    conf.set("parallelism.default", "1")            # el topic tiene 1 partición
    conf.set("execution.checkpointing.interval", "30 s")  # confirma offsets en Kafka
    conf.set("table.local-time-zone", "UTC")

    # --- Origen: Redpanda (Kafka) ------------------------------------------
    # `timestamp` llega como ISO-8601 en UTC sin zona ("2026-11-16T10:00:00.123").
    # event_time: si el campo viene vacío o mal formado se usa 1970, de modo que el
    # evento queda por detrás de la marca de agua y Flink lo descarta (dato tardío)
    # en vez de romper el job.
    t_env.execute_sql(f"""
        CREATE TABLE kafka_ventas (
            `timestamp` TIMESTAMP(3),
            user_id     STRING,
            product     STRING,
            amount      DOUBLE,
            event_time AS COALESCE(`timestamp`, TIMESTAMP '1970-01-01 00:00:00'),
            WATERMARK FOR event_time AS event_time - INTERVAL '5' SECOND
        ) WITH (
            'connector' = 'kafka',
            'topic' = '{TOPIC}',
            'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP}',
            'properties.group.id' = 'flink-ventas',
            'properties.auto.offset.reset' = 'earliest',
            'scan.startup.mode' = 'group-offsets',
            'format' = 'json',
            'json.timestamp-format.standard' = 'ISO-8601',
            'json.ignore-parse-errors' = 'true'
        )
    """)

    # --- Destinos: PostgreSQL (JDBC) ---------------------------------------
    # Solo se declaran las columnas que escribe Flink; `id` lo genera PostgreSQL.
    t_env.execute_sql(f"""
        CREATE TABLE pg_por_producto (
            window_start     TIMESTAMP(3),
            window_end       TIMESTAMP(3),
            product          STRING,
            total_amount     DECIMAL(12, 2),
            num_transactions INT,
            avg_amount       DECIMAL(12, 2)
        ) WITH ({jdbc_options('ventas_por_producto')})
    """)

    t_env.execute_sql(f"""
        CREATE TABLE pg_por_usuario (
            window_start     TIMESTAMP(3),
            window_end       TIMESTAMP(3),
            user_id          STRING,
            total_amount     DECIMAL(12, 2),
            num_transactions INT
        ) WITH ({jdbc_options('ventas_por_usuario')})
    """)

    # --- Ventanas tumbling de 30 s (Window TVF) -----------------------------
    statements = t_env.create_statement_set()   # un solo job, un solo consumidor Kafka

    statements.add_insert_sql("""
        INSERT INTO pg_por_producto
        SELECT window_start,
               window_end,
               product,
               CAST(ROUND(SUM(amount), 2) AS DECIMAL(12, 2)),
               CAST(COUNT(*) AS INT),
               CAST(ROUND(AVG(amount), 2) AS DECIMAL(12, 2))
        FROM TABLE(TUMBLE(TABLE kafka_ventas, DESCRIPTOR(event_time), INTERVAL '30' SECOND))
        GROUP BY window_start, window_end, product
    """)

    statements.add_insert_sql("""
        INSERT INTO pg_por_usuario
        SELECT window_start,
               window_end,
               user_id,
               CAST(ROUND(SUM(amount), 2) AS DECIMAL(12, 2)),
               CAST(COUNT(*) AS INT)
        FROM TABLE(TUMBLE(TABLE kafka_ventas, DESCRIPTOR(event_time), INTERVAL '30' SECOND))
        GROUP BY window_start, window_end, user_id
    """)

    # Con `flink run -d` esto envía el job y vuelve sin esperar a que termine
    statements.execute()


if __name__ == "__main__":
    main()
