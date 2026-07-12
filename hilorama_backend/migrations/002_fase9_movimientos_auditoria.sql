-- FASE 9B: trazabilidad de inventario y auditoria general.
-- Requiere que la migracion 001_fase2_control_acceso.sql ya este aplicada.
-- Es idempotente y no borra ni reescribe registros historicos.

CREATE TABLE IF NOT EXISTS movimientos_almacen (
    id BIGSERIAL PRIMARY KEY,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    usuario TEXT DEFAULT 'ADMIN',
    tipo TEXT NOT NULL,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    codigo TEXT,
    stock_anterior INTEGER,
    stock_nuevo INTEGER,
    cantidad INTEGER NOT NULL DEFAULT 0,
    campo TEXT,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    motivo TEXT
);

ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS cliente_sistema_id INTEGER;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS producto_id INTEGER;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS referencia_tipo TEXT;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS referencia_id TEXT;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS usuario_id INTEGER;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS device_id TEXT;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS metadata_json JSONB;
ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMPTZ;
ALTER TABLE movimientos_almacen ALTER COLUMN fecha_creacion SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_movimientos_almacen_fecha_desc
    ON movimientos_almacen(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_movimientos_almacen_producto_fecha
    ON movimientos_almacen(producto_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_movimientos_almacen_referencia
    ON movimientos_almacen(referencia_tipo, referencia_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_almacen_tipo_fecha
    ON movimientos_almacen(tipo, fecha DESC);
-- La llave de idempotencia pertenece a la empresa que ejecuta la operacion.
-- Este nombre solo pudo haber sido creado por una ejecucion parcial temprana
-- de esta misma migracion; quitarlo no elimina registros historicos.
DROP INDEX IF EXISTS uq_movimientos_almacen_idempotency_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_movimientos_almacen_cliente_idempotency_key
    ON movimientos_almacen (COALESCE(cliente_sistema_id, 0), idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS auditoria_general (
    id BIGSERIAL PRIMARY KEY,
    cliente_sistema_id INTEGER,
    usuario_id INTEGER,
    accion TEXT NOT NULL,
    modulo TEXT NOT NULL,
    entidad_tipo TEXT,
    entidad_id TEXT,
    descripcion TEXT,
    datos_anteriores_json JSONB,
    datos_nuevos_json JSONB,
    resultado TEXT NOT NULL DEFAULT 'OK',
    codigo_error TEXT,
    ip TEXT,
    user_agent TEXT,
    device_id TEXT,
    request_id TEXT,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auditoria_general_fecha_desc
    ON auditoria_general(fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_general_cliente_fecha
    ON auditoria_general(cliente_sistema_id, fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_general_usuario_fecha
    ON auditoria_general(usuario_id, fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_general_modulo_accion_fecha
    ON auditoria_general(modulo, accion, fecha_creacion DESC);
