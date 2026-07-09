from datetime import datetime
import os

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE, require_local_mode
except Exception:
    HILORAMA_DATA_MODE = "local"
    def require_local_mode(area=""):
        if os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api":
            detalle = f" ({area})" if area else ""
            raise RuntimeError(f"Base local bloqueada en modo API cliente{detalle}.")

try:
    from hilorama_desktop.utils.logger import log_error
except Exception:
    def log_error(nombre_modulo, mensaje, exc=None):
        return None

STOCK_MINIMO = 50
MENSAJE_ACCION_ALMACEN_API = (
    "Esta acción de Almacén todavía no está disponible en modo API. "
    "Se migrará en una fase posterior."
)
_schema_ok = False
_productos_api_service = None


def get_conn():
    require_local_mode("core almacen")
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()


def ensure_almacen_schema():
    """Migración segura para que ventas/cotizaciones entiendan los items de cotización."""
    global _schema_ok
    if os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api":
        return
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


def _modo_datos():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower()


def _usar_api_lectura():
    return _modo_datos() == "api"


def _bloquear_escritura_local_api(accion):
    if _usar_api_lectura():
        raise RuntimeError(f"{MENSAJE_ACCION_ALMACEN_API} Acción: {accion}.")


def _api_productos():
    global _productos_api_service
    if _productos_api_service is None:
        from hilorama_desktop.services import productos_api_service
        _productos_api_service = productos_api_service
    return _productos_api_service


def _error_api_lectura(accion, exc):
    detalle = str(exc).strip()
    mensaje = detalle or f"No se pudo {accion} desde la API."
    log_error("almacen", mensaje, exc)
    raise RuntimeError(mensaje) from exc


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
    _bloquear_escritura_local_api("registrar movimiento de almacén")
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
    if _usar_api_lectura():
        try:
            productos = _api_productos().listar_todos_los_productos({
                "incluir_items_cotizacion": "true",
            })
            return [dict(p) for p in productos]
        except Exception as exc:
            _error_api_lectura("listar productos", exc)

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
    if _usar_api_lectura():
        try:
            return _api_productos().listar_marcas()
        except Exception as exc:
            _error_api_lectura("listar marcas", exc)

    ensure_almacen_schema()
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT marca FROM productos ORDER BY marca").fetchall()
    conn.close()
    return [r["marca"] for r in rows]


def obtener_hilos(marca):
    if _usar_api_lectura():
        try:
            return _api_productos().listar_hilos(marca)
        except Exception as exc:
            _error_api_lectura("listar hilos", exc)

    ensure_almacen_schema()
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT hilo FROM productos WHERE marca=%s ORDER BY hilo",
        (marca,)
    ).fetchall()
    conn.close()
    return [r["hilo"] for r in rows]


def obtener_productos(marca=None, hilo=None):
    if _usar_api_lectura():
        try:
            params = {"incluir_items_cotizacion": "true"}
            if marca:
                params["marca"] = marca
            if hilo:
                params["hilo"] = hilo
            productos = _api_productos().listar_todos_los_productos(params)
            return [_producto_para_venta(dict(p)) for p in productos]
        except Exception as exc:
            _error_api_lectura("obtener productos", exc)

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
    if _usar_api_lectura():
        try:
            if len(args) == 1:
                return _api_productos().obtener_producto_por_codigo(args[0])
            if len(args) >= 3:
                return _api_productos().obtener_producto_por_marca_hilo_codigo(
                    args[0], args[1], args[2]
                )
            return None
        except Exception as exc:
            _error_api_lectura("buscar producto", exc)

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
    if _usar_api_lectura():
        try:
            return _api_productos().obtener_precio_venta(marca=marca)
        except Exception as exc:
            _error_api_lectura("obtener precio de venta", exc)

    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("SELECT venta FROM precios WHERE marca=%s", (marca,)).fetchone()
    conn.close()
    return row["venta"] if row else 0


# ================= STOCK =================
def descontar_stock(marca, hilo, codigo, cantidad, *args, **kwargs):
    _bloquear_escritura_local_api("descontar stock local")
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
    _bloquear_escritura_local_api("aplicar venta local")
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
    if _usar_api_lectura():
        try:
            producto = _api_productos().obtener_producto_por_codigo(codigo)
            return _producto_para_venta(producto) if producto else None
        except Exception as exc:
            _error_api_lectura("obtener producto por codigo", exc)

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
    if _usar_api_lectura():
        try:
            return _api_productos().obtener_precio_distribuidor(marca=marca)
        except Exception as exc:
            _error_api_lectura("obtener precio distribuidor", exc)

    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("SELECT distribuidor FROM precios WHERE marca=%s", (marca,)).fetchone()
    conn.close()
    return row["distribuidor"] if row else 0


def obtener_producto_por_codigo_barras(codigo_barras):
    if _usar_api_lectura():
        try:
            producto = _api_productos().obtener_producto_por_codigo_barras(codigo_barras)
            return _producto_para_venta(producto) if producto else None
        except Exception as exc:
            _error_api_lectura("obtener producto por codigo de barras", exc)

    ensure_almacen_schema()
    conn = get_conn()
    row = conn.execute("SELECT * FROM productos WHERE codigo_barras=%s LIMIT 1", (codigo_barras,)).fetchone()
    conn.close()
    if not row:
        return None
    return _producto_para_venta(dict(row))
