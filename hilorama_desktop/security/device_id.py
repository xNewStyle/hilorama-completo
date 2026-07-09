"""Identificador estable del equipo para control de licencia.

Solo se expone el hash; no se manda el identificador crudo del equipo.
"""

import hashlib
import platform
import uuid


def _raw_device_id():
    parts = [
        platform.node() or "equipo",
        platform.system() or "sistema",
        platform.release() or "release",
        str(uuid.getnode()),
    ]
    return "|".join(parts)


def get_device_id_hash():
    return hashlib.sha256(_raw_device_id().encode("utf-8")).hexdigest()


def get_device_profile(app_version):
    return {
        "device_id_hash": get_device_id_hash(),
        "nombre_equipo": platform.node() or "equipo",
        "sistema_operativo": f"{platform.system()} {platform.release()}".strip(),
        "app_version": app_version,
    }
