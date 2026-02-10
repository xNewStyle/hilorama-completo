import psycopg2
import os

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("❌ No se encontró DATABASE_URL")
    exit()

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

sql = """
-- ============================================
-- LIMPIAR (solo desarrollo)
-- ============================================

DROP TABLE IF EXISTS items CASCADE;
DROP TABLE IF EXISTS notas CASCADE;
DROP TABLE IF EXISTS clientes CASCADE;
DROP TABLE IF EXISTS productos CASCADE;
DROP TABLE IF EXISTS precios CASCADE;
DROP TABLE IF EXISTS pedido_estado CASCADE;
DROP TABLE IF EXISTS pedidos CASCADE;
DROP TABLE IF EXISTS empacadores CASCADE;

-- ============================================
-- CLIENTES
-- ============================================

CREATE TABLE clientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT,
    telefono TEXT,
    direccion TEXT
);

-- ============================================
-- EMPACADORES
-- ============================================

CREATE TABLE empacadores (
    id SERIAL PRIMARY KEY,
    usuario TEXT UNIQUE,
    nombre TEXT,
    activo BOOLEAN DEFAULT TRUE
);

-- ============================================
-- PRODUCTOS
-- ============================================

CREATE TABLE productos(
    id SERIAL PRIMARY KEY,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    codigo TEXT UNIQUE,
    codigo_barras TEXT UNIQUE,
    stock INTEGER,
    estado TEXT,
    volumetrico REAL DEFAULT 1
);

-- ============================================
-- PRECIOS
-- ============================================

CREATE TABLE precios(
    marca TEXT PRIMARY KEY,
    distribuidor REAL DEFAULT 0,
    venta REAL DEFAULT 0
);

-- ============================================
-- NOTAS
-- ============================================

CREATE TABLE notas(
    id TEXT PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes(id),
    cliente_nombre TEXT,
    fecha TIMESTAMP,
    estado TEXT,
    total REAL,
    envio TEXT,
    pedido TEXT,
    comprobante TEXT,
    empacador_id INTEGER REFERENCES empacadores(id)
);

-- ============================================
-- ITEMS
-- ============================================

CREATE TABLE items (
    id SERIAL PRIMARY KEY,
    nota_id TEXT REFERENCES notas(id) ON DELETE CASCADE,
    codigo TEXT,
    cantidad INTEGER,
    empacadas INTEGER DEFAULT 0,
    precio REAL
);

-- ============================================
-- PEDIDO ESTADO
-- ============================================

CREATE TABLE pedido_estado(
    id INTEGER PRIMARY KEY,
    numero INTEGER,
    desde DATE,
    hasta DATE
);

-- ============================================
-- HISTORIAL PEDIDOS
-- ============================================

CREATE TABLE pedidos(
    numero INTEGER PRIMARY KEY,
    desde DATE,
    hasta DATE
);

-- ============================================
-- ÍNDICES
-- ============================================

CREATE INDEX idx_producto_codigo ON productos(codigo);
CREATE INDEX idx_producto_codigo_barras ON productos(codigo_barras);
CREATE INDEX idx_producto_marca  ON productos(marca);
CREATE INDEX idx_items_nota     ON items(nota_id);

-- ============================================
-- DATOS INICIALES
-- ============================================

INSERT INTO empacadores (usuario, nombre)
VALUES
('empacador1', 'Juan'),
('empacador2', 'Maria'),
('empacador3', 'Luis');
"""

cur.execute(sql)
conn.commit()

cur.close()
conn.close()

print("✅ Base de datos creada correctamente")
