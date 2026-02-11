# pedidos.py (SQLite version)

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

    try:
        conn.execute("""
            INSERT INTO pedidos(numero, desde, hasta)
            VALUES (%s,%s,%s)
        """, (numero, desde, hasta))

        conn.commit()

    except:
        conn.close()
        raise ValueError("Pedido duplicado")

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

