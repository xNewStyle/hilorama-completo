from database.db import get_conn


# ================= REGISTRAR =================

def registrar_pago(id_nota, imagen_path):
    conn = get_conn()

    conn.execute("""
        INSERT INTO pagos(nota_id, comprobante)
        VALUES (?,?)
    """,(id_nota, imagen_path))

    conn.commit()
    conn.close()


# ================= LISTAR =================

def listar_pagos(id_nota):
    conn = get_conn()

    rows = conn.execute("""
        SELECT * FROM pagos
        WHERE nota_id=?
        ORDER BY fecha DESC
    """,(id_nota,)).fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ================= OBTENER ÚLTIMO =================

def ultimo_pago(id_nota):
    conn = get_conn()

    row = conn.execute("""
        SELECT * FROM pagos
        WHERE nota_id=?
        ORDER BY fecha DESC
        LIMIT 1
    """,(id_nota,)).fetchone()

    conn.close()

    return dict(row) if row else None


# ================= ELIMINAR =================

def eliminar_pago(id_pago):
    conn = get_conn()

    conn.execute(
        "DELETE FROM pagos WHERE id=?",
        (id_pago,)
    )

    conn.commit()
    conn.close()
