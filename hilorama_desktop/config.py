"""Configuracion base de Hilorama Desktop.

No guardar secretos aqui. Las credenciales y tokens deben venir de variables de
entorno o del flujo seguro de autenticacion.
"""

import os
import sys

APP_NAME = "Hilorama Desktop"
APP_VERSION = "0.2.0-fase2"

HILORAMA_ENV = os.environ.get("HILORAMA_ENV", "production").strip().lower()
BUILD_CHANNEL = os.environ.get("BUILD_CHANNEL", "development").strip().lower()
IS_FROZEN_BUILD = bool(getattr(sys, "frozen", False))
HILORAMA_DATA_MODE = os.environ.get("HILORAMA_DATA_MODE", "local").strip().lower()
DATA_MODE = HILORAMA_DATA_MODE

RENDER_API_BASE_URL = os.environ.get(
    "HILORAMA_RENDER_API_BASE_URL",
    "http://127.0.0.1:10000",
).rstrip("/")


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
