"""Servicio comun de autenticacion/licencia para Desktop y Ventas."""

from datetime import datetime, timedelta, timezone

try:
    from ..api_client.render_api_client import RenderApiClient, RenderApiError
    from ..config import (
        APP_VERSION,
        AUTH_DEV_BYPASS,
        AUTH_OFFLINE_GRACE_HOURS,
        DEV_BYPASS_PASSWORD,
        DEV_BYPASS_USER,
        HILORAMA_DATA_MODE,
    )
    from ..security.device_id import get_device_profile
    from ..security.local_secure_store import LocalSecureStore, get_session_file_path
except ImportError:
    from api_client.render_api_client import RenderApiClient, RenderApiError
    from config import (
        APP_VERSION,
        AUTH_DEV_BYPASS,
        AUTH_OFFLINE_GRACE_HOURS,
        DEV_BYPASS_PASSWORD,
        DEV_BYPASS_USER,
        HILORAMA_DATA_MODE,
    )
    from security.device_id import get_device_profile
    from security.local_secure_store import LocalSecureStore, get_session_file_path


BLOCKING_STATES = {"suspendido", "vencido", "bloqueado", "bloqueado_permanente"}


def _now():
    return datetime.now(timezone.utc)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class AuthService:
    def __init__(self, api_client=None, store=None):
        self.api = api_client or RenderApiClient()
        self.store = store or LocalSecureStore()

    @property
    def session_file(self):
        return str(get_session_file_path())

    def login(self, usuario, password, licencia=None, modulo="desktop"):
        if (
            not _api_data_mode()
            and
            AUTH_DEV_BYPASS
            and DEV_BYPASS_USER
            and DEV_BYPASS_PASSWORD
            and usuario == DEV_BYPASS_USER
            and password == DEV_BYPASS_PASSWORD
        ):
            session = self._dev_session(modulo)
            self.store.save(session)
            return session

        payload = {
            "usuario": usuario,
            "password": password,
            "licencia": licencia or "",
            "modulo_actual": modulo,
            **get_device_profile(APP_VERSION),
        }
        data = self.api.post("/api/auth/login", payload)
        if not data.get("permitido"):
            raise RenderApiError(data.get("mensaje") or "Acceso no permitido")

        session = self._normalize_session(data, modulo)
        self.store.save(session)
        return session

    def require_access(self, modulo="desktop"):
        session = self.store.load()
        if not session:
            return None
        if session.get("estado") in BLOCKING_STATES:
            return None
        if _api_data_mode() and _es_sesion_dev(session):
            self.store.clear()
            return None

        token = session.get("token")
        if _api_data_mode() and not token:
            self.store.clear()
            return None
        try:
            data = self.api.post("/api/license/validate", {
                "modulo_actual": modulo,
                **get_device_profile(APP_VERSION),
            }, token=token)
            if not data.get("permitido"):
                session["estado"] = data.get("estado") or "bloqueado"
                session["mensaje"] = data.get("mensaje") or "Acceso no permitido"
                self.store.save(session)
                return None
            session.update(self._normalize_session(data, modulo, existing=session))
            self.store.save(session)
            return session
        except RenderApiError:
            if _api_data_mode():
                return None
            if self._offline_allowed(session):
                session["modo_offline"] = True
                return session
            return None

    def heartbeat(self, modulo="desktop"):
        session = self.store.load()
        if not session or not session.get("token"):
            return {"permitido": False, "estado": "sin_sesion", "mensaje": "Sesion no valida"}

        payload = {
            "modulo_actual": modulo,
            **get_device_profile(APP_VERSION),
        }
        data = self.api.post("/api/license/heartbeat", payload, token=session["token"])
        if data.get("permitido"):
            session.update(self._normalize_session(data, modulo, existing=session))
            self.store.save(session)
        else:
            session["estado"] = data.get("estado") or "bloqueado"
            session["mensaje"] = data.get("mensaje") or "Acceso bloqueado"
            self.store.save(session)
        return data

    def logout(self):
        session = self.store.load()
        if session and session.get("token"):
            try:
                self.api.post("/api/auth/logout", {}, token=session["token"])
            except RenderApiError:
                pass
        self.store.clear()

    def _normalize_session(self, data, modulo, existing=None):
        base = dict(existing or {})
        base.update({
            "token": data.get("token") or base.get("token"),
            "estado": data.get("estado") or base.get("estado") or "activo",
            "permitido": bool(data.get("permitido", True)),
            "permisos": data.get("permisos", base.get("permisos", [])),
            "mensaje": data.get("mensaje", ""),
            "modulo_actual": modulo,
            "usuario": data.get("usuario", base.get("usuario")),
            "cliente": data.get("cliente", base.get("cliente")),
            "last_validated_at": _now().isoformat(),
            "app_version": APP_VERSION,
        })
        return base

    def _offline_allowed(self, session):
        if session.get("estado") in BLOCKING_STATES:
            return False
        last = _parse_dt(session.get("last_validated_at"))
        if not last:
            return False
        return _now() - last <= timedelta(hours=AUTH_OFFLINE_GRACE_HOURS)

    def _dev_session(self, modulo):
        return {
            "token": "dev-local-session",
            "estado": "activo",
            "permitido": True,
            "permisos": ["dev"],
            "mensaje": "Modo local de desarrollo",
            "modulo_actual": modulo,
            "usuario": {"id": 0, "nombre": "Desarrollo", "rol": "super_admin"},
            "cliente": {"id": 0, "nombre_negocio": "Hilorama local"},
            "last_validated_at": _now().isoformat(),
            "app_version": APP_VERSION,
        }


def _api_data_mode():
    return str(HILORAMA_DATA_MODE or "").strip().lower() == "api"


def _es_sesion_dev(session):
    if not session:
        return False
    if session.get("token") == "dev-local-session":
        return True
    permisos = session.get("permisos") or []
    if "dev" in permisos:
        return True
    usuario = session.get("usuario") or {}
    return usuario.get("id") == 0
