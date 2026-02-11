
from database.connection import get_conn


def listar_empacadores_activos():
    conn = get_conn()

    rows = conn.execute("""
        SELECT id, nombre
        FROM empacadores
        WHERE activo = TRUE
        ORDER BY nombre
    """).fetchall()

    conn.close()
    return rows

