"""
Comprobación extremo a extremo del pipeline.

Requisitos: servicios levantados (docker compose up -d), job de Flink enviado
(bash scripts/submit_flink_job.sh) y generator.py corriendo. api.py es opcional
(si no responde se marca como aviso).

    python3 tests/e2e_check.py               # espera hasta 300 s a que haya datos
    python3 tests/e2e_check.py --timeout 60

Sale con código 1 si falla alguna comprobación obligatoria. Solo usa la librería
estándar y psycopg2 (ya en requirements.txt).
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import psycopg2

FLINK = "http://localhost:8083"
PROM = "http://localhost:9090"
GRAFANA = "http://localhost:3000"
LOKI = "http://localhost:3100"
API = "http://localhost:8001"
CONSOLE = "http://localhost:8084"
JOB_NAME = "ventas-ventanas-30s"

GRAFANA_AUTH = "Basic " + base64.b64encode(
    f"admin:{os.getenv('GRAFANA_ADMIN_PASSWORD', 'admin')}".encode()).decode()
PG = dict(host="localhost", port=5432, connect_timeout=5,
          dbname=os.getenv("POSTGRES_DB", "bigdata"),
          user=os.getenv("POSTGRES_USER", "bigdata_user"),
          password=os.getenv("POSTGRES_PASSWORD", "bigdata_pass"))

failures, warnings = [], []
IN_CI = os.getenv("GITHUB_ACTIONS") == "true"


def ci_annotation(level, title, message):
    """En GitHub Actions, publica el mensaje como anotación visible en el resumen del run."""
    if IN_CI:
        msg = str(message).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::{level} title={title}::{msg[:4000]}")


def http_json(url, data=None, headers=None, timeout=10):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def check(name, fn, required=True):
    try:
        detail = fn()
        print(f"  OK    {name}" + (f" — {detail}" if detail else ""))
        return True
    except Exception as e:  # noqa: BLE001 — se informa de cualquier fallo
        tag = "FALLO" if required else "AVISO"
        print(f"  {tag} {name} — {e}")
        ci_annotation("error" if required else "warning", name, e)
        (failures if required else warnings).append(name)
        return False


def wait_until(name, fn, timeout):
    """Reintenta fn() hasta que no lance excepción o se agote el tiempo."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5)
    raise TimeoutError(f"{name}: {last}")


def prom_value(expr):
    q = urllib.parse.urlencode({"query": expr})
    res = http_json(f"{PROM}/api/v1/query?{q}")["data"]["result"]
    if not res:
        raise AssertionError(f"sin datos para {expr}")
    return float(res[0]["value"][1])


# --- comprobaciones ---------------------------------------------------------

def flink_job_running():
    jobs = http_json(f"{FLINK}/jobs/overview")["jobs"]          # campo "state", no "status"
    running = [j for j in jobs if j["name"] == JOB_NAME and j["state"] == "RUNNING"]
    if len(running) != 1:
        raise AssertionError(f"jobs '{JOB_NAME}' en RUNNING: {len(running)} "
                             f"(estados: {[(j['name'], j['state']) for j in jobs]})")
    return running[0]["jid"]


def pg_rows():
    with psycopg2.connect(**PG) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT window_start) FROM ventas_por_producto")
        rows, windows = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM ventas_por_usuario")
        users = cur.fetchone()[0]
    if rows == 0 or users == 0:
        raise AssertionError("aún no hay ventanas escritas")
    return f"{windows} ventanas, {rows} filas por producto, {users} por usuario"


def pg_no_duplicates():
    with psycopg2.connect(**PG) as conn, conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) FROM (SELECT 1 FROM ventas_por_producto
                       GROUP BY window_start, product HAVING COUNT(*) > 1) d""")
        dup = cur.fetchone()[0]
    if dup:
        raise AssertionError(f"{dup} ventanas duplicadas")


def pg_totals_match():
    """Las dos agregaciones salen de los mismos eventos: deben sumar lo mismo por ventana."""
    with psycopg2.connect(**PG) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT window_start, SUM(num_transactions) AS n FROM ventas_por_producto GROUP BY 1
            ) p JOIN (
                SELECT window_start, SUM(num_transactions) AS n FROM ventas_por_usuario GROUP BY 1
            ) u USING (window_start)
            WHERE p.n <> u.n
              -- la última ventana puede estar a medio escribir en una de las dos tablas
              AND window_start < (SELECT MAX(window_start) FROM ventas_por_producto)""")
        bad = cur.fetchone()[0]
    if bad:
        raise AssertionError(f"{bad} ventanas con totales distintos entre producto y usuario")


def prom_targets_up():
    targets = http_json(f"{PROM}/api/v1/targets")["data"]["activeTargets"]
    state = {}
    for t in targets:
        state.setdefault(t["labels"]["job"], []).append(t["health"])
    required = ["prometheus", "redpanda", "flink", "generator"]
    down = [j for j in required if not state.get(j) or any(h != "up" for h in state[j])]
    if down:
        raise AssertionError(f"targets caídos: {down} (todos: {state})")
    return ", ".join(sorted(state))


def flink_source_metric():
    v = prom_value('sum(rate(flink_taskmanager_job_task_operator_numRecordsOut'
                   '{operator_name=~".*kafka_ventas.*"}[1m]))')
    return f"{v:.2f} registros/s"


def grafana_datasources():
    ok = []
    for uid in ("prometheus", "loki", "postgres"):
        res = http_json(f"{GRAFANA}/api/datasources/uid/{uid}/health", headers={"Authorization": GRAFANA_AUTH})
        if res.get("status") != "OK":
            raise AssertionError(f"{uid}: {res}")
        ok.append(uid)
    return ", ".join(ok)


def grafana_panels():
    """Ejecuta la consulta de cada panel del dashboard por /api/ds/query y busca errores."""
    dash = http_json(f"{GRAFANA}/api/dashboards/uid/bigdata-pipeline",
                     headers={"Authorization": GRAFANA_AUTH})["dashboard"]
    errors, empty = [], []
    for panel in dash["panels"]:
        for target in panel.get("targets", []):
            ds = target.get("datasource") or panel.get("datasource")
            query = {**target, "datasource": ds, "intervalMs": 15000, "maxDataPoints": 500}
            res = http_json(f"{GRAFANA}/api/ds/query",
                            {"from": "now-30m", "to": "now", "queries": [query]},
                            headers={"Authorization": GRAFANA_AUTH}, timeout=30)
            r = res["results"][target["refId"]]
            if r.get("error"):
                errors.append(f"{panel['title']}: {r['error']}")
            elif not any(f.get("data", {}).get("values") and f["data"]["values"][0]
                         for f in r.get("frames", [])):
                empty.append(panel["title"])
    if errors:
        raise AssertionError("; ".join(errors))
    if empty:
        warnings.append("paneles sin datos")
        print(f"  AVISO paneles sin datos: {empty}")
    return f"{len(dash['panels'])} paneles sin errores"


def grafana_alert_rules():
    rules = http_json(f"{GRAFANA}/api/v1/provisioning/alert-rules", headers={"Authorization": GRAFANA_AUTH})
    uids = {r["uid"] for r in rules}
    missing = {"flink-job-caido", "sin-ventanas-nuevas"} - uids
    if missing:
        raise AssertionError(f"faltan reglas: {missing}")
    return f"{len(rules)} reglas"


def loki_logs():
    now = int(time.time())
    q = urllib.parse.urlencode({"query": '{job="python_generator"}', "limit": 5,
                                "start": f"{now - 900}000000000", "end": f"{now}000000000"})
    res = http_json(f"{LOKI}/loki/api/v1/query_range?{q}")["data"]["result"]
    if not res:
        raise AssertionError("no hay logs del generador")
    return f"{sum(len(s['values']) for s in res)} líneas recientes"


def api_global():
    h = http_json(f"{API}/health")
    if h.get("status") != "ok":
        raise AssertionError(h)
    g = http_json(f"{API}/ventas/global")
    return f"{g['num_ventanas']} ventanas, top {g['top_producto']}"


def console_up():
    with urllib.request.urlopen(f"{CONSOLE}/api/topics", timeout=10) as r:
        topics = [t["topicName"] for t in json.loads(r.read())["topics"]]
    if "ventas_topic" not in topics:
        raise AssertionError(f"ventas_topic no aparece: {topics}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300, help="segundos de espera a que lleguen datos")
    args = ap.parse_args()

    print("Flink")
    check("job en RUNNING (uno solo)", lambda: wait_until("job", flink_job_running, args.timeout))
    print("PostgreSQL")
    check("ventanas escritas", lambda: wait_until("filas", pg_rows, args.timeout))
    check("sin ventanas duplicadas", pg_no_duplicates)
    check("totales producto = usuario", pg_totals_match)
    print("Prometheus")
    check("targets up", lambda: wait_until("targets", prom_targets_up, 60))
    check("métricas de Flink", lambda: f"jobs en ejecución = {prom_value('max(flink_jobmanager_numRunningJobs)'):.0f}")
    check("métrica del origen Kafka (panel 'Leído por Flink')",
          lambda: wait_until("métrica origen", flink_source_metric, 90), required=False)
    print("Grafana")
    check("datasources", grafana_datasources)
    check("consultas de los paneles", grafana_panels)
    check("reglas de alerta", grafana_alert_rules)
    print("Loki")
    check("logs del generador", lambda: wait_until("logs", loki_logs, 60))
    print("Otros")
    check("API REST", api_global, required=False)
    check("Redpanda Console", console_up, required=False)

    print()
    if failures:
        print(f"FALLAN {len(failures)}: {failures}")
        sys.exit(1)
    print("Todo correcto" + (f" (avisos: {warnings})" if warnings else ""))


if __name__ == "__main__":
    main()
