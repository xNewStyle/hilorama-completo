import json
import os
import unicodedata

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE, require_local_mode
except Exception:
    HILORAMA_DATA_MODE = "local"
    def require_local_mode(area=""):
        if os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api":
            detalle = f" ({area})" if area else ""
            raise RuntimeError(f"Base local bloqueada en modo API cliente{detalle}.")


ACCION_NO_DISPONIBLE_API = "Esta acción todavía no está disponible en modo API."


def get_conn():
    require_local_mode("clientes")
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _clientes_api():
    from hilorama_desktop.services import clientes_api_service
    return clientes_api_service


def _bloquear_escritura_api():
    if not _modo_api():
        return
    try:
        from tkinter import messagebox
        messagebox.showwarning("Modo API", ACCION_NO_DISPONIBLE_API)
    except Exception:
        pass
    raise RuntimeError(ACCION_NO_DISPONIBLE_API)


def _parse_direccion(valor):
    if isinstance(valor, dict):
        return valor
    if not valor:
        return {}
    try:
        return json.loads(valor)
    except Exception:
        return {}



# ================= API =================

def _normalizar(texto):
    return texto.strip().lower()


def obtener_o_crear_cliente(nombre):
    if _modo_api():
        nombre_norm = normalizar_nombre(nombre)
        for cliente in _clientes_api().buscar_clientes({"q": nombre, "limit": 10}):
            if normalizar_nombre(cliente.get("nombre", "")) == nombre_norm:
                return cliente
        direccion_vacia = {
            "calle": "",
            "numero_ext": "",
            "numero_int": "",
            "colonia": "",
            "codigo_postal": "",
            "estado": "",
            "municipio": "",
            "referencia": ""
        }
        return _clientes_api().crear_cliente(nombre.strip(), "", direccion_vacia)

    conn = get_conn()

    nombre_norm = normalizar_nombre(nombre)

    row = conn.execute("""
        SELECT * FROM clientes
        WHERE LOWER(nombre) = %s
    """, (nombre_norm,)).fetchone()

    if row:
        c = dict(row)
        c["direccion"] = _parse_direccion(c.get("direccion"))
        conn.close()
        return c

    direccion_vacia = {
        "calle": "",
        "numero_ext": "",
        "numero_int": "",
        "colonia": "",
        "codigo_postal": "",
        "estado": "",
        "municipio": "",
        "referencia": ""
    }

    cur = conn.execute("""
        INSERT INTO clientes (nombre, telefono, direccion)
        VALUES (%s, %s, %s)
        RETURNING id
    """, (
        nombre.strip(),
        "",
        json.dumps(direccion_vacia)
    ))

    nuevo_id = cur.fetchone()["id"]

    conn.commit()
    conn.close()

    return {
        "id": nuevo_id,
        "nombre": nombre.strip(),
        "telefono": "",
        "direccion": direccion_vacia
    }



def listar_clientes():
    if _modo_api():
        return _clientes_api().listar_clientes()

    conn = get_conn()

    rows = conn.execute("SELECT * FROM clientes").fetchall()

    clientes = []
    for r in rows:
        c = dict(r)
        c["direccion"] = _parse_direccion(c.get("direccion"))
        clientes.append(c)

    conn.close()
    return clientes


def buscar_clientes(texto="", limit=10):
    texto = str(texto or "").strip()
    if not texto:
        return []

    if _modo_api():
        return _clientes_api().buscar_clientes({"q": texto, "limit": limit})

    texto_norm = normalizar_nombre(texto)
    digitos = "".join(c for c in texto if c.isdigit())
    encontrados = []
    for cliente in listar_clientes():
        nombre = normalizar_nombre(cliente.get("nombre", ""))
        telefono = str(cliente.get("telefono", "") or "")
        if texto_norm in nombre or (digitos and digitos in telefono):
            encontrados.append(cliente)
        if len(encontrados) >= limit:
            break
    return encontrados


def obtener_cliente_por_id(id_cliente):
    if _modo_api():
        return _clientes_api().obtener_cliente(id_cliente)

    conn = get_conn()

    r = conn.execute(
        "SELECT * FROM clientes WHERE id=%s",
        (id_cliente,)
    ).fetchone()

    conn.close()

    if not r:
        return None

    c = dict(r)
    c["direccion"] = _parse_direccion(c.get("direccion"))
    return c


def guardar_cliente(cliente):
    if _modo_api():
        actualizado = _clientes_api().actualizar_cliente(cliente["id"], cliente)
        if actualizado:
            cliente.update(actualizado)
        return actualizado

    conn = get_conn()

    conn.execute("""
        UPDATE clientes
        SET nombre=%s,
            telefono=%s,
            direccion=%s
        WHERE id=%s
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
    if len(referencia) > 100:
        return False

    return True


def normalizar_nombre(nombre):
    nombre = nombre.strip().lower()
    nombre = unicodedata.normalize("NFD", nombre)
    nombre = "".join(c for c in nombre if unicodedata.category(c) != "Mn")
    return nombre


def buscar_cliente_por_telefono(telefono):
    if _modo_api():
        return _clientes_api().buscar_cliente_por_telefono(telefono)

    conn = get_conn()

    row = conn.execute("""
        SELECT * FROM clientes
        WHERE telefono=%s
    """, (telefono,)).fetchone()

    conn.close()

    if not row:
        return None
    cliente = dict(row)
    cliente["direccion"] = _parse_direccion(cliente.get("direccion"))
    return cliente
