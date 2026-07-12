"""Consultas de auditoria general por API para Administracion."""

from __future__ import annotations

from typing import Any, Callable

try:
    from ..api_client.render_api_client import RenderApiClient
    from .read_api_support import call_read, normalize_collection, normalize_pagination
except ImportError:
    from api_client.render_api_client import RenderApiClient
    from services.read_api_support import call_read, normalize_collection, normalize_pagination


class AuditoriaApiService:
    def __init__(self, api_client=None, session_provider: Callable[[], dict | None] | None = None):
        self.api = api_client or RenderApiClient()
        self.session_provider = session_provider

    def listar_auditoria(self, filtros: dict[str, Any] | None = None) -> dict:
        params = _prepare_params(filtros)
        data = call_read(
            action="listar auditoria general",
            endpoint="/api/admin/auditoria-general",
            session_provider=self.session_provider,
            api_call=lambda token: self.api.listar_auditoria_general(params=params, token=token),
        )
        return normalize_collection(data, "auditoria", "items")

    def obtener_auditoria(self, auditoria_id: int | str) -> dict:
        auditoria_id = _positive_id(auditoria_id)
        data = call_read(
            action="consultar detalle de auditoria",
            endpoint=f"/api/admin/auditoria/{auditoria_id}",
            session_provider=self.session_provider,
            api_call=lambda token: self.api.obtener_auditoria_general(auditoria_id, token=token),
        )
        return dict(data.get("auditoria") or {})


def _normalize_filters(filtros: dict[str, Any] | None) -> dict[str, Any]:
    allowed = {"q", "texto", "modulo", "accion", "resultado", "usuario", "cliente", "entidad", "desde", "hasta"}
    return {
        key: str(value).strip()
        for key, value in dict(filtros or {}).items()
        if key in allowed and value not in (None, "") and str(value).strip()
    }


def _prepare_params(filtros: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(filtros or {})
    params = _normalize_filters(raw)
    for key in ("page", "per_page", "limit", "offset"):
        if key in raw:
            params[key] = raw[key]
    return normalize_pagination(params)


def _positive_id(value: int | str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("auditoria_id debe ser un entero positivo.") from exc
    if parsed < 1:
        raise ValueError("auditoria_id debe ser un entero positivo.")
    return parsed
