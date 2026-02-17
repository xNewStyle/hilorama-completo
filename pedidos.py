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
from datetime import datetime

def crear_pedido(numero, desde, hasta):

    conn = get_conn()

    # 🔥 convertir a objeto date real
    desde_date = datetime.strptime(desde, "%d/%m/%Y").date()
    hasta_date = datetime.strptime(hasta, "%d/%m/%Y").date()

    existente = conn.execute("""
        SELECT numero
        FROM pedidos
        WHERE numero=%s
    """, (numero,)).fetchone()

    if existente:
        conn.close()
        raise ValueError("Pedido duplicado")

    conn.execute("""
        INSERT INTO pedidos(numero, desde, hasta)
        VALUES (%s,%s,%s)
    """, (numero, desde_date, hasta_date))

    conn.commit()
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
