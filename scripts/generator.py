import json
import os
import random
import signal
import sys
import time
import logging
import logging.handlers
import queue
import urllib.request
from datetime import datetime, timezone
from kafka import KafkaProducer
from prometheus_client import start_http_server, Counter
from pythonjsonlogger import jsonlogger


# --- LOKI HANDLER (push directo a Loki, sin Promtail) ---
class LokiHandler(logging.Handler):
    """Envía cada log a la API de Loki. Si Loki no responde, deja de intentarlo
    durante RETRY_AFTER segundos para no acumular esperas."""
    RETRY_AFTER = 30

    def __init__(self, url=None):
        super().__init__()
        self.url = url or os.getenv('LOKI_URL', 'http://localhost:3100/loki/api/v1/push')
        self._down_until = 0.0

    def emit(self, record):
        if time.monotonic() < self._down_until:
            return  # Loki caído hace poco: se descarta (sigue en stdout y app.log)
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
            self._down_until = time.monotonic() + self.RETRY_AFTER


class DropWhenFullQueueHandler(logging.handlers.QueueHandler):
    """Si la cola está llena (Loki muy lento), descarta el log en vez de bloquear."""
    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            pass


# --- LOGS (JSON estructurado) ---
handler_file = logging.FileHandler("app.log")
handler_file.setFormatter(jsonlogger.JsonFormatter())
handler_stdout = logging.StreamHandler(sys.stdout)
handler_stdout.setFormatter(jsonlogger.JsonFormatter())

# El envío HTTP a Loki se hace en un hilo aparte (QueueListener): el bucle del
# generador nunca espera a la red.
handler_loki = LokiHandler()
handler_loki.setFormatter(jsonlogger.JsonFormatter())
loki_queue = queue.Queue(maxsize=1000)
loki_listener = logging.handlers.QueueListener(loki_queue, handler_loki)
loki_listener.start()
handler_queue = DropWhenFullQueueHandler(loki_queue)
# QueueHandler formatea el mensaje antes de encolarlo: con "%(message)s" se deja tal cual
# (sin esto, basicConfig le pone "INFO:nombre:mensaje"). El JSON lo genera handler_loki.
handler_queue.setFormatter(logging.Formatter("%(message)s"))

logging.basicConfig(level=logging.INFO,
                    handlers=[handler_file, handler_stdout, handler_queue])
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
            # UTC sin zona, ISO-8601 con milisegundos: lo que espera el job de Flink
            'timestamp': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='milliseconds'),
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
    loki_listener.stop()  # vacía la cola de logs pendientes hacia Loki

if __name__ == '__main__':
    logger.info("Generador iniciado", extra={"broker": KAFKA_BOOTSTRAP})
    start_http_server(8000)
    generate_data()
