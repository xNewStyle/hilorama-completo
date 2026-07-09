"""Almacen local basico para sesion.

No guarda contrasenas. El contenido se ofusca con una llave derivada del equipo
para evitar texto plano casual. No es cifrado fuerte y no reemplaza un llavero
del sistema operativo.
"""

import base64
import json
import os
from pathlib import Path

from .device_id import get_device_id_hash


def _app_data_dir():
    base = os.environ.get("HILORAMA_DESKTOP_DATA_DIR")
    if base:
        path = Path(base)
    else:
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        path = Path(root) / "HiloramaDesktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_session_file_path():
    override = os.environ.get("HILORAMA_SESSION_FILE")
    if override:
        return Path(override)
    return _app_data_dir() / "session.dat"


def _xor_bytes(data):
    key = get_device_id_hash().encode("utf-8")
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


class LocalSecureStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else get_session_file_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        protected = base64.b64encode(_xor_bytes(raw)).decode("ascii")
        self.path.write_text(json.dumps({"v": 1, "payload": protected}), encoding="utf-8")

    def load(self):
        if not self.path.exists():
            return None
        try:
            wrapper = json.loads(self.path.read_text(encoding="utf-8"))
            protected = base64.b64decode(wrapper["payload"].encode("ascii"))
            raw = _xor_bytes(protected)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def clear(self):
        if self.path.exists():
            self.path.unlink()
