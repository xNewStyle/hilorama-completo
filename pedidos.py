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
    require_local_mode("pedidos")
    from database.connection import get_conn
    return get_conn()


def _pedidos_api():
    from hilorama_desktop.services import pedidos_api_service
    return pedidos_api_service


def listar_pedidos():
    if _modo_api():
        return _pedidos_api().listar_pedidos()

    conn = _get_conn()
    rows = conn.execute("""
        SELECT numero, desde, hasta
        FROM pedidos
        ORDER BY numero DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def crear_pedido(numero, desde, hasta):
    if _modo_api():
        try:
            return _pedidos_api().crear_pedido(numero, desde, hasta)
        except Exception as exc:
            if "duplicado" in str(exc).lower():
                raise ValueError("Pedido duplicado") from exc
            raise

    conn = _get_conn()
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
        "hasta": hasta,
        "fecha_inicio": desde,
        "fecha_fin": hasta,
    }


def obtener_pedido(numero):
    if _modo_api():
        return _pedidos_api().obtener_pedido(numero)

    conn = _get_conn()
    r = conn.execute("""
        SELECT numero, desde, hasta
        FROM pedidos
        WHERE numero=%s
    """, (numero,)).fetchone()
    conn.close()
    return dict(r) if r else None
