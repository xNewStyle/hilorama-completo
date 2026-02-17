from database.connection import get_conn
from datetime import datetime

# =====================================================
# 🔵 ACTIVAR PEDIDO
# =====================================================
def activar_pedido(numero):
    conn = get_conn()

    # Desactivar todos
    conn.execute("UPDATE pedidos SET activo = FALSE")

    # Activar el seleccionado
    conn.execute("""
        UPDATE pedidos
        SET activo = TRUE
        WHERE numero = %s
    """, (numero,))

    conn.commit()
    conn.close()


# =====================================================
# 🔵 OBTENER PEDIDO ACTIVO
# =====================================================
def cargar_pedido():
    conn = get_conn()

    row = conn.execute("""
        SELECT numero, desde, hasta
        FROM pedidos
        WHERE activo = TRUE
        LIMIT 1
    """).fetchone()

    conn.close()

    return dict(row) if row else None


# =====================================================
# 🔵 DESACTIVAR PEDIDO
# =====================================================
def limpiar_pedido_activo():
    conn = get_conn()
    conn.execute("UPDATE pedidos SET activo = FALSE")
    conn.commit()
    conn.close()


# =====================================================
# 🔵 ESTADOS
# =====================================================
def pedido_vencido(pedido):
    if not pedido:
        return False

    hoy = datetime.now().date()
    fin = pedido["hasta"]

    if isinstance(fin, str):
        fin = datetime.strptime(fin, "%d/%m/%Y").date()

    return hoy > fin



def pedido_por_vencer(pedido):
    if not pedido:
        return False

    hoy = datetime.now().date()
    fin = pedido["hasta"]

    if isinstance(fin, str):
        fin = datetime.strptime(fin, "%d/%m/%Y").date()

    return (fin - hoy).days == 1
