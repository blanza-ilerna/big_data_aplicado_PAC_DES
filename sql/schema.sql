-- Tablas de resultados del pipeline (idempotente: se puede ejecutar varias veces).
-- La ejecutan scripts/init_infra.sh y scripts/submit_flink_job.sh.

CREATE TABLE IF NOT EXISTS ventas_por_producto (
    id               SERIAL PRIMARY KEY,
    window_start     TIMESTAMPTZ    NOT NULL,
    window_end       TIMESTAMPTZ    NOT NULL,
    product          VARCHAR(100)   NOT NULL,
    total_amount     NUMERIC(12, 2) NOT NULL,
    num_transactions INTEGER        NOT NULL,
    avg_amount       NUMERIC(12, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS ventas_por_usuario (
    id               SERIAL PRIMARY KEY,
    window_start     TIMESTAMPTZ    NOT NULL,
    window_end       TIMESTAMPTZ    NOT NULL,
    user_id          VARCHAR(100)   NOT NULL,
    total_amount     NUMERIC(12, 2) NOT NULL,
    num_transactions INTEGER        NOT NULL
);

-- Grafana y la API filtran y ordenan por window_end
CREATE INDEX IF NOT EXISTS idx_vpp_window_end ON ventas_por_producto (window_end);
CREATE INDEX IF NOT EXISTS idx_vpu_window_end ON ventas_por_usuario (window_end);
