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

-- Una fila por ventana y producto/usuario. El job de Flink escribe en modo upsert
-- (INSERT ... ON CONFLICT DO UPDATE) sobre estas claves, así que relanzar el job
-- o reprocesar mensajes tras un fallo no duplica ventanas.
-- En tablas de versiones anteriores se borran antes los duplicados que hubiera.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_vpp_ventana_producto') THEN
        DELETE FROM ventas_por_producto a
              USING ventas_por_producto b
              WHERE a.id > b.id
                AND a.window_start = b.window_start
                AND a.product = b.product;
        ALTER TABLE ventas_por_producto
            ADD CONSTRAINT uq_vpp_ventana_producto UNIQUE (window_start, product);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_vpu_ventana_usuario') THEN
        DELETE FROM ventas_por_usuario a
              USING ventas_por_usuario b
              WHERE a.id > b.id
                AND a.window_start = b.window_start
                AND a.user_id = b.user_id;
        ALTER TABLE ventas_por_usuario
            ADD CONSTRAINT uq_vpu_ventana_usuario UNIQUE (window_start, user_id);
    END IF;
END $$;

-- Grafana y la API filtran y ordenan por window_end
CREATE INDEX IF NOT EXISTS idx_vpp_window_end ON ventas_por_producto (window_end);
CREATE INDEX IF NOT EXISTS idx_vpu_window_end ON ventas_por_usuario (window_end);
