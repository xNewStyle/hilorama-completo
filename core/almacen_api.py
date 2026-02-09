from database.connection import get_conn


STOCK_MINIMO = 50


# ================= CONSULTAS =================

def obtener_marcas():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT marca FROM productos ORDER BY marca"
    ).fetchall()
    conn.close()
    return [r["marca"] for r in rows]


def obtener_hilos(marca):
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT hilo FROM productos WHERE marca=? ORDER BY hilo",
        (marca,)
    ).fetchall()
    conn.close()
    return [r["hilo"] for r in rows]


def obtener_productos(marca=None, hilo=None):
    conn = get_conn()

    query = "SELECT * FROM productos WHERE 1=1"
    params = []

    if marca:
        query += " AND marca=?"
        params.append(marca)

    if hilo:
        query += " AND hilo=?"
        params.append(hilo)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def obtener_stock(codigo):
    conn = get_conn()
    row = conn.execute(
        "SELECT stock FROM productos WHERE codigo=?",
        (codigo,)
    ).fetchone()
    conn.close()
    return row["stock"] if row else 0


def es_stock_bajo(codigo):
    return obtener_stock(codigo) < STOCK_MINIMO


def obtener_precio_venta(marca):
    conn = get_conn()

    row = conn.execute(
        "SELECT venta FROM precios WHERE marca=?",
        (marca,)
    ).fetchone()

    conn.close()

    return row["venta"] if row else 0


# ================= STOCK =================

def descontar_stock(marca, hilo, codigo, cantidad):
    conn = get_conn()

    conn.execute(
        """
        UPDATE productos
        SET stock = stock - ?
        WHERE marca=? AND hilo=? AND codigo=?
        """,
        (cantidad, marca, hilo, codigo)
    )

    conn.commit()
    conn.close()
    return True


def aplicar_venta(items):
    conn = get_conn()

    for p in items:
        conn.execute(
            """
            UPDATE productos
            SET stock = stock - ?
            WHERE marca=? AND hilo=? AND codigo=?
            """,
            (p["cantidad"], p["marca"], p["hilo"], p["codigo"])
        )

    conn.commit()
    conn.close()


def obtener_producto_por_codigo(codigo):
    conn = get_conn()

    row = conn.execute(
        """
        SELECT * FROM productos
        WHERE codigo=? OR codigo_barras=?
        """,
        (codigo, codigo)
    ).fetchone()

    conn.close()

    if not row:
        return None

    producto = dict(row)

    if "volumetrico" not in producto or producto["volumetrico"] is None:
        producto["volumetrico"] = 1.0

    return producto


def obtener_precio_distribuidor(marca):
    conn = get_conn()

    row = conn.execute(
        "SELECT distribuidor FROM precios WHERE marca=?",
        (marca,)
    ).fetchone()

    conn.close()

    return row["distribuidor"] if row else 0
def obtener_producto_por_codigo_barras(codigo_barras):
    conn = get_conn()

    row = conn.execute(
        "SELECT * FROM productos WHERE codigo_barras=?",
        (codigo_barras,)
    ).fetchone()

    conn.close()

    if not row:
        return None

    producto = dict(row)

    if "volumetrico" not in producto or producto["volumetrico"] is None:
        producto["volumetrico"] = 1.0

    return producto
