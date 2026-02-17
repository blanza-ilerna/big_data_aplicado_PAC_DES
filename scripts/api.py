import os
from typing import Optional
import psycopg2
import psycopg2.extras
import uvicorn
from fastapi import FastAPI, Query, HTTPException

app = FastAPI(
    title="Big Data Aplicado — API",
    description="API REST sobre los resultados procesados por el pipeline de streaming.",
    version="1.0.0",
)

DB = {
    'host':     os.getenv('POSTGRES_HOST',     'localhost'),
    'port':     int(os.getenv('POSTGRES_PORT', '5432')),
    'dbname':   os.getenv('POSTGRES_DB',       'bigdata'),
    'user':     os.getenv('POSTGRES_USER',     'bigdata_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'bigdata_pass'),
}


def get_conn():
    return psycopg2.connect(**DB)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Sistema"])
def health():
    try:
        conn = get_conn()
        conn.close()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Ventas por producto
# ---------------------------------------------------------------------------

@app.get("/ventas/productos", tags=["Ventas"])
def ventas_por_producto(
    product: Optional[str] = Query(None, description="Filtrar por producto"),
    limit: int = Query(50, ge=1, le=500),
):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if product:
            cur.execute("""
                SELECT window_start, window_end, product,
                       total_amount, num_transactions, avg_amount
                FROM ventas_por_producto
                WHERE product = %s
                ORDER BY window_end DESC
                LIMIT %s
            """, (product, limit))
        else:
            cur.execute("""
                SELECT window_start, window_end, product,
                       total_amount, num_transactions, avg_amount
                FROM ventas_por_producto
                ORDER BY window_end DESC
                LIMIT %s
            """, (limit,))
        rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/ventas/productos/resumen", tags=["Ventas"])
def resumen_por_producto():
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT product,
                   SUM(total_amount)     AS total_amount,
                   SUM(num_transactions) AS num_transactions,
                   ROUND(AVG(avg_amount)::numeric, 2) AS avg_amount
            FROM ventas_por_producto
            GROUP BY product
            ORDER BY total_amount DESC
        """)
        rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Ventas por usuario
# ---------------------------------------------------------------------------

@app.get("/ventas/usuarios", tags=["Ventas"])
def ventas_por_usuario(
    user_id: Optional[str] = Query(None, description="Filtrar por usuario"),
    limit: int = Query(50, ge=1, le=500),
):
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if user_id:
            cur.execute("""
                SELECT window_start, window_end, user_id,
                       total_amount, num_transactions
                FROM ventas_por_usuario
                WHERE user_id = %s
                ORDER BY window_end DESC
                LIMIT %s
            """, (user_id, limit))
        else:
            cur.execute("""
                SELECT window_start, window_end, user_id,
                       total_amount, num_transactions
                FROM ventas_por_usuario
                ORDER BY window_end DESC
                LIMIT %s
            """, (limit,))
        rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/ventas/usuarios/resumen", tags=["Ventas"])
def resumen_por_usuario():
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT user_id,
                   SUM(total_amount)     AS total_amount,
                   SUM(num_transactions) AS num_transactions
            FROM ventas_por_usuario
            GROUP BY user_id
            ORDER BY total_amount DESC
        """)
        rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Resumen global
# ---------------------------------------------------------------------------

@app.get("/ventas/global", tags=["Ventas"])
def resumen_global():
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT COUNT(*)               AS num_ventanas,
                   SUM(num_transactions)  AS total_transacciones,
                   SUM(total_amount)      AS total_importe,
                   ROUND(AVG(avg_amount)::numeric, 2) AS media_por_transaccion
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

    conn.close()
    return global_row


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8001)
