from database.connection import get_conn

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
