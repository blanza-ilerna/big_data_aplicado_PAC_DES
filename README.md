# Big Data Aplicado — PAC DES (ILERNA)

Repositorio de la PAC de Desarrollo del módulo **Big Data Aplicado** de ILERNA.

Implementa un pipeline de datos en tiempo real completo: ingesta de eventos, procesamiento distribuido, almacenamiento y observabilidad, todo ejecutable desde **GitHub Codespaces** sin instalación local.

---

## Arquitectura

```
[generator.py]
     │
     │
     ├──► Redpanda (Kafka) ──► Apache Flink ──► PostgreSQL ──► api.py (FastAPI)
     │     (ventas_topic)     (flink_job.py,      │
     │                         PyFlink, 30 s)     │
     ├──► Prometheus (métricas) ◄── Flink :9249   │
     │         │                                  │
     └──► Loki (logs)                             │
               └──────────► Grafana ◄─────────────┘
```

### Componentes

| Servicio | Rol | Puerto |
|---|---|---|
| **Redpanda** | Broker de mensajería (Kafka-compatible) | `19092` (Kafka), `8081` (Schema Registry), `8082` (REST Proxy) |
| **Apache Flink** | Procesamiento en streaming (job PyFlink) | `8083` (UI) |
| **PostgreSQL** | Almacenamiento de resultados | `5432` |
| **Prometheus** | Recolección de métricas | `9090` |
| **Loki** | Agregación de logs | `3100` |
| **Grafana** | Visualización de métricas y logs | `3000` |

#### Redpanda

Redpanda es un broker de mensajería compatible con la API de Apache Kafka, pero implementado en C++ sin depender de la JVM. En este proyecto actúa como bus central de eventos: el generador publica mensajes en el topic `ventas_topic` y el job de Flink los consume para su procesamiento.

Expone tres interfaces:
- **`:19092`** — Kafka API, usada por productores y consumidores.
- **`:8081`** — Schema Registry, para registrar y validar esquemas de mensajes.
- **`:8082`** — REST Proxy, para interactuar con el broker vía HTTP.

#### Apache Flink

Apache Flink es el motor de procesamiento distribuido en tiempo real. Se despliega con dos roles diferenciados:

- **JobManager** — coordina la ejecución de los jobs, gestiona el estado y expone la UI web en `:8083`.
- **TaskManager** — ejecuta las tareas del job. Está configurado con 2 slots en paralelo.

El job está en `scripts/flink_job.py` y usa **PyFlink** (Table API + SQL):

- **Origen:** tabla `kafka_ventas` sobre `ventas_topic` (formato JSON). El tiempo de evento es el campo `timestamp` de cada mensaje, con una marca de agua (*watermark*) de 5 s.
- **Procesamiento:** ventanas *tumbling* de 30 s (`TUMBLE(...)`) agrupadas por producto y por usuario.
- **Destino:** tablas `ventas_por_producto` y `ventas_por_usuario` de PostgreSQL (conector JDBC).
- **Tolerancia a fallos:** *checkpoint* cada 30 s. Los offsets se guardan en el consumer group `flink-ventas`, así que al relanzar el job continúa donde lo dejó.

La imagen de Flink se construye desde `docker/flink/Dockerfile` (Flink 1.18.1 + PyFlink + conectores Kafka y JDBC). El job **no se ejecuta con `python3`**: se envía al clúster con `bash scripts/submit_flink_job.sh`, y después aparece en la UI de Flink (`:8083`). Flink expone métricas en el puerto `9249` del JobManager y del TaskManager.

`scripts/python_consumer.py` es el **plan B** sin Flink (el consumidor Python original). Úsalo solo si el clúster no funciona y nunca a la vez que el job, porque los dos escriben en las mismas tablas.

#### PostgreSQL

Base de datos relacional donde se persisten los resultados del job de Flink. Las tablas se crean con `sql/schema.sql`, que ejecuta `scripts/init_infra.sh` al arrancar el Codespace. Se utiliza la imagen Alpine para reducir el tamaño. Los datos se guardan en un volumen Docker (`postgres_data`) para que persistan entre reinicios del Codespace.

#### Prometheus

Sistema de monitorización que recoge métricas de todos los servicios mediante scraping HTTP. Está configurado para consultar cada 15 segundos los siguientes targets:

- `redpanda:9644` — métricas del broker.
- `flink-jobmanager:9249` y `flink-taskmanager:9249` — métricas de Flink (jobs en ejecución, registros procesados, reinicios...).
- `host.docker.internal:8000` — métricas expuestas por `generator.py`.
- `host.docker.internal:8002` — solo con el plan B (`python_consumer.py`); si no se usa, aparece `down`.

Los scripts Python (`generator.py`, `api.py`) corren en el devcontainer, que usa la red del host (`--network=host` en `devcontainer.json`). Por eso Prometheus los alcanza a través de `host.docker.internal` y los scripts alcanzan los servicios en `localhost`.

La configuración de Prometheus (`docker/prometheus/`) y de Grafana (`docker/grafana/provisioning/`) se mete dentro de sus imágenes con `COPY`. No se usan *bind mounts* porque en Codespaces el daemon Docker no ve la carpeta del workspace en la misma ruta. **Después de editar uno de esos archivos:** `docker compose up -d --build prometheus` (o `grafana`). En el dashboard, sube también su `version`.

Las métricas se almacenan durante 1 día en el volumen `prometheus_data`.

#### Loki

Loki es el sistema de agregación de logs, diseñado para integrarse con Grafana. A diferencia de otras soluciones, no indexa el contenido de los logs sino sus etiquetas, lo que lo hace muy eficiente en almacenamiento. `generator.py` envía sus logs directamente a la API de Loki (`/loki/api/v1/push`) con las etiquetas `job="python_generator"` y `level`. Los logs van en JSON estructurado, así que en LogQL se pueden filtrar campos como `user_id` o `product` con `| json`. Además se escriben en `app.log` en el directorio desde el que se lanza el script.

#### Grafana

Plataforma de visualización que centraliza métricas (Prometheus), logs (Loki) y los resultados del job (PostgreSQL) en un dashboard. Está configurada con acceso anónimo en rol Admin para facilitar el uso en el entorno de desarrollo. Permite crear alertas, explorar logs con LogQL y métricas con PromQL.

---

## Ejecución en GitHub Codespaces

### 1. Abrir el Codespace

Desde GitHub, pulsar **Code → Codespaces → Create codespace on main**.

El entorno se configura automáticamente:
- `postCreateCommand` — instala las dependencias Python (`pip install -r requirements.txt`)
- `postStartCommand` — ejecuta `.devcontainer/start.sh`, que ajusta los permisos del socket Docker, construye las imágenes y lanza los servicios (`docker compose up -d --build`), y crea el topic y las tablas (`scripts/init_infra.sh`)

La primera vez tarda varios minutos, porque la imagen de Flink instala PyFlink.

No es necesario ejecutar ningún comando manual para arrancar la infraestructura.

### 2. Verificar que la infraestructura está lista

```bash
docker compose ps
```

Todos los contenedores deben aparecer en estado `healthy`. Si alguno está en `starting`, esperar unos segundos y repetir.

Verificar que Prometheus recoge métricas de todos los targets:

```bash
curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool | grep -E '"health"|"job"'
```

### 3. Ejecutar el pipeline de datos

**Paso 1 — Enviar el job a Flink** (una sola vez; sigue corriendo en el clúster):
```bash
bash scripts/submit_flink_job.sh            # no hace nada si ya está en ejecución
bash scripts/submit_flink_job.sh --restart  # tras modificar flink_job.py
bash scripts/submit_flink_job.sh --cancel   # pararlo
```
Consume de Redpanda, agrega por ventanas de 30 s y escribe en PostgreSQL.

Los demás scripts se arrancan en terminales separadas (botón `+` del panel de terminales de VS Code):

**Terminal 1 — Generador de eventos:**
```bash
python3 scripts/generator.py
```
Simula compras, publica en Redpanda, expone métricas en `:8000` y envía sus logs a Loki.

**Terminal 3 — API REST (opcional):**
```bash
python3 scripts/api.py
```
Sirve los resultados de PostgreSQL mediante FastAPI en `:8001`. Documentación interactiva en `http://localhost:8001/docs`.

#### Endpoints disponibles

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del servidor y conexión a BD |
| `GET` | `/ventas/global` | Resumen global: total de transacciones, importe y producto top |
| `GET` | `/ventas/productos` | Ventas por producto por ventana (param: `product`, `limit`) |
| `GET` | `/ventas/productos/resumen` | Agregado total por producto (todas las ventanas) |
| `GET` | `/ventas/usuarios` | Ventas por usuario por ventana (param: `user_id`, `limit`) |
| `GET` | `/ventas/usuarios/resumen` | Agregado total por usuario (todas las ventanas) |
| `GET` | `/docs` | Swagger UI interactivo |

### 4. Verificar el flujo extremo a extremo

```bash
# Datos agregados en PostgreSQL
docker exec bigdata-postgres psql -U bigdata_user -d bigdata \
  -c "SELECT product, SUM(num_transactions) AS txn FROM ventas_por_producto GROUP BY product ORDER BY txn DESC;"

# Resumen global vía API REST
curl -s http://localhost:8001/ventas/global | python3 -m json.tool

# Métricas del generador
curl -s http://localhost:8000/metrics | grep "^app_"

# Job de Flink en ejecución (debe salir "RUNNING")
docker exec bigdata-flink-jobmanager curl -s http://localhost:8081/jobs/overview | python3 -m json.tool | grep -E '"name"|"state"'
```

Las ventanas se escriben con unos 35-60 s de retraso: la ventana dura 30 s, Flink espera 5 s más de marca de agua y el JDBC agrupa las escrituras.

### 5. Acceder a las interfaces web

Codespaces genera una URL pública por cada puerto expuesto. El formato es:

```
https://{CODESPACE_NAME}-{PUERTO}.app.github.dev
```

El nombre del Codespace aparece en la barra superior de la página de GitHub o ejecutando:

```bash
echo $CODESPACE_NAME
```

#### URLs de acceso

| Servicio | Puerto | Descripción |
|---|---|---|
| **Grafana** | `3000` | Dashboard pre-configurado: métricas, resultados y logs |
| **API REST** | `8001` | Endpoints de consulta + Swagger en `/docs` |
| **Flink UI** | `8083` | Estado del clúster Flink |
| **Prometheus** | `9090` | Explorador de métricas (PromQL) |
| **Redpanda REST Proxy** | `8082` | API HTTP del broker (no es una consola web) |

> **Nota:** Los puertos son **privados por defecto** — solo accesibles con la sesión de GitHub activa. Para hacerlos públicos, ir a la pestaña **Ports** del terminal, clic derecho sobre el puerto → **Port Visibility → Public**.

> Grafana está configurado con acceso anónimo en rol Admin, por lo que no requiere usuario ni contraseña. El dashboard **ILERNA - Big Data Aplicado** se aprovisiona automáticamente al arrancar.

---

## Estructura del repositorio

```
.
├── .devcontainer/
│   ├── Dockerfile              # Imagen con Docker CLI instalado
│   ├── devcontainer.json       # Configuración de GitHub Codespaces
│   └── start.sh                # Script de arranque (chmod socket + docker compose up)
├── docker/
│   ├── flink/Dockerfile        # Flink 1.18.1 + PyFlink + conectores Kafka/JDBC
│   ├── prometheus/             # Imagen con prometheus.yml (targets)
│   └── grafana/provisioning/   # Datasources (Prometheus, Loki, PostgreSQL) y dashboard
├── scripts/
│   ├── generator.py            # Simulador de eventos (Redpanda + Prometheus + Loki)
│   ├── flink_job.py            # Job PyFlink: ventanas de 30 s -> PostgreSQL
│   ├── submit_flink_job.sh     # Envía / relanza / cancela el job en el clúster
│   ├── init_infra.sh           # Crea el topic y las tablas (idempotente)
│   ├── python_consumer.py      # Plan B sin Flink (no usar a la vez que el job)
│   └── api.py                  # API REST FastAPI sobre PostgreSQL
├── sql/schema.sql              # Tablas de resultados
├── docker-compose.yml          # Definición de servicios
└── requirements.txt            # Dependencias Python
```

---

## Base de datos

| Parámetro | Valor |
|---|---|
| Host | `localhost` |
| Puerto | `5432` |
| Base de datos | `bigdata` |
| Usuario | `bigdata_user` |
| Contraseña | `bigdata_pass` |

---

## Dependencias Python

```
kafka-python==2.0.2
prometheus_client==0.20.0
psycopg2-binary==2.9.9
python-json-logger==2.0.7
fastapi==0.111.0
uvicorn==0.30.1
```

PyFlink **no** está en `requirements.txt`: solo se instala dentro de la imagen de Flink.

En Codespaces se instalan automáticamente al crear el entorno. Instalación manual:

```bash
pip install -r requirements.txt
```
