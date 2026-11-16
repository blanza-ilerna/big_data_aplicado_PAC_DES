# Checklist de verificación — Big Data Aplicado

## 1. Infraestructura Docker

- [ ] Todos los contenedores en estado `healthy`
  ```bash
  docker compose ps
  ```
  Servicios esperados: `redpanda`, `prometheus`, `loki`, `grafana`, `flink-jobmanager`, `flink-taskmanager`, `postgres`

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
  - `python_app` — host.docker.internal:8000
  - `flink_job` — host.docker.internal:8002

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

> `flink_job.py` es un consumidor Python y **no aparece** en `/jobs` de Flink. Para comprobar que corre, usar sus métricas (`curl -s http://localhost:8002/metrics | grep "^job_"`) o el target `flink_job` de Prometheus.

---

## 4. Grafana

- [ ] Grafana responde
  ```bash
  curl -s http://localhost:3000/api/health
  ```
  Esperado: `"database":"ok"`

- [ ] Datasources auto-provisionados (Prometheus + Loki)
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

- [ ] **Terminal 2** — Job de procesamiento corriendo
  ```bash
  python3 scripts/flink_job.py
  ```

- [ ] **Terminal 3** — API REST corriendo (opcional)
  ```bash
  python3 scripts/api.py
  ```

- [ ] Datos en PostgreSQL (tras ~30 s)
  ```bash
  docker exec bigdata-postgres psql -U bigdata_user -d bigdata \
    -c "SELECT product, SUM(num_transactions) AS txn FROM ventas_por_producto GROUP BY product ORDER BY txn DESC;"
  ```

- [ ] Resumen global vía API REST
  ```bash
  curl -s http://localhost:8001/ventas/global | python3 -m json.tool
  ```

- [ ] Métricas del generador
  ```bash
  curl -s http://localhost:8000/metrics | grep "^app_"
  ```

- [ ] Métricas del job
  ```bash
  curl -s http://localhost:8002/metrics | grep "^job_"
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

**Métricas del job de procesamiento:**
```promql
# Total mensajes consumidos de Redpanda
job_messages_consumed_total

# Ventanas de 30s escritas en PostgreSQL
job_windows_flushed_total

# Transacciones en la última ventana procesada
job_last_window_transactions

# Errores de escritura en BD
job_db_errors_total

# Duración de ventana — percentil 50 y 95
histogram_quantile(0.50, rate(job_window_duration_seconds_bucket[5m]))
histogram_quantile(0.95, rate(job_window_duration_seconds_bucket[5m]))
```

---

### Paneles del dashboard Grafana

| Panel | Tipo | Query |
|---|---|---|
| Total peticiones generadas | Stat | `sum(app_requests_total)` |
| Mensajes consumidos por el job | Stat | `job_messages_consumed_total` |
| Ventanas escritas en PostgreSQL | Stat | `job_windows_flushed_total` |
| Errores de escritura en BD | Stat | `job_db_errors_total` |
| Tasa producción vs consumo | Timeseries | `sum(rate(app_requests_total[1m]))` + `rate(job_messages_consumed_total[1m])` |
| Tasa errores HTTP 500 | Timeseries | `rate(app_requests_total{http_status="500"}[1m])` |
| Transacciones por ventana de 30s | Timeseries | `job_last_window_transactions` |
| Duración real de ventana | Timeseries | `histogram_quantile(0.50/0.95, ...)` |
| Logs del generador | Logs (Loki) | `{job="python_generator"}` |

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
