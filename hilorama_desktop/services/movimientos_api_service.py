"""Consultas de movimientos de almacen por API, sin acceso a base local."""

from __future__ import annotations

from typing import Any, Callable

try:
    from ..api_client.render_api_client import RenderApiClient
    from .read_api_support import call_read, normalize_collection, normalize_pagination
except ImportError:
    from api_client.render_api_client import RenderApiClient
    from services.read_api_support import call_read, normalize_collection, normalize_pagination


class MovimientosApiService:
    def __init__(self, api_client=None, session_provider: Callable[[], dict | None] | None = None):
        self.api = api_client or RenderApiClient()
        self.session_provider = session_provider

    def listar_movimientos(self, filtros: dict[str, Any] | None = None) -> dict:
        params = _prepare_params(filtros)
        data = call_read(
            action="listar movimientos de almacen",
            endpoint="/api/almacen/movimientos",
            session_provider=self.session_provider,
            api_call=lambda token: self.api.listar_movimientos_almacen(params=params, token=token),
        )
        return normalize_collection(data, "movimientos", "items")

    def listar_movimientos_producto(self, producto_id: int | str, filtros: dict[str, Any] | None = None) -> dict:
        producto_id = _positive_id(producto_id, "producto_id")
        params = _prepare_params(filtros)
        data = call_read(
            action="listar historial de producto",
            endpoint=f"/api/almacen/productos/{producto_id}/movimientos",
            session_provider=self.session_provider,
            api_call=lambda token: self.api.listar_movimientos_producto_almacen(producto_id, params=params, token=token),
        )
        return normalize_collection(data, "movimientos", "items")

    def obtener_movimiento(self, movimiento_id: int | str) -> dict:
        movimiento_id = _positive_id(movimiento_id, "movimiento_id")
        data = call_read(
            action="consultar detalle de movimiento",
            endpoint=f"/api/almacen/movimientos/{movimiento_id}",
            session_provider=self.session_provider,
            api_call=lambda token: self.api.obtener_movimiento_almacen(movimiento_id, token=token),
        )
        return dict(data.get("movimiento") or {})


def _normalize_filters(filtros: dict[str, Any] | None) -> dict[str, Any]:
    allowed = {"q", "producto", "producto_id", "codigo", "marca", "hilo", "color", "tipo", "usuario", "referencia", "desde", "hasta"}
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


def _positive_id(value: int | str, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} debe ser un entero positivo.") from exc
    if parsed < 1:
        raise ValueError(f"{field} debe ser un entero positivo.")
    return parsed
