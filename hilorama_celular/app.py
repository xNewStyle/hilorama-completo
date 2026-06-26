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

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

_pool = None
_schema_ready = False

MEXICO_TZ = ZoneInfo("America/Mexico_City")


def now_mexico():
    return datetime.now(MEXICO_TZ).replace(tzinfo=None)


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
        # IMPORTANTE:
        # Si params viene en None, no mandamos () a psycopg2.
        # Esto evita errores cuando el SQL trae símbolos % literales,
        # por ejemplo: WHERE id LIKE 'COT-%'
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
    if n.get("estado") == "PAGADA" and n.get("fecha_pago"):
        f = n.get("fecha_pago")
    else:
        f = n.get("fecha")
    return (fecha_orden(f), str(n.get("id") or ""))


def require_pin():
    # Para prueba puede quedar vacío. Para uso real, configura MOBILE_PIN en Render.
    expected = os.environ.get("MOBILE_PIN", "").strip()
    if not expected:
        return None

    got = request.headers.get("X-Mobile-Pin", "").strip()
    if got != expected:
        return jsonify({"ok": False, "error": "PIN incorrecto"}), 401
    return None


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

        # Columnas que ya usa tu programa de PC en versiones nuevas.
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
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_asignacion TIMESTAMP")
        db.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_finalizacion TIMESTAMP")

        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS marca TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS hilo TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS color TEXT")
        db.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS empacadas INTEGER DEFAULT 0")

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_notas_estado_fecha
            ON notas(estado, fecha DESC)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_items_nota_mobile
            ON items(nota_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_productos_busqueda_mobile
            ON productos(codigo, marca, hilo, color)
        """)

    _schema_ready = True


@app.before_request
def before_request():
    if request.path.startswith("/api/"):
        ensure_schema()
        err = require_pin()
        if err:
            return err


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


@app.route("/api/health")
def health():
    ensure_schema()
    return jsonify({
        "ok": True,
        "service": "Hilorama Celular API",
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


@app.route("/api/notas")
def listar_notas():
    estado = (request.args.get("estado") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()
    limit = min(int(request.args.get("limit") or 100), 300)

    params = []
    where = ["1=1"]

    if estado and estado != "TODOS":
        where.append("estado=%s")
        params.append(estado)

    if q:
        where.append("(LOWER(id) LIKE %s OR LOWER(COALESCE(cliente_nombre,'')) LIKE %s OR LOWER(COALESCE(pedido,'')) LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sql = f"""
        SELECT id, cliente_id, cliente_nombre, fecha, estado, total, envio,
               pedido, comprobante, fecha_pago, paqueteria, empacador_id
        FROM notas
        WHERE {' AND '.join(where)}
    """

    with DB() as db:
        rows = db.execute(sql, params).fetchall()
        notas = [dict(r) for r in rows]

        ids = [n["id"] for n in notas]
        counts = {}
        if ids:
            marks = ",".join(["%s"] * len(ids))
            item_rows = db.execute(
                f"SELECT nota_id, COUNT(*) AS c FROM items WHERE nota_id IN ({marks}) GROUP BY nota_id",
                ids,
            ).fetchall()
            counts = {r["nota_id"]: int(r["c"]) for r in item_rows}

    notas.sort(key=nota_sort_key, reverse=True)
    notas = notas[:limit]

    for n in notas:
        n["items_count"] = counts.get(n["id"], 0)
        n["envio"] = parse_json_text(n.get("envio"), {})
        n["total"] = float(n.get("total") or 0)

    return jsonify(json_safe(notas))


@app.route("/api/notas/<nota_id>")
def obtener_nota(nota_id):
    with DB() as db:
        nota = db.execute("""
            SELECT * FROM notas WHERE id=%s
        """, (nota_id,)).fetchone()

        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada"}), 404

        items = db.execute("""
            SELECT id, codigo, marca, hilo, color, cantidad, empacadas, precio
            FROM items
            WHERE nota_id=%s
            ORDER BY id
        """, (nota_id,)).fetchall()

    n = dict(nota)
    n["envio"] = parse_json_text(n.get("envio"), {})
    n["items"] = [dict(i) for i in items]
    return jsonify(json_safe(n))


@app.route("/api/clientes")
def buscar_clientes():
    q = (request.args.get("q") or "").strip().lower()
    limit = min(int(request.args.get("limit") or 25), 100)

    params = []
    where = "1=1"
    if q:
        where = "(LOWER(COALESCE(nombre,'')) LIKE %s OR COALESCE(telefono,'') LIKE %s)"
        params = [f"%{q}%", f"%{q}%"]

    with DB() as db:
        rows = db.execute(f"""
            SELECT id, nombre, telefono, direccion
            FROM clientes
            WHERE {where}
            ORDER BY nombre
            LIMIT {limit}
        """, params).fetchall()

    clientes = []
    for r in rows:
        c = dict(r)
        c["direccion"] = parse_json_text(c.get("direccion"), {})
        clientes.append(c)

    return jsonify(json_safe(clientes))


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
    limit = min(int(request.args.get("limit") or 60), 200)

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
                COALESCE(pr.venta, p.precio, 0) AS precio_venta
            FROM productos p
            LEFT JOIN precios pr ON pr.marca = p.marca
            WHERE {' AND '.join(where)}
            ORDER BY p.marca, p.hilo, p.color, p.codigo
            LIMIT {limit}
        """, params).fetchall()

    return jsonify(json_safe([dict(r) for r in rows]))


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
        # Cliente existente o nuevo.
        if cliente_id:
            cliente = db.execute(
                "SELECT id, nombre, telefono, direccion FROM clientes WHERE id=%s",
                (cliente_id,),
            ).fetchone()
            if not cliente:
                return jsonify({"ok": False, "error": "Cliente no encontrado"}), 404
            cliente = dict(cliente)
        else:
            if not cliente_nombre:
                return jsonify({"ok": False, "error": "Falta cliente"}), 400

            direccion_vacia = {
                "calle": "",
                "numero_ext": "",
                "numero_int": "",
                "colonia": "",
                "codigo_postal": "",
                "estado": "",
                "municipio": "",
                "referencia": "",
            }
            cliente = db.execute("""
                INSERT INTO clientes (nombre, telefono, direccion)
                VALUES (%s,%s,%s)
                RETURNING id, nombre, telefono, direccion
            """, (cliente_nombre, telefono, json.dumps(direccion_vacia, ensure_ascii=False))).fetchone()
            cliente = dict(cliente)

        items_finales = []
        errores = []
        total = 0.0

        for raw in items_req:
            codigo = str(raw.get("codigo") or "").strip()
            cantidad = int(raw.get("cantidad") or 0)
            if not codigo or cantidad <= 0:
                continue

            prod = db.execute("""
                SELECT
                    p.codigo, p.codigo_barras, p.marca, p.hilo, p.color,
                    COALESCE(p.stock,0) AS stock,
                    COALESCE(p.es_inventariable, TRUE) AS es_inventariable,
                    COALESCE(p.tipo_producto, 'INVENTARIO') AS tipo_producto,
                    COALESCE(pr.venta, p.precio, 0) AS precio_venta
                FROM productos p
                LEFT JOIN precios pr ON pr.marca = p.marca
                WHERE p.codigo=%s OR p.codigo_barras=%s
                LIMIT 1
            """, (codigo, codigo)).fetchone()

            if not prod:
                errores.append(f"No existe el producto {codigo}")
                continue

            prod = dict(prod)
            es_inventariable = prod.get("es_inventariable")
            if isinstance(es_inventariable, str):
                es_inventariable = es_inventariable.lower() not in ("false", "f", "0", "no", "n")

            stock = int(prod.get("stock") or 0)
            if es_inventariable and stock < cantidad:
                errores.append(f"Stock insuficiente {prod['codigo']} ({stock} disponibles)")
                continue

            precio = float(prod.get("precio_venta") or 0)
            subtotal = cantidad * precio
            total += subtotal

            items_finales.append({
                "codigo": prod["codigo"],
                "marca": prod.get("marca") or "",
                "hilo": prod.get("hilo") or "",
                "color": prod.get("color") or "",
                "cantidad": cantidad,
                "precio": precio,
                "subtotal": subtotal,
            })

        if errores:
            return jsonify({"ok": False, "error": " / ".join(errores)}), 400

        if not items_finales:
            return jsonify({"ok": False, "error": "No hay productos válidos"}), 400

        envio_precio = 0.0
        paqueteria = None
        if isinstance(envio, dict):
            envio_precio = float(envio.get("precio") or 0)
            paqueteria = envio.get("tipo") or envio.get("paqueteria")

        total = round(total + envio_precio, 2)
        nota_id = generar_id_nota(db)

        db.execute("""
            INSERT INTO notas
            (id, cliente_id, cliente_nombre, fecha, estado, total, envio, pedido, paqueteria)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            nota_id,
            cliente["id"],
            cliente["nombre"],
            now_mexico(),
            "COTIZACION",
            total,
            json.dumps(envio, ensure_ascii=False) if envio else None,
            pedido,
            paqueteria,
        ))

        for p in items_finales:
            db.execute("""
                INSERT INTO items
                (nota_id, codigo, marca, hilo, color, cantidad, precio)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                nota_id,
                p["codigo"],
                p["marca"],
                p["hilo"],
                p["color"],
                p["cantidad"],
                p["precio"],
            ))

    return jsonify(json_safe({
        "ok": True,
        "nota_id": nota_id,
        "total": total,
        "items": items_finales,
        "cliente": {"id": cliente["id"], "nombre": cliente["nombre"]},
    }))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
