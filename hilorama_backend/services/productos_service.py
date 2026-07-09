from decimal import Decimal

from database.connection import get_conn


PRODUCTOS_COLUMNAS_BASE = (
    "id",
    "codigo",
    "marca",
    "hilo",
    "color",
    "stock",
    "estado",
)

PRODUCTOS_COLUMNAS_OPCIONALES = (
    "codigo_barras",
    "volumetrico",
    "precio",
    "costo_neto",
    "es_inventariable",
    "tipo_producto",
)

TIPOS_NO_INVENTARIO_FISICO = (
    "ITEM",
    "ITEM_COTIZACION",
    "ANULADO",
    "INACTIVO",
    "COTIZACION",
    "PAQUETE",
    "PAQUETES",
    "COMBO",
    "COMBOS",
    "SERVICIO",
)


def listar_productos(params):
    limit = _limite(params.get("limit"))
    offset = _offset(params.get("offset"))

    with get_conn() as conn:
        columnas = _columnas_productos(conn)
        tiene_precios = _tabla_existe(conn, "precios")
        select = _select_producto(columnas, tiene_precios)
        joins = _joins_producto(tiene_precios)
        where, valores = _where_productos(params, columnas)

        total = conn.execute(
            f"SELECT COUNT(*) AS total FROM productos p {joins} {where}",
            valores,
        ).fetchone()["total"]

        rows = conn.execute(
            f"""
            SELECT {select}
            FROM productos p
            {joins}
            {where}
            ORDER BY p.marca, p.hilo, p.color, p.codigo
            LIMIT %s OFFSET %s
            """,
            tuple(valores) + (limit, offset),
        ).fetchall()

    return {
        "productos": [_normalizar_producto(row) for row in rows],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


def obtener_producto_por_id(producto_id):
    with get_conn() as conn:
        columnas = _columnas_productos(conn)
        tiene_precios = _tabla_existe(conn, "precios")
        select = _select_producto(columnas, tiene_precios)
        joins = _joins_producto(tiene_precios)
        row = conn.execute(
            f"""
            SELECT {select}
            FROM productos p
            {joins}
            WHERE p.id=%s
            LIMIT 1
            """,
            (producto_id,),
        ).fetchone()
    return _normalizar_producto(row) if row else None


def obtener_producto_por_codigo(codigo):
    with get_conn() as conn:
        columnas = _columnas_productos(conn)
        tiene_precios = _tabla_existe(conn, "precios")
        select = _select_producto(columnas, tiene_precios)
        joins = _joins_producto(tiene_precios)
        condiciones = ["p.codigo=%s"]
        valores = [codigo]
        if "codigo_barras" in columnas:
            condiciones.append("p.codigo_barras=%s")
            valores.append(codigo)

        row = conn.execute(
            f"""
            SELECT {select}
            FROM productos p
            {joins}
            WHERE {" OR ".join(condiciones)}
            LIMIT 1
            """,
            tuple(valores),
        ).fetchone()
    return _normalizar_producto(row) if row else None


def listar_marcas():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT marca
            FROM productos
            WHERE marca IS NOT NULL AND marca <> ''
            ORDER BY marca
        """).fetchall()
    return [row["marca"] for row in rows]


def listar_hilos(marca=None):
    valores = []
    where = "WHERE hilo IS NOT NULL AND hilo <> ''"
    if marca:
        where += " AND UPPER(marca)=UPPER(%s)"
        valores.append(marca)

    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT DISTINCT hilo
            FROM productos
            {where}
            ORDER BY hilo
        """, tuple(valores)).fetchall()
    return [row["hilo"] for row in rows]


def resumen_almacen():
    with get_conn() as conn:
        columnas = _columnas_productos(conn)
        tiene_precios = _tabla_existe(conn, "precios")
        joins = _joins_producto(tiene_precios)
        costo = _expr_costo(columnas, tiene_precios)
        venta = _expr_precio_venta(columnas, tiene_precios)
        filtro_inventario = _filtro_inventario(columnas)
        stock_real = "GREATEST(COALESCE(p.stock, 0), 0)"

        rows = conn.execute(f"""
            SELECT
                p.marca,
                p.hilo,
                SUM({stock_real}) AS piezas,
                SUM({stock_real} * {costo}) AS valor_costo,
                SUM({stock_real} * {venta}) AS valor_venta,
                SUM({stock_real} * ({venta} - {costo})) AS ganancia_estimada
            FROM productos p
            {joins}
            WHERE {filtro_inventario}
              AND COALESCE(p.stock, 0) > 0
            GROUP BY p.marca, p.hilo
            ORDER BY p.marca, p.hilo
        """).fetchall()

    grupos = [_normalizar_resumen(row) for row in rows]
    total_general = {
        "piezas": sum(item["piezas"] for item in grupos),
        "valor_costo": round(sum(item["valor_costo"] for item in grupos), 2),
        "valor_venta": round(sum(item["valor_venta"] for item in grupos), 2),
        "ganancia_estimada": round(sum(item["ganancia_estimada"] for item in grupos), 2),
    }
    return {
        "grupos": grupos,
        "total_general": total_general,
    }


def listar_precios(params):
    marca = _texto(params.get("marca"))
    hilo = _texto(params.get("hilo"))

    with get_conn() as conn:
        if not _tabla_existe(conn, "precios"):
            return []

        columnas = _columnas_tabla(conn, "precios")
        select = _select_precio(columnas)
        filtros = []
        valores = []
        if marca and "marca" in columnas:
            filtros.append("UPPER(marca)=UPPER(%s)")
            valores.append(marca)
        if hilo and "hilo" in columnas:
            filtros.append("UPPER(hilo)=UPPER(%s)")
            valores.append(hilo)

        where = "WHERE " + " AND ".join(filtros) if filtros else ""
        order = _order_precios(columnas)
        rows = conn.execute(f"""
            SELECT {select}
            FROM precios
            {where}
            {order}
        """, tuple(valores)).fetchall()

    return [_normalizar_precio(row) for row in rows]


def obtener_precios_marca(marca):
    precios = listar_precios({"marca": marca})
    return precios


def obtener_precio_producto(marca=None, hilo=None, codigo=None):
    marca = _texto(marca)
    hilo = _texto(hilo)
    codigo = _texto(codigo)

    producto = None
    if codigo:
        producto = obtener_producto_por_codigo(codigo)
        if producto:
            marca = marca or _texto(producto.get("marca"))
            hilo = hilo or _texto(producto.get("hilo"))

    precio = _buscar_precio_base(marca=marca, hilo=hilo)
    precio_venta = _primer_precio(
        producto.get("precio") if producto else None,
        producto.get("precio_venta") if producto else None,
        precio.get("venta") if precio else None,
        0,
    )
    precio_distribuidor = _primer_precio(
        producto.get("costo_neto") if producto else None,
        producto.get("precio_distribuidor") if producto else None,
        precio.get("distribuidor") if precio else None,
        0,
    )
    costo_neto = _primer_precio(
        producto.get("costo_neto") if producto else None,
        precio.get("distribuidor") if precio else None,
        precio_distribuidor,
        0,
    )

    return {
        "marca": marca or None,
        "hilo": hilo or None,
        "codigo": codigo or None,
        "precio_venta": precio_venta,
        "precio_distribuidor": precio_distribuidor,
        "costo_neto": costo_neto,
    }


def _columnas_productos(conn):
    return _columnas_tabla(conn, "productos")


def _columnas_tabla(conn, tabla):
    rows = conn.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name=%s
    """, (tabla,)).fetchall()
    return {row["column_name"] for row in rows}


def _tabla_existe(conn, tabla):
    row = conn.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_name=%s
        ) AS existe
    """, (tabla,)).fetchone()
    return bool(row and row["existe"])


def _select_producto(columnas, tiene_precios):
    campos = []
    for columna in PRODUCTOS_COLUMNAS_BASE:
        if columna in columnas:
            campos.append(f"p.{columna} AS {columna}")
        else:
            campos.append(f"NULL AS {columna}")

    for columna in PRODUCTOS_COLUMNAS_OPCIONALES:
        if columna in columnas:
            campos.append(f"p.{columna} AS {columna}")
        else:
            campos.append(f"NULL AS {columna}")

    campos.append(f"{_expr_precio_venta(columnas, tiene_precios)} AS precio_venta")
    campos.append(f"{_expr_costo(columnas, tiene_precios)} AS costo_neto_api")
    if tiene_precios:
        campos.append("COALESCE(pr.distribuidor, 0) AS precio_distribuidor")
    else:
        campos.append("0 AS precio_distribuidor")
    return ", ".join(campos)


def _joins_producto(tiene_precios):
    if not tiene_precios:
        return ""
    return "LEFT JOIN precios pr ON pr.marca = p.marca"


def _expr_precio_venta(columnas, tiene_precios):
    partes = []
    if "precio" in columnas:
        partes.append("NULLIF(p.precio, 0)")
    if tiene_precios:
        partes.append("pr.venta")
    partes.append("0")
    return f"COALESCE({', '.join(partes)})"


def _expr_costo(columnas, tiene_precios):
    partes = []
    if "costo_neto" in columnas:
        partes.append("NULLIF(p.costo_neto, 0)")
    if tiene_precios:
        partes.append("pr.distribuidor")
    partes.append("0")
    return f"COALESCE({', '.join(partes)})"


def _where_productos(params, columnas):
    filtros = []
    valores = []

    marca = _texto(params.get("marca"))
    hilo = _texto(params.get("hilo"))
    codigo = _texto(params.get("codigo"))
    q = _texto(params.get("q"))

    if marca:
        filtros.append("UPPER(p.marca)=UPPER(%s)")
        valores.append(marca)
    if hilo:
        filtros.append("UPPER(p.hilo)=UPPER(%s)")
        valores.append(hilo)
    if codigo:
        condiciones_codigo = ["p.codigo=%s"]
        valores.append(codigo)
        if "codigo_barras" in columnas:
            condiciones_codigo.append("p.codigo_barras=%s")
            valores.append(codigo)
        filtros.append("(" + " OR ".join(condiciones_codigo) + ")")
    if q:
        like = f"%{q}%"
        campos_q = ["p.codigo", "p.marca", "p.hilo", "p.color"]
        if "codigo_barras" in columnas:
            campos_q.append("p.codigo_barras")
        filtros.append("(" + " OR ".join(f"{campo} ILIKE %s" for campo in campos_q) + ")")
        valores.extend([like] * len(campos_q))

    if _bool_param(params.get("solo_inventario")) or _bool_param(params.get("incluir_items_cotizacion")) is False:
        filtro = _filtro_inventario(columnas)
        if filtro != "TRUE":
            filtros.append(filtro)

    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, tuple(valores)


def _filtro_inventario(columnas):
    filtros = []
    if "es_inventariable" in columnas:
        filtros.append("COALESCE(p.es_inventariable, TRUE)=TRUE")
    if "tipo_producto" in columnas:
        tipos = ", ".join(f"'{tipo}'" for tipo in TIPOS_NO_INVENTARIO_FISICO)
        filtros.append(f"UPPER(COALESCE(p.tipo_producto, 'INVENTARIO')) NOT IN ({tipos})")
    return " AND ".join(filtros) if filtros else "TRUE"


def _normalizar_producto(row):
    data = dict(row)
    inventariable = _bool_producto(data.get("es_inventariable"))
    tipo_producto = data.get("tipo_producto") or ("INVENTARIO" if inventariable else "ITEM")
    precio_venta = _float(data.get("precio_venta"))
    costo_neto = _float(data.get("costo_neto_api") if data.get("costo_neto_api") is not None else data.get("costo_neto"))

    return {
        "id": data.get("id"),
        "codigo": data.get("codigo"),
        "codigo_barras": data.get("codigo_barras"),
        "marca": data.get("marca"),
        "hilo": data.get("hilo"),
        "color": data.get("color"),
        "stock": _int(data.get("stock")),
        "precio_venta": precio_venta,
        "precio": _float(data.get("precio")),
        "venta": precio_venta,
        "precio_distribuidor": _float(data.get("precio_distribuidor")),
        "distribuidor": _float(data.get("precio_distribuidor")),
        "costo_neto": costo_neto,
        "volumetrico": _float(data.get("volumetrico"), default=1.0),
        "es_inventariable": inventariable,
        "tipo": tipo_producto,
        "tipo_producto": tipo_producto,
        "estado": data.get("estado"),
    }


def _normalizar_resumen(row):
    return {
        "marca": row.get("marca"),
        "hilo": row.get("hilo"),
        "piezas": _int(row.get("piezas")),
        "valor_costo": round(_float(row.get("valor_costo")), 2),
        "valor_venta": round(_float(row.get("valor_venta")), 2),
        "ganancia_estimada": round(_float(row.get("ganancia_estimada")), 2),
    }


def _buscar_precio_base(marca=None, hilo=None):
    with get_conn() as conn:
        if not _tabla_existe(conn, "precios"):
            return None
        columnas = _columnas_tabla(conn, "precios")
        select = _select_precio(columnas)
        condiciones = []
        valores = []
        if marca and "marca" in columnas:
            condiciones.append("UPPER(marca)=UPPER(%s)")
            valores.append(marca)
        if hilo and "hilo" in columnas:
            condiciones.append("UPPER(hilo)=UPPER(%s)")
            valores.append(hilo)
        if not condiciones:
            return None
        where = " AND ".join(condiciones)
        row = conn.execute(f"""
            SELECT {select}
            FROM precios
            WHERE {where}
            LIMIT 1
        """, tuple(valores)).fetchone()
    return _normalizar_precio(row) if row else None


def _select_precio(columnas):
    campos = []
    for columna in ("marca", "hilo", "distribuidor", "venta"):
        if columna in columnas:
            campos.append(f"{columna} AS {columna}")
        else:
            campos.append(f"NULL AS {columna}")
    return ", ".join(campos)


def _order_precios(columnas):
    campos = [columna for columna in ("marca", "hilo") if columna in columnas]
    return "ORDER BY " + ", ".join(campos) if campos else ""


def _normalizar_precio(row):
    data = dict(row)
    distribuidor = _float(data.get("distribuidor"))
    venta = _float(data.get("venta"))
    return {
        "marca": data.get("marca"),
        "hilo": data.get("hilo"),
        "distribuidor": distribuidor,
        "venta": venta,
        "precio_distribuidor": distribuidor,
        "precio_venta": venta,
        "costo_neto": distribuidor,
    }


def _texto(valor):
    return str(valor or "").strip()


def _limite(valor):
    try:
        limit = int(valor)
    except Exception:
        limit = 200
    return max(1, min(limit, 500))


def _offset(valor):
    try:
        offset = int(valor)
    except Exception:
        offset = 0
    return max(0, offset)


def _bool_param(valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in {"1", "true", "si", "sí", "yes", "y"}


def _bool_producto(valor):
    if value_is_empty(valor):
        return True
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    return str(valor).strip().lower() not in {"false", "f", "0", "no", "n", "item"}


def value_is_empty(valor):
    return valor is None or valor == ""


def _float(valor, default=0.0):
    if isinstance(valor, Decimal):
        return float(valor)
    try:
        if valor is None or valor == "":
            return default
        return float(valor)
    except Exception:
        return default


def _primer_numero(*valores):
    for valor in valores:
        if valor is None or valor == "":
            continue
        try:
            return float(valor)
        except Exception:
            continue
    return 0.0


def _primer_precio(*valores):
    ultimo_cero = None
    for valor in valores:
        if valor is None or valor == "":
            continue
        try:
            numero = float(valor)
        except Exception:
            continue
        if numero != 0:
            return numero
        ultimo_cero = 0.0
    return ultimo_cero if ultimo_cero is not None else 0.0


def _int(valor, default=0):
    try:
        if valor is None or valor == "":
            return default
        return int(float(valor))
    except Exception:
        return default
