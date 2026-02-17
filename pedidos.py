# pedidos.py

from database.connection import get_conn


# ===============================
# 🔵 LISTAR
# ===============================
def listar_pedidos():
    conn = get_conn()

    rows = conn.execute("""
        SELECT numero, desde, hasta
        FROM pedidos
        ORDER BY numero DESC
    """).fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ===============================
# 🔵 CREAR
# ===============================
def crear_pedido(numero, desde, hasta):

    conn = get_conn()

    # 🔎 VALIDAR EXISTENCIA EXPLÍCITA
    existente = conn.execute("""
        SELECT numero
        FROM pedidos
        WHERE numero=%s
    """, (numero,)).fetchone()

    if existente:
        conn.close()
        raise ValueError("Pedido duplicado")

    try:
        conn.execute("""
            INSERT INTO pedidos(numero, desde, hasta)
            VALUES (%s,%s,%s)
        """, (numero, desde, hasta))

        conn.commit()

    except Exception as e:
        conn.rollback()
        conn.close()
        raise e  # 🔥 ahora sí lanza el error real

    conn.close()

    return {
        "numero": numero,
        "desde": desde,
        "hasta": hasta
    }


# ===============================
# 🔵 OBTENER
# ===============================
def obtener_pedido(numero):
    conn = get_conn()

    r = conn.execute("""
        SELECT numero, desde, hasta
        FROM pedidos
        WHERE numero=%s
    """, (numero,)).fetchone()

    conn.close()

    return dict(r) if r else None
