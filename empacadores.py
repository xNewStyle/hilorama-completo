import os

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
    require_local_mode("empacadores")
    from database.connection import get_conn
    return get_conn()


def listar_empacadores_activos():
    if _modo_api():
        from hilorama_desktop.services.pedidos_api_service import listar_empacadores
        return listar_empacadores(activos=True)

    conn = _get_conn()
    rows = conn.execute("""
        SELECT id, nombre
        FROM empacadores
        WHERE activo = TRUE
        ORDER BY nombre
    """).fetchall()
    conn.close()
    return rows
