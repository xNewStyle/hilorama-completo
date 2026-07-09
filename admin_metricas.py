import os

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE
except Exception:
    HILORAMA_DATA_MODE = "local"


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def get_conn():
    if _modo_api():
        raise RuntimeError("Las métricas legacy no están disponibles con base local en modo API.")
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()

def obtener_metricas_empacadores():

    conn = get_conn()

    rows = conn.execute("""
        SELECT 
            e.id,
            e.nombre,

            COUNT(n.id) FILTER (WHERE n.estado IS NOT NULL) AS total_notas,
            COUNT(n.id) FILTER (WHERE n.estado = 'COMPLETA') AS completas,
            COUNT(n.id) FILTER (WHERE n.estado = 'INCOMPLETA') AS incompletas,

            COUNT(err.id) AS errores,

            AVG(EXTRACT(EPOCH FROM 
                (n.fecha_finalizacion - n.fecha_asignacion)
            )/60) FILTER (WHERE n.estado = 'COMPLETA') 
            AS tiempo_promedio_min

        FROM empacadores e

        LEFT JOIN notas n 
            ON n.empacador_id = e.id

        LEFT JOIN errores_scan err
            ON err.empacador_id = e.id

        WHERE e.activo = TRUE

        GROUP BY e.id, e.nombre
        ORDER BY completas DESC
    """).fetchall()

    conn.close()

    return rows
