-- FASE 2: control de acceso, licencias y bloqueo remoto.
-- Revisar antes de ejecutar. No se ejecuta automaticamente.

CREATE TABLE IF NOT EXISTS clientes_sistema (
    id SERIAL PRIMARY KEY,
    nombre_negocio TEXT NOT NULL,
    contacto TEXT,
    telefono TEXT,
    email TEXT,
    estado TEXT NOT NULL DEFAULT 'activo'
        CHECK (estado IN ('activo','suspendido','vencido','bloqueado','bloqueado_permanente')),
    fecha_vencimiento DATE,
    max_dispositivos INTEGER NOT NULL DEFAULT 1,
    puede_actualizar BOOLEAN NOT NULL DEFAULT FALSE,
    plan TEXT,
    notas_admin TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS usuarios_sistema (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes_sistema(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    usuario TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL
        CHECK (rol IN ('super_admin','admin_cliente','vendedor','almacen','solo_lectura')),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dispositivos_autorizados (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes_sistema(id) ON DELETE CASCADE,
    usuario_id INTEGER REFERENCES usuarios_sistema(id) ON DELETE SET NULL,
    device_id_hash TEXT NOT NULL,
    nombre_equipo TEXT,
    sistema_operativo TEXT,
    app_version TEXT,
    estado TEXT NOT NULL DEFAULT 'activo'
        CHECK (estado IN ('activo','bloqueado')),
    ultimo_acceso TIMESTAMPTZ,
    ultima_ip TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cliente_id, device_id_hash)
);

CREATE TABLE IF NOT EXISTS sesiones_activas (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes_sistema(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios_sistema(id) ON DELETE CASCADE,
    device_id_hash TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    modulo_actual TEXT,
    app_version TEXT,
    ip TEXT,
    ultimo_heartbeat TIMESTAMPTZ,
    estado TEXT NOT NULL DEFAULT 'activa'
        CHECK (estado IN ('activa','cerrada','bloqueada')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS licencias_eventos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes_sistema(id) ON DELETE SET NULL,
    usuario_id INTEGER REFERENCES usuarios_sistema(id) ON DELETE SET NULL,
    device_id_hash TEXT,
    evento TEXT NOT NULL,
    detalle TEXT,
    ip TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usuarios_sistema_cliente ON usuarios_sistema(cliente_id);
CREATE INDEX IF NOT EXISTS idx_dispositivos_cliente_estado ON dispositivos_autorizados(cliente_id, estado);
CREATE INDEX IF NOT EXISTS idx_sesiones_token_hash ON sesiones_activas(token_hash);
CREATE INDEX IF NOT EXISTS idx_sesiones_estado_heartbeat ON sesiones_activas(estado, ultimo_heartbeat DESC);
CREATE INDEX IF NOT EXISTS idx_licencias_eventos_created ON licencias_eventos(created_at DESC);
