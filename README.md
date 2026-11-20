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
| **Redpanda Console** | Interfaz web del broker: topics, mensajes, consumer groups | `8084` |
| **Apache Flink** | Procesamiento en streaming (job PyFlink) | `8083` (UI) |
| **PostgreSQL** | Almacenamiento de resultados | `5432` |
| **Prometheus** | Recolección de métricas | `9090` |
| **Loki** | Agregación de logs | `3100` |
| **Grafana** | Visualización de métricas, resultados, logs y alertas | `3000` |

#### Redpanda

Redpanda es un broker de mensajería compatible con la API de Apache Kafka, pero implementado en C++ sin depender de la JVM. En este proyecto actúa como bus central de eventos: el generador publica mensajes en el topic `ventas_topic` y el job de Flink los consume para su procesamiento.

Expone tres interfaces:
- **`:19092`** — Kafka API, usada por productores y consumidores.
- **`:8081`** — Schema Registry, para registrar y validar esquemas de mensajes.
- **`:8082`** — REST Proxy, para interactuar con el broker vía HTTP.

**Redpanda Console** (`:8084`) permite ver los mensajes de `ventas_topic` y el consumer group `flink-ventas` con su *lag* (mensajes pendientes de procesar).

#### Apache Flink

Apache Flink es el motor de procesamiento distribuido en tiempo real. Se despliega con dos roles diferenciados:

- **JobManager** — coordina la ejecución de los jobs, gestiona el estado y expone la UI web en `:8083`.
- **TaskManager** — ejecuta las tareas del job. Está configurado con 2 slots en paralelo.

El job está en `scripts/flink_job.py` y usa **PyFlink** (Table API + SQL):

- **Origen:** tabla `kafka_ventas` sobre `ventas_topic` (formato JSON). El tiempo de evento es el campo `timestamp` de cada mensaje, con una marca de agua (*watermark*) de 5 s.
- **Procesamiento:** ventanas *tumbling* de 30 s (`TUMBLE(...)`) agrupadas por producto y por usuario.
- **Destino:** tablas `ventas_por_producto` y `ventas_por_usuario` de PostgreSQL (conector JDBC en modo **upsert**: `INSERT ... ON CONFLICT DO UPDATE` sobre la clave `(window_start, product)` o `(window_start, user_id)`).
- **Tolerancia a fallos:** *checkpoint* cada 30 s en el volumen `flink_checkpoints`, compartido por el JobManager y el TaskManager. Los offsets se confirman en el consumer group `flink-ventas`.
- **Sin duplicados:** si el job se relanza y reprocesa mensajes, el upsert sobrescribe la ventana en lugar de duplicarla.

La imagen de Flink se construye desde `docker/flink/Dockerfile` (Flink 2.2.1 + PyFlink 2.2.1 en un entorno virtual + conectores Kafka y JDBC, cuyas dependencias resuelve Maven desde `docker/flink/pom.xml`). El job **no se ejecuta con `python3`**: se envía al clúster con `bash scripts/submit_flink_job.sh`, y después aparece en la UI de Flink (`:8083`). Flink expone métricas en el puerto `9249` del JobManager y del TaskManager.

Al arrancar el Codespace, `start.sh` envía el job automáticamente si no está en ejecución (al parar el Codespace, el job se pierde con el reinicio del JobManager).

`scripts/python_consumer.py` es el **plan B** sin Flink (el consumidor Python original). Úsalo solo si el clúster no funciona y nunca a la vez que el job, porque los dos escriben en las mismas tablas.

#### PostgreSQL

Base de datos relacional donde se persisten los resultados del job de Flink. Las tablas se crean con `sql/schema.sql`, que ejecuta `scripts/init_infra.sh` al arrancar el Codespace. Se utiliza la imagen Alpine de PostgreSQL 18 para reducir el tamaño. Los datos se guardan en un volumen Docker (`postgres18_data`) para que persistan entre reinicios del Codespace.

#### Prometheus

Sistema de monitorización que recoge métricas de todos los servicios mediante scraping HTTP. Está configurado para consultar cada 15 segundos los siguientes targets:

- `redpanda:9644` — métricas del broker.
- `flink-jobmanager:9249` y `flink-taskmanager:9249` — métricas de Flink (jobs en ejecución, registros procesados, reinicios...).
- `host.docker.internal:8000` — métricas expuestas por `generator.py`.

Las métricas `job_*` de `python_consumer.py` (plan B) no se scrapean: con Flink no existen. Su equivalente es, por ejemplo, filas escritas en PostgreSQL en 5 min: `sum(increase(flink_taskmanager_job_task_operator_numRecordsOut{operator_name=~".*pg_por_.*"}[5m]))`. Si usas el plan B, añade temporalmente un job `python_consumer` con target `host.docker.internal:8002`.

Los scripts Python (`generator.py`, `api.py`) corren en el devcontainer, que usa la red del host (`--network=host` en `devcontainer.json`). Por eso Prometheus los alcanza a través de `host.docker.internal` y los scripts alcanzan los servicios en `localhost`.

La configuración de Prometheus (`docker/prometheus/`) y de Grafana (`docker/grafana/provisioning/`) se mete dentro de sus imágenes con `COPY`. No se usan *bind mounts* porque en Codespaces el daemon Docker no ve la carpeta del workspace en la misma ruta. **Después de editar uno de esos archivos:** `docker compose up -d --build prometheus` (o `grafana`). En el dashboard, sube también su `version`.

Las métricas se almacenan durante 1 día en el volumen `prometheus_data`.

#### Loki

Loki es el sistema de agregación de logs, diseñado para integrarse con Grafana. A diferencia de otras soluciones, no indexa el contenido de los logs sino sus etiquetas, lo que lo hace muy eficiente en almacenamiento. `generator.py` envía sus logs directamente a la API de Loki (`/loki/api/v1/push`) con las etiquetas `job="python_generator"` y `level`. Los logs van en JSON estructurado, así que en LogQL se pueden filtrar campos como `user_id` o `product` con `| json`. Además se escriben en `app.log` en el directorio desde el que se lanza el script.

#### Grafana

Plataforma de visualización que centraliza métricas (Prometheus), logs (Loki) y los resultados del job (PostgreSQL) en un dashboard. Está configurada con acceso anónimo en rol Admin para facilitar el uso en el entorno de desarrollo (se puede cambiar a `Viewer` en `.env`).

Trae dos **alertas** provisionadas (`docker/grafana/provisioning/alerting/rules.yml`), visibles en *Alerting → Alert rules*:
- **Job de Flink caído:** no hay ningún job en ejecución durante 2 minutos.
- **Sin ventanas nuevas en PostgreSQL:** la última ventana tiene más de 3 minutos.

Las alertas se ven en la UI con su estado (*Normal*, *Pending*, *Firing*), pero **no envían avisos**: no hay servidor de correo, así que `alerting/notifications.yml` las silencia con el *mute timing* `siempre` (así Grafana no llena el log de errores `SMTP not configured`). Para recibir avisos, cambia en ese archivo el *contact point* `sin-avisos` por uno real (Slack, Discord, email...) y quita `mute_time_intervals`.

### Versiones

| Componente | Versión |
|---|---|
| Redpanda / Redpanda Console | v26.2.7 / v3.14.0 |
| Apache Flink / PyFlink | 2.2.1 (Java 17, Python 3.12) |
| Conectores Flink | Kafka `5.0.0-2.2`, JDBC `4.1.0-2.2`, driver PostgreSQL `42.7.14` |
| PostgreSQL | 18.7 (Alpine) |
| Prometheus | v3.16.0 |
| Loki | 3.7.10 |
| Grafana | 13.2.6 |

Todas las imágenes tienen la versión fijada (nunca `latest`). Si actualizas un Codespace que ya tenía versiones anteriores, los volúmenes de Redpanda y PostgreSQL son nuevos (`redpanda_data_v26`, `postgres18_data`), porque los datos antiguos no son compatibles. Los antiguos se pueden borrar con `docker volume prune`.

---

## Ejecución en GitHub Codespaces

### 1. Abrir el Codespace

Desde GitHub, pulsar **Code → Codespaces → Create codespace on main**.

El entorno se configura automáticamente:
- `postCreateCommand` — instala las dependencias Python (`pip install -r requirements.txt`)
- `postStartCommand` — ejecuta `.devcontainer/start.sh`, que ajusta los permisos del socket Docker, construye las imágenes y lanza los servicios (`docker compose up -d --build`), crea el topic y las tablas (`scripts/init_infra.sh`) y envía el job de Flink (`scripts/submit_flink_job.sh`)

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

**Job de Flink:** `start.sh` ya lo envía al arrancar. Para gestionarlo a mano:
```bash
bash scripts/submit_flink_job.sh                 # lo lanza si no está en ejecución
bash scripts/submit_flink_job.sh --restart       # tras modificar flink_job.py (con savepoint)
bash scripts/submit_flink_job.sh --restart-clean # si --restart falla por cambios grandes en el SQL
bash scripts/submit_flink_job.sh --cancel        # pararlo (toma un savepoint)
```
Consume de Redpanda, agrega por ventanas de 30 s y escribe en PostgreSQL. `--restart` toma un *savepoint* (una foto del estado del job), lo para y lo relanza desde él, así que no se pierden las ventanas a medio calcular.

Los demás scripts se arrancan en terminales separadas (botón `+` del panel de terminales de VS Code):

**Terminal 1 — Generador de eventos:**
```bash
python3 scripts/generator.py
```
Simula compras, publica en Redpanda, expone métricas en `:8000` y envía sus logs a Loki.

**Terminal 2 — API REST (opcional):**
```bash
python3 scripts/api.py
```
Sirve los resultados de PostgreSQL mediante FastAPI en `:8001`. Documentación interactiva en `http://localhost:8001/docs`. Usa un pool de conexiones y responde `503` si PostgreSQL no está disponible o las tablas aún no existen.

#### Endpoints disponibles

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del servidor y conexión a BD |
| `GET` | `/ventas/global` | Resumen global: nº de ventanas, transacciones, importe, ticket medio, última ventana y producto top |
| `GET` | `/ventas/productos` | Ventas por producto por ventana (param: `product`, `limit`) |
| `GET` | `/ventas/productos/resumen` | Agregado total por producto (todas las ventanas) |
| `GET` | `/ventas/usuarios` | Ventas por usuario por ventana (param: `user_id`, `limit`) |
| `GET` | `/ventas/usuarios/resumen` | Agregado total por usuario (todas las ventanas) |
| `GET` | `/docs` | Swagger UI interactivo |

### 4. Verificar el flujo extremo a extremo

La forma rápida es el script de comprobación, que revisa Flink, PostgreSQL (incluido que no haya ventanas duplicadas), Prometheus, cada panel de Grafana, las alertas, Loki, la API y Redpanda Console:

```bash
python3 tests/e2e_check.py
```

También se puede comprobar a mano:

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
| **Redpanda Console** | `8084` | Topics, mensajes y consumer groups |
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
│   └── start.sh                # Arranque: compose up, topic/tablas y envío del job
├── docker/
│   ├── flink/                  # Dockerfile (Flink 2.2.1 + PyFlink) y pom.xml (conectores)
│   ├── prometheus/             # Imagen con prometheus.yml (targets)
│   └── grafana/provisioning/   # Datasources, dashboard y alertas
├── scripts/
│   ├── generator.py            # Simulador de eventos (Redpanda + Prometheus + Loki)
│   ├── flink_job.py            # Job PyFlink: ventanas de 30 s -> PostgreSQL
│   ├── submit_flink_job.sh     # Envía / relanza / cancela el job en el clúster
│   ├── init_infra.sh           # Crea el topic y las tablas (idempotente)
│   ├── python_consumer.py      # Plan B sin Flink (no usar a la vez que el job)
│   └── api.py                  # API REST FastAPI sobre PostgreSQL
├── sql/schema.sql              # Tablas de resultados (con claves únicas)
├── tests/e2e_check.py          # Comprobación extremo a extremo
├── .github/workflows/ci.yml    # CI: comprobaciones estáticas + e2e con todo el stack
├── .env.example                # Credenciales (copiar a .env para cambiarlas)
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

Son los valores por defecto. Para cambiarlos, copia `.env.example` a `.env` (no se sube a git) y lee las notas de ese archivo.

---

## Dependencias Python

```
kafka-python==2.3.3
prometheus_client==0.26.0
psycopg2-binary==2.9.13
python-json-logger==4.2.0
fastapi==0.163.1
uvicorn==0.54.0
```

PyFlink **no** está en `requirements.txt`: solo se instala dentro de la imagen de Flink.

`kafka-python` se mantiene en la rama 2.3.x (mantenida): la 3.0 cambia la firma de los serializadores y la jerarquía de excepciones.

En Codespaces se instalan automáticamente al crear el entorno. Instalación manual:

```bash
pip install -r requirements.txt
```

---

## Prebuilds de Codespaces (opcional)

Un *prebuild* deja preparado el devcontainer, de modo que el Codespace arranca en segundos en lugar de minutos. **No hace falta un fork:** se activa en el propio repositorio.

1. En GitHub: **Settings → Codespaces → Set up prebuild**.
2. Rama: `main`. Configuración: `.devcontainer/devcontainer.json`. Región: la más cercana (Europa Oeste).
3. Disparador: *On configuration change* (solo se rehace cuando cambia el devcontainer), para gastar menos.

Ten en cuenta:
- El prebuild ejecuta `postCreateCommand` (`pip install`), pero **no** `postStartCommand`: las imágenes de `docker compose` (sobre todo la de Flink) se siguen construyendo al arrancar.
- Cuesta almacenamiento y minutos de Actions a la cuenta dueña del repositorio.
- Solo se aplica a los Codespaces creados **desde este repositorio**. Si los alumnos hacen *fork*, cada fork necesita su propio prebuild. Si crean el Codespace directamente desde el repo original (o desde una plantilla), sí lo aprovechan.

---

## Integración continua

`.github/workflows/ci.yml` se ejecuta en cada push:

1. **static** — compila los scripts Python, revisa la sintaxis de los `.sh`, valida JSON/YAML y `docker compose config`.
2. **e2e** — levanta todo el stack en el runner de GitHub, envía el job, arranca el generador y la API, y ejecuta `tests/e2e_check.py`. Después relanza el job con `--restart` y vuelve a comprobar que no hay ventanas duplicadas. Tarda unos 10-15 minutos.
