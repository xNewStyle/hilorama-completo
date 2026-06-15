from datetime import datetime
from database.connection import get_conn

STOCK_MINIMO = 50
_schema_ok = False


def ensure_almacen_schema():
    """Migración segura para que ventas/cotizaciones entiendan los items de cotización."""
    global _schema_ok
    if _schema_ok:
        return
    conn = get_conn()
    try:
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS precio REAL DEFAULT 0
        """)
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS costo_neto REAL DEFAULT 0
        """)
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS es_inventariable BOOLEAN DEFAULT TRUE
        """)
        conn.execute("""
            ALTER TABLE productos
            ADD COLUMN IF NOT EXISTS tipo_producto TEXT DEFAULT 'INVENTARIO'
        """)
        conn.execute("""
            UPDATE productos
            SET es_inventariable=TRUE
            WHERE es_inventariable IS NULL
        """)
        conn.execute("""
            UPDATE productos
            SET tipo_producto='INVENTARIO'
            WHERE tipo_producto IS NULL OR tipo_producto=''
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_almacen (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT DEFAULT 'ADMIN',
                tipo TEXT NOT NULL,
                marca TEXT,
                hilo TEXT,
                color TEXT,
                codigo TEXT,
                stock_anterior INTEGER,
                stock_nuevo INTEGER,
                cantidad INTEGER DEFAULT 0,
                campo TEXT,
                valor_anterior TEXT,
                valor_nuevo TEXT,
                motivo TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mov_almacen_fecha
            ON movimientos_almacen(fecha DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mov_almacen_codigo
            ON movimientos_almacen(codigo)
        """)
        conn.commit()
        _schema_ok = True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _dict(row):
    if not row:
        return None
    try:
        return dict(row)
    except Exception:
        return row


def es_inventariable_producto(producto):
    if not producto:
        return True
    try:
        valor = producto.get("es_inventariable", True)
    except Exception:
        return True
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    if isinstance(valor, str):
        return valor.strip().lower() not in ("false", "f", "0", "no", "n", "item")
    return True


def _producto_para_venta(producto):
    """
    Los items de cotización deben aparecer en ventas/cotizaciones, pero sin bloquear por stock.
    Por eso se conserva stock_real y se manda stock alto solo para evitar la alerta visual.
    """
    if not producto:
        return producto
    producto = dict(producto)
    if "volumetrico" not in producto or producto.get("volumetrico") is None:
        producto["volumetrico"] = 1.0
    if not es_inventariable_producto(producto):
        producto["stock_real"] = producto.get("stock", 0)
        producto["stock"] = 999999
        producto["estado"] = "ITEM"
        producto["es_item_cotizacion"] = True
    else:
        producto["stock_real"] = producto.get("stock", 0)
        producto["es_item_cotizacion"] = False
    return producto


def registrar_movimiento(
    tipo,
    marca=None,
    hilo=None,
    color=None,
    codigo=None,
    stock_anterior=None,
    stock_nuevo=None,
    cantidad=0,
    campo=None,
    valor_anterior=None,
    valor_nuevo=None,
    motivo="",
    conn=None
):
    cerrar = False
    try:
        if conn is None:
            ensure_almacen_schema()
            conn = get_conn()
            cerrar = True
        conn.execute("""
            INSERT INTO movimientos_almacen
            (fecha, usuario, tipo, marca, hilo, color, codigo,
             stock_anterior, stock_nuevo, cantidad, campo,
             valor_anterior, valor_nuevo, motivo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            datetime.now(),
            "VENTAS",
            tipo,
            marca,
            hilo,
            color,
            codigo,
            stock_anterior,
            stock_nuevo,
            cantidad,
            campo,
            None if valor_anterior is None else str(valor_anterior),
            None if valor_nuevo is None else str(valor_nuevo),
            motivo,
        ))
        if cerrar:
            conn.commit()
    except Exception:
        # No debe romper una venta por no poder escribir historial.
        if cerrar and conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if cerrar and conn:
            conn.close()


# ================= CONSULTAS =================
def obtener_todos_los_productos():
    ensure_almacen_schema()
    conn = get_conn()
    productos = conn.execute("""
        SELECT codigo, marca, hilo, color, es_inventariable, tipo_producto
        FROM productos
        ORDER BY marca, hilo, color, codigo
    """).fetchall()
    conn.close()
    return [dict(p) for p in productos]


def obtener_marcas():
    ensure_almacen_schema()
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT marca FROM productos ORDER BY marca").fetchall()
    conn.close()
    return [r["marca"] for r in rows]


def obtener_hilos(marca):
    ensure_almacen_schema()
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT hilo FROM productos WHERE marca=%s ORDER BY hilo",
        (marca,)
    ).fetchall()
    conn.close()
    return [r["hilo"] for r in rows]


def obtener_productos(marca=None, hilo=None):
    ensure_almacen_schema()
    conn = get_conn()
    query = "SELECT * FROM productos WHERE 1=1"
    params = []
    if marca:
        query += " AND marca=%s"
        params.append(marca)
    if hilo:
        query += " AND hilo=%s"
        params.append(hilo)
    query += " ORDER BY marca, hilo, color, codigo"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_producto_para_venta(dict(r)) for r in rows]


def _buscar_producto_por_args(args):
    ensure_almacen_schema()
    conn = get_conn()
    try:
        if len(args) == 1:
            codigo = args[0]
            row = conn.execute(
                "SELECT * FROM productos WHERE codigo=%s OR codigo_barras=%s LIMIT 1",
                (codigo, codigo)
            ).fetchone()
        elif len(args) >= 3:
            marca, hilo, codigo = args[0], args[1], args[2]
            row = conn.execute(
                "SELECT * FROM productos WHERE marca=%s AND hilo=%s AND codigo=%s LIMIT 1",
                (marca, hilo, codigo)
            ).fetchone()
        else:
            row = None
    finally:
        conn.close()
    return _dict(row)


def obtener_stock(*args):
    producto = _buscar_producto_por_args(args)
    if not producto:
        return 0
    if not es_inventariable_producto(producto):
        return 999999
    return producto.get("stock", 0) or 0


def es_stock_bajo(*args):
    producto = _buscar_producto_por_args(args)
    if not producto:
        return False
    if not es_inventariable_producto(producto):
        return False
    return (producto.get("stock", 0) or 0) < STOCK_MINIMO


def obtener_precio_venta(marca):
    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("SELECT venta FROM precios WHERE marca=%s", (marca,)).fetchone()
    conn.close()
    return row["venta"] if row else 0


# ================= STOCK =================
def descontar_stock(marca, hilo, codigo, cantidad, *args, **kwargs):
    ensure_almacen_schema()
    conn = get_conn()
    try:
        anterior = conn.execute("""
            SELECT * FROM productos
            WHERE marca=%s AND hilo=%s AND codigo=%s
            LIMIT 1
        """, (marca, hilo, codigo)).fetchone()
        anterior = _dict(anterior)

        if anterior and not es_inventariable_producto(anterior):
            registrar_movimiento(
                "SALIDA_ITEM_COTIZACION",
                marca=marca,
                hilo=hilo,
                color=anterior.get("color"),
                codigo=codigo,
                stock_anterior=0,
                stock_nuevo=0,
                cantidad=-(int(cantidad)),
                campo="stock",
                valor_anterior="NO APLICA",
                valor_nuevo="NO APLICA",
                motivo="Venta/cotización de item de cotización; no descuenta almacén físico",
                conn=conn,
            )
            conn.commit()
            return True

        stock_anterior = int(anterior.get("stock") or 0) if anterior else None
        conn.execute("""
            UPDATE productos
            SET stock = stock - %s
            WHERE marca=%s AND hilo=%s AND codigo=%s
        """, (cantidad, marca, hilo, codigo))

        stock_nuevo = stock_anterior - int(cantidad) if stock_anterior is not None else None
        if stock_nuevo is not None:
            nuevo_estado = "OK" if stock_nuevo >= STOCK_MINIMO else "RESURTIR"
            conn.execute("""
                UPDATE productos
                SET estado=%s
                WHERE marca=%s AND hilo=%s AND codigo=%s
            """, (nuevo_estado, marca, hilo, codigo))

        registrar_movimiento(
            "SALIDA_STOCK",
            marca=marca,
            hilo=hilo,
            color=anterior.get("color") if anterior else None,
            codigo=codigo,
            stock_anterior=stock_anterior,
            stock_nuevo=stock_nuevo,
            cantidad=-(int(cantidad)),
            campo="stock",
            valor_anterior=stock_anterior,
            valor_nuevo=stock_nuevo,
            motivo="Descuento por venta/cotización",
            conn=conn,
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def aplicar_venta(items):
    ensure_almacen_schema()
    for p in items:
        descontar_stock(
            p.get("marca"),
            p.get("hilo"),
            p.get("codigo"),
            p.get("cantidad", 0)
        )
    return True


def obtener_producto_por_codigo(codigo):
    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM productos
        WHERE codigo=%s OR codigo_barras=%s
        LIMIT 1
    """, (codigo, codigo)).fetchone()
    conn.close()
    if not row:
        return None
    return _producto_para_venta(dict(row))


def obtener_precio_distribuidor(marca):
    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("SELECT distribuidor FROM precios WHERE marca=%s", (marca,)).fetchone()
    conn.close()
    return row["distribuidor"] if row else 0


def obtener_producto_por_codigo_barras(codigo_barras):
    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("SELECT * FROM productos WHERE codigo_barras=%s LIMIT 1", (codigo_barras,)).fetchone()
    conn.close()
    if not row:
        return None
    return _producto_para_venta(dict(row))
