import json
import os
import signal
import sys
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone
from kafka import KafkaConsumer
import psycopg2
from psycopg2.extras import execute_values
from pythonjsonlogger import jsonlogger
from prometheus_client import start_http_server, Counter, Gauge, Histogram

# --- LOGS ---
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(jsonlogger.JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)

# --- MÉTRICAS ---
MESSAGES_CONSUMED   = Counter('job_messages_consumed_total',   'Mensajes leídos de Redpanda')
WINDOWS_FLUSHED     = Counter('job_windows_flushed_total',     'Ventanas escritas en PostgreSQL')
DB_ERRORS           = Counter('job_db_errors_total',           'Errores al escribir en PostgreSQL')
LAST_WINDOW_TXN     = Gauge(  'job_last_window_transactions',  'Transacciones en la última ventana')
WINDOW_DURATION     = Histogram('job_window_duration_seconds', 'Duración real de cada ventana',
                                buckets=[15, 30, 45, 60, 90, 120])

# --- CONFIG ---
KAFKA_BOOTSTRAP = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:19092')
TOPIC = 'ventas_topic'
WINDOW_SECONDS = 30

DB = {
    'host':     os.getenv('POSTGRES_HOST',     'localhost'),
    'port':     int(os.getenv('POSTGRES_PORT', '5432')),
    'dbname':   os.getenv('POSTGRES_DB',       'bigdata'),
    'user':     os.getenv('POSTGRES_USER',     'bigdata_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'bigdata_pass'),
}

# --- SHUTDOWN ---
running = True

def handle_shutdown(signum, frame):
    global running
    logger.info("Señal de parada recibida, cerrando job...")
    running = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


def init_db(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ventas_por_producto (
                id               SERIAL PRIMARY KEY,
                window_start     TIMESTAMPTZ NOT NULL,
                window_end       TIMESTAMPTZ NOT NULL,
                product          VARCHAR(100) NOT NULL,
                total_amount     NUMERIC(12, 2) NOT NULL,
                num_transactions INTEGER NOT NULL,
                avg_amount       NUMERIC(12, 2) NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ventas_por_usuario (
                id               SERIAL PRIMARY KEY,
                window_start     TIMESTAMPTZ NOT NULL,
                window_end       TIMESTAMPTZ NOT NULL,
                user_id          VARCHAR(100) NOT NULL,
                total_amount     NUMERIC(12, 2) NOT NULL,
                num_transactions INTEGER NOT NULL
            )
        """)
        conn.commit()
    logger.info("Tablas inicializadas en PostgreSQL")


def flush_window(conn, window_start, window_end, by_product, by_user):
    if not by_product and not by_user:
        return

    with conn.cursor() as cur:
        if by_product:
            rows_product = [
                (window_start, window_end, product,
                 round(data['total'], 2), data['count'],
                 round(data['total'] / data['count'], 2))
                for product, data in by_product.items()
            ]
            execute_values(cur, """
                INSERT INTO ventas_por_producto
                    (window_start, window_end, product, total_amount, num_transactions, avg_amount)
                VALUES %s
            """, rows_product)

        if by_user:
            rows_user = [
                (window_start, window_end, user_id,
                 round(data['total'], 2), data['count'])
                for user_id, data in by_user.items()
            ]
            execute_values(cur, """
                INSERT INTO ventas_por_usuario
                    (window_start, window_end, user_id, total_amount, num_transactions)
                VALUES %s
            """, rows_user)

        conn.commit()

    logger.info(
        "Ventana escrita en PostgreSQL",
        extra={
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "productos": len(by_product),
            "usuarios": len(by_user),
        }
    )


def run():
    # Conexión PostgreSQL
    conn = None
    while not conn:
        try:
            conn = psycopg2.connect(**DB)
            logger.info("Conectado a PostgreSQL")
        except Exception as e:
            logger.warning("Esperando a PostgreSQL...", extra={"error": str(e)})
            time.sleep(5)

    init_db(conn)

    # Conexión Redpanda/Kafka
    consumer = None
    while not consumer:
        try:
            consumer = KafkaConsumer(
                TOPIC,
                bootstrap_servers=[KAFKA_BOOTSTRAP],
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset='earliest',
                group_id='flink-job-group',
                consumer_timeout_ms=1000,
            )
            logger.info("Conectado a Redpanda", extra={"topic": TOPIC})
        except Exception as e:
            logger.warning("Esperando a Redpanda...", extra={"error": str(e)})
            time.sleep(5)

    # Ventana tumbling de WINDOW_SECONDS segundos
    window_start = datetime.now(timezone.utc)
    by_product = defaultdict(lambda: {'total': 0.0, 'count': 0})
    by_user    = defaultdict(lambda: {'total': 0.0, 'count': 0})

    logger.info("Job iniciado", extra={"window_seconds": WINDOW_SECONDS, "topic": TOPIC})

    while running:
        try:
            for message in consumer:
                if not running:
                    break
                event = message.value
                product = event['product']
                user_id = event['user_id']
                amount  = float(event['amount'])

                by_product[product]['total'] += amount
                by_product[product]['count'] += 1
                by_user[user_id]['total']    += amount
                by_user[user_id]['count']    += 1
                MESSAGES_CONSUMED.inc()

            now = datetime.now(timezone.utc)
            elapsed = (now - window_start).total_seconds()
            if elapsed >= WINDOW_SECONDS:
                total_txn = sum(d['count'] for d in by_product.values())
                try:
                    flush_window(conn, window_start, now, dict(by_product), dict(by_user))
                    WINDOWS_FLUSHED.inc()
                    WINDOW_DURATION.observe(elapsed)
                    LAST_WINDOW_TXN.set(total_txn)
                except Exception as e:
                    DB_ERRORS.inc()
                    logger.error("Error escribiendo ventana en PostgreSQL", extra={"error": str(e)})
                window_start = now
                by_product.clear()
                by_user.clear()

        except Exception as e:
            logger.error("Error en el procesamiento", extra={"error": str(e)})
            time.sleep(1)

    flush_window(conn, window_start, datetime.now(timezone.utc),
                 dict(by_product), dict(by_user))
    consumer.close()
    conn.close()
    logger.info("Job detenido correctamente")


if __name__ == '__main__':
    start_http_server(8002)
    logger.info("Métricas Prometheus expuestas", extra={"port": 8002})
    run()
