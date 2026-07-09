import os
from datetime import datetime

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE, require_local_mode
except Exception:
    HILORAMA_DATA_MODE = "local"
    def require_local_mode(area=""):
        if os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api":
            detalle = f" ({area})" if area else ""
            raise RuntimeError(f"Base local bloqueada en modo API cliente{detalle}.")


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _get_conn():
    require_local_mode("pedido activo")
    from database.connection import get_conn
    return get_conn()


def _pedidos_api():
    from hilorama_desktop.services import pedidos_api_service
    return pedidos_api_service


def activar_pedido(numero):
    if _modo_api():
        return _pedidos_api().activar_pedido(numero)

    conn = _get_conn()
    conn.execute("UPDATE pedidos SET activo = FALSE")
    conn.execute("""
        UPDATE pedidos
        SET activo = TRUE
        WHERE numero = %s
    """, (numero,))
    conn.commit()
    conn.close()


def cargar_pedido():
    if _modo_api():
        return _pedidos_api().obtener_pedido_activo()

    conn = _get_conn()
    row = conn.execute("""
        SELECT numero, desde, hasta
        FROM pedidos
        WHERE activo = TRUE
        LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


def limpiar_pedido_activo():
    if _modo_api():
        return _pedidos_api().limpiar_pedido_activo()

    conn = _get_conn()
    conn.execute("UPDATE pedidos SET activo = FALSE")
    conn.commit()
    conn.close()


def _fecha_pedido(valor):
    if not valor:
        return None
    if hasattr(valor, "date") and not isinstance(valor, str):
        try:
            return valor.date()
        except Exception:
            pass
    if hasattr(valor, "isoformat") and not isinstance(valor, str):
        return valor
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except Exception:
            pass
    return None


def pedido_vencido(pedido):
    if not pedido:
        return False
    fin = _fecha_pedido(pedido.get("hasta"))
    if not fin:
        return False
    return datetime.now().date() > fin


def pedido_por_vencer(pedido):
    if not pedido:
        return False
    fin = _fecha_pedido(pedido.get("hasta"))
    if not fin:
        return False
    return (fin - datetime.now().date()).days == 1
