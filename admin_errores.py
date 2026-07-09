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


def get_conn():
    require_local_mode("errores legacy")
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()

def obtener_errores():

    conn = get_conn()

    rows = conn.execute("""
        SELECT 
            e.fecha,
            e.nota_id,
            e.codigo,
            e.motivo,
            em.nombre

        FROM errores_scan e

        JOIN empacadores em
            ON em.id = e.empacador_id

        ORDER BY e.fecha DESC
    """).fetchall()

    conn.close()

    return rows
