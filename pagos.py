import os
import shutil
from pathlib import Path

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE
except Exception:
    HILORAMA_DATA_MODE = "local"


ACCION_NO_DISPONIBLE_API = "Esta acción todavía no está disponible en modo API."
BASE_DIR = Path(__file__).resolve().parent
COMPROBANTES_DIR = BASE_DIR / "comprobantes"


def get_conn():
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _notas_api():
    from hilorama_desktop.services import notas_api_service
    return notas_api_service


def _bloquear_escritura_api():
    if not _modo_api():
        return
    try:
        from tkinter import messagebox
        messagebox.showwarning("Modo API", ACCION_NO_DISPONIBLE_API)
    except Exception:
        pass
    raise RuntimeError(ACCION_NO_DISPONIBLE_API)


def _ruta_portable_comprobante(id_nota, ruta):
    if not ruta:
        return None
    ruta_txt = str(ruta).strip()
    if not ruta_txt:
        return None
    ruta_path = Path(ruta_txt)
    if not ruta_path.is_absolute():
        return ruta_txt.replace("\\", "/")

    COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)
    ext = ruta_path.suffix.lower() or ".png"
    destino = COMPROBANTES_DIR / f"{id_nota}{ext}"
    if ruta_path.resolve() != destino.resolve():
        shutil.copy(str(ruta_path), str(destino))
    return (Path("comprobantes") / destino.name).as_posix()



# ================= REGISTRAR =================

def registrar_pago(id_nota, imagen_path):
    if _modo_api():
        comprobante = _ruta_portable_comprobante(id_nota, imagen_path)
        return _notas_api().registrar_pago(id_nota, comprobante)

    _bloquear_escritura_api()

    conn = get_conn()

    conn.execute("""
        INSERT INTO pagos(nota_id, comprobante)
        VALUES (%s,%s)
    """,(id_nota, imagen_path))

    conn.commit()
    conn.close()


# ================= LISTAR =================

def listar_pagos(id_nota):
    if _modo_api():
        return _notas_api().obtener_pagos_nota(id_nota)

    conn = get_conn()

    rows = conn.execute("""
        SELECT * FROM pagos
        WHERE nota_id=%s
        ORDER BY fecha DESC
    """,(id_nota,)).fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ================= OBTENER ÚLTIMO =================

def ultimo_pago(id_nota):
    if _modo_api():
        pagos = listar_pagos(id_nota)
        return pagos[0] if pagos else None

    conn = get_conn()

    row = conn.execute("""
        SELECT * FROM pagos
        WHERE nota_id=%s
        ORDER BY fecha DESC
        LIMIT 1
    """,(id_nota,)).fetchone()

    conn.close()

    return dict(row) if row else None


# ================= ELIMINAR =================

def eliminar_pago(id_pago):
    _bloquear_escritura_api()

    conn = get_conn()

    conn.execute(
        "DELETE FROM pagos WHERE id=%s",
        (id_pago,)
    )

    conn.commit()
    conn.close()
