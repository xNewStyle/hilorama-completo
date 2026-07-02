import json
import os
from pathlib import Path
import re
import io
import base64
import tempfile
import math
import traceback
from PIL import Image, ImageDraw, ImageFont
import html
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

try:
    from .whatsapp_ia_v27 import procesar_conversacion_v27
except Exception:
    from whatsapp_ia_v27 import procesar_conversacion_v27

APP_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

@app.errorhandler(Exception)
def json_api_errors(e):
    # Evita que errores internos regresen HTML y en el celular salga "Respuesta no válida".
    # Para rutas API, siempre regresamos JSON con el mensaje real del error.
    if request.path.startswith("/api/"):
        try:
            err = str(e) or e.__class__.__name__
        except Exception:
            err = e.__class__.__name__
        try:
            # Esto sí aparece en los logs de Render y permite encontrar la causa real.
            print("ERROR API", request.path, traceback.format_exc(), flush=True)
        except Exception:
            pass
        return jsonify({
            "ok": False,
            "error": f"Error interno en {request.path}: {err}",
            "type": e.__class__.__name__,
        }), 500
    raise e


_pool = None
_schema_ready = False
MEXICO_TZ = ZoneInfo("America/Mexico_City")


def now_mexico():
    return datetime.now(MEXICO_TZ).replace(tzinfo=None, microsecond=0)


def get_database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no configurado en Render")
    return url


def get_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(
            1,
            int(os.environ.get("DB_POOL_MAX", "5")),
            get_database_url(),
        )
    return _pool


class DB:
    def __enter__(self):
        self.pool = get_pool()
        self.conn = self.pool.getconn()
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        return self

    def execute(self, query, params=None):
        # No mandar () cuando no hay params: evita fallas con LIKE 'COT-%'.
        if params is None:
            self.cur.execute(query)
        else:
            self.cur.execute(query, params)
        return self

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.cur.close()
            self.pool.putconn(self.conn)


def json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    return value


def parse_json_text(value, default=None):
    if default is None:
        default = {}
    if not value:
        return default
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def fecha_orden(valor):
    if not valor:
        return datetime.min
    if isinstance(valor, datetime):
        return valor
    texto = str(valor).strip().replace("T", " ").replace("Z", "")
    texto = texto.split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:19], fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(texto)
    except Exception:
        return datetime.min


def nota_sort_key(n):
    f = n.get("fecha_pago") if n.get("estado") == "PAGADA" and n.get("fecha_pago") else n.get("fecha")
    return (fecha_orden(f), str(n.get("id") or ""))


DIRECCION_VACIA = {
    "calle": "",
    "numero_ext": "",
    "numero_int": "",
    "colonia": "",
    "codigo_postal": "",
    "estado": "",
    "municipio": "",
    "referencia": "",
}


def direccion_vacia():
    return dict(DIRECCION_VACIA)


def normalizar_direccion(value):
    d = parse_json_text(value, {}) if not isinstance(value, dict) else dict(value)
    base = direccion_vacia()
    base.update({k: ("" if v is None else str(v).strip()) for k, v in (d or {}).items()})
    return base


def validar_cliente_completo(cliente):
    """Misma regla del programa de PC para poder convertir/pagar una venta."""
    cliente = dict(cliente or {})
    faltantes = []
    nombre = str(cliente.get("nombre") or cliente.get("cliente_nombre") or cliente.get("cliente_nombre_real") or "").strip()
    telefono = re.sub(r"\D+", "", str(cliente.get("telefono") or ""))
    direccion = normalizar_direccion(cliente.get("direccion"))

    if not nombre:
        faltantes.append("Nombre completo")
    if len(telefono) != 10:
        faltantes.append("Teléfono de 10 dígitos")

    labels = {
        "calle": "Calle",
        "numero_ext": "No. exterior",
        "colonia": "Colonia",
        "codigo_postal": "Código postal",
        "estado": "Estado",
        "municipio": "Municipio / alcaldía",
    }
    for key, label in labels.items():
        if not str(direccion.get(key) or "").strip():
            faltantes.append(label)
    if len(str(direccion.get("referencia") or "")) > 100:
        faltantes.append("Referencia menor a 100 caracteres")

    return len(faltantes) == 0, faltantes


def respuesta_cliente_incompleto(cliente, accion="continuar"):
    cliente = dict(cliente or {})
    cliente["direccion"] = normalizar_direccion(cliente.get("direccion"))

    # Cuando esta función recibe una nota, la nota trae id=COT-xxxxx y cliente_id=<id real>.
    # El formulario móvil debe editar el cliente real, no intentar hacer PUT /api/clientes/COT-xxxxx.
    nota_id = cliente.get("nota_id")
    if not nota_id and str(cliente.get("id") or "").upper().startswith(("COT-", "VEN-")):
        nota_id = cliente.get("id")
    if cliente.get("cliente_id"):
        cliente["nota_id"] = nota_id
        cliente["id"] = cliente.get("cliente_id")

    ok, faltantes = validar_cliente_completo(cliente)
    if ok:
        return None
    return jsonify({
        "ok": False,
        "code": "CLIENTE_INCOMPLETO",
        "error": "Completa los datos del cliente para continuar",
        "accion": accion,
        "faltantes": faltantes,
        "cliente": json_safe(cliente),
    }), 400


def require_pin():
    expected = os.environ.get("MOBILE_PIN", "").strip()
    if not expected:
        return None
    # La app manda el PIN por header.
    # Para revisar endpoints manualmente en navegador, también aceptamos ?pin=TU_PIN.
    got = (
        request.headers.get("X-Mobile-Pin", "").strip()
        or request.args.get("pin", "").strip()
        or request.args.get("debug_pin", "").strip()
    )
    if got != expected:
        return jsonify({"ok": False, "error": "PIN incorrecto"}), 401
    return None


def table_exists(db, table):
    row = db.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables WHERE table_name=%s
        ) AS existe
    """, (table,)).fetchone()
    return bool(row and row.get("existe"))


def ensure_schema():
    """Migraciones seguras. No borra datos."""
    global _schema_ready
    if _schema_ready:
        return

    with DB() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                telefono TEXT,
                direccion TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id SERIAL PRIMARY KEY,
                marca TEXT,
                hilo TEXT,
                color TEXT,
                codigo TEXT UNIQUE,
                codigo_barras TEXT UNIQUE,
                stock INTEGER DEFAULT 0,
                estado TEXT,
                volumetrico REAL DEFAULT 1
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS precios (
                marca TEXT PRIMARY KEY,
                distribuidor REAL DEFAULT 0,
                venta REAL DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS notas (
                id TEXT PRIMARY KEY,
                cliente_id INTEGER,
                cliente_nombre TEXT,
                fecha TIMESTAMP,
                estado TEXT,
                total REAL,
                envio TEXT,
                pedido TEXT,
                comprobante TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                nota_id TEXT REFERENCES notas(id) ON DELETE CASCADE,
                codigo TEXT,
                cantidad INTEGER,
                empacadas INTEGER DEFAULT 0,
                precio REAL
            )
        """)

        # Columnas compatibles con el programa de PC.
        db.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS codigo_barras TEXT")
        db.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS precio REAL DEFAULT 0")
        db.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS costo_neto REAL DEFAULT 0")
        db.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS es_inventariable BOOLEAN DEFAULT TRUE")
        db.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS tipo_producto TEXT DEFAULT 'INVENTARIO'")
        db.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS volumetrico REAL DEFAULT 1")

        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS envio TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS pedido TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS comprobante TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_pago TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS metodo_pago TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS monto_pagado REAL DEFAULT 0")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS referencia_pago TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS paqueteria TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS empacador_id INTEGER")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS empacador TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_asignacion TIMESTAMP")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_finalizacion TIMESTAMP")

        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS producto_id INTEGER")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS marca TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS hilo TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS color TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS empacadas INTEGER DEFAULT 0")

        db.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_almacen (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tipo TEXT,
                nota_id TEXT,
                producto_id INTEGER,
                marca TEXT,
                hilo TEXT,
                color TEXT,
                codigo TEXT,
                codigo_barras TEXT,
                stock_anterior INTEGER,
                stock_nuevo INTEGER,
                cantidad INTEGER,
                campo TEXT,
                valor_anterior TEXT,
                valor_nuevo TEXT,
                motivo TEXT,
                usuario TEXT
            )
        """)
        # Si la tabla ya existía de una versión anterior, CREATE TABLE IF NOT EXISTS
        # no agrega columnas nuevas. Las agregamos aquí para evitar que al pagar una
        # nota falle el historial de almacén y deje la transacción de PostgreSQL abortada.
        for col_sql in [
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS tipo TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS nota_id TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS producto_id INTEGER",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS marca TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS hilo TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS color TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS codigo TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS codigo_barras TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS stock_anterior INTEGER",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS stock_nuevo INTEGER",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS cantidad INTEGER",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS campo TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS valor_anterior TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS valor_nuevo TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS motivo TEXT",
            "ALTER TABLE movimientos_almacen ADD COLUMN IF NOT EXISTS usuario TEXT",
        ]:
            db.execute(col_sql)

        # Historial de comprobantes/pagos como en el programa de PC.
        # En móvil guardamos el comprobante optimizado como data:image/jpeg;base64
        # para que siga disponible en Render aunque el disco sea temporal.
        db.execute("""
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                nota_id TEXT REFERENCES notas(id) ON DELETE CASCADE,
                comprobante TEXT,
                metodo_pago TEXT,
                monto_pagado REAL DEFAULT 0,
                referencia_pago TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col_sql in [
            "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS nota_id TEXT",
            "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS comprobante TEXT",
            "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS metodo_pago TEXT",
            "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS monto_pagado REAL DEFAULT 0",
            "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS referencia_pago TEXT",
            "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ]:
            db.execute(col_sql)

        # Base para el agente de WhatsApp IA. Primero se usa como simulador dentro
        # de la app móvil; después estos mismos registros sirven para conectar
        # WhatsApp Cloud API sin rehacer el cerebro del agente.
        db.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_conversaciones (
                id SERIAL PRIMARY KEY,
                telefono TEXT,
                cliente_nombre TEXT,
                origen TEXT DEFAULT 'SIMULADOR',
                estado TEXT DEFAULT 'BORRADOR',
                nota_id TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_mensajes (
                id SERIAL PRIMARY KEY,
                conversacion_id INTEGER REFERENCES whatsapp_conversaciones(id) ON DELETE SET NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                direccion TEXT,
                tipo TEXT DEFAULT 'texto',
                texto TEXT,
                respuesta_sugerida TEXT,
                metadata TEXT
            )
        """)

        db.execute("CREATE INDEX IF NOT EXISTS idx_notas_estado_fecha ON notas(estado, fecha DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_items_nota_mobile ON items(nota_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_items_producto_mobile ON items(producto_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_productos_busqueda_mobile ON productos(codigo, marca, hilo, color)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mov_almacen_fecha_mobile ON movimientos_almacen(fecha DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mov_almacen_codigo_mobile ON movimientos_almacen(codigo)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_pagos_nota_mobile ON pagos(nota_id, fecha DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_wa_conv_telefono_mobile ON whatsapp_conversaciones(telefono)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_wa_msg_conv_fecha_mobile ON whatsapp_mensajes(conversacion_id, fecha DESC)")

    _schema_ready = True


@app.before_request
def before_request():
    if request.path.startswith("/api/"):
        ensure_schema()
        err = require_pin()
        if err:
            return err


# =========================
# Static app
# =========================
@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(APP_DIR, "manifest.webmanifest")


@app.route("/sw.js")
def sw():
    return send_from_directory(APP_DIR, "sw.js")


@app.route("/icon-192.png")
def icon_192():
    return send_from_directory(APP_DIR, "icon-192.png")


@app.route("/icon-512.png")
def icon_512():
    return send_from_directory(APP_DIR, "icon-512.png")


# =========================
# Basic APIs
# =========================
@app.route("/api/health")
def health():
    ensure_schema()
    return jsonify({
        "ok": True,
        "service": "Hilorama Celular API",
        "version": "fase4",
        "time": now_mexico().isoformat(sep=" ", timespec="seconds"),
        "pin_enabled": bool(os.environ.get("MOBILE_PIN", "").strip()),
    })


@app.route("/api/resumen")
def resumen():
    with DB() as db:
        rows = db.execute("""
            SELECT estado, COUNT(*) AS total
            FROM notas
            GROUP BY estado
        """).fetchall()
    data = {r["estado"] or "SIN_ESTADO": int(r["total"]) for r in rows}
    return jsonify(json_safe(data))


@app.route("/api/pedidos")
def listar_pedidos():
    with DB() as db:
        pedidos = []
        if table_exists(db, "pedidos"):
            try:
                rows = db.execute("""
                    SELECT numero, COALESCE(activo,false) AS activo
                    FROM pedidos
                    ORDER BY numero DESC
                    LIMIT 50
                """).fetchall()
                pedidos = [{"numero": str(r["numero"]), "activo": bool(r.get("activo"))} for r in rows]
            except Exception:
                db.rollback()
        if not pedidos:
            rows = db.execute("""
                SELECT DISTINCT pedido
                FROM notas
                WHERE pedido IS NOT NULL AND pedido <> ''
                ORDER BY pedido DESC
                LIMIT 50
            """).fetchall()
            pedidos = [{"numero": str(r["pedido"]), "activo": False} for r in rows]
    return jsonify(json_safe(pedidos))



def _es_inventariable(valor):
    if isinstance(valor, str):
        return valor.strip().lower() not in ("false", "f", "0", "no", "n", "item", "sin inventario")
    return bool(True if valor is None else valor)


def _stock_estado(stock):
    try:
        stock = int(stock or 0)
    except Exception:
        stock = 0
    return "OK" if stock >= 50 else "RESURTIR"


def _registrar_movimiento_almacen(db, tipo, producto=None, cantidad=0, stock_anterior=None, stock_nuevo=None,
                                  campo="stock", valor_anterior=None, valor_nuevo=None, motivo="", nota_id=None,
                                  usuario="movil"):
    """Historial compatible con el almacén de PC.

    Importante en PostgreSQL: si un INSERT opcional falla y solo se atrapa con
    try/except, la transacción queda "aborted" y todo lo siguiente falla con
    "current transaction is aborted". Por eso usamos SAVEPOINT: si el historial
    falla, se revierte solo ese insert y la venta/pago continúa normal.
    """
    producto = dict(producto or {})
    sp_name = "sp_movimiento_almacen_safe"
    try:
        db.execute(f"SAVEPOINT {sp_name}")
        db.execute("""
            INSERT INTO movimientos_almacen
            (fecha, tipo, nota_id, producto_id, marca, hilo, color, codigo, codigo_barras,
             stock_anterior, stock_nuevo, cantidad, campo, valor_anterior, valor_nuevo, motivo, usuario)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            now_mexico(), tipo, nota_id, producto.get("id") or producto.get("producto_id"),
            producto.get("marca"), producto.get("hilo"), producto.get("color"), producto.get("codigo"), producto.get("codigo_barras"),
            stock_anterior, stock_nuevo, int(cantidad or 0), campo,
            None if valor_anterior is None else str(valor_anterior),
            None if valor_nuevo is None else str(valor_nuevo),
            motivo, usuario,
        ))
        db.execute(f"RELEASE SAVEPOINT {sp_name}")
    except Exception as exc:
        try:
            db.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            db.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:
            pass
        print("WARN movimiento_almacen no registrado:", exc, flush=True)


def _items_para_descontar_stock(db, nota_id):
    rows = db.execute("""
        SELECT
            i.id AS item_id,
            COALESCE(i.producto_id, p.id) AS producto_id,
            i.codigo,
            COALESCE(NULLIF(i.marca,''), p.marca, '') AS marca,
            COALESCE(NULLIF(i.hilo,''), p.hilo, '') AS hilo,
            COALESCE(NULLIF(i.color,''), p.color, '') AS color,
            COALESCE(i.cantidad,0) AS cantidad,
            p.codigo_barras,
            COALESCE(p.stock,0) AS stock,
            COALESCE(p.es_inventariable, TRUE) AS es_inventariable
        FROM items i
        LEFT JOIN LATERAL (
            SELECT p2.*
            FROM productos p2
            WHERE
                (i.producto_id IS NOT NULL AND p2.id=i.producto_id)
                OR (
                    i.producto_id IS NULL
                    AND (p2.codigo=i.codigo OR p2.codigo_barras=i.codigo)
                    AND (NULLIF(i.marca,'') IS NULL OR UPPER(COALESCE(p2.marca,''))=UPPER(i.marca))
                    AND (NULLIF(i.hilo,'') IS NULL OR UPPER(COALESCE(p2.hilo,''))=UPPER(i.hilo))
                    AND (NULLIF(i.color,'') IS NULL OR UPPER(COALESCE(p2.color,''))=UPPER(i.color))
                )
            ORDER BY
                CASE WHEN i.producto_id IS NOT NULL AND p2.id=i.producto_id THEN 0 ELSE 1 END,
                CASE WHEN UPPER(COALESCE(p2.marca,''))=UPPER(COALESCE(i.marca,'')) THEN 0 ELSE 1 END,
                CASE WHEN UPPER(COALESCE(p2.hilo,''))=UPPER(COALESCE(i.hilo,'')) THEN 0 ELSE 1 END,
                CASE WHEN UPPER(COALESCE(p2.color,''))=UPPER(COALESCE(i.color,'')) THEN 0 ELSE 1 END,
                COALESCE(p2.stock,0) DESC,
                p2.id ASC
            LIMIT 1
        ) p ON TRUE
        WHERE i.nota_id=%s
        ORDER BY i.id
    """, (nota_id,)).fetchall()
    return [dict(r) for r in rows]


def _descontar_stock_de_nota(db, nota_id):
    """Descuenta stock una sola vez: al convertir cotización a venta o al pagar directo una cotización."""
    items = _items_para_descontar_stock(db, nota_id)
    for it in items:
        cantidad = int(it.get("cantidad") or 0)
        if cantidad <= 0:
            continue
        if not it.get("producto_id"):
            raise ValueError(f"No encontré producto exacto para {it.get('codigo')}")
        es_inv = _es_inventariable(it.get("es_inventariable"))
        stock = int(it.get("stock") or 0)
        if es_inv and stock < cantidad:
            raise ValueError(f"Stock insuficiente {it.get('codigo')} {it.get('marca','')}/{it.get('hilo','')} ({stock} disponibles)")
    descontados = []
    for it in items:
        cantidad = int(it.get("cantidad") or 0)
        es_inv = _es_inventariable(it.get("es_inventariable"))
        if not es_inv or cantidad <= 0:
            continue
        stock_anterior = int(it.get("stock") or 0)
        stock_nuevo = stock_anterior - cantidad
        prod_id = int(it.get("producto_id"))
        row = db.execute("""
            UPDATE productos
            SET stock=%s, estado=%s
            WHERE id=%s
            RETURNING id, codigo, codigo_barras, marca, hilo, color, stock, estado
        """, (stock_nuevo, _stock_estado(stock_nuevo), prod_id)).fetchone()
        prod = dict(row) if row else {"id": prod_id, "codigo": it.get("codigo"), "marca": it.get("marca"), "hilo": it.get("hilo"), "color": it.get("color")}
        _registrar_movimiento_almacen(
            db, "SALIDA_STOCK", prod, cantidad=-cantidad,
            stock_anterior=stock_anterior, stock_nuevo=stock_nuevo,
            motivo="Venta desde celular", nota_id=nota_id,
        )
        descontados.append({"codigo": prod.get("codigo"), "cantidad": cantidad, "stock_anterior": stock_anterior, "stock_nuevo": stock_nuevo})
    return descontados


@app.route("/api/almacen/movimientos")
def listar_movimientos_almacen():
    q = (request.args.get("q") or "").strip().lower()
    limit = min(int(request.args.get("limit") or 80), 200)
    params = []
    where = ["1=1"]
    if q:
        like = f"%{q}%"
        where.append("(LOWER(COALESCE(codigo,'')) LIKE %s OR LOWER(COALESCE(color,'')) LIKE %s OR LOWER(COALESCE(marca,'')) LIKE %s OR LOWER(COALESCE(hilo,'')) LIKE %s OR LOWER(COALESCE(nota_id,'')) LIKE %s)")
        params.extend([like, like, like, like, like])
    with DB() as db:
        rows = db.execute(f"""
            SELECT * FROM movimientos_almacen
            WHERE {' AND '.join(where)}
            ORDER BY fecha DESC, id DESC
            LIMIT {limit}
        """, params).fetchall()
    return jsonify(json_safe([dict(r) for r in rows]))


@app.route("/api/envios")
def listar_envios():
    # Opciones básicas para app móvil. La PC puede seguir usando su configuración completa.
    return jsonify([
        {"paqueteria": "Sin envio", "precio": 0},
        {"paqueteria": "Correos de Mexico", "precio": 0},
        {"paqueteria": "Estafeta", "precio": 0},
        {"paqueteria": "FedEx", "precio": 0},
        {"paqueteria": "Entrega en Tienda", "precio": 0},
    ])


@app.route("/api/notas")
def listar_notas():
    estado = (request.args.get("estado") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()
    limit = min(int(request.args.get("limit") or 100), 300)

    params = []
    where = ["1=1"]
    if estado and estado != "TODOS":
        where.append("n.estado=%s")
        params.append(estado)
    if q:
        where.append("""
            (
                LOWER(COALESCE(n.id,'')) LIKE %s OR
                LOWER(COALESCE(c.nombre,n.cliente_nombre,'')) LIKE %s OR
                LOWER(COALESCE(n.pedido,'')) LIKE %s OR
                LOWER(COALESCE(c.telefono,'')) LIKE %s
            )
        """)
        like = f"%{q}%"
        params.extend([like, like, like, like])

    with DB() as db:
        rows = db.execute(f"""
            SELECT
                n.id, n.cliente_id, COALESCE(c.nombre, n.cliente_nombre) AS cliente_nombre, n.fecha, n.estado,
                n.total, n.envio, n.pedido, n.comprobante, n.fecha_pago,
                n.metodo_pago, n.monto_pagado, n.referencia_pago,
                n.paqueteria, n.empacador_id, n.empacador, n.fecha_asignacion,
                c.telefono,
                COUNT(i.id) AS items_count,
                COALESCE(SUM(i.cantidad),0) AS piezas_total,
                COALESCE(SUM(i.empacadas),0) AS piezas_empacadas
            FROM notas n
            LEFT JOIN clientes c ON c.id=n.cliente_id
            LEFT JOIN items i ON i.nota_id=n.id
            WHERE {' AND '.join(where)}
            GROUP BY n.id, c.nombre, c.telefono
            ORDER BY n.id DESC
            LIMIT {limit}
        """, params).fetchall()

    notas = [dict(r) for r in rows]
    notas.sort(key=nota_sort_key, reverse=True)
    return jsonify(json_safe(notas))


@app.route("/api/notas/<nota_id>")
def detalle_nota(nota_id):
    with DB() as db:
        nota = db.execute("""
            SELECT n.*, c.nombre AS cliente_nombre_real, c.telefono, c.direccion
            FROM notas n
            LEFT JOIN clientes c ON c.id=n.cliente_id
            WHERE n.id=%s
        """, (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404

        items = db.execute("""
            SELECT
                MIN(i.id) AS id,
                MIN(COALESCE(i.producto_id, p.id)) AS producto_id,
                i.codigo,
                COALESCE(NULLIF(i.marca,''), p.marca, '') AS marca,
                COALESCE(NULLIF(i.hilo,''), p.hilo, '') AS hilo,
                COALESCE(NULLIF(i.color,''), p.color, '') AS color,
                SUM(COALESCE(i.cantidad,0)) AS cantidad,
                SUM(COALESCE(i.empacadas,0)) AS empacadas,
                COALESCE(NULLIF(MAX(i.precio),0), MAX(pr.venta), MAX(p.precio), 0) AS precio,
                COALESCE(MAX(p.stock),0) AS stock,
                COALESCE(BOOL_OR(COALESCE(p.es_inventariable, TRUE)), TRUE) AS es_inventariable
            FROM items i
            LEFT JOIN LATERAL (
                SELECT p2.*
                FROM productos p2
                WHERE
                    (i.producto_id IS NOT NULL AND p2.id=i.producto_id)
                    OR (
                        i.producto_id IS NULL
                        AND (p2.codigo=i.codigo OR p2.codigo_barras=i.codigo)
                        AND (NULLIF(i.marca,'') IS NULL OR UPPER(COALESCE(p2.marca,''))=UPPER(i.marca))
                        AND (NULLIF(i.hilo,'') IS NULL OR UPPER(COALESCE(p2.hilo,''))=UPPER(i.hilo))
                        AND (NULLIF(i.color,'') IS NULL OR UPPER(COALESCE(p2.color,''))=UPPER(i.color))
                    )
                ORDER BY
                    CASE WHEN i.producto_id IS NOT NULL AND p2.id=i.producto_id THEN 0 ELSE 1 END,
                    CASE
                        WHEN UPPER(COALESCE(p2.marca,''))=UPPER(COALESCE(i.marca,''))
                         AND UPPER(COALESCE(p2.hilo,''))=UPPER(COALESCE(i.hilo,'')) THEN 0
                        ELSE 1
                    END,
                    CASE WHEN UPPER(COALESCE(p2.color,''))=UPPER(COALESCE(i.color,'')) THEN 0 ELSE 1 END,
                    COALESCE(p2.stock,0) DESC,
                    p2.id
                LIMIT 1
            ) p ON TRUE
            LEFT JOIN precios pr ON pr.marca = COALESCE(NULLIF(i.marca,''), p.marca)
            WHERE i.nota_id=%s
            GROUP BY
                i.codigo,
                COALESCE(NULLIF(i.marca,''), p.marca, ''),
                COALESCE(NULLIF(i.hilo,''), p.hilo, ''),
                COALESCE(NULLIF(i.color,''), p.color, '')
            ORDER BY MIN(i.id)
        """, (nota_id,)).fetchall()

    n = dict(nota)
    n["direccion"] = parse_json_text(n.get("direccion"), {})
    n["envio"] = parse_json_text(n.get("envio"), {})
    n["items"] = [dict(i) for i in items]
    return jsonify(json_safe(n))


# =========================
# Clientes / productos
# =========================
@app.route("/api/clientes")
def buscar_clientes():
    q = (request.args.get("q") or "").strip().lower()
    limit = min(int(request.args.get("limit") or 30), 100)

    params = []
    where = ["1=1"]
    if q:
        where.append("""
            (
                LOWER(COALESCE(nombre,'')) LIKE %s OR
                LOWER(COALESCE(telefono,'')) LIKE %s
            )
        """)
        like = f"%{q}%"
        params.extend([like, like])

    with DB() as db:
        rows = db.execute(f"""
            SELECT id, nombre, telefono, direccion
            FROM clientes
            WHERE {' AND '.join(where)}
            ORDER BY nombre
            LIMIT {limit}
        """, params).fetchall()

    data = []
    for r in rows:
        c = dict(r)
        c["direccion"] = parse_json_text(c.get("direccion"), {})
        data.append(c)
    return jsonify(json_safe(data))


@app.route("/api/clientes", methods=["POST"])
def crear_cliente():
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    direccion = data.get("direccion") or {
        "calle": "",
        "numero_ext": "",
        "numero_int": "",
        "colonia": "",
        "codigo_postal": "",
        "estado": "",
        "municipio": "",
        "referencia": "",
    }

    if not nombre:
        return jsonify({"ok": False, "error": "Falta nombre del cliente"}), 400

    with DB() as db:
        row = db.execute("""
            INSERT INTO clientes (nombre, telefono, direccion)
            VALUES (%s,%s,%s)
            RETURNING id, nombre, telefono, direccion
        """, (nombre, telefono, json.dumps(direccion, ensure_ascii=False))).fetchone()

    c = dict(row)
    c["direccion"] = parse_json_text(c.get("direccion"), {})
    return jsonify(json_safe({"ok": True, "cliente": c}))


@app.route("/api/clientes/<cliente_ref>", methods=["PUT", "PATCH"])
def actualizar_cliente(cliente_ref):
    data = request.get_json(force=True) or {}
    nombre = (data.get("nombre") or "").strip()
    telefono = re.sub(r"\D+", "", str(data.get("telefono") or ""))
    direccion = normalizar_direccion(data.get("direccion") or {})
    validar = bool(data.get("validar", False))

    if not nombre:
        return jsonify({"ok": False, "error": "Nombre obligatorio"}), 400
    if validar and len(telefono) != 10:
        return jsonify({"ok": False, "error": "Teléfono inválido. Deben ser 10 dígitos."}), 400
    if validar:
        ok, faltantes = validar_cliente_completo({"nombre": nombre, "telefono": telefono, "direccion": direccion})
        if not ok:
            return jsonify({"ok": False, "code": "CLIENTE_INCOMPLETO", "error": "Faltan datos del cliente", "faltantes": faltantes}), 400

    cliente_ref = str(cliente_ref or "").strip()
    with DB() as db:
        cliente_id = None
        if cliente_ref.isdigit():
            cliente_id = int(cliente_ref)
        else:
            # Respaldo móvil: si por caché o flujo viejo llega COT-xxxxx/VEN-xxxxx,
            # buscamos el cliente ligado a esa nota en vez de regresar 404.
            nota = db.execute("SELECT cliente_id FROM notas WHERE id=%s", (cliente_ref,)).fetchone()
            if nota and nota.get("cliente_id"):
                cliente_id = nota.get("cliente_id")
        if not cliente_id:
            return jsonify({"ok": False, "error": "Cliente no encontrado para actualizar", "ref": cliente_ref}), 404

        row = db.execute("""
            UPDATE clientes
            SET nombre=%s, telefono=%s, direccion=%s
            WHERE id=%s
            RETURNING id, nombre, telefono, direccion
        """, (nombre, telefono, json.dumps(direccion, ensure_ascii=False), cliente_id)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Cliente no encontrado"}), 404

        # Mantener sincronizado el nombre visible en notas antiguas.
        # Las notas guardan una copia de cliente_nombre para listados/PDFs; si no se actualiza,
        # el cliente queda bien en la tabla clientes pero la app vuelve a mostrar el nombre viejo.
        db.execute("""
            UPDATE notas
            SET cliente_nombre=%s
            WHERE cliente_id=%s
        """, (nombre, cliente_id))
    c = dict(row)
    c["direccion"] = normalizar_direccion(c.get("direccion"))
    c["completo"], c["faltantes"] = validar_cliente_completo(c)
    return jsonify(json_safe({"ok": True, "cliente": c}))


@app.route("/api/cp/<cp>")
def buscar_cp(cp):
    cp = str(cp or "").strip()
    if not re.fullmatch(r"\d{5}", cp):
        return jsonify({"ok": False, "error": "CP inválido"}), 400
    ruta = os.path.join(APP_DIR, "cp_offline.json")
    if not os.path.exists(ruta):
        return jsonify({"ok": False, "error": "No está cargada la base de códigos postales"}), 404
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)
        info = data.get(cp) or data.get(str(cp).zfill(5))
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No pude leer la base de CP: {exc}"}), 500
    if not info:
        return jsonify({"ok": False, "error": "No encontré ese CP"}), 404
    colonias = info.get("colonias") if isinstance(info.get("colonias"), list) else []
    return jsonify(json_safe({
        "ok": True,
        "cp": cp,
        "estado": info.get("estado", ""),
        "municipio": info.get("municipio", ""),
        "colonias": colonias,
    }))


@app.route("/api/productos")
def buscar_productos():
    q = (request.args.get("q") or "").strip().lower()
    marca = (request.args.get("marca") or "").strip()
    hilo = (request.args.get("hilo") or "").strip()
    limit = min(int(request.args.get("limit") or 80), 300)

    params = []
    where = ["1=1"]

    if q:
        where.append("""
            (
                LOWER(COALESCE(p.codigo,'')) LIKE %s OR
                LOWER(COALESCE(p.codigo_barras,'')) LIKE %s OR
                LOWER(COALESCE(p.marca,'')) LIKE %s OR
                LOWER(COALESCE(p.hilo,'')) LIKE %s OR
                LOWER(COALESCE(p.color,'')) LIKE %s
            )
        """)
        like = f"%{q}%"
        params.extend([like, like, like, like, like])

    if marca:
        where.append("p.marca=%s")
        params.append(marca)

    if hilo:
        where.append("p.hilo=%s")
        params.append(hilo)

    with DB() as db:
        rows = db.execute(f"""
            SELECT
                p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                COALESCE(p.stock,0) AS stock,
                COALESCE(p.estado,'') AS estado,
                COALESCE(p.volumetrico,1) AS volumetrico,
                COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
                COALESCE(p.tipo_producto, 'INVENTARIO') AS tipo_producto,
                COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), 0) AS precio_venta,
                COALESCE(p.costo_neto,0) AS costo_neto
            FROM productos p
            LEFT JOIN precios pr ON pr.marca = p.marca
            WHERE {' AND '.join(where)}
            ORDER BY p.marca, p.hilo, p.color, p.codigo
            LIMIT {limit}
        """, params).fetchall()

    return jsonify(json_safe([dict(r) for r in rows]))



@app.route("/api/productos/<codigo>", methods=["PATCH"])
def actualizar_producto(codigo):
    """Compatibilidad: actualiza por código, pero si hay códigos repetidos es mejor usar /api/productos/id/<id>."""
    data = request.get_json(force=True) or {}
    allowed = []
    params = []

    if "color" in data:
        allowed.append("color=%s")
        params.append((data.get("color") or "").strip())
    stock_nuevo_req = None
    if "stock" in data:
        try:
            stock_nuevo_req = int(data.get("stock"))
        except Exception:
            return jsonify({"ok": False, "error": "Stock inválido"}), 400
        allowed.append("stock=%s")
        params.append(stock_nuevo_req)
        allowed.append("estado=%s")
        params.append(_stock_estado(stock_nuevo_req))

    if not allowed:
        return jsonify({"ok": False, "error": "No hay cambios"}), 400

    with DB() as db:
        antes = db.execute("SELECT * FROM productos WHERE codigo=%s ORDER BY id LIMIT 1", (codigo,)).fetchone()
        if not antes:
            return jsonify({"ok": False, "error": "Producto no encontrado"}), 404
        params2 = list(params) + [codigo]
        row = db.execute(f"""
            UPDATE productos
            SET {', '.join(allowed)}
            WHERE codigo=%s
            RETURNING id, codigo, codigo_barras, marca, hilo, color, stock, estado
        """, params2).fetchone()
        if row and stock_nuevo_req is not None:
            ant = dict(antes)
            prod = dict(row)
            stock_anterior = int(ant.get("stock") or 0)
            _registrar_movimiento_almacen(
                db, "AJUSTE_STOCK", prod, cantidad=stock_nuevo_req-stock_anterior,
                stock_anterior=stock_anterior, stock_nuevo=stock_nuevo_req,
                valor_anterior=stock_anterior, valor_nuevo=stock_nuevo_req,
                motivo="Edición manual de stock desde celular",
            )
    return jsonify(json_safe({"ok": True, "producto": dict(row)}))


@app.route("/api/productos/id/<int:producto_id>", methods=["PATCH"])
def actualizar_producto_por_id(producto_id):
    data = request.get_json(force=True) or {}
    allowed = []
    params = []

    if "color" in data:
        allowed.append("color=%s")
        params.append((data.get("color") or "").strip())
    stock_nuevo_req = None
    if "stock" in data:
        try:
            stock_nuevo_req = int(data.get("stock"))
        except Exception:
            return jsonify({"ok": False, "error": "Stock inválido"}), 400
        allowed.append("stock=%s")
        params.append(stock_nuevo_req)
        allowed.append("estado=%s")
        params.append(_stock_estado(stock_nuevo_req))

    if not allowed:
        return jsonify({"ok": False, "error": "No hay cambios"}), 400

    with DB() as db:
        antes = db.execute("SELECT * FROM productos WHERE id=%s", (producto_id,)).fetchone()
        if not antes:
            return jsonify({"ok": False, "error": "Producto no encontrado"}), 404
        params2 = list(params) + [producto_id]
        row = db.execute(f"""
            UPDATE productos
            SET {', '.join(allowed)}
            WHERE id=%s
            RETURNING id, codigo, codigo_barras, marca, hilo, color, stock, estado
        """, params2).fetchone()
        prod = dict(row)
        ant = dict(antes)
        if stock_nuevo_req is not None:
            stock_anterior = int(ant.get("stock") or 0)
            _registrar_movimiento_almacen(
                db, "AJUSTE_STOCK", prod, cantidad=stock_nuevo_req-stock_anterior,
                stock_anterior=stock_anterior, stock_nuevo=stock_nuevo_req,
                valor_anterior=stock_anterior, valor_nuevo=stock_nuevo_req,
                motivo="Edición manual de stock desde celular",
            )
        if "color" in data and (ant.get("color") or "") != (prod.get("color") or ""):
            _registrar_movimiento_almacen(
                db, "AJUSTE_COLOR", prod, cantidad=0,
                stock_anterior=ant.get("stock"), stock_nuevo=prod.get("stock"), campo="color",
                valor_anterior=ant.get("color"), valor_nuevo=prod.get("color"),
                motivo="Edición manual de color desde celular",
            )
    return jsonify(json_safe({"ok": True, "producto": prod}))


@app.route("/api/catalogo/marcas")
def catalogo_marcas():
    with DB() as db:
        rows = db.execute("""
            SELECT DISTINCT marca
            FROM productos
            WHERE marca IS NOT NULL AND TRIM(marca) <> ''
            ORDER BY marca
        """).fetchall()
    return jsonify([r["marca"] for r in rows])


@app.route("/api/catalogo/hilos")
def catalogo_hilos():
    marca = (request.args.get("marca") or "").strip()
    params = []
    where = ["hilo IS NOT NULL", "TRIM(hilo) <> ''"]
    if marca:
        where.append("marca=%s")
        params.append(marca)
    with DB() as db:
        rows = db.execute(f"""
            SELECT DISTINCT hilo
            FROM productos
            WHERE {' AND '.join(where)}
            ORDER BY hilo
        """, params).fetchall()
    return jsonify([r["hilo"] for r in rows])


def _norm_txt(v):
    v = (v or '').strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', v) if unicodedata.category(c) != 'Mn')


COLOR_GRUPOS = {
    'negro': ['negro','negra','black','blac','blak','obscuro','oscuro'],
    'blanco': ['blanco','blanca','white','crudo','hueso','marfil','ivory'],
    'gris': ['gris','gray','grey','plata','plateado','silver'],
    'rojo': ['rojo','roja','red','cereza','escarlata'],
    'vino': ['vino','vinotinto','guinda','borgona','burgundy'],
    'rosa': ['rosa','rosita','pink','fucsia','fiusha','rosa mexicano','mexicano'],
    'morado': ['morado','morada','purple','violeta','lila','lavanda','uva'],
    'azul': ['azul','blue','celeste','cielo','marino','azul rey','rey'],
    'verde': ['verde','green','bandera','menta','olivo','pistache','militar','limon'],
    'amarillo': ['amarillo','amarilla','yellow','mostaza','canario','oro'],
    'naranja': ['naranja','orange','mandarina','coral','salmon'],
    'cafe': ['cafe','brown','marron','chocolate','camel','capuchino'],
    'beige': ['beige','crema','nude','arena','champagne'],
    'dorado': ['dorado','dorada','gold'],
}

COMPATIBILIDAD_COLORES = {
    'negro': ['blanco','gris','rojo','rosa','beige'],
    'blanco': ['negro','azul','rosa','beige','gris'],
    'gris': ['negro','rosa','azul','blanco','vino'],
    'rojo': ['negro','blanco','gris','beige','vino'],
    'vino': ['beige','gris','blanco','rosa','negro'],
    'rosa': ['gris','blanco','beige','morado','vino'],
    'morado': ['rosa','gris','blanco','beige','azul'],
    'azul': ['blanco','gris','beige','negro','verde'],
    'verde': ['beige','blanco','gris','azul','cafe'],
    'amarillo': ['gris','blanco','cafe','verde','naranja'],
    'naranja': ['beige','gris','cafe','amarillo','verde'],
    'cafe': ['beige','blanco','verde','naranja','amarillo'],
    'beige': ['cafe','rosa','blanco','verde','vino'],
    'dorado': ['negro','blanco','vino','beige','gris'],
}


def _color_canon(texto):
    t = _norm_txt(texto)
    encontrados = []
    for canon, aliases in COLOR_GRUPOS.items():
        for a in aliases:
            aa = _norm_txt(a)
            if aa and re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t):
                if canon not in encontrados:
                    encontrados.append(canon)
                break
    return encontrados


def _extraer_referencia_visual(texto):
    t = _norm_txt(texto)
    if not t:
        return None
    ref = {'raw': texto}
    m = re.search(r'(?:de ese|de la foto|de la imagen|quiero el|ese|el numero|numero)\s*(\d+)', t)
    if m:
        ref['numero'] = int(m.group(1))
    posiciones = []
    patrones = [
        ('arriba_derecha', r'arriba\s+(?:a\s+la\s+)?derecha'),
        ('arriba_izquierda', r'arriba\s+(?:a\s+la\s+)?izquierda'),
        ('abajo_derecha', r'abajo\s+(?:a\s+la\s+)?derecha'),
        ('abajo_izquierda', r'abajo\s+(?:a\s+la\s+)?izquierda'),
        ('arriba', r'\bde arriba\b|\barriba\b'),
        ('abajo', r'\bde abajo\b|\babajo\b'),
        ('medio', r'en medio|de en medio|del medio|centro'),
        ('derecha', r'\bderecha\b'),
        ('izquierda', r'\bizquierda\b'),
        ('primero', r'el primero|la primera|primero'),
        ('segundo', r'el segundo|la segunda|segundo'),
        ('tercero', r'el tercero|la tercera|tercero'),
        ('ultimo', r'el ultimo|el ultimo de abajo|ultima|ultimo'),
    ]
    for nombre, pat in patrones:
        if re.search(pat, t):
            posiciones.append(nombre)
    if posiciones:
        ref['posiciones'] = posiciones
    if 'tachado' in t or 'tachame' in t or 'tachon' in t:
        ref['accion'] = 'excluir_tachado'
    if 'circulo' in t or 'encerrado' in t or 'rodeado' in t:
        ref['marca'] = 'circulo'
    if 'flecha' in t or 'senalado' in t or 'señalado' in t:
        ref['marca'] = 'flecha'
    return ref if len(ref) > 1 else None


def _es_intencion_historial(texto):
    t = _norm_txt(texto)
    frases = [
        'los mismos de ayer','lo mismo de ayer','los mismos de la ultima vez','lo mismo de la ultima vez',
        'los mismos de la vez pasada','lo mismo que ayer','igual que ayer','igual que la vez pasada','los mismos de siempre'
    ]
    return any(f in t for f in frases)


def _resolver_items_ultima_nota(db, cliente_nombre='', telefono=''):
    where = []
    params = []
    if cliente_nombre:
        where.append("LOWER(COALESCE(n.cliente_nombre,'')) = %s")
        params.append(cliente_nombre.strip().lower())
    if telefono:
        where.append("LOWER(COALESCE(c.telefono,'')) = %s")
        params.append(telefono.strip().lower())
    if not where:
        return None, []
    row = db.execute(f"""
        SELECT n.id, n.fecha
        FROM notas n
        LEFT JOIN clientes c ON c.id = n.cliente_id
        WHERE {' OR '.join(where)}
        ORDER BY n.fecha DESC, n.id DESC
        LIMIT 1
    """, params).fetchone()
    if not row:
        return None, []
    items = db.execute("""
        SELECT i.codigo, COALESCE(i.cantidad,1) AS cantidad,
               COALESCE(i.marca, p.marca) AS marca,
               COALESCE(i.hilo, p.hilo) AS hilo,
               COALESCE(i.color, p.color) AS color,
               COALESCE(p.stock,0) AS stock,
               COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), NULLIF(i.precio,0), 0) AS precio_venta,
               COALESCE(p.es_inventariable, TRUE) AS es_inventariable
        FROM items i
        LEFT JOIN productos p ON p.codigo = i.codigo
        LEFT JOIN precios pr ON pr.marca = COALESCE(i.marca, p.marca)
        WHERE i.nota_id=%s
        ORDER BY i.id
    """, (row['id'],)).fetchall()
    return row['id'], [dict(i) for i in items]


def _armar_pedidos_desde_items(items_rows):
    pedidos = []
    for prod in items_rows:
        pedidos.append({
            'producto_id': prod.get('id'),
            'codigo': prod.get('codigo'),
            'marca': prod.get('marca') or '',
            'hilo': prod.get('hilo') or '',
            'color': prod.get('color') or '',
            'stock': int(prod.get('stock') or 0),
            'precio_venta': float(prod.get('precio_venta') or 0),
            'cantidad': int(prod.get('cantidad') or 1),
            'es_inventariable': prod.get('es_inventariable', True),
        })
    return pedidos


def _productos_uno_de_cada_color(productos):
    vistos = set()
    elegidos = []
    for p in productos:
        clave = _norm_txt(p.get('color'))
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        elegidos.append(p)
    return elegidos


def _productos_top_vendidos(db, marca='', hilo='', limit=1):
    where = ["1=1"]
    params = []
    if marca:
        where.append("UPPER(COALESCE(p.marca,''))=UPPER(%s)")
        params.append(marca)
    if hilo:
        where.append("UPPER(COALESCE(p.hilo,''))=UPPER(%s)")
        params.append(hilo)
    rows = db.execute(f"""
        SELECT i.codigo,
               COALESCE(i.marca, p.marca) AS marca,
               COALESCE(i.hilo, p.hilo) AS hilo,
               COALESCE(i.color, p.color) AS color,
               COALESCE(p.stock,0) AS stock,
               COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), NULLIF(i.precio,0), 0) AS precio_venta,
               COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
               SUM(COALESCE(i.cantidad,0)) AS vendidas
        FROM items i
        LEFT JOIN notas n ON n.id = i.nota_id
        LEFT JOIN productos p ON p.codigo = i.codigo
        LEFT JOIN precios pr ON pr.marca = COALESCE(i.marca, p.marca)
        WHERE {' AND '.join(where)}
          AND COALESCE(n.estado,'') IN ('PAGADA','VENTA_PENDIENTE','EN_PROCESO')
        GROUP BY i.codigo, COALESCE(i.marca, p.marca), COALESCE(i.hilo, p.hilo), COALESCE(i.color, p.color), COALESCE(p.stock,0), COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), NULLIF(i.precio,0), 0), COALESCE(p.es_inventariable, TRUE)
        ORDER BY SUM(COALESCE(i.cantidad,0)) DESC, i.codigo ASC
        LIMIT %s
    """, tuple(params + [limit])).fetchall()
    return [dict(r) for r in rows]


def _productos_surtido_bonito(productos, limit=6):
    preferencia = ['beige','rosa','vino','gris','blanco','azul','verde','cafe','morado','rojo','amarillo','naranja','negro']
    buckets = {c: [] for c in preferencia}
    extras = []
    for p in productos:
        canon = (_color_canon(p.get('color') or '') or [''])[0]
        if canon in buckets:
            buckets[canon].append(p)
        else:
            extras.append(p)
    elegidos = []
    usados = set()
    for canon in preferencia:
        for p in buckets[canon]:
            key = _norm_txt(p.get('color'))
            if key and key not in usados:
                elegidos.append(p)
                usados.add(key)
                break
        if len(elegidos) >= limit:
            break
    for p in extras:
        if len(elegidos) >= limit:
            break
        key = _norm_txt(p.get('color'))
        if key and key not in usados:
            elegidos.append(p)
            usados.add(key)
    return elegidos[:limit]


def _buscar_tonos_parecidos(productos, texto, limit=6):
    colores = _color_canon(texto)
    if not colores:
        return []
    base = colores[0]
    grupo = [base] + COMPATIBILIDAD_COLORES.get(base, [])[:2]
    elegidos = []
    for c in grupo:
        for p in productos:
            canon = (_color_canon(p.get('color') or '') or [''])[0]
            if canon == c:
                elegidos.append(p)
        if len(elegidos) >= limit:
            break
    unicos = []
    vistos = set()
    for p in elegidos:
        key = (str(p.get('codigo')), _norm_txt(p.get('color')))
        if key in vistos:
            continue
        vistos.add(key)
        unicos.append(p)
        if len(unicos) >= limit:
            break
    return unicos


def _productos_combinados(productos, texto, limit=6):
    colores = _color_canon(texto)
    if colores:
        base = colores[0]
        objetivo = [base] + COMPATIBILIDAD_COLORES.get(base, [])
    else:
        objetivo = ['beige','rosa','gris','blanco','vino','azul']
    elegidos = []
    usados = set()
    for canon in objetivo:
        for p in productos:
            pc = (_color_canon(p.get('color') or '') or [''])[0]
            key = _norm_txt(p.get('color'))
            if pc == canon and key not in usados:
                elegidos.append(p)
                usados.add(key)
                break
        if len(elegidos) >= limit:
            break
    return elegidos


def _detectar_intenciones_especiales(texto):
    t = _norm_txt(texto)
    out = {'uno_de_cada': False, 'surtidos': 0, 'surtido_bonito': False, 'mas_vendido': 0, 'parecidos': False, 'combinar': False, 'visual': False}
    if any(x in t for x in ['uno de cada color','una de cada color','uno de cada tono','uno de cada','una de cada']):
        out['uno_de_cada'] = True
    m = re.search(r'(\d+)\s+surtid', t)
    if m:
        out['surtidos'] = int(m.group(1))
    elif 'surtido' in t and 'bonito' not in t:
        out['surtidos'] = 5
    if 'surtido bonito' in t or 'bonito surtido' in t or 'armame bonito' in t or 'armame un bonito surtido' in t:
        out['surtido_bonito'] = True
    if 'mas vendido' in t or 'más vendido' in t or 'el que mas sale' in t or 'el que más sale' in t:
        m2 = re.search(r'(\d+)\s+(?:mas vendidos|más vendidos)', t)
        out['mas_vendido'] = int(m2.group(1)) if m2 else 1
    if 'parecid' in t or 'similar' in t:
        out['parecidos'] = True
    if 'combinam' in t or 'combinal' in t or 'combinamel' in t or 'combinamelo' in t:
        out['combinar'] = True
    if any(x in t for x in ['foto','imagen','de ese','de la foto','de la imagen','circulo','flecha','tachado','arriba','abajo','izquierda','derecha']):
        out['visual'] = True
    return out


def _respuesta_pedidos_especial(pedidos, marca, hilo, productos, modo_especial, advertencias=None, referencia_visual=None):
    return jsonify(json_safe({
        'ok': True,
        'modo': modo_especial,
        'modo_especial': modo_especial,
        'contexto': {'marca': marca, 'hilo': hilo, 'productos_contexto': len(productos)},
        'pedidos': pedidos,
        'errores': [],
        'advertencias': advertencias or [],
        'sugerencias': {},
        'referencia_visual': referencia_visual,
    }))




# =========================
# WhatsApp IA: contexto automático por almacén
# =========================
def _wa_aliases_hilo(hilo):
    h = _norm_txt(hilo or '')
    aliases = set()
    if h:
        aliases.add(h)
        aliases.add(h.replace(' ', ''))
        aliases.add(h.replace('-', ' '))
    # Alias humanos comunes. Se generan aunque el nombre venga ligeramente distinto en BD.
    if 'velluto' in h or 'veluto' in h:
        aliases.update(['velluto','vellutos','veluto','velutos','vello','vellos','terciopelo','aterciopelado','chenille','chenil'])
    if 'komfy' in h or 'comfy' in h or 'komfi' in h:
        aliases.update(['komfy','komfy mini','komfymini','komfi','komfi mini','comfy','comfy mini','komfis'])
    if 'trapillo' in h or 'kraft' in h:
        aliases.update(['trapillo','trapillo kraft','kraft','trapiyo','trapiyos'])
    if 'alize' in h:
        aliases.update(['alize','alise'])
    return {a for a in aliases if a and len(a) >= 3}


def _wa_catalogo_hilos(productos):
    hilos = []
    seen = set()
    for p in productos or []:
        h = (p.get('hilo') or '').strip()
        if h and _norm_txt(h) not in seen:
            hilos.append(h)
            seen.add(_norm_txt(h))
    return hilos


def _wa_detectar_hilos(texto, productos):
    t = _norm_txt(texto or '')
    if not t:
        return []
    hallados = []
    for h in _wa_catalogo_hilos(productos):
        for a in _wa_aliases_hilo(h):
            aa = _norm_txt(a)
            if not aa:
                continue
            # permite alias con espacios o pegados: komfy mini / komfymini
            if re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t) or aa.replace(' ', '') in t.replace(' ', ''):
                if h not in hallados:
                    hallados.append(h)
                break
    return hallados


def _wa_filtrar_por_hilo(productos, hilo):
    if not hilo:
        return list(productos or [])
    hn = _norm_txt(hilo)
    return [p for p in (productos or []) if _norm_txt(p.get('hilo') or '') == hn]


def _wa_filtrar_por_marca_hilo(productos, marca='', hilo=''):
    out = list(productos or [])
    if marca:
        mn = _norm_txt(marca)
        out = [p for p in out if _norm_txt(p.get('marca') or '') == mn]
    if hilo:
        hn = _norm_txt(hilo)
        out = [p for p in out if _norm_txt(p.get('hilo') or '') == hn]
    return out


def _wa_split_clausulas(texto):
    t = _norm_txt(texto or '')
    t = re.sub(r'\b(tambien|ademas|aparte|luego|y tambien|y aparte)\b', ',', t)
    # mantiene "pero de komfy mini" dentro de la misma cláusula; separa "pensándolo mejor" porque suele cancelar.
    t = re.sub(r'\b(pensandolo mejor|mejor|olvida|cancelame|quitame|quitalo|quita|no pongas|ya no quiero)\b', r', \1 ', t)
    partes = [x.strip(' ,.;') for x in re.split(r'[,;\n]+', t) if x.strip(' ,.;')]
    return partes or [t]


def _wa_es_quitar(texto):
    t = _norm_txt(texto or '')
    return bool(re.search(r'\b(quitame|quita|quitalo|elimina|saca|borra|cancelame|cancela|olvida|ya no quiero|mejor no|pensandolo mejor)\b', t))


def _wa_codigo_map(productos):
    d = {}
    for p in productos or []:
        for k in [p.get('codigo'), p.get('codigo_barras')]:
            c = str(k or '').strip().lstrip('0') or '0'
            if c != '0':
                d.setdefault(c, []).append(p)
    return d


def _wa_pedidos_full_desde_parse(parse, productos_ctx):
    por_codigo = _wa_codigo_map(productos_ctx)
    pedidos = []
    errores = []
    for ped in parse.get('pedidos', []) or []:
        codigo_norm = str(ped.get('codigo') or '').strip().lstrip('0') or '0'
        opciones = por_codigo.get(codigo_norm) or []
        if not opciones:
            errores.append(codigo_norm)
            continue
        prod = opciones[0]
        pedidos.append({
            'producto_id': prod.get('id'),
            'codigo': prod.get('codigo'),
            'marca': prod.get('marca') or '',
            'hilo': prod.get('hilo') or '',
            'color': prod.get('color') or '',
            'stock': int(prod.get('stock') or 0),
            'precio_venta': float(prod.get('precio_venta') or 0),
            'cantidad': int(ped.get('cantidad') or 1),
            'es_inventariable': prod.get('es_inventariable', True),
        })
    return pedidos, errores


def _wa_agregar_o_sumar(dest, prod):
    key = str(prod.get('producto_id') or '') or f"{prod.get('marca')}|{prod.get('hilo')}|{prod.get('codigo')}"
    if key in dest:
        dest[key]['cantidad'] = int(dest[key].get('cantidad') or 0) + int(prod.get('cantidad') or 1)
    else:
        dest[key] = dict(prod)


def _wa_remover_por_texto(pedidos_dict, texto, productos):
    hilos = _wa_detectar_hilos(texto, productos)
    tn = _norm_txt(texto or '')
    colores = []
    for grupo, aliases in COLOR_GRUPOS.items():
        if any(re.search(rf'(?<!\w){re.escape(_norm_txt(a))}(?!\w)', tn) for a in aliases):
            colores.append(grupo)
    borrar = []
    for k, p in pedidos_dict.items():
        ph = p.get('hilo') or ''
        pc = _norm_txt(p.get('color') or '')
        hit_hilo = bool(hilos and any(_norm_txt(h) == _norm_txt(ph) for h in hilos))
        hit_color = bool(colores and any(any(_norm_txt(a) in pc for a in COLOR_GRUPOS.get(c, [])) for c in colores))
        if hit_hilo or hit_color or (not hilos and not colores):
            borrar.append(k)
    for k in borrar:
        pedidos_dict.pop(k, None)
    return len(borrar)


def _wa_color_descripcion_keywords(texto):
    t = _norm_txt(texto or '')
    grupos = []
    for grupo, aliases in COLOR_GRUPOS.items():
        if any(re.search(rf'(?<!\w){re.escape(_norm_txt(a))}(?!\w)', t) for a in aliases):
            grupos.append(grupo)
    # descripciones humanas que no son color exacto
    if any(x in t for x in ['hueso','marfil','crudo','ivory','perla','crema']):
        grupos.extend(['blanco','beige'])
    if any(x in t for x in ['amarillento','amarillo suave','medio amarillo','calido','calida','mostaza','oro']):
        grupos.extend(['amarillo','beige','dorado'])
    if any(x in t for x in ['piel','carne','nude','arena']):
        grupos.extend(['beige','rosa','cafe'])
    # orden sin duplicados
    out=[]
    for g in grupos:
        if g not in out:
            out.append(g)
    return out


def _wa_sugerir_tonos_por_descripcion(texto, productos_ctx, limit=5):
    grupos = _wa_color_descripcion_keywords(texto)
    if not grupos:
        return []
    t = _norm_txt(texto or '')
    scored = []
    for p in productos_ctx or []:
        color = _norm_txt(p.get('color') or '')
        if not color:
            continue
        score = 0
        razones = []
        for g in grupos:
            aliases = [_norm_txt(a) for a in COLOR_GRUPOS.get(g, [])]
            if any(a and a in color for a in aliases):
                score += 6; razones.append(g)
        # palabras especiales que suelen existir como nombres de tono.
        especiales = ['hueso','crudo','marfil','crema','perla','beige','arena','camello','mango','oro','mostaza','carne','piel','nude','blanco']
        for e in especiales:
            if e in t and e in color:
                score += 8; razones.append(e)
        if int(p.get('stock') or 0) > 0:
            score += 1
        if score > 0:
            scored.append((score, p, ', '.join(sorted(set(razones))) or 'tono parecido'))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get('stock') or 0), str(x[1].get('codigo') or '')))
    out=[]
    seen=set()
    for score,p,razon in scored:
        key=(p.get('hilo'),p.get('codigo'))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            'producto_id': p.get('id'), 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
            'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
            'precio_venta': float(p.get('precio_venta') or 0), 'razon': razon, 'confianza': 'media-alta' if score >= 8 else 'media'
        })
        if len(out) >= limit:
            break
    return out


def _wa_sugerir_hilos_similares(texto, productos, limit=5):
    t = _norm_txt(texto or '')
    # Diccionario interno para poder decir "sé cuál es / es parecido a..." sin depender aún de una API de búsqueda web.
    textura_map = {
        'terciopelo': ['velluto','chenille','chenil','velvet','velour','felpa','suave','peluche'],
        'suave': ['velluto','komfy','chenille','peluche','felpa','aterciopelado'],
        'trapillo': ['trapillo','kraft','algodon','algodón','tshirt','playera'],
        'algodon': ['algodon','algodón','cotton','trapillo'],
        'delgado': ['mini','fino','bebé','bebe'],
        'grueso': ['chunky','grueso','mega','jumbo','bulky'],
    }
    wanted=[]
    for textura, aliases in textura_map.items():
        if any(a in t for a in aliases):
            wanted.append(textura)
    if not wanted:
        return []
    hilos = {}
    for p in productos or []:
        hn = _norm_txt(p.get('hilo') or '')
        if not hn:
            continue
        score=0
        for textura in wanted:
            for a in textura_map.get(textura, []):
                if _norm_txt(a) in hn:
                    score += 5
        if int(p.get('stock') or 0) > 0:
            score += 1
        if score > 0:
            cur = hilos.get(hn)
            if not cur or score > cur[0]:
                hilos[hn]=(score,p)
    arr=sorted(hilos.values(), key=lambda x: (-x[0], str(x[1].get('hilo') or '')))[:limit]
    return [{'marca':p.get('marca') or '', 'hilo':p.get('hilo') or '', 'ejemplo_codigo':p.get('codigo'), 'ejemplo_color':p.get('color') or '', 'stock': int(p.get('stock') or 0)} for score,p in arr]


def _wa_parsear_con_contexto_almacen(texto_total, productos_all, marca='', hilo='', extraer_pedidos_func=None):
    """Parser de capa superior para el agente.
    Usa el almacén para inferir hilos aunque la interfaz esté en Todas/Todos.
    Divide mensajes largos, respeta cambios tipo "pensándolo mejor quítame komfy"
    y devuelve sugerencias si la clienta describe textura/tono en lugar de código.
    """
    extraer = extraer_pedidos_func
    productos_base = _wa_filtrar_por_marca_hilo(productos_all, marca, hilo)
    texto_norm = _norm_txt(texto_total or '')
    hilos_globales = _wa_detectar_hilos(texto_norm, productos_base)
    contexto_global = hilo or (hilos_globales[0] if len(hilos_globales) == 1 else '')
    pedidos_dict = {}
    preguntas=[]; errores=[]; advertencias=[]; sugerencias=[]; hilos_detectados=[]
    ultimo_hilo = contexto_global

    for h in hilos_globales:
        if h not in hilos_detectados:
            hilos_detectados.append(h)

    for parte in _wa_split_clausulas(texto_norm):
        if not parte:
            continue
        hilos_parte = _wa_detectar_hilos(parte, productos_base)
        for h in hilos_parte:
            if h not in hilos_detectados:
                hilos_detectados.append(h)
        if _wa_es_quitar(parte):
            borrados = _wa_remover_por_texto(pedidos_dict, parte, productos_base)
            if borrados:
                advertencias.append(f"Se quitaron {borrados} producto(s) por indicación de la clienta: '{parte}'.")
            else:
                advertencias.append(f"La clienta pidió quitar algo, pero no encontré coincidencia clara: '{parte}'.")
            continue
        hilo_ctx = hilos_parte[0] if len(hilos_parte) == 1 else (ultimo_hilo or contexto_global)
        if hilo_ctx:
            ultimo_hilo = hilo_ctx
        productos_ctx = _wa_filtrar_por_hilo(productos_base, hilo_ctx) if hilo_ctx else productos_base
        parse = extraer(parte, productos_ctx) if extraer else {'pedidos': [], 'preguntas': [], 'errores': []}
        full, err = _wa_pedidos_full_desde_parse(parse, productos_ctx)
        for fp in full:
            _wa_agregar_o_sumar(pedidos_dict, fp)
        errores.extend(err)
        errores.extend(parse.get('errores') or [])
        preguntas.extend(parse.get('preguntas') or [])
        advertencias.extend(parse.get('advertencias') or [])

        # Si hubo duda por color/descripción, ofrece alternativas del almacén para que la respuesta sea útil.
        if hilo_ctx and (parse.get('preguntas') or []) and _wa_color_descripcion_keywords(parte):
            sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
            if sug:
                sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})

        # Si mencionó un hilo pero no se pudo convertir a producto, pregunta o sugiere tonos.
        if hilo_ctx and not full:
            # ¿Describe un tono en palabras?
            sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
            if sug:
                sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                preguntas.append(f"Para {hilo_ctx}, la clienta describió un tono. Sugiere opciones del almacén antes de agregar.")
            elif re.search(r'\b(codigo|cod|tono|color|lista|cuales|cuantos|tienes|manejas|hay|quiero|dame|ocupo|necesito)\b', parte):
                # Si pidió cantidad + hilo sin tono/código: "quiero 3 vellutos".
                m_qty = re.search(r'\b(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b', parte)
                if m_qty:
                    preguntas.append(f"Sí contamos con {hilo_ctx}. Falta confirmar qué tono o código quiere para {m_qty.group(1)} pieza(s).")
                else:
                    preguntas.append(f"Sí contamos con {hilo_ctx}. Pregunta si ya tiene lista de tonos/códigos o si busca un tono específico.")

    # Si no hay hilo exacto pero el texto parece pedir una textura/producto externo, sugiere similares.
    if not pedidos_dict and not sugerencias:
        similares = _wa_sugerir_hilos_similares(texto_norm, productos_base, limit=5)
        if similares:
            sugerencias.append({'tipo': 'hilo_similar', 'texto': texto_total, 'opciones': similares})
            preguntas.append('El producto exacto no se identificó en almacén; ofrece alternativas similares por textura.')

    return {
        'pedidos_full': list(pedidos_dict.values()),
        'errores': sorted(set(str(e) for e in errores if e)),
        'advertencias': sorted(set(str(a) for a in advertencias if a)),
        'preguntas': sorted(set(str(p) for p in preguntas if p)),
        'sugerencias_almacen': sugerencias,
        'hilos_detectados': hilos_detectados,
        'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales},
    }


@app.route("/api/parser-whatsapp", methods=["POST"])
def parser_whatsapp_mobile():
    """
    Parser mejorado para pedidos tipo WhatsApp con contexto, referencias visuales,
    frases abiertas, historial y sugerencias de combinación.
    """
    from parser_whatsapp import extraer_pedidos

    data = request.get_json(force=True) or {}
    texto = data.get("texto") or ""
    marca = (data.get("marca") or "").strip()
    hilo = (data.get("hilo") or "").strip()
    texto_imagen = (data.get("texto_imagen") or "").strip()
    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    imagen_referencia = bool(data.get("imagen_referencia"))

    if not texto.strip() and not texto_imagen.strip():
        return jsonify({"ok": False, "error": "Pega o escribe un pedido primero"}), 400

    texto_total = ((texto or "").strip() + " " + (texto_imagen or "").strip()).strip()
    intenciones = _detectar_intenciones_especiales(texto_total)
    referencia_visual = _extraer_referencia_visual(texto_total) if (imagen_referencia or intenciones.get('visual')) else None

    params = []
    where = ["1=1"]
    if marca:
        where.append("UPPER(COALESCE(p.marca,''))=UPPER(%s)")
        params.append(marca)
    if hilo:
        where.append("UPPER(COALESCE(p.hilo,''))=UPPER(%s)")
        params.append(hilo)

    with DB() as db:
        rows = db.execute(f"""
            SELECT
                p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                COALESCE(p.stock,0) AS stock,
                COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
                COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), 0) AS precio_venta
            FROM productos p
            LEFT JOIN precios pr ON pr.marca = p.marca
            WHERE {' AND '.join(where)}
            ORDER BY p.marca, p.hilo, p.codigo
            LIMIT 10000
        """, params).fetchall()
        productos = [dict(r) for r in rows]

        if _es_intencion_historial(texto_total):
            nota_ref, items_previos = _resolver_items_ultima_nota(db, cliente_nombre, telefono)
            if items_previos:
                return _respuesta_pedidos_especial(
                    _armar_pedidos_desde_items(items_previos), marca, hilo, productos, 'historial',
                    [f"Se usó la nota reciente {nota_ref}."], referencia_visual
                )

        if intenciones.get('uno_de_cada'):
            elegidos = _productos_uno_de_cada_color(productos)
            pedidos = [{
                'producto_id': p.get('id'), 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
                'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
                'precio_venta': float(p.get('precio_venta') or 0), 'cantidad': 1,
                'es_inventariable': p.get('es_inventariable', True),
            } for p in elegidos]
            return _respuesta_pedidos_especial(pedidos, marca, hilo, productos, 'uno_de_cada', ['Se agregó 1 por cada color del contexto.'], referencia_visual)

        if intenciones.get('mas_vendido'):
            top_rows = _productos_top_vendidos(db, marca=marca, hilo=hilo, limit=max(1, int(intenciones['mas_vendido'])))
            pedidos = [{
                'producto_id': None, 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
                'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
                'precio_venta': float(p.get('precio_venta') or 0), 'cantidad': 1,
                'es_inventariable': p.get('es_inventariable', True),
            } for p in top_rows]
            return _respuesta_pedidos_especial(pedidos, marca, hilo, productos, 'mas_vendido', ['Sugerencia basada en histórico de ventas.'], referencia_visual)

    if intenciones.get('surtido_bonito'):
        elegidos = _productos_surtido_bonito(productos, limit=6)
        pedidos = [{
            'producto_id': p.get('id'), 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
            'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
            'precio_venta': float(p.get('precio_venta') or 0), 'cantidad': 1,
            'es_inventariable': p.get('es_inventariable', True),
        } for p in elegidos]
        return _respuesta_pedidos_especial(pedidos, marca, hilo, productos, 'surtido_bonito', ['Se armó un surtido bonito con tonos variados.'], referencia_visual)

    if intenciones.get('surtidos'):
        elegidos = _productos_surtido_bonito(productos, limit=max(1, int(intenciones['surtidos'])))
        pedidos = [{
            'producto_id': p.get('id'), 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
            'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
            'precio_venta': float(p.get('precio_venta') or 0), 'cantidad': 1,
            'es_inventariable': p.get('es_inventariable', True),
        } for p in elegidos]
        return _respuesta_pedidos_especial(pedidos, marca, hilo, productos, 'surtidos', [f"Se armó un surtido sugerido de {len(pedidos)} producto(s)."], referencia_visual)

    if intenciones.get('parecidos'):
        elegidos = _buscar_tonos_parecidos(productos, texto_total, limit=6)
        if elegidos:
            pedidos = [{
                'producto_id': p.get('id'), 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
                'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
                'precio_venta': float(p.get('precio_venta') or 0), 'cantidad': 1,
                'es_inventariable': p.get('es_inventariable', True),
            } for p in elegidos]
            return _respuesta_pedidos_especial(pedidos, marca, hilo, productos, 'parecidos', ['Se propusieron tonos parecidos según el color mencionado.'], referencia_visual)

    if intenciones.get('combinar'):
        elegidos = _productos_combinados(productos, texto_total, limit=6)
        if elegidos:
            pedidos = [{
                'producto_id': p.get('id'), 'codigo': p.get('codigo'), 'marca': p.get('marca') or '',
                'hilo': p.get('hilo') or '', 'color': p.get('color') or '', 'stock': int(p.get('stock') or 0),
                'precio_venta': float(p.get('precio_venta') or 0), 'cantidad': 1,
                'es_inventariable': p.get('es_inventariable', True),
            } for p in elegidos]
            return _respuesta_pedidos_especial(pedidos, marca, hilo, productos, 'combinar', ['Se propuso una combinación de tonos compatibles.'], referencia_visual)

    # Nuevo motor contextual: ya no requiere que el vendedor seleccione marca/hilo.
    # Primero interpreta el mensaje con base en el almacén real: hilos disponibles,
    # códigos reales, colores, descripciones y cambios de opinión.
    ctx_result = _wa_parsear_con_contexto_almacen(
        texto_total, productos, marca=marca, hilo=hilo, extraer_pedidos_func=extraer_pedidos
    )

    pedidos = ctx_result.get('pedidos_full') or []
    errores = ctx_result.get('errores') or []
    advertencias = ctx_result.get('advertencias') or []
    preguntas = ctx_result.get('preguntas') or []

    if referencia_visual:
        advertencias.append("Se detectó referencia visual; revisa posiciones, círculos, flechas o tachones antes de confirmar.")

    return jsonify(json_safe({
        "ok": True,
        "modo": "contextual_almacen",
        "modo_especial": None,
        "contexto": {
            "marca": marca,
            "hilo": hilo,
            "productos_contexto": len(productos),
            "contexto_inferido": ctx_result.get('contexto_inferido') or {},
            "hilos_detectados": ctx_result.get('hilos_detectados') or [],
        },
        "pedidos": pedidos,
        "errores": sorted(set(str(e) for e in errores if e)),
        "advertencias": sorted(set(str(a) for a in advertencias if a)),
        "preguntas": sorted(set(str(p) for p in preguntas if p)),
        "sugerencias": {},
        "sugerencias_almacen": ctx_result.get('sugerencias_almacen') or [],
        "respuesta_preferida": ctx_result.get('respuesta_preferida') or '',
        "ventas_info": ctx_result.get('ventas_info') or {},
        "referencia_visual": referencia_visual,
    }))


# =========================
# Motor WhatsApp IA / Simulador
# =========================
def _call_parser_whatsapp_local(payload):
    """Reutiliza el parser real de la app para que el simulador y WhatsApp usen el mismo cerebro."""
    with app.test_request_context('/api/parser-whatsapp', method='POST', json=payload):
        out = parser_whatsapp_mobile()
    status = 200
    response = out
    if isinstance(out, tuple):
        response = out[0]
        if len(out) > 1:
            status = out[1]
    try:
        data = response.get_json() if hasattr(response, 'get_json') else None
    except Exception:
        data = None
    return data or {"ok": False, "error": "No pude leer respuesta del parser"}, int(status or 200)


def _norm_sales_txt(v):
    return _norm_txt(v or '')


def _clasificar_intencion_wa(texto, parsed):
    t = _norm_sales_txt(texto)
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    advertencias = parsed.get('advertencias') or []

    if any(x in t for x in ['comprobante', 'pague', 'pagado', 'deposit', 'transfer', 'ticket', 'recibo']):
        intent = 'comprobante_pago'
    elif any(x in t for x in ['parecid', 'similar', 'tono para', 'tonos para', 'color para', 'muñeco', 'amigurumi', 'trabajo', 'referencia']):
        intent = 'sugerir_tonos'
    elif pedidos:
        intent = 'pedido'
    elif any(x in t for x in ['precio', 'cuanto', 'cuesta', 'costo', 'vale']):
        intent = 'pregunta_precio'
    elif any(x in t for x in ['envio', 'envias', 'paqueteria', 'llega', 'neza', 'cp ', 'codigo postal']):
        intent = 'pregunta_envio'
    elif any(x in t for x in ['stock', 'tienes', 'hay', 'disponible', 'manejas']):
        intent = 'pregunta_stock'
    else:
        intent = 'conversacion'

    if preguntas or errores:
        confianza = 'baja'
        accion = 'preguntar'
        puede_auto = False
    elif pedidos and any(int(p.get('stock') or 0) < int(p.get('cantidad') or 1) and p.get('es_inventariable', True) for p in pedidos):
        confianza = 'media'
        accion = 'revisar_stock'
        puede_auto = False
    elif pedidos:
        confianza = 'alta' if not advertencias else 'media'
        accion = 'crear_cotizacion'
        puede_auto = not advertencias
    elif intent in ['pregunta_precio', 'pregunta_envio', 'pregunta_stock']:
        confianza = 'media'
        accion = 'responder'
        puede_auto = False  # al inicio conviene aprobar todo hasta entrenarlo con mensajes reales
    elif intent == 'sugerir_tonos':
        confianza = 'media'
        accion = 'sugerir_sin_agregar'
        puede_auto = False
    else:
        confianza = 'baja'
        accion = 'revisar'
        puede_auto = False

    return {
        'intencion': intent,
        'confianza': confianza,
        'accion_recomendada': accion,
        'puede_auto_enviar': bool(puede_auto),
    }


def _codigos_provisionales_desde_preguntas(preguntas):
    """Detecta códigos que el parser agregó solo como provisional por una duda real.
    Ejemplo de pregunta: "Confirma el color 'blanco': coincide con varios códigos (55, 62). Se usó 55 provisionalmente."
    Esos productos NO se deben confirmar al cliente como definitivos todavía.
    """
    cods = set()
    for q in preguntas or []:
        qtxt = str(q or '')
        m = re.search(r"se\s+uso\s+(\d+)\s+provisionalmente", _norm_txt(qtxt), re.I)
        if m:
            cods.add(str(m.group(1)).lstrip('0') or '0')
    return cods


def _formatear_producto_wa(p):
    hilo = (p.get('hilo') or p.get('marca') or 'Producto').strip()
    codigo = str(p.get('codigo') or '').strip()
    color = (p.get('color') or '').strip()
    cantidad = int(p.get('cantidad') or 1)
    # Si el código ya identifica perfecto, lo mostramos junto al color solo si existe.
    base = f"{hilo} {codigo}".strip()
    if color:
        base += f" {color}"
    return f"- {base} x{cantidad}"


def _limpiar_pregunta_wa(q):
    q = str(q or '').strip()
    if not q:
        return ''
    # Evita frases internas del parser como "Se usó 55 provisionalmente" en el WhatsApp al cliente.
    q = re.sub(r"\.?\s*Se\s+us[óo]\s+\d+\s+provisionalmente\.?", "", q, flags=re.I)
    q = re.sub(r"^Confirma:\s*", "", q, flags=re.I).strip()
    q = re.sub(r"^Confirma\s+", "Confírmame ", q, flags=re.I).strip()
    return q




def _formatear_sugerencias_almacen_wa(parsed):
    sugerencias = parsed.get('sugerencias_almacen') or []
    if not sugerencias:
        return ''
    bloques = []
    for s in sugerencias[:3]:
        tipo = s.get('tipo')
        opciones = s.get('opciones') or []
        if tipo == 'tonos_por_descripcion':
            hilo = s.get('hilo') or 'ese hilo'
            lineas = []
            for op in opciones[:5]:
                lineas.append(f"- {op.get('hilo') or hilo} {op.get('codigo')} {op.get('color')} ({op.get('confianza','parecido')})")
            if lineas:
                bloques.append('Para el tono que describes en ' + hilo + ', lo más parecido que tengo es:\n' + '\n'.join(lineas))
        elif tipo == 'hilo_similar':
            lineas = []
            for op in opciones[:5]:
                txt = f"- {op.get('hilo')}"
                if op.get('ejemplo_codigo'):
                    txt += f". Ejemplo: {op.get('ejemplo_codigo')} {op.get('ejemplo_color','')}"
                lineas.append(txt.strip())
            if lineas:
                bloques.append('Ese producto exacto no lo veo con ese nombre en mi almacén, pero sí tengo opciones similares en textura:\n' + '\n'.join(lineas))
    return '\n\n'.join(bloques).strip()


def _fallback_respuesta_wa(texto, parsed, meta):
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    advertencias = parsed.get('advertencias') or []
    sug_txt = _formatear_sugerencias_almacen_wa(parsed)
    intent = meta.get('intencion')

    # Regla de oro: código existente/producto detectado = confirmado.
    # Solo se pregunta lo que venga en preguntas/errores; no se vuelve a pedir confirmación de códigos detectados.
    provisionales = _codigos_provisionales_desde_preguntas(preguntas)
    pedidos_confirmados = [p for p in pedidos if (str(p.get('codigo') or '').strip().lstrip('0') or '0') not in provisionales]

    if errores:
        txt = ''
        if pedidos_confirmados:
            lineas = [_formatear_producto_wa(p) for p in pedidos_confirmados[:18]]
            txt += 'Claro 😊 ya tengo claro esto:\n' + '\n'.join(lineas) + '\n\n'
        txt += 'Estos códigos no me aparecen en catálogo: ' + ', '.join(map(str, errores[:8])) + '. ¿Me los confirmas?'
        return txt

    if preguntas:
        q_limpias = [_limpiar_pregunta_wa(q) for q in preguntas if _limpiar_pregunta_wa(q)]
        txt = ''
        if pedidos_confirmados:
            lineas = [_formatear_producto_wa(p) for p in pedidos_confirmados[:18]]
            txt += 'Claro 😊 ya tengo claro:\n' + '\n'.join(lineas)
            if len(pedidos_confirmados) > 18:
                txt += f"\nY {len(pedidos_confirmados)-18} producto(s) más."
            txt += '\n\n'
        if sug_txt:
            txt += sug_txt + '\n\n'
        if q_limpias:
            q0 = q_limpias[0].replace('Sí contamos con', 'Sí cuento con')
            txt += 'Solo para confirmar 😊 ' + q0
        else:
            txt += 'Solo necesito confirmar un detalle para no agregarte un tono equivocado 😊'
        return txt

    if sug_txt and not pedidos:
        return sug_txt + '\n\n¿Quieres que te arme una opción con alguno de esos tonos?'

    if pedidos:
        lineas = []
        for p in pedidos[:18]:
            lineas.append(_formatear_producto_wa(p))
        txt = 'Claro 😊 te agrego:\n' + '\n'.join(lineas)
        if len(pedidos) > 18:
            txt += f"\nY {len(pedidos)-18} producto(s) más."
        txt += '\n\nTe preparo tu cotización.'
        # No mencionar advertencias técnicas si no son preguntas reales.
        return txt
    if intent == 'pregunta_precio':
        return 'Claro 😊 ¿me confirmas qué hilo o código quieres revisar? Así te doy el precio exacto y disponibilidad.'
    if intent == 'pregunta_envio':
        return 'Sí manejamos envíos 😊 Para cotizarlo necesito tu código postal o municipio.'
    if intent == 'pregunta_stock':
        return 'Con gusto 😊 dime el código, color o hilo que buscas y reviso disponibilidad.'
    if intent == 'sugerir_tonos':
        return 'Sí 😊 mándame la foto o referencia y te sugiero los tonos más parecidos según el catálogo disponible. No los agrego directo hasta que tú confirmes.'
    if intent == 'comprobante_pago':
        return 'Perfecto 😊 mándame la imagen del comprobante y reviso monto, referencia y datos para continuar con tu pedido.'
    return 'Claro 😊 dime qué hilo, código o color necesitas y te ayudo a armar tu cotización.'


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    # Para pedidos ya parseados usamos respuesta determinística.
    # Motivo: evita que la IA vuelva a preguntar por códigos que YA existen en el almacén
    # (ej. "un 429") o que pida confirmar un negro único como el 60.
    # OpenAI queda para conversaciones generales, precio/envío/stock y tono comercial.
    if (parsed.get('pedidos') or parsed.get('preguntas') or parsed.get('errores')):
        return _fallback_respuesta_wa(texto, parsed, meta), 'reglas_hilorama'

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return _fallback_respuesta_wa(texto, parsed, meta), 'fallback_sin_openai'
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '90')))
        productos = []
        for p in (parsed.get('pedidos') or [])[:30]:
            productos.append({
                'codigo': p.get('codigo'), 'marca': p.get('marca'), 'hilo': p.get('hilo'),
                'color': p.get('color'), 'cantidad': p.get('cantidad'), 'stock': p.get('stock'),
                'precio': p.get('precio_venta')
            })
        system = (
            'Eres el asistente de ventas de Hilorama, una mercería mexicana. '
            'Responde amable, breve y natural por WhatsApp. No inventes stock, precios, códigos ni productos. '
            'Usa solo los productos detectados y el contexto enviado. Si hay dudas, pregunta antes de vender. '
            'Si el pedido está claro, confirma los productos y di que prepararás la cotización. '
            'No marques pagos, no prometas envío y no cierres venta si faltan datos. '
            'Devuelve SOLO JSON válido con claves: respuesta, razon, requiere_humano.'
        )
        payload = {
            'mensaje_cliente': texto,
            'contexto': contexto,
            'clasificacion': meta,
            'productos_detectados': productos,
            'preguntas': parsed.get('preguntas') or [],
            'advertencias': parsed.get('advertencias') or [],
            'errores': parsed.get('errores') or [],
        }
        resp = client.chat.completions.create(
            model=os.environ.get('OPENAI_SALES_MODEL', os.environ.get('OPENAI_TEXT_MODEL', 'gpt-4o-mini')),
            temperature=0.2,
            max_tokens=650,
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}
            ]
        )
        raw = resp.choices[0].message.content or '{}'
        obj = json.loads(raw)
        respuesta = str(obj.get('respuesta') or '').strip()
        if not respuesta:
            respuesta = _fallback_respuesta_wa(texto, parsed, meta)
        return respuesta, 'openai'
    except Exception as exc:
        print('WARN WhatsApp IA OpenAI fallback:', exc, flush=True)
        return _fallback_respuesta_wa(texto, parsed, meta), 'fallback_error_openai'


@app.route('/api/whatsapp-ia/simular', methods=['POST'])
def whatsapp_ia_simular():
    """
    Simulador del agente real con memoria de conversación.

    La memoria permite que, si primero la clienta pregunta por Velluto y luego escribe
    "rojo 56" o "y el 429", el sistema siga usando el hilo anterior sin obligar al
    vendedor a repetir el contexto.
    """
    data = request.get_json(force=True) or {}
    texto = (data.get('texto') or '').strip()
    marca = (data.get('marca') or '').strip()
    hilo = (data.get('hilo') or '').strip()
    cliente_nombre = (data.get('cliente_nombre') or '').strip()
    telefono = (data.get('telefono') or '').strip()
    texto_imagen = (data.get('texto_imagen') or '').strip()
    imagen_referencia = bool(data.get('imagen_referencia'))
    conversacion_id = data.get('conversacion_id')
    nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

    texto_total = ' '.join(x for x in [texto, texto_imagen] if x).strip()
    if not texto_total:
        return jsonify({'ok': False, 'error': 'Escribe o pega un mensaje de clienta primero.'}), 400

    memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)
    productos_mem = _wa_memoria_productos_min()

    # Si la vendedora no seleccionó marca/hilo y el mensaje no trae hilo nuevo,
    # aplica el último hilo de la conversación. Si el mensaje sí trae hilo nuevo,
    # ese nuevo hilo gana y actualiza la memoria.
    marca_parser, hilo_parser, memoria_aplicada = _wa_memoria_resolver_contexto_para_parser(
        texto_total, marca, hilo, memoria_previa, productos_mem
    )

    parser_payload = {
        'texto': texto,
        'marca': marca_parser,
        'hilo': hilo_parser,
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'texto_imagen': texto_imagen,
        'imagen_referencia': imagen_referencia,
    }
    parsed, status = _call_parser_whatsapp_local(parser_payload)
    if status >= 400 or not parsed.get('ok', False):
        return jsonify(parsed), status

    meta = _clasificar_intencion_wa(texto_total, parsed)
    contexto = {
        'marca': marca_parser or marca or 'Todas',
        'hilo': hilo_parser or hilo or 'Todos',
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'fase': 'simulador_manual_pre_whatsapp_cloud_api',
        'memoria_conversacion': memoria_aplicada,
        'historial_reciente': _wa_memoria_historial_reciente(conversacion_id) if conversacion_id and not nueva_conversacion else [],
    }
    respuesta, motor = _generar_respuesta_wa_con_openai(texto_total, parsed, meta, contexto)

    try:
        with DB() as db:
            if conversacion_id and not nueva_conversacion:
                conv = db.execute("""
                    UPDATE whatsapp_conversaciones
                    SET cliente_nombre=%s, telefono=%s, ultima_actualizacion=%s, estado=%s
                    WHERE id=%s
                    RETURNING id
                """, (cliente_nombre, telefono, now_mexico(), 'SIMULADOR', conversacion_id)).fetchone()
                if not conv:
                    conversacion_id = None
            if not conversacion_id or nueva_conversacion:
                conv = db.execute("""
                    INSERT INTO whatsapp_conversaciones (telefono, cliente_nombre, origen, estado, fecha, ultima_actualizacion)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    RETURNING id
                """, (telefono, cliente_nombre, 'SIMULADOR', 'SIMULADOR', now_mexico(), now_mexico())).fetchone()
                conversacion_id = conv['id']
            db.execute("""
                INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (conversacion_id, 'IN', 'texto', texto_total, respuesta, json.dumps({'parsed': parsed, 'meta': meta, 'motor': motor, 'memoria_usada': memoria_aplicada}, ensure_ascii=False)))
    except Exception as exc:
        print('WARN no se pudo guardar simulacion WA:', exc, flush=True)

    memoria_actualizada = _wa_memoria_actualizar(
        conversacion_id=conversacion_id,
        telefono=telefono,
        cliente_nombre=cliente_nombre,
        texto=texto_total,
        respuesta=respuesta,
        parsed=parsed,
        meta=meta,
        marca_parser=marca_parser,
        hilo_parser=hilo_parser,
        memoria_previa=memoria_previa,
        productos=productos_mem,
    )

    return jsonify(json_safe({
        'ok': True,
        'conversacion_id': conversacion_id,
        'motor': motor + ':memoria_v14',
        'mensaje_cliente': texto_total,
        'respuesta_sugerida': respuesta,
        'intencion': meta.get('intencion'),
        'confianza': meta.get('confianza'),
        'accion_recomendada': meta.get('accion_recomendada'),
        'puede_auto_enviar': meta.get('puede_auto_enviar'),
        'pedidos': parsed.get('pedidos') or [],
        'preguntas': parsed.get('preguntas') or [],
        'errores': parsed.get('errores') or [],
        'advertencias': parsed.get('advertencias') or [],
        'parser': parsed,
        'memoria_usada': memoria_aplicada,
        'memoria_actual': memoria_actualizada,
    }))

@app.route('/api/whatsapp-ia/conversaciones')
def whatsapp_ia_conversaciones():
    limit = min(int(request.args.get('limit') or 30), 100)
    with DB() as db:
        rows = db.execute("""
            SELECT c.*, (
                SELECT texto FROM whatsapp_mensajes m WHERE m.conversacion_id=c.id ORDER BY m.fecha DESC LIMIT 1
            ) AS ultimo_mensaje
            FROM whatsapp_conversaciones c
            ORDER BY c.ultima_actualizacion DESC NULLS LAST, c.fecha DESC
            LIMIT %s
        """, (limit,)).fetchall()
    return jsonify(json_safe([dict(r) for r in rows]))


# =========================
# Cotizaciones / notas
# =========================
def generar_id_nota(db):
    row = db.execute("""
        SELECT id
        FROM notas
        WHERE id LIKE 'COT-%'
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()
    if not row:
        return "COT-00001"
    m = re.search(r"(\d+)$", str(row["id"]))
    numero = int(m.group(1)) if m else 0
    return f"COT-{numero + 1:05d}"


def obtener_pedido_default(db):
    try:
        if table_exists(db, "pedidos"):
            try:
                row = db.execute("""
                    SELECT numero
                    FROM pedidos
                    WHERE activo = TRUE
                    ORDER BY numero DESC
                    LIMIT 1
                """).fetchone()
                if row and row.get("numero") is not None:
                    return str(row["numero"])
            except Exception:
                db.rollback()
            try:
                row = db.execute("""
                    SELECT numero
                    FROM pedidos
                    ORDER BY numero DESC
                    LIMIT 1
                """).fetchone()
                if row and row.get("numero") is not None:
                    return str(row["numero"])
            except Exception:
                db.rollback()
        row = db.execute("""
            SELECT pedido FROM notas
            WHERE pedido IS NOT NULL AND pedido <> ''
            ORDER BY fecha DESC
            LIMIT 1
        """).fetchone()
        return str(row["pedido"]) if row and row.get("pedido") else None
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _item_key(raw):
    return "|".join([
        str(raw.get("codigo") or "").strip(),
        str(raw.get("marca") or "").strip().upper(),
        str(raw.get("hilo") or "").strip().upper(),
        str(raw.get("color") or "").strip().upper(),
    ])


def _calcular_items_y_total(db, items_req, envio=None, validar_stock=False):
    """
    Normaliza y consolida productos conservando producto_id cuando viene del móvil.
    Esto hace que el almacén descuente el producto exacto, aunque haya códigos repetidos.
    """
    agrupados = {}
    for raw in items_req:
        codigo = str(raw.get("codigo") or "").strip()
        marca = str(raw.get("marca") or "").strip()
        hilo = str(raw.get("hilo") or "").strip()
        color = str(raw.get("color") or "").strip()
        producto_id = raw.get("producto_id") or raw.get("id")
        try:
            producto_id = int(producto_id) if producto_id not in (None, "") else None
        except Exception:
            producto_id = None
        try:
            cantidad = int(float(raw.get("cantidad") or 0))
        except Exception:
            cantidad = 0
        if not (codigo or producto_id) or cantidad <= 0:
            continue
        key = f"ID:{producto_id}" if producto_id else _item_key({"codigo": codigo, "marca": marca, "hilo": hilo, "color": color})
        if key not in agrupados:
            agrupados[key] = {
                "producto_id": producto_id,
                "codigo": codigo,
                "marca": marca,
                "hilo": hilo,
                "color": color,
                "cantidad": 0,
                "precio": raw.get("precio"),
            }
        agrupados[key]["cantidad"] += cantidad
        if raw.get("precio") not in (None, ""):
            agrupados[key]["precio"] = raw.get("precio")

    items_finales = []
    errores = []
    total = 0.0

    for raw in agrupados.values():
        producto_id = raw.get("producto_id")
        codigo = str(raw.get("codigo") or "").strip()
        marca = str(raw.get("marca") or "").strip()
        hilo = str(raw.get("hilo") or "").strip()
        color = str(raw.get("color") or "").strip()
        cantidad = int(raw.get("cantidad") or 0)
        precio_manual = raw.get("precio")
        if not (codigo or producto_id) or cantidad <= 0:
            continue

        if producto_id:
            prod = db.execute("""
                SELECT
                    p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                    COALESCE(p.stock,0) AS stock,
                    COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
                    COALESCE(p.tipo_producto, 'INVENTARIO') AS tipo_producto,
                    COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), 0) AS precio_venta
                FROM productos p
                LEFT JOIN precios pr ON pr.marca = p.marca
                WHERE p.id=%s
                LIMIT 1
            """, (producto_id,)).fetchone()
        else:
            prod = db.execute("""
                SELECT
                    p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                    COALESCE(p.stock,0) AS stock,
                    COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
                    COALESCE(p.tipo_producto, 'INVENTARIO') AS tipo_producto,
                    COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), 0) AS precio_venta
                FROM productos p
                LEFT JOIN precios pr ON pr.marca = p.marca
                WHERE (p.codigo=%s OR p.codigo_barras=%s)
                  AND (%s='' OR UPPER(COALESCE(p.marca,''))=UPPER(%s))
                  AND (%s='' OR UPPER(COALESCE(p.hilo,''))=UPPER(%s))
                  AND (%s='' OR UPPER(COALESCE(p.color,''))=UPPER(%s))
                ORDER BY
                    CASE
                        WHEN %s<>'' AND UPPER(COALESCE(p.marca,''))=UPPER(%s)
                         AND %s<>'' AND UPPER(COALESCE(p.hilo,''))=UPPER(%s) THEN 0
                        WHEN %s<>'' AND UPPER(COALESCE(p.marca,''))=UPPER(%s) THEN 1
                        ELSE 2
                    END,
                    CASE WHEN %s<>'' AND UPPER(COALESCE(p.color,''))=UPPER(%s) THEN 0 ELSE 1 END,
                    p.id
                LIMIT 1
            """, (codigo, codigo, marca, marca, hilo, hilo, color, color,
                  marca, marca, hilo, hilo, marca, marca, color, color)).fetchone()

        if not prod:
            contexto = ""
            if marca or hilo:
                contexto = f" en contexto {marca or 'todas'} / {hilo or 'todos'}"
            errores.append(f"No existe el producto {codigo or producto_id}{contexto}")
            continue

        prod = dict(prod)
        es_inventariable = prod.get("es_inventariable")
        if isinstance(es_inventariable, str):
            es_inventariable = es_inventariable.lower() not in ("false", "f", "0", "no", "n")

        stock = int(prod.get("stock") or 0)
        if validar_stock and es_inventariable and stock < cantidad:
            errores.append(f"Stock insuficiente {prod['codigo']} {prod.get('marca','')}/{prod.get('hilo','')} ({stock} disponibles)")
            continue

        precio = float(precio_manual if precio_manual not in (None, "") else (prod.get("precio_venta") or 0))
        subtotal = cantidad * precio
        total += subtotal
        items_finales.append({
            "producto_id": prod.get("id"),
            "codigo": prod["codigo"],
            "marca": prod.get("marca") or "",
            "hilo": prod.get("hilo") or "",
            "color": prod.get("color") or "",
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": subtotal,
            "stock": stock,
            "es_inventariable": bool(es_inventariable),
        })

    if errores:
        raise ValueError(" / ".join(errores))
    if not items_finales:
        raise ValueError("No hay productos válidos")

    envio_precio = 0.0
    if isinstance(envio, dict):
        envio_precio = float(envio.get("precio") or 0)
    return items_finales, round(total + envio_precio, 2)


@app.route("/api/cotizaciones", methods=["POST"])
def crear_cotizacion_movil():
    data = request.get_json(force=True) or {}
    cliente_id = data.get("cliente_id")
    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    items_req = data.get("items") or []
    envio = data.get("envio") or None
    pedido = data.get("pedido") or None

    if not items_req:
        return jsonify({"ok": False, "error": "La cotización no tiene productos"}), 400

    with DB() as db:
        if not pedido:
            pedido = obtener_pedido_default(db)

        if cliente_id:
            cliente = db.execute("SELECT id, nombre, telefono, direccion FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
            if not cliente:
                return jsonify({"ok": False, "error": "Cliente no encontrado"}), 404
            cliente = dict(cliente)
        else:
            if not cliente_nombre:
                return jsonify({"ok": False, "error": "Falta cliente"}), 400
            direccion_vacia = {"calle":"","numero_ext":"","numero_int":"","colonia":"","codigo_postal":"","estado":"","municipio":"","referencia":""}
            cliente = db.execute("""
                INSERT INTO clientes (nombre, telefono, direccion)
                VALUES (%s,%s,%s)
                RETURNING id, nombre, telefono, direccion
            """, (cliente_nombre, telefono, json.dumps(direccion_vacia, ensure_ascii=False))).fetchone()
            cliente = dict(cliente)

        try:
            items_finales, total = _calcular_items_y_total(db, items_req, envio, validar_stock=True)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        paqueteria = None
        if isinstance(envio, dict):
            paqueteria = envio.get("tipo") or envio.get("paqueteria")

        nota_id = generar_id_nota(db)
        db.execute("""
            INSERT INTO notas
            (id, cliente_id, cliente_nombre, fecha, estado, total, envio, pedido, paqueteria)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            nota_id, cliente["id"], cliente["nombre"], now_mexico(), "COTIZACION", total,
            json.dumps(envio, ensure_ascii=False) if envio else None,
            pedido, paqueteria,
        ))

        for p in items_finales:
            db.execute("""
                INSERT INTO items (nota_id, producto_id, codigo, marca, hilo, color, cantidad, precio)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (nota_id, p.get("producto_id"), p["codigo"], p["marca"], p["hilo"], p["color"], p["cantidad"], p["precio"]))

    return jsonify(json_safe({"ok": True, "nota_id": nota_id, "total": total, "items": items_finales, "cliente": {"id": cliente["id"], "nombre": cliente["nombre"]}}))


@app.route("/api/notas/<nota_id>", methods=["PUT"])
def editar_cotizacion(nota_id):
    data = request.get_json(force=True) or {}
    items_req = data.get("items") or []
    envio = data.get("envio") if "envio" in data else None
    pedido = data.get("pedido") if "pedido" in data else None

    if not items_req:
        return jsonify({"ok": False, "error": "La cotización no tiene productos"}), 400

    with DB() as db:
        nota = db.execute("SELECT id, estado FROM notas WHERE id=%s", (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
        if nota.get("estado") != "COTIZACION":
            return jsonify({"ok": False, "error": "Solo se pueden editar cotizaciones"}), 400

        try:
            items_finales, total = _calcular_items_y_total(db, items_req, envio, validar_stock=True)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        paqueteria = None
        if isinstance(envio, dict):
            paqueteria = envio.get("tipo") or envio.get("paqueteria")

        sets = ["total=%s"]
        params = [total]
        if "envio" in data:
            sets.append("envio=%s")
            params.append(json.dumps(envio, ensure_ascii=False) if envio else None)
            sets.append("paqueteria=%s")
            params.append(paqueteria)
        if "pedido" in data:
            sets.append("pedido=%s")
            params.append(pedido)
        params.append(nota_id)
        db.execute(f"UPDATE notas SET {', '.join(sets)} WHERE id=%s", params)

        db.execute("DELETE FROM items WHERE nota_id=%s", (nota_id,))
        for p in items_finales:
            db.execute("""
                INSERT INTO items (nota_id, producto_id, codigo, marca, hilo, color, cantidad, precio)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (nota_id, p.get("producto_id"), p["codigo"], p["marca"], p["hilo"], p["color"], p["cantidad"], p["precio"]))

    return jsonify(json_safe({"ok": True, "nota_id": nota_id, "total": total}))


@app.route("/api/notas/<nota_id>/envio", methods=["POST"])
def actualizar_envio_nota(nota_id):
    data = request.get_json(force=True) or {}
    envio = data.get("envio") or {}
    pedido = data.get("pedido")
    paqueteria = envio.get("tipo") or envio.get("paqueteria") if isinstance(envio, dict) else None
    precio_envio = float(envio.get("precio") or 0) if isinstance(envio, dict) else 0

    with DB() as db:
        nota = db.execute("SELECT id, estado FROM notas WHERE id=%s", (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
        subtotal = db.execute("SELECT COALESCE(SUM(cantidad*precio),0) AS subtotal FROM items WHERE nota_id=%s", (nota_id,)).fetchone()["subtotal"]
        total = round(float(subtotal or 0) + precio_envio, 2)
        db.execute("""
            UPDATE notas
            SET envio=%s, paqueteria=%s, total=%s, pedido=COALESCE(%s, pedido)
            WHERE id=%s
        """, (json.dumps(envio, ensure_ascii=False), paqueteria, total, pedido, nota_id))
    return jsonify({"ok": True, "nota_id": nota_id, "total": total})



@app.route("/api/notas/<nota_id>/convertir", methods=["POST"])
def convertir_a_venta(nota_id):
    with DB() as db:
        nota = db.execute("""
            SELECT n.id, n.estado, n.cliente_id, c.nombre, c.telefono, c.direccion
            FROM notas n
            LEFT JOIN clientes c ON c.id=n.cliente_id
            WHERE n.id=%s
        """, (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
        if nota.get("estado") != "COTIZACION":
            return jsonify({"ok": False, "error": "Solo se puede convertir una COTIZACION"}), 400
        incompleto = respuesta_cliente_incompleto(nota, accion="convertir")
        if incompleto:
            return incompleto
        try:
            descontados = _descontar_stock_de_nota(db, nota_id)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        db.execute("UPDATE notas SET estado='VENTA_PENDIENTE' WHERE id=%s", (nota_id,))
    return jsonify({"ok": True, "nota_id": nota_id, "estado": "VENTA_PENDIENTE", "descontados": descontados})


@app.route("/api/notas/<nota_id>/pagar", methods=["POST"])
def marcar_pagada(nota_id):
    data = request.get_json(force=True) or {}
    comprobante_in = data.get("comprobante_base64") or data.get("comprobante") or None
    metodo_pago = (data.get("metodo_pago") or data.get("metodo") or "Transferencia").strip()
    referencia_pago = (data.get("referencia_pago") or data.get("referencia") or "").strip()
    monto_pagado = data.get("monto_pagado")
    try:
        monto_pagado = float(monto_pagado) if monto_pagado not in (None, "") else None
    except Exception:
        return jsonify({"ok": False, "error": "Monto pagado inválido"}), 400

    with DB() as db:
        nota = db.execute("""
            SELECT n.id, n.estado, n.total, n.comprobante,
                   n.cliente_id, c.nombre, c.telefono, c.direccion
            FROM notas n
            LEFT JOIN clientes c ON c.id=n.cliente_id
            WHERE n.id=%s
        """, (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
        nota = dict(nota)
        estado_anterior = nota.get("estado")
        if estado_anterior not in ("COTIZACION", "VENTA_PENDIENTE", "PAGADA"):
            return jsonify({"ok": False, "error": "Esta nota no se puede marcar como pagada"}), 400

        # Igual que en la PC: antes de continuar el proceso de venta/pago,
        # si el cliente está incompleto, se pide completar datos y luego se reintenta.
        if estado_anterior != "PAGADA":
            incompleto = respuesta_cliente_incompleto(nota, accion="pagar")
            if incompleto:
                return incompleto

        comprobante_final = None
        if comprobante_in:
            comprobante_final = _normalizar_comprobante_data_url(comprobante_in)
        elif nota.get("comprobante"):
            comprobante_final = nota.get("comprobante")

        metodo_norm = _strip_acc(metodo_pago)
        if not comprobante_final and metodo_norm not in ("efectivo", "cash"):
            return jsonify({
                "ok": False,
                "code": "FALTA_COMPROBANTE",
                "error": "Sube o arrastra la imagen del comprobante antes de confirmar el pago",
            }), 400

        descontados = []
        # Si se paga directo una cotización, también descuenta almacén.
        # Si ya era VENTA_PENDIENTE, el stock ya se descontó al convertir y no se repite.
        # Si ya era PAGADA, solo actualizamos/cambiamos el comprobante, sin tocar stock.
        if estado_anterior == "COTIZACION":
            try:
                descontados = _descontar_stock_de_nota(db, nota_id)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        if monto_pagado is None:
            monto_pagado = float(nota.get("total") or 0)

        db.execute("""
            UPDATE notas
            SET estado='PAGADA',
                fecha_pago=COALESCE(fecha_pago, %s),
                comprobante=COALESCE(%s, comprobante),
                metodo_pago=%s,
                monto_pagado=%s,
                referencia_pago=%s
            WHERE id=%s
        """, (now_mexico().isoformat(sep=" ", timespec="seconds"), comprobante_final,
              metodo_pago or None, monto_pagado, referencia_pago or None, nota_id))

        if comprobante_final:
            db.execute("""
                INSERT INTO pagos (nota_id, comprobante, metodo_pago, monto_pagado, referencia_pago, fecha)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (nota_id, comprobante_final, metodo_pago or None, monto_pagado, referencia_pago or None, now_mexico()))

    return jsonify({
        "ok": True,
        "nota_id": nota_id,
        "estado": "PAGADA",
        "metodo_pago": metodo_pago,
        "monto_pagado": monto_pagado,
        "comprobante": bool(comprobante_final),
        "descontados": descontados,
    })


@app.route("/api/notas/<nota_id>/comprobante", methods=["POST"])
def guardar_comprobante_nota(nota_id):
    data = request.get_json(force=True) or {}
    comprobante_in = data.get("comprobante_base64") or data.get("comprobante")
    if not comprobante_in:
        return jsonify({"ok": False, "error": "Falta imagen de comprobante"}), 400
    comprobante_final = _normalizar_comprobante_data_url(comprobante_in)
    with DB() as db:
        row = db.execute("""
            UPDATE notas
            SET comprobante=%s
            WHERE id=%s
            RETURNING id, comprobante
        """, (comprobante_final, nota_id)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
    return jsonify({"ok": True, "nota_id": nota_id, "comprobante": comprobante_final})


# =========================
# Empacador móvil
# =========================
@app.route("/api/empacador/notas")
def empacador_notas():
    q = (request.args.get("q") or "").strip().lower()
    only_pending = (request.args.get("pendientes") or "1") == "1"
    params = []
    where = ["n.estado IN ('VENTA_PENDIENTE','PAGADA','EN_PROCESO','COTIZACION')"]
    if q:
        where.append("(LOWER(n.id) LIKE %s OR LOWER(COALESCE(n.cliente_nombre,'')) LIKE %s OR LOWER(COALESCE(n.pedido,'')) LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])

    with DB() as db:
        rows = db.execute(f"""
            SELECT n.id, n.cliente_nombre, n.pedido, n.estado, n.fecha, n.empacador, n.empacador_id,
                   COALESCE(SUM(i.cantidad),0) AS piezas_total,
                   COALESCE(SUM(i.empacadas),0) AS piezas_empacadas
            FROM notas n
            LEFT JOIN items i ON i.nota_id=n.id
            WHERE {' AND '.join(where)}
            GROUP BY n.id
            ORDER BY n.id DESC
            LIMIT 150
        """, params).fetchall()
    data = []
    for r in rows:
        d = dict(r)
        if only_pending and int(d.get("piezas_total") or 0) and int(d.get("piezas_empacadas") or 0) >= int(d.get("piezas_total") or 0):
            continue
        data.append(d)
    return jsonify(json_safe(data))


@app.route("/api/empacador/notas/<nota_id>/item", methods=["POST"])
def actualizar_empacado_item(nota_id):
    data = request.get_json(force=True) or {}
    item_id = data.get("item_id")
    codigo = data.get("codigo")
    try:
        empacadas = int(data.get("empacadas") or 0)
    except Exception:
        return jsonify({"ok": False, "error": "Cantidad inválida"}), 400
    empacadas = max(0, empacadas)

    with DB() as db:
        if item_id:
            row = db.execute("""
                UPDATE items
                SET empacadas=LEAST(%s, COALESCE(cantidad,0))
                WHERE id=%s AND nota_id=%s
                RETURNING id, codigo, cantidad, empacadas
            """, (empacadas, item_id, nota_id)).fetchone()
        else:
            row = db.execute("""
                UPDATE items
                SET empacadas=LEAST(%s, COALESCE(cantidad,0))
                WHERE codigo=%s AND nota_id=%s
                RETURNING id, codigo, cantidad, empacadas
            """, (empacadas, codigo, nota_id)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Item no encontrado"}), 404
        totals = db.execute("""
            SELECT COALESCE(SUM(cantidad),0) AS total, COALESCE(SUM(empacadas),0) AS empacadas
            FROM items WHERE nota_id=%s
        """, (nota_id,)).fetchone()
        if int(totals.get("total") or 0) and int(totals.get("empacadas") or 0) >= int(totals.get("total") or 0):
            db.execute("UPDATE notas SET fecha_finalizacion=COALESCE(fecha_finalizacion,%s) WHERE id=%s", (now_mexico(), nota_id))
    return jsonify(json_safe({"ok": True, "item": dict(row)}))


# =========================
# Visión / OCR / Audio / PDF
# =========================
def _strip_acc(v):
    v = (v or '').strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', v) if unicodedata.category(c) != 'Mn')


def _extract_data_url_bytes(data_url):
    if not data_url:
        return None
    if ',' in data_url:
        data_url = data_url.split(',', 1)[1]
    return base64.b64decode(data_url)


def _optimizar_data_url_imagen(data_url, max_side=1400, quality=86):
    """
    Reduce fotos grandes antes de mandarlas a la IA.
    Sin esto, Render/Gunicorn puede cortar el request y regresar HTML 500.
    """
    if not data_url:
        return data_url
    try:
        raw = _extract_data_url_bytes(data_url)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=quality, optimize=True)
        return _image_bytes_to_data_url(bio.getvalue(), "image/jpeg")
    except Exception:
        return data_url


def _normalizar_comprobante_data_url(data_url, max_side=1400, quality=82):
    """Optimiza y devuelve comprobante como data URL persistente para Render."""
    if not data_url:
        return None
    data_url = str(data_url).strip()
    if not data_url.startswith("data:image"):
        # Compatibilidad con rutas viejas del programa de PC.
        return data_url
    try:
        raw = _extract_data_url_bytes(data_url)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=quality, optimize=True)
        return _image_bytes_to_data_url(bio.getvalue(), "image/jpeg")
    except Exception as exc:
        raise ValueError(f"No pude procesar el comprobante: {exc}")


def _image_reference_summary(texto):
    t = _strip_acc(texto)
    out = {'numbers': [], 'positions': [], 'marks': [], 'raw_text': texto or ''}
    out['numbers'] = [int(x) for x in re.findall(r'\b(\d{1,3})\b', t)]
    mapping = [
        ('arriba_derecha', r'arriba\s+(?:a\s+la\s+)?derecha'),
        ('arriba_izquierda', r'arriba\s+(?:a\s+la\s+)?izquierda'),
        ('abajo_derecha', r'abajo\s+(?:a\s+la\s+)?derecha'),
        ('abajo_izquierda', r'abajo\s+(?:a\s+la\s+)?izquierda'),
        ('arriba', r'\barriba\b'),
        ('abajo', r'\babajo\b'),
        ('derecha', r'\bderecha\b'),
        ('izquierda', r'\bizquierda\b'),
        ('medio', r'en medio|del medio|de en medio|centro'),
        ('primero', r'primero|primera'),
        ('segundo', r'segundo|segunda'),
        ('tercero', r'tercero|tercera'),
        ('ultimo', r'ultimo|ultima'),
    ]
    for name, pat in mapping:
        if re.search(pat, t):
            out['positions'].append(name)
    if 'circulo' in t or 'encerrado' in t or 'rodeado' in t or 'marcado' in t:
        out['marks'].append('circulo')
    if 'flecha' in t or 'senalado' in t or 'señalado' in t or 'apunta' in t:
        out['marks'].append('flecha')
    if 'tachado' in t or 'tachon' in t or 'tacha' in t or 'tachame' in t:
        out['marks'].append('tachado')
    out['numbers'] = list(dict.fromkeys(out['numbers']))
    out['positions'] = list(dict.fromkeys(out['positions']))
    out['marks'] = list(dict.fromkeys(out['marks']))
    return out


def _safe_json_from_text(txt):
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        pass
    m = re.search(r'\{.*\}', txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None



def _codigos_contexto_productos(db, marca='', hilo=''):
    params = []
    where = ["1=1"]
    if marca:
        where.append("UPPER(COALESCE(p.marca,''))=UPPER(%s)")
        params.append(marca)
    if hilo:
        where.append("UPPER(COALESCE(p.hilo,''))=UPPER(%s)")
        params.append(hilo)
    rows = db.execute(f"""
        SELECT p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
               COALESCE(p.stock,0) AS stock,
               COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
               COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), 0) AS precio_venta
        FROM productos p
        LEFT JOIN precios pr ON pr.marca = p.marca
        WHERE {' AND '.join(where)}
        ORDER BY
            p.marca,
            p.hilo,
            CASE WHEN p.codigo ~ '^[0-9]+$' THEN p.codigo::int ELSE 999999 END,
            p.codigo
        LIMIT 10000
    """, params).fetchall()
    return [dict(r) for r in rows]


def _productos_a_pedidos_por_codigos(productos, add_codes, exclude_codes=None, quantities=None):
    exclude_codes = set(str(c).strip().lstrip('0') for c in (exclude_codes or []))
    quantities = quantities or {}
    por_codigo = {}
    for p in productos:
        c = str(p.get('codigo') or '').strip().lstrip('0') or '0'
        por_codigo.setdefault(c, []).append(p)
        cb = str(p.get('codigo_barras') or '').strip().lstrip('0') or '0'
        if cb != '0':
            por_codigo.setdefault(cb, []).append(p)
    pedidos = []
    no_encontrados = []
    for c in add_codes:
        c = str(c).strip().lstrip('0') or '0'
        if c in exclude_codes:
            continue
        opciones = por_codigo.get(c) or []
        if not opciones:
            no_encontrados.append(c)
            continue
        prod = opciones[0]
        pedidos.append({
            'producto_id': prod.get('id'),
            'codigo': prod.get('codigo'),
            'marca': prod.get('marca') or '',
            'hilo': prod.get('hilo') or '',
            'color': prod.get('color') or '',
            'stock': int(prod.get('stock') or 0),
            'precio_venta': float(prod.get('precio_venta') or 0),
            'cantidad': int(quantities.get(c, 1) or 1),
            'es_inventariable': prod.get('es_inventariable', True),
        })
    return pedidos, no_encontrados


def _red_components_from_image_bytes(raw):
    """
    Fallback visual sin OpenAI/OCR: detecta manchas rojas de círculos/tachones.
    No lee texto de la imagen; mapea las marcas a la cuadrícula del contexto.
    """
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    pix = img.load()
    mask = set()
    # muestreo completo; las imágenes de catálogo no suelen ser enormes tras WhatsApp
    for y in range(h):
        for x in range(w):
            r, g, b = pix[x, y]
            # rojo fuerte de marcador/whatsapp
            if r > 150 and g < 105 and b < 105 and r > g * 1.45 and r > b * 1.45:
                mask.add((x, y))
    if not mask:
        return [], (w, h)

    # componentes conectados, con salto 2 para unir trazos cercanos
    seen = set()
    comps = []
    neigh = [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)]
    for p in list(mask):
        if p in seen:
            continue
        stack = [p]
        seen.add(p)
        xs = []
        ys = []
        count = 0
        while stack:
            qx, qy = stack.pop()
            xs.append(qx); ys.append(qy); count += 1
            for dx, dy in neigh:
                nq = (qx + dx, qy + dy)
                if nq in mask and nq not in seen:
                    seen.add(nq)
                    stack.append(nq)
        if count < max(30, (w*h)//20000):
            continue
        x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = x2-x1+1, y2-y1+1
        # ignorar subrayados muy pequeños o puntos aislados
        if bw < w*0.035 and bh < h*0.035:
            continue
        comps.append({"bbox": [x1, y1, x2, y2], "area": count, "center": [(x1+x2)/2, (y1+y2)/2]})
    return comps, (w, h)


def _classify_red_mark_component(comp):
    x1,y1,x2,y2 = comp["bbox"]
    bw, bh = x2-x1+1, y2-y1+1
    ratio = bw / max(bh, 1)
    # Los tachones suelen ser más compactos o diagonales sobre la madeja.
    # Los círculos alrededor del código/nombre suelen ser más altos/ovalados.
    if 0.65 <= ratio <= 1.55 and comp["area"] > (bw*bh*0.10):
        return "tachado"
    return "circulo"


def _infer_visual_codes_grid(raw, productos_contexto, comentario=''):
    """
    Intenta deducir códigos por posición de marcas rojas usando el orden del contexto.
    Mejora la clasificación entre círculo (sí agregar) y tachado (no agregar).
    Requiere que el usuario haya seleccionado marca/hilo correctos.
    """
    comps, (w, h) = _red_components_from_image_bytes(raw)
    if not comps or not productos_contexto:
        return [], [], {"components": len(comps), "grid": None}

    n = len(productos_contexto)
    if n >= 15:
        cols = 5
    elif n >= 9:
        cols = 4
    else:
        cols = 3
    rows = max(1, math.ceil(n / cols))

    # Zona útil aproximada del catálogo.
    left, right = w * 0.13, w * 0.87
    top, bottom = h * 0.16, h * 0.86
    cell_w = (right - left) / max(cols, 1)
    cell_h = (bottom - top) / max(rows, 1)
    x_centers = [left + cell_w * (i + 0.5) for i in range(cols)]
    y_centers = [top + cell_h * (j + 0.5) for j in range(rows)]

    cell_marks = {}
    assigned = []

    for comp in comps:
        cx, cy = comp["center"]
        if cy < h * 0.08 or cy > h * 0.94:
            continue

        col = min(range(cols), key=lambda i: abs(x_centers[i] - cx))
        row = min(range(rows), key=lambda j: abs(y_centers[j] - cy))
        idx = row * cols + col
        if idx < 0 or idx >= n:
            continue

        codigo = str(productos_contexto[idx].get("codigo") or "").strip().lstrip("0")
        if not codigo:
            continue

        # Posición relativa dentro de la celda asignada
        cell_top = top + row * cell_h
        rel_y = (cy - cell_top) / max(cell_h, 1)

        x1, y1, x2, y2 = comp["bbox"]
        bw, bh = x2 - x1 + 1, y2 - y1 + 1

        # Heurística:
        # - Círculos de selección suelen estar alrededor de código/nombre o parte baja del tono.
        # - Tachones/X suelen ser compactos, con mucha área roja dentro del bbox, o dos trazos cruzados.
        is_lower = rel_y >= 0.50
        is_tall = bh >= cell_h * 0.38
        is_wide = bw >= cell_w * 0.30
        shape_kind = _classify_red_mark_component(comp)
        is_strong_oval = (
            bh >= cell_h * 1.05 or
            (is_lower and bh >= cell_h * 0.85 and bw >= cell_w * 0.55) or
            (rel_y >= 0.70 and bh >= cell_h * 0.65 and bw >= cell_w * 0.75)
        )
        is_small_quantity_mark = is_lower and bh <= cell_h * 0.45 and bw <= cell_w * 0.45

        if is_strong_oval or is_small_quantity_mark:
            kind = "circulo"
        elif is_lower and shape_kind != "tachado":
            kind = "circulo"
        elif (not is_lower) and is_tall and is_wide:
            kind = "tachado"
        else:
            kind = shape_kind

        item = {
            "codigo": codigo,
            "row": row + 1,
            "col": col + 1,
            "kind": kind,
            "bbox": comp["bbox"],
            "rel_y": round(rel_y, 3),
            "size": [bw, bh],
        }
        assigned.append(item)
        cell_marks.setdefault((row, col, codigo), []).append(item)

    add = []
    ex = []
    # Resolver por celda:
    # si en una celda hay al menos una marca baja/círculo -> agregar.
    # si solo hay marcas altas/tachado -> excluir.
    for (row, col, codigo), marks in cell_marks.items():
        has_circle = any(m["kind"] == "circulo" for m in marks)
        has_tachado = any(m["kind"] == "tachado" for m in marks)
        if has_circle:
            if codigo not in add:
                add.append(codigo)
        elif has_tachado:
            if codigo not in ex:
                ex.append(codigo)

    # Si por alguna razón un código salió en ambos, priorizar agregar si hay círculo.
    ex = [c for c in ex if c not in add]

    return add, ex, {
        "components": len(comps),
        "grid": {
            "cols": cols,
            "rows": rows,
            "assigned": assigned,
            "cell_w": round(cell_w, 1),
            "cell_h": round(cell_h, 1),
        }
    }


def _safe_json_from_text(texto):
    """
    Limpia respuestas de IA que vengan con ```json ...```
    y devuelve dict seguro.
    """
    if not texto:
        return {}
    s = str(texto).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s.strip(), flags=re.I).strip()
        s = re.sub(r"```$", "", s.strip()).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
    return {}


def _norm_code_list(values):
    out = []
    if values is None:
        return out
    if isinstance(values, (str, int, float)):
        values = [values]
    if isinstance(values, dict):
        values = list(values.values())
    for v in values:
        try:
            c = str(int(float(str(v).strip())))
        except Exception:
            c = re.sub(r"\D+", "", str(v or ""))
            c = str(int(c)) if c else ""
        if c and c not in out:
            out.append(c)
    return out


def _productos_contexto_para_vision(productos_contexto, max_items=120):
    """
    Lista compacta para que la IA visual valide códigos contra catálogo.
    """
    items = []
    for p in productos_contexto[:max_items]:
        items.append({
            "codigo": str(p.get("codigo") or "").strip(),
            "color": str(p.get("color") or "").strip(),
            "marca": str(p.get("marca") or "").strip(),
            "hilo": str(p.get("hilo") or "").strip(),
        })
    return items



def _analizar_catalogo_grid_openai(data_url, comentario, contexto, productos_contexto):
    """
    Análisis más estricto para catálogos tipo hoja con cuadrícula.
    En vez de pedir solo "qué códigos agregar", le pedimos a la IA que
    enumere TODOS los productos visibles por fila y columna y clasifique
    cada uno como:
      - selected
      - excluded
      - none
    Esto reduce las alucinaciones y los saltos de código.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "sin_openai_api_key"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))

    catalogo = _productos_contexto_para_vision(productos_contexto, max_items=300)

    schema_text = """
Devuelve SOLO JSON válido, sin markdown, con esta forma:
{
  "items": [
    {"row": 1, "col": 1, "code": "39", "label": "MANGO", "mark": "selected", "reason": "circled"},
    {"row": 1, "col": 2, "code": "54", "label": "CAMELLO", "mark": "none", "reason": "no red mark"},
    {"row": 1, "col": 5, "code": "73", "label": "SANDIA", "mark": "excluded", "reason": "crossed out"}
  ],
  "quantities": {"39": 1},
  "summary": "breve"
}
"""

    prompt = f"""
Eres un analizador visual de catálogos de mercería. Debes analizar una sola imagen tipo catálogo.

OBJETIVO:
Recorrer la imagen como una cuadrícula visual, de izquierda a derecha y de arriba a abajo, y clasificar CADA producto visible.

MUY IMPORTANTE:
- El catálogo muestra madejas con un código numérico impreso debajo.
- Cada celda visible contiene: madeja, código y color.
- Quiero que identifiques TODOS los productos visibles y marques cada uno con:
  - "selected" = sí comprar / sí agregar
  - "excluded" = no comprar / tachado / X roja
  - "none" = visible pero no marcado
- Un círculo rojo, encierro rojo, subrayado rojo fuerte o contorno rojo alrededor del producto/código = "selected".
- Una X roja o tachón claro sobre el producto = "excluded".
- Si hay un comentario como "los que tengan circulo 1 de cada uno los tachados no", entonces:
  - los circulados van como selected
  - los tachados van como excluded
  - los demás van como none
- NO adivines códigos vecinos.
- NO conviertas una marca de un producto en selección del de al lado.
- NO inventes productos que no estén visibles.
- Si dudas entre selected y none, solo usa selected si el producto está claramente rodeado o marcado.
- Si dudas entre excluded y none, solo usa excluded si tiene una X/tachón muy evidente.
- Devuelve los ítems visibles en orden de lectura: fila por fila, izquierda a derecha.

CONTEXTO DEL CATÁLOGO ACTUAL:
{contexto}

LISTA DE PRODUCTOS VÁLIDOS DEL CONTEXTO (para validar código y nombre):
{json.dumps(catalogo, ensure_ascii=False)}

COMENTARIO DEL USUARIO:
{comentario}

FORMATO OBLIGATORIO:
{schema_text}
""".strip()

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Responde solo JSON válido, sin markdown."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}}
            ]}
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content or "{}"
    parsed = _safe_json_from_text(content)
    return parsed, "openai_grid_catalog"


def _convert_grid_items_to_codes(parsed, productos_contexto):
    """
    Convierte items detallados de grid a add_codes/exclude_codes/quantities.
    """
    items = parsed.get("items") or []
    if not isinstance(items, list):
        items = []

    valid_codes = set()
    for p in productos_contexto:
        c = str(p.get("codigo") or "").strip().lstrip("0")
        if c:
            valid_codes.add(c)
        cb = str(p.get("codigo_barras") or "").strip().lstrip("0")
        if cb:
            valid_codes.add(cb)

    add_codes = []
    exclude_codes = []
    quantities = {}
    raw_quantities = parsed.get("quantities") or {}
    if isinstance(raw_quantities, dict):
        for k, v in raw_quantities.items():
            norm = _norm_code_list([k])
            if not norm:
                continue
            code = norm[0]
            try:
                quantities[code] = max(1, int(v))
            except Exception:
                quantities[code] = 1

    # Captura una cantidad global tipo "1 de cada uno", "2 de cada uno"
    qty_global = 1
    txt = _strip_acc(str(parsed.get("summary") or ""))
    # Nada aquí; la cantidad real global viene del comentario en otra función
    # y se aplica después.

    # Resolver por código; si aparece repetido, priorizamos:
    # excluded > selected > none  (luego selected si comentario indica "circulos sí, tachados no")
    priority = {"excluded": 3, "selected": 2, "none": 1}
    best = {}
    for item in items:
        code = _norm_code_list([item.get("code")])
        if not code:
            continue
        code = code[0]
        if valid_codes and code not in valid_codes:
            continue
        mark = str(item.get("mark") or "").strip().lower()
        if mark in ("circle", "circled", "selected", "add", "yes"):
            mark = "selected"
        elif mark in ("excluded", "crossed", "cross", "x", "tachado", "exclude", "no"):
            mark = "excluded"
        else:
            mark = "none"
        prev = best.get(code)
        if not prev or priority.get(mark, 0) > priority.get(prev["mark"], 0):
            best[code] = {
                "mark": mark,
                "row": item.get("row") or 999,
                "col": item.get("col") or 999,
                "label": item.get("label") or "",
            }

    # Mantener orden visual row/col
    ordered = sorted(best.items(), key=lambda kv: (kv[1]["row"], kv[1]["col"], int(kv[0]) if str(kv[0]).isdigit() else 9999))
    for code, meta in ordered:
        if meta["mark"] == "selected":
            add_codes.append(code)
        elif meta["mark"] == "excluded":
            exclude_codes.append(code)

    return add_codes, exclude_codes, quantities, {"items_count": len(items), "resolved_count": len(ordered), "ordered": ordered}


def _extract_global_each_quantity(texto):
    """
    Detecta frases como:
    - 1 de cada uno
    - uno de cada uno
    - 2 de cada uno
    - dos de cada uno
    """
    t = _strip_acc(texto or "")
    if not t:
        return None
    word_map = {
        "un": 1, "uno": 1, "una": 1,
        "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    }
    m = re.search(r"\b(\d+)\s+de\s+cada\s+uno\b", t)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            pass
    m2 = re.search(r"\b(un|uno|una|dos|tres|cuatro|cinco)\s+de\s+cada\s+uno\b", t)
    if m2:
        return word_map.get(m2.group(1), None)
    return None


def _comentario_tachados_no(comentario):
    """True cuando la clienta usa tachado/X como NO comprar."""
    t = _strip_acc(comentario or '')
    if not t:
        return False
    patrones = [
        r"\btachad[oa]s?\s+no\b", r"\bno\s+(los\s+)?tachad[oa]s?\b",
        r"\bcruzad[oa]s?\s+no\b", r"\blos\s+de\s+x\s+no\b",
        r"\bno\s+(quiero|agregues|pongas|metas).*?(tachad|cruzad|x)\b",
        r"\bmenos\s+(el|los|la|las)?\s*(tachad|cruzad|x)\b",
        r"\bexcepto\s+(el|los|la|las)?\s*(tachad|cruzad|x)\b",
    ]
    return any(re.search(p, t) for p in patrones)


def _comentario_taches_son_marca(comentario):
    """True cuando taches/rayas/X significan 'estos sí'."""
    t = _strip_acc(comentario or '')
    if not t:
        return False
    if _comentario_tachados_no(t):
        return False
    patrones = [
        r"\blos\s+(tachad|cruzad|rayad|marcad|senalad)[oa]s?\b",
        r"\blos\s+de\s+(x|tache|raya|punto|puntito)\b",
        r"\blos\s+que\s+tienen\s+(x|tache|raya|punto|puntito)\b",
        r"\blos\s+marcados?\b", r"\blos\s+senalados?\b",
        r"\bmis\s+(taches|rayas|puntos)\b",
    ]
    return any(re.search(p, t) for p in patrones)


def _comentario_todos_menos(comentario):
    """True cuando el comentario implica todos los visibles excepto los excluidos."""
    t = _strip_acc(comentario or '')
    if not t:
        return False
    patrones = [
        r"\btodos?\s+(menos|excepto|exepto)\b",
        r"\bmenos\s+este\b", r"\bmenos\s+estos\b", r"\bsin\s+este\b", r"\bsin\s+estos\b",
        r"\blos\s+demas\s+(si|sí|tambien|igual)\b",
        r"\btach(e|ado).*\b(no|menos)\b.*\bdemas\b",
        r"\bsolo\s+no\s+(quiero|agregues|pongas|metas)\b",
    ]
    return any(re.search(p, t) for p in patrones)


def _visual_text_qty_hint(*parts):
    """Detecta cantidades escritas en reason/mark_type: puntos, rayas, x2, 2pz, etc."""
    t = _strip_acc(' '.join(str(x or '') for x in parts))
    if not t:
        return None
    word_map = {
        'un': 1, 'uno': 1, 'una': 1,
        'dos': 2, 'par': 2, 'pares': 2,
        'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6,
        'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10,
    }
    m = re.search(r"\b(?:x|por)\s*(\d{1,2})\b", t)
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"\b(\d{1,2})\s*(?:pz|pza|pzas|pieza|piezas|madeja|madejas|unid|unidades)\b", t)
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"\b(\d{1,2})\s+(?:ray|raya|rayita|palito|punto|puntito|marca)", t)
    if m:
        return max(1, int(m.group(1)))
    for word, qty in sorted(word_map.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{word}\s+(?:ray|raya|rayita|palito|punto|puntito|marca|pieza|pza|madeja)", t):
            return qty
    # marcas tipo II / III / //// dentro del texto o mark_type
    if re.search(r"\b(4|cuatro|four|iiii|////)\b", t):
        return 4
    if re.search(r"\b(3|tres|three|iii|///)\b", t):
        return 3
    if re.search(r"\b(2|dos|two|ii|//)\b", t):
        return 2
    if re.search(r"\b(1|uno|una|one|i|/)\b", t):
        return 1
    return None


def _fallback_strong_circle_codes(fb_debug):
    """
    Códigos con círculo/óvalo muy claro según respaldo visual.
    Se usa solo para rescatar casos donde la IA confundió un óvalo grande con tachón.
    """
    out = []
    try:
        grid = (fb_debug or {}).get('grid') or {}
        cell_h = float(grid.get('cell_h') or 1)
        cell_w = float(grid.get('cell_w') or 1)
        for m in grid.get('assigned') or []:
            code = str(m.get('codigo') or '').strip().lstrip('0')
            if not code:
                continue
            kind = str(m.get('kind') or '').lower()
            rel_y = float(m.get('rel_y') or 0)
            size = m.get('size') or [0, 0]
            bw, bh = float(size[0] or 0), float(size[1] or 0)
            # Óvalo fuerte: marca grande, baja o rodeando la zona código/nombre. Evita rescatar X compactas.
            strong_oval = (
                kind == 'circulo' and
                (
                    bh >= cell_h * 1.05 or
                    (rel_y >= 0.52 and bh >= cell_h * 0.85 and bw >= cell_w * 0.55) or
                    (rel_y >= 0.70 and bh >= cell_h * 0.65 and bw >= cell_w * 0.75)
                )
            )
            if strong_oval and code not in out:
                out.append(code)
    except Exception:
        pass
    return out


def _analizar_imagen_con_openai_lens(data_url, comentario, contexto, productos_contexto):
    """
    Analizador principal estilo Lens:
    1) Lee la imagen completa.
    2) Lee números/texto.
    3) Ubica marcas rojas: círculos, flechas, subrayados, tachones/X.
    4) Devuelve JSON estructurado.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "sin_openai_api_key"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))

    catalogo = _productos_contexto_para_vision(productos_contexto)
    schema_text = """
Devuelve SOLO JSON válido, sin markdown:
{
  "add_codes": ["39","68"],
  "exclude_codes": ["73"],
  "quantities": {"39": 1},
  "all_visible_codes": ["39","54"],
  "explanation": "breve"
}
"""

    prompt = f"""
Eres un analizador visual de pedidos de mercería, parecido a Google Lens pero especializado en catálogos de hilos.

TAREA:
Analiza la imagen. Debes detectar qué productos marcó la clienta.

REGLAS IMPORTANTES:
- Los números impresos debajo de cada madeja son CÓDIGOS de producto.
- Círculo rojo, encierro, subrayado fuerte o flecha roja = AGREGAR.
- X roja, tachón rojo o producto cruzado = EXCLUIR.
- Si el comentario dice "los círculos sí y los tachados no", agrega solo los circulados y excluye los tachados.
- No inventes códigos. Usa únicamente códigos visibles en la imagen o en la lista de contexto.
- Si ves una marca roja rodeando el texto del código/nombre, cuenta como seleccionado.
- Si hay marca roja arriba pero no cruza el producto, revisa si es parte del círculo; no lo excluyas automáticamente.
- Si un producto está claramente con X roja grande sobre la madeja, va en exclude_codes.
- Devuelve códigos como texto sin ceros extra.

CONTEXTO ELEGIDO EN LA APP:
{contexto}

PRODUCTOS DEL CONTEXTO, para validar:
{json.dumps(catalogo, ensure_ascii=False)}

REGLAS DE CONTEXTO DEL COMENTARIO:
- Da prioridad al comentario cuando explica qué significan las marcas.
- "1 de cada uno", "uno de cada", "una de cada" = cantidad global 1 para cada selected.
- "2 de cada uno", "dos de cada" = cantidad global 2 para cada selected.
- "todos", "todos los colores", "todos estos" puede significar todos los visibles, pero solo úsalo si el comentario lo dice claramente.
- "todos menos/excepto", "menos este", "sin el", "los demás sí" = seleccionar visibles salvo los excluded.
- "no hay", "sin stock", "agotado" sobre un producto no significa pedido; puede indicar excluded/none según contexto.
- Si el usuario escribe códigos en el comentario, no los confundas con cantidades: un número cerca de palabras pz/pieza/cantidad es cantidad; un número que coincide con código visible puede ser producto.

COMENTARIO DE LA CLIENTA:
{comentario}

FORMATO:
{schema_text}
"""

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")

    # Chat Completions es más compatible con versiones viejas del SDK que Responses.
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Responde siempre JSON válido. No uses markdown."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ]},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content or "{}"
    parsed = _safe_json_from_text(content)
    return parsed, "openai_lens"


def _validar_resultado_lens(parsed, productos_contexto):
    codigos_validos = set()
    for p in productos_contexto:
        c = str(p.get("codigo") or "").strip().lstrip("0")
        if c:
            codigos_validos.add(c)
        cb = str(p.get("codigo_barras") or "").strip().lstrip("0")
        if cb:
            codigos_validos.add(cb)

    add = _norm_code_list(parsed.get("add_codes") or parsed.get("selected_codes") or parsed.get("add"))
    ex = _norm_code_list(parsed.get("exclude_codes") or parsed.get("excluded_codes") or parsed.get("exclude"))
    quantities_raw = parsed.get("quantities") or {}
    quantities = {}
    if isinstance(quantities_raw, dict):
        for k, v in quantities_raw.items():
            ck = _norm_code_list([k])
            if not ck:
                continue
            try:
                quantities[ck[0]] = int(v)
            except Exception:
                quantities[ck[0]] = 1

    # Si el modelo encontró códigos visibles que no están en contexto, los dejamos,
    # porque luego el endpoint puede reintentar contra todo el almacén.
    add = [c for c in add if c not in ex]
    return add, ex, quantities


def _extract_codes_from_free_text(texto):
    """
    Extrae códigos explícitos de frases tipo:
    39, 68, 78 / agregar 39 68 78 / de ese 39
    No debe tomar el "1" de 'los círculos 1' como código.
    """
    t = _strip_acc(texto or "")
    if not t:
        return []
    if re.search(r"circulos?\s+1\b|circulos?\s+y\b|tachados?\s+no", t):
        # evitar que la frase "los círculos y los tachados no" se vuelva código 1
        nums = [n for n in re.findall(r"\b\d{2,4}\b", t)]
    else:
        nums = re.findall(r"\b\d{1,4}\b", t)
    # en Hilorama los códigos reales visuales normalmente son 2-4 dígitos;
    # ignorar 1 cuando viene de "uno" o instrucción visual.
    return list(dict.fromkeys(str(int(n)) for n in nums if int(n) > 1))


def _analizar_catalogo_por_fases_openai(data_url, original_data_url, comentario, contexto, productos_contexto):
    """
    Analizador visual por fases, como propuso Jorge:
    Fase 1: segmentar catálogo en celdas/productos visibles.
    Fase 2: leer código primero, luego color escrito, luego color visual.
    Fase 3: si hay original, comparar original vs editada para detectar modificaciones.
    Fase 4: asociar cualquier marca/modificación a la celda correcta.
    Fase 5: decidir selected/excluded/none.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "sin_openai_api_key"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))

    catalogo = _productos_contexto_para_vision(productos_contexto, max_items=350)

    schema = """
Devuelve SOLO JSON válido, sin markdown:
{
  "phases": {
    "segmentation": "qué hiciste para separar celdas",
    "codes": "cómo asociaste código con madeja",
    "marks": "cómo detectaste modificaciones",
    "decision": "cómo decidiste selected/excluded/none"
  },
  "items": [
    {
      "row": 1,
      "col": 1,
      "code": "39",
      "label_text": "MANGO",
      "visual_color": "amarillo",
      "bbox": [0.10, 0.12, 0.25, 0.29],
      "mark": "selected",
      "mark_type": "circle",
      "confidence": 0.94,
      "reason": "círculo rojo rodea el código y la parte baja de la madeja"
    }
  ],
  "add_codes": ["39"],
  "exclude_codes": ["73"],
  "quantities": {"39": 1},
  "warnings": []
}
"""

    extra_original = ""
    if original_data_url:
        extra_original = """
HAY DOS IMÁGENES:
- Imagen 1: imagen EDITADA por la clienta.
- Imagen 2: imagen ORIGINAL sin editar.
Compara ambas y detecta qué trazos/marcas se agregaron en la imagen editada.
"""

    prompt = f"""
Eres un analizador visual especializado en catálogos de hilos/estambres. 
NO eres un buscador genérico. Tu trabajo es mapear correctamente marcas de una clienta a códigos de producto.

ANÁLISIS POR FASES OBLIGATORIO:

FASE 1 - SEGMENTACIÓN:
- Divide la imagen en productos/celdas.
- Cada producto normalmente tiene una madeja arriba y debajo un CÓDIGO numérico y un nombre/color.
- El código impreso debajo pertenece a la madeja inmediatamente arriba en la misma columna/celda.
- Si hay otra madeja arriba o abajo, no confundas: el código debajo de una madeja pertenece a esa madeja, no a la de otra fila.
- Recorre de izquierda a derecha y de arriba a abajo.
- Identifica todos los códigos visibles antes de decidir seleccionados.

FASE 2 - LECTURA:
- Prioridad de identificación:
  1) código numérico impreso
  2) texto/nombre del color debajo del código
  3) color visual de la madeja solo para corroborar
- No inventes códigos que no estén visibles.
- No agregues código 1 por la frase "1 de cada uno"; eso es cantidad, no código.

FASE 3 - MODIFICACIONES:
{extra_original}
- Si solo hay una imagen, detecta marcas agregadas por la clienta: círculos, flechas, subrayados, tachones, X, rayones.
- Las marcas pueden ser rojas u otro color llamativo.
- Una marca que rodea código/nombre o madeja = selección.
- Una X/tachón cruzando la madeja o celda = excluir.
- Un círculo alrededor del código aunque no cubra toda la madeja = selección.

FASE 4 - ASOCIACIÓN:
- Asocia cada marca a la celda/producto con mayor solapamiento o cercanía.
- La marca no debe brincar al vecino si está más cerca del código/madeja de otro producto.
- Si una marca toca dos celdas, elige la que contiene el código dentro/abajo de la marca.
- Si un producto tiene círculo y otro tiene tachón, no mezcles.

FASE 5 - DECISIÓN:
- mark = "selected" si la clienta lo quiere.
- mark = "excluded" si está tachado/X o el comentario dice que tachados no.
- mark = "none" si no hay marca clara.
- Devuelve add_codes solo con selected.
- Devuelve exclude_codes solo con excluded.
- Si el comentario dice "los que tengan círculo 1 de cada uno los tachados no":
  - todos los selected llevan cantidad 1
  - todos los excluded NO se agregan.

CONTEXTO APP:
{contexto}

PRODUCTOS VÁLIDOS DEL CONTEXTO:
{json.dumps(catalogo, ensure_ascii=False)}

COMENTARIO CLIENTA:
{comentario}

FORMATO:
{schema}
""".strip()

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
    ]
    if original_data_url:
        content.append({"type": "image_url", "image_url": {"url": original_data_url, "detail": "high"}})

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Responde únicamente JSON válido. No uses markdown. No inventes códigos."},
            {"role": "user", "content": content},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    parsed = _safe_json_from_text(resp.choices[0].message.content or "{}")
    return parsed, "openai_phased_catalog"


def _resolver_estado_items_por_fases(parsed, productos_contexto, comentario):
    """
    Convierte items de la IA por fases a add/exclude con filtros duros:
    - Solo acepta códigos que aparecieron como item visible.
    - No acepta código 1 si solo viene de cantidad.
    - Prioriza mark por item, no add_codes sueltos.
    """
    items = parsed.get("items") or []
    if not isinstance(items, list):
        items = []

    valid = set()
    for p in productos_contexto:
        c = str(p.get("codigo") or "").strip().lstrip("0")
        if c:
            valid.add(c)
        cb = str(p.get("codigo_barras") or "").strip().lstrip("0")
        if cb:
            valid.add(cb)

    # Cantidad global "1 de cada uno".
    global_qty = _extract_global_each_quantity(comentario) or 1

    resolved = {}
    for it in items:
        code_list = _norm_code_list([it.get("code")])
        if not code_list:
            continue
        code = code_list[0]
        if valid and code not in valid:
            continue
        # Nunca aceptar código 1 desde imagen si no se ve como producto real.
        if code == "1" and "1" not in valid:
            continue

        mark = str(it.get("mark") or "").strip().lower()
        if mark in ("selected", "circle", "circled", "add", "yes", "seleccionado", "agregar"):
            state = "selected"
        elif mark in ("excluded", "exclude", "x", "cross", "crossed", "tachado", "no"):
            state = "excluded"
        else:
            state = "none"

        try:
            conf = float(it.get("confidence") or 0)
        except Exception:
            conf = 0

        # Si ya existe, priorizar excluded sobre selected solo si tiene alta confianza;
        # pero selected con círculo claro puede sobrepasar none.
        prev = resolved.get(code)
        rank = {"excluded": 3, "selected": 2, "none": 1}
        if not prev or (rank.get(state, 0), conf) > (rank.get(prev["state"], 0), prev["confidence"]):
            resolved[code] = {
                "state": state,
                "confidence": conf,
                "item": it,
            }

    add = []
    ex = []
    quantities = {}
    visual_items = []
    for code, data in sorted(
        resolved.items(),
        key=lambda kv: (
            int(kv[1]["item"].get("row") or 999),
            int(kv[1]["item"].get("col") or 999),
            int(kv[0]) if str(kv[0]).isdigit() else 999999
        )
    ):
        st = data["state"]
        it = data["item"]
        visual_items.append({
            "code": code,
            "row": it.get("row"),
            "col": it.get("col"),
            "label_text": it.get("label_text") or it.get("label") or "",
            "visual_color": it.get("visual_color") or "",
            "mark": st,
            "mark_type": it.get("mark_type") or "",
            "confidence": data["confidence"],
            "reason": it.get("reason") or "",
        })
        if st == "selected":
            add.append(code)
            quantities[code] = global_qty
        elif st == "excluded":
            ex.append(code)

    # Si el JSON trae quantities, respetarlas solo para códigos seleccionados.
    qraw = parsed.get("quantities") or {}
    if isinstance(qraw, dict):
        for k, v in qraw.items():
            kk = _norm_code_list([k])
            if not kk:
                continue
            kk = kk[0]
            if kk in add:
                try:
                    quantities[kk] = max(1, int(v))
                except Exception:
                    pass

    add = [c for c in add if c not in set(ex)]
    return add, ex, quantities, visual_items



def _image_bytes_to_data_url(raw, mime="image/png"):
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def _crear_imagen_grid_anotada(raw, cols=5, rows=4):
    """
    Crea una versión de la imagen con una cuadrícula visible y nombres de celda.
    Esto obliga al modelo visual a analizar por secciones, no como imagen libre.
    """
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size

    # Si la imagen viene muy grande, mantener proporción pero limitar para costo/tamaño.
    max_side = 1600
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w*scale), int(h*scale)))
        w, h = img.size

    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(18, w//45))
        font_small = ImageFont.truetype("DejaVuSans-Bold.ttf", max(12, w//70))
    except Exception:
        font = None
        font_small = None

    cw = w / cols
    rh = h / rows

    # Líneas de celda
    for c in range(cols+1):
        x = int(c*cw)
        draw.line([(x, 0), (x, h)], fill=(0, 90, 255), width=max(3, w//350))
    for r in range(rows+1):
        y = int(r*rh)
        draw.line([(0, y), (w, y)], fill=(0, 90, 255), width=max(3, h//500))

    # Etiquetas R1C1, etc.
    for r in range(rows):
        for c in range(cols):
            label = f"R{r+1}C{c+1}"
            x = int(c*cw + 8)
            y = int(r*rh + 8)
            # fondo blanco semitransparente simulado
            draw.rectangle([x-3, y-3, x+70, y+28], fill=(255,255,255), outline=(0,90,255), width=2)
            draw.text((x, y), label, fill=(0, 0, 0), font=font_small)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), {"cols": cols, "rows": rows, "width": w, "height": h}


def _infer_rows_cols_para_catalogo(raw, productos_contexto=None):
    """
    Regla inicial: los catálogos que el usuario manda suelen ser 5 columnas.
    Las filas se estiman por proporción de imagen y/o cantidad visible.
    Para páginas de tonos como la de Komfy Mini: 5x4.
    """
    img = Image.open(io.BytesIO(raw))
    w, h = img.size
    cols = 5
    # La página enviada tiene 4 filas; usar 4 por defecto en catálogos altos.
    if h / max(w, 1) > 1.15:
        rows = 4
    else:
        rows = 3
    # Si el contexto es chico, ajustar sin bajar de 3 para no romper catálogos
    if productos_contexto:
        n = len(productos_contexto)
        if n <= 10:
            rows = 2
        elif n <= 15:
            rows = 3
        else:
            rows = 4
    return cols, rows


def _analizar_celdas_anotadas_openai(data_url_original, raw, comentario, contexto, productos_contexto):
    """
    Analizador por celdas:
    1) dibuja una cuadrícula R1C1...
    2) pide al modelo leer código/nombre/estado por celda
    3) devuelve JSON estructurado.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "sin_openai_api_key"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))

    cols, rows = _infer_rows_cols_para_catalogo(raw, productos_contexto)
    annotated_raw, grid_info = _crear_imagen_grid_anotada(raw, cols=cols, rows=rows)
    annotated_url = _image_bytes_to_data_url(annotated_raw)

    # Solo códigos válidos como ayuda, pero el modelo debe leer el código de la imagen.
    valid_codes = []
    for p in productos_contexto[:350]:
        c = str(p.get("codigo") or "").strip()
        if c:
            valid_codes.append({
                "codigo": c,
                "color": str(p.get("color") or "").strip(),
                "marca": str(p.get("marca") or "").strip(),
                "hilo": str(p.get("hilo") or "").strip(),
            })

    prompt = f"""
Analiza esta imagen de catálogo de hilos dividida en una cuadrícula azul con celdas R1C1, R1C2, etc.

NO adivines por orden del catálogo de la base de datos.
DEBES LEER EL CÓDIGO IMPRESO DENTRO DE CADA CELDA.

Para cada celda que tenga un producto:
1. Lee el código numérico impreso debajo de la madeja.
2. Lee el nombre/color escrito debajo del código.
3. Determina si la celda está:
   - selected: tiene círculo rojo, contorno rojo, subrayado rojo o marca roja indicando que sí lo quiere.
   - excluded: tiene X roja o tachón claro sobre la madeja/celda.
   - none: no tiene marca de selección.
4. La marca solo aplica a la celda donde está, no a la vecina.
5. Si el comentario dice "los que tengan círculo 1 de cada uno los tachados no":
   - selected = agregar cantidad 1
   - excluded = no agregar
   - none = ignorar
6. NO conviertas "1 de cada uno" en código 1.
7. NO agregues blanco/marfil/rosa/etc. si no lees su código impreso y no está marcado.
8. Si una celda tiene una línea roja pequeña pero el círculo grande rodea otra celda, no la marques selected.

CONTEXTO DE APP:
{contexto}

CÓDIGOS VÁLIDOS DEL CONTEXTO, SOLO PARA VALIDAR:
{json.dumps(valid_codes, ensure_ascii=False)}

COMENTARIO:
{comentario}

Devuelve SOLO JSON válido:
{{
  "grid": {{"cols": {cols}, "rows": {rows}}},
  "cells": [
    {{"cell":"R1C1","row":1,"col":1,"code":"39","label_text":"MANGO","mark":"selected","mark_type":"circle","confidence":0.95,"reason":"círculo rojo rodea el código 39"}},
    {{"cell":"R1C2","row":1,"col":2,"code":"54","label_text":"CAMELLO","mark":"none","mark_type":"","confidence":0.90,"reason":"sin marca"}},
    {{"cell":"R1C5","row":1,"col":5,"code":"73","label_text":"SANDIA","mark":"excluded","mark_type":"x","confidence":0.95,"reason":"X roja sobre el producto"}}
  ],
  "add_codes":["39"],
  "exclude_codes":["73"],
  "quantities":{{"39":1}},
  "warnings":[]
}}
""".strip()

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Responde únicamente JSON válido. No uses markdown. Lee códigos por celda."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": annotated_url, "detail": "high"}},
            ]},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    parsed = _safe_json_from_text(resp.choices[0].message.content or "{}")
    parsed["_grid_info_local"] = grid_info
    return parsed, "openai_cell_grid"


def _convertir_celdas_a_resultado(parsed, productos_contexto, comentario):
    cells = parsed.get("cells") or parsed.get("items") or []
    if not isinstance(cells, list):
        cells = []

    valid = set()
    for p in productos_contexto:
        c = str(p.get("codigo") or "").strip().lstrip("0")
        if c:
            valid.add(c)
        cb = str(p.get("codigo_barras") or "").strip().lstrip("0")
        if cb:
            valid.add(cb)

    global_qty = _extract_global_each_quantity(comentario) or 1
    add = []
    ex = []
    quantities = {}
    visual_items = []

    # Si el modelo entrega cells, confiar más en cells que en add_codes.
    for cell in cells:
        code_list = _norm_code_list([cell.get("code")])
        if not code_list:
            continue
        code = code_list[0]
        # Duro: no aceptar código 1 si es cantidad, y no aceptar código fuera de contexto.
        if code == "1" and "1" not in valid:
            continue
        if valid and code not in valid:
            # guardarlo en visual_items como inválido para debug, pero no agregar
            visual_items.append({
                "code": code,
                "row": cell.get("row"),
                "col": cell.get("col"),
                "label_text": cell.get("label_text") or cell.get("label") or "",
                "visual_color": cell.get("visual_color") or "",
                "mark": "invalid_context",
                "mark_type": cell.get("mark_type") or "",
                "confidence": cell.get("confidence") or 0,
                "reason": "Código leído pero no existe en el contexto seleccionado",
            })
            continue

        mark = str(cell.get("mark") or "").lower().strip()
        if mark in ("selected", "select", "circle", "circled", "add", "yes", "si", "sí"):
            state = "selected"
        elif mark in ("excluded", "exclude", "x", "cross", "crossed", "tachado", "no"):
            state = "excluded"
        else:
            state = "none"

        item = {
            "code": code,
            "row": cell.get("row"),
            "col": cell.get("col"),
            "label_text": cell.get("label_text") or cell.get("label") or "",
            "visual_color": cell.get("visual_color") or "",
            "mark": state,
            "mark_type": cell.get("mark_type") or "",
            "confidence": cell.get("confidence") or 0,
            "reason": cell.get("reason") or "",
        }
        visual_items.append(item)

        if state == "selected" and code not in add:
            add.append(code)
            quantities[code] = global_qty
        elif state == "excluded" and code not in ex:
            ex.append(code)

    add = [c for c in add if c not in set(ex)]

    # Si no hubo cells, usar add/exclude del JSON directo como respaldo.
    if not add and not ex:
        add = _norm_code_list(parsed.get("add_codes") or [])
        ex = _norm_code_list(parsed.get("exclude_codes") or [])
        add = [c for c in add if c not in set(ex) and (not valid or c in valid)]
        ex = [c for c in ex if (not valid or c in valid)]
        for c in add:
            quantities[c] = global_qty

    return add, ex, quantities, visual_items



def _parse_code_grid_text(texto):
    """
    Convierte un mapa escrito por filas a una matriz de códigos.
    Ejemplos:
    39 54 61 68 73
    78 93 94 99 104
    121 164 172 173 185
    193 209 215 218
    """
    if not texto:
        return []
    rows = []
    for line in str(texto).replace('|', '\n').splitlines():
        nums = re.findall(r'\b\d{1,5}\b', line)
        if nums:
            rows.append([str(int(n)) for n in nums if int(n) > 0])
    return rows


def _red_mask_components_simple(raw):
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert('RGB')
    w, h = img.size
    pix = img.load()
    red = set()
    for y in range(h):
        for x in range(w):
            r, g, b = pix[x, y]
            if r > 145 and g < 125 and b < 125 and r > g * 1.25 and r > b * 1.25:
                red.add((x, y))
    seen = set()
    comps = []
    neigh = [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)]
    min_area = max(25, (w*h)//35000)
    for p in list(red):
        if p in seen: continue
        stack=[p]; seen.add(p); xs=[]; ys=[]; count=0
        while stack:
            qx,qy=stack.pop(); xs.append(qx); ys.append(qy); count += 1
            for dx,dy in neigh:
                nq=(qx+dx,qy+dy)
                if nq in red and nq not in seen:
                    seen.add(nq); stack.append(nq)
        if count < min_area: continue
        x1,x2,y1,y2 = min(xs), max(xs), min(ys), max(ys)
        bw,bh = x2-x1+1, y2-y1+1
        if bw < w*0.02 and bh < h*0.02: continue
        comps.append({'bbox':[x1,y1,x2,y2], 'area':count, 'center':[(x1+x2)/2,(y1+y2)/2], 'size':[bw,bh]})
    return comps, (w,h)


def _infer_marcas_por_grid_codigos(raw, code_grid, comentario=''):
    """
    Modo seguro: usa una grilla de códigos visible y asocia marcas rojas por geometría.
    No usa orden de base de datos y no inventa códigos.
    """
    comps, (w,h) = _red_mask_components_simple(raw)
    if not code_grid:
        return [], [], {}, {'error':'sin_code_grid'}
    rows = len(code_grid)
    cols = max(len(r) for r in code_grid)
    # Estimación de área útil: para catálogos de madejas, deja márgenes.
    left, right = w*0.045, w*0.955
    top, bottom = h*0.055, h*0.955
    cell_w = (right-left)/max(cols,1)
    cell_h = (bottom-top)/max(rows,1)

    marks = {}
    debug_comps = []
    for comp in comps:
        x1,y1,x2,y2 = comp['bbox']
        cx,cy = comp['center']
        if cx < left or cx > right or cy < top or cy > bottom:
            continue
        col = int((cx-left)/cell_w)
        row = int((cy-top)/cell_h)
        col = max(0, min(cols-1, col))
        row = max(0, min(rows-1, row))
        if row >= len(code_grid) or col >= len(code_grid[row]):
            continue
        code = code_grid[row][col]
        cell_top = top + row*cell_h
        cell_left = left + col*cell_w
        rel_y = (cy-cell_top)/max(cell_h,1)
        rel_x = (cx-cell_left)/max(cell_w,1)
        bw,bh = comp['size']
        # Regla: marca muy alta y gruesa sobre madeja = tachado/X.
        # Marca baja, cerca del código/nombre o rodeando parte baja = seleccionado.
        is_upper = rel_y < 0.46
        is_big = bw > cell_w*0.33 and bh > cell_h*0.24
        is_x_like = is_upper and is_big
        kind = 'excluded' if is_x_like else 'selected'
        # Si el comentario dice círculos sí, tachados no, respetar esta clasificación.
        marks.setdefault(code, []).append({'kind':kind,'row':row+1,'col':col+1,'rel_y':round(rel_y,3),'rel_x':round(rel_x,3),'bbox':comp['bbox'],'area':comp['area']})
        debug_comps.append({'code':code,'kind':kind,'row':row+1,'col':col+1,'rel_y':round(rel_y,3),'bbox':comp['bbox']})

    add=[]; ex=[]; visual=[]
    qty = _extract_global_each_quantity(comentario) or 1
    for r_i, row_codes in enumerate(code_grid):
        for c_i, code in enumerate(row_codes):
            m = marks.get(code, [])
            if not m:
                visual.append({'code':code,'row':r_i+1,'col':c_i+1,'mark':'none','confidence':0.8,'reason':'sin marca roja detectada'})
                continue
            # Si hay cualquier selected en la celda, agregar; si solo excluded, excluir.
            # Esto evita que un pedacito de círculo arriba convierta el círculo en tachado.
            has_sel = any(x['kind']=='selected' for x in m)
            has_ex = any(x['kind']=='excluded' for x in m)
            if has_sel:
                add.append(code)
                visual.append({'code':code,'row':r_i+1,'col':c_i+1,'mark':'selected','confidence':0.92,'reason':'marca roja asociada a la celda/código'})
            elif has_ex:
                ex.append(code)
                visual.append({'code':code,'row':r_i+1,'col':c_i+1,'mark':'excluded','confidence':0.9,'reason':'tachón/X roja en la parte alta de la celda'})
    add = [c for c in add if c not in set(ex)]
    quantities = {c: qty for c in add}
    debug={'mode':'manual_code_grid_red_geometry','rows':rows,'cols':cols,'components':len(comps),'assigned':debug_comps,'cell_w':round(cell_w,1),'cell_h':round(cell_h,1)}
    return add, ex, quantities, {'visual_items':visual,'debug':debug}


def _crear_overlay_marcas_data_url(raw):
    """
    Crea una imagen auxiliar: fondo atenuado y trazos rojos/marcadores resaltados.
    No decide productos; solo ayuda al modelo a distinguir marcas de la clienta.
    """
    img = Image.open(io.BytesIO(raw)).convert('RGB')
    w, h = img.size
    max_side = 1600
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w*scale), int(h*scale)))
        w, h = img.size
    base = Image.new('RGB', (w, h), (238, 238, 238))
    dim = Image.blend(img, base, 0.62)
    out = dim.copy()
    pix_in = img.load()
    pix_out = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pix_in[x, y]
            redish = (r > 140 and r > g*1.25 and r > b*1.25 and (r-g) > 35 and (r-b) > 35)
            if redish:
                pix_out[x, y] = (255, 0, 0)
    bio = io.BytesIO()
    out.save(bio, format='PNG')
    return _image_bytes_to_data_url(bio.getvalue(), 'image/png')


def _analizar_seleccion_hilos_ia_pura(data_url, raw, original_data_url, comentario, contexto, productos_contexto, fast=False):
    """
    Modo principal: interpretación pura de IA visual.
    No usa mapa manual. No permite inventar códigos a partir del catálogo.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'sin_openai_api_key'
    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))

    # Modo preciso por defecto: mantiene más resolución y SIEMPRE manda imagen auxiliar de marcas.
    # El parámetro fast queda solo por compatibilidad, pero aquí no se usa para bajar precisión.
    max_side = int(os.environ.get("OPENAI_IMAGE_MAX_SIDE", "1400"))
    data_url = _optimizar_data_url_imagen(data_url, max_side=max_side, quality=int(os.environ.get("OPENAI_IMAGE_QUALITY", "90")))
    if original_data_url:
        original_data_url = _optimizar_data_url_imagen(original_data_url, max_side=max_side, quality=int(os.environ.get("OPENAI_IMAGE_QUALITY", "90")))

    max_items = int(os.environ.get("OPENAI_CATALOG_MAX_ITEMS", "350"))
    catalogo = _productos_contexto_para_vision(productos_contexto, max_items=max_items)
    overlay_url = None
    try:
        overlay_url = _crear_overlay_marcas_data_url(raw)
    except Exception:
        overlay_url = None

    schema = """
Devuelve SOLO JSON válido, sin markdown:
{
  "visible_products": [
    {
      "code": "39",
      "label_text": "MANGO",
      "row": 1,
      "col": 1,
      "visual_color": "amarillo",
      "cell_description": "madeja amarilla con código 39 debajo"
    }
  ],
  "selected_products": [
    {
      "code": "39",
      "quantity": 1,
      "mark_type": "circle|oval|line|two_lines|three_lines|dot|two_dots|three_dots|number|arrow|underline|check|slash|x_as_marker|scribble|other",
      "quantity_evidence": "por frase 1 de cada uno / número 2 escrito / dos rayitas / dos puntos / x2 / dos palitos",
      "reason": "círculo rojo rodea código/nombre de la celda 39"
    }
  ],
  "excluded_products": [
    {
      "code": "73",
      "mark_type": "x|clear_x|cross_out|tachado|exclude_scribble",
      "reason": "X roja cruza la madeja/celda"
    }
  ],
  "ambiguous_products": [
    {"code": "104", "reason": "marca toca dos celdas"}
  ],
  "global_quantity": 1,
  "warnings": []
}
"""

    if original_data_url:
        original_text = """
IMAGEN ORIGINAL DISPONIBLE:
- Imagen 1: foto editada por clienta.
- Imagen 2: imagen auxiliar con marcas resaltadas.
- Imagen 3: original sin editar.
Compara la editada contra la original para detectar solo trazos nuevos: rayas, puntos, círculos, tachones, números escritos, flechas.
"""
    else:
        original_text = """
NO HAY IMAGEN ORIGINAL:
- Imagen 1: foto editada por clienta.
- Imagen 2: imagen auxiliar con posibles marcas resaltadas.
Debes distinguir marcas hechas por la clienta de texto/etiquetas del catálogo.
"""

    prompt = f"""
Eres una IA visual para interpretar pedidos de una mercería. Debes funcionar como un humano que ve una foto marcada por una clienta.

OBJETIVO:
Detectar qué hilos/estambres quiere la clienta y qué cantidad quiere de cada uno, usando SOLO la imagen y el comentario.

REGLAS DURAS:
1. NO inventes productos.
2. NO agregues colores que no estén en la imagen. Si no ves BLANCO, no digas BLANCO.
3. NO conviertas el número "1" de "1 de cada uno" en código de producto. Eso es cantidad.
4. Antes de seleccionar, primero crea mentalmente una lista de visible_products con los códigos impresos que SÍ se ven en la imagen.
5. selected_products y excluded_products deben ser SUBCONJUNTO de visible_products.
6. La lista de productos del contexto SOLO sirve para validar código/nombre; NO sirve para inventar productos que no viste.
7. Si no puedes leer un código con claridad, ponlo en ambiguous_products y NO lo agregues al carrito.

ASOCIACION CODIGO-HILO:
- Cada madeja tiene su código y nombre/color debajo.
- El código debajo pertenece a la madeja de arriba en la misma celda/columna.
- Si una marca rodea el código/nombre, pertenece a esa madeja.
- Si una marca rodea la madeja, pertenece al código inmediatamente debajo.
- No saltes a productos vecinos.

MARCAS DE LA CLIENTA - INTERPRETACIÓN HUMANA:
- círculo, óvalo, encierro, contorno, rayón, raya, palito, subrayado, flecha, palomita, punto, puntito o marca cerca/debajo/sobre el hilo = normalmente la clienta lo quiere.
- Un círculo/óvalo grande alrededor del código, nombre o madeja = selected aunque el trazo toque o cruce un poco la madeja. NO lo confundas con tachado.
- Una X grande o tachón CLARO de dos trazos cruzados sobre la madeja/celda = excluded solo cuando el contexto indique que tachado significa NO, o cuando hay otros círculos/palomitas que claramente son los seleccionados.
- NO clasifiques como excluded solo porque una línea roja toca una celda: puede ser parte de un círculo, una raya de cantidad o una marca de selección.
- Si todos o casi todos los productos marcados tienen X/tachón y el comentario no dice "tachados no", "menos", "no", "excluir", interpreta esos taches como MARCA DE SELECCIÓN, no como exclusión.
- Si solo tachan uno o pocos y el comentario dice "los demás", "todos los demás", "todos menos", "excepto", "menos el tachado", entonces los tachados son excluded y los demás visibles son selected.
- Si el comentario dice "tachados no", "los tachados no", "no los tachados", "cruzados no" o "los de X no", cualquier X/tachón queda excluded aunque tenga otra marca.
- Si el comentario dice "los marcados", "los señalados", "los de tache", "los que tienen X", "los rayados" o "los puntitos", esas marcas son selected.
- Si hay una mezcla de círculos y X/tachones, los círculos/óvalos/palomitas/flechas son selected y las X/tachones claros son excluded.
- Si el comentario dice "los que NO están tachados", "los no tachados" o "los demás", los tachados son excluded y los demás visibles son selected.
- Si el comentario dice "solo los tachados", "los de tache", "los cruzados" o "los marcados con X", entonces las X/tachones son selected.
- Si el comentario dice "todos menos los marcados" o "los marcados no", entonces las marcas son excluded y los demás visibles son selected.
- Palomita/check/visto, flecha, llave, corchete, línea apuntando, subrayado debajo del nombre/código, número escrito encima o a un lado = selected salvo que el comentario diga lo contrario.
- Un rayón largo que atraviesa una fila completa puede ser solo una marca visual de selección grupal; no lo trates como excluded a menos que el comentario diga "no", "menos", "tachados no" o sea una X clara.
- El color de la tinta de la marca (rojo, azul, negro, verde) NO es color del hilo; solo indica selección/exclusión/cantidad.
- Si no hay círculos pero sí puntos/rayitas/marcas pequeñas junto a varios productos, eso normalmente significa selected con quantity según cantidad de marcas.
- Si una X está solamente sobre el precio/código o etiqueta pero el producto está encerrado por un óvalo grande, gana el óvalo: selected, salvo comentario explícito de exclusión.
- Si una celda tiene una marca ambigua pero el código/nombre queda claramente dentro de un encierro, clasifícala selected y explica la duda en reason.

CANTIDADES POR MARCAS:
- Una sola rayita, palito, raya o slash cerca del hilo = 1 pieza si no hay otra cantidad.
- Dos rayitas, dos palitos, //, II o dos marcas iguales = 2 piezas.
- Tres rayitas, III o tres marcas iguales = 3 piezas.
- Cuatro rayitas, IIII o cuatro marcas iguales = 4 piezas.
- Un punto/puntito = 1 pieza; dos puntos/puntitos = 2 piezas; tres puntos/puntitos = 3 piezas; cuatro puntos = 4 piezas.
- Un número escrito cerca del hilo, por ejemplo 2, 3, 4, 5, indica esa cantidad. Distingue números escritos a mano de los códigos impresos del catálogo.
- Textos como x2, x 2, 2x, 2pz, 2 pz, 2 piezas, dos pzas, par, pares, doble, triple indican cantidad.
- Dos circulitos/puntos sobre la misma celda = 2 piezas; tres circulitos/puntos = 3 piezas.
- Una marca tipo +, cruz pequeña o palomita sin otra cantidad = 1 pieza. Si hay dos marcas pequeñas separadas en la misma celda = 2 piezas.
- Si el comentario dice "doble" o "dos de los marcados", todos los selected llevan quantity 2 salvo que una celda tenga cantidad específica.
- Si el comentario dice "una bolsita", "una madeja", "una pieza", "una pza" cerca de un producto = quantity 1.
- Si hay varias marcas de cantidad en una misma celda, usa la evidencia más clara: número escrito > puntos/rayitas contadas > comentario global.
- Si el comentario dice "1 de cada uno", todos los seleccionados llevan quantity 1 salvo que una marca diga otra cantidad.
- Si solo hay círculo/óvalo y no hay cantidad, quantity=1.

REGLAS DE CONTEXTO DEL COMENTARIO:
- Da prioridad al comentario cuando explica qué significan las marcas.
- "1 de cada uno", "uno de cada", "una de cada" = cantidad global 1 para cada selected.
- "2 de cada uno", "dos de cada" = cantidad global 2 para cada selected.
- "todos", "todos los colores", "todos estos" puede significar todos los visibles, pero solo úsalo si el comentario lo dice claramente.
- "todos menos/excepto", "menos este", "sin el", "los demás sí" = seleccionar visibles salvo los excluded.
- "no hay", "sin stock", "agotado" sobre un producto no significa pedido; puede indicar excluded/none según contexto.
- Si el usuario escribe códigos en el comentario, no los confundas con cantidades: un número cerca de palabras pz/pieza/cantidad es cantidad; un número que coincide con código visible puede ser producto.

COMENTARIO DE LA CLIENTA:
{comentario}

CONTEXTO DE LA APP:
{contexto}

PRODUCTOS VÁLIDOS DEL CONTEXTO PARA VALIDAR, NO PARA INVENTAR:
{json.dumps(catalogo, ensure_ascii=False)}

{original_text}

DEVUELVE ESTRICTAMENTE EL JSON:
{schema}
""".strip()

    content = [
        {'type': 'text', 'text': prompt},
        {'type': 'image_url', 'image_url': {'url': data_url, 'detail': 'high'}},
    ]
    if overlay_url:
        content.append({'type': 'image_url', 'image_url': {'url': overlay_url, 'detail': 'high'}})
    if original_data_url:
        content.append({'type': 'image_url', 'image_url': {'url': original_data_url, 'detail': 'high'}})

    model = os.environ.get('OPENAI_VISION_MODEL', 'gpt-4o')
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': 'Responde solo JSON válido. Sé estricto: no inventes productos ni códigos.'},
            {'role': 'user', 'content': content},
        ],
        temperature=0,
        response_format={'type': 'json_object'},
    )
    parsed = _safe_json_from_text(resp.choices[0].message.content or '{}')
    return parsed, 'openai_pura_marcas_preciso'


def _resolver_ia_pura_marcas(parsed, productos_contexto, comentario):
    """
    Convierte JSON visual a carrito con compuertas anti-alucinación.
    """
    if not isinstance(parsed, dict):
        return [], [], {}, [], ['Respuesta IA vacía o inválida']

    valid = set()
    for p in productos_contexto:
        c = str(p.get('codigo') or '').strip().lstrip('0')
        if c:
            valid.add(c)
        cb = str(p.get('codigo_barras') or '').strip().lstrip('0')
        if cb:
            valid.add(cb)

    visible_products = parsed.get('visible_products') or parsed.get('items') or []
    selected_products = parsed.get('selected_products') or []
    excluded_products = parsed.get('excluded_products') or []
    ambiguous_products = parsed.get('ambiguous_products') or []

    visible_codes = []
    visual_map = {}
    for it in visible_products:
        codes = _norm_code_list([it.get('code') if isinstance(it, dict) else it])
        if not codes:
            continue
        code = codes[0]
        if code == '1' and '1' not in valid:
            continue
        if code not in visible_codes:
            visible_codes.append(code)
        if isinstance(it, dict):
            visual_map[code] = it

    global_qty = parsed.get('global_quantity') or _extract_global_each_quantity(comentario) or 1
    try:
        global_qty = max(1, int(global_qty))
    except Exception:
        global_qty = 1

    tachados_no = _comentario_tachados_no(comentario)
    taches_son_marca = _comentario_taches_son_marca(comentario)
    todos_menos = _comentario_todos_menos(comentario)

    # Ajustes de contexto:
    # - A veces la clienta usa X/taches como marca de selección.
    # - A veces tacha uno y quiere todos los demás.
    if excluded_products and (taches_son_marca or (not selected_products and not tachados_no and not todos_menos)):
        selected_products = list(selected_products) + list(excluded_products)
        excluded_products = []
    elif visible_codes and excluded_products and todos_menos:
        excluded_set_tmp = set()
        for it in excluded_products:
            cc = _norm_code_list([it.get('code') if isinstance(it, dict) else it])
            if cc:
                excluded_set_tmp.add(cc[0])
        already_selected = set()
        for it in selected_products:
            cc = _norm_code_list([it.get('code') if isinstance(it, dict) else it])
            if cc:
                already_selected.add(cc[0])
        for c in visible_codes:
            if c not in excluded_set_tmp and c not in already_selected:
                selected_products.append({
                    'code': c,
                    'quantity': global_qty,
                    'mark_type': 'all_except_context',
                    'quantity_evidence': 'comentario: todos/los demás salvo tachados',
                    'reason': 'seleccionado por contexto de todos menos/exepto/los demás sí'
                })

    selected_code_set = set()
    for it in selected_products:
        cc = _norm_code_list([it.get('code') if isinstance(it, dict) else it])
        if cc:
            selected_code_set.add(cc[0])

    exclude_codes = []
    for it in excluded_products:
        codes = _norm_code_list([it.get('code') if isinstance(it, dict) else it])
        if not codes:
            continue
        code = codes[0]
        if code not in visible_codes:
            continue
        # Si la IA puso un código en selected y excluded, selected gana salvo que el comentario diga tachados no.
        if code in selected_code_set and not tachados_no:
            continue
        if code not in exclude_codes:
            exclude_codes.append(code)

    add_codes = []
    quantities = {}
    for it in selected_products:
        codes = _norm_code_list([it.get('code') if isinstance(it, dict) else it])
        if not codes:
            continue
        code = codes[0]
        if code not in visible_codes:
            continue
        if code in exclude_codes:
            continue
        qty = global_qty
        if isinstance(it, dict):
            raw_q = it.get('quantity') or it.get('qty')
            try:
                if raw_q is not None:
                    qty = max(1, int(raw_q))
            except Exception:
                qty = global_qty
            if raw_q is None:
                hint_qty = _visual_text_qty_hint(it.get('mark_type'), it.get('quantity_evidence'), it.get('reason'))
                if hint_qty:
                    qty = hint_qty
        if code not in add_codes:
            add_codes.append(code)
            quantities[code] = qty

    visual_items = []
    states = {c: 'none' for c in visible_codes}
    for c in exclude_codes:
        states[c] = 'excluded'
    for c in add_codes:
        states[c] = 'selected'

    reason_by_code = {}
    mark_by_code = {}
    for group in [selected_products, excluded_products, ambiguous_products]:
        for it in group:
            if not isinstance(it, dict):
                continue
            codes = _norm_code_list([it.get('code')])
            if not codes:
                continue
            code = codes[0]
            reason_by_code[code] = it.get('reason') or it.get('quantity_evidence') or ''
            mark_by_code[code] = it.get('mark_type') or ''

    for code in visible_codes:
        it = visual_map.get(code) or {}
        visual_items.append({
            'code': code,
            'row': it.get('row') if isinstance(it, dict) else None,
            'col': it.get('col') if isinstance(it, dict) else None,
            'label_text': (it.get('label_text') or it.get('label') or '') if isinstance(it, dict) else '',
            'visual_color': it.get('visual_color') if isinstance(it, dict) else '',
            'mark': states.get(code, 'none'),
            'mark_type': mark_by_code.get(code, ''),
            'quantity': quantities.get(code, ''),
            'confidence': it.get('confidence', '') if isinstance(it, dict) else '',
            'reason': reason_by_code.get(code) or ((it.get('cell_description') or '') if isinstance(it, dict) else ''),
        })

    warnings = list(parsed.get('warnings') or []) if isinstance(parsed.get('warnings'), list) else []
    if not visible_codes:
        warnings.append('La IA no pudo leer códigos visibles. No agregué productos para evitar inventar.')
    if not add_codes and selected_products:
        warnings.append('La IA mencionó seleccionados pero no estaban en visible_products; se bloquearon para evitar alucinación.')

    return add_codes, exclude_codes, quantities, visual_items, warnings

@app.route('/api/analizar-imagen-referencia', methods=['POST'])
def analizar_imagen_referencia():
    data = request.get_json(force=True) or {}
    data_url = data.get('image_base64') or ''
    original_data_url = data.get('original_image_base64') or ''
    comentario = (data.get('comentario') or '').strip()
    marca = (data.get('marca') or '').strip()
    hilo = (data.get('hilo') or '').strip()
    contexto = (data.get('contexto') or '').strip()
    if not contexto:
        contexto = f"{marca} / {hilo}".strip(" / ")

    if not data_url:
        return jsonify({'ok': False, 'error': 'No se recibió imagen'}), 400

    try:
        raw = _extract_data_url_bytes(data_url)
    except Exception:
        return jsonify({'ok': False, 'error': 'No pude leer la imagen. Intenta subirla otra vez.'}), 400

    modo = (data.get('modo') or '').strip().lower()
    # Se desactiva el modo rápido: el analizador visual debe priorizar precisión.
    # Aun si una versión vieja del navegador manda modo=rapido/prefer_local, el servidor usa IA precisa.
    force_ia = True
    prefer_local = False
    fast_vision = False

    vision_notes = []
    add_codes = []
    exclude_codes = []
    quantities = {}
    visual_items = []
    advertencias = []
    phase_result = None
    grid_debug = None
    ocr_text = ''
    vision_text = ''

    with DB() as db:
        productos_contexto = _codigos_contexto_productos(db, marca, hilo)

    try:
        parsed, provider = _analizar_seleccion_hilos_ia_pura(data_url, raw, original_data_url, comentario, contexto, productos_contexto, fast=fast_vision)
        vision_notes.append(provider)
        if parsed:
            phase_result = parsed
            vision_text = json.dumps(parsed, ensure_ascii=False)
            add_codes, exclude_codes, quantities, visual_items, warns = _resolver_ia_pura_marcas(parsed, productos_contexto, comentario)
            advertencias.extend(warns)
    except Exception as e:
        vision_notes.append('openai_pura_error:' + str(e)[:220])
        advertencias.append('Falló la IA visual: ' + str(e)[:180])

    # Diagnóstico rápido sin IA: detecta trazos rojos para que el botón no quede ciego
    # si OpenAI tarda, falla o no hay API key. También rescata óvalos grandes que la IA confunda con tachones.
    try:
        fb_add, fb_exclude, fb_debug = _infer_visual_codes_grid(raw, productos_contexto, comentario)
        grid_debug = fb_debug
        if not add_codes and marca and hilo and (fb_add or fb_exclude):
            add_codes = fb_add
            exclude_codes = list(dict.fromkeys(list(exclude_codes) + list(fb_exclude)))
            quantities = {c: quantities.get(c, 1) for c in add_codes}
            vision_notes.append('fallback_marcas_rojas')
            advertencias.append('Usé respaldo de marcas rojas porque la IA no respondió con productos. Revisa el carrito antes de guardar.')
        elif add_codes and marca and hilo and fb_debug:
            # PRECISIÓN PRIMERO:
            # Antes se hacía un "rescate" automático de óvalos detectados por geometría local.
            # Ese respaldo puede confundir trazos de una celda con otra y agregar códigos que no pidió
            # la clienta (por ejemplo 1, 14, 25, 61 o 73).
            # Ahora, si la IA ya devolvió productos, NO mezclamos resultados del fallback.
            # El fallback solo se usa cuando la IA no devuelve ningún producto.
            if str(os.environ.get('ALLOW_VISUAL_RESCUE', '')).strip().lower() in ('1', 'true', 'yes', 'si'):
                # Modo opcional para diagnóstico/admin. Aun así solo rescata códigos que la IA haya
                # marcado como ambiguos o excluidos con razón de círculo/óvalo, no códigos nuevos.
                rescue_codes = _fallback_strong_circle_codes(fb_debug)
                allowed_to_rescue = set()
                try:
                    if isinstance(phase_result, dict):
                        for group_name in ('ambiguous_products', 'excluded_products'):
                            for it in (phase_result.get(group_name) or []):
                                if not isinstance(it, dict):
                                    continue
                                cc = _norm_code_list([it.get('code')])
                                if not cc:
                                    continue
                                reason = _strip_acc(str(it.get('reason') or '') + ' ' + str(it.get('mark_type') or ''))
                                if any(w in reason for w in ('circulo', 'circle', 'oval', 'ovalo', 'encierro', 'contorno')):
                                    allowed_to_rescue.add(cc[0])
                except Exception:
                    allowed_to_rescue = set()
                rescued = []
                for c in rescue_codes:
                    if c in allowed_to_rescue and c not in add_codes:
                        add_codes.append(c)
                        quantities[c] = quantities.get(c, 1)
                        rescued.append(c)
                if rescued:
                    exclude_codes = [c for c in exclude_codes if c not in set(rescued)]
                    vision_notes.append('rescate_ovalos_grandes_admin')
                    advertencias.append('Rescaté como seleccionados estos códigos por óvalo grande claro: ' + ', '.join(rescued) + '. Revisa antes de guardar.')
            else:
                vision_notes.append('fallback_marcas_rojas_solo_diagnostico')
    except Exception as e:
        vision_notes.append('fallback_marcas_rojas_error:' + str(e)[:160])

    # OCR local puede hacer lento Render y normalmente no se necesita; solo se activa en diagnóstico.
    if bool(data.get('include_ocr')) or bool(data.get('admin_debug')):
        try:
            img = Image.open(io.BytesIO(raw))
            try:
                import pytesseract
                ocr_text = (pytesseract.image_to_string(img, lang='spa+eng') or '').strip()
                if ocr_text:
                    vision_notes.append('ocr_debug')
            except Exception:
                pass
        except Exception:
            pass

    if not os.environ.get('OPENAI_API_KEY'):
        advertencias.append('No hay OPENAI_API_KEY. La interpretación pura de imagen necesita esa key.')

    add_codes = [c for c in add_codes if c not in set(exclude_codes)]
    pedidos, no_encontrados = _productos_a_pedidos_por_codigos(productos_contexto, add_codes, exclude_codes, quantities)

    retried_all = False
    if add_codes and not pedidos:
        with DB() as db:
            productos_all = _codigos_contexto_productos(db, '', '')
        pedidos, no_encontrados = _productos_a_pedidos_por_codigos(productos_all, add_codes, exclude_codes, quantities)
        if pedidos:
            retried_all = True
            vision_notes.append('fallback_sin_contexto')
            advertencias.append('El contexto no encontró productos; busqué los códigos en todo el almacén.')

    if not marca or not hilo:
        advertencias.append('Selecciona Marca e Hilo exactos antes de analizar; eso evita que un código repetido se convierta en otro producto.')
    if no_encontrados:
        advertencias.append('Códigos detectados que no existen en el contexto: ' + ', '.join(no_encontrados))

    resumen = _image_reference_summary(' '.join(x for x in [comentario, ocr_text, vision_text] if x).strip())
    suggested_text = ', '.join(f"{c} {quantities.get(c,1)}" for c in add_codes) if add_codes else comentario

    return jsonify(json_safe({
        'ok': True,
        'ocr_text': ocr_text,
        'vision_text': vision_text,
        'summary': resumen,
        'vision_notes': vision_notes,
        'suggested_text': suggested_text,
        'add_codes': add_codes,
        'exclude_codes': exclude_codes,
        'quantities': quantities,
        'pedidos': pedidos,
        'no_encontrados': no_encontrados,
        'visual_items': visual_items,
        'contexto': {'marca': marca, 'hilo': hilo, 'productos_contexto': len(productos_contexto), 'retry_all': retried_all},
        'grid_debug': grid_debug,
        'phase_result': phase_result,
        'cell_result': None,
        'advertencias': advertencias,
    }))

@app.route('/api/transcribir-audio', methods=['POST'])
def transcribir_audio():
    data = request.get_json(force=True) or {}
    data_url = data.get('audio_base64') or ''
    filename = (data.get('filename') or 'audio.ogg').strip()
    user_prompt = (data.get('prompt') or '').strip()
    marca_ctx = (data.get('marca') or '').strip()
    hilo_ctx = (data.get('hilo') or '').strip()
    if not data_url:
        return jsonify({'ok': False, 'error': 'No se recibió audio'}), 400
    try:
        raw = _extract_data_url_bytes(data_url)
    except Exception:
        return jsonify({'ok': False, 'error': 'No pude leer el audio. Intenta grabarlo otra vez o sube un audio compatible.'}), 400
    suffix = '.' + filename.split('.')[-1].lower() if '.' in filename else '.ogg'
    transcript = ''
    provider = ''
    # Intento con OpenAI compatible
    try:
        api_key = os.environ.get('OPENAI_API_KEY')
        if api_key:
            from openai import OpenAI
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw)
                temp_path = tmp.name
            try:
                client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "90")))
                base_prompt = (
                    'Pedido de mercería Hilorama en español de México. '
                    'Puede incluir códigos numéricos de colores, cantidades, piezas, madejas, nombres de tonos y marcas. '
                    'Transcribe de forma literal y conserva los números como dígitos cuando sean códigos o cantidades.'
                )
                ctx_bits = []
                if marca_ctx:
                    ctx_bits.append('Marca contexto: ' + marca_ctx)
                if hilo_ctx:
                    ctx_bits.append('Hilo contexto: ' + hilo_ctx)
                final_prompt = ' '.join([base_prompt, user_prompt] + ctx_bits).strip()[:900]
                with open(temp_path, 'rb') as f:
                    kwargs = {
                        'model': os.environ.get('OPENAI_TRANSCRIBE_MODEL', 'whisper-1'),
                        'file': f,
                        'language': 'es',
                    }
                    if final_prompt:
                        kwargs['prompt'] = final_prompt
                    try:
                        resp = client.audio.transcriptions.create(**kwargs)
                    except TypeError:
                        kwargs.pop('prompt', None)
                        kwargs.pop('language', None)
                        resp = client.audio.transcriptions.create(**kwargs)
                transcript = getattr(resp, 'text', '') or (resp.get('text') if isinstance(resp, dict) else '') or ''
                provider = 'openai'
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
    except Exception:
        transcript = ''
    # Intento con speech_recognition (si existe y el formato lo permite)
    if not transcript:
        try:
            import speech_recognition as sr
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw)
                temp_path = tmp.name
            try:
                rec = sr.Recognizer()
                with sr.AudioFile(temp_path) as source:
                    audio = rec.record(source)
                transcript = rec.recognize_google(audio, language='es-MX')
                provider = 'google-sr'
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        except Exception:
            transcript = ''
    if not transcript:
        return jsonify({'ok': False, 'error': 'No pude transcribir el audio. Para que funcione en Render, configura OPENAI_API_KEY o usa un formato compatible con SpeechRecognition/WAV.'}), 400
    return jsonify({'ok': True, 'transcript': transcript, 'provider': provider})



def _parse_json_field(value, default=None):
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        if isinstance(value, str) and value.strip():
            return json.loads(value)
    except Exception:
        pass
    return default


def _nota_full(db, nota_id):
    nota = db.execute("""
        SELECT n.*, c.nombre AS cliente_nombre_real, c.telefono, c.direccion
        FROM notas n
        LEFT JOIN clientes c ON c.id = n.cliente_id
        WHERE n.id=%s
    """, (nota_id,)).fetchone()
    if not nota:
        return None

    # Solución definitiva contra duplicados en PDF:
    # NO hacemos JOIN directo a productos porque en tu almacén existen códigos repetidos,
    # incluso filas repetidas del mismo código/color con distinto stock.
    # Usamos LEFT JOIN LATERAL con LIMIT 1 para que cada renglón de items encuentre
    # máximo 1 producto de referencia y no se multiplique.
    rows = db.execute("""
        SELECT
            i.id,
            i.nota_id,
            i.codigo,
            COALESCE(i.cantidad, 1) AS cantidad,
            COALESCE(i.precio, p.precio, pr.venta, 0) AS precio_unit,
            COALESCE(NULLIF(i.marca,''), p.marca, '') AS marca_final,
            COALESCE(NULLIF(i.hilo,''), p.hilo, '') AS hilo_final,
            COALESCE(NULLIF(i.color,''), p.color, '') AS color_final
        FROM items i
        LEFT JOIN LATERAL (
            SELECT p2.*
            FROM productos p2
            WHERE (
                    (i.producto_id IS NOT NULL AND p2.id = i.producto_id)
                    OR (
                        i.producto_id IS NULL
                        AND p2.codigo = i.codigo
                    )
                  )
              AND (
                    i.producto_id IS NOT NULL
                    OR COALESCE(NULLIF(i.marca,''),'') = ''
                    OR UPPER(COALESCE(p2.marca,'')) = UPPER(COALESCE(i.marca,''))
                  )
              AND (
                    i.producto_id IS NOT NULL
                    OR COALESCE(NULLIF(i.hilo,''),'') = ''
                    OR UPPER(COALESCE(p2.hilo,'')) = UPPER(COALESCE(i.hilo,''))
                  )
              AND (
                    i.producto_id IS NOT NULL
                    OR COALESCE(NULLIF(i.color,''),'') = ''
                    OR UPPER(COALESCE(p2.color,'')) = UPPER(COALESCE(i.color,''))
                  )
            ORDER BY
                CASE WHEN i.producto_id IS NOT NULL AND p2.id=i.producto_id THEN 0 ELSE 1 END,
                CASE WHEN UPPER(COALESCE(p2.marca,'')) = UPPER(COALESCE(i.marca,'')) THEN 0 ELSE 1 END,
                CASE WHEN UPPER(COALESCE(p2.hilo,'')) = UPPER(COALESCE(i.hilo,'')) THEN 0 ELSE 1 END,
                CASE WHEN UPPER(COALESCE(p2.color,'')) = UPPER(COALESCE(i.color,'')) THEN 0 ELSE 1 END,
                COALESCE(p2.stock,0) DESC,
                p2.id ASC
            LIMIT 1
        ) p ON TRUE
        LEFT JOIN precios pr ON pr.marca = COALESCE(NULLIF(i.marca,''), p.marca)
        WHERE i.nota_id=%s
        ORDER BY i.id
    """, (nota_id,)).fetchall()

    n = dict(nota)
    n["envio"] = _parse_json_field(n.get("envio"), {})
    n["direccion"] = _parse_json_field(n.get("direccion"), {})
    n["cliente_nombre"] = n.get("cliente_nombre") or n.get("cliente_nombre_real") or ""
    n["telefono"] = n.get("telefono") or ""

    # Consolida SOLO items reales repetidos, no duplicados generados por JOIN.
    # Como el LATERAL ya no multiplica, sumar aquí sí es seguro.
    consolidados = {}
    orden = []
    for x in rows:
        d = dict(x)
        try:
            precio = float(d.get("precio_unit") or 0)
        except Exception:
            precio = 0.0
        try:
            cantidad = int(d.get("cantidad") or 0)
        except Exception:
            cantidad = 0

        item = {
            "id": d.get("id"),
            "codigo": str(d.get("codigo") or ""),
            "marca": d.get("marca_final") or "",
            "hilo": d.get("hilo_final") or "",
            "color": d.get("color_final") or "",
            "cantidad": cantidad,
            "precio": precio,
        }
        key = (
            item["codigo"].strip(),
            item["marca"].strip().upper(),
            item["hilo"].strip().upper(),
            item["color"].strip().upper(),
            item["precio"],
        )
        if key not in consolidados:
            consolidados[key] = item
            orden.append(key)
        else:
            consolidados[key]["cantidad"] += cantidad

    n["items"] = [consolidados[k] for k in orden]
    return n


def _generate_pc_pdf_file(nota):
    out_dir = os.path.join(tempfile.gettempdir(), "hilorama_pdfs")
    os.makedirs(out_dir, exist_ok=True)
    estado = (nota.get("estado") or "").upper()

    if estado == "COTIZACION":
        from generar_pdf_cotizacion import generar_pdf_cotizacion
        ruta_pdf = os.path.join(out_dir, f"{nota['id']}.pdf")
        generar_pdf_cotizacion(nota, ruta_pdf, ruta_logo="logo_hilorama.png")
        nombre = f"{nota['id']}.pdf"
    else:
        from generar_pdf_venta_premium import generar_pdf_venta_premium
        ruta_pdf = os.path.join(out_dir, f"{nota['id']}_premium.pdf")
        generar_pdf_venta_premium(nota, ruta_pdf, ruta_logo="logo_hilorama.png")
        nombre = f"{nota['id']}_premium.pdf"

    if not os.path.exists(ruta_pdf):
        raise RuntimeError("No se pudo generar el PDF")
    return ruta_pdf, nombre


@app.route('/api/debug-nota-items/<nota_id>')
def debug_nota_items(nota_id):
    with DB() as db:
        nota = _nota_full(db, nota_id)
    if not nota:
        return jsonify({'ok': False, 'error': 'Nota no encontrada'}), 404
    return jsonify(json_safe({
        'ok': True,
        'nota_id': nota_id,
        'items_count': len(nota.get('items') or []),
        'items': nota.get('items') or [],
    }))


@app.route('/debug-nota-items/<nota_id>')
def debug_nota_items_browser(nota_id):
    expected = os.environ.get("MOBILE_PIN", "").strip()
    got = request.args.get("pin", "").strip() or request.args.get("debug_pin", "").strip()
    if expected and got != expected:
        return jsonify({'ok': False, 'error': 'PIN incorrecto. Abre esta URL agregando ?pin=TU_PIN'}), 401
    with DB() as db:
        nota = _nota_full(db, nota_id)
    if not nota:
        return jsonify({'ok': False, 'error': 'Nota no encontrada'}), 404
    return jsonify(json_safe({
        'ok': True,
        'nota_id': nota_id,
        'items_count': len(nota.get('items') or []),
        'items': nota.get('items') or [],
    }))


@app.route('/nota-pdf/<nota_id>')
def nota_pdf_html(nota_id):
    """
    Genera el PDF usando los mismos generadores del programa de PC:
    - COTIZACION -> generar_pdf_cotizacion.py
    - VENTA_PENDIENTE/PAGADA -> generar_pdf_venta_premium.py
    """
    with DB() as db:
        nota = _nota_full(db, nota_id)
    if not nota:
        return 'Nota no encontrada', 404
    try:
        ruta_pdf, nombre = _generate_pc_pdf_file(nota)
        return send_file(ruta_pdf, mimetype='application/pdf', as_attachment=False, download_name=nombre)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'No se pudo generar PDF estilo PC: {e}'}), 500


@app.route('/api/notas/<nota_id>/pdf-pc')
def nota_pdf_pc_api(nota_id):
    with DB() as db:
        nota = _nota_full(db, nota_id)
    if not nota:
        return jsonify({'ok': False, 'error': 'Nota no encontrada'}), 404
    try:
        ruta_pdf, nombre = _generate_pc_pdf_file(nota)
        return send_file(ruta_pdf, mimetype='application/pdf', as_attachment=False, download_name=nombre)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'No se pudo generar PDF estilo PC: {e}'}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)


# ==========================================================
# WhatsApp IA V3 - cerebro comercial Hilorama basado en almacén
# ==========================================================
# Esta capa sobreescribe funciones del simulador para que el agente:
# - no dependa del selector manual de marca/hilo,
# - entienda consultas reales de clientas,
# - use el almacén como fuente de verdad,
# - no invente productos ni pregunte lo obvio,
# - responda más humano y corto.

WA_QTY_WORDS = {
    'un':1,'uno':1,'una':1,'dos':2,'tres':3,'cuatro':4,'cinco':5,'seis':6,'siete':7,'ocho':8,'nueve':9,'diez':10,
    'once':11,'doce':12,'trece':13,'catorce':14,'quince':15,'dieciseis':16,'dieciséis':16,
    'veinte':20,'treinta':30,'cuarenta':40
}


def _wa_aliases_hilo(hilo):
    h = _norm_txt(hilo or '')
    aliases = set()
    if h:
        aliases.add(h)
        aliases.add(h.replace(' ', ''))
        aliases.add(h.replace('-', ' '))
    # Alize Velluto / Velluto
    if any(x in h for x in ['velluto','veluto','velvet','chenille','chenil']):
        aliases.update(['alize velluto','alize veluto','velluto','vellutos','veluto','velutos','vello','vellos','terciopelo','aterciopelado','chenille','chenil'])
    # Karina Komfy Mini
    if any(x in h for x in ['komfy','comfy','komfi']):
        aliases.update(['karina komfy','karina komfy mini','komfy','komfy mini','komfymini','komfi','komfi mini','comfy','comfy mini','komfis','konfy','konfy mini','konfi'])
    # Kurumi
    if 'kurumi' in h or 'kurumi' in h.replace(' ', ''):
        aliases.update(['kurumi','karina kurumi','kurumis','kurumi mini'])
    # Trapillo kraft
    if 'trapillo' in h or 'kraft' in h:
        aliases.update(['trapillo','trapillo kraft','kraft','trapiyo','trapiyos','trapillo karina'])
    # Fiorentino, fosfo u otros hilos comunes si existen en el almacén.
    if 'fiorentino' in h or 'fior' in h:
        aliases.update(['fiorentino','florentino','fior','fioren'])
    if 'fosfo' in h:
        aliases.update(['fosfo','fosforescente','fluor','neon'])
    return {a for a in aliases if a and len(a) >= 3}


def _wa_aliases_marca(marca):
    m = _norm_txt(marca or '')
    aliases = set([m]) if m else set()
    if 'karina' in m:
        aliases.update(['karina','estambres karina'])
    if 'alize' in m:
        aliases.update(['alize','alise'])
    if 'hilorama' in m:
        aliases.update(['hilorama'])
    return {a for a in aliases if a and len(a) >= 3}


def _wa_detectar_marcas(texto, productos):
    t = _norm_txt(texto or '')
    out=[]; seen=set()
    for p in productos or []:
        marca=(p.get('marca') or '').strip()
        mn=_norm_txt(marca)
        if not marca or mn in seen:
            continue
        for a in _wa_aliases_marca(marca):
            aa=_norm_txt(a)
            if re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t):
                out.append(marca); seen.add(mn); break
    return out


def _wa_detectar_hilos(texto, productos):
    t = _norm_txt(texto or '')
    if not t:
        return []
    hallados = []
    for h in _wa_catalogo_hilos(productos):
        hn=_norm_txt(h)
        for a in _wa_aliases_hilo(h):
            aa = _norm_txt(a)
            if not aa:
                continue
            compacto = t.replace(' ', '')
            if re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t) or aa.replace(' ', '') in compacto:
                if h not in hallados:
                    hallados.append(h)
                break
        # Match inverso: si el texto tiene velluto y el hilo se llama ALIZE VELLUTO, etc.
        if h not in hallados:
            for token in ['velluto','veluto','komfy','komfi','konfy','kurumi','trapillo','kraft','fiorentino','fosfo']:
                if token in t and token in hn:
                    hallados.append(h); break
    return hallados


def _wa_split_clausulas(texto):
    t = _norm_txt(texto or '')
    # Separa listas largas sin romper descripciones como "blanco o hueso medio amarillento".
    t = re.sub(r'\b(tambien|ademas|aparte|luego|y tambien|y aparte)\b', ',', t)
    # "y 3 negros", "y un 429", etc. suele iniciar otro renglón/producto.
    qty = r'(?:\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|veinte|treinta|cuarenta)'
    t = re.sub(rf'\s+y\s+(?={qty}\b)', ', ', t)
    # Cambios de opinión/cancelaciones deben ser su propia cláusula.
    t = re.sub(r'\b(pensandolo mejor|mejor|olvida|cancelame|quitame|quitalo|quita|no pongas|ya no quiero|mejor no)\b', r', \1 ', t)
    partes = [x.strip(' ,.;') for x in re.split(r'[,;\n]+', t) if x.strip(' ,.;')]
    return partes or [t]


def _wa_hay_cantidad(texto):
    t=_norm_txt(texto or '')
    return bool(re.search(r'(?<!\w)(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|veinte|treinta|cuarenta)(?!\w)', t))


def _wa_es_consulta_catalogo(texto):
    t=_norm_txt(texto or '')
    return bool(re.search(r'\b(me interesa|tienen|tiene|manejan|maneja|cuenta con|hay|disponible|disponibilidad|catalogo|carta|colores|tonos|precio|cuanto|cuesta|paquete|combo)\b', t)) and not _wa_hay_cantidad(t)


def _wa_es_pregunta_envio(texto):
    t=_norm_txt(texto or '')
    return bool(re.search(r'\b(envio|envios|envias|mandan|mandas|paqueteria|correo|estafeta|fedex|mexico|republica|codigo postal|cp)\b', t))


def _wa_es_pregunta_pago(texto):
    t=_norm_txt(texto or '')
    return bool(re.search(r'\b(pague|pago|pagado|deposito|transferencia|comprobante|ticket|recibo|mando comprobante)\b', t))


def _wa_es_saludo(texto):
    t=_norm_txt(texto or '')
    return bool(re.fullmatch(r'(hola|buenos dias|buenas tardes|buenas noches|hello|ola)[!\. ]*', t or ''))


def _wa_resumen_hilo(hilo, productos):
    ctx=_wa_filtrar_por_hilo(productos, hilo)
    disponibles=[p for p in ctx if int(p.get('stock') or 0) > 0]
    precios=[]
    for p in ctx:
        try:
            pr=float(p.get('precio_venta') or 0)
            if pr>0: precios.append(pr)
        except Exception:
            pass
    colores=[]
    seen=set()
    for p in disponibles:
        c=(p.get('color') or '').strip()
        cod=str(p.get('codigo') or '').strip()
        key=_norm_txt(c) or cod
        if key and key not in seen:
            colores.append({'codigo':cod,'color':c,'stock':int(p.get('stock') or 0)})
            seen.add(key)
    return {'hilo':hilo,'total':len(ctx),'disponibles':len(disponibles),'precio_min':min(precios) if precios else 0,'precio_max':max(precios) if precios else 0,'colores':colores[:12]}


def _wa_resumen_marca(marca, productos):
    mn=_norm_txt(marca)
    hilos=[]; seen=set()
    for p in productos or []:
        if _norm_txt(p.get('marca') or '') != mn:
            continue
        h=(p.get('hilo') or '').strip()
        if h and _norm_txt(h) not in seen:
            hilos.append(h); seen.add(_norm_txt(h))
    return {'marca':marca,'hilos':hilos[:8]}


def _wa_respuesta_consulta_almacen(texto, productos, hilos=None, marcas=None):
    t=_norm_txt(texto or '')
    hilos=hilos or []
    marcas=marcas or []
    if _wa_es_pregunta_envio(texto):
        cp = re.search(r'\b\d{5}\b', t)
        if cp:
            return f"Sí tenemos envíos 😊 Con el CP {cp.group(0)} puedo cotizarte opciones de paquetería. En un momento te comparto las opciones disponibles."
        return "Sí, hacemos envíos a todo México 😊 Para cotizarte el envío me puede compartir su código postal, por favor."
    if _wa_es_pregunta_pago(texto):
        return "Perfecto 😊 Puede mandarme la imagen del comprobante y reviso que coincida el monto para continuar con su pedido."
    if hilos:
        bloques=[]
        for h in hilos[:3]:
            r=_wa_resumen_hilo(h, productos)
            if r['total']:
                precio = f" desde ${r['precio_min']:.2f}" if r['precio_min'] else ""
                if 'color' in t or 'tono' in t or 'disponib' in t or 'catalogo' in t:
                    sample=', '.join([f"{c['codigo']} {c['color']}".strip() for c in r['colores'][:6] if c.get('codigo') or c.get('color')])
                    extra=f"\nTonos disponibles ejemplo: {sample}." if sample else ""
                    bloques.append(f"Sí 😊 manejamos {h}{precio}. Tengo varios tonos disponibles.{extra}")
                else:
                    bloques.append(f"Sí 😊 manejamos {h}{precio}. ¿Busca algún tono o código en especial?")
        if bloques:
            return '\n\n'.join(bloques).strip()
    if marcas:
        bloques=[]
        for m in marcas[:3]:
            r=_wa_resumen_marca(m, productos)
            if r['hilos']:
                bloques.append(f"Sí 😊 manejamos {m}. Tengo por ejemplo: " + ', '.join(r['hilos'][:5]) + ". ¿Cuál buscaba?")
        if bloques:
            return '\n\n'.join(bloques)
    # Productos externos comunes que preguntan por nombre, sin estar en almacén.
    externos = {
        'abuelita': 'La Abuelita por el momento no la manejamos. Lo más parecido que puedo ofrecerle depende del proyecto: Kurumi si busca algo más firme/delgado, o Komfy Mini si busca chenille suave. ¿Para qué trabajo lo ocuparía?',
        'karenita': 'Karenita por el momento no la veo en el almacén. Sí manejamos opciones Karina; dígame si busca grosor, textura o color específico y le sugiero el más parecido.',
        'abuelitas': 'La Abuelita por el momento no la manejamos. Lo más parecido que puedo ofrecerle depende del proyecto: Kurumi si busca algo más firme/delgado, o Komfy Mini si busca chenille suave. ¿Para qué trabajo lo ocuparía?',
    }
    for k,msg in externos.items():
        if k in t:
            return msg
    return ''


def _wa_parece_linea_contexto_hilo(parte):
    # Ej. "40 de komfy mini" en una lista de combo: normalmente es encabezado de bloque, no producto para agregar.
    t=_norm_txt(parte or '')
    return bool(re.fullmatch(r'(?:\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|veinte|cuarenta)\s+(?:de\s+)?[a-z0-9 ]{3,35}', t))


def _wa_parsear_con_contexto_almacen(texto_total, productos_all, marca='', hilo='', extraer_pedidos_func=None):
    extraer = extraer_pedidos_func
    productos_base = _wa_filtrar_por_marca_hilo(productos_all, marca, hilo)
    texto_norm = _norm_txt(texto_total or '')
    hilos_globales = _wa_detectar_hilos(texto_norm, productos_base)
    marcas_globales = _wa_detectar_marcas(texto_norm, productos_base)
    contexto_global = hilo or (hilos_globales[0] if len(hilos_globales) == 1 else '')
    pedidos_dict = {}
    preguntas=[]; errores=[]; advertencias=[]; sugerencias=[]; hilos_detectados=[]
    respuesta_preferida = ''
    ultimo_hilo = contexto_global

    for h in hilos_globales:
        if h not in hilos_detectados:
            hilos_detectados.append(h)

    # Consultas sin pedido: "Me interesa Alize Velluto, qué colores tienen disponibles", "¿y de Komfy Mini?"
    if _wa_es_consulta_catalogo(texto_norm):
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            return {
                'pedidos_full': [], 'errores': [], 'advertencias': [], 'preguntas': [],
                'sugerencias_almacen': [], 'hilos_detectados': hilos_detectados,
                'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
                'respuesta_preferida': resp,
                'ventas_info': {'tipo': 'consulta_catalogo'}
            }

    # Preguntas de envío/pago sin pedido claro.
    if not _wa_hay_cantidad(texto_norm) and (_wa_es_pregunta_envio(texto_norm) or _wa_es_pregunta_pago(texto_norm)):
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            return {
                'pedidos_full': [], 'errores': [], 'advertencias': [], 'preguntas': [],
                'sugerencias_almacen': [], 'hilos_detectados': hilos_detectados,
                'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
                'respuesta_preferida': resp,
                'ventas_info': {'tipo': 'consulta_envio_pago'}
            }

    # Procesa por cláusulas para evitar mezclar Velluto con Komfy o cancelaciones.
    clauses=_wa_split_clausulas(texto_norm)
    for idx, parte in enumerate(clauses):
        if not parte:
            continue
        hilos_parte = _wa_detectar_hilos(parte, productos_base)
        marcas_parte = _wa_detectar_marcas(parte, productos_base)
        for h in hilos_parte:
            if h not in hilos_detectados:
                hilos_detectados.append(h)
        if _wa_es_quitar(parte):
            borrados = _wa_remover_por_texto(pedidos_dict, parte, productos_base)
            if borrados:
                advertencias.append(f"Se quitaron {borrados} producto(s) por indicación de la clienta.")
            else:
                advertencias.append("La clienta pidió quitar algo, pero no encontré una coincidencia clara.")
            continue

        # Si en medio de una conversación pregunta por catálogo sin pedir cantidad.
        if _wa_es_consulta_catalogo(parte) and not _wa_hay_cantidad(parte):
            resp=_wa_respuesta_consulta_almacen(parte, productos_base, hilos_parte or hilos_globales, marcas_parte or marcas_globales)
            if resp and not pedidos_dict:
                respuesta_preferida=resp
            elif resp:
                advertencias.append(resp)
            continue

        hilo_ctx = hilos_parte[0] if len(hilos_parte) == 1 else (ultimo_hilo or contexto_global)
        if hilo_ctx:
            ultimo_hilo = hilo_ctx
        productos_ctx = _wa_filtrar_por_hilo(productos_base, hilo_ctx) if hilo_ctx else productos_base

        # Si la línea solo establece contexto para las siguientes líneas (lista grande/combos), no agregues ni preguntes todavía.
        if hilo_ctx and _wa_parece_linea_contexto_hilo(parte) and idx < len(clauses)-1:
            continue

        parse = extraer(parte, productos_ctx) if extraer else {'pedidos': [], 'preguntas': [], 'errores': []}
        full, err = _wa_pedidos_full_desde_parse(parse, productos_ctx)
        for fp in full:
            _wa_agregar_o_sumar(pedidos_dict, fp)
        errores.extend(err)
        errores.extend(parse.get('errores') or [])
        preguntas.extend(parse.get('preguntas') or [])
        advertencias.extend(parse.get('advertencias') or [])

        # Tono descrito: "blanco o hueso medio amarillento"; usar sugerencias del almacén y preguntar cuál agregar.
        if hilo_ctx and _wa_color_descripcion_keywords(parte):
            # Solo agregar sugerencias cuando el color fue ambiguo o la frase describe algo no exacto.
            descripcion_larga = any(x in parte for x in ['hueso','marfil','amarillent','medio','parecid','calido','piel','crema','nude'])
            if descripcion_larga or (parse.get('preguntas') or []):
                sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
                if sug:
                    sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                    preguntas.append(f"Para {hilo_ctx}, la clienta describió un tono. Sugiere opciones del almacén y pregunta cuál quiere agregar.")

        # Menciona hilo con cantidad pero no dio tono/código claro: preguntar qué tonos.
        if hilo_ctx and not full and _wa_hay_cantidad(parte):
            sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
            if sug:
                sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                preguntas.append(f"Para {hilo_ctx}, falta confirmar cuál de las opciones sugeridas desea agregar.")
            else:
                m_qty = re.search(r'\b(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|veinte|cuarenta)\b', parte)
                preguntas.append(f"Sí contamos con {hilo_ctx}. Falta confirmar qué tono o código quiere para {m_qty.group(1) if m_qty else ''} pieza(s).")

    # Si no hubo pedido ni respuesta, revisa producto externo por nombre.
    if not pedidos_dict and not respuesta_preferida and not preguntas:
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            respuesta_preferida = resp
        else:
            similares = _wa_sugerir_hilos_similares(texto_norm, productos_base, limit=5)
            if similares:
                sugerencias.append({'tipo': 'hilo_similar', 'texto': texto_total, 'opciones': similares})
                preguntas.append('El producto exacto no se identificó en almacén; ofrece alternativas similares por textura.')

    return {
        'pedidos_full': list(pedidos_dict.values()),
        'errores': sorted(set(str(e) for e in errores if e)),
        'advertencias': sorted(set(str(a) for a in advertencias if a)),
        'preguntas': sorted(set(str(p) for p in preguntas if p)),
        'sugerencias_almacen': sugerencias,
        'hilos_detectados': hilos_detectados,
        'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
        'respuesta_preferida': respuesta_preferida,
        'ventas_info': {'tipo': 'pedido_o_conversacion'}
    }


def _formatear_sugerencias_almacen_wa(parsed):
    bloques = []
    for sug in parsed.get('sugerencias_almacen') or []:
        tipo = sug.get('tipo')
        opciones = sug.get('opciones') or []
        hilo = sug.get('hilo') or ''
        if tipo == 'tonos_por_descripcion' and opciones:
            lineas = []
            for op in opciones[:4]:
                linea = f"- {op.get('codigo')} {op.get('color','')}"
                if op.get('stock') is not None:
                    linea += f" (stock {op.get('stock')})"
                lineas.append(linea.strip())
            if lineas:
                bloques.append(f"Para ese tono en {hilo}, las opciones más cercanas que tengo son:\n" + '\n'.join(lineas))
        elif tipo == 'hilo_similar' and opciones:
            lineas = []
            for op in opciones[:4]:
                txt = f"- {op.get('hilo')}"
                if op.get('ejemplo_codigo'):
                    txt += f". Ejemplo: {op.get('ejemplo_codigo')} {op.get('ejemplo_color','')}"
                lineas.append(txt.strip())
            if lineas:
                bloques.append('No lo veo con ese nombre exacto en mi almacén, pero puedo ofrecerle opciones similares:\n' + '\n'.join(lineas))
    return '\n\n'.join(bloques).strip()


def _fallback_respuesta_wa(texto, parsed, meta):
    if parsed.get('respuesta_preferida'):
        return str(parsed.get('respuesta_preferida')).strip()
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    sug_txt = _formatear_sugerencias_almacen_wa(parsed)
    intent = meta.get('intencion')

    provisionales = _codigos_provisionales_desde_preguntas(preguntas)
    pedidos_confirmados = [p for p in pedidos if (str(p.get('codigo') or '').strip().lstrip('0') or '0') not in provisionales]

    if errores:
        txt=''
        if pedidos_confirmados:
            txt += 'Claro 😊 ya tengo claro esto:\n' + '\n'.join(_formatear_producto_wa(p) for p in pedidos_confirmados[:20]) + '\n\n'
        txt += 'Estos códigos no me aparecen en catálogo: ' + ', '.join(map(str, errores[:8])) + '. ¿Me los confirma por favor?'
        return txt

    if preguntas:
        q_limpias = [_limpiar_pregunta_wa(q) for q in preguntas if _limpiar_pregunta_wa(q)]
        txt=''
        if pedidos_confirmados:
            txt += 'Claro 😊 ya tengo claro:\n' + '\n'.join(_formatear_producto_wa(p) for p in pedidos_confirmados[:20])
            if len(pedidos_confirmados)>20:
                txt += f"\nY {len(pedidos_confirmados)-20} producto(s) más."
            txt += '\n\n'
        if sug_txt:
            txt += sug_txt + '\n\n'
        # Pregunta una sola cosa y sin frases técnicas.
        if sug_txt:
            txt += '¿Cuál de esos tonos le agrego?'
        elif q_limpias:
            q0 = q_limpias[0]
            q0 = q0.replace('Sí contamos con', 'Sí contamos con')
            txt += 'Solo para confirmar 😊 ' + q0
        else:
            txt += 'Solo necesito confirmar un detalle para no agregarle un tono equivocado 😊'
        return txt.strip()

    if sug_txt and not pedidos:
        return sug_txt + '\n\n¿Quiere que le arme una opción con alguno de esos tonos?'

    if pedidos:
        lineas=[_formatear_producto_wa(p) for p in pedidos[:25]]
        txt='Claro 😊 le agrego:\n' + '\n'.join(lineas)
        if len(pedidos)>25:
            txt += f"\nY {len(pedidos)-25} producto(s) más."
        txt += '\n\nLe preparo su cotización.'
        return txt

    if intent == 'pregunta_precio':
        return 'Claro 😊 ¿me confirma qué hilo o código quiere revisar? Así le doy precio y disponibilidad exacta.'
    if intent == 'pregunta_envio':
        return 'Sí, hacemos envíos a todo México 😊 Para cotizarlo necesito su código postal.'
    if intent == 'pregunta_stock':
        return 'Con gusto 😊 dígame el hilo, código o color que busca y reviso disponibilidad.'
    if intent == 'sugerir_tonos':
        return 'Sí 😊 mándeme la foto o referencia y le sugiero los tonos más parecidos según lo que tenga disponible. No agrego nada hasta que usted confirme.'
    if intent == 'comprobante_pago':
        return 'Perfecto 😊 mándeme la imagen del comprobante y reviso monto, referencia y datos para continuar con su pedido.'
    return 'Claro 😊 dígame qué hilo, código o color necesita y le ayudo a armar su cotización.'


def _clasificar_intencion_wa(texto, parsed):
    t = _norm_sales_txt(texto)
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    advertencias = parsed.get('advertencias') or []
    if parsed.get('respuesta_preferida'):
        intent='consulta_catalogo'
    elif any(x in t for x in ['comprobante', 'pague', 'pagado', 'deposit', 'transfer', 'ticket', 'recibo']):
        intent = 'comprobante_pago'
    elif any(x in t for x in ['parecid', 'similar', 'tono para', 'tonos para', 'color para', 'muñeco', 'amigurumi', 'trabajo', 'referencia']):
        intent = 'sugerir_tonos'
    elif pedidos:
        intent = 'pedido'
    elif any(x in t for x in ['precio', 'cuanto', 'cuesta', 'costo', 'vale']):
        intent = 'pregunta_precio'
    elif any(x in t for x in ['envio', 'envias', 'paqueteria', 'llega', 'cp ', 'codigo postal']):
        intent = 'pregunta_envio'
    elif any(x in t for x in ['stock', 'tienes', 'hay', 'disponible', 'manejas', 'colores', 'tonos']):
        intent = 'pregunta_stock'
    else:
        intent = 'conversacion'
    if preguntas or errores:
        confianza='baja'; accion='preguntar'; puede_auto=False
    elif pedidos and any(int(p.get('stock') or 0) < int(p.get('cantidad') or 1) and p.get('es_inventariable', True) for p in pedidos):
        confianza='media'; accion='revisar_stock'; puede_auto=False
    elif pedidos:
        confianza='alta' if not advertencias else 'media'; accion='crear_cotizacion'; puede_auto=not advertencias
    elif parsed.get('respuesta_preferida'):
        confianza='media-alta'; accion='responder'; puede_auto=False
    else:
        confianza='media' if intent.startswith('pregunta') else 'baja'; accion='responder' if intent.startswith('pregunta') else 'revisar'; puede_auto=False
    return {'intencion': intent, 'confianza': confianza, 'accion_recomendada': accion, 'puede_auto_enviar': bool(puede_auto)}


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    # V3: para pedidos, dudas, consultas de almacén y respuestas preferidas usamos reglas determinísticas.
    # OpenAI se deja solo para conversación libre, para evitar inventos o preguntas redundantes.
    if (parsed.get('pedidos') or parsed.get('preguntas') or parsed.get('errores') or parsed.get('respuesta_preferida') or parsed.get('sugerencias_almacen')):
        return _fallback_respuesta_wa(texto, parsed, meta), 'reglas_hilorama_v3'
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return _fallback_respuesta_wa(texto, parsed, meta), 'fallback_sin_openai'
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '90')))
        system = (
            'Eres asistente de ventas de Hilorama, mercería mexicana. Responde natural y breve por WhatsApp. '
            'No inventes productos, códigos, stock ni precios. Si no sabes, pregunta un dato concreto. '
            'Si el cliente pregunta por catálogo, envío, pago o disponibilidad, responde como negocio y pide el siguiente dato útil. '
            'Devuelve SOLO JSON válido con claves: respuesta, razon, requiere_humano.'
        )
        payload={'mensaje_cliente': texto, 'contexto': contexto, 'clasificacion': meta}
        resp = client.chat.completions.create(
            model=os.environ.get('OPENAI_SALES_MODEL', os.environ.get('OPENAI_TEXT_MODEL', 'gpt-4o-mini')),
            temperature=0.15, max_tokens=450, response_format={'type':'json_object'},
            messages=[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
        )
        obj=json.loads(resp.choices[0].message.content or '{}')
        respuesta=str(obj.get('respuesta') or '').strip()
        return (respuesta or _fallback_respuesta_wa(texto, parsed, meta)), 'openai'
    except Exception as exc:
        print('WARN WhatsApp IA OpenAI fallback V3:', exc, flush=True)
        return _fallback_respuesta_wa(texto, parsed, meta), 'fallback_error_openai'


# ==========================================================
# WhatsApp IA V4 - reglas comerciales reales por almacén
# ==========================================================
# Correcciones principales:
# - El parser ahora devuelve respuesta_preferida al simulador.
# - Consultas sin cantidad NO agregan productos accidentalmente.
# - Combo/paquete se responde como pregunta comercial, no como producto.
# - Hilos como Velluto, Komfy Mini y Kurumi se detectan aunque el vendedor deje Todas/Todos.
# - Producto externo "La Abuelita" se responde con alternativa humana.

WA_HILO_ALIAS_CANON = {
    'velluto': ['velluto','vellutos','veluto','velutos','alize velluto','alize veluto','alize','chenille velluto','vello','vellos'],
    'komfy': ['komfy','komfy mini','komfymini','komfi','komfi mini','konfy','konfy mini','konfi','comfy','comfy mini','karina komfy','karina komfy mini'],
    'kurumi': ['kurumi','kurumis','karina kurumi'],
    'trapillo': ['trapillo','trapillo kraft','kraft','trapiyo','trapiyos'],
}


def _wa_hilo_family(hilo):
    h = _norm_txt(hilo or '')
    if any(x in h for x in ['velluto','veluto']):
        return 'velluto'
    if any(x in h for x in ['komfy','komfi','konfy','comfy']):
        return 'komfy'
    if 'kurumi' in h:
        return 'kurumi'
    if 'trapillo' in h or 'kraft' in h:
        return 'trapillo'
    return h


def _wa_aliases_hilo(hilo):
    h = _norm_txt(hilo or '')
    aliases = set()
    if h:
        aliases.add(h)
        aliases.add(h.replace(' ', ''))
        aliases.add(h.replace('-', ' '))
    fam = _wa_hilo_family(hilo)
    aliases.update(WA_HILO_ALIAS_CANON.get(fam, []))
    if 'fiorentino' in h or 'fior' in h:
        aliases.update(['fiorentino','florentino','fiorentino karina','fioren'])
    if 'fosfo' in h:
        aliases.update(['fosfo','fosforescente','fluor','neon'])
    return {a for a in aliases if a and len(a) >= 3}


def _wa_detectar_hilos(texto, productos):
    t = _norm_txt(texto or '')
    compacto = t.replace(' ', '')
    if not t:
        return []
    # Primero detecta familias explícitas en el mensaje.
    familias = []
    for fam, aliases in WA_HILO_ALIAS_CANON.items():
        for a in aliases:
            aa = _norm_txt(a)
            if re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t) or aa.replace(' ', '') in compacto:
                familias.append(fam)
                break
    hallados = []
    hilos = _wa_catalogo_hilos(productos)
    for fam in familias:
        for h in hilos:
            if _wa_hilo_family(h) == fam and h not in hallados:
                hallados.append(h)
    # Luego coincide por nombre/alias exacto del catálogo.
    for h in hilos:
        if h in hallados:
            continue
        for a in _wa_aliases_hilo(h):
            aa = _norm_txt(a)
            if re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t) or aa.replace(' ', '') in compacto:
                hallados.append(h)
                break
    return hallados


def _wa_tiene_palabra_pregunta(t):
    return bool(re.search(r'\b(que|qué|cuanto|cuánto|cuesta|precio|vale|tienen|tiene|manejan|maneja|hay|disponible|disponibilidad|colores|tonos|carta|catalogo|catálogo|envio|envío|envios|envíos|puedo|se puede|incluye|sale con|gratis)\b', t or ''))


def _wa_es_consulta_catalogo(texto):
    t = _norm_txt(texto or '')
    # Si no hay cantidad, cualquier pregunta comercial es consulta.
    if not _wa_hay_cantidad(t) and _wa_tiene_palabra_pregunta(t):
        return True
    # Paquetes/combos con pregunta NO son producto para carrito.
    if re.search(r'\b(combo|paquete|kit|promocion|promoción)\b', t) and _wa_tiene_palabra_pregunta(t):
        return True
    return False


def _wa_precio_texto(minp, maxp=None):
    try:
        minp = float(minp or 0)
    except Exception:
        minp = 0
    try:
        maxp = float(maxp or 0)
    except Exception:
        maxp = 0
    if minp <= 0:
        return ''
    if maxp and abs(maxp - minp) > 0.01:
        return f"entre ${minp:.2f} y ${maxp:.2f}"
    return f"en ${minp:.2f}"


def _wa_resumen_hilo(hilo, productos):
    ctx = _wa_filtrar_por_hilo(productos, hilo)
    disponibles = [p for p in ctx if int(p.get('stock') or 0) > 0]
    precios = []
    for p in ctx:
        # Evita que productos tipo combo/surtido distorsionen el precio unitario.
        color = _norm_txt(p.get('color') or '')
        codigo = str(p.get('codigo') or '')
        if any(x in color for x in ['surtido','combo','paquete']) or codigo in {'10','20','40'}:
            continue
        try:
            pr = float(p.get('precio_venta') or 0)
            if pr > 0:
                precios.append(pr)
        except Exception:
            pass
    colores=[]; seen=set()
    for p in disponibles:
        c=(p.get('color') or '').strip()
        cod=str(p.get('codigo') or '').strip()
        if not c and not cod:
            continue
        cn=_norm_txt(c)
        if any(x in cn for x in ['surtido','combo','paquete']):
            continue
        key=(cod, cn)
        if key in seen:
            continue
        seen.add(key)
        colores.append({'codigo':cod,'color':c,'stock':int(p.get('stock') or 0)})
    return {'hilo':hilo,'total':len(ctx),'disponibles':len(disponibles),'precio_min':min(precios) if precios else 0,'precio_max':max(precios) if precios else 0,'colores':colores[:18]}


def _wa_mensaje_externo(t):
    if re.search(r'\b(abuelita|abuelitas|la abuelita)\b', t):
        if 'parecid' in t or 'similar' in t or 'recomiend' in t:
            return 'La Abuelita por el momento no la manejamos 😊 pero puedo ofrecerle opciones parecidas según su proyecto: Kurumi si busca algo más firme/delgado, o Komfy Mini si quiere algo suave tipo chenille. ¿Para qué trabajo lo ocuparía?'
        return 'La Abuelita por el momento no la manejamos 😊 pero sí tengo opciones similares. ¿La busca para amigurumi, tejido o algún proyecto en especial?'
    if re.search(r'\b(karenita|karineta)\b', t):
        return 'Karenita por el momento no la veo en el almacén 😊 pero sí manejamos varios hilos Karina. Si me dice textura o color, le sugiero el más parecido.'
    return ''


def _wa_combo_detectado(t):
    m = re.search(r'\b(?:combo|paquete|kit)\s*(?:de\s*)?(10|20|40)\b', t)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(10|20|40)\s*(?:piezas|pz|pzas|madejas)\b', t)
    if m and re.search(r'\b(combo|paquete|kit)\b', t):
        return int(m.group(1))
    return 0


def _wa_respuesta_combo(t, hilos):
    n = _wa_combo_detectado(t)
    hilo_txt = hilos[0] if hilos else 'Velluto'
    if n:
        if 'escoger' in t or 'elegir' in t or 'colores' in t or 'tonos' in t:
            return f"Sí 😊 el paquete de {n} piezas de {hilo_txt} puede ir con colores a elegir, sujeto a disponibilidad. Mándeme la lista de tonos/códigos y le preparo su nota."
        if 'envio' in t or 'envío' in t or 'gratis' in t:
            return f"Sí 😊 manejamos paquete de {n} piezas de {hilo_txt}. Para confirmarle si aplica envío gratis y dejarlo bien armado, mándeme los tonos o códigos que quiere."
        return f"Sí 😊 manejamos paquete de {n} piezas de {hilo_txt}. Puede elegir sus colores sujeto a disponibilidad."
    return ''


def _wa_respuesta_consulta_almacen(texto, productos, hilos=None, marcas=None):
    t = _norm_txt(texto or '')
    hilos = hilos or []
    marcas = marcas or []
    externo = _wa_mensaje_externo(t)
    if externo:
        return externo
    if _wa_es_pregunta_envio(texto):
        cp = re.search(r'\b\d{5}\b', t)
        if cp:
            return f"Sí hacemos envíos 😊 Con el CP {cp.group(0)} puedo cotizarle las opciones de paquetería."
        return "Sí, hacemos envíos a todo México 😊 Para cotizarle el envío me comparte su código postal, por favor."
    if _wa_es_pregunta_pago(texto):
        return "Perfecto 😊 puede mandarme la imagen del comprobante y reviso que coincida el monto para continuar con su pedido."
    combo_resp = _wa_respuesta_combo(t, hilos)
    if combo_resp:
        return combo_resp
    if hilos:
        bloques=[]
        for h in hilos[:3]:
            r = _wa_resumen_hilo(h, productos)
            if not r['total']:
                continue
            precio = _wa_precio_texto(r.get('precio_min'), r.get('precio_max'))
            if 'precio' in t or 'cuanto' in t or 'cuesta' in t or 'costo' in t or 'vale' in t:
                if precio:
                    bloques.append(f"El {h} está {precio} por madeja 😊 ¿Qué color o código busca?")
                else:
                    bloques.append(f"Sí manejamos {h} 😊 Para darle precio exacto reviso el tono o código que necesita.")
            elif 'color' in t or 'tono' in t or 'disponib' in t or 'catalogo' in t or 'catálogo' in t or 'carta' in t:
                muestra=', '.join([f"{c['codigo']} {c['color']}".strip() for c in r['colores'][:8] if c.get('codigo') or c.get('color')])
                extra=f" Algunos tonos disponibles son: {muestra}." if muestra else ''
                bloques.append(f"Sí 😊 tenemos {h} disponible.{extra}\nLe puedo compartir la carta de colores completa.")
            else:
                bloques.append(f"Sí 😊 manejamos {h}{(' ' + precio) if precio else ''}. ¿Busca algún color o código en especial?")
        if bloques:
            return '\n\n'.join(bloques).strip()
    if marcas:
        bloques=[]
        for m in marcas[:3]:
            r=_wa_resumen_marca(m, productos)
            if r.get('hilos'):
                bloques.append(f"Sí 😊 manejamos {m}. Tenemos por ejemplo: " + ', '.join(r['hilos'][:6]) + ". ¿Cuál buscaba?")
        if bloques:
            return '\n\n'.join(bloques)
    return ''


def _wa_parsear_con_contexto_almacen(texto_total, productos_all, marca='', hilo='', extraer_pedidos_func=None):
    extraer = extraer_pedidos_func
    productos_base = _wa_filtrar_por_marca_hilo(productos_all, marca, hilo)
    texto_norm = _norm_txt(texto_total or '')
    hilos_globales = _wa_detectar_hilos(texto_norm, productos_base)
    marcas_globales = _wa_detectar_marcas(texto_norm, productos_base)
    contexto_global = hilo or (hilos_globales[0] if len(hilos_globales) == 1 else '')
    pedidos_dict = {}
    preguntas=[]; errores=[]; advertencias=[]; sugerencias=[]; hilos_detectados=[]
    respuesta_preferida = ''
    ultimo_hilo = contexto_global
    for h in hilos_globales:
        if h not in hilos_detectados:
            hilos_detectados.append(h)

    # Consulta comercial: no agregues productos aunque aparezcan números de paquetes.
    if _wa_es_consulta_catalogo(texto_norm):
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            return {
                'pedidos_full': [], 'errores': [], 'advertencias': [], 'preguntas': [],
                'sugerencias_almacen': [], 'hilos_detectados': hilos_detectados,
                'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
                'respuesta_preferida': resp,
                'ventas_info': {'tipo': 'consulta_catalogo_v4'}
            }

    clauses = _wa_split_clausulas(texto_norm)
    for idx, parte in enumerate(clauses):
        if not parte:
            continue
        hilos_parte = _wa_detectar_hilos(parte, productos_base)
        marcas_parte = _wa_detectar_marcas(parte, productos_base)
        for h in hilos_parte:
            if h not in hilos_detectados:
                hilos_detectados.append(h)
        if _wa_es_quitar(parte):
            borrados = _wa_remover_por_texto(pedidos_dict, parte, productos_base)
            advertencias.append(f"Se quitaron {borrados} producto(s) por indicación de la clienta." if borrados else "La clienta pidió quitar algo, pero no encontré una coincidencia clara.")
            continue
        if _wa_es_consulta_catalogo(parte):
            resp = _wa_respuesta_consulta_almacen(parte, productos_base, hilos_parte or hilos_globales, marcas_parte or marcas_globales)
            if resp and not pedidos_dict:
                respuesta_preferida = resp
            elif resp:
                advertencias.append(resp)
            continue
        hilo_ctx = hilos_parte[0] if len(hilos_parte) == 1 else (ultimo_hilo or contexto_global)
        if hilo_ctx:
            ultimo_hilo = hilo_ctx
        productos_ctx = _wa_filtrar_por_hilo(productos_base, hilo_ctx) if hilo_ctx else productos_base
        if hilo_ctx and _wa_parece_linea_contexto_hilo(parte) and idx < len(clauses)-1:
            continue
        parse = extraer(parte, productos_ctx) if extraer else {'pedidos': [], 'preguntas': [], 'errores': []}
        full, err = _wa_pedidos_full_desde_parse(parse, productos_ctx)
        for fp in full:
            _wa_agregar_o_sumar(pedidos_dict, fp)
        errores.extend(err)
        errores.extend(parse.get('errores') or [])
        # No uses preguntas del parser cuando ya hubo coincidencia exacta; muchas veces son dudas redundantes.
        if not full:
            preguntas.extend(parse.get('preguntas') or [])
        advertencias.extend(parse.get('advertencias') or [])
        if hilo_ctx and _wa_color_descripcion_keywords(parte):
            descripcion_larga = any(x in parte for x in ['hueso','marfil','amarillent','medio','parecid','calido','piel','crema','nude'])
            if descripcion_larga and not full:
                sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
                if sug:
                    sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                    preguntas.append(f"Para {hilo_ctx}, la clienta describió un tono. Sugiere opciones del almacén y pregunta cuál quiere agregar.")
        if hilo_ctx and not full and _wa_hay_cantidad(parte):
            sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
            if sug:
                sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                preguntas.append(f"Para {hilo_ctx}, falta confirmar cuál tono desea agregar.")
            else:
                m_qty = re.search(r'\b(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|veinte|cuarenta)\b', parte)
                preguntas.append(f"Sí contamos con {hilo_ctx}. Falta confirmar qué tono o código quiere para {m_qty.group(1) if m_qty else ''} pieza(s).")

    if not pedidos_dict and not respuesta_preferida and not preguntas:
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            respuesta_preferida = resp
        else:
            similares = _wa_sugerir_hilos_similares(texto_norm, productos_base, limit=5)
            if similares:
                sugerencias.append({'tipo': 'hilo_similar', 'texto': texto_total, 'opciones': similares})
                preguntas.append('El producto exacto no se identificó en almacén; ofrece alternativas similares por textura.')
    return {
        'pedidos_full': list(pedidos_dict.values()),
        'errores': sorted(set(str(e) for e in errores if e)),
        'advertencias': sorted(set(str(a) for a in advertencias if a)),
        'preguntas': sorted(set(str(p) for p in preguntas if p)),
        'sugerencias_almacen': sugerencias,
        'hilos_detectados': hilos_detectados,
        'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
        'respuesta_preferida': respuesta_preferida,
        'ventas_info': {'tipo': 'pedido_o_conversacion_v4'}
    }


def _fallback_respuesta_wa(texto, parsed, meta):
    if parsed.get('respuesta_preferida'):
        return str(parsed.get('respuesta_preferida')).strip()
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    sug_txt = _formatear_sugerencias_almacen_wa(parsed)
    intent = meta.get('intencion')
    provisionales = _codigos_provisionales_desde_preguntas(preguntas)
    pedidos_confirmados = [p for p in pedidos if (str(p.get('codigo') or '').strip().lstrip('0') or '0') not in provisionales]
    if errores:
        txt=''
        if pedidos_confirmados:
            txt += 'Claro 😊 ya tengo claro esto:\n' + '\n'.join(_formatear_producto_wa(p) for p in pedidos_confirmados[:25]) + '\n\n'
        txt += 'Estos códigos no me aparecen en catálogo: ' + ', '.join(map(str, errores[:8])) + '. ¿Me los confirma por favor?'
        return txt
    if preguntas:
        q_limpias=[_limpiar_pregunta_wa(q) for q in preguntas if _limpiar_pregunta_wa(q)]
        txt=''
        if pedidos_confirmados:
            txt += 'Claro 😊 ya tengo claro:\n' + '\n'.join(_formatear_producto_wa(p) for p in pedidos_confirmados[:25]) + '\n\n'
        if sug_txt:
            txt += sug_txt + '\n\n¿Cuál de esos tonos le agrego?'
        elif q_limpias:
            txt += 'Solo para confirmar 😊 ' + q_limpias[0]
        else:
            txt += 'Solo necesito confirmar un detalle para no agregarle algo equivocado 😊'
        return txt.strip()
    if sug_txt and not pedidos:
        return sug_txt + '\n\n¿Quiere que le arme una opción con alguno de esos tonos?'
    if pedidos:
        lineas=[_formatear_producto_wa(p) for p in pedidos[:40]]
        txt='Claro 😊 le agrego:\n' + '\n'.join(lineas)
        if len(pedidos)>40:
            txt += f"\nY {len(pedidos)-40} producto(s) más."
        txt += '\n\nLe preparo su cotización.'
        return txt
    if intent == 'pregunta_precio':
        return 'Claro 😊 ¿me confirma qué hilo o código quiere revisar? Así le doy precio y disponibilidad exacta.'
    if intent == 'pregunta_envio':
        return 'Sí, hacemos envíos a todo México 😊 Para cotizarlo necesito su código postal.'
    if intent == 'pregunta_stock':
        return 'Con gusto 😊 dígame el hilo, código o color que busca y reviso disponibilidad.'
    if intent == 'sugerir_tonos':
        return 'Sí 😊 mándeme la foto o referencia y le sugiero los tonos más parecidos según lo que tenga disponible. No agrego nada hasta que usted confirme.'
    if intent == 'comprobante_pago':
        return 'Perfecto 😊 mándeme la imagen del comprobante y reviso monto, referencia y datos para continuar con su pedido.'
    return 'Claro 😊 dígame qué hilo, código o color necesita y le ayudo a armar su cotización.'


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    # V4: las respuestas comerciales se hacen con reglas y almacén para no inventar.
    if (parsed.get('pedidos') or parsed.get('preguntas') or parsed.get('errores') or parsed.get('respuesta_preferida') or parsed.get('sugerencias_almacen')):
        return _fallback_respuesta_wa(texto, parsed, meta), 'reglas_hilorama_v4'
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return _fallback_respuesta_wa(texto, parsed, meta), 'fallback_sin_openai'
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '90')))
        system = (
            'Eres asistente de ventas de Hilorama, mercería mexicana. Responde natural, breve y útil por WhatsApp. '
            'No inventes productos, códigos, stock ni precios. Si no sabes, pregunta un dato concreto. '
            'No digas que no sabes si el almacén ya confirmó información. Devuelve SOLO JSON válido con claves: respuesta, razon, requiere_humano.'
        )
        payload={'mensaje_cliente': texto, 'contexto': contexto, 'clasificacion': meta}
        resp = client.chat.completions.create(
            model=os.environ.get('OPENAI_SALES_MODEL', os.environ.get('OPENAI_TEXT_MODEL', 'gpt-4o-mini')),
            temperature=0.1, max_tokens=350, response_format={'type':'json_object'},
            messages=[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
        )
        obj=json.loads(resp.choices[0].message.content or '{}')
        respuesta=str(obj.get('respuesta') or '').strip()
        return (respuesta or _fallback_respuesta_wa(texto, parsed, meta)), 'openai'
    except Exception as exc:
        print('WARN WhatsApp IA OpenAI fallback V4:', exc, flush=True)
        return _fallback_respuesta_wa(texto, parsed, meta), 'fallback_error_openai'


# ==========================================================
# WhatsApp IA V5 - resolver comercial por familia/hilo real
# ==========================================================
# Corrige casos detectados en pruebas reales:
# - Komfy Mini no debe mezclarse con Velluto/Kairo.
# - Consultas de Komfy Mini/Kurumi deben detectarse aunque el selector esté en Todas/Todos.
# - Combos/paquetes con envío no deben caer en pregunta genérica de CP antes de responder el paquete.
# - Pedidos por color usan primero el hilo mencionado y después el color más parecido dentro de ese hilo.

WA_HILO_ALIAS_CANON = {
    'velluto': ['velluto','vellutos','veluto','velutos','alize velluto','alize veluto','alize','chenille velluto','vello','vellos'],
    'komfy_mini': ['komfy mini','komfymini','komfi mini','konfy mini','konfi mini','comfy mini','karina komfy mini','karina komfi mini','komfy','komfi','konfy','konfi','comfy'],
    'kurumi': ['kurumi','kurumis','karina kurumi'],
    'trapillo': ['trapillo','trapillo kraft','kraft','trapiyo','trapiyos'],
}


def _wa_hilo_family(hilo):
    h = _norm_txt(hilo or '')
    compacto = h.replace(' ', '')
    if 'velluto' in h or 'veluto' in h or ('alize' in h and 'velluto' in h):
        return 'velluto'
    if 'komfy' in h or 'komfi' in h or 'konfy' in h or 'comfy' in h or 'komfymini' in compacto or 'komfimini' in compacto:
        return 'komfy_mini'
    if 'kurumi' in h or 'kurumi' in compacto:
        return 'kurumi'
    if 'trapillo' in h or 'kraft' in h:
        return 'trapillo'
    return h


def _wa_hilo_es_mejor_para_familia(hilo, fam, texto=''):
    h = _norm_txt(hilo or '')
    t = _norm_txt(texto or '')
    score = 0
    if _wa_hilo_family(hilo) == fam:
        score += 100
    if fam == 'komfy_mini':
        if 'mini' in h:
            score += 30
        if 'komfy mini' in t or 'komfi mini' in t or 'konfy mini' in t or 'comfy mini' in t:
            if 'mini' in h:
                score += 50
        # Si existe HILO exacto KOMFY MINI, debe vencer a KOMFY o otros hilos parecidos.
        if h in {'komfy mini','karina komfy mini'}:
            score += 100
        if h == 'komfy':
            score -= 25
    if fam == 'velluto':
        if h == 'velluto':
            score += 100
        if 'alize velluto' in h:
            score += 60
    if fam == 'kurumi':
        if h == 'kurumi':
            score += 100
        if 'kurumi' in h:
            score += 50
    return score


def _wa_dedup_hilos_por_familia(hilos, texto=''):
    grupos = {}
    for h in hilos or []:
        fam = _wa_hilo_family(h)
        if not fam:
            continue
        score = _wa_hilo_es_mejor_para_familia(h, fam, texto)
        current = grupos.get(fam)
        if current is None or score > current[1]:
            grupos[fam] = (h, score)
    out = []
    for h, _score in grupos.values():
        if h not in out:
            out.append(h)
    return out


def _wa_detectar_hilos(texto, productos):
    t = _norm_txt(texto or '')
    compacto = t.replace(' ', '')
    if not t:
        return []

    familias = []
    for fam, aliases in WA_HILO_ALIAS_CANON.items():
        for a in aliases:
            aa = _norm_txt(a)
            aac = aa.replace(' ', '')
            if re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t) or (len(aac) >= 5 and aac in compacto):
                if fam not in familias:
                    familias.append(fam)
                break

    hilos = _wa_catalogo_hilos(productos)
    hallados = []
    for fam in familias:
        candidatos = [h for h in hilos if _wa_hilo_family(h) == fam]
        candidatos = sorted(candidatos, key=lambda h: _wa_hilo_es_mejor_para_familia(h, fam, t), reverse=True)
        if candidatos and candidatos[0] not in hallados:
            hallados.append(candidatos[0])

    # Match exacto adicional por nombre real del hilo.
    for h in hilos:
        hn = _norm_txt(h)
        hnc = hn.replace(' ', '')
        if h in hallados:
            continue
        if (hn and re.search(rf'(?<!\w){re.escape(hn)}(?!\w)', t)) or (len(hnc) >= 5 and hnc in compacto):
            hallados.append(h)

    return _wa_dedup_hilos_por_familia(hallados, t)


def _wa_filtrar_por_hilo(productos, hilo):
    if not hilo:
        return list(productos or [])
    hn = _norm_txt(hilo)
    fam = _wa_hilo_family(hilo)
    exactos = [p for p in (productos or []) if _norm_txt(p.get('hilo') or '') == hn]
    if exactos:
        return exactos
    if fam:
        fams = [p for p in (productos or []) if _wa_hilo_family(p.get('hilo') or '') == fam]
        if fams:
            return fams
    return []


def _wa_token_qty_v5(token):
    if token is None:
        return None
    s = _norm_txt(str(token))
    if s.isdigit():
        try:
            return int(s)
        except Exception:
            return None
    return WA_QTY_WORDS.get(s)


def _wa_quitar_hilo_del_texto(texto, hilos):
    t = _norm_txt(texto or '')
    for h in hilos or []:
        for a in sorted(_wa_aliases_hilo(h), key=len, reverse=True):
            aa = _norm_txt(a)
            if len(aa) >= 3:
                t = re.sub(rf'(?<!\w){re.escape(aa)}(?!\w)', ' ', t)
                t = t.replace(aa.replace(' ', ''), ' ')
    return re.sub(r'\s+', ' ', t).strip()


def _wa_color_score_producto(producto, texto_color, grupo=None):
    color = _norm_txt(producto.get('color') or '')
    codigo = str(producto.get('codigo') or '').strip()
    t = _norm_txt(texto_color or '')
    if not color:
        return -999
    score = 0
    if codigo and re.search(rf'(?<!\d){re.escape(codigo)}(?!\d)', t):
        score += 200
    # Limpia palabras que no son color.
    t_clean = re.sub(r'\b(de|del|la|el|los|las|pieza|piezas|pz|pzas|madeja|madejas|uno|una|un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|quiero|dame|ocupo|agrega|agregame)\b', ' ', t)
    t_clean = re.sub(r'\s+', ' ', t_clean).strip()
    if t_clean:
        if color == t_clean:
            score += 150
        if t_clean in color:
            score += 110
        words = [w for w in t_clean.split() if len(w) > 1]
        if words and all(w in color for w in words):
            score += 90
        if words and any(w in color for w in words):
            score += 45
    # Alias por grupo de color, pero con menor peso que el nombre exacto.
    if grupo:
        aliases = [_norm_txt(a) for a in COLOR_GRUPOS.get(grupo, [])]
        # Si la clienta dijo rosa, preferir color que tenga ROSA sobre FUCsia.
        if grupo == 'rosa' and 'rosa' in t:
            if 'rosa' in color:
                score += 80
            elif 'fucsia' in color or 'fiusha' in color or 'fuc' in color:
                score += 15
        elif grupo == 'rojo' and 'rojo escolar' in t:
            if 'rojo escolar' in color:
                score += 120
            elif 'rojo' in color:
                score += 45
        elif grupo == 'negro' and 'negro' in t:
            if color == 'negro' or 'negro' in color:
                score += 100
        else:
            if any(a and a in color for a in aliases):
                score += 40
    try:
        if int(producto.get('stock') or 0) > 0:
            score += 8
    except Exception:
        pass
    return score


def _wa_resolver_producto_por_color(productos_ctx, texto_color):
    grupos = _wa_color_descripcion_keywords(texto_color) or _color_canon(texto_color)
    t = _norm_txt(texto_color or '')
    # Código exacto dentro del contexto.
    codigos = re.findall(r'(?<!\d)\d{1,4}(?!\d)', t)
    for cod in codigos:
        matches = [p for p in productos_ctx if str(p.get('codigo') or '').strip().lstrip('0') == str(cod).lstrip('0')]
        if matches:
            return sorted(matches, key=lambda p: int(p.get('stock') or 0), reverse=True)[0], []
    candidatos = []
    for p in productos_ctx or []:
        # Evita combos/paquetes/surtidos como tono normal.
        cn = _norm_txt(p.get('color') or '')
        if any(x in cn for x in ['surtido','combo','paquete']):
            continue
        best = max([_wa_color_score_producto(p, t, g) for g in (grupos or [None])])
        if best > 0:
            candidatos.append((best, p))
    candidatos.sort(key=lambda x: x[0], reverse=True)
    if not candidatos:
        return None, []
    # Si hay un ganador claro, usarlo. Si no, preguntar con opciones.
    top_score, top = candidatos[0]
    opciones = [p for _s, p in candidatos[:5]]
    if len(candidatos) == 1 or top_score >= 100 or (len(candidatos) > 1 and top_score - candidatos[1][0] >= 35):
        return top, opciones
    return None, opciones


def _wa_extraer_pedidos_simples_v5(texto, productos_base, hilos_globales, hilo_actual=''):
    pedidos = []
    preguntas = []
    advertencias = []
    ultimo_hilo = hilo_actual or (hilos_globales[0] if len(hilos_globales) == 1 else '')
    clauses = _wa_split_clausulas(texto)
    qty_pat = r'(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|veinte|treinta|cuarenta)'
    for parte in clauses:
        if not parte or _wa_es_quitar(parte) or _wa_es_consulta_catalogo(parte):
            continue
        hilos_parte = _wa_detectar_hilos(parte, productos_base)
        if hilos_parte:
            ultimo_hilo = hilos_parte[0]
        hilo_ctx = ultimo_hilo
        productos_ctx = _wa_filtrar_por_hilo(productos_base, hilo_ctx) if hilo_ctx else productos_base
        # Detecta pares cantidad + descripción/código. Ej: 3 Komfy Mini negro / 2 rosa / 1 rojo escolar.
        matches = list(re.finditer(rf'(?<!\w){qty_pat}(?!\w)\s+(?:de\s+|del\s+)?([^,;]+?)(?=(?:\s+y\s+{qty_pat}\b)|$)', parte))
        if not matches:
            continue
        for m in matches:
            qty = _wa_token_qty_v5(m.group(1)) or 1
            desc = (m.group(2) or '').strip()
            desc_sin_hilo = _wa_quitar_hilo_del_texto(desc, hilos_parte or ([hilo_ctx] if hilo_ctx else []))
            # Si la descripción quedó casi vacía, falta tono/código.
            if not desc_sin_hilo or _norm_txt(desc_sin_hilo) in {'pieza','piezas','pz','pzas','madeja','madejas'}:
                if hilo_ctx:
                    preguntas.append(f"Sí contamos con {hilo_ctx}. Falta confirmar qué tono o código quiere para {qty} pieza(s).")
                continue
            prod, opciones = _wa_resolver_producto_por_color(productos_ctx, desc_sin_hilo)
            if prod:
                pedidos.append({
                    'producto_id': prod.get('id'),
                    'codigo': prod.get('codigo'),
                    'marca': prod.get('marca') or '',
                    'hilo': prod.get('hilo') or '',
                    'color': prod.get('color') or '',
                    'stock': int(prod.get('stock') or 0),
                    'precio_venta': float(prod.get('precio_venta') or 0),
                    'cantidad': int(qty),
                    'es_inventariable': prod.get('es_inventariable', True),
                })
            elif opciones:
                opts = ', '.join([f"{p.get('codigo')} {p.get('color')}".strip() for p in opciones[:4]])
                preguntas.append(f"Para {hilo_ctx or 'ese hilo'}, '{desc_sin_hilo}' tiene varias opciones: {opts}. ¿Cuál le agrego?")
            elif hilo_ctx:
                preguntas.append(f"Sí contamos con {hilo_ctx}. No ubiqué exacto '{desc_sin_hilo}', ¿me confirma código o tono?")
    return pedidos, preguntas, advertencias


def _wa_respuesta_combo(t, hilos):
    n = _wa_combo_detectado(t)
    hilo_txt = hilos[0] if hilos else ('Velluto' if 'velluto' in _norm_txt(t) or 'veluto' in _norm_txt(t) else 'el hilo')
    if n:
        if 'envio' in t or 'envío' in t or 'gratis' in t:
            return f"Sí 😊 el paquete de {n} piezas de {hilo_txt} se puede manejar con colores a elegir, sujeto a disponibilidad. Para confirmar envío gratis/paquetería, mándeme su lista de tonos o códigos y su código postal."
        if 'escoger' in t or 'elegir' in t or 'colores' in t or 'tonos' in t:
            return f"Sí 😊 el paquete de {n} piezas de {hilo_txt} puede ir con colores a elegir, sujeto a disponibilidad. Mándeme la lista de tonos/códigos y le preparo su nota."
        return f"Sí 😊 manejamos paquete de {n} piezas de {hilo_txt}. Puede elegir sus colores sujeto a disponibilidad."
    return ''


def _wa_respuesta_consulta_almacen(texto, productos, hilos=None, marcas=None):
    t = _norm_txt(texto or '')
    hilos = _wa_dedup_hilos_por_familia(hilos or [], t)
    marcas = marcas or []
    externo = _wa_mensaje_externo(t)
    if externo:
        return externo
    # Primero combos/paquetes; si se revisa envío después, la respuesta debe seguir siendo del paquete.
    combo_resp = _wa_respuesta_combo(t, hilos)
    if combo_resp:
        return combo_resp
    if _wa_es_pregunta_envio(texto):
        cp = re.search(r'\b\d{5}\b', t)
        if cp:
            return f"Sí hacemos envíos 😊 Con el CP {cp.group(0)} puedo cotizarle las opciones de paquetería."
        return "Sí, hacemos envíos a todo México 😊 Para cotizarle el envío me comparte su código postal, por favor."
    if _wa_es_pregunta_pago(texto):
        return "Perfecto 😊 puede mandarme la imagen del comprobante y reviso que coincida el monto para continuar con su pedido."
    if hilos:
        bloques=[]
        for h in hilos[:2]:
            r = _wa_resumen_hilo(h, productos)
            if not r['total']:
                continue
            precio = _wa_precio_texto(r.get('precio_min'), r.get('precio_max'))
            nombre = h
            if 'precio' in t or 'cuanto' in t or 'cuesta' in t or 'costo' in t or 'vale' in t:
                if precio:
                    bloques.append(f"El {nombre} está {precio} por madeja 😊 ¿Qué color o código busca?")
                else:
                    bloques.append(f"Sí manejamos {nombre} 😊 Para darle precio exacto reviso el tono o código que necesita.")
            elif 'color' in t or 'tono' in t or 'disponib' in t or 'catalogo' in t or 'catálogo' in t or 'carta' in t:
                muestra = ', '.join([f"{c['codigo']} {c['color']}".strip() for c in r['colores'][:8] if c.get('codigo') or c.get('color')])
                extra = f" Algunos tonos disponibles son: {muestra}." if muestra else ''
                bloques.append(f"Sí 😊 tenemos {nombre} disponible.{extra}\nLe puedo compartir la carta de colores completa.")
            else:
                bloques.append(f"Sí 😊 manejamos {nombre}{(' ' + precio) if precio else ''}. ¿Busca algún color o código en especial?")
        if bloques:
            return '\n\n'.join(bloques).strip()
    if marcas:
        bloques=[]
        for m in marcas[:2]:
            r=_wa_resumen_marca(m, productos)
            if r.get('hilos'):
                bloques.append(f"Sí 😊 manejamos {m}. Tenemos por ejemplo: " + ', '.join(r['hilos'][:6]) + ". ¿Cuál buscaba?")
        if bloques:
            return '\n\n'.join(bloques)
    return ''


def _wa_parsear_con_contexto_almacen(texto_total, productos_all, marca='', hilo='', extraer_pedidos_func=None):
    extraer = extraer_pedidos_func
    productos_base = _wa_filtrar_por_marca_hilo(productos_all, marca, hilo)
    texto_norm = _norm_txt(texto_total or '')
    hilos_globales = _wa_detectar_hilos(texto_norm, productos_base)
    marcas_globales = _wa_detectar_marcas(texto_norm, productos_base)
    contexto_global = hilo or (hilos_globales[0] if len(hilos_globales) == 1 else '')
    pedidos_dict = {}
    preguntas=[]; errores=[]; advertencias=[]; sugerencias=[]; hilos_detectados=[]
    respuesta_preferida = ''
    for h in hilos_globales:
        if h not in hilos_detectados:
            hilos_detectados.append(h)

    # Consulta comercial: jamás convertir paquetes/consultas en producto de carrito.
    if _wa_es_consulta_catalogo(texto_norm):
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            return {
                'pedidos_full': [], 'errores': [], 'advertencias': [], 'preguntas': [],
                'sugerencias_almacen': [], 'hilos_detectados': hilos_detectados,
                'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
                'respuesta_preferida': resp,
                'ventas_info': {'tipo': 'consulta_catalogo_v5'}
            }

    # Resolución propia por familia/hilo para evitar mezclar Velluto/Kairo/Komfy.
    pedidos_v5, preguntas_v5, advertencias_v5 = _wa_extraer_pedidos_simples_v5(texto_norm, productos_base, hilos_globales, contexto_global)
    for fp in pedidos_v5:
        _wa_agregar_o_sumar(pedidos_dict, fp)
    preguntas.extend(preguntas_v5)
    advertencias.extend(advertencias_v5)

    # Si V5 ya resolvió productos, no dejar que el parser viejo agregue de otros hilos.
    if pedidos_dict:
        return {
            'pedidos_full': list(pedidos_dict.values()),
            'errores': [],
            'advertencias': sorted(set(str(a) for a in advertencias if a)),
            'preguntas': sorted(set(str(p) for p in preguntas if p)),
            'sugerencias_almacen': sugerencias,
            'hilos_detectados': hilos_detectados,
            'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
            'respuesta_preferida': '',
            'ventas_info': {'tipo': 'pedido_v5_familia_hilo'}
        }

    # Si no resolvió nada, usa el flujo anterior pero con hilos deduplicados.
    clauses = _wa_split_clausulas(texto_norm)
    ultimo_hilo = contexto_global
    for idx, parte in enumerate(clauses):
        if not parte:
            continue
        hilos_parte = _wa_detectar_hilos(parte, productos_base)
        marcas_parte = _wa_detectar_marcas(parte, productos_base)
        for h in hilos_parte:
            if h not in hilos_detectados:
                hilos_detectados.append(h)
        if _wa_es_quitar(parte):
            borrados = _wa_remover_por_texto(pedidos_dict, parte, productos_base)
            advertencias.append(f"Se quitaron {borrados} producto(s) por indicación de la clienta." if borrados else "La clienta pidió quitar algo, pero no encontré una coincidencia clara.")
            continue
        if _wa_es_consulta_catalogo(parte):
            resp = _wa_respuesta_consulta_almacen(parte, productos_base, hilos_parte or hilos_globales, marcas_parte or marcas_globales)
            if resp and not pedidos_dict:
                respuesta_preferida = resp
            elif resp:
                advertencias.append(resp)
            continue
        hilo_ctx = hilos_parte[0] if len(hilos_parte) == 1 else (ultimo_hilo or contexto_global)
        if hilo_ctx:
            ultimo_hilo = hilo_ctx
        productos_ctx = _wa_filtrar_por_hilo(productos_base, hilo_ctx) if hilo_ctx else productos_base
        if hilo_ctx and _wa_parece_linea_contexto_hilo(parte) and idx < len(clauses)-1:
            continue
        parse = extraer(parte, productos_ctx) if extraer else {'pedidos': [], 'preguntas': [], 'errores': []}
        full, err = _wa_pedidos_full_desde_parse(parse, productos_ctx)
        for fp in full:
            _wa_agregar_o_sumar(pedidos_dict, fp)
        errores.extend(err)
        errores.extend(parse.get('errores') or [])
        if not full:
            preguntas.extend(parse.get('preguntas') or [])
        advertencias.extend(parse.get('advertencias') or [])
        if hilo_ctx and _wa_color_descripcion_keywords(parte):
            descripcion_larga = any(x in parte for x in ['hueso','marfil','amarillent','medio','parecid','calido','piel','crema','nude'])
            if descripcion_larga and not full:
                sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
                if sug:
                    sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                    preguntas.append(f"Para {hilo_ctx}, la clienta describió un tono. Sugiere opciones del almacén y pregunta cuál quiere agregar.")
        if hilo_ctx and not full and _wa_hay_cantidad(parte):
            sug = _wa_sugerir_tonos_por_descripcion(parte, productos_ctx, limit=5)
            if sug:
                sugerencias.append({'tipo': 'tonos_por_descripcion', 'hilo': hilo_ctx, 'texto': parte, 'opciones': sug})
                preguntas.append(f"Para {hilo_ctx}, falta confirmar cuál tono desea agregar.")
            else:
                m_qty = re.search(r'\b(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|veinte|cuarenta)\b', parte)
                preguntas.append(f"Sí contamos con {hilo_ctx}. Falta confirmar qué tono o código quiere para {m_qty.group(1) if m_qty else ''} pieza(s).")

    if not pedidos_dict and not respuesta_preferida and not preguntas:
        resp = _wa_respuesta_consulta_almacen(texto_norm, productos_base, hilos_globales, marcas_globales)
        if resp:
            respuesta_preferida = resp
        else:
            similares = _wa_sugerir_hilos_similares(texto_norm, productos_base, limit=5)
            if similares:
                sugerencias.append({'tipo': 'hilo_similar', 'texto': texto_total, 'opciones': similares})
                preguntas.append('El producto exacto no se identificó en almacén; ofrece alternativas similares por textura.')
    return {
        'pedidos_full': list(pedidos_dict.values()),
        'errores': sorted(set(str(e) for e in errores if e)),
        'advertencias': sorted(set(str(a) for a in advertencias if a)),
        'preguntas': sorted(set(str(p) for p in preguntas if p)),
        'sugerencias_almacen': sugerencias,
        'hilos_detectados': hilos_detectados,
        'contexto_inferido': {'marca': marca or '', 'hilo': hilo or contexto_global or '', 'hilos_mencionados': hilos_globales, 'marcas_mencionadas': marcas_globales},
        'respuesta_preferida': respuesta_preferida,
        'ventas_info': {'tipo': 'pedido_o_conversacion_v5'}
    }


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    # V5: primero reglas y almacén. OpenAI solo para conversación libre sin datos resueltos.
    if (parsed.get('pedidos') or parsed.get('preguntas') or parsed.get('errores') or parsed.get('respuesta_preferida') or parsed.get('sugerencias_almacen')):
        return _fallback_respuesta_wa(texto, parsed, meta), 'reglas_hilorama_v5'
    return _fallback_respuesta_wa(texto, parsed, meta), 'reglas_hilorama_v5_base'


# ==========================================================
# WhatsApp IA V6 - cerebro comercial basado en almacén real
# ==========================================================
# Esta capa final reemplaza la lógica V5 en tiempo de ejecución.
# Objetivo: NO mezclar hilos, NO convertir consultas en pedidos,
# responder como vendedor humano y usar el almacén como fuente de verdad.

V6_QTY_WORDS = {
    'un': 1, 'uno': 1, 'una': 1, 'unos': 1, 'unas': 1,
    'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6,
    'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10, 'once': 11,
    'doce': 12, 'trece': 13, 'catorce': 14, 'quince': 15,
    'dieciseis': 16, 'dieciséis': 16, 'veinte': 20, 'treinta': 30,
    'cuarenta': 40, 'cincuenta': 50,
}

V6_HILO_FALLBACK_PRICE = {
    'velluto': 59.99,
    'komfy_mini': 28.99,
    'kurumi': 25.99,
}

V6_COMBOS_VELLUTO = {
    10: 690,
    20: 1250,
    40: 2400,
}

V6_COLOR_GROUPS_EXTRA = {
    'negro': ['negro', 'negra', 'black', 'negros', 'oscurito'],
    'blanco': ['blanco', 'blanca', 'white', 'whit', 'hueso', 'marfil', 'ivory', 'crudo', 'cream', 'crema', 'beige clarito'],
    'hueso': ['hueso', 'marfil', 'ivory', 'crudo', 'cream', 'crema', 'amarillento', 'amarillentito', 'medio amarillo', 'blanco calido', 'blanco cálido'],
    'rosa': ['rosa', 'rosita', 'rosa bte', 'rosa bb', 'pink', 'sandia', 'sandía'],
    'rojo_escolar': ['rojo escolar', 'rojo esc', 'rojo fuerte', 'rojo bandera'],
    'rojo': ['rojo', 'roja', 'red'],
    'verde': ['verde', 'green', 'bandera', 'chicharo', 'chícharo', 'pistache', 'limon', 'limón', 'olivo'],
    'azul': ['azul', 'blue', 'cielo', 'celeste', 'turquesa', 'pepsi', 'marino'],
    'amarillo': ['amarillo', 'yellow', 'mango', 'mimosa', 'canario', 'oro', 'marigold', 'mostaza'],
    'naranja': ['naranja', 'orange', 'mirinda', 'mandarina'],
    'cafe': ['cafe', 'café', 'brown', 'tabaco', 'camello', 'arena', 'ladrillo', 'beige', 'camel'],
    'morado': ['morado', 'lila', 'lilac', 'purple', 'lavanda', 'violeta'],
    'gris': ['gris', 'plata', 'gray', 'grey', 'oxford'],
}


def _v6_norm(v):
    try:
        return _norm_txt(v or '')
    except Exception:
        v = (v or '').strip().lower()
        return ''.join(c for c in unicodedata.normalize('NFD', v) if unicodedata.category(c) != 'Mn')


def _v6_hilo_family(hilo):
    h = _v6_norm(hilo)
    compact = h.replace(' ', '')
    if 'komfymini' in compact or 'komfimini' in compact or 'konfymini' in compact or 'comfymini' in compact:
        return 'komfy_mini'
    if 'komfy' in h or 'komfi' in h or 'konfy' in h or 'comfy' in h:
        # Si el nombre real del catálogo solo dice KOMFY, también lo agrupamos, pero
        # al detectar texto explícito "komfy mini" se preferirá el HILO exacto KOMFY MINI.
        return 'komfy_mini'
    if 'velluto' in h or 'veluto' in h or 'vello' in h or 'alize' in h:
        return 'velluto'
    if 'kurumi' in h:
        return 'kurumi'
    if 'trapillo' in h or 'kraft' in h:
        return 'trapillo'
    if 'kairo' in h:
        return 'kairo'
    if 'fiorentino' in h:
        return 'fiorentino'
    if 'fosfo' in h:
        return 'fosfo'
    return h


def _v6_hilo_display(hilo):
    fam = _v6_hilo_family(hilo)
    if fam == 'velluto':
        return 'Velluto'
    if fam == 'komfy_mini':
        return 'Komfy Mini'
    if fam == 'kurumi':
        return 'Kurumi'
    if fam == 'trapillo':
        return 'Trapillo'
    return (hilo or '').title()


def _v6_producto_linea(p):
    hilo = _v6_hilo_display(p.get('hilo') or '')
    codigo = str(p.get('codigo') or '').strip()
    color = str(p.get('color') or '').strip()
    cantidad = int(p.get('cantidad') or 1)
    base = ' '.join(x for x in [hilo, codigo, color] if x)
    return f"- {base} x{cantidad}"


def _v6_all_hilos(productos):
    out = []
    seen = set()
    for p in productos or []:
        h = str(p.get('hilo') or '').strip()
        if not h:
            continue
        key = _v6_norm(h)
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def _v6_best_hilo_for_family(productos, fam, texto=''):
    hilos = _v6_all_hilos(productos)
    t = _v6_norm(texto)
    candidates = [h for h in hilos if _v6_hilo_family(h) == fam]
    if not candidates:
        return ''
    def score(h):
        hn = _v6_norm(h)
        s = 0
        if fam == 'komfy_mini':
            if hn == 'komfy mini':
                s += 200
            if 'mini' in hn:
                s += 80
            if 'komfy mini' in t or 'komfi mini' in t or 'konfy mini' in t or 'comfy mini' in t:
                if 'mini' in hn:
                    s += 200
                elif hn == 'komfy':
                    s -= 60
            if hn == 'komfy':
                s -= 10
        elif fam == 'velluto':
            if hn == 'velluto':
                s += 200
            if 'velluto' in hn:
                s += 120
            if 'alize' in hn:
                s += 20
        elif fam == 'kurumi':
            if hn == 'kurumi':
                s += 200
            if 'kurumi' in hn:
                s += 100
        elif fam == 'kairo':
            if hn == 'kairo':
                s += 200
        return s
    return sorted(candidates, key=score, reverse=True)[0]


def _v6_detect_hilos(texto, productos):
    t = _v6_norm(texto)
    found = []
    rules = [
        ('komfy_mini', [r'komfy\s*mini', r'komfi\s*mini', r'konfy\s*mini', r'comfy\s*mini', r'komfymini', r'komfimini', r'konfymini', r'komfy', r'komfi', r'konfy', r'comfy']),
        ('velluto', [r'alize\s+velluto', r'alize\s+veluto', r'\bvellutos?\b', r'\bvelutos?\b', r'\bvello\b', r'\balize\b']),
        ('kurumi', [r'\bkurumi\b', r'\bkurumis\b']),
        ('trapillo', [r'\btrapillo\b', r'\btrapillo\s+kraft\b', r'\bkraft\b']),
        ('kairo', [r'\bkairo\b']),
        ('fiorentino', [r'\bfiorentino\b', r'\bflorentino\b']),
        ('fosfo', [r'\bfosfo\b', r'\bneon\b', r'\bneón\b']),
    ]
    for fam, pats in rules:
        if any(re.search(p, t) for p in pats):
            h = _v6_best_hilo_for_family(productos, fam, t)
            if h and h not in found:
                found.append(h)
    return found


def _v6_products_for_hilo(productos, hilo):
    if not hilo:
        return list(productos or [])
    hn = _v6_norm(hilo)
    exact = [p for p in productos or [] if _v6_norm(p.get('hilo') or '') == hn]
    if exact:
        return exact
    fam = _v6_hilo_family(hilo)
    return [p for p in productos or [] if _v6_hilo_family(p.get('hilo') or '') == fam]


def _v6_code_map(productos):
    mp = {}
    for p in productos or []:
        c = str(p.get('codigo') or '').strip()
        if not c:
            continue
        key = c.lstrip('0') or c
        mp.setdefault(key, []).append(p)
    return mp


def _v6_choose_by_code(productos, codigo, hilo_ctx=''):
    key = str(codigo or '').strip().lstrip('0') or str(codigo or '').strip()
    matches = _v6_code_map(productos).get(key) or []
    if not matches:
        return None, []
    if hilo_ctx:
        ctx = _v6_products_for_hilo(matches, hilo_ctx)
        if ctx:
            matches = ctx
    # Evitar combos/surtidos si el código también existe como tono normal.
    normales = [p for p in matches if not any(x in _v6_norm(p.get('color') or '') for x in ['combo', 'paquete', 'surtido'])]
    if normales:
        matches = normales
    return sorted(matches, key=lambda p: int(p.get('stock') or 0), reverse=True)[0], matches


def _v6_price_range(productos, fam=None):
    vals = []
    for p in productos or []:
        try:
            val = float(p.get('precio_venta') or 0)
        except Exception:
            val = 0
        if val > 0:
            vals.append(val)
    if not vals and fam in V6_HILO_FALLBACK_PRICE:
        vals = [V6_HILO_FALLBACK_PRICE[fam]]
    if not vals:
        return None, None
    return min(vals), max(vals)


def _v6_price_text(productos, fam=None):
    mn, mx = _v6_price_range(productos, fam)
    if mn is None:
        return ''
    if abs(mn - mx) < 0.01:
        return f"${mn:,.2f}"
    return f"desde ${mn:,.2f}"


def _v6_color_groups(texto):
    t = _v6_norm(texto)
    found = []
    merged = {}
    try:
        for k, v in COLOR_GRUPOS.items():
            merged.setdefault(k, []).extend(v)
    except Exception:
        pass
    for k, v in V6_COLOR_GROUPS_EXTRA.items():
        merged.setdefault(k, []).extend(v)
    for group, aliases in merged.items():
        for a in aliases:
            aa = _v6_norm(a)
            if aa and (re.search(rf'(?<!\w){re.escape(aa)}(?!\w)', t) or (len(aa) >= 5 and aa in t)):
                if group not in found:
                    found.append(group)
                break
    return found


def _v6_color_score(producto, desc):
    color = _v6_norm(producto.get('color') or '')
    descn = _v6_norm(desc or '')
    if not color or any(x in color for x in ['combo', 'paquete', 'surtido']):
        return -999
    # Remueve ruido de venta.
    clean = re.sub(r'\b(de|del|la|el|los|las|pieza|piezas|pz|pzas|madeja|madejas|color|tono|tonos|quiero|dame|deme|ocupo|agrega|agregame|tambien|también|pero|uno|una|un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b', ' ', descn)
    clean = re.sub(r'\s+', ' ', clean).strip()
    score = 0
    if clean:
        if color == clean:
            score += 300
        if clean in color:
            score += 220
        words = [w for w in clean.split() if len(w) >= 2]
        if words and all(w in color for w in words):
            score += 170
        elif words and any(w in color for w in words):
            score += 75
    groups = _v6_color_groups(descn)
    for g in groups:
        if g == 'rojo_escolar':
            if 'rojo escolar' in color:
                score += 260
            elif 'rojo' in color:
                score += 80
        elif g == 'hueso':
            if any(x in color for x in ['hueso', 'marfil', 'ivory', 'cream', 'crema', 'light cream']):
                score += 230
            elif 'blanco' in color or 'white' in color:
                score += 85
            elif 'canario' in color or 'amarillo' in color:
                score += 35
        elif g == 'rosa':
            if 'rosa' in color:
                score += 220
            elif 'sandia' in color or 'sandía' in color or 'pink' in color:
                score += 120
            elif 'fucsia' in color or 'fiusha' in color:
                score += 45
        elif g == 'negro':
            if color == 'negro' or 'negro' in color or color == 'black':
                score += 250
        elif g == 'blanco':
            if any(x in color for x in ['blanco', 'white']):
                score += 200
            elif any(x in color for x in ['hueso', 'cream', 'crema', 'marfil']):
                score += 130
        else:
            aliases = V6_COLOR_GROUPS_EXTRA.get(g, [])
            if any(_v6_norm(a) in color for a in aliases):
                score += 150
    try:
        stock = int(producto.get('stock') or 0)
        if stock > 0:
            score += 10
    except Exception:
        pass
    return score


def _v6_resolve_color(productos_ctx, desc):
    # Código explícito gana sobre color.
    for cod in re.findall(r'(?<!\d)\d{1,4}(?!\d)', _v6_norm(desc)):
        prod, matches = _v6_choose_by_code(productos_ctx, cod)
        if prod:
            return prod, []
    scored = []
    for p in products_ctx if False else []:
        pass
    scored = [(_v6_color_score(p, desc), p) for p in productos_ctx or []]
    scored = [(s, p) for s, p in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, []
    top_score, top = scored[0]
    # Opciones relevantes: no mostrar demasiadas ni repetidas por color.
    opts = []
    seen = set()
    for s, p in scored[:8]:
        key = (str(p.get('codigo') or ''), _v6_norm(p.get('color') or ''))
        if key not in seen:
            seen.add(key)
            opts.append(p)
    # Si la diferencia es clara o hubo match fuerte, agregar directo.
    if len(scored) == 1 or top_score >= 230 or (len(scored) > 1 and top_score - scored[1][0] >= 80):
        return top, opts
    # Para texto simple como "negro" dentro de un hilo, si solo hay un color negro real, agregar.
    descn = _v6_norm(desc)
    groups = _v6_color_groups(descn)
    if groups:
        g = groups[0]
        exactish = [p for _s, p in scored if _v6_color_score(p, desc) >= 180]
        if len(exactish) == 1:
            return exactish[0], opts
    return None, opts[:5]


def _v6_qty_token(tok):
    s = _v6_norm(tok or '')
    if s.isdigit():
        try:
            return int(s)
        except Exception:
            return None
    return V6_QTY_WORDS.get(s)


def _v6_normalize_order_text(t):
    # Divide "y 1 rojo" como otro item sin romper "rojo escolar".
    t = _v6_norm(t)
    t = re.sub(r'\b(tambien|también|ademas|además|agregame|agrégame|agrega|agregar|dame|deme|quiero|ocupo|seria|sería|serian|serían|con|los colores siguientes|los siguientes colores)\b', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _v6_split_qty_items(texto):
    t = _v6_normalize_order_text(texto)
    qty_words = sorted(V6_QTY_WORDS.keys(), key=len, reverse=True)
    qty_alt = r'\d+|' + '|'.join(re.escape(w) for w in qty_words)
    # Marcar separadores antes de cantidad.
    pat = re.compile(rf'(?<!\w)({qty_alt})(?!\w)')
    matches = list(pat.finditer(t))
    out = []
    for i, m in enumerate(matches):
        qty = _v6_qty_token(m.group(1))
        if qty is None:
            continue
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(t)
        desc = t[start:end]
        desc = re.sub(r'^[\s,;\.\-]*(de|del|la|el|las|los)?\s*', '', desc)
        desc = re.sub(r'[\s,;\.\-]+$', '', desc).strip()
        # Evitar CP / teléfono / importes como productos.
        if qty >= 100 and not re.search(r'\b(piezas|pz|madejas|colores|surtidos?)\b', desc):
            continue
        if desc:
            out.append((qty, desc))
    return out


def _v6_contains_order_intent(texto):
    t = _v6_norm(texto)
    if any(x in t for x in ['dame', 'deme', 'quiero', 'ocupo', 'agrega', 'agregame', 'agrégame', 'seria', 'sería', 'serian', 'serían', 'pedido', 'paquete', 'combo']):
        return True
    # Lista con varias líneas/cantidades también cuenta como pedido.
    if len(_v6_split_qty_items(t)) >= 2:
        return True
    return False


def _v6_is_consultation(texto):
    t = _v6_norm(texto)
    # Si hay intención de pedido explícita con cantidades, no es solo consulta.
    if _v6_contains_order_intent(t) and _v6_split_qty_items(t) and not any(x in t for x in ['cuanto', 'precio', 'cuesta', 'sale', 'manejan', 'tienen', 'disponible', 'colores']):
        return False
    consult_words = ['cuanto', 'cuánto', 'precio', 'cuesta', 'costo', 'vale', 'sale', 'manejan', 'maneja', 'tienen', 'tiene', 'disponible', 'disponibilidad', 'colores', 'carta', 'catalogo', 'catálogo', 'envio', 'envío', 'envios', 'envíos', 'mandan', 'paqueteria', 'paquetería']
    return any(w in t for w in consult_words)


def _v6_detect_combo(texto):
    t = _v6_norm(texto)
    if not any(x in t for x in ['combo', 'paquete']):
        return None
    m = re.search(r'\b(10|20|40)\b', t)
    cantidad = int(m.group(1)) if m else None
    return {'cantidad': cantidad, 'hilo': 'Velluto' if any(x in t for x in ['velluto', 'veluto', 'alize']) else ''}


def _v6_public_answer_for_combo(texto):
    info = _v6_detect_combo(texto)
    if not info:
        return ''
    cantidad = info.get('cantidad')
    if cantidad in V6_COMBOS_VELLUTO:
        precio = V6_COMBOS_VELLUTO[cantidad]
        if cantidad == 40:
            return f"Sí 😊 el paquete de {cantidad} Velluto puede ir con colores a elegir, sujeto a disponibilidad. El paquete está en ${precio:,.0f} y se maneja con envío gratis en la promo activa. Mándeme su lista de tonos o códigos y le preparo su nota."
        return f"Sí 😊 el combo de {cantidad} Velluto puede ir con colores a elegir, sujeto a disponibilidad. El combo está en ${precio:,.0f}. Mándeme su lista de tonos o códigos y le preparo su nota."
    return "Sí 😊 puede armarse por combo o paquete según disponibilidad. Mándeme cuántas piezas y qué tonos busca para cotizarle bien."


def _v6_format_color_options(options, limit=5):
    lines = []
    for p in (options or [])[:limit]:
        codigo = str(p.get('codigo') or '').strip()
        color = str(p.get('color') or '').strip()
        stock = p.get('stock')
        extra = f" (stock {stock})" if stock not in (None, '') else ''
        lines.append(f"{codigo} {color}{extra}".strip())
    return ', '.join(lines)


def _v6_respuesta_consulta(texto, productos, hilos=None, marcas=None):
    t = _v6_norm(texto)
    combo = _v6_public_answer_for_combo(t)
    if combo:
        return combo
    if 'abuelita' in t:
        if any(x in t for x in ['parecid', 'similar', 'recomiendas', 'recomienda']):
            return "La Abuelita por el momento no la manejamos 😊 pero puedo ofrecerle opciones parecidas según su proyecto: Kurumi si busca algo más firme/delgado para amigurumi, o Komfy Mini si quiere algo suave tipo chenille. ¿Para qué trabajo lo ocuparía?"
        return "La Abuelita por el momento no la manejamos 😊 pero sí tengo otras opciones. ¿La busca para amigurumi, tejido o algún proyecto en especial?"
    if any(x in t for x in ['karineta', 'carineta', 'karinita']):
        return "Sí manejamos productos Karina 😊 ¿Me podría confirmar si busca Kurumi, Komfy Mini, Kairo u otro hilo de Karina?"
    if any(x in t for x in ['envio', 'envío', 'envios', 'envíos', 'mandan', 'paqueteria', 'paquetería']):
        cp = re.search(r'\b\d{5}\b', t)
        if cp:
            return f"Sí hacemos envíos a todo México 😊 Con su código postal {cp.group(0)} puedo revisar opciones de paquetería."
        return "Sí hacemos envíos a todo México 😊 Para cotizarle el envío me comparte su código postal, por favor."
    hilos = hilos or _v6_detect_hilos(t, productos)
    if hilos:
        bloques = []
        color_groups = _v6_color_groups(t)
        for h in hilos[:2]:
            prods_h = _v6_products_for_hilo(productos, h)
            fam = _v6_hilo_family(h)
            nombre = _v6_hilo_display(h)
            precio = _v6_price_text(prods_h, fam)
            if any(x in t for x in ['precio', 'cuanto', 'cuánto', 'cuesta', 'costo', 'vale']):
                if precio:
                    bloques.append(f"El {nombre} está en {precio} por madeja 😊 ¿Busca algún color o código en especial?")
                else:
                    bloques.append(f"Sí manejamos {nombre} 😊 ¿Qué color o código busca para revisar precio y disponibilidad?")
            elif color_groups:
                partes = []
                for g in color_groups[:3]:
                    prod, opts = _v6_resolve_color(prods_h, g)
                    if prod:
                        partes.append(f"{prod.get('codigo')} {prod.get('color')}")
                    elif opts:
                        partes.append(_v6_format_color_options(opts, 3))
                if partes:
                    bloques.append(f"Sí 😊 en {nombre} tengo opciones para esos tonos: " + '; '.join(partes) + ". ¿Cuántas piezas le aparto?")
                else:
                    bloques.append(f"Sí manejamos {nombre} 😊 ¿Me indica qué tono o código busca?")
            elif any(x in t for x in ['color', 'colores', 'disponib', 'carta', 'catalogo', 'catálogo']):
                muestra = []
                seen = set()
                for p in prods_h:
                    cn = _v6_norm(p.get('color') or '')
                    if not cn or any(x in cn for x in ['combo', 'paquete', 'surtido']):
                        continue
                    key = (str(p.get('codigo') or ''), cn)
                    if key in seen:
                        continue
                    seen.add(key)
                    muestra.append(f"{p.get('codigo')} {p.get('color')}")
                    if len(muestra) >= 8:
                        break
                extra = ' Algunos tonos disponibles son: ' + ', '.join(muestra) + '.' if muestra else ''
                bloques.append(f"Sí 😊 tenemos {nombre} disponible.{extra}\nLe puedo compartir la carta de colores completa.")
            else:
                if precio:
                    bloques.append(f"Sí 😊 manejamos {nombre}, está en {precio} por madeja. ¿Busca algún color o código en especial?")
                else:
                    bloques.append(f"Sí 😊 manejamos {nombre}. ¿Busca algún color o código en especial?")
        return '\n\n'.join(bloques).strip()
    return ''


def _wa_es_consulta_catalogo(texto):
    return _v6_is_consultation(texto)


def _wa_respuesta_consulta_almacen(texto, productos, hilos=None, marcas=None):
    return _v6_respuesta_consulta(texto, productos, hilos, marcas)


def _v6_add_or_sum(dest, p):
    key = str(p.get('producto_id') or '') or '|'.join([str(p.get('codigo') or ''), _v6_norm(p.get('marca') or ''), _v6_norm(p.get('hilo') or ''), _v6_norm(p.get('color') or '')])
    if key in dest:
        dest[key]['cantidad'] = int(dest[key].get('cantidad') or 0) + int(p.get('cantidad') or 0)
    else:
        dest[key] = dict(p)


def _v6_parse_order(texto, productos, hilos_globales=None, contexto_global=''):
    t = _v6_norm(texto)
    hilos_globales = hilos_globales or _v6_detect_hilos(t, productos)
    ultimo_hilo = contexto_global or (hilos_globales[0] if len(hilos_globales) == 1 else '')
    pedidos = {}
    preguntas = []
    errores = []
    advertencias = []

    # Códigos puros o códigos con cantidad tienen prioridad.
    items = _v6_split_qty_items(t)
    for qty, desc in items:
        hilos_desc = _v6_detect_hilos(desc, productos)
        if hilos_desc:
            ultimo_hilo = hilos_desc[0]
        hilo_ctx = hilos_desc[0] if hilos_desc else ultimo_hilo
        prods_ctx = _v6_products_for_hilo(productos, hilo_ctx) if hilo_ctx else productos

        # Quitar palabras de hilo de la descripción para dejar color/código.
        desc_clean = desc
        for h in hilos_desc or ([hilo_ctx] if hilo_ctx else []):
            for alias in sorted(_wa_aliases_hilo(h), key=len, reverse=True):
                a = _v6_norm(alias)
                if len(a) >= 3:
                    desc_clean = re.sub(rf'(?<!\w){re.escape(a)}(?!\w)', ' ', _v6_norm(desc_clean))
                    desc_clean = desc_clean.replace(a.replace(' ', ''), ' ')
        desc_clean = re.sub(r'\b(de|del|la|el|los|las|pieza|piezas|pz|pzas|madeja|madejas)\b', ' ', _v6_norm(desc_clean))
        desc_clean = re.sub(r'\s+', ' ', desc_clean).strip()

        # Código exacto.
        codigos = re.findall(r'(?<!\d)\d{1,4}(?!\d)', desc_clean)
        if codigos:
            cod = codigos[0]
            prod, matches = _v6_choose_by_code(prods_ctx if hilo_ctx else productos, cod, hilo_ctx)
            if prod:
                _v6_add_or_sum(pedidos, {
                    'producto_id': prod.get('id'), 'codigo': prod.get('codigo'), 'marca': prod.get('marca') or '',
                    'hilo': prod.get('hilo') or '', 'color': prod.get('color') or '', 'stock': int(prod.get('stock') or 0),
                    'precio_venta': float(prod.get('precio_venta') or 0), 'cantidad': int(qty),
                    'es_inventariable': prod.get('es_inventariable', True),
                })
                continue
            else:
                errores.append(cod)
                continue

        if not desc_clean:
            if hilo_ctx:
                preguntas.append(f"Me falta el tono o código para {qty} pieza(s) de {_v6_hilo_display(hilo_ctx)}.")
            else:
                preguntas.append(f"Me falta el hilo y tono para {qty} pieza(s).")
            continue

        prod, opts = _v6_resolve_color(prods_ctx, desc_clean)
        if prod:
            _v6_add_or_sum(pedidos, {
                'producto_id': prod.get('id'), 'codigo': prod.get('codigo'), 'marca': prod.get('marca') or '',
                'hilo': prod.get('hilo') or '', 'color': prod.get('color') or '', 'stock': int(prod.get('stock') or 0),
                'precio_venta': float(prod.get('precio_venta') or 0), 'cantidad': int(qty),
                'es_inventariable': prod.get('es_inventariable', True),
            })
        elif opts:
            nombre = _v6_hilo_display(hilo_ctx) if hilo_ctx else 'ese hilo'
            preguntas.append(f"Para {nombre}, tengo varias opciones parecidas a '{desc_clean}': {_v6_format_color_options(opts, 5)}. ¿Cuál le agrego x{qty}?")
        else:
            if hilo_ctx:
                preguntas.append(f"Sí cuento con {_v6_hilo_display(hilo_ctx)}, pero no ubiqué el tono '{desc_clean}'. ¿Me manda código o una foto de la carta para confirmarlo?")
            else:
                preguntas.append(f"No ubiqué '{desc_clean}' con seguridad. ¿Me confirma hilo y tono/código?")

    # Códigos sin cantidad en mensajes tipo "dame 55 56 429".
    if not pedidos and not preguntas and not errores and _v6_contains_order_intent(t):
        codigos = re.findall(r'(?<!\d)\d{1,4}(?!\d)', t)
        for cod in codigos:
            prod, _matches = _v6_choose_by_code(productos, cod, ultimo_hilo)
            if prod:
                _v6_add_or_sum(pedidos, {
                    'producto_id': prod.get('id'), 'codigo': prod.get('codigo'), 'marca': prod.get('marca') or '',
                    'hilo': prod.get('hilo') or '', 'color': prod.get('color') or '', 'stock': int(prod.get('stock') or 0),
                    'precio_venta': float(prod.get('precio_venta') or 0), 'cantidad': 1,
                    'es_inventariable': prod.get('es_inventariable', True),
                })
            elif len(cod) <= 4:
                errores.append(cod)

    # Cambios de opinión: quitar un hilo mencionado.
    if any(x in t for x in ['quitame', 'quítame', 'quita', 'quitar', 'ya no', 'pensandolo mejor', 'pensándolo mejor']):
        for h in _v6_detect_hilos(t, productos):
            fam = _v6_hilo_family(h)
            before = len(pedidos)
            pedidos = {k: v for k, v in pedidos.items() if _v6_hilo_family(v.get('hilo') or '') != fam}
            if len(pedidos) != before:
                advertencias.append(f"Se quitaron los productos de {_v6_hilo_display(h)} por cambio de la clienta.")

    return list(pedidos.values()), preguntas, errores, advertencias


def _wa_parsear_con_contexto_almacen(texto_total, productos_all, marca='', hilo='', extraer_pedidos_func=None):
    productos_base = _wa_filtrar_por_marca_hilo(productos_all, marca, hilo)
    t = _v6_norm(texto_total or '')
    hilos_detectados = _v6_detect_hilos(t, productos_base)
    contexto_global = hilo or (hilos_detectados[0] if len(hilos_detectados) == 1 else '')
    combo_resp = _v6_public_answer_for_combo(t)

    # Consultas comerciales: responder, no agregar carrito.
    if combo_resp:
        return {
            'pedidos_full': [], 'errores': [], 'advertencias': [], 'preguntas': [], 'sugerencias_almacen': [],
            'hilos_detectados': hilos_detectados, 'contexto_inferido': {'marca': marca or '', 'hilo': contexto_global or '', 'hilos_mencionados': hilos_detectados},
            'respuesta_preferida': combo_resp, 'ventas_info': {'tipo': 'combo_v6'}
        }

    # Si es pregunta sin pedido claro, no extraer productos aunque mencione colores.
    if _v6_is_consultation(t) and not (_v6_contains_order_intent(t) and _v6_split_qty_items(t)):
        resp = _v6_respuesta_consulta(t, productos_base, hilos_detectados, _wa_detectar_marcas(t, productos_base))
        if resp:
            return {
                'pedidos_full': [], 'errores': [], 'advertencias': [], 'preguntas': [], 'sugerencias_almacen': [],
                'hilos_detectados': hilos_detectados, 'contexto_inferido': {'marca': marca or '', 'hilo': contexto_global or '', 'hilos_mencionados': hilos_detectados},
                'respuesta_preferida': resp, 'ventas_info': {'tipo': 'consulta_v6'}
            }

    pedidos, preguntas, errores, advertencias = _v6_parse_order(t, productos_base, hilos_detectados, contexto_global)

    # Mensaje solo con código desconocido como "57000".
    if not pedidos and not preguntas and not errores:
        only_nums = re.findall(r'(?<!\d)\d{4,6}(?!\d)', t)
        if only_nums and len(t.replace(' ', '')) <= 8:
            errores.extend(only_nums)

    # Producto externo o parecido.
    respuesta_preferida = ''
    sugerencias = []
    if not pedidos and not preguntas and not errores:
        resp = _v6_respuesta_consulta(t, productos_base, hilos_detectados, _wa_detectar_marcas(t, productos_base))
        if resp:
            respuesta_preferida = resp
        else:
            respuesta_preferida = ''

    return {
        'pedidos_full': pedidos,
        'errores': sorted(set(str(e) for e in errores if e)),
        'advertencias': sorted(set(str(a) for a in advertencias if a)),
        'preguntas': sorted(set(str(p) for p in preguntas if p)),
        'sugerencias_almacen': sugerencias,
        'hilos_detectados': hilos_detectados,
        'contexto_inferido': {'marca': marca or '', 'hilo': contexto_global or '', 'hilos_mencionados': hilos_detectados},
        'respuesta_preferida': respuesta_preferida,
        'ventas_info': {'tipo': 'cerebro_comercial_v6'}
    }


def _fallback_respuesta_wa(texto, parsed, meta):
    if parsed.get('respuesta_preferida'):
        return str(parsed.get('respuesta_preferida')).strip()
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    if errores:
        base = ''
        if pedidos:
            base += 'Claro 😊 ya tengo claro esto:\n' + '\n'.join(_v6_producto_linea(p) for p in pedidos[:25]) + '\n\n'
        return base + 'Estos códigos no me aparecen en el catálogo: ' + ', '.join(map(str, errores[:8])) + '. ¿Me los confirma por favor?'
    if pedidos and preguntas:
        return 'Claro 😊 ya tengo claro esto:\n' + '\n'.join(_v6_producto_linea(p) for p in pedidos[:25]) + '\n\n' + preguntas[0]
    if preguntas:
        return 'Solo para confirmar 😊 ' + preguntas[0]
    if pedidos:
        txt = 'Claro 😊 le agrego:\n' + '\n'.join(_v6_producto_linea(p) for p in pedidos[:40])
        if len(pedidos) > 40:
            txt += f"\nY {len(pedidos)-40} producto(s) más."
        return txt + '\n\nLe preparo su cotización.'
    intent = (meta or {}).get('intencion')
    if intent == 'pregunta_envio':
        return 'Sí hacemos envíos a todo México 😊 Para cotizarle el envío me comparte su código postal, por favor.'
    if intent == 'comprobante_pago':
        return 'Perfecto 😊 mándeme la imagen del comprobante y reviso monto, referencia y datos para continuar con su pedido.'
    if intent == 'sugerir_tonos':
        return 'Sí 😊 mándeme la foto o referencia y le sugiero tonos parecidos según el catálogo disponible. No agrego nada hasta que usted confirme.'
    return 'Claro 😊 dígame qué hilo, color o código necesita y le ayudo a armar su cotización.'


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    # V6: determinístico con almacén. Evita que el modelo invente, mezcle hilos o pregunte de más.
    return _fallback_respuesta_wa(texto, parsed, meta), 'reglas_hilorama_v6'

# V6.1 - corrige separación de cantidades vs códigos.
def _v6_split_qty_items(texto):
    t = _v6_normalize_order_text(texto)
    qty_words = sorted(V6_QTY_WORDS.keys(), key=len, reverse=True)
    qty_alt = r'\d+|' + '|'.join(re.escape(w) for w in qty_words)
    # Separar "y 1 rojo", "también 2 negro" solo cuando después viene una cantidad.
    t = re.sub(rf'\s+(?:y|e|tambien|también|ademas|además)\s+(?=({qty_alt})\b)', ', ', t)
    raw_parts = [p.strip() for p in re.split(r'[,;\n]+', t) if p.strip()]
    out = []
    for part in raw_parts:
        m = re.match(rf'^(?:de\s+|del\s+)?({qty_alt})\b\s*(.*)$', part)
        if not m:
            continue
        qty = _v6_qty_token(m.group(1))
        if qty is None:
            continue
        desc = (m.group(2) or '').strip()
        desc = re.sub(r'^(?:de\s+|del\s+|codigo\s+|código\s+)', '', desc).strip()
        # Si el fragmento es solamente una cantidad grande, probablemente es CP/teléfono/importe, no pedido.
        if qty >= 100 and not desc:
            continue
        if desc:
            out.append((qty, desc))
    # Fallback para secuencias compactas de códigos: "55 56 429" después de un verbo de pedido.
    if not out and any(x in t for x in ['dame', 'deme', 'quiero', 'ocupo', 'agrega', 'agregame', 'agrégame']):
        nums = re.findall(r'(?<!\d)\d{1,4}(?!\d)', t)
        if len(nums) >= 2:
            out = [(1, n) for n in nums]
    return out

# V6.2 - si el cliente escribe solo una lista de códigos, no tomar el primer código como cantidad.
def _v6_split_qty_items(texto):
    t_original = _v6_norm(texto)
    t = _v6_normalize_order_text(texto)
    qty_words = sorted(V6_QTY_WORDS.keys(), key=len, reverse=True)
    qty_alt = r'\d+|' + '|'.join(re.escape(w) for w in qty_words)
    t = re.sub(rf'\s+(?:y|e|tambien|también|ademas|además)\s+(?=({qty_alt})\b)', ', ', t)
    raw_parts = [p.strip() for p in re.split(r'[,;\n]+', t) if p.strip()]
    out = []
    for part in raw_parts:
        m = re.match(rf'^(?:de\s+|del\s+)?({qty_alt})\b\s*(.*)$', part)
        if not m:
            continue
        qty = _v6_qty_token(m.group(1))
        if qty is None:
            continue
        desc = (m.group(2) or '').strip()
        desc = re.sub(r'^(?:de\s+|del\s+|codigo\s+|código\s+)', '', desc).strip()
        if qty >= 100 and not desc:
            continue
        if desc:
            out.append((qty, desc))
    # Lista compacta: "dame 55 56 429" = 1 de cada código.
    if len(out) == 1:
        qty, desc = out[0]
        nums_all = re.findall(r'(?<!\d)\d{1,4}(?!\d)', t)
        desc_nums = re.findall(r'(?<!\d)\d{1,4}(?!\d)', desc)
        # Si hay 3+ números y la primera "cantidad" es grande, casi seguro son códigos.
        if qty >= 20 and len(nums_all) >= 3 and len(desc_nums) >= 2:
            return [(1, n) for n in nums_all]
    if not out and any(x in t_original for x in ['dame', 'deme', 'quiero', 'ocupo', 'agrega', 'agregame', 'agrégame']):
        nums = re.findall(r'(?<!\d)\d{1,4}(?!\d)', t_original)
        if len(nums) >= 2:
            out = [(1, n) for n in nums]
    return out

# V6.3 - capa de ambigüedad antes de aceptar pares de números pequeños como pedido.
_wa_parsear_con_contexto_almacen_v6_core = _wa_parsear_con_contexto_almacen

def _wa_parsear_con_contexto_almacen(texto_total, productos_all, marca='', hilo='', extraer_pedidos_func=None):
    t = _v6_norm(texto_total or '')
    # Ejemplo clásico: "dame 2 4". Sin "del/código" puede significar 2 piezas del 4 o códigos 2 y 4.
    if re.search(r'\b(dame|deme|quiero|ocupo|agrega|agregame|agrégame)\s+([1-9])\s+([1-9])\b', t) and not re.search(r'\b(del|de|codigo|código)\b', t):
        nums = re.search(r'\b(?:dame|deme|quiero|ocupo|agrega|agregame|agrégame)\s+([1-9])\s+([1-9])\b', t)
        n1, n2 = nums.group(1), nums.group(2)
        return {
            'pedidos_full': [], 'errores': [], 'advertencias': [],
            'preguntas': [f"¿Se refiere a {n1} pieza(s) del código {n2}, o a los códigos {n1} y {n2}?"],
            'sugerencias_almacen': [], 'hilos_detectados': _v6_detect_hilos(t, productos_all),
            'contexto_inferido': {'marca': marca or '', 'hilo': hilo or '', 'hilos_mencionados': _v6_detect_hilos(t, productos_all)},
            'respuesta_preferida': '', 'ventas_info': {'tipo': 'ambiguedad_numerica_v6'}
        }
    return _wa_parsear_con_contexto_almacen_v6_core(texto_total, productos_all, marca, hilo, extraer_pedidos_func)


# ==========================================================
# WhatsApp IA V7 - Biblioteca IA + aprendizaje humano
# ==========================================================
# Esta capa agrega una memoria administrable para que el agente deje de depender
# solo de reglas: cuando una conversación se mande a humano, la respuesta correcta
# se puede guardar como aprendizaje y se reutiliza en casos parecidos.

WA_V7_STOPWORDS = set("""hola buenos dias buenas tardes noches gracias por favor favor me mi mis tu tus su sus el la los las un una uno unas unos de del al a y o en con para por que qué cual cuál cuanto cuánto cuesta precio tiene tienen maneja manejan dame deme quiero ocupo necesito agregar agregame agrégame articulos artículos piezas pieza pz pzas madeja madejas estambre hilo hilos color colores tono tonos disponible disponibilidad""".split())

def _wa_v7_schema():
    try:
        with DB() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ia_recursos (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT,
                    categoria TEXT DEFAULT 'respuesta',
                    marca TEXT,
                    hilo TEXT,
                    triggers TEXT,
                    pregunta_ejemplo TEXT,
                    respuesta TEXT,
                    archivo_url TEXT,
                    grupo TEXT,
                    orden INTEGER DEFAULT 0,
                    enviar_junto BOOLEAN DEFAULT FALSE,
                    notas TEXT,
                    prioridad INTEGER DEFAULT 50,
                    activo BOOLEAN DEFAULT TRUE,
                    auto_aprendido BOOLEAN DEFAULT FALSE,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS ia_pendientes_humano (
                    id SERIAL PRIMARY KEY,
                    mensaje_cliente TEXT,
                    respuesta_ia TEXT,
                    motivo TEXT,
                    contexto TEXT,
                    estado TEXT DEFAULT 'PENDIENTE',
                    respuesta_humana TEXT,
                    recurso_id INTEGER,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for col in [
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS nombre TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS categoria TEXT DEFAULT 'respuesta'",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS marca TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS hilo TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS triggers TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS pregunta_ejemplo TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS respuesta TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS archivo_url TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS grupo TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS orden INTEGER DEFAULT 0",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS enviar_junto BOOLEAN DEFAULT FALSE",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS notas TEXT",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS prioridad INTEGER DEFAULT 50",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT TRUE",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS auto_aprendido BOOLEAN DEFAULT FALSE",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE ia_recursos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS mensaje_cliente TEXT",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS respuesta_ia TEXT",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS motivo TEXT",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS contexto TEXT",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'PENDIENTE'",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS respuesta_humana TEXT",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS recurso_id INTEGER",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE ia_pendientes_humano ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            ]:
                db.execute(col)
            db.execute("CREATE INDEX IF NOT EXISTS idx_ia_recursos_activo_categoria ON ia_recursos(activo, categoria)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_ia_recursos_grupo ON ia_recursos(grupo, activo, orden)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_ia_pendientes_estado ON ia_pendientes_humano(estado, updated_at DESC)")
            base_count = db.execute("SELECT COUNT(*) AS c FROM ia_recursos").fetchone()['c']
            if int(base_count or 0) == 0:
                seeds = [
                    ('Colores Velluto', 'carta_colores', 'ALIZE', 'VELLUTO', 'velluto, alize velluto, colores velluto, carta velluto, tonos velluto', 'Hola, me interesa Alize Velluto. ¿Qué colores tienen disponibles?', 'Sí 😊 tenemos Alize Velluto disponible. Le comparto la carta de colores actualizada. Si busca algún tono o código en especial, indíqueme cuál y con gusto le reviso disponibilidad.', '', 'Usar cuando pregunten por carta/colores de Alize Velluto.', 80),
                    ('Colores Komfy Mini', 'carta_colores', 'KARINA', 'KOMFY MINI', 'komfy mini, komfi mini, konfy mini, colores komfy, carta komfy, tonos komfy', '¿Y de Komfy Mini qué colores tienen?', 'Sí 😊 manejamos Komfy Mini. Le comparto la carta de colores disponible. Si me indica los códigos o tonos que le gusten, le preparo su cotización.', '', 'Usar cuando pregunten por colores o disponibilidad de Komfy Mini.', 80),
                    ('Colores Kurumi', 'carta_colores', 'KARINA', 'KURUMI', 'kurumi, colores kurumi, carta kurumi, disponibilidad kurumi', 'Me puedes mandar disponibilidad de Kurumi, por favor.', 'Sí 😊 manejamos Kurumi. Le comparto la disponibilidad actualizada para que pueda elegir tonos.', '', 'Usar cuando pregunten por Kurumi.', 80),
                    ('Envío por código postal', 'envio', '', '', 'envio, envío, envios, envíos, paqueteria, paquetería, correos, estafeta, fedex, codigo postal, código postal, cp', '¿Tienen envíos a todo México?', 'Sí 😊 hacemos envíos a todo México. Para cotizarle opciones de paquetería me comparte su código postal, por favor.', '', 'Usar cuando pregunten por envíos y no haya CP claro.', 70),
                    ('Datos de pago', 'pago', '', '', 'pago, pagar, transferencia, mercado pago, datos de pago, cuenta, clabe', '¿Me puede pasar los datos de pago?', 'Claro 😊 le comparto los datos de pago. Cuando realice el pago me manda su comprobante para revisarlo y continuar con su pedido.', '', 'Adjuntar imagen de datos de pago si se carga en archivo_url.', 70),
                    ('La Abuelita alternativa', 'producto_similar', '', '', 'abuelita, la abuelita, estambre abuelita, parecido a la abuelita, similar a la abuelita', 'Busco algo parecido a La Abuelita, ¿qué me recomiendas?', 'La Abuelita por el momento no la manejamos 😊 pero puedo ofrecerle opciones parecidas según su proyecto: Kurumi si busca algo más firme/delgado para amigurumi, o Komfy Mini si quiere algo suave tipo chenille. ¿Para qué trabajo lo ocuparía?', '', 'Producto externo: sugerir opciones del almacén sin inventar que se maneja.', 75),
                ]
                for row in seeds:
                    db.execute("""
                        INSERT INTO ia_recursos (nombre,categoria,marca,hilo,triggers,pregunta_ejemplo,respuesta,archivo_url,notas,prioridad,activo,auto_aprendido,fecha,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,FALSE,%s,%s)
                    """, (*row, now_mexico(), now_mexico()))
            _wa_v8_auto_seed_static_recursos(db)
    except Exception as exc:
        print('WARN schema IA recursos:', exc, flush=True)



def _wa_v8_static_url(rel_path):
    rel_path = str(rel_path).replace('\\', '/')
    parts = []
    for part in rel_path.split('/'):
        if part and part not in ('.', '..'):
            parts.append(part)
    return '/static/' + '/'.join(parts)


def _wa_v8_auto_seed_static_recursos(db):
    """Registra automáticamente cartas/gamas y fotos físicas de static/recursos_ia."""
    try:
        base = Path(__file__).resolve().parent / 'static' / 'recursos_ia'
        if not base.exists():
            return
        now = now_mexico()
        gama_dir = base / 'Velluto Carta de Colores'
        if gama_dir.exists():
            order_names = ['004.png', '4.png', '5.png', '6.png']
            files = []
            for name in order_names:
                f = gama_dir / name
                if f.exists():
                    files.append(f)
            seen = {f.name for f in files}
            for f in sorted(gama_dir.iterdir(), key=lambda x: x.name.lower()):
                if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.jfif') and f.name not in seen:
                    files.append(f)
            for idx, f in enumerate(files, start=1):
                rel = f.relative_to(Path(__file__).resolve().parent / 'static')
                url = _wa_v8_static_url(rel)
                exists = db.execute('SELECT id FROM ia_recursos WHERE archivo_url=%s LIMIT 1', (url,)).fetchone()
                if exists:
                    db.execute("""
                        UPDATE ia_recursos
                        SET grupo=%s, orden=%s, enviar_junto=TRUE, categoria=%s, marca=%s, hilo=%s,
                            triggers=COALESCE(NULLIF(triggers,''), %s), updated_at=%s
                        WHERE id=%s
                    """, ('gama_velluto', idx, 'carta_colores', 'ALIZE', 'VELLUTO',
                          'velluto, alize velluto, colores velluto, carta velluto, gama velluto, tonos velluto',
                          now, exists['id']))
                else:
                    db.execute("""
                        INSERT INTO ia_recursos
                        (nombre,categoria,marca,hilo,triggers,pregunta_ejemplo,respuesta,archivo_url,grupo,orden,enviar_junto,notas,prioridad,activo,auto_aprendido,fecha,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,TRUE,FALSE,%s,%s)
                    """, (
                        f'Carta de colores Alize Velluto {idx}', 'carta_colores', 'ALIZE', 'VELLUTO',
                        'velluto, alize velluto, colores velluto, carta velluto, gama velluto, tonos velluto, que colores tienen velluto',
                        'Hola, me interesa Alize Velluto. ¿Qué colores tienen disponibles?',
                        'Claro 😊 le comparto la gama de colores de Alize Velluto. Si le gusta algún código o tono, me lo indica y le reviso disponibilidad.',
                        url, 'gama_velluto', idx,
                        'Parte de la gama Velluto. Enviar junto con todos los recursos del grupo gama_velluto.',
                        92, now, now
                    ))
        tonos_dir = base / 'Velluto Colores'
        if tonos_dir.exists():
            for f in sorted(tonos_dir.iterdir(), key=lambda x: x.name.lower()):
                if not f.is_file() or f.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.jfif'):
                    continue
                codigo = f.stem.strip()
                if not codigo:
                    continue
                rel = f.relative_to(Path(__file__).resolve().parent / 'static')
                url = _wa_v8_static_url(rel)
                exists = db.execute('SELECT id FROM ia_recursos WHERE archivo_url=%s LIMIT 1', (url,)).fetchone()
                tags = f'velluto {codigo}, tono {codigo}, código {codigo}, codigo {codigo}, foto {codigo}, color {codigo}, alize velluto {codigo}'
                if exists:
                    db.execute("""
                        UPDATE ia_recursos
                        SET categoria=%s, marca=%s, hilo=%s, grupo=%s, orden=1, enviar_junto=FALSE,
                            triggers=COALESCE(NULLIF(triggers,''), %s), updated_at=%s
                        WHERE id=%s
                    """, ('foto_tono', 'ALIZE', 'VELLUTO', f'tono_velluto_{codigo}', tags, now, exists['id']))
                else:
                    db.execute("""
                        INSERT INTO ia_recursos
                        (nombre,categoria,marca,hilo,triggers,pregunta_ejemplo,respuesta,archivo_url,grupo,orden,enviar_junto,notas,prioridad,activo,auto_aprendido,fecha,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,FALSE,%s,%s,TRUE,FALSE,%s,%s)
                    """, (
                        f'Foto tono Velluto {codigo}', 'foto_tono', 'ALIZE', 'VELLUTO', tags,
                        f'¿Me mandas foto del {codigo}?',
                        f'Claro 😊 le comparto la foto del tono Velluto {codigo}.',
                        url, f'tono_velluto_{codigo}',
                        'Foto individual de tono Velluto. Enviar solo cuando pidan ese código/tono.',
                        78, now, now
                    ))
    except Exception as exc:
        print('WARN auto seed static recursos IA:', exc, flush=True)


def _wa_v8_recurso_to_url(recurso):
    return str((recurso or {}).get('archivo_url') or '').strip()


def _wa_v8_obtener_recursos_grupo(recurso):
    if not recurso:
        return []
    grupo = str(recurso.get('grupo') or '').strip()
    enviar_junto = bool(recurso.get('enviar_junto'))
    if not grupo or not enviar_junto:
        return [recurso]
    try:
        with DB() as db:
            rows = db.execute("""
                SELECT * FROM ia_recursos
                WHERE activo=TRUE AND grupo=%s
                ORDER BY COALESCE(orden,0), id
                LIMIT 20
            """, (grupo,)).fetchall()
        return [dict(r) for r in rows] or [recurso]
    except Exception as exc:
        print('WARN obtener grupo recursos IA:', exc, flush=True)
        return [recurso]

def _wa_v7_tokens(txt):
    txt = _v6_norm(txt or '') if '_v6_norm' in globals() else str(txt or '').lower()
    return [w for w in re.findall(r'[a-z0-9ñ]+', txt) if len(w) >= 3 and w not in WA_V7_STOPWORDS]


def _wa_v7_score_recurso(texto, recurso):
    t = _v6_norm(texto or '') if '_v6_norm' in globals() else str(texto or '').lower()
    score = 0
    triggers = str(recurso.get('triggers') or '')
    pregunta = str(recurso.get('pregunta_ejemplo') or '')
    nombre = str(recurso.get('nombre') or '')
    hay_trigger_fuerte = False
    for raw in re.split(r'[,;\n]+', triggers):
        tr = _v6_norm(raw.strip()) if '_v6_norm' in globals() else raw.strip().lower()
        if not tr:
            continue
        if tr in t:
            score += 55 + min(len(tr), 30)
            hay_trigger_fuerte = True
        else:
            toks = _wa_v7_tokens(tr)
            if toks:
                inter = len(set(toks) & set(_wa_v7_tokens(t)))
                if inter:
                    score += inter * 10
    ref_tokens = set(_wa_v7_tokens(' '.join([pregunta, nombre, str(recurso.get('categoria') or ''), str(recurso.get('marca') or ''), str(recurso.get('hilo') or '')])))
    msg_tokens = set(_wa_v7_tokens(t))
    if ref_tokens and msg_tokens:
        score += int(100 * len(ref_tokens & msg_tokens) / max(6, len(ref_tokens | msg_tokens)))
    try:
        score += min(int(recurso.get('prioridad') or 0), 100) // 10
    except Exception:
        pass
    return score, hay_trigger_fuerte


def _wa_v7_buscar_recurso(texto, categoria=None):
    _wa_v7_schema()
    try:
        with DB() as db:
            params=[]
            where="activo=TRUE"
            if categoria:
                where += " AND categoria=%s"
                params.append(categoria)
            rows = db.execute(f"""
                SELECT * FROM ia_recursos
                WHERE {where}
                ORDER BY prioridad DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
                LIMIT 500
            """, tuple(params)).fetchall()
        best=None; best_score=0; best_strong=False
        for r in rows:
            d=dict(r)
            sc,strong = _wa_v7_score_recurso(texto, d)
            if sc > best_score:
                best, best_score, best_strong = d, sc, strong
        if best and (best_score >= 42 or best_strong):
            best['_score'] = best_score
            return best
    except Exception as exc:
        print('WARN buscar recurso IA:', exc, flush=True)
    return None


def _wa_v7_respuesta_de_recurso(recurso):
    if not recurso:
        return ''
    recursos = _wa_v8_obtener_recursos_grupo(recurso)
    principal = recursos[0] if recursos else recurso
    resp = str(principal.get('respuesta') or '').strip()
    nombre = str(principal.get('nombre') or '').strip()
    grupo = str(principal.get('grupo') or '').strip()
    urls = []
    for r in recursos:
        url = _wa_v8_recurso_to_url(r)
        if url and url not in urls:
            urls.append(url)
    if urls:
        if len(urls) == 1:
            extra = f"\n\n📎 Recurso para enviar: {nombre}\n{urls[0]}"
        else:
            titulo = 'Recursos para enviar juntos'
            if grupo:
                titulo += f' · grupo {grupo}'
            extra = "\n\n📎 " + titulo + "\n" + "\n".join([f"{i+1}. {u}" for i,u in enumerate(urls)])
        if extra not in resp:
            resp += extra
    return resp.strip()



# ==========================================================
# WhatsApp IA V10 - prioridad a foto de tono por código exacto
# ==========================================================
def _wa_v10_tone_resource_from_code(texto):
    """Si el cliente pide ver/foto/tono/color de un código existente en recursos físicos,
    prioriza la foto individual antes que la gama completa.
    Ej: "muéstrame el tono del velluto 56" -> /Velluto Colores/56.webp
    """
    try:
        t = _v6_norm(texto or '') if '_v6_norm' in globals() else str(texto or '').lower()
    except Exception:
        t = str(texto or '').lower()
    # Solo aplica cuando realmente pide mostrar foto/tono/color, no para cantidades de pedido.
    wants_image = bool(re.search(r'\b(foto|imagen|mostrar|muestra|ver|enseña|ensena|mandar|manda|tono|color|como se ve|se ve)\b', t, re.I))
    mentions_velluto = bool(re.search(r'\b(velluto|veluto|vellutos|alize)\b', t, re.I))
    if not wants_image:
        return None
    nums = re.findall(r'(?<!\d)(\d{1,4})(?!\d)', t)
    if not nums:
        return None
    # Si menciona velluto, buscamos en fotos individuales Velluto. Si no menciona producto,
    # también intentamos Velluto porque por ahora es la biblioteca física cargada.
    for code in nums:
        grupo = f'tono_velluto_{code}'
        try:
            with DB() as db:
                row = db.execute("""
                    SELECT * FROM ia_recursos
                    WHERE activo=TRUE
                      AND (grupo=%s OR archivo_url ILIKE %s OR triggers ILIKE %s)
                    ORDER BY CASE WHEN grupo=%s THEN 0 ELSE 1 END, prioridad DESC NULLS LAST, id DESC
                    LIMIT 1
                """, (grupo, f'%/Velluto Colores/{code}.%', f'%{code}%', grupo)).fetchone()
            if row:
                d = dict(row)
                # Evita que una carta/gama gane por contener el número en otro texto.
                if str(d.get('categoria') or '').lower() == 'foto_tono' or str(d.get('grupo') or '') == grupo:
                    d['_score'] = 999
                    d['_v10_exact_code'] = code
                    return d
        except Exception as exc:
            print('WARN buscar tono exacto recurso IA:', exc, flush=True)
        # Respaldo físico: si el recurso no quedó registrado en DB, pero el archivo existe, úsalo.
        try:
            base = Path(__file__).resolve().parent / 'static' / 'recursos_ia' / 'Velluto Colores'
            for ext in ('.webp', '.png', '.jpg', '.jpeg', '.jfif'):
                f = base / f'{code}{ext}'
                if f.exists():
                    url = _wa_v8_static_url(f.relative_to(Path(__file__).resolve().parent / 'static'))
                    return {
                        'id': None,
                        'nombre': f'Foto tono Velluto {code}',
                        'categoria': 'foto_tono',
                        'marca': 'ALIZE',
                        'hilo': 'VELLUTO',
                        'triggers': f'velluto {code}, tono {code}, codigo {code}, código {code}, foto {code}',
                        'respuesta': f'Claro 😊 le comparto la foto del tono Velluto {code}.',
                        'archivo_url': url,
                        'grupo': f'tono_velluto_{code}',
                        'orden': 1,
                        'enviar_junto': False,
                        'prioridad': 100,
                        '_score': 999,
                        '_v10_exact_code': code,
                    }
        except Exception as exc:
            print('WARN respaldo físico tono exacto IA:', exc, flush=True)
    return None

_wa_generar_respuesta_v6_core = _generar_respuesta_wa_con_openai

def _wa_v11_pide_carta_o_gama(texto):
    """Detecta cuando la clienta realmente quiere ver la gama/carta/catálogo de colores.
    IMPORTANTE: la palabra "tono/color" sola no basta, porque en "cuánto cuesta Velluto" no se debe mandar la carta.
    """
    try:
        t = _v6_norm(texto or '')
    except Exception:
        t = str(texto or '').lower()
    patrones = [
        r'\b(gama|carta|catalogo|catálogo)\b',
        r'\b(que|qué|cuales|cuáles)\s+(colores|tonos)\b',
        r'\b(colores|tonos)\s+(tienen|manejan|disponibles|hay)\b',
        r'\b(manda|mandame|mándame|enviame|envíame|pasa|pasame|pásame|muestra|muestrame|muéstrame)\b.*\b(colores|tonos)\b',
        r'\b(ver|mostrar)\b.*\b(colores|tonos)\b',
    ]
    return any(re.search(pat, t, re.I) for pat in patrones)


def _wa_v11_es_pregunta_precio(texto):
    try:
        t = _v6_norm(texto or '')
    except Exception:
        t = str(texto or '').lower()
    return bool(re.search(r'\b(cuanto|cuánto|precio|cuesta|costo|vale|en cuanto|sale)\b', t, re.I))


def _wa_v11_es_pregunta_envio(texto):
    try:
        t = _v6_norm(texto or '')
    except Exception:
        t = str(texto or '').lower()
    return bool(re.search(r'\b(envio|envío|envios|envíos|paqueteria|paquetería|cp|codigo postal|código postal|mandan|mandas)\b', t, re.I))


def _wa_v11_es_pregunta_pago(texto):
    try:
        t = _v6_norm(texto or '')
    except Exception:
        t = str(texto or '').lower()
    return bool(re.search(r'\b(pago|pagar|transferencia|mercado pago|mercadopago|clabe|cuenta|comprobante|deposito|depósito)\b', t, re.I))


_wa_generar_respuesta_v10_core = _wa_generar_respuesta_v6_core

def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    """V11: decide mejor cuándo usar Biblioteca IA.

    Corrección clave:
    - Pregunta de precio ("¿cuánto cuesta Velluto?") NO debe disparar la gama de colores.
    - Petición de gama/carta/colores SÍ debe disparar el grupo de imágenes.
    - Petición de foto/tono + código exacto sigue teniendo prioridad sobre la gama.
    """
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []

    # Primero calculamos la respuesta comercial base con almacén/precios.
    respuesta_base, motor_base = _wa_generar_respuesta_v6_core(texto, parsed, meta, contexto)

    try:
        es_consulta = _v6_is_consultation(texto)
    except Exception:
        es_consulta = False

    pide_carta = _wa_v11_pide_carta_o_gama(texto)
    pregunta_precio = _wa_v11_es_pregunta_precio(texto)
    pregunta_envio = _wa_v11_es_pregunta_envio(texto)
    pregunta_pago = _wa_v11_es_pregunta_pago(texto)

    # 1) Prioridad absoluta: foto/tono/color + código exacto => recurso individual.
    recurso_exact_code = _wa_v10_tone_resource_from_code(texto)
    if recurso_exact_code and (not pedidos or preguntas or errores or es_consulta):
        resp = _wa_v7_respuesta_de_recurso(recurso_exact_code)
        if resp:
            rid = recurso_exact_code.get('id') or recurso_exact_code.get('_v10_exact_code') or 'fisico'
            return resp, f"biblioteca_ia_v11_tono_exacto:{rid}"

    # 2) Gama/carta: solo cuando de verdad la pidan. No usar por una pregunta de precio.
    if pide_carta and (not pedidos or preguntas or errores or es_consulta):
        recurso = _wa_v7_buscar_recurso(texto, categoria='carta_colores') or _wa_v7_buscar_recurso(texto)
        if recurso:
            resp = _wa_v7_respuesta_de_recurso(recurso)
            if resp:
                return resp, f"biblioteca_ia_v11_carta:{recurso.get('id')}"

    # 3) Pago/envío: permitir recursos de esas categorías si existen.
    #    Si no hay recurso, usar la respuesta base del agente.
    if (pregunta_envio or pregunta_pago) and (not pedidos or preguntas or errores or es_consulta):
        categoria = 'envio' if pregunta_envio else 'pago'
        recurso = _wa_v7_buscar_recurso(texto, categoria=categoria)
        if recurso:
            resp = _wa_v7_respuesta_de_recurso(recurso)
            if resp:
                return resp, f"biblioteca_ia_v11_{categoria}:{recurso.get('id')}"

    # 4) Para precio: NO buscar carta ni recursos generales. Usar almacén.
    if pregunta_precio:
        return respuesta_base, motor_base + ':v11_precio_sin_carta'

    # 5) Recursos generales/aprendizajes: solo si no es pedido claro.
    if (not pedidos or preguntas or errores or es_consulta):
        recurso = _wa_v7_buscar_recurso(texto)
        if recurso:
            # Evitar que una carta se use por accidente si no pidieron carta/gama.
            if str(recurso.get('categoria') or '').lower() == 'carta_colores' and not pide_carta:
                return respuesta_base, motor_base + ':v11_omite_carta_no_solicitada'
            resp = _wa_v7_respuesta_de_recurso(recurso)
            if resp:
                return resp, f"biblioteca_ia_v11:{recurso.get('id')}"

    return respuesta_base, motor_base


@app.route('/api/ia/recursos', methods=['GET'])
def ia_recursos_listar():
    _wa_v7_schema()
    q = (request.args.get('q') or '').strip()
    limit = min(int(request.args.get('limit') or 100), 500)
    params=[]
    where="1=1"
    if q:
        like = '%' + q + '%'
        where += " AND (nombre ILIKE %s OR categoria ILIKE %s OR marca ILIKE %s OR hilo ILIKE %s OR triggers ILIKE %s OR pregunta_ejemplo ILIKE %s OR respuesta ILIKE %s OR notas ILIKE %s)"
        params += [like]*8
    with DB() as db:
        rows = db.execute(f"""
            SELECT * FROM ia_recursos
            WHERE {where}
            ORDER BY activo DESC, prioridad DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC
            LIMIT %s
        """, tuple(params+[limit])).fetchall()
    return jsonify(json_safe([dict(r) for r in rows]))


@app.route('/api/ia/recursos', methods=['POST'])
def ia_recursos_crear():
    _wa_v7_schema()
    data = request.get_json(force=True) or {}
    nombre = (data.get('nombre') or data.get('titulo') or '').strip() or 'Recurso IA'
    categoria = (data.get('categoria') or 'respuesta').strip()
    marca = (data.get('marca') or '').strip()
    hilo = (data.get('hilo') or '').strip()
    triggers = (data.get('triggers') or data.get('tags') or '').strip()
    pregunta = (data.get('pregunta_ejemplo') or data.get('pregunta') or '').strip()
    respuesta = (data.get('respuesta') or '').strip()
    archivo_url = (data.get('archivo_url') or data.get('url') or '').strip()
    grupo = (data.get('grupo') or data.get('bundle') or '').strip()
    try:
        orden = int(data.get('orden') or 0)
    except Exception:
        orden = 0
    enviar_junto = bool(data.get('enviar_junto') or data.get('enviarJunto') or False)
    notas = (data.get('notas') or '').strip()
    prioridad = int(data.get('prioridad') or 50)
    activo = bool(data.get('activo', True))
    auto_aprendido = bool(data.get('auto_aprendido', False))
    if not respuesta and not archivo_url:
        return jsonify({'ok': False, 'error': 'Agrega una respuesta o un link/archivo del recurso.'}), 400
    with DB() as db:
        r = db.execute("""
            INSERT INTO ia_recursos (nombre,categoria,marca,hilo,triggers,pregunta_ejemplo,respuesta,archivo_url,grupo,orden,enviar_junto,notas,prioridad,activo,auto_aprendido,fecha,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
        """, (nombre,categoria,marca,hilo,triggers,pregunta,respuesta,archivo_url,grupo,orden,enviar_junto,notas,prioridad,activo,auto_aprendido,now_mexico(),now_mexico())).fetchone()
    return jsonify(json_safe({'ok': True, 'recurso': dict(r)}))


@app.route('/api/ia/recursos/<int:rid>', methods=['PUT'])
def ia_recursos_actualizar(rid):
    _wa_v7_schema()
    data = request.get_json(force=True) or {}
    campos=[]; vals=[]
    allowed = ['nombre','categoria','marca','hilo','triggers','pregunta_ejemplo','respuesta','archivo_url','grupo','orden','enviar_junto','notas','prioridad','activo']
    for k in allowed:
        if k in data:
            campos.append(f"{k}=%s")
            vals.append(data[k])
    if not campos:
        return jsonify({'ok': False, 'error': 'No hay cambios.'}), 400
    campos.append('updated_at=%s'); vals.append(now_mexico()); vals.append(rid)
    with DB() as db:
        r = db.execute(f"UPDATE ia_recursos SET {', '.join(campos)} WHERE id=%s RETURNING *", tuple(vals)).fetchone()
    return jsonify(json_safe({'ok': True, 'recurso': dict(r) if r else None}))


@app.route('/api/ia/recursos/importar-static', methods=['POST'])
def ia_recursos_importar_static():
    """Escanea static/recursos_ia y registra gamas/fotos físicas en Biblioteca IA."""
    _wa_v7_schema()
    try:
        with DB() as db:
            _wa_v8_auto_seed_static_recursos(db)
            total = db.execute("SELECT COUNT(*) AS c FROM ia_recursos WHERE archivo_url LIKE '/static/recursos_ia/%'").fetchone()['c']
            gama = db.execute("SELECT COUNT(*) AS c FROM ia_recursos WHERE grupo='gama_velluto' AND activo=TRUE").fetchone()['c']
            tonos = db.execute("SELECT COUNT(*) AS c FROM ia_recursos WHERE categoria='foto_tono' AND hilo='VELLUTO' AND activo=TRUE").fetchone()['c']
        return jsonify(json_safe({'ok': True, 'total_static': total, 'gama_velluto': gama, 'tonos_velluto': tonos}))
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/whatsapp-ia/pendiente-humano' , methods=['POST'])
def whatsapp_ia_pendiente_humano():
    _wa_v7_schema()
    data = request.get_json(force=True) or {}
    mensaje = (data.get('mensaje_cliente') or data.get('mensaje') or '').strip()
    respuesta_ia = (data.get('respuesta_ia') or '').strip()
    motivo = (data.get('motivo') or 'Requiere revisión humana').strip()
    contexto = data.get('contexto') or {}
    if not mensaje:
        return jsonify({'ok': False, 'error': 'Falta el mensaje de la clienta.'}), 400
    with DB() as db:
        r = db.execute("""
            INSERT INTO ia_pendientes_humano (mensaje_cliente,respuesta_ia,motivo,contexto,estado,fecha,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *
        """, (mensaje,respuesta_ia,motivo,json.dumps(contexto,ensure_ascii=False),'PENDIENTE',now_mexico(),now_mexico())).fetchone()
    return jsonify(json_safe({'ok': True, 'pendiente': dict(r)}))


@app.route('/api/whatsapp-ia/pendientes', methods=['GET'])
def whatsapp_ia_pendientes_listar():
    _wa_v7_schema()
    estado = (request.args.get('estado') or '').strip()
    where='1=1'; params=[]
    if estado:
        where += ' AND estado=%s'; params.append(estado)
    with DB() as db:
        rows = db.execute(f"""
            SELECT * FROM ia_pendientes_humano
            WHERE {where}
            ORDER BY updated_at DESC NULLS LAST, fecha DESC
            LIMIT 100
        """, tuple(params)).fetchall()
    return jsonify(json_safe([dict(r) for r in rows]))


@app.route('/api/whatsapp-ia/guardar-aprendizaje', methods=['POST'])
def whatsapp_ia_guardar_aprendizaje():
    _wa_v7_schema()
    data = request.get_json(force=True) or {}
    mensaje = (data.get('mensaje_cliente') or data.get('mensaje') or '').strip()
    respuesta_humana = (data.get('respuesta_humana') or data.get('respuesta') or '').strip()
    respuesta_ia = (data.get('respuesta_ia') or '').strip()
    categoria = (data.get('categoria') or 'aprendizaje_humano').strip()
    tags = (data.get('tags') or '').strip()
    if not mensaje or not respuesta_humana:
        return jsonify({'ok': False, 'error': 'Falta mensaje de clienta o respuesta humana correcta.'}), 400
    toks = _wa_v7_tokens(mensaje)
    auto_tags = ', '.join(list(dict.fromkeys(toks))[:12])
    triggers = tags or auto_tags
    nombre = (data.get('nombre') or ('Aprendizaje: ' + (mensaje[:52] + ('...' if len(mensaje) > 52 else '')))).strip()
    contexto = data.get('contexto') or {}
    with DB() as db:
        recurso = db.execute("""
            INSERT INTO ia_recursos (nombre,categoria,marca,hilo,triggers,pregunta_ejemplo,respuesta,archivo_url,notas,prioridad,activo,auto_aprendido,fecha,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,TRUE,%s,%s)
            RETURNING *
        """, (nombre,categoria,(contexto.get('marca') if isinstance(contexto,dict) else '') or '',(contexto.get('hilo') if isinstance(contexto,dict) else '') or '',triggers,mensaje,respuesta_humana,'', 'Respuesta guardada desde intervención humana. Respuesta IA anterior: ' + respuesta_ia[:500], 95, now_mexico(), now_mexico())).fetchone()
        pendiente_id = data.get('pendiente_id')
        if pendiente_id:
            db.execute("""
                UPDATE ia_pendientes_humano SET estado=%s,respuesta_humana=%s,recurso_id=%s,updated_at=%s
                WHERE id=%s
            """, ('APRENDIDO', respuesta_humana, recurso['id'], now_mexico(), pendiente_id))
    return jsonify(json_safe({'ok': True, 'recurso': dict(recurso)}))


# ==========================================================
# WhatsApp IA V13 - búsqueda en internet con copia en Biblioteca IA
# ==========================================================
# Cuando el agente no encuentra una respuesta segura en almacén/Biblioteca,
# puede consultar internet usando OpenAI Web Search y guardar una copia como
# recurso de Biblioteca IA para reutilizarla después.
# Seguridad: NO usa internet para precios, stock, pagos, comprobantes, datos
# personales ni envíos internos. Esas respuestas deben salir de almacén/reglas.

def _wa_v13_schema():
    _wa_v7_schema()
    try:
        with DB() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS ia_busquedas_web (
                    id SERIAL PRIMARY KEY,
                    consulta TEXT,
                    respuesta TEXT,
                    fuente TEXT,
                    motor TEXT,
                    recurso_id INTEGER,
                    estado TEXT DEFAULT 'GUARDADO',
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for col in [
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS consulta TEXT",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS respuesta TEXT",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS fuente TEXT",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS motor TEXT",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS recurso_id INTEGER",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'GUARDADO'",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE ia_busquedas_web ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            ]:
                db.execute(col)
            db.execute("CREATE INDEX IF NOT EXISTS idx_ia_busquedas_web_fecha ON ia_busquedas_web(updated_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_ia_recursos_internet_cache ON ia_recursos(categoria, activo, updated_at DESC)")
    except Exception as exc:
        print('WARN schema IA web cache:', exc, flush=True)


def _wa_v13_env_bool(name, default='0'):
    val = str(os.environ.get(name, default)).strip().lower()
    return val in ('1','true','si','sí','yes','on','enabled')


def _wa_v13_limpia_respuesta_base(txt):
    t = str(txt or '').strip()
    # Evita guardar mensajes técnicos o rutas en cache de internet.
    t = re.sub(r'\n\s*📎[\s\S]*$', '', t).strip()
    return t


def _wa_v13_es_dato_interno(texto):
    """Cosas que NUNCA se deben buscar en internet porque deben salir de Hilorama."""
    try:
        t = _v6_norm(texto or '')
    except Exception:
        t = str(texto or '').lower()
    patrones_bloqueo = [
        r'\b(cuanto|cuánto|precio|cuesta|costo|vale|sale)\b',
        r'\b(stock|existencia|disponible|disponibilidad|tienen|hay)\b',
        r'\b(envio|envío|envios|envíos|paqueteria|paquetería|cp|codigo postal|código postal|fedex|estafeta|correos)\b',
        r'\b(pago|pagar|transferencia|mercado pago|mercadopago|clabe|cuenta|comprobante|deposito|depósito)\b',
        r'\b(direccion|dirección|calle|colonia|telefono|teléfono|nombre completo|datos)\b',
        r'\b(gama|carta|catalogo|catálogo|foto|imagen|mostrar|muestrame|muéstrame)\b.*\b(velluto|komfy|kurumi|tono|codigo|código)\b',
    ]
    return any(re.search(p, t, re.I) for p in patrones_bloqueo)


def _wa_v13_es_pregunta_de_conocimiento(texto):
    """Casos donde sí puede ayudar buscar contexto externo: qué es un material, marca externa, usos, sustitutos."""
    try:
        t = _v6_norm(texto or '')
    except Exception:
        t = str(texto or '').lower()
    patrones = [
        r'\b(que es|qué es|cual es|cuál es|como es|cómo es|para que sirve|para qué sirve|se usa|usar)\b',
        r'\b(parecido|similar|sustituto|alternativa|equivalente|recomiendas|recomendar)\b',
        r'\b(material|textura|grosor|composicion|composición|rendimiento|aguja|gancho)\b',
        r'\b(manejas|manejan|tienes|tienen)\b.*\b(abuelita|sinfonia|sinfonía|crochet|macrame|macramé|algodon|algodón|chenille|velvet|baby)\b',
    ]
    return any(re.search(p, t, re.I) for p in patrones)


def _wa_v13_respuesta_parece_insuficiente(respuesta):
    r = _v6_norm(respuesta or '') if '_v6_norm' in globals() else str(respuesta or '').lower()
    pistas = [
        'no tengo informacion', 'no tengo información', 'no manejo informacion', 'no manejo información',
        'no lo manejo', 'no la manejamos', 'no me aparece', 'no encontre', 'no encontré',
        'podrias especificar', 'podrías especificar', 'que tipo', 'qué tipo',
        'dime que hilo', 'dime qué hilo', 'no pude', 'revisar antes', 'requiere revision', 'requiere revisión'
    ]
    return any(p in r for p in pistas)


def _wa_v13_buscar_cache_internet(texto):
    """Busca primero una respuesta aprendida/copiada de internet."""
    _wa_v13_schema()
    try:
        recurso = _wa_v7_buscar_recurso(texto, categoria='internet_cache')
        if recurso:
            resp = _wa_v7_respuesta_de_recurso(recurso)
            if resp:
                return recurso, resp
    except Exception as exc:
        print('WARN cache internet IA:', exc, flush=True)
    return None, ''


def _wa_v13_guardar_cache_internet(texto, respuesta, fuente='', motor='openai_web_search'):
    _wa_v13_schema()
    texto = (texto or '').strip()
    respuesta = _wa_v13_limpia_respuesta_base(respuesta)
    if not texto or not respuesta:
        return None
    toks = _wa_v7_tokens(texto)
    triggers = ', '.join(list(dict.fromkeys(toks))[:16])
    nombre = 'Internet: ' + (texto[:58] + ('...' if len(texto) > 58 else ''))
    notas_obj = {
        'origen': 'busqueda_internet_automatica',
        'advertencia': 'Copia guardada automáticamente. Revisar/editar si se usará en automático.',
        'fuente': fuente or '',
        'fecha': str(now_mexico()),
    }
    try:
        with DB() as db:
            # Evita duplicados exactos por pregunta muy parecida.
            existente = db.execute("""
                SELECT id FROM ia_recursos
                WHERE activo=TRUE AND categoria='internet_cache' AND pregunta_ejemplo ILIKE %s
                ORDER BY id DESC LIMIT 1
            """, (texto[:200] + '%',)).fetchone()
            if existente:
                db.execute("""
                    UPDATE ia_recursos SET respuesta=%s, triggers=%s, notas=%s, updated_at=%s
                    WHERE id=%s
                """, (respuesta, triggers, json.dumps(notas_obj, ensure_ascii=False), now_mexico(), existente['id']))
                rid = existente['id']
            else:
                recurso = db.execute("""
                    INSERT INTO ia_recursos
                    (nombre,categoria,marca,hilo,triggers,pregunta_ejemplo,respuesta,archivo_url,grupo,orden,enviar_junto,notas,prioridad,activo,auto_aprendido,fecha,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,TRUE,%s,%s)
                    RETURNING id
                """, (nombre, 'internet_cache', '', '', triggers, texto, respuesta, '', '', 0, False, json.dumps(notas_obj, ensure_ascii=False), 60, now_mexico(), now_mexico())).fetchone()
                rid = recurso['id']
            db.execute("""
                INSERT INTO ia_busquedas_web (consulta,respuesta,fuente,motor,recurso_id,estado,fecha,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (texto, respuesta, fuente or '', motor, rid, 'GUARDADO', now_mexico(), now_mexico()))
            return rid
    except Exception as exc:
        print('WARN guardar cache internet IA:', exc, flush=True)
    return None


def _wa_v13_respuesta_web_openai(texto, contexto=None):
    """Consulta internet con OpenAI Web Search. Devuelve texto corto para WhatsApp."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return '', 'sin_openai_key'
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '90')))
        model = os.environ.get('OPENAI_WEB_MODEL') or os.environ.get('OPENAI_SALES_MODEL') or 'gpt-4o-mini'
        prompt = (
            'Eres asistente de ventas de Hilorama, una mercería mexicana.\n'
            'Busca en internet SOLO para entender productos/materiales externos o dudas generales que no estén en el almacén.\n'
            'No des precios externos, no prometas stock, no inventes que Hilorama maneja un producto.\n'
            'Si el producto no aparece en el almacén de Hilorama, di: "por el momento no me aparece en almacén con ese nombre".\n'
            'Da una explicación breve y una alternativa de venta prudente: pedir foto, proyecto o sugerir revisar opciones similares de Hilorama.\n'
            'Respuesta máxima 3 frases, tono humano de WhatsApp, sin formato técnico.\n\n'
            f'Mensaje de clienta: {texto}\n'
            f'Contexto de Hilorama: {json.dumps(contexto or {}, ensure_ascii=False)[:1200]}'
        )
        # Responses API con herramienta de búsqueda web. Si la cuenta/modelo no lo soporta, cae al except.
        resp = client.responses.create(
            model=model,
            tools=[{"type": "web_search_preview"}],
            input=prompt,
        )
        out = (getattr(resp, 'output_text', None) or '').strip()
        if not out:
            # Compatibilidad si el SDK regresa estructura output[].
            try:
                chunks = []
                for item in getattr(resp, 'output', []) or []:
                    for c in getattr(item, 'content', []) or []:
                        txt = getattr(c, 'text', None)
                        if txt:
                            chunks.append(txt)
                out = '\n'.join(chunks).strip()
            except Exception:
                out = ''
        out = _wa_v13_limpia_respuesta_base(out)
        if not out:
            return '', 'openai_web_sin_texto'
        return out, 'openai_web_search'
    except Exception as exc:
        print('WARN busqueda web OpenAI IA:', exc, flush=True)
        return '', 'openai_web_error:' + str(exc)[:140]


def _wa_v13_debe_buscar_internet(texto, parsed, respuesta_base, motor_base):
    if not _wa_v13_env_bool('OPENAI_WEB_SEARCH_ENABLED', '1'):
        return False
    if not texto or not str(texto).strip():
        return False
    # No buscar si hay pedido concreto detectado, porque ahí manda almacén/parser.
    if parsed.get('pedidos'):
        return False
    # Datos internos se responden con almacén/biblioteca/reglas.
    if _wa_v13_es_dato_interno(texto):
        return False
    # Si hay recurso de biblioteca específico, no buscar.
    try:
        recurso = _wa_v7_buscar_recurso(texto)
        if recurso and str(recurso.get('categoria') or '') not in ('internet_cache', ''):
            return False
    except Exception:
        pass
    # Buscar si la pregunta claramente es de conocimiento externo o si la respuesta base es pobre.
    if _wa_v13_es_pregunta_de_conocimiento(texto):
        return True
    if _wa_v13_respuesta_parece_insuficiente(respuesta_base):
        return True
    return False


_wa_generar_respuesta_v12_core = _generar_respuesta_wa_con_openai

def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    """V13: si no hay respuesta en almacén/biblioteca, busca internet y guarda copia."""
    respuesta_base, motor_base = _wa_generar_respuesta_v12_core(texto, parsed, meta, contexto)

    if not _wa_v13_debe_buscar_internet(texto, parsed, respuesta_base, motor_base):
        return respuesta_base, motor_base + ':v13_sin_web'

    # 1) Cache local antes de pagar otra búsqueda.
    recurso_cache, resp_cache = _wa_v13_buscar_cache_internet(texto)
    if resp_cache:
        return resp_cache, f"internet_cache_v13:{recurso_cache.get('id') if recurso_cache else 'local'}"

    # 2) Búsqueda web real.
    respuesta_web, motor_web = _wa_v13_respuesta_web_openai(texto, contexto)
    if respuesta_web:
        rid = _wa_v13_guardar_cache_internet(texto, respuesta_web, fuente='OpenAI Web Search', motor=motor_web)
        suf = f':guardado_{rid}' if rid else ':no_guardado'
        return respuesta_web, motor_web + suf

    # 3) Si falla internet, no romper el flujo.
    if _wa_v13_respuesta_parece_insuficiente(respuesta_base):
        return (respuesta_base + '\n\nLo dejo en revisión para responderle con seguridad 😊'), motor_base + ':v13_web_fallo_revision'
    return respuesta_base, motor_base + ':v13_web_fallo'


@app.route('/api/ia/web-cache', methods=['GET'])
def ia_web_cache_listar():
    """Lista búsquedas guardadas automáticamente desde internet."""
    _wa_v13_schema()
    limit = min(int(request.args.get('limit') or 100), 300)
    with DB() as db:
        rows = db.execute("""
            SELECT * FROM ia_recursos
            WHERE categoria='internet_cache'
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT %s
        """, (limit,)).fetchall()
    return jsonify(json_safe([dict(r) for r in rows]))


@app.route('/api/whatsapp-ia/buscar-internet', methods=['POST'])
def whatsapp_ia_buscar_internet_manual():
    """Búsqueda manual desde la app para guardar una respuesta en Biblioteca IA."""
    data = request.get_json(force=True) or {}
    texto = (data.get('texto') or data.get('consulta') or '').strip()
    if not texto:
        return jsonify({'ok': False, 'error': 'Falta la consulta.'}), 400
    if _wa_v13_es_dato_interno(texto) and not bool(data.get('forzar')):
        return jsonify({'ok': False, 'error': 'Esta consulta parece de precio/stock/envío/pago. Debe responderse desde almacén o reglas internas, no internet.'}), 400
    respuesta, motor = _wa_v13_respuesta_web_openai(texto, data.get('contexto') or {})
    if not respuesta:
        return jsonify({'ok': False, 'error': 'No se pudo obtener respuesta de internet.', 'motor': motor}), 500
    rid = _wa_v13_guardar_cache_internet(texto, respuesta, fuente='OpenAI Web Search manual', motor=motor)
    return jsonify(json_safe({'ok': True, 'respuesta': respuesta, 'recurso_id': rid, 'motor': motor}))

# -----------------------------------------------------------------------------
# V14 - Memoria de conversación para WhatsApp IA
# -----------------------------------------------------------------------------
# Esta memoria permite que mensajes cortos como "rojo 56", "y el 429?" o
# "mándame ese" usen el contexto anterior de la misma conversación.


def _wa_memoria_schema():
    try:
        with DB() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_contexto_cliente (
                    id SERIAL PRIMARY KEY,
                    clave TEXT UNIQUE,
                    conversacion_id INTEGER,
                    telefono TEXT,
                    cliente_nombre TEXT,
                    marca_actual TEXT,
                    hilo_actual TEXT,
                    ultima_intencion TEXT,
                    ultimo_codigo TEXT,
                    ultimo_color TEXT,
                    pedido_en_proceso TEXT,
                    dudas_pendientes TEXT,
                    historial_resumen TEXT,
                    ultimo_mensaje TEXT,
                    ultima_respuesta TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for col_sql in [
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS clave TEXT UNIQUE",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS conversacion_id INTEGER",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS telefono TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS cliente_nombre TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS marca_actual TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS hilo_actual TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultima_intencion TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultimo_codigo TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultimo_color TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS pedido_en_proceso TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS dudas_pendientes TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS historial_resumen TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultimo_mensaje TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultima_respuesta TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            ]:
                db.execute(col_sql)
            db.execute("CREATE INDEX IF NOT EXISTS idx_wa_contexto_clave ON whatsapp_contexto_cliente(clave)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_wa_contexto_tel ON whatsapp_contexto_cliente(telefono)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_wa_contexto_conv ON whatsapp_contexto_cliente(conversacion_id)")
    except Exception as exc:
        print('WARN schema memoria WA:', exc, flush=True)


def _wa_memoria_clave(conversacion_id=None, telefono=''):
    tel = re.sub(r'\D+', '', str(telefono or ''))
    if tel:
        return 'tel:' + tel[-12:]
    if conversacion_id:
        return 'conv:' + str(conversacion_id)
    return ''


def _wa_memoria_cargar(conversacion_id=None, telefono=''):
    _wa_memoria_schema()
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return {}
    try:
        with DB() as db:
            row = db.execute("SELECT * FROM whatsapp_contexto_cliente WHERE clave=%s LIMIT 1", (clave,)).fetchone()
            return dict(row) if row else {}
    except Exception as exc:
        print('WARN cargar memoria WA:', exc, flush=True)
        return {}


def _wa_memoria_historial_reciente(conversacion_id, limit=8):
    if not conversacion_id:
        return []
    try:
        with DB() as db:
            rows = db.execute("""
                SELECT direccion, texto, respuesta_sugerida, fecha
                FROM whatsapp_mensajes
                WHERE conversacion_id=%s
                ORDER BY fecha DESC, id DESC
                LIMIT %s
            """, (conversacion_id, limit)).fetchall()
        out = []
        for r in reversed([dict(x) for x in rows]):
            if r.get('texto'):
                out.append({'de': 'cliente', 'texto': r.get('texto')})
            if r.get('respuesta_sugerida'):
                out.append({'de': 'hilorama', 'texto': r.get('respuesta_sugerida')})
        return out[-limit:]
    except Exception as exc:
        print('WARN historial reciente WA:', exc, flush=True)
        return []


def _wa_memoria_productos_min():
    try:
        with DB() as db:
            rows = db.execute("""
                SELECT
                    p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                    COALESCE(p.stock,0) AS stock,
                    COALESCE(NULLIF(p.precio,0), NULLIF(pr.venta,0), 0) AS precio_venta
                FROM productos p
                LEFT JOIN precios pr ON pr.marca = p.marca
                ORDER BY p.marca, p.hilo, p.codigo
                LIMIT 15000
            """).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        print('WARN productos memoria WA:', exc, flush=True)
        return []


def _wa_memoria_norm(x):
    try:
        return _v6_norm(x)
    except Exception:
        return re.sub(r'\s+', ' ', str(x or '').lower()).strip()


def _wa_memoria_marca_para_hilo(productos, hilo):
    hn = _wa_memoria_norm(hilo)
    for p in productos or []:
        if _wa_memoria_norm(p.get('hilo')) == hn:
            return str(p.get('marca') or '').strip()
    fam = ''
    try:
        fam = _v6_hilo_family(hilo)
    except Exception:
        fam = hn
    for p in productos or []:
        try:
            if _v6_hilo_family(p.get('hilo')) == fam:
                return str(p.get('marca') or '').strip()
        except Exception:
            pass
    return ''


def _wa_memoria_detectar_hilos_explicitos(texto, productos):
    try:
        return _v6_detect_hilos(texto, productos) or []
    except Exception:
        t = _wa_memoria_norm(texto)
        rules = [
            ('VELLUTO', ['velluto', 'veluto', 'alize']),
            ('KOMFY MINI', ['komfy mini', 'komfi mini', 'konfy mini', 'comfy mini', 'komfy', 'komfi', 'konfy']),
            ('KURUMI', ['kurumi']),
            ('TRAPILLO', ['trapillo', 'kraft']),
            ('KAIRO', ['kairo']),
        ]
        out = []
        hilos_db = []
        for p in productos or []:
            h = str(p.get('hilo') or '').strip()
            if h and h not in hilos_db:
                hilos_db.append(h)
        for canonical, aliases in rules:
            if any(a in t for a in aliases):
                for h in hilos_db:
                    if _wa_memoria_norm(h) == _wa_memoria_norm(canonical) or _wa_memoria_norm(canonical) in _wa_memoria_norm(h):
                        out.append(h)
                        break
        return out


def _wa_memoria_resolver_contexto_para_parser(texto, marca_ui, hilo_ui, memoria, productos):
    hilos_exp = _wa_memoria_detectar_hilos_explicitos(texto, productos)
    memoria = memoria or {}

    # Si el usuario seleccionó manualmente marca/hilo, eso manda.
    if marca_ui or hilo_ui:
        return marca_ui, hilo_ui, {
            'activa': bool(marca_ui or hilo_ui),
            'origen': 'seleccion_manual',
            'marca': marca_ui,
            'hilo': hilo_ui,
            'hilos_mencionados': hilos_exp,
        }

    # Si el mensaje trae un hilo nuevo explícito, cambia el contexto.
    if hilos_exp:
        hilo = hilos_exp[0]
        marca = _wa_memoria_marca_para_hilo(productos, hilo)
        return marca, hilo, {
            'activa': True,
            'origen': 'mensaje_actual',
            'marca': marca,
            'hilo': hilo,
            'hilos_mencionados': hilos_exp,
        }

    # Si no hay hilo explícito, usa la memoria anterior.
    hilo_mem = str(memoria.get('hilo_actual') or '').strip()
    marca_mem = str(memoria.get('marca_actual') or '').strip()
    if hilo_mem or marca_mem:
        return marca_mem, hilo_mem, {
            'activa': True,
            'origen': 'memoria_conversacion',
            'marca': marca_mem,
            'hilo': hilo_mem,
            'ultima_intencion': memoria.get('ultima_intencion'),
            'ultimo_codigo': memoria.get('ultimo_codigo'),
            'ultimo_color': memoria.get('ultimo_color'),
        }

    return '', '', {'activa': False, 'origen': 'sin_contexto', 'hilos_mencionados': hilos_exp}


def _wa_memoria_primer_pedido(parsed):
    pedidos = parsed.get('pedidos') or []
    if pedidos:
        return pedidos[0]
    return {}


def _wa_memoria_derivar_datos(texto, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos):
    pedido = _wa_memoria_primer_pedido(parsed)
    hilos_exp = _wa_memoria_detectar_hilos_explicitos(texto, productos)

    hilo = str(hilo_parser or '').strip()
    marca = str(marca_parser or '').strip()

    if hilos_exp:
        hilo = hilos_exp[0]
        marca = _wa_memoria_marca_para_hilo(productos, hilo) or marca

    if pedido:
        hilo = str(pedido.get('hilo') or hilo or '').strip()
        marca = str(pedido.get('marca') or marca or '').strip()

    # Algunos parsers devuelven contexto inferido aunque no haya pedido.
    try:
        ctx_inf = ((parsed.get('contexto') or {}).get('contexto_inferido') or {})
        if not hilo and ctx_inf.get('hilo'):
            hilo = str(ctx_inf.get('hilo') or '').strip()
        if not marca and ctx_inf.get('marca'):
            marca = str(ctx_inf.get('marca') or '').strip()
    except Exception:
        pass

    # Si el mensaje fue consulta/pedido corto y no hay hilo nuevo, conservar memoria previa.
    if not hilo:
        hilo = str((memoria_previa or {}).get('hilo_actual') or '').strip()
    if not marca:
        marca = str((memoria_previa or {}).get('marca_actual') or '').strip()

    ultimo_codigo = str(pedido.get('codigo') or '').strip()
    ultimo_color = str(pedido.get('color') or '').strip()
    if not ultimo_codigo:
        m = re.search(r'\b(\d{1,4})\b', str(texto or ''))
        ultimo_codigo = m.group(1) if m else str((memoria_previa or {}).get('ultimo_codigo') or '')
    if not ultimo_color:
        ultimo_color = str((memoria_previa or {}).get('ultimo_color') or '')

    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    resumen = []
    if hilo:
        resumen.append('hilo=' + hilo)
    if marca:
        resumen.append('marca=' + marca)
    if pedidos:
        resumen.append('productos=' + ', '.join([f"{p.get('codigo','')} {p.get('color','')} x{p.get('cantidad',1)}" for p in pedidos[:8]]))
    if preguntas:
        resumen.append('dudas=' + '; '.join(map(str, preguntas[:3])))

    return {
        'marca_actual': marca,
        'hilo_actual': hilo,
        'ultima_intencion': (meta or {}).get('intencion') or '',
        'ultimo_codigo': ultimo_codigo,
        'ultimo_color': ultimo_color,
        'pedido_en_proceso': json.dumps(pedidos[:30], ensure_ascii=False),
        'dudas_pendientes': json.dumps(preguntas[:20], ensure_ascii=False),
        'historial_resumen': ' | '.join(resumen)[:1500],
    }


def _wa_memoria_actualizar(conversacion_id, telefono, cliente_nombre, texto, respuesta, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos):
    _wa_memoria_schema()
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return {}
    datos = _wa_memoria_derivar_datos(texto, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos)
    try:
        with DB() as db:
            row = db.execute("""
                INSERT INTO whatsapp_contexto_cliente
                    (clave, conversacion_id, telefono, cliente_nombre, marca_actual, hilo_actual, ultima_intencion,
                     ultimo_codigo, ultimo_color, pedido_en_proceso, dudas_pendientes, historial_resumen,
                     ultimo_mensaje, ultima_respuesta, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (clave) DO UPDATE SET
                    conversacion_id=EXCLUDED.conversacion_id,
                    telefono=EXCLUDED.telefono,
                    cliente_nombre=EXCLUDED.cliente_nombre,
                    marca_actual=EXCLUDED.marca_actual,
                    hilo_actual=EXCLUDED.hilo_actual,
                    ultima_intencion=EXCLUDED.ultima_intencion,
                    ultimo_codigo=EXCLUDED.ultimo_codigo,
                    ultimo_color=EXCLUDED.ultimo_color,
                    pedido_en_proceso=EXCLUDED.pedido_en_proceso,
                    dudas_pendientes=EXCLUDED.dudas_pendientes,
                    historial_resumen=EXCLUDED.historial_resumen,
                    ultimo_mensaje=EXCLUDED.ultimo_mensaje,
                    ultima_respuesta=EXCLUDED.ultima_respuesta,
                    updated_at=EXCLUDED.updated_at
                RETURNING *
            """, (
                clave, conversacion_id, re.sub(r'\D+', '', str(telefono or '')), cliente_nombre,
                datos.get('marca_actual'), datos.get('hilo_actual'), datos.get('ultima_intencion'),
                datos.get('ultimo_codigo'), datos.get('ultimo_color'), datos.get('pedido_en_proceso'),
                datos.get('dudas_pendientes'), datos.get('historial_resumen'),
                str(texto or '')[:2000], str(respuesta or '')[:4000], now_mexico(), now_mexico()
            )).fetchone()
            return dict(row) if row else datos
    except Exception as exc:
        print('WARN actualizar memoria WA:', exc, flush=True)
        return datos


@app.route('/api/whatsapp-ia/memoria', methods=['GET'])
def whatsapp_ia_memoria_ver():
    conversacion_id = request.args.get('conversacion_id') or None
    telefono = request.args.get('telefono') or ''
    return jsonify(json_safe({'ok': True, 'memoria': _wa_memoria_cargar(conversacion_id, telefono)}))


@app.route('/api/whatsapp-ia/memoria/reset', methods=['POST'])
def whatsapp_ia_memoria_reset():
    data = request.get_json(force=True) or {}
    conversacion_id = data.get('conversacion_id')
    telefono = data.get('telefono') or ''
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return jsonify({'ok': False, 'error': 'No hay conversación o teléfono para limpiar.'}), 400
    _wa_memoria_schema()
    try:
        with DB() as db:
            db.execute("DELETE FROM whatsapp_contexto_cliente WHERE clave=%s", (clave,))
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


# -----------------------------------------------------------------------------
# V15 - Cierre amable diferido para mensajes de cortesía (gracias)
# -----------------------------------------------------------------------------
# Regla comercial:
# - Si la clienta solo dice "gracias" o una cortesía de cierre, NO responder al instante.
# - Se programa un mensaje amable para 5 minutos después.
# - Si la clienta escribe algo más antes de esos 5 minutos, se cancela el cierre.
# - Si el mensaje trae indicios de pedido/seguimiento ("me surte 3 blancos"), se procesa normal.

WA_V15_CIERRE_MINUTOS = int(os.environ.get('WA_CIERRE_GRACIAS_MINUTOS', '5') or '5')
WA_V15_CIERRE_TEXTO = os.environ.get(
    'WA_CIERRE_GRACIAS_TEXTO',
    'A sus órdenes 😊 cualquier cosa no dude en escribirme, con gusto le atiendo.'
)


def _wa_v15_norm_txt(texto):
    return re.sub(r'\s+', ' ', _wa_memoria_norm(texto or '')).strip()


def _wa_v15_tiene_indicio_seguir(texto):
    t = _wa_v15_norm_txt(texto)
    # Si aparte del gracias viene pedido, cantidad, producto o acción, NO es cierre.
    patrones = [
        r'\b(dame|deme|me\s+surte|surteme|s[uú]rteme|agrega|agregame|agr[eé]game|quiero|ocupo|necesito|apartame|ap[aá]rteme|cotiza|cotizame|muestra|mandame|m[aá]ndame|foto|tono|color|codigo|c[oó]digo|gama|carta|envio|env[ií]o|cp|pago|comprobante)\b',
        r'\b(velluto|veluto|komfy|komfi|kurumi|trapillo|kairo|alize|karina)\b',
        r'\b\d{1,4}\b',
        r'\b(blanco|negro|rojo|rosa|azul|verde|amarillo|hueso|beige|cafe|caf[eé]|gris|morado|lila|naranja)\b',
    ]
    return any(re.search(p, t) for p in patrones)


def _wa_v15_es_cortesia_cierre(texto):
    t = _wa_v15_norm_txt(texto)
    if not t:
        return False
    if _wa_v15_tiene_indicio_seguir(t):
        return False
    # Solo frases cortas tipo cierre. "ok" solo puede ser ambiguo, por eso se acepta
    # principalmente si va acompañado de gracias o expresiones de cierre.
    frases = {
        'gracias', 'muchas gracias', 'mil gracias', 'ok gracias', 'okay gracias', 'oki gracias',
        'vale gracias', 'va gracias', 'sale gracias', 'perfecto gracias', 'listo gracias',
        'esta bien gracias', 'está bien gracias', 'muy amable', 'gracias muy amable',
        'excelente gracias', 'super gracias', 'súper gracias', 'gracias bonita', 'gracias amigo',
        'gracias amiga', 'gracias linda', 'gracias que amable', 'gracias por la informacion',
        'gracias por la información', 'muchas gracias por la informacion', 'muchas gracias por la información',
    }
    if t in frases:
        return True
    return bool(re.fullmatch(r'(muchas\s+)?gracias(\s+(muy\s+)?amable)?', t))


def _wa_v15_programados_schema():
    try:
        with DB() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS whatsapp_mensajes_programados (
                    id SERIAL PRIMARY KEY,
                    clave TEXT,
                    conversacion_id INTEGER,
                    telefono TEXT,
                    tipo TEXT DEFAULT 'cierre_gracias',
                    mensaje TEXT,
                    programado_para TIMESTAMP,
                    estado TEXT DEFAULT 'pendiente',
                    motivo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for col in [
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS clave TEXT",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS conversacion_id INTEGER",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS telefono TEXT",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS tipo TEXT DEFAULT 'cierre_gracias'",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS mensaje TEXT",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS programado_para TIMESTAMP",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'pendiente'",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS motivo TEXT",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE whatsapp_mensajes_programados ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            ]:
                db.execute(col)
            db.execute("CREATE INDEX IF NOT EXISTS idx_wa_prog_clave_estado ON whatsapp_mensajes_programados(clave, estado)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_wa_prog_due ON whatsapp_mensajes_programados(estado, programado_para)")
    except Exception as exc:
        print('WARN schema mensajes programados WA:', exc, flush=True)


def _wa_v15_ensure_conversacion(conversacion_id=None, telefono='', cliente_nombre=''):
    try:
        with DB() as db:
            if conversacion_id:
                conv = db.execute("""
                    UPDATE whatsapp_conversaciones
                    SET cliente_nombre=%s, telefono=%s, ultima_actualizacion=%s, estado=%s
                    WHERE id=%s
                    RETURNING id
                """, (cliente_nombre, telefono, now_mexico(), 'SIMULADOR', conversacion_id)).fetchone()
                if conv:
                    return conv['id']
            conv = db.execute("""
                INSERT INTO whatsapp_conversaciones (telefono, cliente_nombre, origen, estado, fecha, ultima_actualizacion)
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (telefono, cliente_nombre, 'SIMULADOR', 'SIMULADOR', now_mexico(), now_mexico())).fetchone()
            return conv['id'] if conv else conversacion_id
    except Exception as exc:
        print('WARN ensure conv WA:', exc, flush=True)
        return conversacion_id


def _wa_v15_cancelar_cierres(conversacion_id=None, telefono='', motivo='cliente_continuo'):
    _wa_v15_programados_schema()
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return 0
    try:
        with DB() as db:
            row = db.execute("""
                UPDATE whatsapp_mensajes_programados
                SET estado='cancelado', motivo=%s, updated_at=%s
                WHERE clave=%s AND estado='pendiente' AND tipo='cierre_gracias'
                RETURNING id
            """, (motivo, now_mexico(), clave)).fetchall()
            return len(row or [])
    except Exception as exc:
        print('WARN cancelar cierre WA:', exc, flush=True)
        return 0


def _wa_v15_programar_cierre(conversacion_id=None, telefono='', mensaje=None, minutos=None):
    _wa_v15_programados_schema()
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return None
    minutos = int(minutos or WA_V15_CIERRE_MINUTOS)
    msg = mensaje or WA_V15_CIERRE_TEXTO
    due = now_mexico() + timedelta(minutes=minutos)
    try:
        with DB() as db:
            # Solo debe existir un cierre pendiente por conversación.
            db.execute("""
                UPDATE whatsapp_mensajes_programados
                SET estado='cancelado', motivo='reprogramado', updated_at=%s
                WHERE clave=%s AND estado='pendiente' AND tipo='cierre_gracias'
            """, (now_mexico(), clave))
            row = db.execute("""
                INSERT INTO whatsapp_mensajes_programados
                    (clave, conversacion_id, telefono, tipo, mensaje, programado_para, estado, motivo, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
            """, (clave, conversacion_id, re.sub(r'\D+', '', str(telefono or '')), 'cierre_gracias', msg, due, 'pendiente', 'gracias_sin_indicio_seguir', now_mexico(), now_mexico())).fetchone()
            return dict(row) if row else {'mensaje': msg, 'programado_para': due}
    except Exception as exc:
        print('WARN programar cierre WA:', exc, flush=True)
        return {'mensaje': msg, 'programado_para': due, 'error': str(exc)}


@app.route('/api/whatsapp-ia/cierres-pendientes', methods=['GET'])
def whatsapp_ia_cierres_pendientes():
    """Lista cierres ya vencidos. Cuando exista WhatsApp Cloud API, este endpoint servirá para enviarlos."""
    _wa_v15_programados_schema()
    limit = min(int(request.args.get('limit') or 50), 200)
    try:
        with DB() as db:
            rows = db.execute("""
                SELECT * FROM whatsapp_mensajes_programados
                WHERE estado='pendiente' AND programado_para <= %s
                ORDER BY programado_para ASC
                LIMIT %s
            """, (now_mexico(), limit)).fetchall()
        return jsonify(json_safe({'ok': True, 'cierres': [dict(r) for r in rows]}))
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/whatsapp-ia/cierre-marcar-enviado', methods=['POST'])
def whatsapp_ia_cierre_marcar_enviado():
    data = request.get_json(force=True) or {}
    rid = data.get('id')
    if not rid:
        return jsonify({'ok': False, 'error': 'Falta id'}), 400
    _wa_v15_programados_schema()
    try:
        with DB() as db:
            db.execute("""
                UPDATE whatsapp_mensajes_programados
                SET estado='enviado', updated_at=%s
                WHERE id=%s
            """, (now_mexico(), rid))
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


def whatsapp_ia_simular_v15():
    data = request.get_json(force=True) or {}
    texto = (data.get('texto') or '').strip()
    marca = (data.get('marca') or '').strip()
    hilo = (data.get('hilo') or '').strip()
    cliente_nombre = (data.get('cliente_nombre') or '').strip()
    telefono = (data.get('telefono') or '').strip()
    texto_imagen = (data.get('texto_imagen') or '').strip()
    imagen_referencia = bool(data.get('imagen_referencia'))
    conversacion_id = data.get('conversacion_id')
    nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

    texto_total = ' '.join(x for x in [texto, texto_imagen] if x).strip()
    if not texto_total:
        return jsonify({'ok': False, 'error': 'Escribe o pega un mensaje de clienta primero.'}), 400

    memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)

    # Si la clienta continuó con un pedido o pregunta, cancelar cierres pendientes.
    if not _wa_v15_es_cortesia_cierre(texto_total):
        _wa_v15_cancelar_cierres(conversacion_id, telefono, 'cliente_envio_nuevo_mensaje')

    # Caso especial: solo agradecimiento/cierre. No responder al instante; programar cierre.
    if _wa_v15_es_cortesia_cierre(texto_total):
        if nueva_conversacion:
            conversacion_id = None
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id, telefono, cliente_nombre)
        cierre = _wa_v15_programar_cierre(conversacion_id, telefono)
        try:
            with DB() as db:
                db.execute("""
                    INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (conversacion_id, 'IN', 'texto', texto_total, '', json.dumps({'motor': 'cierre_diferido_v15', 'cierre_programado': cierre}, ensure_ascii=False)))
        except Exception as exc:
            print('WARN guardar gracias WA:', exc, flush=True)
        # Actualiza solo último mensaje sin borrar contexto de producto/hilo.
        try:
            with DB() as db:
                clave = _wa_memoria_clave(conversacion_id, telefono)
                if clave:
                    db.execute("""
                        INSERT INTO whatsapp_contexto_cliente
                            (clave, conversacion_id, telefono, cliente_nombre, marca_actual, hilo_actual, ultima_intencion,
                             ultimo_codigo, ultimo_color, pedido_en_proceso, dudas_pendientes, historial_resumen,
                             ultimo_mensaje, ultima_respuesta, created_at, updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (clave) DO UPDATE SET
                            conversacion_id=EXCLUDED.conversacion_id,
                            telefono=EXCLUDED.telefono,
                            cliente_nombre=EXCLUDED.cliente_nombre,
                            ultimo_mensaje=EXCLUDED.ultimo_mensaje,
                            updated_at=EXCLUDED.updated_at
                    """, (
                        clave, conversacion_id, re.sub(r'\D+', '', str(telefono or '')), cliente_nombre,
                        (memoria_previa or {}).get('marca_actual'), (memoria_previa or {}).get('hilo_actual'), (memoria_previa or {}).get('ultima_intencion'),
                        (memoria_previa or {}).get('ultimo_codigo'), (memoria_previa or {}).get('ultimo_color'),
                        (memoria_previa or {}).get('pedido_en_proceso'), (memoria_previa or {}).get('dudas_pendientes'), (memoria_previa or {}).get('historial_resumen'),
                        texto_total[:2000], (memoria_previa or {}).get('ultima_respuesta'), now_mexico(), now_mexico()
                    ))
        except Exception as exc:
            print('WARN actualizar memoria gracias WA:', exc, flush=True)
        return jsonify(json_safe({
            'ok': True,
            'conversacion_id': conversacion_id,
            'motor': 'cierre_diferido_v15',
            'mensaje_cliente': texto_total,
            'respuesta_sugerida': '',
            'respuesta_diferida': WA_V15_CIERRE_TEXTO,
            'cierre_programado': True,
            'cierre_minutos': WA_V15_CIERRE_MINUTOS,
            'programado_para': cierre.get('programado_para') if isinstance(cierre, dict) else None,
            'intencion': 'cortesia_cierre',
            'confianza': 'alta',
            'accion_recomendada': 'esperar_y_cerrar_si_no_responde',
            'puede_auto_enviar': False,
            'pedidos': [],
            'preguntas': [],
            'errores': [],
            'advertencias': ['No responder inmediatamente. Si la clienta no escribe algo más, enviar el cierre después del tiempo programado.'],
            'parser': {},
            'memoria_usada': memoria_previa,
            'memoria_actual': _wa_memoria_cargar(conversacion_id, telefono),
        }))

    productos_mem = _wa_memoria_productos_min()
    marca_parser, hilo_parser, memoria_aplicada = _wa_memoria_resolver_contexto_para_parser(
        texto_total, marca, hilo, memoria_previa, productos_mem
    )

    parser_payload = {
        'texto': texto,
        'marca': marca_parser,
        'hilo': hilo_parser,
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'texto_imagen': texto_imagen,
        'imagen_referencia': imagen_referencia,
    }
    parsed, status = _call_parser_whatsapp_local(parser_payload)
    if status >= 400 or not parsed.get('ok', False):
        return jsonify(parsed), status

    meta = _clasificar_intencion_wa(texto_total, parsed)
    contexto = {
        'marca': marca_parser or marca or 'Todas',
        'hilo': hilo_parser or hilo or 'Todos',
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'fase': 'simulador_manual_pre_whatsapp_cloud_api',
        'memoria_conversacion': memoria_aplicada,
        'historial_reciente': _wa_memoria_historial_reciente(conversacion_id) if conversacion_id and not nueva_conversacion else [],
        'regla_cierre': f'Si la clienta solo agradece, no responder de inmediato; programar cierre en {WA_V15_CIERRE_MINUTOS} minutos.',
    }
    respuesta, motor = _generar_respuesta_wa_con_openai(texto_total, parsed, meta, contexto)

    try:
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id if not nueva_conversacion else None, telefono, cliente_nombre)
        with DB() as db:
            db.execute("""
                INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (conversacion_id, 'IN', 'texto', texto_total, respuesta, json.dumps({'parsed': parsed, 'meta': meta, 'motor': motor, 'memoria_usada': memoria_aplicada}, ensure_ascii=False)))
    except Exception as exc:
        print('WARN no se pudo guardar simulacion WA v15:', exc, flush=True)

    memoria_actualizada = _wa_memoria_actualizar(
        conversacion_id=conversacion_id,
        telefono=telefono,
        cliente_nombre=cliente_nombre,
        texto=texto_total,
        respuesta=respuesta,
        parsed=parsed,
        meta=meta,
        marca_parser=marca_parser,
        hilo_parser=hilo_parser,
        memoria_previa=memoria_previa,
        productos=productos_mem,
    )

    return jsonify(json_safe({
        'ok': True,
        'conversacion_id': conversacion_id,
        'motor': motor + ':memoria_v15_cierre',
        'mensaje_cliente': texto_total,
        'respuesta_sugerida': respuesta,
        'intencion': meta.get('intencion'),
        'confianza': meta.get('confianza'),
        'accion_recomendada': meta.get('accion_recomendada'),
        'puede_auto_enviar': meta.get('puede_auto_enviar'),
        'pedidos': parsed.get('pedidos') or [],
        'preguntas': parsed.get('preguntas') or [],
        'errores': parsed.get('errores') or [],
        'advertencias': parsed.get('advertencias') or [],
        'parser': parsed,
        'memoria_usada': memoria_aplicada,
        'memoria_actual': memoria_actualizada,
    }))


# Sobrescribe el endpoint del simulador para usar la lógica V15 sin perder compatibilidad.
app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v15

# -----------------------------------------------------------------------------
# V16 - Parser WhatsApp real: exportaciones, mensajes por bloques y listas de códigos
# -----------------------------------------------------------------------------
# Mejora casos reales pegados desde WhatsApp:
# - Quita encabezados [hora, fecha] Nombre/Teléfono: para no leer fechas/teléfonos como códigos.
# - Usa solo el último bloque pendiente de la clienta, no toda la conversación vieja.
# - Junta mensajes separados por minutos cuando forman un pedido/lista.
# - Si la clienta dice "lista de colores" y luego manda puros códigos, los interpreta como pedido x1.

WA_V16_MEDIA_MARKERS = {'foto', 'imagen', 'video', 'audio', 'sticker', 'documento', 'archivo'}
WA_V16_OWN_NAMES = {'hilorama', 'tu', 'tú', 'yo'}


def _wa_v16_norm(v):
    try:
        return _v6_norm(v or '')
    except Exception:
        return re.sub(r'\s+', ' ', str(v or '').lower()).strip()


def _wa_v16_es_mensaje_media_o_ruido(txt):
    t = _wa_v16_norm(txt)
    if not t:
        return True
    if t in WA_V16_MEDIA_MARKERS:
        return True
    if re.match(r'^cot[-_\w\d]+\.pdf\b', t):
        return True
    if re.match(r'.+\.(pdf|jpg|jpeg|png|webp|heic|mp4|mp3|opus)\b', t):
        return True
    return False


def _wa_v16_parse_export_whatsapp(raw):
    """Convierte texto exportado/copypaste de WhatsApp en mensajes estructurados."""
    raw = str(raw or '')
    if not raw.strip():
        return []
    # A veces el usuario pega varios extractos separados por coma antes del siguiente encabezado.
    raw = re.sub(r',(?=\[\d{1,2}:\d{2}\s*(?:a|p)\.?\s*m\.?,)', '\n', raw, flags=re.I)
    raw = re.sub(r'(?<!\n)(?=\[\d{1,2}:\d{2}\s*(?:a|p)\.?\s*m\.?,)', '\n', raw, flags=re.I)
    header = re.compile(r'^\s*\[(?P<hora>\d{1,2}:\d{2}\s*(?:a|p)\.?\s*m\.?),\s*(?P<fecha>\d{1,2}/\d{1,2}/\d{4})\]\s*(?P<sender>[^:\n]{1,120}):\s*(?P<msg>.*)$', re.I)
    mensajes = []
    actual = None
    for line in raw.splitlines():
        m = header.match(line)
        if m:
            if actual:
                actual['texto'] = actual.get('texto', '').strip()
                mensajes.append(actual)
            sender = (m.group('sender') or '').strip()
            msg = (m.group('msg') or '').strip()
            actual = {
                'hora': m.group('hora'),
                'fecha': m.group('fecha'),
                'sender': sender,
                'texto': msg,
                'own': _wa_v16_norm(sender) in WA_V16_OWN_NAMES or 'hilorama' in _wa_v16_norm(sender),
                'telefono': re.sub(r'\D+', '', sender) if '+' in sender or re.search(r'\d{7,}', sender) else '',
            }
        else:
            if actual is not None:
                actual['texto'] = (actual.get('texto') or '') + ('\n' if actual.get('texto') else '') + line.strip()
            elif line.strip():
                # No parece export, pero conservamos como mensaje suelto para compatibilidad.
                mensajes.append({'sender': '', 'texto': line.strip(), 'own': False, 'telefono': ''})
    if actual:
        actual['texto'] = actual.get('texto', '').strip()
        mensajes.append(actual)
    # Si no detectó encabezados reales, no es export.
    if not any(m.get('sender') for m in mensajes):
        return []
    return mensajes


def _wa_v16_extraer_bloque_cliente(raw, telefono_actual=''):
    mensajes = _wa_v16_parse_export_whatsapp(raw)
    if not mensajes:
        return {'es_export': False, 'texto_cliente': str(raw or '').strip(), 'telefono': telefono_actual or '', 'cliente_nombre': ''}

    # Busca el último mensaje NO propio. Si el último mensaje del chat es de Hilorama,
    # se toma el último bloque de clienta anterior solo para simular; en WhatsApp real no respondería a algo ya contestado.
    idx = None
    for i in range(len(mensajes) - 1, -1, -1):
        if not mensajes[i].get('own'):
            idx = i
            break
    if idx is None:
        return {'es_export': True, 'texto_cliente': '', 'telefono': telefono_actual or '', 'cliente_nombre': ''}

    # Junta mensajes consecutivos de clienta antes de que Hilorama responda.
    sender_obj = mensajes[idx].get('sender') or ''
    bloque = []
    j = idx
    while j >= 0 and not mensajes[j].get('own'):
        # Si vienen diferentes clientas mezcladas en el pegado, no mezclar.
        if sender_obj and mensajes[j].get('sender') and mensajes[j].get('sender') != sender_obj:
            break
        txt = (mensajes[j].get('texto') or '').strip()
        if txt and not _wa_v16_es_mensaje_media_o_ruido(txt):
            bloque.append(txt)
        j -= 1
    bloque.reverse()

    # Si el bloque último solo dice ok/gracias/muy bien, busca si en el mismo bloque hay algo accionable anterior.
    # Si no, se deja para cierre diferido V15.
    texto_cliente = '\n'.join(bloque).strip()
    tel = telefono_actual or mensajes[idx].get('telefono') or ''
    nombre = '' if mensajes[idx].get('telefono') else (mensajes[idx].get('sender') or '')
    return {
        'es_export': True,
        'texto_cliente': texto_cliente,
        'telefono': tel,
        'cliente_nombre': nombre,
        'mensajes_total': len(mensajes),
        'sender': sender_obj,
        'ultimo_mensaje_era_de_hilorama': bool(mensajes and mensajes[-1].get('own')),
    }


def _wa_v16_es_lista_codigos_pura(texto):
    t = _wa_v16_norm(texto)
    if not t:
        return False
    # Debe tener varios números de 2-4 dígitos y pocas palabras. Sirve para listas tipo:
    # 60\n310\n107\n329...
    nums = re.findall(r'(?<!\d)\d{1,4}(?!\d)', t)
    palabras = [p for p in re.findall(r'[a-zñ]+', t) if p not in ('x', 'de', 'del')]
    if len(nums) >= 3 and len(palabras) <= 8:
        return True
    return False


def _wa_v16_preparar_texto_parser(texto_cliente, memoria_previa=None):
    """Ajusta el mensaje para que el parser entienda intención real de venta."""
    texto_cliente = str(texto_cliente or '').strip()
    if not texto_cliente:
        return texto_cliente
    lineas = [l.strip() for l in texto_cliente.splitlines() if l.strip()]
    t = _wa_v16_norm(texto_cliente)

    # Caso muy común: "le paso la lista de los colores" + mensaje siguiente con códigos.
    pide_lista = bool(re.search(r'\b(lista|tonos|colores|codigos|códigos)\b', t) and re.search(r'\b(le\s+paso|paso|mando|envio|envío|serian|serían|estos|son)\b', t))
    nums = re.findall(r'(?<!\d)\d{1,4}(?!\d)', texto_cliente)
    if (pide_lista and len(nums) >= 2) or _wa_v16_es_lista_codigos_pura(texto_cliente):
        # Evita que palabras como "colores" disparen carta/foto. Lo convertimos a pedido x1.
        solo_nums = '\n'.join(nums)
        return 'quiero 1 de cada uno:\n' + solo_nums

    # Si la memoria dice que la clienta estaba armando pedido y ahora manda puros códigos,
    # interpretarlos como lista, no como consulta de foto de tono.
    mem = memoria_previa or {}
    if _wa_v16_es_lista_codigos_pura(texto_cliente) and str(mem.get('hilo_actual') or '').strip():
        return 'quiero 1 de cada uno:\n' + '\n'.join(nums)

    return texto_cliente


def whatsapp_ia_simular_v16():
    data = request.get_json(force=True) or {}
    texto_original = (data.get('texto') or '').strip()
    marca = (data.get('marca') or '').strip()
    hilo = (data.get('hilo') or '').strip()
    cliente_nombre = (data.get('cliente_nombre') or '').strip()
    telefono = (data.get('telefono') or '').strip()
    texto_imagen = (data.get('texto_imagen') or '').strip()
    imagen_referencia = bool(data.get('imagen_referencia'))
    conversacion_id = data.get('conversacion_id')
    nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

    export_info = _wa_v16_extraer_bloque_cliente(texto_original, telefono)
    texto_cliente = (export_info.get('texto_cliente') or texto_original).strip()
    telefono = telefono or export_info.get('telefono') or ''
    cliente_nombre = cliente_nombre or export_info.get('cliente_nombre') or ''

    texto_total_preview = ' '.join(x for x in [texto_cliente, texto_imagen] if x).strip()
    if not texto_total_preview:
        return jsonify({'ok': False, 'error': 'No encontré un mensaje pendiente de clienta para responder.'}), 400

    memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)
    texto_parser_base = _wa_v16_preparar_texto_parser(texto_cliente, memoria_previa)
    texto_total = ' '.join(x for x in [texto_parser_base, texto_imagen] if x).strip()

    # Si la clienta continuó con un pedido o pregunta, cancelar cierres pendientes.
    if not _wa_v15_es_cortesia_cierre(texto_total_preview):
        _wa_v15_cancelar_cierres(conversacion_id, telefono, 'cliente_envio_nuevo_mensaje')

    # Caso especial: solo agradecimiento/cierre. No responder al instante; programar cierre.
    if _wa_v15_es_cortesia_cierre(texto_total_preview):
        if nueva_conversacion:
            conversacion_id = None
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id, telefono, cliente_nombre)
        cierre = _wa_v15_programar_cierre(conversacion_id, telefono)
        try:
            with DB() as db:
                db.execute("""
                    INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (conversacion_id, 'IN', 'texto', texto_total_preview, '', json.dumps({'motor': 'cierre_diferido_v16', 'cierre_programado': cierre, 'export_info': export_info}, ensure_ascii=False)))
        except Exception as exc:
            print('WARN guardar gracias WA v16:', exc, flush=True)
        return jsonify(json_safe({
            'ok': True,
            'conversacion_id': conversacion_id,
            'motor': 'cierre_diferido_v16',
            'mensaje_cliente': texto_total_preview,
            'respuesta_sugerida': '',
            'respuesta_diferida': WA_V15_CIERRE_TEXTO,
            'cierre_programado': True,
            'cierre_minutos': WA_V15_CIERRE_MINUTOS,
            'programado_para': cierre.get('programado_para') if isinstance(cierre, dict) else None,
            'intencion': 'cortesia_cierre',
            'confianza': 'alta',
            'accion_recomendada': 'esperar_y_cerrar_si_no_responde',
            'puede_auto_enviar': False,
            'pedidos': [], 'preguntas': [], 'errores': [],
            'advertencias': ['No responder inmediatamente. Si la clienta no escribe algo más, enviar el cierre después del tiempo programado.'],
            'parser': {},
            'memoria_usada': memoria_previa,
            'memoria_actual': _wa_memoria_cargar(conversacion_id, telefono),
            'whatsapp_export': export_info,
        }))

    productos_mem = _wa_memoria_productos_min()
    marca_parser, hilo_parser, memoria_aplicada = _wa_memoria_resolver_contexto_para_parser(
        texto_total, marca, hilo, memoria_previa, productos_mem
    )

    parser_payload = {
        'texto': texto_total,
        'marca': marca_parser,
        'hilo': hilo_parser,
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'texto_imagen': '',
        'imagen_referencia': imagen_referencia,
    }
    parsed, status = _call_parser_whatsapp_local(parser_payload)
    if status >= 400 or not parsed.get('ok', False):
        return jsonify(parsed), status

    meta = _clasificar_intencion_wa(texto_total, parsed)
    contexto = {
        'marca': marca_parser or marca or 'Todas',
        'hilo': hilo_parser or hilo or 'Todos',
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'fase': 'simulador_manual_pre_whatsapp_cloud_api',
        'memoria_conversacion': memoria_aplicada,
        'historial_reciente': _wa_memoria_historial_reciente(conversacion_id) if conversacion_id and not nueva_conversacion else [],
        'regla_cierre': f'Si la clienta solo agradece, no responder de inmediato; programar cierre en {WA_V15_CIERRE_MINUTOS} minutos.',
        'whatsapp_export': export_info,
        'mensaje_original_cliente': texto_cliente,
        'mensaje_parser_v16': texto_total,
    }
    respuesta, motor = _generar_respuesta_wa_con_openai(texto_total, parsed, meta, contexto)

    try:
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id if not nueva_conversacion else None, telefono, cliente_nombre)
        with DB() as db:
            db.execute("""
                INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (conversacion_id, 'IN', 'texto', texto_total_preview, respuesta, json.dumps({'parsed': parsed, 'meta': meta, 'motor': motor, 'memoria_usada': memoria_aplicada, 'v16_texto_parser': texto_total, 'export_info': export_info}, ensure_ascii=False)))
    except Exception as exc:
        print('WARN no se pudo guardar simulacion WA v16:', exc, flush=True)

    memoria_actualizada = _wa_memoria_actualizar(
        conversacion_id=conversacion_id,
        telefono=telefono,
        cliente_nombre=cliente_nombre,
        texto=texto_total_preview,
        respuesta=respuesta,
        parsed=parsed,
        meta=meta,
        marca_parser=marca_parser,
        hilo_parser=hilo_parser,
        memoria_previa=memoria_previa,
        productos=productos_mem,
    )

    advertencias = parsed.get('advertencias') or []
    if export_info.get('es_export'):
        advertencias = list(advertencias) + [f"V16: se leyó solo el último bloque pendiente de la clienta ({export_info.get('sender') or 'sin nombre'})."]
        if export_info.get('ultimo_mensaje_era_de_hilorama'):
            advertencias.append('V16: el último mensaje del pegado parece ser de Hilorama; en WhatsApp real no se respondería hasta que la clienta escriba otra vez.')
    if texto_total != texto_total_preview:
        advertencias = list(advertencias) + ['V16: lista de códigos normalizada como pedido de 1 pieza por código.']

    return jsonify(json_safe({
        'ok': True,
        'conversacion_id': conversacion_id,
        'motor': motor + ':memoria_v16_parser_whatsapp_real',
        'mensaje_cliente': texto_total_preview,
        'mensaje_parser': texto_total,
        'respuesta_sugerida': respuesta,
        'intencion': meta.get('intencion'),
        'confianza': meta.get('confianza'),
        'accion_recomendada': meta.get('accion_recomendada'),
        'puede_auto_enviar': meta.get('puede_auto_enviar'),
        'pedidos': parsed.get('pedidos') or [],
        'preguntas': parsed.get('preguntas') or [],
        'errores': parsed.get('errores') or [],
        'advertencias': advertencias,
        'parser': parsed,
        'memoria_usada': memoria_aplicada,
        'memoria_actual': memoria_actualizada,
        'whatsapp_export': export_info,
    }))


# Sobrescribe el endpoint del simulador para usar V16.
app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v16

# -----------------------------------------------------------------------------
# V17 - Parser WhatsApp de listas reales: no quedarse solo con el primer código
# -----------------------------------------------------------------------------
# Corrige casos reales donde la clienta manda:
# "le paso la lista de colores" y luego códigos uno por línea.
# También entiende líneas tipo "550 x2", "216 canario - 4", "Blanco 01- 2".

WA_V17_CORTESIA_LINEA = {
    'ok', 'oki', 'okay', 'va', 'vale', 'muy bien', 'perfecto', 'gracias',
    'muchas gracias', 'si', 'sí', 'si por favor', 'sí por favor', 'por favor'
}


def _wa_v17_norm(v):
    try:
        return _v6_norm(v or '')
    except Exception:
        return re.sub(r'\s+', ' ', str(v or '').lower()).strip()


def _wa_v17_es_linea_ruido(linea):
    t = _wa_v17_norm(linea)
    if not t:
        return True
    if t in WA_V17_CORTESIA_LINEA:
        return True
    if _wa_v16_es_mensaje_media_o_ruido(linea):
        return True
    # Mensajes que abren una lista, pero no son producto.
    if re.search(r'\b(le\s+paso|paso|mando|envio|envío|lista|colores|tonos|porfavor|por\s+favor)\b', t) and not re.search(r'\d', t):
        return True
    return False


def _wa_v17_linea_a_item(linea):
    """Devuelve items de una línea de pedido real de WhatsApp.

    Soporta:
    - 60
    - 550 x2
    - 60 x 2
    - 216 canario - 4
    - Blanco 01- 2
    - Rojo escolar- 2
    """
    raw = str(linea or '').strip().strip(',.;')
    if not raw:
        return []
    s = raw.replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s).strip()
    t = _wa_v17_norm(s)
    if _wa_v17_es_linea_ruido(s):
        return []

    # Una línea puede traer varios códigos separados por espacios/comas: "60 310 107".
    if re.fullmatch(r'(?:\d{1,4}\s*[,\s]+){1,}\d{1,4}', s):
        return [{'codigo': c.lstrip('0') or c, 'cantidad': 1, 'desc': '', 'raw': raw} for c in re.findall(r'\d{1,4}', s)]

    # Código puro: 60
    m = re.fullmatch(r'(\d{1,4})', s)
    if m:
        code = m.group(1)
        return [{'codigo': code.lstrip('0') or code, 'cantidad': 1, 'desc': '', 'raw': raw}]

    # Código x cantidad: 550 x2 / 60 x 2 / 550 por 2
    m = re.fullmatch(r'(\d{1,4})\s*(?:x|por|\*)\s*(\d{1,3})', t)
    if m:
        return [{'codigo': (m.group(1).lstrip('0') or m.group(1)), 'cantidad': int(m.group(2)), 'desc': '', 'raw': raw}]

    # Código color - cantidad: 216 canario - 4
    m = re.fullmatch(r'(\d{1,4})\s+(.+?)\s*-\s*(\d{1,3})', s, flags=re.I)
    if m:
        code = m.group(1)
        return [{'codigo': code.lstrip('0') or code, 'cantidad': int(m.group(3)), 'desc': m.group(2).strip(), 'raw': raw}]

    # Color código - cantidad: Blanco 01- 2 / Rosa bte 185 - 1
    m = re.fullmatch(r'(.+?)\s+(\d{1,4})\s*-\s*(\d{1,3})', s, flags=re.I)
    if m:
        code = m.group(2)
        return [{'codigo': code.lstrip('0') or code, 'cantidad': int(m.group(3)), 'desc': m.group(1).strip(), 'raw': raw}]

    # Color/código con x cantidad: Blanco 01 x2
    m = re.fullmatch(r'(.+?)\s+(\d{1,4})\s*(?:x|por|\*)\s*(\d{1,3})', s, flags=re.I)
    if m:
        code = m.group(2)
        return [{'codigo': code.lstrip('0') or code, 'cantidad': int(m.group(3)), 'desc': m.group(1).strip(), 'raw': raw}]

    # Color - cantidad: Rojo escolar- 2 / Hueso - 1
    m = re.fullmatch(r'(.+?)\s*-\s*(\d{1,3})', s, flags=re.I)
    if m:
        desc = m.group(1).strip()
        if desc and not desc.isdigit():
            return [{'codigo': '', 'cantidad': int(m.group(2)), 'desc': desc, 'raw': raw}]

    return []


def _wa_v17_extraer_items_lista(texto_cliente):
    texto = str(texto_cliente or '').strip()
    if not texto:
        return [], False
    lineas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    if not lineas:
        return [], False
    norm_full = _wa_v17_norm(texto)
    hay_disparador_lista = bool(re.search(r'\b(lista|serian|serían|estos|son|colores|tonos|codigos|códigos)\b', norm_full))

    # Si hay frase tipo "le paso la lista", tomar preferentemente lo que va después de esa frase.
    start = 0
    for i, ln in enumerate(lineas):
        tl = _wa_v17_norm(ln)
        if re.search(r'\b(le\s+paso|paso|mando|envio|envío|lista|serian|serían|estos|son)\b', tl) and re.search(r'\b(colores|tonos|codigos|códigos|lista)\b', tl):
            start = i + 1
    candidatas = lineas[start:] if start < len(lineas) else lineas

    items = []
    lineas_con_item = 0
    for ln in candidatas:
        its = _wa_v17_linea_a_item(ln)
        if its:
            items.extend(its)
            lineas_con_item += 1
        else:
            # Si ya empezó la lista y aparece una línea que no es producto, no la metemos.
            continue

    # También aceptar listas puras aunque no venga la frase "lista".
    lista_pura = lineas_con_item >= 3 and len(items) >= 3
    es_lista = bool((hay_disparador_lista and len(items) >= 2) or lista_pura)
    return items, es_lista


def _wa_v17_producto_dict(prod, cantidad):
    return {
        'producto_id': prod.get('id'),
        'codigo': prod.get('codigo'),
        'marca': prod.get('marca') or '',
        'hilo': prod.get('hilo') or '',
        'color': prod.get('color') or '',
        'stock': int(prod.get('stock') or 0),
        'precio_venta': float(prod.get('precio_venta') or 0),
        'cantidad': int(cantidad or 1),
        'es_inventariable': prod.get('es_inventariable', True),
    }


def _wa_v17_resolver_items_lista(items, productos, marca_parser='', hilo_parser=''):
    pedidos = {}
    preguntas = []
    errores = []
    advertencias = []

    productos_ctx = list(productos or [])
    if marca_parser:
        mn = _wa_v17_norm(marca_parser)
        productos_ctx = [p for p in productos_ctx if _wa_v17_norm(p.get('marca') or '') == mn]
    if hilo_parser:
        productos_ctx = _v6_products_for_hilo(productos_ctx, hilo_parser)

    def add_prod(prod, qty):
        key = str(prod.get('id') or prod.get('codigo') or '') + '|' + str(prod.get('marca') or '') + '|' + str(prod.get('hilo') or '')
        if key in pedidos:
            pedidos[key]['cantidad'] = int(pedidos[key].get('cantidad') or 0) + int(qty or 1)
        else:
            pedidos[key] = _wa_v17_producto_dict(prod, qty)

    for it in items:
        code = str(it.get('codigo') or '').strip().lstrip('0') or str(it.get('codigo') or '').strip()
        desc = str(it.get('desc') or '').strip()
        qty = int(it.get('cantidad') or 1)
        raw = str(it.get('raw') or '').strip()
        prod = None
        opciones = []

        if code:
            matches = (_v6_code_map(productos_ctx).get(code) or [])
            if not matches and not hilo_parser:
                matches = (_v6_code_map(productos or []).get(code) or [])
            # Evitar elegir entre varios hilos si no hay contexto. Si todos son de la misma familia, sí se puede.
            if matches:
                normales = [p for p in matches if not any(x in _wa_v17_norm(p.get('color') or '') for x in ['combo', 'paquete', 'surtido'])]
                matches = normales or matches
                familias = sorted(set(_v6_hilo_family(p.get('hilo') or '') for p in matches))
                if not hilo_parser and len(familias) > 1:
                    opts = ', '.join(sorted(set(str(p.get('hilo') or '') for p in matches))[:5])
                    preguntas.append(f"El código {code} aparece en varios hilos ({opts}). ¿De cuál hilo lo agrego?")
                    continue
                prod = sorted(matches, key=lambda p: int(p.get('stock') or 0), reverse=True)[0]
            else:
                errores.append(code)
                continue
        elif desc:
            if not hilo_parser:
                preguntas.append(f"Para '{raw}' necesito confirmar el hilo antes de agregarlo.")
                continue
            prod, opciones = _wa_resolver_producto_por_color(productos_ctx, desc)
            if not prod and opciones:
                opts = ', '.join([f"{p.get('codigo')} {p.get('color')}".strip() for p in opciones[:5]])
                preguntas.append(f"Para '{desc}' tengo varias opciones: {opts}. ¿Cuál le agrego?")
                continue
            if not prod:
                preguntas.append(f"No ubiqué exacto '{desc}', ¿me confirma código o tono?")
                continue

        if prod:
            add_prod(prod, qty)

    return list(pedidos.values()), preguntas, errores, advertencias


def whatsapp_ia_simular_v17():
    data = request.get_json(force=True) or {}
    texto_original = (data.get('texto') or '').strip()
    marca = (data.get('marca') or '').strip()
    hilo = (data.get('hilo') or '').strip()
    cliente_nombre = (data.get('cliente_nombre') or '').strip()
    telefono = (data.get('telefono') or '').strip()
    texto_imagen = (data.get('texto_imagen') or '').strip()
    imagen_referencia = bool(data.get('imagen_referencia'))
    conversacion_id = data.get('conversacion_id')
    nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

    export_info = _wa_v16_extraer_bloque_cliente(texto_original, telefono)
    texto_cliente = (export_info.get('texto_cliente') or texto_original).strip()
    telefono = telefono or export_info.get('telefono') or ''
    cliente_nombre = cliente_nombre or export_info.get('cliente_nombre') or ''

    texto_total_preview = ' '.join(x for x in [texto_cliente, texto_imagen] if x).strip()
    if not texto_total_preview:
        return jsonify({'ok': False, 'error': 'No encontré un mensaje pendiente de clienta para responder.'}), 400

    memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)

    # Si la clienta continuó con un pedido o pregunta, cancelar cierres pendientes.
    if not _wa_v15_es_cortesia_cierre(texto_total_preview):
        _wa_v15_cancelar_cierres(conversacion_id, telefono, 'cliente_envio_nuevo_mensaje')

    # Caso especial: solo agradecimiento/cierre.
    if _wa_v15_es_cortesia_cierre(texto_total_preview):
        if nueva_conversacion:
            conversacion_id = None
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id, telefono, cliente_nombre)
        cierre = _wa_v15_programar_cierre(conversacion_id, telefono)
        try:
            with DB() as db:
                db.execute("""
                    INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (conversacion_id, 'IN', 'texto', texto_total_preview, '', json.dumps({'motor': 'cierre_diferido_v17', 'cierre_programado': cierre, 'export_info': export_info}, ensure_ascii=False)))
        except Exception as exc:
            print('WARN guardar gracias WA v17:', exc, flush=True)
        return jsonify(json_safe({
            'ok': True,
            'conversacion_id': conversacion_id,
            'motor': 'cierre_diferido_v17',
            'mensaje_cliente': texto_total_preview,
            'respuesta_sugerida': '',
            'respuesta_diferida': WA_V15_CIERRE_TEXTO,
            'cierre_programado': True,
            'cierre_minutos': WA_V15_CIERRE_MINUTOS,
            'programado_para': cierre.get('programado_para') if isinstance(cierre, dict) else None,
            'intencion': 'cortesia_cierre',
            'confianza': 'alta',
            'accion_recomendada': 'esperar_y_cerrar_si_no_responde',
            'puede_auto_enviar': False,
            'pedidos': [], 'preguntas': [], 'errores': [],
            'advertencias': ['No responder inmediatamente. Si la clienta no escribe algo más, enviar el cierre después del tiempo programado.'],
            'parser': {},
            'memoria_usada': memoria_previa,
            'memoria_actual': _wa_memoria_cargar(conversacion_id, telefono),
            'whatsapp_export': export_info,
        }))

    productos_mem = _wa_memoria_productos_min()
    items_lista, es_lista_real = _wa_v17_extraer_items_lista(texto_cliente)

    # Para listas de códigos, resolver contexto ANTES de mandar al parser normal.
    marca_parser, hilo_parser, memoria_aplicada = _wa_memoria_resolver_contexto_para_parser(
        texto_cliente, marca, hilo, memoria_previa, productos_mem
    )

    parsed = None
    status = 200
    texto_parser_base = _wa_v16_preparar_texto_parser(texto_cliente, memoria_previa)
    texto_total = ' '.join(x for x in [texto_parser_base, texto_imagen] if x).strip()
    motor_extra = ''

    if es_lista_real:
        pedidos, preguntas, errores, advertencias = _wa_v17_resolver_items_lista(items_lista, productos_mem, marca_parser, hilo_parser)
        parsed = {
            'ok': True,
            'modo': 'lista_whatsapp_real_v17',
            'modo_especial': 'lista_codigos_colores',
            'contexto': {
                'marca': marca_parser or marca,
                'hilo': hilo_parser or hilo,
                'productos_contexto': len(productos_mem),
                'contexto_inferido': {'marca': marca_parser or marca or '', 'hilo': hilo_parser or hilo or ''},
                'hilos_detectados': [hilo_parser] if hilo_parser else [],
            },
            'pedidos': pedidos,
            'errores': sorted(set(str(e) for e in errores if e)),
            'advertencias': sorted(set(str(a) for a in advertencias if a)),
            'preguntas': sorted(set(str(p) for p in preguntas if p)),
            'sugerencias': {},
            'sugerencias_almacen': [],
            'respuesta_preferida': '',
            'items_lista_v17': items_lista,
        }
        texto_total = 'Lista de pedido detectada:\n' + '\n'.join([str(x.get('raw') or '') for x in items_lista])
        motor_extra = ':lista_real_v17'
    else:
        parser_payload = {
            'texto': texto_total,
            'marca': marca_parser,
            'hilo': hilo_parser,
            'cliente_nombre': cliente_nombre,
            'telefono': telefono,
            'texto_imagen': '',
            'imagen_referencia': imagen_referencia,
        }
        parsed, status = _call_parser_whatsapp_local(parser_payload)
        if status >= 400 or not parsed.get('ok', False):
            return jsonify(parsed), status

    meta = _clasificar_intencion_wa(texto_total, parsed)
    # Si el parser especial encontró pedidos sin dudas, subir confianza.
    if es_lista_real and (parsed.get('pedidos') or []) and not parsed.get('preguntas') and not parsed.get('errores'):
        meta['intencion'] = 'pedido'
        meta['confianza'] = 'alta'
        meta['accion_recomendada'] = 'agregar_productos'
        meta['puede_auto_enviar'] = True

    contexto = {
        'marca': marca_parser or marca or 'Todas',
        'hilo': hilo_parser or hilo or 'Todos',
        'cliente_nombre': cliente_nombre,
        'telefono': telefono,
        'fase': 'simulador_manual_pre_whatsapp_cloud_api',
        'memoria_conversacion': memoria_aplicada,
        'historial_reciente': _wa_memoria_historial_reciente(conversacion_id) if conversacion_id and not nueva_conversacion else [],
        'regla_cierre': f'Si la clienta solo agradece, no responder de inmediato; programar cierre en {WA_V15_CIERRE_MINUTOS} minutos.',
        'whatsapp_export': export_info,
        'mensaje_original_cliente': texto_cliente,
        'mensaje_parser_v17': texto_total,
        'items_lista_v17': items_lista,
    }
    respuesta, motor = _generar_respuesta_wa_con_openai(texto_total, parsed, meta, contexto)

    try:
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id if not nueva_conversacion else None, telefono, cliente_nombre)
        with DB() as db:
            db.execute("""
                INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (conversacion_id, 'IN', 'texto', texto_total_preview, respuesta, json.dumps({'parsed': parsed, 'meta': meta, 'motor': motor + motor_extra, 'memoria_usada': memoria_aplicada, 'v17_texto_parser': texto_total, 'export_info': export_info}, ensure_ascii=False)))
    except Exception as exc:
        print('WARN no se pudo guardar simulacion WA v17:', exc, flush=True)

    memoria_actualizada = _wa_memoria_actualizar(
        conversacion_id=conversacion_id,
        telefono=telefono,
        cliente_nombre=cliente_nombre,
        texto=texto_total_preview,
        respuesta=respuesta,
        parsed=parsed,
        meta=meta,
        marca_parser=marca_parser,
        hilo_parser=hilo_parser,
        memoria_previa=memoria_previa,
        productos=productos_mem,
    )

    advertencias = parsed.get('advertencias') or []
    if export_info.get('es_export'):
        advertencias = list(advertencias) + [f"V17: se leyó solo el último bloque pendiente de la clienta ({export_info.get('sender') or 'sin nombre'})."]
        if export_info.get('ultimo_mensaje_era_de_hilorama'):
            advertencias.append('V17: el último mensaje del pegado parece ser de Hilorama; en WhatsApp real no se respondería hasta que la clienta escriba otra vez.')
    if es_lista_real:
        advertencias = list(advertencias) + [f'V17: lista real detectada con {len(items_lista)} línea(s)/producto(s) antes de llamar al parser normal.']
    elif texto_total != texto_total_preview:
        advertencias = list(advertencias) + ['V17: texto normalizado antes del parser.']

    return jsonify(json_safe({
        'ok': True,
        'conversacion_id': conversacion_id,
        'motor': motor + ':memoria_v17_parser_whatsapp_real' + motor_extra,
        'mensaje_cliente': texto_total_preview,
        'mensaje_parser': texto_total,
        'respuesta_sugerida': respuesta,
        'intencion': meta.get('intencion'),
        'confianza': meta.get('confianza'),
        'accion_recomendada': meta.get('accion_recomendada'),
        'puede_auto_enviar': meta.get('puede_auto_enviar'),
        'pedidos': parsed.get('pedidos') or [],
        'preguntas': parsed.get('preguntas') or [],
        'errores': parsed.get('errores') or [],
        'advertencias': advertencias,
        'parser': parsed,
        'memoria_usada': memoria_aplicada,
        'memoria_actual': memoria_actualizada,
        'whatsapp_export': export_info,
        'items_lista_v17': items_lista if es_lista_real else [],
    }))


# Sobrescribe el endpoint del simulador para usar V17.
app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v17

# -----------------------------------------------------------------------------
# V18 - Parser WhatsApp: listas con encabezado + primer producto en la misma línea
# -----------------------------------------------------------------------------
# Corrige casos como:
# "me puede poner esta lista 550 x2" + líneas siguientes.
# V17 saltaba esa primera línea por traer la palabra "lista" y por eso podía caer
# en respuesta de foto de tono en lugar de armar pedido.


def _wa_v18_limpiar_intro_linea(linea):
    raw = str(linea or '').strip().strip(',.;')
    if not raw:
        return ''
    s = raw.replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s).strip()
    # Quitar encabezados típicos ANTES del primer item, conservando lo que venga después.
    # Ej: "me puede poner esta lista 550 x2" -> "550 x2"
    patrones = [
        r'^.*?\b(?:esta\s+)?lista\b\s*(?:de\s+(?:colores|tonos|codigos|códigos))?\s*(?:por\s*favor|porfavor)?\s*',
        r'^\s*(?:me\s+puede\s+|me\s+podria\s+|me\s+podría\s+)?(?:poner|agregar|apartar|surtir|cotizar)\s*(?:esta|la|mi)?\s*(?:lista)?\s*',
        r'^\s*(?:quiero|dame|deme|ocupo|necesito|agregame|agrégame|ponme)\s+',
        r'^\s*(?:buenas\s+tardes|buen\s+dia|buen\s+día|hola)\s*,?\s*',
    ]
    out = s
    for pat in patrones:
        nuevo = re.sub(pat, '', out, flags=re.I).strip()
        # Solo aceptamos la limpieza si todavía queda algún número o una descripción útil.
        if nuevo and (re.search(r'\d', nuevo) or re.search(r'[a-záéíóúñ]{3,}', nuevo, flags=re.I)):
            out = nuevo
    return out.strip()


def _wa_v18_linea_a_item(linea):
    """Versión más permisiva para líneas de pedido reales."""
    raw = str(linea or '').strip()
    if not raw:
        return []

    # Primero intenta la lógica V17 exacta.
    try:
        items = _wa_v17_linea_a_item(raw)
        if items:
            return items
    except Exception:
        pass

    limpia = _wa_v18_limpiar_intro_linea(raw)
    if limpia and limpia != raw:
        try:
            items = _wa_v17_linea_a_item(limpia)
            if items:
                # Mantener el raw original para que el usuario vea lo que se leyó.
                for it in items:
                    it['raw'] = raw
                return items
        except Exception:
            pass

    # Buscar patrones incrustados dentro de una frase.
    # Ej: "me puede poner esta lista 550 x2".
    s = raw.replace('×', 'x').replace('–', '-').replace('—', '-')
    m = re.search(r'(?<!\d)(\d{1,4})\s*(?:x|por|\*)\s*(\d{1,3})(?!\d)', s, flags=re.I)
    if m:
        return [{'codigo': (m.group(1).lstrip('0') or m.group(1)), 'cantidad': int(m.group(2)), 'desc': '', 'raw': raw}]

    # Ej: "agregue blanco 01- 2".
    m = re.search(r'([A-Za-zÁÉÍÓÚáéíóúÑñ ]{3,})\s+(\d{1,4})\s*-\s*(\d{1,3})(?!\d)', s)
    if m:
        desc = re.sub(r'^.*?\b(?:agregue|agrega|poner|ponme|quiero|dame|deme)\b\s*', '', m.group(1).strip(), flags=re.I).strip()
        return [{'codigo': (m.group(2).lstrip('0') or m.group(2)), 'cantidad': int(m.group(3)), 'desc': desc, 'raw': raw}]

    return []


def _wa_v18_extraer_items_lista(texto_cliente):
    texto = str(texto_cliente or '').strip()
    if not texto:
        return [], False
    lineas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
    if not lineas:
        return [], False

    norm_full = _wa_v17_norm(texto)
    hay_disparador_lista = bool(re.search(r'\b(lista|serian|serían|estos|son|colores|tonos|codigos|códigos)\b', norm_full))
    hay_verbo_pedido = bool(re.search(r'\b(poner|ponme|agregar|agregame|agrégame|apartar|aparta|surtir|surte|cotizar|cotizacion|cotización|quiero|dame|deme|ocupo|necesito|pedido)\b', norm_full))

    items = []
    lineas_con_item = 0
    ya_empezo_lista = False

    for ln in lineas:
        tl = _wa_v17_norm(ln)
        its = _wa_v18_linea_a_item(ln)
        if its:
            items.extend(its)
            lineas_con_item += 1
            ya_empezo_lista = True
            continue
        # Encabezado o cortesía: no rompe la lista.
        if _wa_v17_es_linea_ruido(ln):
            continue
        if re.search(r'\b(lista|colores|tonos|codigos|códigos|serian|serían|estos|son)\b', tl):
            ya_empezo_lista = True
            continue
        # Si ya empezó una lista y llega texto no interpretable, lo ignoramos para no inventar.
        if ya_empezo_lista:
            continue

    # Una lista real puede ser:
    # - frase "lista/colores" + al menos 1 item,
    # - verbo de pedido + al menos 1 item,
    # - varias líneas de códigos sin texto.
    lista_pura = lineas_con_item >= 3 and len(items) >= 3
    es_lista = bool((hay_disparador_lista and len(items) >= 1) or (hay_verbo_pedido and len(items) >= 1) or lista_pura)

    # Evitar confundir consulta de foto/tono de un solo código con pedido/lista.
    if len(items) == 1 and re.search(r'\b(foto|imagen|mostrar|muestra|ver|enseñar|ensena|enseña)\b', norm_full):
        es_lista = False

    return items, es_lista


# Sobrescribe el extractor V17 con el extractor corregido V18.
_wa_v17_extraer_items_lista = _wa_v18_extraer_items_lista


_wa_v18_generar_respuesta_anterior = _generar_respuesta_wa_con_openai


def _wa_v18_respuesta_lista(parsed):
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    if not pedidos:
        return ''
    lineas = []
    total_pzas = 0
    for p in pedidos:
        qty = int(p.get('cantidad') or 1)
        total_pzas += qty
        hilo = str(p.get('hilo') or '').strip()
        codigo = str(p.get('codigo') or '').strip()
        color = str(p.get('color') or '').strip()
        nombre = ' '.join(x for x in [hilo, codigo, color] if x).strip()
        if not nombre:
            nombre = str(p.get('nombre') or 'producto').strip()
        lineas.append(f"- {nombre} x{qty}")
    resp = "Claro 😊 le agrego:\n" + "\n".join(lineas)
    resp += f"\n\nTotal: {total_pzas} pieza" + ("s" if total_pzas != 1 else "") + "."
    if errores:
        resp += "\n\nNo ubiqué estos códigos en almacén: " + ", ".join(str(e) for e in errores) + "."
    if preguntas:
        resp += "\n\n" + "\n".join(str(q) for q in preguntas[:4])
    else:
        resp += "\nLe preparo su cotización."
    return resp


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    """V18: si ya detectamos una lista de pedido, responder como pedido y no como foto/gama."""
    try:
        modo = str(parsed.get('modo') or '')
        if 'lista_whatsapp_real' in modo and (parsed.get('pedidos') or []):
            resp = _wa_v18_respuesta_lista(parsed)
            if resp:
                return resp, 'reglas_hilorama_v18_lista_pedido_sin_foto'
    except Exception as exc:
        print('WARN respuesta lista v18:', exc, flush=True)
    return _wa_v18_generar_respuesta_anterior(texto, parsed, meta, contexto)


# Mantener el mismo endpoint V17, pero usando extractor/generador V18 por sobrescritura global.
app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v17

# -----------------------------------------------------------------------------
# V19 - Corrección de contexto "Todos/Todas" + confirmación de hilo para listas
# -----------------------------------------------------------------------------
# Problemas corregidos:
# - El selector "Todas/Todos" del simulador no debe bloquear la memoria de conversación.
# - Si la clienta confirma "sería todo de Velluto" después de una lista con dudas,
#   se reintenta resolver la última lista usando ese hilo, en lugar de responder precio.
# - Si solo confirma hilo sin lista pendiente, se actualiza contexto y no se contesta como consulta de precio.


def _wa_v19_clean_selector(valor):
    v = str(valor or '').strip()
    n = _wa_memoria_norm(v)
    if not v or n in {'todo', 'todos', 'toda', 'todas', 'all', 'ninguno', 'ninguna'}:
        return ''
    return v


_wa_v19_resolver_contexto_anterior = _wa_memoria_resolver_contexto_para_parser


def _wa_memoria_resolver_contexto_para_parser(texto, marca_ui, hilo_ui, memoria, productos):
    """V19: tratar Todas/Todos como vacío para que sí funcione la memoria."""
    return _wa_v19_resolver_contexto_anterior(
        texto,
        _wa_v19_clean_selector(marca_ui),
        _wa_v19_clean_selector(hilo_ui),
        memoria,
        productos,
    )


def _wa_v19_es_confirmacion_todo_hilo(texto, productos):
    """Detecta frases tipo: 'sería todo de velluto', 'todos son velluto'."""
    t = _wa_memoria_norm(texto or '')
    if not t:
        return False, '', ''
    hilos = _wa_memoria_detectar_hilos_explicitos(texto, productos) or []
    if not hilos:
        return False, '', ''
    # Debe sonar a corrección/confirmación de contexto, no a pregunta de precio ni carta.
    if re.search(r'\b(cuanto|cuánto|precio|cuesta|vale|costo|gama|carta|colores disponibles|foto|imagen|mostrar|muestra)\b', t):
        return False, '', ''
    patron_confirmacion = bool(re.search(
        r'\b(seria|sería|es|son|todo|todos|toda|todas|los|las|lista|pedido|colores)\b.*\b(de|en|para|como)?\b.*\b(velluto|veluto|komfy|komfi|konfy|kurumi|kairo|trapillo|alize|karina)\b'
        r'|\b(velluto|veluto|komfy|komfi|konfy|kurumi|kairo|trapillo)\b.*\b(todo|todos|toda|todas|lista|pedido)\b',
        t
    ))
    if not patron_confirmacion:
        return False, '', ''
    hilo = hilos[0]
    marca = _wa_memoria_marca_para_hilo(productos, hilo)
    return True, marca, hilo


def _wa_v19_ultima_lista_items(conversacion_id=None, telefono=''):
    """Recupera la última lista de pedido guardada en la conversación para resolver dudas posteriores."""
    try:
        if not conversacion_id:
            return []
        with DB() as db:
            rows = db.execute("""
                SELECT metadata, texto
                FROM whatsapp_mensajes
                WHERE conversacion_id=%s
                ORDER BY fecha DESC, id DESC
                LIMIT 20
            """, (conversacion_id,)).fetchall()
        for r in rows:
            meta_raw = (dict(r).get('metadata') or '')
            texto = dict(r).get('texto') or ''
            meta = {}
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) and meta_raw else (meta_raw or {})
            except Exception:
                meta = {}
            parsed = meta.get('parsed') or {}
            items = parsed.get('items_lista_v17') or meta.get('items_lista_v17') or []
            if items:
                return items
            # Respaldo: si se guardó texto normalizado de lista, re-extraer.
            posible = meta.get('v17_texto_parser') or meta.get('v16_texto_parser') or texto
            if isinstance(posible, str) and 'Lista de pedido detectada' in posible:
                limpio = posible.replace('Lista de pedido detectada:', '').strip()
                items2, es_lista = _wa_v17_extraer_items_lista(limpio)
                if es_lista and items2:
                    return items2
    except Exception as exc:
        print('WARN V19 recuperar ultima lista:', exc, flush=True)
    return []


def _wa_v19_producto_base_desde_desc(desc, productos_ctx):
    """Fallback suave: 'rojo escolar' en Velluto puede mapear a 'rojo' si hay una sola opción clara."""
    d = _wa_memoria_norm(desc or '')
    if not d:
        return None
    bases = [
        'blanco', 'negro', 'hueso', 'rojo', 'vino', 'rosa', 'azul', 'cielo', 'marino',
        'verde', 'amarillo', 'lila', 'morado', 'cafe', 'café', 'gris', 'beige', 'arena',
        'camel', 'canario', 'uva', 'naranja', 'durazno', 'lavanda', 'palo de rosa'
    ]
    candidatos_base = []
    for b in bases:
        if b in d:
            candidatos_base.append(b)
    for b in candidatos_base:
        try:
            prod, opciones = _wa_resolver_producto_por_color(productos_ctx, b)
            if prod:
                return prod
            if opciones and len(opciones) == 1:
                return opciones[0]
        except Exception:
            pass
    return None


_wa_v19_resolver_items_anterior = _wa_v17_resolver_items_lista


def _wa_v17_resolver_items_lista(items, productos, marca_parser='', hilo_parser=''):
    """V19: resolver listas respetando contexto limpio y con fallback para colores coloquiales."""
    marca_parser = _wa_v19_clean_selector(marca_parser)
    hilo_parser = _wa_v19_clean_selector(hilo_parser)
    pedidos, preguntas, errores, advertencias = _wa_v19_resolver_items_anterior(items, productos, marca_parser, hilo_parser)

    # Si hay contexto de hilo y quedaron preguntas por descripciones como 'Rojo escolar',
    # intenta una segunda pasada solo para descripciones sin código que aún no se agregaron.
    if hilo_parser and preguntas:
        productos_ctx = list(productos or [])
        if marca_parser:
            mn = _wa_memoria_norm(marca_parser)
            productos_ctx = [p for p in productos_ctx if _wa_memoria_norm(p.get('marca') or '') == mn]
        productos_ctx = _v6_products_for_hilo(productos_ctx, hilo_parser)
        ya = set(str(p.get('producto_id') or '') for p in pedidos)
        nuevas_preguntas = []
        agregados = []
        for q in preguntas:
            # Busca el raw entre comillas simples: Para 'Rojo escolar- 2'...
            m = re.search(r"'([^']+)'", str(q))
            raw_desc = m.group(1) if m else ''
            item = None
            if raw_desc:
                for it in items or []:
                    if not str(it.get('codigo') or '').strip() and _wa_memoria_norm(raw_desc) in _wa_memoria_norm(it.get('raw') or it.get('desc') or ''):
                        item = it
                        break
            if item:
                prod = _wa_v19_producto_base_desde_desc(item.get('desc') or item.get('raw'), productos_ctx)
                if prod and str(prod.get('id') or '') not in ya:
                    agregados.append(_wa_v17_producto_dict(prod, int(item.get('cantidad') or 1)))
                    ya.add(str(prod.get('id') or ''))
                    continue
            nuevas_preguntas.append(q)
        if agregados:
            # Combinar cantidades si se repitió producto.
            merged = {}
            for p in list(pedidos) + agregados:
                key = str(p.get('producto_id') or p.get('codigo') or '')
                if key in merged:
                    merged[key]['cantidad'] = int(merged[key].get('cantidad') or 0) + int(p.get('cantidad') or 1)
                else:
                    merged[key] = p
            pedidos = list(merged.values())
            preguntas = nuevas_preguntas
            advertencias = list(advertencias or []) + ['V19: se resolvió un color coloquial usando el contexto de hilo.']
    return pedidos, preguntas, errores, advertencias


_wa_v19_view_anterior = app.view_functions.get('whatsapp_ia_simular')


def whatsapp_ia_simular_v19():
    data = request.get_json(force=True) or {}
    texto_original = (data.get('texto') or '').strip()
    marca = _wa_v19_clean_selector(data.get('marca') or '')
    hilo = _wa_v19_clean_selector(data.get('hilo') or '')
    cliente_nombre = (data.get('cliente_nombre') or '').strip()
    telefono = (data.get('telefono') or '').strip()
    texto_imagen = (data.get('texto_imagen') or '').strip()
    conversacion_id = data.get('conversacion_id')
    nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

    export_info = _wa_v16_extraer_bloque_cliente(texto_original, telefono)
    texto_cliente = (export_info.get('texto_cliente') or texto_original).strip()
    telefono = telefono or export_info.get('telefono') or ''
    cliente_nombre = cliente_nombre or export_info.get('cliente_nombre') or ''
    texto_total_preview = ' '.join(x for x in [texto_cliente, texto_imagen] if x).strip()

    productos_mem = _wa_memoria_productos_min()
    es_conf_hilo, marca_conf, hilo_conf = _wa_v19_es_confirmacion_todo_hilo(texto_total_preview, productos_mem)

    if es_conf_hilo:
        memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)
        _wa_v15_cancelar_cierres(conversacion_id, telefono, 'cliente_confirmo_hilo')
        if nueva_conversacion:
            conversacion_id = None
        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id, telefono, cliente_nombre)

        items_previos = _wa_v19_ultima_lista_items(conversacion_id, telefono)
        if items_previos:
            pedidos, preguntas, errores, advertencias = _wa_v17_resolver_items_lista(items_previos, productos_mem, marca_conf, hilo_conf)
            parsed = {
                'ok': True,
                'modo': 'lista_whatsapp_real_v19_confirmacion_hilo',
                'modo_especial': 'resolver_lista_previa_con_hilo_confirmado',
                'contexto': {
                    'marca': marca_conf,
                    'hilo': hilo_conf,
                    'productos_contexto': len(productos_mem),
                    'contexto_inferido': {'marca': marca_conf or '', 'hilo': hilo_conf or ''},
                    'hilos_detectados': [hilo_conf] if hilo_conf else [],
                },
                'pedidos': pedidos,
                'errores': sorted(set(str(e) for e in errores if e)),
                'advertencias': sorted(set(str(a) for a in advertencias if a)),
                'preguntas': sorted(set(str(p) for p in preguntas if p)),
                'sugerencias': {},
                'sugerencias_almacen': [],
                'respuesta_preferida': '',
                'items_lista_v17': items_previos,
            }
            meta = _clasificar_intencion_wa('Lista previa confirmada como ' + hilo_conf, parsed)
            meta['intencion'] = 'pedido'
            meta['confianza'] = 'alta' if pedidos and not preguntas and not errores else 'media'
            meta['accion_recomendada'] = 'agregar_productos' if pedidos and not preguntas and not errores else 'revisar'
            meta['puede_auto_enviar'] = bool(pedidos and not preguntas and not errores)
            respuesta_base = _wa_v18_respuesta_lista(parsed)
            if respuesta_base:
                respuesta = f"Perfecto 😊 tomo la lista anterior como {hilo_conf}.\n" + respuesta_base.replace('Claro 😊 le agrego:\n', 'Le agrego:\n')
            else:
                respuesta = f"Perfecto 😊 tomo la lista anterior como {hilo_conf}, pero necesito revisar los tonos antes de agregar." 
            motor = 'reglas_hilorama_v19_confirmacion_hilo_resuelve_lista'
        else:
            parsed = {
                'ok': True,
                'modo': 'confirmacion_hilo_v19_sin_lista_pendiente',
                'contexto': {'marca': marca_conf, 'hilo': hilo_conf, 'contexto_inferido': {'marca': marca_conf or '', 'hilo': hilo_conf or ''}},
                'pedidos': [], 'preguntas': [], 'errores': [], 'advertencias': [], 'sugerencias': {}, 'sugerencias_almacen': []
            }
            meta = {'intencion': 'confirmacion_contexto', 'confianza': 'alta', 'accion_recomendada': 'responder', 'puede_auto_enviar': False}
            respuesta = f"Perfecto 😊 entonces lo manejamos como {hilo_conf}. Me puede pasar los códigos o cantidades y se lo cotizo."
            motor = 'reglas_hilorama_v19_confirmacion_hilo_sin_precio'

        try:
            with DB() as db:
                db.execute("""
                    INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (conversacion_id, 'IN', 'texto', texto_total_preview, respuesta, json.dumps({'parsed': parsed, 'meta': meta, 'motor': motor, 'memoria_usada': memoria_previa, 'export_info': export_info}, ensure_ascii=False)))
        except Exception as exc:
            print('WARN guardar simulacion WA v19:', exc, flush=True)

        memoria_actualizada = _wa_memoria_actualizar(
            conversacion_id=conversacion_id,
            telefono=telefono,
            cliente_nombre=cliente_nombre,
            texto=texto_total_preview,
            respuesta=respuesta,
            parsed=parsed,
            meta=meta,
            marca_parser=marca_conf,
            hilo_parser=hilo_conf,
            memoria_previa=memoria_previa,
            productos=productos_mem,
        )
        return jsonify(json_safe({
            'ok': True,
            'conversacion_id': conversacion_id,
            'motor': motor + ':memoria_v19_contexto_confirmado',
            'mensaje_cliente': texto_total_preview,
            'mensaje_parser': texto_total_preview,
            'respuesta_sugerida': respuesta,
            'intencion': meta.get('intencion'),
            'confianza': meta.get('confianza'),
            'accion_recomendada': meta.get('accion_recomendada'),
            'puede_auto_enviar': meta.get('puede_auto_enviar'),
            'pedidos': parsed.get('pedidos') or [],
            'preguntas': parsed.get('preguntas') or [],
            'errores': parsed.get('errores') or [],
            'advertencias': list(parsed.get('advertencias') or []) + ['V19: se interpretó como confirmación de hilo/contexto, no como pregunta de precio.'],
            'parser': parsed,
            'memoria_usada': memoria_previa,
            'memoria_actual': memoria_actualizada,
            'whatsapp_export': export_info,
        }))

    # Caso normal: usar el endpoint anterior, con los selectores ya corregidos por el wrapper global.
    return _wa_v19_view_anterior()


_wa_v19_generar_respuesta_anterior = _generar_respuesta_wa_con_openai


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    """V19: evitar que 'sería todo de Velluto' se convierta en respuesta de precio."""
    try:
        productos_mem = _wa_memoria_productos_min()
        es_conf, marca_conf, hilo_conf = _wa_v19_es_confirmacion_todo_hilo(texto, productos_mem)
        if es_conf and not (parsed.get('pedidos') or []):
            return f"Perfecto 😊 entonces lo manejamos como {hilo_conf}. Me puede pasar los códigos o cantidades y se lo cotizo.", 'reglas_hilorama_v19_confirmacion_hilo_sin_precio'
    except Exception as exc:
        print('WARN respuesta confirmacion hilo v19:', exc, flush=True)
    return _wa_v19_generar_respuesta_anterior(texto, parsed, meta, contexto)


app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v19

# -----------------------------------------------------------------------------
# V20 - Resolver listas con código + color sin equivocarse
# -----------------------------------------------------------------------------
# Corrige casos como:
#   Blanco 01- 2
#   Hueso 26- 1
# Cuando el código no existe en el hilo actual o el código no coincide con el
# nombre/color escrito por la clienta, el agente NO debe agregar el producto
# equivocado. Primero intenta resolver por el nombre del color dentro del hilo
# confirmado; si no es claro, pregunta.

_WA_V20_COLOR_BASES = [
    'blanco', 'negro', 'hueso', 'rojo', 'vino', 'rosa', 'azul', 'cielo', 'marino',
    'verde', 'amarillo', 'lila', 'morado', 'cafe', 'café', 'gris', 'beige', 'arena',
    'camel', 'canario', 'uva', 'naranja', 'durazno', 'lavanda', 'palo de rosa',
    'palo rosa', 'piel', 'carne', 'trigo', 'mandarina', 'pizarra', 'botella',
    'bandera', 'turquesa', 'agua', 'chocolate'
]

_WA_V20_ALIASES_COLOR = {
    'rojo escolar': 'rojo',
    'rosa bebe': 'rosa',
    'rosa bebé': 'rosa',
    'azul bebe': 'azul',
    'azul bebé': 'azul',
    'azul cielo': 'cielo',
    'cafe': 'café',
    'cafe oscuro': 'café',
    'café oscuro': 'café',
    'cafe claro': 'café',
    'café claro': 'café',
}


def _wa_v20_norm(v):
    try:
        return _wa_memoria_norm(v or '')
    except Exception:
        return _wa_v17_norm(v or '')


def _wa_v20_color_tokens(desc):
    d = _wa_v20_norm(desc or '')
    if not d:
        return []
    toks = []
    for k, v in _WA_V20_ALIASES_COLOR.items():
        if _wa_v20_norm(k) in d:
            toks.append(_wa_v20_norm(v))
    for b in _WA_V20_COLOR_BASES:
        bn = _wa_v20_norm(b)
        if bn and bn in d:
            toks.append(bn)
    # Quitar duplicados conservando orden
    out = []
    for x in toks:
        if x and x not in out:
            out.append(x)
    return out


def _wa_v20_desc_compatible_con_producto(prod, desc):
    """True si el texto color/código de la clienta coincide con el producto."""
    d = _wa_v20_norm(desc or '')
    if not d:
        return True
    color = _wa_v20_norm((prod or {}).get('color') or (prod or {}).get('nombre') or '')
    if not color:
        return False
    if d in color or color in d:
        return True
    for token in _wa_v20_color_tokens(d):
        if token and token in color:
            return True
    return False


def _wa_v20_buscar_por_desc(productos_ctx, desc):
    """Resolver por nombre/color dentro del hilo actual, con fallback a color base."""
    desc = str(desc or '').strip()
    if not desc:
        return None, []
    try:
        prod, opciones = _wa_resolver_producto_por_color(productos_ctx, desc)
        if prod:
            return prod, opciones or []
        if opciones and len(opciones) == 1:
            return opciones[0], opciones
    except Exception:
        opciones = []

    # Fallback: blanco/hueso/rojo escolar/etc. Busca una sola coincidencia clara.
    for token in _wa_v20_color_tokens(desc):
        try:
            prod, opciones = _wa_resolver_producto_por_color(productos_ctx, token)
            if prod:
                return prod, opciones or []
            if opciones and len(opciones) == 1:
                return opciones[0], opciones
        except Exception:
            pass
    return None, opciones or []


def _wa_v20_nombre_producto(prod):
    if not prod:
        return ''
    hilo = str(prod.get('hilo') or '').strip()
    codigo = str(prod.get('codigo') or '').strip()
    color = str(prod.get('color') or '').strip()
    return ' '.join(x for x in [hilo, codigo, color] if x).strip() or str(prod.get('nombre') or 'producto')


def _wa_v20_merge_pedidos(pedidos):
    merged = {}
    for p in pedidos or []:
        key = str(p.get('producto_id') or p.get('id') or p.get('codigo') or '') + '|' + str(p.get('marca') or '') + '|' + str(p.get('hilo') or '')
        if key in merged:
            merged[key]['cantidad'] = int(merged[key].get('cantidad') or 0) + int(p.get('cantidad') or 1)
        else:
            merged[key] = p
    return list(merged.values())


_wa_v20_resolver_items_anterior = _wa_v17_resolver_items_lista


def _wa_v17_resolver_items_lista(items, productos, marca_parser='', hilo_parser=''):
    """V20: no agregar un código si el nombre escrito por la clienta lo contradice."""
    marca_parser = _wa_v19_clean_selector(marca_parser)
    hilo_parser = _wa_v19_clean_selector(hilo_parser)

    productos_ctx = list(productos or [])
    if marca_parser:
        mn = _wa_v20_norm(marca_parser)
        productos_ctx = [p for p in productos_ctx if _wa_v20_norm(p.get('marca') or '') == mn]
    if hilo_parser:
        productos_ctx = _v6_products_for_hilo(productos_ctx, hilo_parser)

    pedidos = []
    preguntas = []
    errores = []
    advertencias = []

    code_map_ctx = _v6_code_map(productos_ctx)
    code_map_all = _v6_code_map(productos or [])

    for it in items or []:
        code_raw = str(it.get('codigo') or '').strip()
        code = code_raw.lstrip('0') or code_raw
        desc = str(it.get('desc') or '').strip()
        qty = int(it.get('cantidad') or 1)
        raw = str(it.get('raw') or '').strip()
        prod = None

        matches = []
        if code:
            matches = code_map_ctx.get(code) or []
            if not matches and not hilo_parser:
                matches = code_map_all.get(code) or []
            if matches:
                normales = [p for p in matches if not any(x in _wa_v20_norm(p.get('color') or '') for x in ['combo', 'paquete', 'surtido'])]
                matches = normales or matches
                familias = sorted(set(_v6_hilo_family(p.get('hilo') or '') for p in matches))
                if not hilo_parser and len(familias) > 1:
                    opts = ', '.join(sorted(set(str(p.get('hilo') or '') for p in matches))[:5])
                    preguntas.append(f"El código {code} aparece en varios hilos ({opts}). ¿De cuál hilo lo agrego?")
                    continue
                prod_code = sorted(matches, key=lambda p: int(p.get('stock') or 0), reverse=True)[0]

                # Si la línea trae descripción, validar que el código coincida con el color.
                if desc and not _wa_v20_desc_compatible_con_producto(prod_code, desc):
                    prod_desc, opciones_desc = _wa_v20_buscar_por_desc(productos_ctx, desc)
                    if prod_desc and str(prod_desc.get('id') or '') != str(prod_code.get('id') or ''):
                        prod = prod_desc
                        advertencias.append(
                            f"V20: en '{raw}' el código {code} corresponde a {_wa_v20_nombre_producto(prod_code)}, "
                            f"pero el texto dice '{desc}'. Se resolvió por nombre/color como {_wa_v20_nombre_producto(prod_desc)}."
                        )
                    elif prod_desc:
                        prod = prod_code
                    else:
                        preguntas.append(
                            f"En '{raw}', el código {code} corresponde a {_wa_v20_nombre_producto(prod_code)}, "
                            f"pero el texto dice '{desc}'. ¿Agrego el código {code} o el color '{desc}'?"
                        )
                        continue
                else:
                    prod = prod_code
            else:
                # Código no ubicado en ese hilo. Si hay nombre/color, intentar por nombre antes de marcar error.
                if desc:
                    prod_desc, opciones_desc = _wa_v20_buscar_por_desc(productos_ctx, desc)
                    if prod_desc:
                        prod = prod_desc
                        advertencias.append(
                            f"V20: en '{raw}' no se ubicó el código {code} en {hilo_parser or 'el contexto'}, "
                            f"se resolvió por color como {_wa_v20_nombre_producto(prod_desc)}."
                        )
                    elif opciones_desc:
                        opts = ', '.join([f"{p.get('codigo')} {p.get('color')}".strip() for p in opciones_desc[:5]])
                        preguntas.append(f"Para '{raw}' no ubiqué el código {code}; por color encontré: {opts}. ¿Cuál le agrego?")
                        continue
                    else:
                        errores.append(code)
                        preguntas.append(f"No ubiqué '{raw}' en {hilo_parser or 'almacén'}. ¿Me confirma el código o tono?")
                        continue
                else:
                    errores.append(code)
                    continue
        elif desc:
            if not hilo_parser:
                preguntas.append(f"Para '{raw}' necesito confirmar el hilo antes de agregarlo.")
                continue
            prod_desc, opciones_desc = _wa_v20_buscar_por_desc(productos_ctx, desc)
            if prod_desc:
                prod = prod_desc
            elif opciones_desc:
                opts = ', '.join([f"{p.get('codigo')} {p.get('color')}".strip() for p in opciones_desc[:5]])
                preguntas.append(f"Para '{desc}' tengo varias opciones: {opts}. ¿Cuál le agrego?")
                continue
            else:
                preguntas.append(f"No ubiqué exacto '{desc}', ¿me confirma código o tono?")
                continue

        if prod:
            pedidos.append(_wa_v17_producto_dict(prod, qty))

    pedidos = _wa_v20_merge_pedidos(pedidos)
    return pedidos, sorted(set(preguntas)), sorted(set(str(e) for e in errores if e)), sorted(set(advertencias))


_wa_v20_generar_respuesta_anterior = _generar_respuesta_wa_con_openai


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    """V20: listas con conflictos código/color siguen siendo pedido, no foto ni precio."""
    try:
        modo = str(parsed.get('modo') or '')
        if ('lista_whatsapp_real' in modo or 'resolver_lista_previa' in modo) and (parsed.get('pedidos') or []):
            resp = _wa_v18_respuesta_lista(parsed)
            if resp:
                return resp, 'reglas_hilorama_v20_lista_codigo_color_seguro'
    except Exception as exc:
        print('WARN respuesta lista v20:', exc, flush=True)
    return _wa_v20_generar_respuesta_anterior(texto, parsed, meta, contexto)

# Mantener endpoint V19, pero usando el resolver V20 por sobrescritura global.
app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v19

# -----------------------------------------------------------------------------
# V21 - Agente de ventas: listas más humanas y sin confundir encabezados
# -----------------------------------------------------------------------------
# Corrige casos como:
#   "me puede poner esta lista 550 x2"
# para que NO tome "me puede poner esta lista" como color.
# También evita mandar al cliente dudas técnicas tipo "el código corresponde a...".


def _wa_v21_norm(v):
    try:
        return _wa_memoria_norm(v or '')
    except Exception:
        return re.sub(r'\s+', ' ', str(v or '').lower()).strip()


def _wa_v21_limpiar_intro(linea):
    raw = str(linea or '').strip().strip(',.;')
    if not raw:
        return ''
    s = raw.replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s).strip()

    # Quitar texto de cortesía/encabezado ANTES del primer item real.
    # Se busca el primer patrón claramente comprable dentro de la línea.
    patrones_item = [
        r'(\d{1,4}\s*(?:x|por|\*)\s*\d{1,3})',          # 550 x2
        r'(\d{1,4}\s+[A-Za-zÁÉÍÓÚáéíóúÑñ][^\n]*?\s*-\s*\d{1,3})',  # 216 canario - 4
        r'([A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ\s]{2,}\s+\d{1,4}\s*-\s*\d{1,3})', # Blanco 01 - 2
        r'([A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ\s]{2,}\s*-\s*\d{1,3})', # Rojo escolar - 2
        r'(\d{1,4})\s*$',                                      # 493
    ]
    for pat in patrones_item:
        m = re.search(pat, s, flags=re.I)
        if m:
            return m.group(1).strip()

    # Fallback por frases de encabezado conocidas.
    out = re.sub(
        r'^.*?\b(?:lista|colores|tonos|codigos|códigos)\b\s*(?:de\s+(?:colores|tonos|codigos|códigos))?\s*(?:por\s*favor|porfavor)?\s*',
        '', s, flags=re.I
    ).strip()
    return out or s


def _wa_v21_linea_a_item(linea):
    raw = str(linea or '').strip().strip(',.;')
    if not raw:
        return []
    limpia = _wa_v21_limpiar_intro(raw)
    candidatos = []
    if limpia and limpia != raw:
        candidatos.append(limpia)
    candidatos.append(raw)

    for cand in candidatos:
        try:
            items = _wa_v17_linea_a_item_original_v21(cand)
        except NameError:
            items = []
        except Exception:
            items = []
        if items:
            for it in items:
                it['raw'] = raw
                # Si el desc quedó con texto de encabezado, limpiarlo.
                descn = _wa_v21_norm(it.get('desc') or '')
                if descn and re.search(r'\b(me puede|me podria|me podría|poner|lista|agregar|cotizar|pedido)\b', descn):
                    it['desc'] = ''
            return items

    # Por seguridad, patrones directos.
    s = limpia.replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s).strip()
    if re.fullmatch(r'(?:\d{1,4}\s*[,\s]+){1,}\d{1,4}', s):
        return [{'codigo': c.lstrip('0') or c, 'codigo_raw': c, 'cantidad': 1, 'desc': '', 'raw': raw} for c in re.findall(r'\d{1,4}', s)]
    m = re.fullmatch(r'(\d{1,4})\s*(?:x|por|\*)\s*(\d{1,3})', s, flags=re.I)
    if m:
        return [{'codigo': (m.group(1).lstrip('0') or m.group(1)), 'codigo_raw': m.group(1), 'cantidad': int(m.group(2)), 'desc': '', 'raw': raw}]
    m = re.fullmatch(r'(\d{1,4})', s)
    if m:
        return [{'codigo': (m.group(1).lstrip('0') or m.group(1)), 'codigo_raw': m.group(1), 'cantidad': 1, 'desc': '', 'raw': raw}]
    return []


# Guardar la función base una sola vez para evitar recursión si Render recarga.
try:
    _wa_v17_linea_a_item_original_v21
except NameError:
    _wa_v17_linea_a_item_original_v21 = _wa_v17_linea_a_item


def _wa_v17_linea_a_item(linea):
    return _wa_v21_linea_a_item(linea)


def _wa_v21_sanitizar_item(it):
    it = dict(it or {})
    raw = str(it.get('raw') or '').strip()
    desc = str(it.get('desc') or '').strip()
    code_raw = str(it.get('codigo_raw') or it.get('codigo') or '').strip()

    # Caso: "me puede poner esta lista 550 x2" debe quedar código 550, sin descripción.
    limpio = _wa_v21_limpiar_intro(raw)
    m = re.fullmatch(r'(\d{1,4})\s*(?:x|por|\*)\s*(\d{1,3})', limpio, flags=re.I)
    if m:
        it['codigo'] = m.group(1).lstrip('0') or m.group(1)
        it['codigo_raw'] = m.group(1)
        it['cantidad'] = int(m.group(2))
        it['desc'] = ''
        return it

    # Caso: encabezado se quedó accidentalmente como color.
    if desc and re.search(r'\b(me puede|me podria|me podría|poner|lista|agregar|cotizar|pedido)\b', _wa_v21_norm(desc)):
        it['desc'] = ''

    # Guardar código original con ceros para poder distinguir 01, 08, etc.
    if code_raw and 'codigo_raw' not in it:
        it['codigo_raw'] = code_raw
    return it


def _wa_v21_producto_dict(prod, cantidad):
    return _wa_v17_producto_dict(prod, cantidad)


def _wa_v21_producto_label(prod):
    if not prod:
        return 'producto'
    hilo = str(prod.get('hilo') or '').strip()
    codigo = str(prod.get('codigo') or '').strip()
    color = str(prod.get('color') or prod.get('nombre') or '').strip()
    return ' '.join(x for x in [hilo, codigo, color] if x).strip() or 'producto'


def _wa_v21_buscar_codigo(productos_ctx, productos_all, code_norm, code_raw=''):
    codes = []
    for c in [code_raw, code_norm, str(code_raw).lstrip('0'), str(code_norm).lstrip('0')]:
        c = str(c or '').strip()
        if c and c not in codes:
            codes.append(c)
    mapa_ctx = _v6_code_map(productos_ctx)
    mapa_all = _v6_code_map(productos_all)
    for c in codes:
        matches = mapa_ctx.get(c) or []
        if matches:
            return matches
    for c in codes:
        matches = mapa_all.get(c) or []
        if matches:
            return matches
    return []


def _wa_v21_buscar_por_desc(productos_ctx, desc):
    try:
        return _wa_v20_buscar_por_desc(productos_ctx, desc)
    except Exception:
        try:
            return _wa_resolver_producto_por_color(productos_ctx, desc)
        except Exception:
            return None, []


def _wa_v17_resolver_items_lista(items, productos, marca_parser='', hilo_parser=''):
    """V21: resolver como vendedor: prioriza contexto y evita preguntas técnicas."""
    marca_parser = _wa_v19_clean_selector(marca_parser)
    hilo_parser = _wa_v19_clean_selector(hilo_parser)

    productos_all = list(productos or [])
    productos_ctx = list(productos_all)
    if marca_parser:
        mn = _wa_v21_norm(marca_parser)
        productos_ctx = [p for p in productos_ctx if _wa_v21_norm(p.get('marca') or '') == mn]
    if hilo_parser:
        productos_ctx = _v6_products_for_hilo(productos_ctx, hilo_parser)

    pedidos = []
    preguntas = []
    errores = []
    advertencias = []

    for it0 in items or []:
        it = _wa_v21_sanitizar_item(it0)
        raw = str(it.get('raw') or '').strip()
        code_raw = str(it.get('codigo_raw') or it.get('codigo') or '').strip()
        code = str(it.get('codigo') or '').strip().lstrip('0') or str(it.get('codigo') or '').strip()
        desc = str(it.get('desc') or '').strip()
        qty = int(it.get('cantidad') or 1)
        prod = None

        # 1) Si trae descripción y el código es dudoso o contradice, intentar resolver por nombre/color dentro del hilo.
        prod_desc = None
        opciones_desc = []
        if desc and hilo_parser:
            prod_desc, opciones_desc = _wa_v21_buscar_por_desc(productos_ctx, desc)

        # 2) Buscar por código dentro del contexto primero.
        matches = []
        if code:
            matches = _wa_v21_buscar_codigo(productos_ctx, productos_all if not hilo_parser else productos_ctx, code, code_raw)
            normales = [p for p in matches if not any(x in _wa_v21_norm(p.get('color') or '') for x in ['combo', 'paquete', 'surtido'])]
            matches = normales or matches

        if matches:
            familias = sorted(set(_v6_hilo_family(p.get('hilo') or '') for p in matches))
            if not hilo_parser and len(familias) > 1:
                # Si no hay contexto, preguntar simple, pero no técnico.
                opts = ', '.join(sorted(set(str(p.get('hilo') or '') for p in matches))[:4])
                preguntas.append(f"¿El código {code_raw or code} lo agrego de {opts}?")
                continue
            prod_code = sorted(matches, key=lambda p: int(p.get('stock') or 0), reverse=True)[0]

            if desc and not _wa_v20_desc_compatible_con_producto(prod_code, desc):
                # Si el nombre/color escrito por la clienta sí existe en el hilo, preferir lo que escribió.
                if prod_desc:
                    prod = prod_desc
                    advertencias.append(f"V21: en '{raw}' se priorizó el color escrito por la clienta sobre el código capturado.")
                else:
                    preguntas.append(f"En '{raw}' veo código y color diferentes. ¿Le agrego {code_raw or code} o el tono {desc}?")
                    continue
            else:
                prod = prod_code
        else:
            # Sin código ubicado: resolver por descripción si se puede.
            if desc:
                if not prod_desc:
                    prod_desc, opciones_desc = _wa_v21_buscar_por_desc(productos_ctx, desc)
                if prod_desc:
                    prod = prod_desc
                    if code:
                        advertencias.append(f"V21: en '{raw}' no se usó el código {code_raw or code}; se resolvió por el nombre/color.")
                elif opciones_desc and len(opciones_desc) == 1:
                    prod = opciones_desc[0]
                elif opciones_desc:
                    opts = ', '.join([f"{p.get('codigo')} {p.get('color')}".strip() for p in opciones_desc[:4]])
                    preguntas.append(f"Para '{desc}' encontré varias opciones ({opts}). ¿Cuál le agrego?")
                    continue
                else:
                    preguntas.append(f"No ubiqué bien '{raw}'. ¿Me confirma el tono o código?")
                    if code:
                        errores.append(code_raw or code)
                    continue
            elif code:
                errores.append(code_raw or code)
                preguntas.append(f"No ubiqué el código {code_raw or code}. ¿Me confirma si está correcto?")
                continue

        if prod:
            pedidos.append(_wa_v21_producto_dict(prod, qty))

    pedidos = _wa_v20_merge_pedidos(pedidos)
    return pedidos, sorted(set(preguntas)), sorted(set(str(e) for e in errores if e)), sorted(set(advertencias))


def _wa_v21_respuesta_lista(parsed):
    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    if not pedidos and not preguntas:
        return ''
    total_pzas = 0
    lineas = []
    for p in pedidos:
        qty = int(p.get('cantidad') or 1)
        total_pzas += qty
        hilo = str(p.get('hilo') or '').strip()
        codigo = str(p.get('codigo') or '').strip()
        color = str(p.get('color') or '').strip()
        nombre = ' '.join(x for x in [hilo, codigo, color] if x).strip() or 'producto'
        lineas.append(f"- {nombre} x{qty}")

    resp = ''
    if lineas:
        resp = "Claro 😊 le agrego:\n" + "\n".join(lineas)
        resp += f"\n\nTotal: {total_pzas} pieza" + ("s" if total_pzas != 1 else "") + "."
    if preguntas:
        if resp:
            resp += "\n\nSolo para no equivocarme, me ayuda a confirmar:\n"
        else:
            resp = "Claro 😊 solo para no equivocarme, me ayuda a confirmar:\n"
        # Convertir preguntas técnicas en texto amable.
        limpias = []
        for q in preguntas[:4]:
            q = str(q).strip()
            q = re.sub(r'^En \'([^\']+)\'.*?¿', r"En '\1', ¿", q)
            limpias.append('- ' + q)
        resp += "\n".join(limpias)
    elif errores:
        resp += "\n\nSolo me faltó confirmar estos códigos: " + ", ".join(str(e) for e in errores) + "."
    else:
        resp += "\nLe preparo su cotización."
    return resp


_wa_v21_generar_respuesta_anterior = _generar_respuesta_wa_con_openai


def _generar_respuesta_wa_con_openai(texto, parsed, meta, contexto):
    try:
        modo = str(parsed.get('modo') or '')
        if ('lista_whatsapp_real' in modo or 'resolver_lista_previa' in modo) and ((parsed.get('pedidos') or []) or (parsed.get('preguntas') or [])):
            resp = _wa_v21_respuesta_lista(parsed)
            if resp:
                return resp, 'reglas_hilorama_v21_agente_ventas_lista_humana'
    except Exception as exc:
        print('WARN respuesta lista v21:', exc, flush=True)
    return _wa_v21_generar_respuesta_anterior(texto, parsed, meta, contexto)

# Mantener endpoint V19; usa estas funciones porque se resolvieron globalmente.
app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v19

# -----------------------------------------------------------------------------
# V22 - Vendedora WhatsApp segura: stock real, memoria rica y revision humana
# -----------------------------------------------------------------------------
# Esta capa final mantiene compatibilidad con el simulador actual. Solo ajusta el
# comportamiento publico del agente para que venda como una persona: consulta
# almacen, no confirma agotados, pregunta corto y deja acciones para aprobacion.

WA_V22_MAX_COLORES_DETALLE = int(os.environ.get('WA_MAX_COLORES_DETALLE', '24') or '24')


def _wa_v22_norm(v):
    try:
        return _wa_v21_norm(v or '')
    except Exception:
        try:
            return _v6_norm(v or '')
        except Exception:
            return re.sub(r'\s+', ' ', str(v or '').lower()).strip()


def _wa_v22_no_es_combo(prod):
    color = _wa_v22_norm((prod or {}).get('color') or '')
    return not any(x in color for x in ['combo', 'paquete', 'surtido'])


def _wa_v22_stock(prod):
    try:
        return int((prod or {}).get('stock') or 0)
    except Exception:
        return 0


def _wa_v22_disponibles(productos):
    return [p for p in (productos or []) if _wa_v22_stock(p) > 0 and _wa_v22_no_es_combo(p)]


def _wa_v22_precio_texto(productos, fam=None):
    vals = []
    for p in productos or []:
        try:
            val = float(p.get('precio_venta') or 0)
        except Exception:
            val = 0
        if val > 0:
            vals.append(val)
    if not vals:
        return ''
    mn, mx = min(vals), max(vals)
    return f"${mn:,.2f}" if abs(mn - mx) < 0.01 else f"desde ${mn:,.2f}"


def _wa_v22_linea_producto(prod, cantidad=None):
    hilo = str((prod or {}).get('hilo') or '').strip()
    codigo = str((prod or {}).get('codigo') or '').strip()
    color = str((prod or {}).get('color') or '').strip()
    base = ' '.join(x for x in [hilo, codigo, color] if x).strip() or 'producto'
    if cantidad is None:
        return base
    return f"{base} x{int(cantidad or 1)}"


def _wa_v22_formato_colores(productos, limite=WA_V22_MAX_COLORES_DETALLE):
    lineas = []
    vistos = set()
    for p in _wa_v22_disponibles(productos):
        codigo = str(p.get('codigo') or '').strip()
        color = str(p.get('color') or '').strip()
        key = (codigo, _wa_v22_norm(color))
        if not codigo or key in vistos:
            continue
        vistos.add(key)
        lineas.append(f"- {codigo} {color}".strip())
        if len(lineas) >= limite:
            break
    return lineas, len(vistos)


def _wa_v22_envio_opciones_texto(cp=''):
    cp = re.search(r'\b\d{5}\b', str(cp or ''))
    cp_txt = cp.group(0) if cp else ''
    candidatos = [
        Path(APP_DIR) / 'envios_config.json',
        Path(APP_DIR).parent / 'envios_config.json',
    ]
    opciones = []
    for path in candidatos:
        try:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            for nombre, cfg in data.items():
                try:
                    base = float((cfg or {}).get('base') or 0)
                except Exception:
                    base = 0
                if base > 0:
                    opciones.append((str(nombre), base))
            if opciones:
                break
        except Exception as exc:
            print('WARN leer envios_config v22:', exc, flush=True)
    if opciones:
        lineas = [f"- {nombre}: desde ${precio:,.0f}" for nombre, precio in opciones[:5]]
        intro = f"Con el CP {cp_txt} " if cp_txt else ""
        return intro + "le puedo revisar estas opciones de envio:\n" + "\n".join(lineas) + "\n\nLa opcion final depende del peso y volumen del pedido."
    if cp_txt:
        return f"Perfecto, con el CP {cp_txt} reviso las opciones de paqueteria disponibles para su pedido."
    return "Si me comparte su codigo postal, le reviso las opciones de paqueteria disponibles."


_wa_v22_respuesta_consulta_anterior = _v6_respuesta_consulta


def _v6_respuesta_consulta(texto, productos, hilos=None, marcas=None):
    """V22: responder consultas con stock/precio reales y sin inventar disponibilidad."""
    t = _wa_v22_norm(texto)
    if not t:
        return ''

    combo = _v6_public_answer_for_combo(t)
    if combo:
        return combo

    if re.search(r'\b(abuelita|abuelitas|la abuelita)\b', t):
        return (
            "La Abuelita por el momento no la manejamos 😊 "
            "pero si tengo alternativas segun su proyecto: Kurumi para amigurumi mas firme/delgado "
            "o Komfy Mini si busca algo suave tipo chenille. ¿Para que trabajo lo ocuparia?"
        )

    if re.search(r'\b(envio|envios|envia|envias|mandan|paqueteria|cp|codigo postal)\b', t):
        cp = re.search(r'\b\d{5}\b', t)
        if cp:
            return _wa_v22_envio_opciones_texto(cp.group(0))
        return "Si 😊 hacemos envios. Para cotizarle bien me comparte su codigo postal, por favor."

    hilos = hilos or _v6_detect_hilos(t, productos)
    if not hilos:
        return _wa_v22_respuesta_consulta_anterior(texto, productos, hilos, marcas)

    pregunta_precio = bool(re.search(r'\b(precio|cuanto|cuesta|costo|vale|sale)\b', t))
    pregunta_colores = bool(re.search(r'\b(color|colores|tono|tonos|disponible|disponibles|carta|catalogo|gama)\b', t))
    color_groups = _v6_color_groups(t)
    bloques = []

    for h in hilos[:2]:
        prods_h = _v6_products_for_hilo(productos, h)
        disponibles = _wa_v22_disponibles(prods_h)
        nombre = _v6_hilo_display(h)
        fam = _v6_hilo_family(h)
        precio = _wa_v22_precio_texto(prods_h, fam)

        if pregunta_precio:
            if precio:
                bloques.append(f"El {nombre} esta en {precio} por madeja 😊 ¿Busca algun color o codigo en especial?")
            else:
                bloques.append(f"Si manejo {nombre} 😊 ¿Que color o codigo busca para revisarle precio exacto?")
            continue

        if color_groups and not re.search(r'\b(carta|catalogo|gama)\b', t):
            partes = []
            for g in color_groups[:3]:
                prod, opts = _v6_resolve_color(disponibles or prods_h, g)
                if prod and _wa_v22_stock(prod) > 0:
                    partes.append(f"{prod.get('codigo')} {prod.get('color')}")
                elif opts:
                    opts_disp = [o for o in opts if _wa_v22_stock(o) > 0]
                    if opts_disp:
                        partes.append(_v6_format_color_options(opts_disp, 4))
            if partes:
                bloques.append(f"Si 😊 en {nombre} tengo disponible: " + "; ".join(partes) + ". ¿Cuantas piezas le aparto?")
            else:
                bloques.append(f"En {nombre} no me aparece disponible ese tono exacto 😊 ¿quiere que le muestre opciones parecidas?")
            continue

        if pregunta_colores:
            lineas, total_mostrado = _wa_v22_formato_colores(prods_h)
            total_disp = len(_wa_v22_disponibles(prods_h))
            if not total_disp:
                bloques.append(f"Por el momento no me aparece stock disponible de {nombre}. ¿Quiere que le sugiera algun hilo parecido?")
            elif total_disp <= WA_V22_MAX_COLORES_DETALLE:
                bloques.append(f"Claro 😊 de {nombre} tengo disponibles estos tonos:\n" + "\n".join(lineas))
            else:
                muestra = ", ".join([ln.replace("- ", "") for ln in lineas[:10]])
                bloques.append(
                    f"Tengo {total_disp} tonos disponibles de {nombre} 😊 "
                    f"Algunos son: {muestra}. ¿Busca algun color en especial o le comparto la carta?"
                )
            continue

        if disponibles:
            extra = f", esta en {precio}" if precio else ""
            bloques.append(f"Si 😊 manejamos {nombre}{extra}. ¿Busca algun color o codigo en especial?")
        else:
            bloques.append(f"Si manejamos {nombre}, pero ahorita no me aparece stock disponible. ¿Le reviso alguna alternativa?")

    return "\n\n".join(bloques).strip()


def _wa_respuesta_consulta_almacen(texto, productos, hilos=None, marcas=None):
    return _v6_respuesta_consulta(texto, productos, hilos, marcas)


def _wa_v22_limpiar_pregunta_cliente(q):
    q = str(q or '').strip()
    if not q:
        return ''
    q = re.sub(r'\bV\d+:\s*', '', q)
    q = re.sub(r'\.?\s*Se\s+us[óo]\s+\d+\s+provisionalmente\.?', '', q, flags=re.I)
    q = re.sub(r'\bconfianza\s+(baja|media|alta)\b', '', q, flags=re.I)
    q = re.sub(r'\s+', ' ', q).strip()
    # Suaviza preguntas tecnicas de codigo/color.
    q = q.replace("veo codigo y color diferentes", "quiero confirmar el tono")
    q = q.replace("no se uso", "no tome")
    return q


def _formatear_sugerencias_almacen_wa(parsed):
    sugerencias = parsed.get('sugerencias_almacen') or []
    if not sugerencias:
        return ''
    bloques = []
    for s in sugerencias[:3]:
        tipo = s.get('tipo')
        opciones = s.get('opciones') or []
        if tipo == 'tonos_por_descripcion':
            hilo = s.get('hilo') or 'ese hilo'
            lineas = []
            for op in opciones[:5]:
                lineas.append(f"- {op.get('hilo') or hilo} {op.get('codigo')} {op.get('color')}".strip())
            if lineas:
                bloques.append('Lo mas parecido que tengo en ' + hilo + ' es:\n' + '\n'.join(lineas))
        elif tipo == 'hilo_similar':
            lineas = []
            for op in opciones[:5]:
                txt = f"- {op.get('hilo')}"
                if op.get('ejemplo_codigo'):
                    txt += f" (ej. {op.get('ejemplo_codigo')} {op.get('ejemplo_color','')})"
                lineas.append(txt.strip())
            if lineas:
                bloques.append('Ese producto exacto no lo veo en mi almacen, pero si tengo opciones parecidas:\n' + '\n'.join(lineas))
    return '\n\n'.join(bloques).strip()


_wa_v22_clasificar_anterior = _clasificar_intencion_wa


def _clasificar_intencion_wa(texto, parsed):
    meta = _wa_v22_clasificar_anterior(texto, parsed)
    t = _wa_v22_norm(texto)

    if re.search(r'\b(comprobante|pago|pague|pagado|deposito|transferencia|ticket|recibo)\b', t) or re.search(r'\b(ya\s+quedo|ya\s+quedo|ya\s+qued[oó])\b.*\bpago\b', t):
        meta['intencion'] = 'comprobante_pago'
        meta['confianza'] = 'media'
        meta['accion_recomendada'] = 'pedir_comprobante_revision'
    elif re.search(r'\b(cp|codigo postal)\b', t):
        meta['intencion'] = 'pregunta_envio'
        meta['confianza'] = 'media'
        meta['accion_recomendada'] = 'responder'
    elif parsed.get('respuesta_preferida') and not parsed.get('pedidos'):
        meta['confianza'] = 'alta'
        meta['accion_recomendada'] = 'responder'

    # Seguridad de fase: el agente sugiere/prepara, no envia ni marca acciones solo.
    meta['puede_auto_enviar'] = False
    return meta


def _wa_v22_partir_stock(pedidos):
    ok, parciales, agotados = [], [], []
    for p in pedidos or []:
        qty = int(p.get('cantidad') or 1)
        inv = p.get('es_inventariable', True)
        stock = _wa_v22_stock(p)
        if inv and stock <= 0:
            agotados.append(p)
        elif inv and stock < qty:
            parciales.append(p)
        else:
            ok.append(p)
    return ok, parciales, agotados


def _fallback_respuesta_wa(texto, parsed, meta):
    if parsed.get('respuesta_preferida'):
        return str(parsed.get('respuesta_preferida')).strip()

    pedidos = parsed.get('pedidos') or []
    preguntas = parsed.get('preguntas') or []
    errores = parsed.get('errores') or []
    sug_txt = _formatear_sugerencias_almacen_wa(parsed)
    intent = (meta or {}).get('intencion')
    t = _wa_v22_norm(texto)

    if intent == 'comprobante_pago':
        return 'Perfecto 😊 mandeme la imagen del comprobante y lo dejo para revision antes de marcar el pago.'

    if intent == 'pregunta_envio' and re.search(r'\b\d{5}\b', t):
        return _wa_v22_envio_opciones_texto(t)

    if re.search(r'\b(abuelita|abuelitas|la abuelita)\b', t) and not pedidos:
        return _v6_respuesta_consulta(texto, [], [], [])

    provisionales = _codigos_provisionales_desde_preguntas(preguntas)
    pedidos_confirmados = [
        p for p in pedidos
        if (str(p.get('codigo') or '').strip().lstrip('0') or '0') not in provisionales
    ]
    ok, parciales, agotados = _wa_v22_partir_stock(pedidos_confirmados)

    if errores:
        txt = ''
        if ok:
            txt += 'Claro 😊 ya tengo claro esto:\n' + '\n'.join('- ' + _wa_v22_linea_producto(p, p.get('cantidad')) for p in ok[:18]) + '\n\n'
        txt += 'No ubique estos codigos en almacen: ' + ', '.join(map(str, errores[:8])) + '. ¿Me los confirma, por favor?'
        return txt

    if preguntas:
        limpias = [_wa_v22_limpiar_pregunta_cliente(q) for q in preguntas if _wa_v22_limpiar_pregunta_cliente(q)]
        txt = ''
        if ok:
            txt += 'Claro 😊 ya tengo claro:\n' + '\n'.join('- ' + _wa_v22_linea_producto(p, p.get('cantidad')) for p in ok[:18]) + '\n\n'
        if sug_txt:
            txt += sug_txt + '\n\n'
        if limpias:
            txt += 'Solo para no equivocarme, ' + limpias[0]
        else:
            txt += 'Solo necesito confirmar un detalle para no agregarle un tono equivocado 😊'
        return txt

    if sug_txt and not pedidos:
        return sug_txt + '\n\n¿Le preparo una opcion con alguno de esos tonos?'

    if pedidos:
        partes = []
        if ok:
            total = sum(int(p.get('cantidad') or 1) for p in ok)
            partes.append('Claro 😊 le agrego:\n' + '\n'.join('- ' + _wa_v22_linea_producto(p, p.get('cantidad')) for p in ok[:18]))
            partes.append(f"Total confirmado: {total} pieza" + ("s." if total != 1 else "."))
        for p in parciales:
            partes.append(
                f"De {_wa_v22_linea_producto(p)} me aparecen {int(p.get('stock') or 0)} disponibles "
                f"y pidio {int(p.get('cantidad') or 1)}. ¿Le aparto las disponibles o le muestro otra opcion?"
            )
        for p in agotados:
            partes.append(f"{_wa_v22_linea_producto(p)} me aparece agotado por el momento. ¿Quiere que le busque un tono parecido?")
        if ok and not parciales and not agotados:
            partes.append('Le preparo su cotizacion.')
        return '\n\n'.join(partes).strip()

    if intent == 'pregunta_precio':
        return 'Claro 😊 ¿me confirma que hilo o codigo quiere revisar? Asi le doy precio exacto desde almacen.'
    if intent == 'pregunta_envio':
        return _wa_v22_envio_opciones_texto('')
    if intent == 'pregunta_stock':
        return 'Con gusto 😊 digame el hilo, color o codigo y le reviso disponibilidad real en almacen.'
    if intent == 'sugerir_tonos':
        return 'Si 😊 mandeme la foto o referencia y le sugiero tonos parecidos del catalogo disponible. No agrego nada hasta que usted confirme.'
    return 'Claro 😊 digame que hilo, codigo o color necesita y le ayudo a armar su cotizacion.'


_wa_v22_memoria_schema_anterior = _wa_memoria_schema


def _wa_memoria_schema():
    _wa_v22_memoria_schema_anterior()
    try:
        with DB() as db:
            for col_sql in [
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultimos_colores_codigos TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultima_lista_recibida TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS fecha_ultima_actividad TIMESTAMP",
            ]:
                db.execute(col_sql)
    except Exception as exc:
        print('WARN schema memoria WA v22:', exc, flush=True)


_wa_v22_memoria_derivar_anterior = _wa_memoria_derivar_datos


def _wa_memoria_derivar_datos(texto, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos):
    datos = _wa_v22_memoria_derivar_anterior(texto, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos)
    pedidos = parsed.get('pedidos') or []
    items_lista = parsed.get('items_lista_v17') or []

    ultimos = []
    for p in pedidos[:20]:
        ultimos.append({
            'codigo': p.get('codigo') or '',
            'color': p.get('color') or '',
            'hilo': p.get('hilo') or '',
            'cantidad': p.get('cantidad') or 1,
        })
    if not ultimos:
        for it in items_lista[:20]:
            ultimos.append({
                'codigo': it.get('codigo_raw') or it.get('codigo') or '',
                'color': it.get('desc') or '',
                'hilo': hilo_parser or '',
                'cantidad': it.get('cantidad') or 1,
            })

    if ultimos:
        datos['ultimos_colores_codigos'] = json.dumps(ultimos, ensure_ascii=False)
    elif (memoria_previa or {}).get('ultimos_colores_codigos'):
        datos['ultimos_colores_codigos'] = (memoria_previa or {}).get('ultimos_colores_codigos')

    if items_lista:
        datos['ultima_lista_recibida'] = json.dumps(items_lista[:60], ensure_ascii=False)
    elif pedidos and len(pedidos) > 1:
        datos['ultima_lista_recibida'] = json.dumps(ultimos[:60], ensure_ascii=False)
    elif (memoria_previa or {}).get('ultima_lista_recibida'):
        datos['ultima_lista_recibida'] = (memoria_previa or {}).get('ultima_lista_recibida')

    datos['fecha_ultima_actividad'] = now_mexico()
    return datos


_wa_v22_memoria_actualizar_anterior = _wa_memoria_actualizar


def _wa_memoria_actualizar(conversacion_id, telefono, cliente_nombre, texto, respuesta, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos):
    row = _wa_v22_memoria_actualizar_anterior(
        conversacion_id, telefono, cliente_nombre, texto, respuesta, parsed, meta,
        marca_parser, hilo_parser, memoria_previa, productos
    )
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return row
    try:
        datos = _wa_memoria_derivar_datos(texto, parsed, meta, marca_parser, hilo_parser, memoria_previa, productos)
        with DB() as db:
            updated = db.execute("""
                UPDATE whatsapp_contexto_cliente
                SET ultimos_colores_codigos=%s,
                    ultima_lista_recibida=%s,
                    fecha_ultima_actividad=%s,
                    updated_at=%s
                WHERE clave=%s
                RETURNING *
            """, (
                datos.get('ultimos_colores_codigos'),
                datos.get('ultima_lista_recibida'),
                datos.get('fecha_ultima_actividad'),
                now_mexico(),
                clave,
            )).fetchone()
        return dict(updated) if updated else row
    except Exception as exc:
        print('WARN actualizar memoria WA v22:', exc, flush=True)
        return row


def _wa_v22_sanitizar_respuesta_publica(txt):
    txt = str(txt or '').strip()
    if not txt:
        return txt
    lineas = []
    for ln in txt.splitlines():
        if re.search(r'\b(V\d+|confianza baja|confianza media|codigo no coincide|c[oó]digo no coincide)\b', ln, re.I):
            continue
        lineas.append(ln)
    txt = '\n'.join(lineas).strip()
    txt = re.sub(r'\s+\n', '\n', txt)
    return txt


_wa_v22_view_anterior = app.view_functions.get('whatsapp_ia_simular')


def whatsapp_ia_simular_v22():
    out = _wa_v22_view_anterior()
    status = 200
    response = out
    if isinstance(out, tuple):
        response = out[0]
        if len(out) > 1:
            status = out[1]
    try:
        data = response.get_json() if hasattr(response, 'get_json') else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return out

    data['respuesta_sugerida'] = _wa_v22_sanitizar_respuesta_publica(data.get('respuesta_sugerida') or '')
    data['puede_auto_enviar'] = False
    intent = data.get('intencion') or ''
    if intent == 'comprobante_pago':
        data['accion_recomendada'] = 'pedir_comprobante_revision'
    elif data.get('pedidos'):
        data['accion_recomendada'] = 'preparar_carrito_revision'
    elif data.get('accion_recomendada') in ('agregar_productos', 'crear_cotizacion'):
        data['accion_recomendada'] = 'responder_revision'
    data['motor'] = str(data.get('motor') or '') + ':v22_vendedora_segura'
    return jsonify(json_safe(data)), status


app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v22


# ==========================================================
# V24 - Envia.com SOLO COTIZACION DE ENVIOS (NO GENERA GUIAS)
# ==========================================================
# Seguridad: este bloque NUNCA llama /ship/generate/. Solo consulta /ship/rate/.
# Sirve para que el agente WhatsApp IA responda costos reales por CP sin inventar.

ENVIA_V24_REF_PRECIOS = {
    'correosdemexico': 110.0,
    'correos': 110.0,
    'estafeta': 199.0,
    'fedex': 269.0,
    'dhl': 269.0,
}

ENVIA_V24_NOMBRES = {
    'correosdemexico': 'Correos de México',
    'correos': 'Correos de México',
    'estafeta': 'Estafeta',
    'fedex': 'FedEx',
    'dhl': 'DHL',
    'paquetexpress': 'Paquetexpress',
    'ampm': 'AmPm',
    'uber': 'Uber',
    'redpack': 'Redpack',
}


def _envia_v24_bool_env(name, default=False):
    val = str(os.environ.get(name, '')).strip().lower()
    if not val:
        return bool(default)
    return val in ('1', 'true', 'yes', 'si', 'sí', 'on', 'enabled')


def _envia_v24_float_env(name, default):
    try:
        return float(str(os.environ.get(name, default)).strip() or default)
    except Exception:
        return float(default)


def _envia_v24_int_env(name, default):
    try:
        return int(float(str(os.environ.get(name, default)).strip() or default))
    except Exception:
        return int(default)


def _envia_v24_config():
    env = str(os.environ.get('ENVIA_ENV') or 'sandbox').strip().lower()
    production = env in ('prod', 'production', 'real')
    return {
        'enabled': _envia_v24_bool_env('ENVIA_ENABLED', False),
        'env': 'production' if production else 'sandbox',
        'token': (os.environ.get('ENVIA_TOKEN') or '').strip(),
        'api_base': 'https://api.envia.com' if production else 'https://api-test.envia.com',
        'queries_base': 'https://queries.envia.com' if production else 'https://queries-test.envia.com',
        # Envia documenta Geocodes con URL única sin token.
        'geocodes_base': 'https://geocodes.envia.com',
        'origin_country': (os.environ.get('ENVIA_ORIGIN_COUNTRY') or 'MX').strip().upper(),
        'origin_zip': re.sub(r'\D+', '', os.environ.get('ENVIA_ORIGIN_ZIP') or ''),
        'origin_name': (os.environ.get('ENVIA_ORIGIN_NAME') or 'Hilorama').strip(),
        'origin_phone': (os.environ.get('ENVIA_ORIGIN_PHONE') or '+520000000000').strip(),
        'origin_street': (os.environ.get('ENVIA_ORIGIN_STREET') or 'Origen Hilorama').strip(),
        'origin_city': (os.environ.get('ENVIA_ORIGIN_CITY') or '').strip(),
        'origin_state': (os.environ.get('ENVIA_ORIGIN_STATE') or '').strip(),
        'weight_kg': _envia_v24_float_env('ENVIA_DEFAULT_WEIGHT_KG', 1),
        'length_cm': _envia_v24_float_env('ENVIA_DEFAULT_LENGTH_CM', 30),
        'width_cm': _envia_v24_float_env('ENVIA_DEFAULT_WIDTH_CM', 25),
        'height_cm': _envia_v24_float_env('ENVIA_DEFAULT_HEIGHT_CM', 20),
        'cache_hours': _envia_v24_int_env('ENVIA_CACHE_HOURS', 24),
        'declared_value': _envia_v24_float_env('ENVIA_DECLARED_VALUE', 1000),
        'currency': (os.environ.get('ENVIA_CURRENCY') or 'MXN').strip().upper(),
        'timeout': _envia_v24_int_env('ENVIA_TIMEOUT_SECONDS', 18),
    }


def _envia_v24_carriers():
    raw = os.environ.get('ENVIA_CARRIERS') or 'estafeta,fedex,dhl,paquetexpress,correosdemexico'
    carriers = []
    for c in str(raw).split(','):
        c = re.sub(r'\s+', '', c.strip().lower())
        if c and c not in carriers:
            carriers.append(c)
    return carriers or ['estafeta', 'fedex']


def _envia_v24_http_json(method, url, payload=None, token=None, timeout=18):
    import urllib.request
    import urllib.error
    import urllib.parse
    body = None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            try:
                return True, json.loads(raw or '{}'), int(resp.status or 200), ''
            except Exception:
                return True, {'raw': raw}, int(resp.status or 200), ''
    except urllib.error.HTTPError as exc:
        raw = ''
        try:
            raw = exc.read().decode('utf-8', errors='replace')
        except Exception:
            pass
        try:
            obj = json.loads(raw or '{}')
        except Exception:
            obj = {'raw': raw}
        return False, obj, int(getattr(exc, 'code', 0) or 0), str(exc)
    except Exception as exc:
        return False, {}, 0, str(exc)


def _envia_v24_extraer_geocode(obj):
    """Acepta varias formas de respuesta de Geocodes y devuelve city/state/locality si existen."""
    candidatos = []
    if isinstance(obj, dict):
        for k in ('data', 'result', 'results', 'zipcodes', 'zipcode'):
            v = obj.get(k)
            if isinstance(v, list):
                candidatos.extend([x for x in v if isinstance(x, dict)])
            elif isinstance(v, dict):
                candidatos.append(v)
        candidatos.append(obj)
    elif isinstance(obj, list):
        candidatos.extend([x for x in obj if isinstance(x, dict)])
    for item in candidatos:
        city = item.get('city') or item.get('municipality') or item.get('municipio') or item.get('locality') or item.get('localidad') or item.get('town') or ''
        state = item.get('state_code') or item.get('stateCode') or item.get('state') or item.get('province') or item.get('region') or ''
        locality = item.get('locality') or item.get('localidad') or item.get('neighborhood') or item.get('colony') or item.get('colonia') or ''
        if city or state or locality:
            return {'city': str(city or '').strip(), 'state': str(state or '').strip(), 'locality': str(locality or '').strip(), 'raw': item}
    return {'city': '', 'state': '', 'locality': '', 'raw': obj}


def _envia_v24_geocode_zip(country, cp):
    cfg = _envia_v24_config()
    cp = re.sub(r'\D+', '', str(cp or ''))
    country = (country or 'MX').strip().upper()
    if not cp:
        return {'city': '', 'state': '', 'locality': ''}
    url = f"{cfg['geocodes_base'].rstrip('/')}/zipcode/{country}/{cp}"
    ok, obj, status, err = _envia_v24_http_json('GET', url, None, None, cfg['timeout'])
    if not ok:
        print('WARN Envia geocode fallo:', status, err, flush=True)
        return {'city': '', 'state': '', 'locality': '', 'error': err, 'status': status}
    return _envia_v24_extraer_geocode(obj)


def _envia_v24_address(cp, tipo='destination', nombre='Cliente'):
    cfg = _envia_v24_config()
    country = cfg['origin_country'] or 'MX'
    cp = re.sub(r'\D+', '', str(cp or ''))
    geo = _envia_v24_geocode_zip(country, cp)
    if tipo == 'origin':
        return {
            'name': cfg['origin_name'] or 'Hilorama',
            'phone': cfg['origin_phone'] or '+520000000000',
            'street': cfg['origin_street'] or 'Origen Hilorama',
            'city': cfg['origin_city'] or geo.get('city') or 'Ciudad',
            'state': cfg['origin_state'] or geo.get('state') or '',
            'country': country,
            'postalCode': cp,
        }
    return {
        'name': nombre or 'Cliente Hilorama',
        'phone': '+520000000000',
        'street': 'Por confirmar',
        'city': geo.get('city') or 'Ciudad',
        'state': geo.get('state') or '',
        'country': country,
        'postalCode': cp,
    }


def _envia_v24_package(piezas=None, peso_kg=None, largo_cm=None, ancho_cm=None, alto_cm=None):
    cfg = _envia_v24_config()
    try:
        piezas_i = max(1, int(piezas or 0))
    except Exception:
        piezas_i = 1
    # Regla conservadora: si no pasas peso, usa el default configurado. Si se pasan piezas,
    # estima mínimo 0.12kg por madeja, sin bajar del default si ENVIA_DEFAULT_WEIGHT_KG ya es mayor.
    peso = float(peso_kg or 0) or max(float(cfg['weight_kg'] or 1), round(piezas_i * 0.12, 2) if piezas_i else 1)
    largo = float(largo_cm or cfg['length_cm'] or 30)
    ancho = float(ancho_cm or cfg['width_cm'] or 25)
    alto = float(alto_cm or cfg['height_cm'] or 20)
    return {
        'type': 'box',
        'content': 'Hilos y estambres',
        'amount': 1,
        'declaredValue': float(cfg['declared_value'] or 1000),
        'lengthUnit': 'CM',
        'weightUnit': 'KG',
        'weight': round(peso, 3),
        'dimensions': {'length': round(largo, 2), 'width': round(ancho, 2), 'height': round(alto, 2)},
    }


def _envia_v24_cache_schema():
    try:
        with DB() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS envios_cotizaciones_cache (
                    id SERIAL PRIMARY KEY,
                    cache_key TEXT UNIQUE,
                    cp_destino TEXT,
                    request_json TEXT,
                    response_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_envios_cache_key ON envios_cotizaciones_cache(cache_key)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_envios_cache_cp ON envios_cotizaciones_cache(cp_destino, expires_at)")
    except Exception as exc:
        print('WARN schema Envia cache:', exc, flush=True)


def _envia_v24_cache_key(cp_destino, paquete, carriers):
    cfg = _envia_v24_config()
    base = {
        'env': cfg['env'],
        'origin_zip': cfg['origin_zip'],
        'cp_destino': re.sub(r'\D+', '', str(cp_destino or '')),
        'package': paquete,
        'carriers': carriers,
    }
    return json.dumps(base, sort_keys=True, ensure_ascii=False)


def _envia_v24_cache_get(cache_key):
    _envia_v24_cache_schema()
    try:
        with DB() as db:
            row = db.execute("""
                SELECT response_json FROM envios_cotizaciones_cache
                WHERE cache_key=%s AND (expires_at IS NULL OR expires_at > %s)
                ORDER BY created_at DESC LIMIT 1
            """, (cache_key, now_mexico())).fetchone()
            if row and row.get('response_json'):
                data = json.loads(row['response_json'])
                data['desde_cache'] = True
                return data
    except Exception as exc:
        print('WARN leer cache Envia:', exc, flush=True)
    return None


def _envia_v24_cache_set(cache_key, cp_destino, request_obj, response_obj):
    _envia_v24_cache_schema()
    cfg = _envia_v24_config()
    expires = now_mexico() + timedelta(hours=max(1, int(cfg.get('cache_hours') or 24)))
    try:
        with DB() as db:
            db.execute("""
                INSERT INTO envios_cotizaciones_cache (cache_key, cp_destino, request_json, response_json, created_at, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (cache_key) DO UPDATE SET
                    request_json=EXCLUDED.request_json,
                    response_json=EXCLUDED.response_json,
                    created_at=EXCLUDED.created_at,
                    expires_at=EXCLUDED.expires_at
            """, (
                cache_key, cp_destino,
                json.dumps(request_obj, ensure_ascii=False),
                json.dumps(response_obj, ensure_ascii=False),
                now_mexico(), expires,
            ))
    except Exception as exc:
        print('WARN guardar cache Envia:', exc, flush=True)


def _envia_v24_collect_rates(obj, carrier):
    """Extrae tarifas aunque Envia cambie ligeramente nombres/campos."""
    encontrados = []
    def walk(x):
        if isinstance(x, dict):
            price_raw = x.get('totalPrice', x.get('price', x.get('amount', x.get('total'))))
            if price_raw is not None and (x.get('carrier') or carrier):
                try:
                    precio = float(str(price_raw).replace(',', '').strip())
                except Exception:
                    precio = None
                if precio is not None and precio >= 0:
                    c = str(x.get('carrier') or carrier or '').strip().lower()
                    ref = ENVIA_V24_REF_PRECIOS.get(c)
                    encontrados.append({
                        'carrier': c,
                        'paqueteria': ENVIA_V24_NOMBRES.get(c, str(x.get('carrier') or carrier).title()),
                        'service': x.get('service') or x.get('serviceCode') or '',
                        'servicio': x.get('serviceDescription') or x.get('serviceName') or x.get('description') or x.get('service') or '',
                        'entrega': x.get('deliveryEstimate') or x.get('delivery') or x.get('estimatedDelivery') or '',
                        'precio': round(float(precio), 2),
                        'moneda': x.get('currency') or 'MXN',
                        'precio_referencia': ref,
                        'posible_reexpedicion': bool(ref and precio > ref * 1.25),
                    })
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)
    walk(obj)
    # Deduplicar por carrier/servicio/precio.
    out, seen = [], set()
    for r in encontrados:
        key = (r.get('carrier'), r.get('service'), r.get('precio'))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def cotizar_envio_envia(cp_destino, piezas=None, peso_kg=None, largo_cm=None, ancho_cm=None, alto_cm=None, carriers=None):
    """Cotiza Envia.com SOLO por /ship/rate/. No crea guías ni cobra etiquetas."""
    cfg = _envia_v24_config()
    cp_destino = re.sub(r'\D+', '', str(cp_destino or ''))
    if not re.fullmatch(r'\d{5}', cp_destino or ''):
        return {'ok': False, 'error': 'CP destino inválido', 'opciones': [], 'modo': 'SOLO_COTIZACION_NO_GUIAS'}
    if not cfg['enabled']:
        return {'ok': False, 'error': 'ENVIA_ENABLED no está activo', 'opciones': [], 'modo': 'SOLO_COTIZACION_NO_GUIAS'}
    if not cfg['token']:
        return {'ok': False, 'error': 'ENVIA_TOKEN no configurado', 'opciones': [], 'modo': 'SOLO_COTIZACION_NO_GUIAS'}
    if not re.fullmatch(r'\d{5}', cfg['origin_zip'] or ''):
        return {'ok': False, 'error': 'ENVIA_ORIGIN_ZIP inválido o vacío', 'opciones': [], 'modo': 'SOLO_COTIZACION_NO_GUIAS'}

    carriers = carriers or _envia_v24_carriers()
    paquete = _envia_v24_package(piezas, peso_kg, largo_cm, ancho_cm, alto_cm)
    cache_key = _envia_v24_cache_key(cp_destino, paquete, carriers)
    cached = _envia_v24_cache_get(cache_key)
    if cached:
        return cached

    origin = _envia_v24_address(cfg['origin_zip'], 'origin')
    destination = _envia_v24_address(cp_destino, 'destination')
    base_req = {
        'origin': origin,
        'destination': destination,
        'packages': [paquete],
        'settings': {'currency': cfg['currency'] or 'MXN'},
    }
    opciones, errores = [], []
    for carrier in carriers:
        req_obj = dict(base_req)
        req_obj['shipment'] = {'type': 1, 'carrier': carrier}
        url = cfg['api_base'].rstrip('/') + '/ship/rate/'
        ok, obj, status, err = _envia_v24_http_json('POST', url, req_obj, cfg['token'], cfg['timeout'])
        if not ok:
            # No exponemos token ni payload completo en respuesta al cliente.
            errores.append({'carrier': carrier, 'status': status, 'error': str(err)[:180], 'respuesta': obj})
            continue
        rates = _envia_v24_collect_rates(obj, carrier)
        if not rates:
            errores.append({'carrier': carrier, 'status': status, 'error': 'Sin tarifas disponibles', 'respuesta': obj})
        opciones.extend(rates)

    opciones = sorted(opciones, key=lambda x: float(x.get('precio') or 0))
    resp = {
        'ok': bool(opciones),
        'cp_destino': cp_destino,
        'cp_origen': cfg['origin_zip'],
        'env': cfg['env'],
        'modo': 'SOLO_COTIZACION_NO_GUIAS',
        'desde_cache': False,
        'paquete': paquete,
        'opciones': opciones,
        # Errores solo para diagnostico interno/API, no para respuesta pública.
        'errores': errores[:10],
    }
    _envia_v24_cache_set(cache_key, cp_destino, {'base': base_req, 'carriers': carriers}, resp)
    return resp


@app.route('/api/envios/cotizar', methods=['GET', 'POST'])
def api_envios_cotizar_v24():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
    else:
        data = request.args.to_dict(flat=True)
    cp = data.get('cp_destino') or data.get('cp') or data.get('codigo_postal') or data.get('postalCode') or ''
    carriers_raw = data.get('carriers') or data.get('paqueterias') or ''
    carriers = None
    if carriers_raw:
        if isinstance(carriers_raw, str):
            carriers = [re.sub(r'\s+', '', c.strip().lower()) for c in carriers_raw.split(',') if c.strip()]
        elif isinstance(carriers_raw, list):
            carriers = [re.sub(r'\s+', '', str(c).strip().lower()) for c in carriers_raw if str(c).strip()]
    result = cotizar_envio_envia(
        cp,
        piezas=data.get('piezas'),
        peso_kg=data.get('peso_kg') or data.get('peso'),
        largo_cm=data.get('largo_cm') or data.get('largo'),
        ancho_cm=data.get('ancho_cm') or data.get('ancho'),
        alto_cm=data.get('alto_cm') or data.get('alto'),
        carriers=carriers,
    )
    status = 200 if result.get('ok') or result.get('opciones') else 400
    return jsonify(json_safe(result)), status


def _envia_v24_formato_publico(cp, cotizacion):
    opciones = (cotizacion or {}).get('opciones') or []
    if not opciones:
        return (
            f"Con el CP {cp} necesito revisar el envío manualmente 😊 "
            "No me aparecen opciones automáticas seguras en este momento."
        )
    lineas = []
    vistos = set()
    for op in opciones[:6]:
        nombre = op.get('paqueteria') or op.get('carrier') or 'Paquetería'
        servicio = op.get('servicio') or op.get('service') or ''
        precio = float(op.get('precio') or 0)
        moneda = op.get('moneda') or 'MXN'
        key = (str(nombre).lower(), str(servicio).lower(), round(precio, 2))
        if key in vistos:
            continue
        vistos.add(key)
        desc = f"🚚 {nombre}: ${precio:,.2f} {moneda}"
        if servicio and servicio.lower() not in str(nombre).lower():
            desc += f" ({servicio})"
        if op.get('entrega'):
            desc += f" — {op.get('entrega')}"
        lineas.append(desc)
    if not lineas:
        return f"Con el CP {cp} necesito revisar el envío manualmente 😊"
    extra = ''
    if any(op.get('posible_reexpedicion') for op in opciones):
        extra = '\n\nPara ese CP el costo puede cambiar por zona o servicio; se lo confirmo antes de cerrar la nota.'
    cache_txt = ' (cotización guardada)' if (cotizacion or {}).get('desde_cache') else ''
    return (
        f"A su zona con CP {cp} me aparecen estas opciones{cache_txt}:\n\n" +
        "\n".join(lineas) +
        "\n\nEsta cotización es para el paquete configurado y puede variar si cambia peso o volumen. ¿Cuál le gustaría usar?" +
        extra
    )


# Guardamos la función anterior como respaldo si Envia falla o no está configurado.
_wa_v24_envio_opciones_anterior = _wa_v22_envio_opciones_texto


def _wa_v22_envio_opciones_texto(cp=''):
    cp_m = re.search(r'\b\d{5}\b', str(cp or ''))
    if not cp_m:
        return "Claro 😊 para decirle el costo exacto de envío necesito su código postal."
    cp_txt = cp_m.group(0)
    try:
        cot = cotizar_envio_envia(cp_txt)
        if cot.get('ok') and cot.get('opciones'):
            return _envia_v24_formato_publico(cp_txt, cot)
        # Si Envia está activo pero no regresó tarifas, no inventamos precio.
        if _envia_v24_config().get('enabled'):
            return (
                f"Con el CP {cp_txt} necesito revisar el envío manualmente 😊 "
                "No me aparece una tarifa automática segura en este momento."
            )
    except Exception as exc:
        print('WARN Envia cotizacion WA:', exc, flush=True)
    # Respaldo anterior solo si Envia no está activo/configurado.
    return _wa_v24_envio_opciones_anterior(cp_txt)


_wa_v24_clasificar_anterior = _clasificar_intencion_wa


def _clasificar_intencion_wa(texto, parsed):
    meta = _wa_v24_clasificar_anterior(texto, parsed)
    t = _wa_v22_norm(texto)
    # Un CP solo, después de hablar de envío, debe disparar cotización y no tratarse como código de hilo.
    if re.fullmatch(r'\s*(?:cp\s*)?\d{5}\s*', str(texto or ''), re.I) or re.search(r'\b(codigo postal|código postal|cp|envio|envío|paqueteria|paquetería)\b', t):
        meta['intencion'] = 'pregunta_envio'
        meta['accion_recomendada'] = 'cotizar_envio_revision'
        meta['confianza'] = 'media'
        meta['puede_auto_enviar'] = False
    return meta


_wa_v24_view_anterior = app.view_functions.get('whatsapp_ia_simular')


def whatsapp_ia_simular_v24():
    out = _wa_v24_view_anterior()
    status = 200
    response = out
    if isinstance(out, tuple):
        response = out[0]
        if len(out) > 1:
            status = out[1]
    try:
        data = response.get_json() if hasattr(response, 'get_json') else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return out
    # Si el mensaje trae CP/envío y Envia está configurado, forzamos respuesta de cotización real.
    texto_req = ''
    try:
        req_data = request.get_json(silent=True) or {}
        texto_req = ' '.join(str(req_data.get(k) or '') for k in ('texto', 'texto_imagen'))
    except Exception:
        texto_req = ''
    if re.search(r'\b\d{5}\b', texto_req) and re.search(r'\b(cp|codigo postal|código postal|envio|envío|paqueteria|paquetería|\d{5})\b', _wa_v22_norm(texto_req)):
        data['respuesta_sugerida'] = _wa_v22_envio_opciones_texto(texto_req)
        data['intencion'] = 'pregunta_envio'
        data['accion_recomendada'] = 'cotizar_envio_revision'
        data['puede_auto_enviar'] = False
    data['motor'] = str(data.get('motor') or '') + ':v24_envia_solo_cotizacion'
    return jsonify(json_safe(data)), status


app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v24

# ==========================================================
# V25 - Envia cotizacion: CP offline + estados Envia + cache nuevo
# ==========================================================
# Motivo: en produccion algunos tokens no permiten Geocodes API (403 Forbidden).
# Para Mexico usamos cp_offline.json local para ciudad/estado y normalizamos estados
# a claves de Envia como NL, CX, YU, EM. Seguimos SOLO cotizando: nunca genera guias.

_ENVIA_V25_CP_CACHE = None

_ENVIA_V25_ESTADOS = {
    'aguascalientes': 'AG',
    'baja california': 'BC',
    'baja california norte': 'BC',
    'baja california sur': 'BS',
    'campeche': 'CM',
    'chiapas': 'CS',
    'chihuahua': 'CH',
    'ciudad de mexico': 'CX',
    'ciudad de méxico': 'CX',
    'cdmx': 'CX',
    'distrito federal': 'CX',
    'coahuila': 'CO',
    'coahuila de zaragoza': 'CO',
    'colima': 'CL',
    'durango': 'DG',
    'estado de mexico': 'EM',
    'estado de méxico': 'EM',
    'mexico': 'EM',
    'méxico': 'EM',
    'edomex': 'EM',
    'guanajuato': 'GT',
    'guerrero': 'GR',
    'hidalgo': 'HG',
    'jalisco': 'JA',
    'michoacan': 'MI',
    'michoacán': 'MI',
    'michoacan de ocampo': 'MI',
    'michoacán de ocampo': 'MI',
    'morelos': 'MO',
    'nayarit': 'NA',
    'nuevo leon': 'NL',
    'nuevo león': 'NL',
    'oaxaca': 'OA',
    'puebla': 'PU',
    'queretaro': 'QE',
    'querétaro': 'QE',
    'quintana roo': 'QR',
    'san luis potosi': 'SL',
    'san luis potosí': 'SL',
    'sinaloa': 'SI',
    'sonora': 'SO',
    'tabasco': 'TB',
    'tamaulipas': 'TM',
    'tlaxcala': 'TL',
    'veracruz': 'VE',
    'veracruz de ignacio de la llave': 'VE',
    'yucatan': 'YU',
    'yucatán': 'YU',
    'zacatecas': 'ZA',
}


def _envia_v25_norm_txt(s):
    try:
        import unicodedata
        s = str(s or '').strip().lower()
        s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        s = re.sub(r'[^a-z0-9 ]+', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s
    except Exception:
        return str(s or '').strip().lower()


def _envia_v25_state_code(valor):
    raw = str(valor or '').strip()
    if not raw:
        return ''
    up = raw.upper().strip()
    # Ya viene como clave de Envia de 2 letras; no tocar.
    if re.fullmatch(r'[A-Z]{2}', up):
        return up
    return _ENVIA_V25_ESTADOS.get(_envia_v25_norm_txt(raw), raw)


def _envia_v25_cp_data():
    global _ENVIA_V25_CP_CACHE
    if _ENVIA_V25_CP_CACHE is not None:
        return _ENVIA_V25_CP_CACHE
    try:
        ruta = os.path.join(APP_DIR, 'cp_offline.json')
        with open(ruta, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            _ENVIA_V25_CP_CACHE = data
        else:
            _ENVIA_V25_CP_CACHE = {}
    except Exception as exc:
        print('WARN Envia V25 no pudo leer cp_offline.json:', exc, flush=True)
        _ENVIA_V25_CP_CACHE = {}
    return _ENVIA_V25_CP_CACHE


def _envia_v25_cp_info(cp):
    cp = re.sub(r'\D+', '', str(cp or ''))
    data = _envia_v25_cp_data()
    info = data.get(cp) or {}
    if not isinstance(info, dict):
        return {}
    estado = str(info.get('estado') or '').strip()
    municipio = str(info.get('municipio') or '').strip()
    colonias = info.get('colonias') or []
    colonia = ''
    if isinstance(colonias, list) and colonias:
        colonia = str(colonias[0] or '').strip()
    return {
        'city': municipio,
        'state': _envia_v25_state_code(estado),
        'state_name': estado,
        'locality': colonia,
    }


_envia_v25_config_base = _envia_v24_config
_envia_v25_geocode_old = _envia_v24_geocode_zip
_envia_v25_cache_key_old = _envia_v24_cache_key


def _envia_v24_config():
    cfg = _envia_v25_config_base()
    # Corregir ENVIA_ORIGIN_STATE si el usuario puso "Estado de Mexico" o nombre completo.
    origin_info = _envia_v25_cp_info(cfg.get('origin_zip'))
    if not str(cfg.get('origin_city') or '').strip() and origin_info.get('city'):
        cfg['origin_city'] = origin_info.get('city')
    if not str(cfg.get('origin_state') or '').strip() and origin_info.get('state'):
        cfg['origin_state'] = origin_info.get('state')
    else:
        cfg['origin_state'] = _envia_v25_state_code(cfg.get('origin_state'))
    cfg['version'] = 'v25_cp_offline'
    return cfg


def _envia_v24_geocode_zip(country, cp):
    cp = re.sub(r'\D+', '', str(cp or ''))
    country = (country or 'MX').strip().upper()
    if country == 'MX':
        info = _envia_v25_cp_info(cp)
        if info.get('city') or info.get('state'):
            return {'city': info.get('city') or 'Ciudad', 'state': info.get('state') or '', 'locality': info.get('locality') or '', 'source': 'cp_offline'}
    # Por defecto NO dependemos de Geocodes porque puede regresar 403 aunque /ship/rate/ funcione.
    # Si se necesita probar Geocodes, activar ENVIA_USE_GEOCODE=1.
    if _envia_v24_bool_env('ENVIA_USE_GEOCODE', False):
        return _envia_v25_geocode_old(country, cp)
    return {'city': 'Ciudad', 'state': '', 'locality': '', 'source': 'fallback_no_geocode'}


def _envia_v24_address(cp, tipo='destination', nombre='Cliente'):
    cfg = _envia_v24_config()
    country = cfg['origin_country'] or 'MX'
    cp = re.sub(r'\D+', '', str(cp or ''))
    geo = _envia_v24_geocode_zip(country, cp)
    if tipo == 'origin':
        return {
            'name': cfg['origin_name'] or 'Hilorama',
            'phone': cfg['origin_phone'] or '+520000000000',
            'street': cfg['origin_street'] or 'Origen Hilorama',
            'city': cfg['origin_city'] or geo.get('city') or 'Ciudad',
            'state': _envia_v25_state_code(cfg['origin_state'] or geo.get('state') or ''),
            'country': country,
            'postalCode': cp,
        }
    return {
        'name': nombre or 'Cliente Hilorama',
        'phone': os.environ.get('ENVIA_DESTINATION_PHONE', '+520000000000'),
        'street': os.environ.get('ENVIA_DESTINATION_STREET', 'Por confirmar'),
        'city': geo.get('city') or 'Ciudad',
        'state': _envia_v25_state_code(geo.get('state') or ''),
        'country': country,
        'postalCode': cp,
    }


def _envia_v24_cache_key(cp_destino, paquete, carriers):
    # Cambiamos version para no reutilizar errores/cache de V24 donde fallaba Geocodes.
    cfg = _envia_v24_config()
    base = {
        'version': 'v25_cp_offline',
        'env': cfg.get('env'),
        'origin_zip': cfg.get('origin_zip'),
        'origin_state': cfg.get('origin_state'),
        'cp_destino': re.sub(r'\D+', '', str(cp_destino or '')),
        'package': paquete,
        'carriers': carriers,
    }
    return json.dumps(base, sort_keys=True, ensure_ascii=False)


# Endpoint ligero para revisar qué dirección enviaría a Envia, sin exponer token.
@app.route('/api/envios/debug-direccion', methods=['GET'])
def api_envios_debug_direccion_v25():
    cp = request.args.get('cp') or request.args.get('cp_destino') or ''
    cfg = _envia_v24_config()
    return jsonify(json_safe({
        'ok': True,
        'modo': 'V25_SOLO_DEBUG_NO_GUIAS',
        'env': cfg.get('env'),
        'origin': _envia_v24_address(cfg.get('origin_zip'), 'origin'),
        'destination': _envia_v24_address(cp, 'destination'),
        'carriers': _envia_v24_carriers(),
        'nota': 'No se muestra ENVIA_TOKEN. Este endpoint solo ayuda a revisar ciudad/estado/CP.',
    }))


# -----------------------------------------------------------------------------
# V26 - Entendimiento conversacional: pausas humanas + cantidades "5 del 55"
# -----------------------------------------------------------------------------
# Corrige casos reales de WhatsApp donde la clienta escribe por partes:
#   "hola buenas tardes quiero cotizar un pedido de velluto son 15 madejas"
#   "5 del 55 y 10 del 60"
# El agente debe seguir el hilo de Velluto, ignorar el total "15 madejas" como
# código, y entender "5 del 55" = cantidad 5 del código 55.

WA_V26_BUFFER_SECONDS = int(os.environ.get('WA_MESSAGE_BUFFER_SECONDS', '35') or '35')
WA_V26_CONTEXT_STRONG_MINUTES = int(os.environ.get('WA_CONTEXT_STRONG_MINUTES', '30') or '30')

try:
    _wa_v26_linea_anterior
except NameError:
    _wa_v26_linea_anterior = _wa_v17_linea_a_item

try:
    _wa_v26_extraer_anterior
except NameError:
    _wa_v26_extraer_anterior = _wa_v17_extraer_items_lista


def _wa_v26_norm(v):
    try:
        return _wa_v22_norm(v or '')
    except Exception:
        return re.sub(r'\s+', ' ', str(v or '').lower()).strip()


def _wa_v26_limpiar_intro_pedido(texto):
    """Quita cortesía/encabezados sin borrar los items reales."""
    s = str(texto or '').replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s).strip(' ,.;')
    # Quitar saludos y frases de intención, pero conservar lo que viene después.
    s = re.sub(r'^(?:hola|ola|buen\s+dia|buen\s+día|buenas\s+tardes|buenas\s+noches|buenos\s+dias|buenos\s+días)\b\s*,?\s*', '', s, flags=re.I).strip()
    s = re.sub(r'^(?:quiero|quisiera|me\s+gustaria|me\s+gustaría|podria|podría|me\s+puede)\s+', '', s, flags=re.I).strip()
    return s


def _wa_v26_items_cantidad_del_codigo(texto):
    """Detecta expresiones humanas: 5 del 55, 10 de 60, 3 piezas del código 429."""
    raw = str(texto or '').strip()
    if not raw:
        return []
    s = raw.replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s)
    # Evitar que totales como "son 15 madejas" se traten como producto.
    s = re.sub(r'\b(?:son|serian|serían|seria|sería|total(?:es)?)\s+\d{1,3}\s*(?:madejas?|piezas?|pzas?|pz)\b', ' ', s, flags=re.I)
    s = re.sub(r'\b\d{1,3}\s*(?:madejas?|piezas?|pzas?|pz)\s+en\s+total\b', ' ', s, flags=re.I)

    items = []
    # 5 del 55 / 10 de 60 / 3 piezas del codigo 429 / 2 pzas tono 56
    pat = re.compile(
        r'(?<!\d)(\d{1,3})\s*'
        r'(?:pzas?|piezas?|madejas?|unidades?)?\s*'
        r'(?:del|de\s+el|de|codigo|código|cod|tono|color)\s*'
        r'(?:#|n[uú]m(?:ero)?\.?\s*)?'
        r'(\d{1,4})(?!\d)',
        flags=re.I
    )
    for m in pat.finditer(s):
        qty = int(m.group(1))
        code_raw = m.group(2)
        # Si accidentalmente el "código" parece CP largo, no tomarlo. Aquí ya limitamos a 4.
        if qty <= 0:
            continue
        items.append({
            'codigo': code_raw.lstrip('0') or code_raw,
            'codigo_raw': code_raw,
            'cantidad': qty,
            'desc': '',
            'raw': m.group(0).strip(),
            'fuente': 'v26_cantidad_del_codigo',
        })
    return items


def _wa_v26_items_codigo_con_cantidad_contextual(texto):
    """Detecta: del 55 quiero 5, código 60 serían 10. Menos común, pero útil."""
    raw = str(texto or '').strip()
    if not raw:
        return []
    s = raw.replace('×', 'x').replace('–', '-').replace('—', '-')
    s = re.sub(r'\s+', ' ', s)
    items = []
    pat = re.compile(
        r'(?:del|de\s+el|de|codigo|código|cod|tono|color)\s*(\d{1,4})\s*'
        r'(?:quiero|deme|dame|ponme|agregue|agrega|serian|serían|son)?\s*'
        r'(\d{1,3})\s*(?:pzas?|piezas?|madejas?|unidades?)?\b',
        flags=re.I
    )
    for m in pat.finditer(s):
        code_raw = m.group(1)
        qty = int(m.group(2))
        if qty <= 0:
            continue
        items.append({
            'codigo': code_raw.lstrip('0') or code_raw,
            'codigo_raw': code_raw,
            'cantidad': qty,
            'desc': '',
            'raw': m.group(0).strip(),
            'fuente': 'v26_codigo_cantidad_contextual',
        })
    return items


def _wa_v26_dedup_items(items):
    out = []
    seen = set()
    for it in items or []:
        key = (str(it.get('codigo_raw') or it.get('codigo') or ''), int(it.get('cantidad') or 1), _wa_v26_norm(it.get('raw') or ''))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _wa_v17_linea_a_item(linea):
    """V26: agrega lectura humana de cantidad antes del código."""
    raw = str(linea or '').strip()
    if not raw:
        return []

    # Primero detectar expresiones inequívocas de cantidad + código.
    items = _wa_v26_items_cantidad_del_codigo(raw) + _wa_v26_items_codigo_con_cantidad_contextual(raw)
    if items:
        return _wa_v26_dedup_items(items)

    # Si no es ese caso, usar todo lo anterior.
    try:
        return _wa_v26_linea_anterior(linea)
    except Exception:
        return []


def _wa_v17_extraer_items_lista(texto_cliente):
    """V26: una frase completa también puede contener lista/pedido."""
    texto = str(texto_cliente or '').strip()
    if not texto:
        return [], False

    # Caso prioritario: pedido humano en una sola frase o en mensaje separado.
    items_humanos = []
    for bloque in re.split(r'[\n,;]+', texto):
        items_humanos.extend(_wa_v26_items_cantidad_del_codigo(bloque))
        items_humanos.extend(_wa_v26_items_codigo_con_cantidad_contextual(bloque))
    # También revisar el texto completo para frases con "y": 5 del 55 y 10 del 60.
    items_humanos.extend(_wa_v26_items_cantidad_del_codigo(texto))
    items_humanos.extend(_wa_v26_items_codigo_con_cantidad_contextual(texto))
    items_humanos = _wa_v26_dedup_items(items_humanos)

    if items_humanos:
        t = _wa_v26_norm(texto)
        # Si se detectó qty+codigo, es pedido aunque no diga "lista".
        es_pedido = True
        # Evitar confundir preguntas tipo "foto del 55" (no debería entrar porque no hay qty antes), por seguridad.
        if re.search(r'\b(foto|imagen|mostrar|muestra|ver|enseñar|ensena|enseña)\b', t) and not re.search(r'\b(quiero|deme|dame|ponme|agregar|agregue|cotizar|pedido|surtir|surte)\b', t):
            es_pedido = False
        if es_pedido:
            return items_humanos, True

    try:
        return _wa_v26_extraer_anterior(texto_cliente)
    except Exception:
        return [], False


def _wa_v26_es_mensaje_preparatorio(texto):
    """Mensajes humanos que abren una intención pero todavía no traen productos."""
    t = _wa_v26_norm(texto)
    if not t:
        return False
    if _wa_v17_extraer_items_lista(texto)[0]:
        return False
    return bool(re.search(r'\b(quiero|quisiera|me\s+gustaria|me\s+gustaría|voy\s+a|le\s+paso|mando|mandar|pasar|cotizar|cotizacion|cotización|pedido|lista)\b', t))


def _wa_v26_respuesta_preparatoria(texto, memoria):
    t = _wa_v26_norm(texto)
    hilo = (memoria or {}).get('hilo_actual') or (memoria or {}).get('ultimo_hilo') or ''
    if 'velluto' in t:
        hilo = 'VELLUTO'
    elif 'komfy' in t or 'konfy' in t or 'comfy' in t:
        hilo = 'KOMFY MINI'
    if hilo:
        return f"Claro 😊 mándeme la lista cuando guste y se la cotizo en {hilo}."
    return "Claro 😊 mándeme la lista cuando guste y se la cotizo."


_wa_v26_view_anterior = app.view_functions.get('whatsapp_ia_simular')


def whatsapp_ia_simular_v26():
    """V26: maneja mejor mensajes por pausas y pedidos en mensajes separados."""
    data = request.get_json(force=True) or {}
    texto_original = (data.get('texto') or '').strip()
    marca = _wa_v19_clean_selector(data.get('marca') or '')
    hilo = _wa_v19_clean_selector(data.get('hilo') or '')
    telefono = (data.get('telefono') or '').strip()
    conversacion_id = data.get('conversacion_id')
    nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

    # Si solo es un mensaje preparatorio sin productos, responder humano y guardar contexto.
    # En WhatsApp real este tipo de mensaje se puede esperar/agrupir por WA_MESSAGE_BUFFER_SECONDS.
    try:
        export_info = _wa_v16_extraer_bloque_cliente(texto_original, telefono)
        texto_cliente = (export_info.get('texto_cliente') or texto_original).strip()
        memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)
        productos_mem = _wa_memoria_productos_min()
        hilos = _wa_memoria_detectar_hilos_explicitos(texto_cliente, productos_mem) or []
        if _wa_v26_es_mensaje_preparatorio(texto_cliente) and not hilos:
            # Si no menciona hilo y tampoco hay memoria, dejar que el flujo anterior pregunte mejor.
            pass
        elif _wa_v26_es_mensaje_preparatorio(texto_cliente) and not re.search(r'\b\d{1,4}\b', texto_cliente):
            # Menciona pedido/lista, pero aún no manda productos.
            marca_parser, hilo_parser, memoria_aplicada = _wa_memoria_resolver_contexto_para_parser(
                texto_cliente, marca, hilo, memoria_previa, productos_mem
            )
            if hilo_parser or hilos:
                if nueva_conversacion:
                    conversacion_id = None
                conversacion_id = _wa_v15_ensure_conversacion(conversacion_id, telefono, (data.get('cliente_nombre') or '').strip())
                parsed = {'ok': True, 'modo': 'v26_mensaje_preparatorio_pedido', 'pedidos': [], 'preguntas': [], 'errores': [], 'advertencias': [], 'contexto': {'hilo': hilo_parser or (hilos[0] if hilos else '')}}
                meta = {'intencion': 'pedido_en_espera', 'confianza': 'alta', 'accion_recomendada': 'esperar_lista', 'puede_auto_enviar': False}
                respuesta = _wa_v26_respuesta_preparatoria(texto_cliente, {'hilo_actual': hilo_parser or (hilos[0] if hilos else '')})
                try:
                    with DB() as db:
                        db.execute("""
                            INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                            VALUES (%s,%s,%s,%s,%s,%s)
                        """, (conversacion_id, 'IN', 'texto', texto_cliente, respuesta, json.dumps({'parsed': parsed, 'meta': meta, 'motor': 'v26_mensaje_preparatorio', 'buffer_seconds': WA_V26_BUFFER_SECONDS}, ensure_ascii=False)))
                except Exception as exc:
                    print('WARN guardar preparatorio v26:', exc, flush=True)
                memoria_actualizada = _wa_memoria_actualizar(
                    conversacion_id=conversacion_id,
                    telefono=telefono,
                    cliente_nombre=(data.get('cliente_nombre') or '').strip(),
                    texto=texto_cliente,
                    respuesta=respuesta,
                    parsed=parsed,
                    meta=meta,
                    marca_parser=marca_parser,
                    hilo_parser=hilo_parser or (hilos[0] if hilos else ''),
                    memoria_previa=memoria_previa,
                    productos=productos_mem,
                )
                return jsonify(json_safe({
                    'ok': True,
                    'conversacion_id': conversacion_id,
                    'motor': 'reglas_hilorama_v26_mensaje_preparatorio_buffer',
                    'mensaje_cliente': texto_cliente,
                    'mensaje_parser': texto_cliente,
                    'respuesta_sugerida': respuesta,
                    'intencion': meta.get('intencion'),
                    'confianza': meta.get('confianza'),
                    'accion_recomendada': meta.get('accion_recomendada'),
                    'puede_auto_enviar': meta.get('puede_auto_enviar'),
                    'pedidos': [],
                    'preguntas': [],
                    'errores': [],
                    'advertencias': [f'V26: mensaje preparatorio. En WhatsApp real se espera {WA_V26_BUFFER_SECONDS}s para agrupar si la clienta sigue escribiendo.'],
                    'parser': parsed,
                    'memoria_usada': memoria_previa,
                    'memoria_actual': memoria_actualizada,
                    'whatsapp_export': export_info,
                }))
    except Exception as exc:
        print('WARN v26 preparatorio:', exc, flush=True)

    out = _wa_v26_view_anterior()
    try:
        resp = out.get_json() if hasattr(out, 'get_json') else None
        if isinstance(resp, dict):
            resp['motor'] = str(resp.get('motor') or '') + ':v26_cantidades_del_codigo_pausas'
            adv = resp.get('advertencias') or []
            # Si detectamos items humanos, anotar internamente.
            items, es_lista = _wa_v17_extraer_items_lista(texto_original)
            if es_lista and any((it.get('fuente') or '').startswith('v26') for it in items):
                adv.append('V26: se interpretó cantidad antes del código, por ejemplo "5 del 55" = 5 piezas del código 55.')
                resp['items_lista_v26'] = items
            resp['advertencias'] = adv
            return jsonify(json_safe(resp))
    except Exception:
        pass
    return out


app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v26

# -----------------------------------------------------------------------------
# V27 - Motor conversacional ordenado: normaliza -> intencion -> memoria ->
# almacen -> respuesta humana.
# -----------------------------------------------------------------------------


def _wa_v27_memoria_schema():
    _wa_memoria_schema()
    try:
        with DB() as db:
            for col_sql in [
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS intencion_actual TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS estado_actual TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultima_lista_pendiente TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS ultima_pregunta_hecha TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS total_esperado INTEGER",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS datos_envio_pendientes BOOLEAN DEFAULT FALSE",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS cp_actual TEXT",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS pago_pendiente BOOLEAN DEFAULT FALSE",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS cotizacion_activa BOOLEAN DEFAULT FALSE",
                "ALTER TABLE whatsapp_contexto_cliente ADD COLUMN IF NOT EXISTS fecha_ultima_actividad TIMESTAMP",
            ]:
                db.execute(col_sql)
            db.execute("CREATE INDEX IF NOT EXISTS idx_wa_contexto_fecha_actividad ON whatsapp_contexto_cliente(fecha_ultima_actividad)")
    except Exception as exc:
        print('WARN schema memoria WA v27:', exc, flush=True)


def _wa_v27_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'si', 'sí', 'on')


def _wa_v27_json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    return [x for x in obj if isinstance(x, dict)] if isinstance(obj, list) else []


def _wa_v27_piezas_desde_memoria(contexto):
    memoria = (contexto or {}).get('memoria_previa') or {}
    for key in ('pedido_en_proceso', 'ultima_lista_pendiente', 'ultima_lista_recibida'):
        items = _wa_v27_json_list(memoria.get(key))
        total = 0
        for it in items:
            if it.get('codigo') or it.get('codigo_raw') or it.get('producto_id') or it.get('color') or it.get('desc'):
                try:
                    total += int(it.get('cantidad') or 1)
                except Exception:
                    total += 1
        if total > 0:
            return total
    return None


def _wa_v27_envio_formato_publico(cp, cotizacion):
    opciones = (cotizacion or {}).get('opciones') or []
    if not opciones:
        return (
            f"Con el CP {cp} necesito revisar el envio manualmente \U0001f60a "
            "No me aparece una tarifa automatica segura en este momento."
        )
    lineas = []
    vistos = set()
    for op in opciones[:3]:
        nombre = op.get('paqueteria') or op.get('carrier') or 'Paqueteria'
        servicio = op.get('servicio') or op.get('service') or ''
        try:
            precio = float(op.get('precio') or 0)
        except Exception:
            precio = 0.0
        moneda = op.get('moneda') or 'MXN'
        key = (str(nombre).lower(), str(servicio).lower(), round(precio, 2))
        if key in vistos:
            continue
        vistos.add(key)
        desc = f"- {nombre}: ${precio:,.2f} {moneda}"
        if servicio and servicio.lower() not in str(nombre).lower():
            desc += f" ({servicio})"
        if op.get('entrega'):
            desc += f" - {op.get('entrega')}"
        lineas.append(desc)
    if not lineas:
        return f"Con el CP {cp} necesito revisar el envio manualmente \U0001f60a"
    return (
        f"Con el CP {cp} me aparecen estas opciones de envio:\n\n" +
        "\n".join(lineas) +
        "\n\nLa cotizacion puede variar si cambia peso, volumen o zona. Cual le gustaria usar?"
    )


def _wa_v27_buscar_recurso(intencion, normalizado, contexto, extraccion):
    principal = (intencion or {}).get('principal') or ''
    texto = (normalizado or {}).get('texto') or ''
    consulta = ' '.join(x for x in [texto, (contexto or {}).get('hilo_actual'), (contexto or {}).get('marca_actual')] if x)
    try:
        if principal == 'pide_foto_tono':
            recurso = _wa_v10_tone_resource_from_code(consulta)
            if recurso:
                return {
                    'respuesta': _wa_v7_respuesta_de_recurso(recurso),
                    'recurso': recurso,
                    'motor': 'biblioteca_ia_tono_exacto_v27',
                }
        if principal == 'pide_gama':
            recurso = _wa_v7_buscar_recurso(consulta, categoria='carta_colores')
            if recurso:
                return {
                    'respuesta': _wa_v7_respuesta_de_recurso(recurso),
                    'recurso': recurso,
                    'motor': 'biblioteca_ia_carta_colores_v27',
                }
    except Exception as exc:
        print('WARN recurso WA v27:', exc, flush=True)
    return {}


def _wa_v27_cotizar_envio(cp, contexto):
    cp = re.sub(r'\D+', '', str(cp or ''))
    if not re.fullmatch(r'\d{5}', cp):
        return {'respuesta': "Claro \U0001f60a para decirle el costo exacto de envio necesito su codigo postal."}
    try:
        piezas = _wa_v27_piezas_desde_memoria(contexto)
        cot = cotizar_envio_envia(cp, piezas=piezas)
        if cot.get('ok') and cot.get('opciones'):
            return {'respuesta': _wa_v27_envio_formato_publico(cp, cot), 'cotizacion': cot}
        if _envia_v24_config().get('enabled'):
            return {
                'respuesta': (
                    f"Con el CP {cp} necesito revisar el envio manualmente \U0001f60a "
                    "No me aparece una tarifa automatica segura en este momento."
                ),
                'cotizacion': cot,
            }
    except Exception as exc:
        print('WARN cotizar envio WA v27:', exc, flush=True)
    try:
        return {'respuesta': _wa_v22_envio_opciones_texto(cp)}
    except Exception:
        return {
            'respuesta': (
                f"Con el CP {cp} necesito revisar el envio manualmente \U0001f60a "
                "No me aparece una tarifa automatica segura en este momento."
            )
        }


def _wa_v27_parser_obj(resultado):
    resolucion = resultado.get('resolucion') or {}
    extraccion = resultado.get('extraccion') or {}
    contexto = resultado.get('contexto') or {}
    return {
        'ok': True,
        'modo': 'v27_motor_conversacional',
        'pedidos': resolucion.get('pedidos') or [],
        'preguntas': resolucion.get('preguntas') or [],
        'errores': resolucion.get('errores') or [],
        'advertencias': (resolucion.get('internos') or []) + [
            str(s.get('tipo') or s) for s in (resolucion.get('sugerencias') or [])
        ],
        'items_lista_v17': extraccion.get('items') or [],
        'items_lista_v27': extraccion.get('items') or [],
        'contexto': {
            'hilo': contexto.get('hilo_actual') or '',
            'marca': contexto.get('marca_actual') or '',
            'origen_contexto': contexto.get('origen_contexto') or '',
            'contexto_inferido': {
                'hilo': contexto.get('hilo_actual') or '',
                'marca': contexto.get('marca_actual') or '',
            },
        },
    }


def _wa_v27_meta_obj(resultado):
    confianza = resultado.get('confianza') or {}
    intencion = resultado.get('intencion') or {}
    return {
        'intencion': intencion.get('principal') or '',
        'confianza': confianza.get('confianza') or 'media',
        'accion_recomendada': confianza.get('accion_recomendada') or 'responder_revision',
        'puede_auto_enviar': False,
    }


def _wa_v27_actualizar_memoria_db(conversacion_id, telefono, cliente_nombre, texto, resultado, memoria_previa, productos):
    _wa_v27_memoria_schema()
    parsed = _wa_v27_parser_obj(resultado)
    meta = _wa_v27_meta_obj(resultado)
    contexto = resultado.get('contexto') or {}
    memoria_v27 = resultado.get('memoria') or {}
    respuesta = resultado.get('respuesta') or ''
    marca_parser = contexto.get('marca_actual') or memoria_v27.get('marca_actual') or ''
    hilo_parser = contexto.get('hilo_actual') or memoria_v27.get('hilo_actual') or ''
    row = _wa_memoria_actualizar(
        conversacion_id=conversacion_id,
        telefono=telefono,
        cliente_nombre=cliente_nombre,
        texto=texto,
        respuesta=respuesta,
        parsed=parsed,
        meta=meta,
        marca_parser=marca_parser,
        hilo_parser=hilo_parser,
        memoria_previa=memoria_previa,
        productos=productos,
    )
    clave = _wa_memoria_clave(conversacion_id, telefono)
    if not clave:
        return row or memoria_v27
    try:
        total = memoria_v27.get('total_esperado')
        try:
            total = int(total) if str(total or '').strip() else None
        except Exception:
            total = None
        with DB() as db:
            updated = db.execute("""
                UPDATE whatsapp_contexto_cliente
                SET intencion_actual=%s,
                    estado_actual=%s,
                    ultima_lista_pendiente=%s,
                    ultima_pregunta_hecha=%s,
                    total_esperado=%s,
                    datos_envio_pendientes=%s,
                    cp_actual=%s,
                    pago_pendiente=%s,
                    cotizacion_activa=%s,
                    fecha_ultima_actividad=%s,
                    updated_at=%s
                WHERE clave=%s
                RETURNING *
            """, (
                memoria_v27.get('intencion_actual') or meta.get('intencion') or '',
                memoria_v27.get('estado_actual') or '',
                memoria_v27.get('ultima_lista_pendiente') or '',
                memoria_v27.get('ultima_pregunta_hecha') or '',
                total,
                _wa_v27_bool(memoria_v27.get('datos_envio_pendientes')),
                memoria_v27.get('cp_actual') or '',
                _wa_v27_bool(memoria_v27.get('pago_pendiente')),
                _wa_v27_bool(memoria_v27.get('cotizacion_activa')),
                now_mexico(),
                now_mexico(),
                clave,
            )).fetchone()
        return dict(updated) if updated else (row or memoria_v27)
    except Exception as exc:
        print('WARN actualizar memoria WA v27:', exc, flush=True)
        return row or memoria_v27


_wa_v27_view_anterior = app.view_functions.get('whatsapp_ia_simular')


def whatsapp_ia_simular_v27():
    try:
        data = request.get_json(force=True) or {}
        texto = (data.get('texto') or '').strip()
        texto_imagen = (data.get('texto_imagen') or '').strip()
        texto_original = ' '.join(x for x in [texto, texto_imagen] if x).strip()
        if not texto_original:
            return jsonify({'ok': False, 'error': 'Escribe o pega un mensaje de clienta primero.'}), 400

        marca = _wa_v19_clean_selector(data.get('marca') or '')
        hilo = _wa_v19_clean_selector(data.get('hilo') or '')
        telefono = (data.get('telefono') or '').strip()
        cliente_nombre = (data.get('cliente_nombre') or '').strip()
        conversacion_id = data.get('conversacion_id')
        nueva_conversacion = bool(data.get('nueva_conversacion') or data.get('reset_contexto'))

        export_info = _wa_v16_extraer_bloque_cliente(texto_original, telefono)
        texto_cliente = (export_info.get('texto_cliente') or texto_original).strip()

        _wa_v27_memoria_schema()
        memoria_previa = {} if nueva_conversacion else _wa_memoria_cargar(conversacion_id, telefono)
        productos_mem = _wa_memoria_productos_min()

        payload = dict(data)
        payload.update({
            'texto': texto_cliente,
            'marca': marca,
            'hilo': hilo,
            'buffer_seconds': int(data.get('buffer_seconds') or WA_V26_BUFFER_SECONDS),
        })
        resultado = procesar_conversacion_v27(
            payload,
            productos_mem,
            memoria=memoria_previa,
            callbacks={
                'buscar_recurso': _wa_v27_buscar_recurso,
                'cotizar_envio': _wa_v27_cotizar_envio,
            },
        )
        respuesta = _wa_v22_sanitizar_respuesta_publica(resultado.get('respuesta') or '')
        resultado['respuesta'] = respuesta

        cierre = resultado.get('cierre_diferido') or {}
        if cierre.get('programar'):
            conversacion_id = _wa_v15_ensure_conversacion(conversacion_id if not nueva_conversacion else None, telefono, cliente_nombre)
            cierre_db = _wa_v15_programar_cierre(
                conversacion_id=conversacion_id,
                telefono=telefono,
                mensaje=cierre.get('mensaje'),
                minutos=cierre.get('minutos'),
            )
            try:
                with DB() as db:
                    db.execute("""
                        INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (
                        conversacion_id,
                        'IN',
                        'texto',
                        texto_cliente,
                        '',
                        json.dumps(json_safe({
                            'motor': 'v27_cierre_diferido',
                            'cierre_programado': cierre_db,
                            'resultado': resultado,
                            'whatsapp_export': export_info,
                        }), ensure_ascii=False),
                    ))
            except Exception as exc:
                print('WARN guardar cierre v27:', exc, flush=True)
            memoria_actual = _wa_v27_actualizar_memoria_db(
                conversacion_id, telefono, cliente_nombre, texto_cliente,
                resultado, memoria_previa, productos_mem
            )
            return jsonify(json_safe({
                'ok': True,
                'conversacion_id': conversacion_id,
                'motor': 'v27_motor_conversacional_cierre_diferido',
                'mensaje_cliente': texto_cliente,
                'mensaje_parser': texto_cliente,
                'respuesta_sugerida': '',
                'respuesta_diferida': cierre_db,
                'intencion': 'agradecimiento',
                'confianza': 'alta',
                'accion_recomendada': 'cierre_diferido',
                'puede_auto_enviar': False,
                'pedidos': [],
                'preguntas': [],
                'errores': [],
                'advertencias': [],
                'parser': _wa_v27_parser_obj(resultado),
                'memoria_usada': memoria_previa,
                'memoria_actual': memoria_actual,
                'whatsapp_export': export_info,
                'v27': resultado,
            }))

        try:
            _wa_v15_cancelar_cierres(conversacion_id, telefono, motivo='cliente_continuo_v27')
        except Exception:
            pass

        conversacion_id = _wa_v15_ensure_conversacion(conversacion_id if not nueva_conversacion else None, telefono, cliente_nombre)
        parsed = _wa_v27_parser_obj(resultado)
        meta = _wa_v27_meta_obj(resultado)
        try:
            with DB() as db:
                db.execute("""
                    INSERT INTO whatsapp_mensajes (conversacion_id, direccion, tipo, texto, respuesta_sugerida, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (
                    conversacion_id,
                    'IN',
                    'texto',
                    texto_cliente,
                    respuesta,
                    json.dumps(json_safe({
                        'parsed': parsed,
                        'meta': meta,
                        'motor': 'v27_motor_conversacional',
                        'memoria_usada': memoria_previa,
                        'resultado': resultado,
                        'whatsapp_export': export_info,
                    }), ensure_ascii=False),
                ))
        except Exception as exc:
            print('WARN guardar simulacion WA v27:', exc, flush=True)

        memoria_actual = _wa_v27_actualizar_memoria_db(
            conversacion_id, telefono, cliente_nombre, texto_cliente,
            resultado, memoria_previa, productos_mem
        )
        return jsonify(json_safe({
            'ok': True,
            'conversacion_id': conversacion_id,
            'motor': 'v27_motor_conversacional',
            'mensaje_cliente': texto_cliente,
            'mensaje_parser': texto_cliente,
            'respuesta_sugerida': respuesta,
            'intencion': meta.get('intencion'),
            'confianza': meta.get('confianza'),
            'accion_recomendada': meta.get('accion_recomendada'),
            'puede_auto_enviar': False,
            'pedidos': parsed.get('pedidos') or [],
            'preguntas': parsed.get('preguntas') or [],
            'errores': parsed.get('errores') or [],
            'advertencias': parsed.get('advertencias') or [],
            'parser': parsed,
            'memoria_usada': memoria_previa,
            'memoria_actual': memoria_actual,
            'whatsapp_export': export_info,
            'v27': resultado,
        }))
    except Exception as exc:
        print('WARN v27 motor conversacional, se usa respaldo v26:', exc, flush=True)
        if _wa_v27_view_anterior:
            return _wa_v27_view_anterior()
        raise


app.view_functions['whatsapp_ia_simular'] = whatsapp_ia_simular_v27

# Silenciar /favicon.ico para que no ensucie logs con 500 cuando el navegador lo pida.
@app.route('/favicon.ico')
def favicon_v26():
    try:
        ruta = os.path.join(APP_DIR, 'icon-192.png')
        if os.path.exists(ruta):
            return send_file(ruta, mimetype='image/png')
    except Exception:
        pass
    return ('', 204)
