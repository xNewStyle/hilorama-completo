-- =================================================
-- LIMPIAR (solo desarrollo)
-- =================================================
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS notas;
DROP TABLE IF EXISTS clientes;
DROP TABLE IF EXISTS productos;
DROP TABLE IF EXISTS precios;
DROP TABLE IF EXISTS pedido_estado;
DROP TABLE IF EXISTS pedidos;


-- =================================================
-- CLIENTES
-- =================================================
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT,
    telefono TEXT,
    direccion TEXT
);

-- =================================================
-- EMPACADORES
-- =================================================
CREATE TABLE empacadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT UNIQUE,
    nombre TEXT,
    activo INTEGER DEFAULT 1
);

-- =================================================
-- PRODUCTOS (almacén real)
-- =================================================
CREATE TABLE productos(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    codigo TEXT UNIQUE,
    codigo_barras TEXT UNIQUE,   -- ⭐ NUEVO (8697678072808)
    stock INTEGER,
    estado TEXT,
    volumetrico REAL DEFAULT 1
);


-- =================================================
-- PRECIOS POR MARCA
-- =================================================
CREATE TABLE precios(
    marca TEXT PRIMARY KEY,
    distribuidor REAL DEFAULT 0,
    venta REAL DEFAULT 0
);


-- =================================================
-- NOTAS / COTIZACIONES / VENTAS
-- =================================================
CREATE TABLE notas(
    id TEXT PRIMARY KEY,
    cliente_id INTEGER,
    cliente_nombre TEXT,
    fecha TEXT,
    estado TEXT,
    total REAL,
    envio TEXT,
    pedido TEXT,
    comprobante TEXT   
    empacador_id INTEGER-- ⭐ NUEVO
);

INSERT INTO empacadores (usuario, nombre)
VALUES
("empacador1", "Juan"),
("empacador2", "Maria"),
("empacador3", "Luis");


-- =================================================
-- ITEMS DE CADA NOTA
-- =================================================
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nota_id TEXT,
    codigo TEXT,
    cantidad INTEGER,
    empacadas INTEGER DEFAULT 0,  -- ⭐ NUEVO
    precio REAL,
    FOREIGN KEY(nota_id) REFERENCES notas(id)
);




-- =================================================
-- PEDIDO ESTADO (contador actual)
-- =================================================
CREATE TABLE pedido_estado(
    id INTEGER PRIMARY KEY CHECK(id=1),
    numero INTEGER,
    desde TEXT,
    hasta TEXT
);


-- =================================================
-- HISTORIAL PEDIDOS
-- =================================================
CREATE TABLE pedidos(
    numero INTEGER PRIMARY KEY,
    desde TEXT,
    hasta TEXT
);


-- =================================================
-- ÍNDICES (performance 🔥)
-- =================================================
CREATE INDEX idx_producto_codigo ON productos(codigo);
CREATE INDEX idx_producto_codigo_barras ON productos(codigo_barras);
CREATE INDEX idx_producto_marca  ON productos(marca);
CREATE INDEX idx_items_nota     ON items(nota_id);
