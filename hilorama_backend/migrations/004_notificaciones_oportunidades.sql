BEGIN;

CREATE TABLE IF NOT EXISTS notificaciones_oportunidades_control (
    id BIGSERIAL PRIMARY KEY,
    cliente_id BIGINT NOT NULL,
    categoria TEXT NOT NULL,
    pospuesto_hasta TIMESTAMPTZ,
    oculto_hasta TIMESTAMPTZ,
    fecha_accion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    usuario TEXT,
    UNIQUE (cliente_id, categoria)
);

CREATE INDEX IF NOT EXISTS idx_notificaciones_oportunidades_control_vigencia
    ON notificaciones_oportunidades_control (cliente_id, categoria, pospuesto_hasta, oculto_hasta);

COMMIT;
