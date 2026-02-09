import json
import unicodedata
from database.connection import get_conn



# ================= API =================

def _normalizar(texto):
    return texto.strip().lower()


def obtener_o_crear_cliente(nombre):
    conn = get_conn()

    nombre_norm = normalizar_nombre(nombre)

    row = conn.execute("""
        SELECT * FROM clientes
        WHERE LOWER(nombre)=?
    """,(nombre_norm,)).fetchone()

    # 🔥 FIX → convertir direccion JSON a dict
    if row:
        c = dict(row)
        c["direccion"] = json.loads(c["direccion"])
        conn.close()
        return c

    direccion_vacia = {
        "calle": "",
        "numero_ext": "",
        "numero_int": "",
        "colonia": "",
        "codigo_postal": "",
        "estado": "",
        "referencia": ""
    }

    cur = conn.execute("""
        INSERT INTO clientes(nombre, telefono, direccion)
        VALUES (?,?,?)
    """,(nombre.strip(), "", json.dumps(direccion_vacia)))

    conn.commit()

    nuevo_id = cur.lastrowid

    nuevo = {
        "id": nuevo_id,
        "nombre": nombre.strip(),
        "telefono": "",
        "direccion": direccion_vacia
    }

    conn.close()
    return nuevo


def listar_clientes():
    conn = get_conn()

    rows = conn.execute("SELECT * FROM clientes").fetchall()

    clientes = []
    for r in rows:
        c = dict(r)
        c["direccion"] = json.loads(c["direccion"])
        clientes.append(c)

    conn.close()
    return clientes


def obtener_cliente_por_id(id_cliente):
    conn = get_conn()

    r = conn.execute(
        "SELECT * FROM clientes WHERE id=?",
        (id_cliente,)
    ).fetchone()

    conn.close()

    if not r:
        return None

    c = dict(r)
    c["direccion"] = json.loads(c["direccion"])
    return c


def guardar_cliente(cliente):
    conn = get_conn()

    conn.execute("""
        UPDATE clientes
        SET nombre=?,
            telefono=?,
            direccion=?
        WHERE id=?
    """,(
        cliente["nombre"],
        cliente["telefono"],
        json.dumps(cliente["direccion"]),
        cliente["id"]
    ))

    conn.commit()
    conn.close()


def cliente_completo(cliente):
    if not cliente:
        return False

    if not cliente.get("nombre"):
        return False

    tel = cliente.get("telefono", "")
    if not tel.isdigit() or len(tel) != 10:
        return False

    direccion = cliente.get("direccion", {})
    campos_dir = [
        direccion.get("calle"),
        direccion.get("numero_ext"),
        direccion.get("colonia"),
        direccion.get("codigo_postal"),
        direccion.get("estado"),
        direccion.get("municipio"),
    ]

    if not all(campos_dir):
        return False

    referencia = direccion.get("referencia", "")
    if len(referencia) > 20:
        return False

    return True


def normalizar_nombre(nombre):
    nombre = nombre.strip().lower()
    nombre = unicodedata.normalize("NFD", nombre)
    nombre = "".join(c for c in nombre if unicodedata.category(c) != "Mn")
    return nombre


