# Big Data Aplicado — PAC DES (ILERNA)

Repositorio de la PAC de Desarrollo del módulo **Big Data Aplicado** de ILERNA.

Implementa un pipeline de datos en tiempo real completo: ingesta de eventos, procesamiento distribuido, almacenamiento y observabilidad, todo ejecutable desde **GitHub Codespaces** sin instalación local.

---

## Arquitectura

```
[generator.py]
     │
     ├──► Redpanda (Kafka) ──► Apache Flink ──► PostgreSQL
     │         (ventas_topic)    (flink_job.py)
     │
     ├──► Prometheus (métricas :8000)
     │
     └──► Loki (logs via Promtail)
                │
                └──► Grafana (dashboards)
```

### Componentes

| Servicio | Rol | Puerto |
|---|---|---|
| **Redpanda** | Broker de mensajería (Kafka-compatible) | `19092` (Kafka), `8081` (Schema Registry), `8082` (REST Proxy) |
| **Apache Flink** | Procesamiento distribuido en tiempo real | `8083` (UI) |
| **PostgreSQL** | Almacenamiento de resultados | `5432` |
| **Prometheus** | Recolección de métricas | `9090` |
| **Loki** | Agregación de logs | `3100` |
| **Promtail** | Agente de logs → Loki | — |
| **Grafana** | Visualización de métricas y logs | `3000` |

#### Redpanda

Redpanda es un broker de mensajería compatible con la API de Apache Kafka, pero implementado en C++ sin depender de la JVM. En este proyecto actúa como bus central de eventos: el generador publica mensajes en el topic `ventas_topic` y Flink los consume para su procesamiento.

Expone tres interfaces:
- **`:19092`** — Kafka API, usada por productores y consumidores.
- **`:8081`** — Schema Registry, para registrar y validar esquemas de mensajes.
- **`:8082`** — REST Proxy, para interactuar con el broker vía HTTP.

#### Apache Flink

Apache Flink es el motor de procesamiento distribuido en tiempo real. Se despliega con dos roles diferenciados:

- **JobManager** — coordina la ejecución de los jobs, gestiona el estado y expone la UI web en `:8083`.
- **TaskManager** — ejecuta las tareas del job. Está configurado con 2 slots en paralelo.

El job de procesamiento se define en `scripts/flink_job.py`. Flink expone métricas en el rango de puertos `9250-9260`, que Prometheus recoge automáticamente.

#### PostgreSQL

Base de datos relacional donde se persisten los resultados del procesamiento de Flink. Se utiliza la imagen Alpine para reducir el tamaño. Los datos se guardan en un volumen Docker (`postgres_data`) para que persistan entre reinicios del Codespace.

#### Prometheus

Sistema de monitorización que recoge métricas de todos los servicios mediante scraping HTTP. Está configurado para consultar cada 15 segundos los siguientes targets:

- `redpanda:9644` — métricas del broker.
- `flink-jobmanager:9250` — métricas del clúster Flink.
- `host.docker.internal:8000` — métricas expuestas por `generator.py`.

Las métricas se almacenan durante 1 día en el volumen `prometheus_data`.

#### Loki

Loki es el sistema de agregación de logs, diseñado para integrarse con Grafana. A diferencia de otras soluciones, no indexa el contenido de los logs sino sus etiquetas, lo que lo hace muy eficiente en almacenamiento. Recibe los logs de Promtail y los sirve a Grafana para su consulta con el lenguaje LogQL.

#### Promtail

Agente que monitoriza el archivo `app.log` generado por `generator.py` y lo envía a Loki en tiempo real. Los logs se formatean en JSON estructurado para que Loki pueda filtrar por campos como `level`, `user_id` o `product`.

#### Grafana

Plataforma de visualización que centraliza métricas (Prometheus) y logs (Loki) en dashboards. Está configurada con acceso anónimo en rol Admin para facilitar el uso en el entorno de desarrollo. Permite crear alertas, explorar logs con LogQL y métricas con PromQL.

---

## Ejecución en GitHub Codespaces

### 1. Abrir el Codespace

Desde GitHub, pulsar **Code → Codespaces → Create codespace on main**.

El entorno se configura automáticamente con todas las dependencias Python definidas en `requirements.txt`.

### 2. Arrancar la infraestructura

```bash
docker-compose up -d
```

Verificar que todos los servicios están en estado `healthy`:

```bash
docker-compose ps
```

### 3. Ejecutar el generador de datos

```bash
python scripts/generator.py
```

Esto inicia la simulación de eventos de compra que envía datos a Redpanda, expone métricas en el puerto `8000` y escribe logs en `app.log` (recogidos por Promtail).

### 4. Acceder a las interfaces web

Codespaces genera una URL pública por cada puerto expuesto. El formato es:

```
https://{CODESPACE_NAME}-{PUERTO}.app.github.dev
```

El nombre del Codespace aparece en la barra superior de la página de GitHub o ejecutando:

```bash
echo $CODESPACE_NAME
```

#### URLs de acceso

| Servicio | Puerto | URL de ejemplo |
|---|---|---|
| Grafana | `3000` | `https://nombre-codespace-3000.app.github.dev` |
| Flink UI | `8083` | `https://nombre-codespace-8083.app.github.dev` |
| Prometheus | `9090` | `https://nombre-codespace-9090.app.github.dev` |

> **Nota:** Los puertos son **privados por defecto** — solo accesibles con la sesión de GitHub activa. Para hacerlos públicos, ir a la pestaña **Ports** del terminal, clic derecho sobre el puerto → **Port Visibility → Public**.

> Grafana está configurado con acceso anónimo en rol Admin, por lo que no requiere usuario ni contraseña.

---

## Estructura del repositorio

```
.
├── .devcontainer/
│   └── devcontainer.json       # Configuración de GitHub Codespaces
├── config/
│   ├── flink-conf.yaml         # Configuración de Apache Flink
│   ├── prometheus.yml          # Targets de scraping de Prometheus
│   └── promtail-config.yml     # Ruta de logs hacia Loki
├── scripts/
│   ├── generator.py            # Simulador de eventos (Redpanda + Prometheus + Loki)
│   └── flink_job.py            # Job de procesamiento en Apache Flink
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
apache-flink==1.18.1
python-json-logger==2.0.7
```

Instalación manual:

```bash
pip install -r requirements.txt
```
