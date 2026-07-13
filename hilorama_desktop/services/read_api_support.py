"""Soporte comun para servicios Desktop de solo lectura por API."""

from __future__ import annotations

from typing import Any, Callable

try:
    from ..api_client.render_api_client import RenderApiError
    from ..security.local_secure_store import LocalSecureStore
    from ..utils.logger import log_error, log_info
    from ..utils.presentation import redact_sensitive_data
except ImportError:
    from api_client.render_api_client import RenderApiError
    from security.local_secure_store import LocalSecureStore
    from utils.logger import log_error, log_info
    from utils.presentation import redact_sensitive_data


class ApiReadError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class SessionExpiredError(ApiReadError):
    pass


class PermissionDeniedError(ApiReadError):
    pass


class RecordNotFoundError(ApiReadError):
    pass


def normalize_pagination(params: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(params or {})
    page = _positive_int(values.pop("page", 1), "page")
    per_page = _positive_int(values.pop("per_page", values.pop("limit", 50)), "per_page")
    if per_page > 100:
        raise ValueError("per_page no puede ser mayor a 100.")
    values["page"] = page
    values["per_page"] = per_page
    values.pop("offset", None)
    return {key: value for key, value in values.items() if value not in (None, "")}


def load_session(session_provider: Callable[[], dict | None] | None = None) -> dict:
    provider = session_provider or LocalSecureStore().load
    session = provider() or {}
    token = extract_token(session)
    if not token:
        raise SessionExpiredError("La sesion expiro. Inicia sesion nuevamente.", status=401)
    return session


def extract_token(session: dict | None) -> str | None:
    for field in ("token", "access_token", "session_token", "auth_token"):
        value = (session or {}).get(field)
        if value:
            return str(value)
    return None


def call_read(
    *,
    action: str,
    endpoint: str,
    api_call: Callable[[str], dict],
    session_provider: Callable[[], dict | None] | None = None,
) -> dict:
    session = load_session(session_provider)
    token = extract_token(session)
    try:
        data = api_call(token) or {}
    except RenderApiError as exc:
        error = _translate_error(exc)
        log_error("hilorama_desktop", f"Lectura API fallida: accion={action} endpoint={endpoint} status={exc.status}")
        raise error from exc
    except Exception as exc:
        log_error("hilorama_desktop", f"Lectura API inesperada: accion={action} endpoint={endpoint}", exc)
        raise ApiReadError("No se pudo consultar el backend.") from exc

    if not data.get("ok", True):
        message = str(data.get("error") or data.get("mensaje") or "No se pudo completar la consulta.")
        log_error("hilorama_desktop", f"Respuesta API no exitosa: accion={action} endpoint={endpoint}")
        raise ApiReadError(_safe_message(message))
    log_info("hilorama_desktop", f"Lectura API correcta: accion={action} endpoint={endpoint}")
    return data


def normalize_collection(data: dict, primary_key: str, compatibility_key: str) -> dict:
    rows = data.get(primary_key)
    if not isinstance(rows, list):
        rows = data.get(compatibility_key)
    rows = list(rows) if isinstance(rows, list) else []
    pagination = dict(data.get("pagination") or {})
    page = _safe_int(pagination.get("page") or data.get("page"), 1)
    per_page = _safe_int(pagination.get("per_page") or data.get("per_page") or data.get("limit"), 50)
    total = _safe_int(pagination.get("total") or data.get("total"), len(rows))
    pages = _safe_int(pagination.get("pages"), (total + per_page - 1) // per_page if total else 0)
    normalized_pagination = {"page": max(1, page), "per_page": max(1, min(per_page, 100)), "total": max(0, total), "pages": max(0, pages)}
    return {"ok": True, primary_key: rows, compatibility_key: rows, "items": rows, "pagination": normalized_pagination}


def _translate_error(exc: RenderApiError) -> ApiReadError:
    status = exc.status
    message = _safe_message(str(exc))
    if status == 401:
        return SessionExpiredError("La sesion expiro. Inicia sesion nuevamente.", status=status)
    if status == 403:
        if "permiso" in message.casefold() or "rol" in message.casefold():
            return PermissionDeniedError("No tienes permiso para consultar esta informacion.", status=status)
        return PermissionDeniedError("Licencia bloqueada, suspendida o vencida.", status=status)
    if status == 404:
        return RecordNotFoundError("El registro solicitado no fue encontrado.", status=status)
    if status == 500:
        return ApiReadError("El servidor no pudo completar la consulta. Intenta nuevamente.", status=status)
    if status is None:
        return ApiReadError("Backend no disponible. Revisa tu conexion.")
    return ApiReadError(message or "No se pudo completar la consulta.", status=status)


def _positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} debe ser un entero positivo.") from exc
    if parsed < 1:
        raise ValueError(f"{field} debe ser un entero positivo.")
    return parsed


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_message(message: str) -> str:
    redacted = redact_sensitive_data(message)
    return str(redacted or "No se pudo completar la consulta.")
