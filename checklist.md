# Checklist de verificación — Big Data Aplicado

> Atajo: `python3 tests/e2e_check.py` hace casi todas estas comprobaciones de una vez.

## 1. Infraestructura Docker

- [ ] Todos los contenedores en estado `healthy`
  ```bash
  docker compose ps
  ```
  Servicios esperados: `redpanda`, `redpanda-console`, `prometheus`, `loki`, `grafana`, `flink-jobmanager`, `flink-taskmanager`, `postgres`

---

## 2. Prometheus

- [ ] Prometheus responde
  ```bash
  curl -s http://localhost:9090/-/healthy
  ```

- [ ] Todos los targets en estado `up`
  ```bash
  curl -s http://localhost:9090/api/v1/targets | python3 -m json.tool | grep -E '"health"|"job"'
  ```
  Targets esperados (con los scripts corriendo):
  - `prometheus` — localhost:9090
  - `redpanda` — redpanda:9644
  - `flink` — flink-jobmanager:9249 y flink-taskmanager:9249
  - `generator` — host.docker.internal:8000

- [ ] Métricas del generador disponibles
  ```bash
  curl -s "http://localhost:9090/api/v1/query?query=app_requests_total" | python3 -m json.tool
  ```

---

## 3. Flink

- [ ] JobManager responde y tiene 1 TaskManager conectado
  ```bash
  curl -s http://localhost:8083/overview | python3 -m json.tool
  ```
  Esperado: `"taskmanagers": 1`, `"slots-available": 2`

- [ ] TaskManager registrado
  ```bash
  curl -s http://localhost:8083/taskmanagers | python3 -m json.tool
  ```

- [ ] Job `ventas-ventanas-30s` en estado `RUNNING` (después de `bash scripts/submit_flink_job.sh`)
  ```bash
  curl -s http://localhost:8083/jobs/overview | python3 -m json.tool | grep -E '"name"|"state"'
  ```
  Ojo: `/jobs/overview` usa el campo `state`; `/jobs` usa `status`.

- [ ] Métricas de Flink en Prometheus
  ```bash
  curl -s "http://localhost:9090/api/v1/query?query=flink_jobmanager_numRunningJobs" | python3 -m json.tool
  ```
  Esperado: valor `1`

---

## 4. Grafana

- [ ] Grafana responde
  ```bash
  curl -s http://localhost:3000/api/health
  ```
  Esperado: `"database":"ok"`

- [ ] Datasources auto-provisionados (Prometheus + Loki + PostgreSQL)
  ```bash
  curl -s http://localhost:3000/api/datasources \
    -H "Authorization: Basic YWRtaW46YWRtaW4="
  ```

- [ ] Dashboard cargado
  ```bash
  curl -s "http://localhost:3000/api/dashboards/uid/bigdata-pipeline" \
    -H "Authorization: Basic YWRtaW46YWRtaW4=" | python3 -m json.tool | grep -E '"title"|"uid"'
  ```
  Esperado: `"title": "ILERNA - Big Data Aplicado"`

- [ ] Reglas de alerta provisionadas (`Job de Flink caído`, `Sin ventanas nuevas en PostgreSQL`)
  ```bash
  curl -s http://localhost:3000/api/v1/provisioning/alert-rules \
    -H "Authorization: Basic YWRtaW46YWRtaW4=" | python3 -m json.tool | grep '"title"'
  ```

- [ ] Dashboard visible en el navegador → carpeta **Big Data Pipeline** → **ILERNA - Big Data Aplicado**

---

## 5. Loki

- [ ] Loki listo
  ```bash
  curl -s http://localhost:3100/ready
  ```
  Esperado: `ready`

- [ ] Logs llegando a Loki (con `generator.py` corriendo; los envía directamente a Loki)
  ```bash
  NOW=$(date +%s); HOUR_AGO=$((NOW - 3600))
  curl -s "http://localhost:3100/loki/api/v1/query_range?query=%7Bjob%3D%22python_generator%22%7D&start=${HOUR_AGO}000000000&end=${NOW}000000000&limit=5" \
    | python3 -m json.tool | grep -c '"stream"'
  ```
  Esperado: `1` o más

---

## 6. Pipeline extremo a extremo

- [ ] **Terminal 1** — Generador corriendo
  ```bash
  python3 scripts/generator.py
  ```

- [ ] Job de Flink enviado (lo hace `start.sh`; a mano si no)
  ```bash
  bash scripts/submit_flink_job.sh
  ```

- [ ] **Terminal 3** — API REST corriendo (opcional)
  ```bash
  python3 scripts/api.py
  ```

- [ ] Datos en PostgreSQL (tras ~60 s)
  ```bash
  docker exec bigdata-postgres psql -U bigdata_user -d bigdata \
    -c "SELECT product, SUM(num_transactions) AS txn FROM ventas_por_producto GROUP BY product ORDER BY txn DESC;"
  ```

- [ ] Sin ventanas duplicadas (debe salir 0)
  ```bash
  docker exec bigdata-postgres psql -U bigdata_user -d bigdata -tc \
    "SELECT COUNT(*) FROM (SELECT 1 FROM ventas_por_producto GROUP BY window_start, product HAVING COUNT(*) > 1) d;"
  ```

- [ ] Redpanda Console muestra `ventas_topic` y el consumer group `flink-ventas` (puerto `8084`)

- [ ] Resumen global vía API REST
  ```bash
  curl -s http://localhost:8001/ventas/global | python3 -m json.tool
  ```

- [ ] Métricas del generador
  ```bash
  curl -s http://localhost:8000/metrics | grep "^app_"
  ```


- [ ] Paneles del dashboard de Grafana muestran datos en tiempo real

---

## 7. Queries de referencia

### PromQL — Prometheus (`localhost:9090` → pestaña Graph)

**Métricas del generador:**
```promql
# Total acumulado de peticiones
sum(app_requests_total)

# Tasa de peticiones por segundo (última 1 min)
rate(app_requests_total[1m])

# Solo errores HTTP 500
rate(app_requests_total{http_status="500"}[1m])

# Solo éxitos HTTP 200
rate(app_requests_total{http_status="200"}[1m])
```

**Métricas de Flink:**
```promql
# Jobs en ejecución (debe ser 1)
flink_jobmanager_numRunningJobs

# Reinicios del job (si crece, el job está fallando)
flink_jobmanager_job_numRestarts

# Registros por segundo que lee el origen Kafka del job
sum(rate(flink_taskmanager_job_task_operator_numRecordsOut{operator_name=~".*kafka_ventas.*"}[1m]))

# Filas escritas en PostgreSQL en los últimos 5 min (sinks JDBC)
sum(increase(flink_taskmanager_job_task_operator_numRecordsOut{operator_name=~".*pg_por_.*"}[5m]))
```

#### Métricas adicionales de Flink

Los nombres los genera el reporter de Prometheus de Flink (prefijo `flink_`, ámbito y nombre de la métrica). Pueden variar según la versión de Flink y del conector. Para comprobar cuáles existen en el clúster: `{__name__=~"flink_.*"}` en Prometheus (`http://localhost:9090/graph`) o Grafana → Explore.

| Métrica | Qué mide | Consulta |
|---|---|---|
| `flink_jobmanager_job_uptime` | Milisegundos transcurridos desde que el job está en ejecución. Vuelve a 0 tras un reinicio. | `max(flink_jobmanager_job_uptime) / 1000` |
| `flink_jobmanager_job_numRestarts` | Reinicios acumulados del job. | `max(flink_jobmanager_job_numRestarts)` |
| `flink_jobmanager_job_lastCheckpointDuration` | Duración en ms del último checkpoint completado. | `max(flink_jobmanager_job_lastCheckpointDuration)` |
| `flink_jobmanager_job_lastCheckpointSize` | Tamaño en bytes del último checkpoint. | `max(flink_jobmanager_job_lastCheckpointSize)` |
| `flink_jobmanager_job_numberOfFailedCheckpoints` | Número de checkpoints fallidos. | `max(flink_jobmanager_job_numberOfFailedCheckpoints)` |
| `flink_taskmanager_job_task_operator_numRecordsIn` | Registros recibidos por cada operador. | `sum by (operator_name) (rate(flink_taskmanager_job_task_operator_numRecordsIn[1m]))` |
| `flink_taskmanager_job_task_operator_numRecordsOut` | Registros emitidos por cada operador. | `sum by (operator_name) (rate(flink_taskmanager_job_task_operator_numRecordsOut[1m]))` |
| `flink_taskmanager_job_task_operator_watermarkLag` | Diferencia en ms entre el reloj y la marca de agua del origen. | `max(flink_taskmanager_job_task_operator_watermarkLag)` |
| `flink_taskmanager_job_task_operator_currentEmitEventTimeLag` | Diferencia en ms entre el tiempo de evento de un registro y el momento en que el origen lo emite. | `max(flink_taskmanager_job_task_operator_currentEmitEventTimeLag)` |
| `flink_taskmanager_job_task_currentInputWatermark` | Valor actual de la marca de agua (epoch en ms) en cada tarea. | `max by (task_name) (flink_taskmanager_job_task_currentInputWatermark)` |
| `flink_taskmanager_job_task_numLateRecordsDropped` | Registros descartados por llegar con retraso superior al permitido. | `sum(flink_taskmanager_job_task_numLateRecordsDropped)` |
| `flink_taskmanager_job_task_backPressuredTimeMsPerSecond` | Ms por segundo que una tarea está bloqueada esperando a la siguiente. Rango 0–1000. | `max by (task_name) (flink_taskmanager_job_task_backPressuredTimeMsPerSecond)` |
| `flink_taskmanager_job_task_busyTimeMsPerSecond` | Ms por segundo que una tarea está procesando datos. Rango 0–1000. | `max by (task_name) (flink_taskmanager_job_task_busyTimeMsPerSecond)` |
| `flink_taskmanager_job_task_idleTimeMsPerSecond` | Ms por segundo que una tarea está sin datos que procesar. Rango 0–1000. | `max by (task_name) (flink_taskmanager_job_task_idleTimeMsPerSecond)` |
| `flink_taskmanager_Status_JVM_Memory_Heap_Used` | Bytes de heap usados por la JVM del TaskManager. | `flink_taskmanager_Status_JVM_Memory_Heap_Used` |
| `flink_taskmanager_Status_JVM_CPU_Load` | Carga de CPU de la JVM del TaskManager (0–1). | `flink_taskmanager_Status_JVM_CPU_Load` |
| `flink_taskmanager_Status_JVM_GarbageCollector_<nombre>_Time` | Tiempo acumulado en ms de recolección de basura. `<nombre>` depende del recolector en uso. | `rate({__name__=~"flink_taskmanager_Status_JVM_GarbageCollector_.*_Time"}[1m])` |
| `flink_taskmanager_job_task_operator_KafkaSourceReader_KafkaConsumer_records_lag_max` | Lag máximo del consumidor Kafka, en registros. | `max(flink_taskmanager_job_task_operator_KafkaSourceReader_KafkaConsumer_records_lag_max)` |

Los tres paneles inferiores del dashboard (reinicios, retraso de marca de agua y contrapresión) usan algunas de estas métricas.

---

### Paneles del dashboard Grafana

| Panel | Origen | Query |
|---|---|---|
| Peticiones generadas | Prometheus | `sum(app_requests_total)` |
| Jobs Flink en ejecución | Prometheus | `max(flink_jobmanager_numRunningJobs)` |
| Ventanas escritas en PostgreSQL | PostgreSQL | `COUNT(DISTINCT window_start)` |
| Última ventana hace | PostgreSQL | `now() - MAX(window_end)` |
| Producción vs consumo | Prometheus | `sum(rate(app_requests_total[1m]))` + `numRecordsOut` del origen Kafka |
| Errores HTTP 500 simulados | Prometheus | `sum(rate(app_requests_total{http_status="500"}[1m]))` |
| Importe por producto y ventana | PostgreSQL | `ventas_por_producto` |
| Transacciones por ventana de 30 s | PostgreSQL | `SUM(num_transactions)` por ventana |
| Resumen por producto / por usuario | PostgreSQL | agregados en el rango del dashboard |
| Logs del generador | Loki | `{job="python_generator"}` |
| Reinicios del job Flink | Prometheus | `max(flink_jobmanager_job_numRestarts)` |
| Retraso de la marca de agua | Prometheus | `max(flink_taskmanager_job_task_operator_watermarkLag)` |
| Contrapresión | Prometheus | `max by (task_name) (flink_taskmanager_job_task_backPressuredTimeMsPerSecond)` |

---

### LogQL — Loki (Grafana → Explore → datasource Loki)

```logql
# Todos los logs
{job="python_generator"}

# Solo errores
{job="python_generator", level="error"}

# Solo info
{job="python_generator", level="info"}

# Filtrar por texto libre
{job="python_generator"} |= "checkout"

# Logs de un producto concreto
{job="python_generator"} |= "laptop"
```
