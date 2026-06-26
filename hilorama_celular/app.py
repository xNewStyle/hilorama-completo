import json
import os
import re
import io
import base64
import tempfile
import math
import traceback
from PIL import Image, ImageDraw, ImageFont
import html
import unicodedata
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

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
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS paqueteria TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS empacador_id INTEGER")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS empacador TEXT")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_asignacion TIMESTAMP")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_finalizacion TIMESTAMP")

        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS marca TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS hilo TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS color TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS empacadas INTEGER DEFAULT 0")

        db.execute("CREATE INDEX IF NOT EXISTS idx_notas_estado_fecha ON notas(estado, fecha DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_items_nota_mobile ON items(nota_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_productos_busqueda_mobile ON productos(codigo, marca, hilo, color)")

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
                LOWER(COALESCE(n.cliente_nombre,'')) LIKE %s OR
                LOWER(COALESCE(n.pedido,'')) LIKE %s OR
                LOWER(COALESCE(c.telefono,'')) LIKE %s
            )
        """)
        like = f"%{q}%"
        params.extend([like, like, like, like])

    with DB() as db:
        rows = db.execute(f"""
            SELECT
                n.id, n.cliente_id, n.cliente_nombre, n.fecha, n.estado,
                n.total, n.envio, n.pedido, n.comprobante, n.fecha_pago,
                n.paqueteria, n.empacador_id, n.empacador, n.fecha_asignacion,
                c.telefono,
                COUNT(i.id) AS items_count,
                COALESCE(SUM(i.cantidad),0) AS piezas_total,
                COALESCE(SUM(i.empacadas),0) AS piezas_empacadas
            FROM notas n
            LEFT JOIN clientes c ON c.id=n.cliente_id
            LEFT JOIN items i ON i.nota_id=n.id
            WHERE {' AND '.join(where)}
            GROUP BY n.id, c.telefono
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
                WHERE (p2.codigo=i.codigo OR p2.codigo_barras=i.codigo)
                  AND (NULLIF(i.marca,'') IS NULL OR UPPER(p2.marca)=UPPER(i.marca))
                  AND (NULLIF(i.hilo,'') IS NULL OR UPPER(p2.hilo)=UPPER(i.hilo))
                ORDER BY
                    CASE
                        WHEN UPPER(COALESCE(p2.marca,''))=UPPER(COALESCE(i.marca,''))
                         AND UPPER(COALESCE(p2.hilo,''))=UPPER(COALESCE(i.hilo,'')) THEN 0
                        ELSE 1
                    END,
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
                COALESCE(pr.venta, p.precio, 0) AS precio_venta,
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
    data = request.get_json(force=True) or {}
    allowed = []
    params = []

    if "color" in data:
        allowed.append("color=%s")
        params.append((data.get("color") or "").strip())
    if "stock" in data:
        try:
            stock = int(data.get("stock"))
        except Exception:
            return jsonify({"ok": False, "error": "Stock inválido"}), 400
        allowed.append("stock=%s")
        params.append(stock)

    if not allowed:
        return jsonify({"ok": False, "error": "No hay cambios"}), 400

    params.append(codigo)
    with DB() as db:
        row = db.execute(f"""
            UPDATE productos
            SET {', '.join(allowed)}
            WHERE codigo=%s
            RETURNING id, codigo, marca, hilo, color, stock
        """, params).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Producto no encontrado"}), 404
    return jsonify(json_safe({"ok": True, "producto": dict(row)}))


@app.route("/api/productos/id/<int:producto_id>", methods=["PATCH"])
def actualizar_producto_por_id(producto_id):
    data = request.get_json(force=True) or {}
    allowed = []
    params = []

    if "color" in data:
        allowed.append("color=%s")
        params.append((data.get("color") or "").strip())
    if "stock" in data:
        try:
            stock = int(data.get("stock"))
        except Exception:
            return jsonify({"ok": False, "error": "Stock inválido"}), 400
        allowed.append("stock=%s")
        params.append(stock)

    if not allowed:
        return jsonify({"ok": False, "error": "No hay cambios"}), 400

    params.append(producto_id)
    with DB() as db:
        row = db.execute(f"""
            UPDATE productos
            SET {', '.join(allowed)}
            WHERE id=%s
            RETURNING id, codigo, marca, hilo, color, stock
        """, params).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Producto no encontrado"}), 404
    return jsonify(json_safe({"ok": True, "producto": dict(row)}))


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
               COALESCE(pr.venta, p.precio, i.precio, 0) AS precio_venta,
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
               COALESCE(pr.venta, p.precio, i.precio, 0) AS precio_venta,
               COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
               SUM(COALESCE(i.cantidad,0)) AS vendidas
        FROM items i
        LEFT JOIN notas n ON n.id = i.nota_id
        LEFT JOIN productos p ON p.codigo = i.codigo
        LEFT JOIN precios pr ON pr.marca = COALESCE(i.marca, p.marca)
        WHERE {' AND '.join(where)}
          AND COALESCE(n.estado,'') IN ('PAGADA','VENTA_PENDIENTE','EN_PROCESO')
        GROUP BY i.codigo, COALESCE(i.marca, p.marca), COALESCE(i.hilo, p.hilo), COALESCE(i.color, p.color), COALESCE(p.stock,0), COALESCE(pr.venta, p.precio, i.precio, 0), COALESCE(p.es_inventariable, TRUE)
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
                COALESCE(pr.venta, p.precio, 0) AS precio_venta
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

    resultado = extraer_pedidos(texto_total, productos)

    por_codigo = {}
    for p in productos:
        codigo_norm = str(p.get("codigo") or "").strip().lstrip("0") or "0"
        por_codigo.setdefault(codigo_norm, []).append(p)
        cb = str(p.get("codigo_barras") or "").strip().lstrip("0") or "0"
        if cb != "0":
            por_codigo.setdefault(cb, []).append(p)

    pedidos = []
    errores = []
    advertencias = []
    for ped in resultado.get("pedidos", []):
        codigo_norm = str(ped.get("codigo") or "").strip().lstrip("0") or "0"
        opciones = por_codigo.get(codigo_norm) or []
        if not opciones:
            errores.append(codigo_norm)
            continue
        if len(opciones) > 1 and not (marca or hilo):
            advertencias.append(f"El código {codigo_norm} existe en varias marcas/hilos. Usa contexto para evitar errores.")
        prod = opciones[0]
        pedidos.append({
            "producto_id": prod.get("id"),
            "codigo": prod.get("codigo"),
            "marca": prod.get("marca") or "",
            "hilo": prod.get("hilo") or "",
            "color": prod.get("color") or "",
            "stock": int(prod.get("stock") or 0),
            "precio_venta": float(prod.get("precio_venta") or 0),
            "cantidad": int(ped.get("cantidad") or 1),
            "es_inventariable": prod.get("es_inventariable"),
        })

    errores.extend(resultado.get("errores") or [])
    advertencias.extend(resultado.get("advertencias") or [])
    if referencia_visual:
        advertencias.append("Se detectó referencia visual; revisa posiciones, círculos, flechas o tachones antes de confirmar.")

    return jsonify(json_safe({
        "ok": True,
        "modo": resultado.get("modo"),
        "modo_especial": None,
        "contexto": {"marca": marca, "hilo": hilo, "productos_contexto": len(productos)},
        "pedidos": pedidos,
        "errores": sorted(set(str(e) for e in errores if e)),
        "advertencias": sorted(set(str(a) for a in advertencias if a)),
        "sugerencias": resultado.get("sugerencias") or {},
        "referencia_visual": referencia_visual,
    }))


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
    Normaliza y consolida productos por código + marca + hilo + color.
    Esto evita duplicados raros cuando un mismo código existe en varios hilos/marcas
    y conserva el contexto seleccionado en el celular.
    """
    agrupados = {}
    for raw in items_req:
        codigo = str(raw.get("codigo") or "").strip()
        marca = str(raw.get("marca") or "").strip()
        hilo = str(raw.get("hilo") or "").strip()
        color = str(raw.get("color") or "").strip()
        try:
            cantidad = int(float(raw.get("cantidad") or 0))
        except Exception:
            cantidad = 0
        if not codigo or cantidad <= 0:
            continue
        key = _item_key({"codigo": codigo, "marca": marca, "hilo": hilo, "color": color})
        if key not in agrupados:
            agrupados[key] = {
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
        codigo = str(raw.get("codigo") or "").strip()
        marca = str(raw.get("marca") or "").strip()
        hilo = str(raw.get("hilo") or "").strip()
        color = str(raw.get("color") or "").strip()
        cantidad = int(raw.get("cantidad") or 0)
        precio_manual = raw.get("precio")
        if not codigo or cantidad <= 0:
            continue

        prod = db.execute("""
            SELECT
                p.id, p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                COALESCE(p.stock,0) AS stock,
                COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
                COALESCE(p.tipo_producto, 'INVENTARIO') AS tipo_producto,
                COALESCE(pr.venta, p.precio, 0) AS precio_venta
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
                p.id
            LIMIT 1
        """, (codigo, codigo, marca, marca, hilo, hilo, color, color,
              marca, marca, hilo, hilo, marca, marca)).fetchone()

        if not prod:
            contexto = ""
            if marca or hilo:
                contexto = f" en contexto {marca or 'todas'} / {hilo or 'todos'}"
            errores.append(f"No existe el producto {codigo}{contexto}")
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
                INSERT INTO items (nota_id, codigo, marca, hilo, color, cantidad, precio)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (nota_id, p["codigo"], p["marca"], p["hilo"], p["color"], p["cantidad"], p["precio"]))

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
                INSERT INTO items (nota_id, codigo, marca, hilo, color, cantidad, precio)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (nota_id, p["codigo"], p["marca"], p["hilo"], p["color"], p["cantidad"], p["precio"]))

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
        nota = db.execute("SELECT id, estado FROM notas WHERE id=%s", (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
        if nota.get("estado") != "COTIZACION":
            return jsonify({"ok": False, "error": "Solo se puede convertir una COTIZACION"}), 400

        items = db.execute("""
            SELECT i.codigo, COALESCE(i.cantidad,0) AS cantidad, COALESCE(p.stock,0) AS stock,
                   COALESCE(p.es_inventariable, TRUE) AS es_inventariable
            FROM items i
            LEFT JOIN productos p ON p.codigo=i.codigo
            WHERE i.nota_id=%s
        """, (nota_id,)).fetchall()

        for it in items:
            es_inv = it.get("es_inventariable")
            if isinstance(es_inv, str):
                es_inv = es_inv.lower() not in ("false", "f", "0", "no", "n")
            if es_inv and int(it.get("stock") or 0) < int(it.get("cantidad") or 0):
                return jsonify({"ok": False, "error": f"Stock insuficiente {it['codigo']}"}), 400

        for it in items:
            es_inv = it.get("es_inventariable")
            if isinstance(es_inv, str):
                es_inv = es_inv.lower() not in ("false", "f", "0", "no", "n")
            if es_inv:
                db.execute("UPDATE productos SET stock=COALESCE(stock,0)-%s WHERE codigo=%s", (int(it["cantidad"] or 0), it["codigo"]))

        db.execute("UPDATE notas SET estado='VENTA_PENDIENTE' WHERE id=%s", (nota_id,))
    return jsonify({"ok": True, "nota_id": nota_id, "estado": "VENTA_PENDIENTE"})


@app.route("/api/notas/<nota_id>/pagar", methods=["POST"])
def marcar_pagada(nota_id):
    data = request.get_json(force=True) or {}
    comprobante = data.get("comprobante") or None
    with DB() as db:
        nota = db.execute("SELECT id, estado FROM notas WHERE id=%s", (nota_id,)).fetchone()
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404
        db.execute("""
            UPDATE notas
            SET estado='PAGADA', fecha_pago=%s, comprobante=COALESCE(%s, comprobante)
            WHERE id=%s
        """, (now_mexico().isoformat(sep=" ", timespec="seconds"), comprobante, nota_id))
    return jsonify({"ok": True, "nota_id": nota_id, "estado": "PAGADA"})


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
               COALESCE(pr.venta, p.precio, 0) AS precio_venta
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


def _analizar_seleccion_hilos_ia_pura(data_url, raw, original_data_url, comentario, contexto, productos_contexto):
    """
    Modo principal: interpretación pura de IA visual.
    No usa mapa manual. No permite inventar códigos a partir del catálogo.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'sin_openai_api_key'
    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))

    # Evita mandar fotos enormes; mantiene suficiente calidad para leer códigos.
    data_url = _optimizar_data_url_imagen(data_url, max_side=int(os.environ.get("OPENAI_IMAGE_MAX_SIDE", "900")))
    if original_data_url:
        original_data_url = _optimizar_data_url_imagen(original_data_url, max_side=int(os.environ.get("OPENAI_IMAGE_MAX_SIDE", "900")))

    catalogo = _productos_contexto_para_vision(productos_contexto, max_items=int(os.environ.get("OPENAI_CATALOG_MAX_ITEMS", "250")))
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
    return parsed, 'openai_pura_marcas'


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
        parsed, provider = _analizar_seleccion_hilos_ia_pura(data_url, raw, original_data_url, comentario, contexto, productos_contexto)
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
            # Caso típico: la IA interpreta un óvalo grande alrededor del código como X/tachón.
            # Solo se rescatan círculos MUY claros para no convertir X reales en productos.
            rescue_codes = _fallback_strong_circle_codes(fb_debug)
            rescued = []
            for c in rescue_codes:
                if c in exclude_codes and c not in add_codes:
                    add_codes.append(c)
                    quantities[c] = quantities.get(c, 1)
                    rescued.append(c)
            if rescued:
                exclude_codes = [c for c in exclude_codes if c not in set(rescued)]
                vision_notes.append('rescate_ovalos_grandes')
                advertencias.append('Rescaté como seleccionados estos códigos por óvalo grande claro: ' + ', '.join(rescued) + '. Revisa antes de guardar.')
    except Exception as e:
        vision_notes.append('fallback_marcas_rojas_error:' + str(e)[:160])

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
    if not data_url:
        return jsonify({'ok': False, 'error': 'No se recibió audio'}), 400
    try:
        raw = _extract_data_url_bytes(data_url)
    except Exception:
        return jsonify({'ok': False, 'error': 'No pude leer la imagen. Intenta subirla otra vez o usa una imagen más pequeña.'}), 400
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
                client = OpenAI(api_key=api_key, timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60")))
                with open(temp_path, 'rb') as f:
                    resp = client.audio.transcriptions.create(model=os.environ.get('OPENAI_TRANSCRIBE_MODEL', 'whisper-1'), file=f)
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
            WHERE p2.codigo = i.codigo
              AND (
                    COALESCE(NULLIF(i.marca,''),'') = ''
                    OR UPPER(COALESCE(p2.marca,'')) = UPPER(COALESCE(i.marca,''))
                  )
              AND (
                    COALESCE(NULLIF(i.hilo,''),'') = ''
                    OR UPPER(COALESCE(p2.hilo,'')) = UPPER(COALESCE(i.hilo,''))
                  )
              AND (
                    COALESCE(NULLIF(i.color,''),'') = ''
                    OR UPPER(COALESCE(p2.color,'')) = UPPER(COALESCE(i.color,''))
                  )
            ORDER BY
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
