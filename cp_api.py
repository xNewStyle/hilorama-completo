# cp_api.py
import json
import os

# ================= RUTAS =================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CP_JSON = os.path.join(BASE_DIR, "cp_offline.json")

# ================= CACHE =================

_CP_DATA = None


# ================= CARGA =================

def _cargar_cp():
    global _CP_DATA

    if _CP_DATA is not None:
        return

    if not os.path.exists(CP_JSON):
        print("❌ No existe cp_offline.json")
        _CP_DATA = {}
        return

    with open(CP_JSON, "r", encoding="utf-8") as f:
        _CP_DATA = json.load(f)

    # seguridad: forzar claves string
    _CP_DATA = {str(k).zfill(5): v for k, v in _CP_DATA.items()}


# ================= API PUBLICA =================

def buscar_codigo_postal(cp):
    """
    Devuelve:
    {
        estado: str,
        municipio: str,
        colonias: list[str]
    }
    o None si no existe
    """

    if not cp:
        return None

    cp = str(cp).strip()

    if not cp.isdigit() or len(cp) != 5:
        return None

    _cargar_cp()

    info = _CP_DATA.get(cp)
    if not info:
        return None

    estado = info.get("estado", "").strip()
    municipio = info.get("municipio", "").strip()
    colonias = info.get("colonias", [])

    if not isinstance(colonias, list):
        colonias = []

    return {
        "estado": estado,
        "municipio": municipio,
        "colonias": colonias
    }
