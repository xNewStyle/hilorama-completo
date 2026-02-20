# auditoria.py

from database.connection import get_conn
from datetime import datetime

USUARIO_ACTUAL = "ADMIN"

def registrar_cambio(nota_id, accion, detalle):

    conn = get_conn()

    conn.execute("""
        INSERT INTO auditoria_notas
        (nota_id, usuario, accion, detalle)
        VALUES (%s, %s, %s, %s)
    """, (
        nota_id,
        USUARIO_ACTUAL,
        accion,
        detalle
    ))

    conn.commit()
    conn.close()
from database.connection import get_conn

def obtener_registros():

    conn = get_conn()

    rows = conn.execute("""
        SELECT fecha, nota_id, tipo, descripcion
        FROM auditoria
        ORDER BY fecha DESC
    """).fetchall()

    conn.close()

    return [dict(r) for r in rows]    
from database.connection import get_conn
from datetime import datetime

def registrar_evento(nota_id, tipo, descripcion):
    conn = get_conn()

    conn.execute("""
        INSERT INTO auditoria (fecha, nota_id, tipo, descripcion)
        VALUES (%s, %s, %s, %s)
    """, (
        datetime.now(),
        nota_id,
        tipo,
        descripcion
    ))

    conn.commit()
    conn.close()