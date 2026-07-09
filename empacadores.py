import os

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE
except Exception:
    HILORAMA_DATA_MODE = "local"


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _get_conn():
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
