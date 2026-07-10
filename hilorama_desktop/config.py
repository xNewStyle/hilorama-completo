"""Configuracion base de Hilorama Desktop.

No guardar secretos aqui. Las credenciales y tokens deben venir de variables de
entorno o del flujo seguro de autenticacion.
"""

import os
import sys
from pathlib import Path

APP_NAME = "Hilorama Desktop"
APP_VERSION = "0.2.0-fase2"
APP_UPDATE_NAME = "HiloramaCliente"

HILORAMA_ENV = os.environ.get("HILORAMA_ENV", "production").strip().lower()
BUILD_CHANNEL = os.environ.get("BUILD_CHANNEL", "development").strip().lower()
IS_FROZEN_BUILD = bool(getattr(sys, "frozen", False))
HILORAMA_CLIENT_MODE = os.environ.get("HILORAMA_CLIENT_MODE", "production").strip().lower()
DEFAULT_API_BASE_URL = "https://hilorama-completo.onrender.com"
DEFAULT_UPDATE_MANIFEST_URL = "https://hilorama-completo.onrender.com/updates/HiloramaCliente/update.json"


def _default_data_mode():
    project_root = Path(__file__).resolve().parents[1]
    if (project_root / "database").exists():
        return "local"
    return "api"


HILORAMA_DATA_MODE = os.environ.get("HILORAMA_DATA_MODE", _default_data_mode()).strip().lower()
DATA_MODE = HILORAMA_DATA_MODE


def get_api_base_url():
    base_url = os.environ.get("HILORAMA_RENDER_API_BASE_URL", "").strip() or DEFAULT_API_BASE_URL
    if not base_url:
        raise RuntimeError("Falta HILORAMA_RENDER_API_BASE_URL o DEFAULT_API_BASE_URL.")
    return base_url.rstrip("/")


RENDER_API_BASE_URL = get_api_base_url()


def get_update_manifest_url():
    return (
        os.environ.get("HILORAMA_UPDATE_MANIFEST_URL", "").strip()
        or DEFAULT_UPDATE_MANIFEST_URL
    ).strip()


def current_data_mode():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower()


def is_api_mode():
    return current_data_mode() == "api"


def require_local_mode(area=""):
    if not is_api_mode():
        return
    detalle = f" ({area})" if area else ""
    raise RuntimeError(f"Base local bloqueada en modo API cliente{detalle}.")


def is_dev_bypass_allowed(env=None, build_channel=None, requested=None, frozen=None):
    env = (env if env is not None else HILORAMA_ENV).strip().lower()
    build_channel = (build_channel if build_channel is not None else BUILD_CHANNEL).strip().lower()
    requested = (
        os.environ.get("HILORAMA_AUTH_DEV_BYPASS", "0") == "1"
        if requested is None
        else bool(requested)
    )
    frozen = IS_FROZEN_BUILD if frozen is None else bool(frozen)
    return requested and env == "development" and build_channel != "production" and not frozen


# Para build final:
#   HILORAMA_ENV=production
#   HILORAMA_AUTH_DEV_BYPASS=0
# En cualquier ejecutable congelado sys.frozen=True, este bypass siempre queda
# desactivado aunque alguien cambie variables de entorno.
AUTH_DEV_BYPASS = is_dev_bypass_allowed()
DEV_BYPASS_USER = os.environ.get("HILORAMA_DEV_BYPASS_USER", "")
DEV_BYPASS_PASSWORD = os.environ.get("HILORAMA_DEV_BYPASS_PASSWORD", "")
AUTH_OFFLINE_GRACE_HOURS = int(os.environ.get("HILORAMA_AUTH_OFFLINE_GRACE_HOURS", "72"))
HEARTBEAT_INTERVAL_MS = int(os.environ.get("HILORAMA_HEARTBEAT_INTERVAL_MS", "300000"))
