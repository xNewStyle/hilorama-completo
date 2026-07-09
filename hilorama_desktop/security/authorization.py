"""Autorizaciones locales temporales para flujos legacy.

En modo API las autorizaciones sensibles se validan en el backend. La validacion
local queda solo para desarrollo/modo local mientras terminan de migrarse esos
dialogos.
"""

from __future__ import annotations

import os


DEFAULT_ADMIN_OVERRIDE_KEY = "1"
ENV_ADMIN_OVERRIDE_KEY = "HILORAMA_ADMIN_OVERRIDE_KEY"
ENV_LEGACY_LOCAL_OVERRIDE_KEY = "HILORAMA_LEGACY_LOCAL_OVERRIDE_KEY"


def _env_key():
    value = os.environ.get(ENV_ADMIN_OVERRIDE_KEY, "").strip()
    return value or None


def _legacy_local_env_key():
    value = os.environ.get(ENV_LEGACY_LOCAL_OVERRIDE_KEY, "").strip()
    return value or _env_key()


def _is_api_mode():
    try:
        from hilorama_desktop.config import is_api_mode

        return is_api_mode()
    except Exception:
        return os.environ.get("HILORAMA_DATA_MODE", "").strip().lower() == "api"


def _session_token():
    try:
        from hilorama_desktop.security.local_secure_store import LocalSecureStore

        session = LocalSecureStore().load() or {}
    except Exception:
        return None
    token = session.get("token")
    if not token or token == "dev-local-session":
        return None
    return token


def get_admin_override_key():
    return _env_key() or DEFAULT_ADMIN_OVERRIDE_KEY


def get_legacy_sales_override_key():
    return _legacy_local_env_key() or DEFAULT_ADMIN_OVERRIDE_KEY


def validar_autorizacion_backend(tipo, clave, contexto=None):
    token = _session_token()
    if not token:
        return False

    try:
        from hilorama_desktop.api_client.render_api_client import RenderApiClient

        data = RenderApiClient().post(
            "/api/autorizaciones/validar",
            {
                "tipo": tipo,
                "clave": str(clave or ""),
                "contexto": contexto or {},
            },
            token=token,
        )
        return bool(data.get("ok") and data.get("autorizado"))
    except Exception:
        return False


def is_admin_override_key(value):
    return str(value or "") == get_admin_override_key()


def is_legacy_sales_override_key(value, contexto=None):
    if _is_api_mode():
        return validar_autorizacion_backend("admin_legacy", value, contexto=contexto)
    return str(value or "") == get_legacy_sales_override_key()
