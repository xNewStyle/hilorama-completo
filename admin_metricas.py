from database.connection import get_conn

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
