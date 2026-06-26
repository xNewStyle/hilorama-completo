import json
import os
import re
import io
import base64
import tempfile
import html
import unicodedata
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

APP_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

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
    got = request.headers.get("X-Mobile-Pin", "").strip()
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


def _image_reference_summary(texto):
    t = _strip_acc(texto)
    out = {'numbers': [], 'positions': [], 'marks': []}
    out['numbers'] = [int(x) for x in re.findall(r'(\d{1,3})', t)]
    mapping = [
        ('arriba_derecha', r'arriba\s+(?:a\s+la\s+)?derecha'),
        ('arriba_izquierda', r'arriba\s+(?:a\s+la\s+)?izquierda'),
        ('abajo_derecha', r'abajo\s+(?:a\s+la\s+)?derecha'),
        ('abajo_izquierda', r'abajo\s+(?:a\s+la\s+)?izquierda'),
        ('arriba', r'arriba'), ('abajo', r'abajo'), ('derecha', r'derecha'),
        ('izquierda', r'izquierda'), ('medio', r'en medio|del medio|centro'), ('primero', r'primero'),
        ('segundo', r'segundo'), ('tercero', r'tercero'), ('ultimo', r'ultimo|ultima'),
    ]
    for name, pat in mapping:
        if re.search(pat, t):
            out['positions'].append(name)
    if 'circulo' in t or 'encerrado' in t or 'rodeado' in t:
        out['marks'].append('circulo')
    if 'flecha' in t or 'senalado' in t or 'señalado' in t:
        out['marks'].append('flecha')
    if 'tachado' in t or 'tachon' in t or 'tacha' in t:
        out['marks'].append('tachado')
    out['numbers'] = list(dict.fromkeys(out['numbers']))
    out['positions'] = list(dict.fromkeys(out['positions']))
    out['marks'] = list(dict.fromkeys(out['marks']))
    return out


@app.route('/api/analizar-imagen-referencia', methods=['POST'])
def analizar_imagen_referencia():
    data = request.get_json(force=True) or {}
    data_url = data.get('image_base64') or ''
    comentario = (data.get('comentario') or '').strip()
    if not data_url:
        return jsonify({'ok': False, 'error': 'No se recibió imagen'}), 400
    raw = _extract_data_url_bytes(data_url)
    ocr_text = ''
    vision_notes = []
    circles = 0
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        try:
            import pytesseract
            ocr_text = (pytesseract.image_to_string(img, lang='spa+eng') or '').strip()
            if ocr_text:
                vision_notes.append('ocr')
        except Exception:
            pass
        try:
            import cv2
            import numpy as np
            arr = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
            gray = cv2.medianBlur(gray, 5)
            found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1.2, 35, param1=80, param2=24, minRadius=10, maxRadius=140)
            if found is not None:
                circles = int(found.shape[1])
                vision_notes.append(f'circulos:{circles}')
        except Exception:
            pass
    except Exception:
        pass

    joined = ' '.join(x for x in [comentario, ocr_text] if x).strip()
    resumen = _image_reference_summary(joined)
    if circles and 'circulo' not in resumen['marks']:
        resumen['marks'].append('circulo')
    suggested = []
    if resumen['numbers']:
        suggested.append('numero ' + ' '.join(str(n) for n in resumen['numbers']))
    if resumen['positions']:
        suggested.append('posicion ' + ' '.join(resumen['positions']))
    if resumen['marks']:
        suggested.append('marca ' + ' '.join(resumen['marks']))
    suggested_text = ('referencia visual ' + ' '.join(suggested)).strip() if suggested else comentario
    return jsonify(json_safe({
        'ok': True,
        'ocr_text': ocr_text,
        'summary': resumen,
        'vision_notes': vision_notes,
        'suggested_text': suggested_text,
    }))


@app.route('/api/transcribir-audio', methods=['POST'])
def transcribir_audio():
    data = request.get_json(force=True) or {}
    data_url = data.get('audio_base64') or ''
    filename = (data.get('filename') or 'audio.ogg').strip()
    if not data_url:
        return jsonify({'ok': False, 'error': 'No se recibió audio'}), 400
    raw = _extract_data_url_bytes(data_url)
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
                client = OpenAI(api_key=api_key)
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


def _nota_full(db, nota_id):
    nota = db.execute("""
        SELECT n.*, c.nombre AS cliente_nombre_real, c.telefono, c.direccion
        FROM notas n
        LEFT JOIN clientes c ON c.id = n.cliente_id
        WHERE n.id=%s
    """, (nota_id,)).fetchone()
    if not nota:
        return None, []
    items = db.execute("""
        SELECT i.*, COALESCE(i.precio,0) AS precio_unit,
               COALESCE(i.marca, p.marca) AS marca_final,
               COALESCE(i.hilo, p.hilo) AS hilo_final,
               COALESCE(i.color, p.color) AS color_final
        FROM items i
        LEFT JOIN productos p ON p.codigo = i.codigo
        WHERE i.nota_id=%s
        ORDER BY i.id
    """, (nota_id,)).fetchall()
    return dict(nota), [dict(x) for x in items]


@app.route('/nota-pdf/<nota_id>')
def nota_pdf_html(nota_id):
    with DB() as db:
        nota, items = _nota_full(db, nota_id)
    if not nota:
        return 'Nota no encontrada', 404
    total = float(nota.get('total') or 0)
    envio_txt = ''
    try:
        envio = nota.get('envio')
        if isinstance(envio, str) and envio.strip():
            envio = json.loads(envio)
        if isinstance(envio, dict):
            envio_txt = f"{envio.get('paqueteria','')} {envio.get('precio','')}"
    except Exception:
        envio_txt = ''
    rows = ''.join(
        f"<tr><td>{html.escape(str(i.get('codigo') or ''))}</td><td>{html.escape(str(i.get('color_final') or i.get('color') or ''))}</td><td>{html.escape(str(i.get('marca_final') or i.get('marca') or ''))}</td><td>{html.escape(str(i.get('hilo_final') or i.get('hilo') or ''))}</td><td>{int(i.get('cantidad') or 0)}</td><td>${float(i.get('precio_unit') or i.get('precio') or 0):,.2f}</td><td>${(float(i.get('precio_unit') or i.get('precio') or 0)*float(i.get('cantidad') or 0)):,.2f}</td></tr>"
        for i in items
    )
    html_doc = f"""
<!doctype html><html lang='es'><head><meta charset='utf-8'><title>{html.escape(nota_id)}</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
body{{font-family:Arial,sans-serif;background:#f3f4f7;margin:0;padding:0}} .page{{max-width:980px;margin:18px auto;background:#fff;box-shadow:0 10px 40px rgba(0,0,0,.08);position:relative;overflow:hidden;border-radius:16px}}
.header{{background:url('/assets/fondo_premium.png') center/cover no-repeat;padding:24px 28px;color:#fff;position:relative}}
.header::after{{content:'';position:absolute;inset:0;background:rgba(50,26,73,.55)}} .header-inner{{position:relative;z-index:2;display:flex;justify-content:space-between;gap:18px;align-items:center}}
.logo{{height:72px;object-fit:contain}} .watermark{{position:absolute;right:20px;bottom:12px;height:74px;opacity:.14;z-index:1}}
.section{{padding:20px 28px}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .card{{background:#faf8ff;border:1px solid #ece6f7;border-radius:14px;padding:14px}}
table{{width:100%;border-collapse:collapse;margin-top:14px}} th,td{{padding:10px;border-bottom:1px solid #ececec;font-size:14px;text-align:left}} th{{background:#f7f1ff;color:#5a2d82}} .tot{{text-align:right;font-size:22px;font-weight:bold;color:#5a2d82;margin-top:18px}} .printbar{{padding:14px 28px;display:flex;justify-content:flex-end;gap:10px}} .btn{{padding:10px 16px;border:none;border-radius:10px;background:#5a2d82;color:white;font-weight:700;cursor:pointer}} @media print{{body{{background:white}} .page{{box-shadow:none;margin:0;max-width:none;border-radius:0}} .printbar{{display:none}} }}
</style></head><body>
<div class='page'>
<div class='printbar'><button class='btn' onclick='window.print()'>Imprimir / Guardar PDF</button></div>
<div class='header'><div class='header-inner'><div><img class='logo' src='/assets/logo_hilorama.png' alt='Hilorama'><div style='margin-top:8px;font-size:13px;opacity:.95'>Cotización / Nota estilo móvil similar PC</div></div><div style='text-align:right'><div style='font-size:30px;font-weight:800'>{html.escape(nota_id)}</div><div>{html.escape(str(nota.get('estado') or ''))}</div><div>{html.escape(str(nota.get('fecha') or ''))}</div></div></div><img class='watermark' src='/assets/marca_agua.png' alt='marca'></div>
<div class='section'><div class='grid'><div class='card'><strong>Cliente</strong><br>{html.escape(str(nota.get('cliente_nombre') or nota.get('cliente_nombre_real') or ''))}<br>Tel: {html.escape(str(nota.get('telefono') or ''))}<br>Dirección: {html.escape(str(nota.get('direccion') or ''))}</div><div class='card'><strong>Pedido / envío</strong><br>Pedido: {html.escape(str(nota.get('pedido') or '-'))}<br>Envío: {html.escape(envio_txt or '-')}<br>Empacador: {html.escape(str(nota.get('empacador') or ''))}</div></div>
<h3 style='margin:22px 0 8px;color:#5a2d82'>Productos</h3>
<table><thead><tr><th>Código</th><th>Color</th><th>Marca</th><th>Hilo</th><th>Cant.</th><th>P. Unit</th><th>Subtotal</th></tr></thead><tbody>{rows}</tbody></table>
<div class='tot'>Total: ${total:,.2f}</div></div></div></body></html>"""
    return html_doc


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
