import json
import os
import random
import signal
import sys
import time
import logging
import urllib.request
from datetime import datetime
from kafka import KafkaProducer
from prometheus_client import start_http_server, Counter
from pythonjsonlogger import jsonlogger


# --- LOKI HANDLER (push directo, sin promtail) ---
class LokiHandler(logging.Handler):
    def __init__(self, url="http://localhost:3100/loki/api/v1/push"):
        super().__init__()
        self.url = url

    def emit(self, record):
        try:
            log_entry = self.format(record)
            ts_ns = str(int(record.created * 1_000_000_000))
            payload = json.dumps({
                "streams": [{
                    "stream": {"job": "python_generator", "level": record.levelname.lower()},
                    "values": [[ts_ns, log_entry]]
                }]
            }).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # Loki no disponible: no interrumpir el generador


# --- LOGS (JSON estructurado) ---
handler_file = logging.FileHandler("app.log")
handler_file.setFormatter(jsonlogger.JsonFormatter())
handler_stdout = logging.StreamHandler(sys.stdout)
handler_stdout.setFormatter(jsonlogger.JsonFormatter())
handler_loki = LokiHandler()
handler_loki.setFormatter(jsonlogger.JsonFormatter())

logging.basicConfig(level=logging.INFO, handlers=[handler_file, handler_stdout, handler_loki])
logger = logging.getLogger(__name__)

# --- MÉTRICAS (Prometheus) ---
REQUEST_COUNT = Counter('app_requests_total', 'Total de peticiones simuladas', ['method', 'endpoint', 'http_status'])

# --- SHUTDOWN LIMPIO ---
running = True

def handle_shutdown(signum, frame):
    global running
    logger.info("Señal de parada recibida, cerrando generador...")
    running = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# --- CONEXIÓN A REDPANDA ---
KAFKA_BOOTSTRAP = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:19092')

producer = None
while not producer:
    try:
        producer = KafkaProducer(
            bootstrap_servers=[KAFKA_BOOTSTRAP],
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        logger.info("Conectado a Redpanda", extra={"bootstrap": KAFKA_BOOTSTRAP})
    except Exception as e:
        logger.warning("Esperando a Redpanda...", extra={"error": str(e)})
        time.sleep(5)

# --- SIMULACIÓN ---
productos = ['laptop', 'mouse', 'teclado', 'monitor', 'cable_hdmi']
usuarios = ['user_1', 'user_2', 'user_3', 'user_4']

def generate_data():
    while running:
        compra = {
            'timestamp': datetime.now().isoformat(),
            'user_id': random.choice(usuarios),
            'product': random.choice(productos),
            'amount': round(random.uniform(10.0, 500.0), 2)
        }

        try:
            producer.send('ventas_topic', compra)
        except Exception as e:
            logger.error("Error enviando mensaje a Redpanda", extra={"error": str(e)})

        if random.random() > 0.8:
            logger.error("Error crítico en checkout", extra={"user_id": compra['user_id']})
            REQUEST_COUNT.labels(method='POST', endpoint='/checkout', http_status='500').inc()
        else:
            logger.info("Compra completada", extra={"product": compra['product'], "amount": compra['amount']})
            REQUEST_COUNT.labels(method='POST', endpoint='/checkout', http_status='200').inc()

        time.sleep(random.uniform(1, 3))

    producer.flush()
    producer.close()
    logger.info("Generador detenido correctamente")

if __name__ == '__main__':
    logger.info("Generador iniciado", extra={"broker": KAFKA_BOOTSTRAP})
    start_http_server(8000)
    generate_data()
