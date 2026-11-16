import os
import threading
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.errors
import psycopg2.extras
import psycopg2.pool
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Big Data Aplicado — API",
    description="API REST sobre los resultados procesados por el pipeline de streaming.",
    version="1.1.0",
)

DB = {
    'host':     os.getenv('POSTGRES_HOST',     'localhost'),
    'port':     int(os.getenv('POSTGRES_PORT', '5432')),
    'dbname':   os.getenv('POSTGRES_DB',       'bigdata'),
    'user':     os.getenv('POSTGRES_USER',     'bigdata_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'bigdata_pass'),
    'connect_timeout': 5,
}

# ---------------------------------------------------------------------------
# Pool de conexiones
# ---------------------------------------------------------------------------
# FastAPI ejecuta los endpoints síncronos en varios hilos, por eso un pool
# "Threaded". Se crea en la primera petición: la API arranca aunque PostgreSQL
# todavía no esté listo.
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, **DB)
        return _pool


@contextmanager
def db_cursor():
    """Cursor de diccionarios; la conexión vuelve siempre al pool (o se descarta si se rompió)."""
    pool = get_pool()
    conn = pool.getconn()
    broken = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except psycopg2.OperationalError:
        broken = True          # p. ej. PostgreSQL reiniciado: no reutilizar esta conexión
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn, close=broken or conn.closed != 0)


@app.exception_handler(psycopg2.OperationalError)
def db_unavailable(_: Request, exc: psycopg2.OperationalError):
    return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible", "error": str(exc).strip()})


@app.exception_handler(psycopg2.errors.UndefinedTable)
def tables_missing(_: Request, exc: psycopg2.Error):
    return JSONResponse(status_code=503, content={
        "detail": "Las tablas aún no existen: ejecuta `bash scripts/init_infra.sh`",
        "error": str(exc).strip(),
    })


def fetch_all(sql: str, params=()) -> list:
    with db_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Sistema"])
def health():
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except psycopg2.Error as e:
        raise HTTPException(status_code=503, detail=str(e).strip())


# ---------------------------------------------------------------------------
# Ventas por producto
# ---------------------------------------------------------------------------

@app.get("/ventas/productos", tags=["Ventas"])
def ventas_por_producto(
    product: Optional[str] = Query(None, description="Filtrar por producto"),
    limit: int = Query(50, ge=1, le=500),
):
    return fetch_all("""
        SELECT window_start, window_end, product,
               total_amount, num_transactions, avg_amount
        FROM ventas_por_producto
        WHERE (%(product)s::text IS NULL OR product = %(product)s)
        ORDER BY window_end DESC
        LIMIT %(limit)s
    """, {"product": product, "limit": limit})


@app.get("/ventas/productos/resumen", tags=["Ventas"])
def resumen_por_producto():
    return fetch_all("""
        SELECT product,
               SUM(total_amount)     AS total_amount,
               SUM(num_transactions) AS num_transactions,
               ROUND(SUM(total_amount) / NULLIF(SUM(num_transactions), 0), 2) AS avg_amount
        FROM ventas_por_producto
        GROUP BY product
        ORDER BY total_amount DESC
    """)


# ---------------------------------------------------------------------------
# Ventas por usuario
# ---------------------------------------------------------------------------

@app.get("/ventas/usuarios", tags=["Ventas"])
def ventas_por_usuario(
    user_id: Optional[str] = Query(None, description="Filtrar por usuario"),
    limit: int = Query(50, ge=1, le=500),
):
    return fetch_all("""
        SELECT window_start, window_end, user_id,
               total_amount, num_transactions
        FROM ventas_por_usuario
        WHERE (%(user_id)s::text IS NULL OR user_id = %(user_id)s)
        ORDER BY window_end DESC
        LIMIT %(limit)s
    """, {"user_id": user_id, "limit": limit})


@app.get("/ventas/usuarios/resumen", tags=["Ventas"])
def resumen_por_usuario():
    return fetch_all("""
        SELECT user_id,
               SUM(total_amount)     AS total_amount,
               SUM(num_transactions) AS num_transactions
        FROM ventas_por_usuario
        GROUP BY user_id
        ORDER BY total_amount DESC
    """)


# ---------------------------------------------------------------------------
# Resumen global
# ---------------------------------------------------------------------------

@app.get("/ventas/global", tags=["Ventas"])
def resumen_global():
    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT window_start) AS num_ventanas,
                   SUM(num_transactions)        AS total_transacciones,
                   SUM(total_amount)            AS total_importe,
                   ROUND(SUM(total_amount) / NULLIF(SUM(num_transactions), 0), 2) AS media_por_transaccion,
                   MAX(window_end)              AS ultima_ventana
            FROM ventas_por_producto
        """)
        global_row = dict(cur.fetchone())

        cur.execute("""
            SELECT product, SUM(total_amount) AS total
            FROM ventas_por_producto
            GROUP BY product
            ORDER BY total DESC
            LIMIT 1
        """)
        top = cur.fetchone()
        global_row['top_producto'] = dict(top) if top else None

    return global_row


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8001)
