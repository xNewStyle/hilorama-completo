# auditoria.py

import os
from datetime import datetime

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE
except Exception:
    HILORAMA_DATA_MODE = "local"

USUARIO_ACTUAL = "ADMIN"


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def get_conn():
    if _modo_api():
        raise RuntimeError("La base local de auditoría no está disponible en modo API.")
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()


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


def obtener_registros():

    conn = get_conn()

    rows = conn.execute("""
        SELECT fecha, nota_id, tipo, descripcion
        FROM auditoria
        ORDER BY fecha DESC
    """).fetchall()

    conn.close()

    return [dict(r) for r in rows]


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
