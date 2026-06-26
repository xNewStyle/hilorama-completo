import json
import os
import re
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


@app.route("/api/parser-whatsapp", methods=["POST"])
def parser_whatsapp_mobile():
    """
    Interpreta texto libre tipo WhatsApp usando la misma lógica del programa de PC.
    Recibe contexto opcional de marca/hilo para que los números se interpreten dentro
    del hilo correcto, igual que el combo de contexto en la PC.
    """
    from parser_whatsapp import extraer_pedidos

    data = request.get_json(force=True) or {}
    texto = data.get("texto") or ""
    marca = (data.get("marca") or "").strip()
    hilo = (data.get("hilo") or "").strip()

    if not texto.strip():
        return jsonify({"ok": False, "error": "Pega o escribe un pedido primero"}), 400

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
                p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
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
    resultado = extraer_pedidos(texto, productos)

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

    return jsonify(json_safe({
        "ok": True,
        "modo": resultado.get("modo"),
        "contexto": {"marca": marca, "hilo": hilo, "productos_contexto": len(productos)},
        "pedidos": pedidos,
        "errores": sorted(set(str(e) for e in errores if e)),
        "advertencias": sorted(set(str(a) for a in advertencias if a)),
        "sugerencias": resultado.get("sugerencias") or {},
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
