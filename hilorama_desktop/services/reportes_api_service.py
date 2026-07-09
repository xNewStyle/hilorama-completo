"""Reportes de solo lectura por API para Hilorama Desktop."""

try:
    from .productos_api_service import _call_api
except ImportError:
    from productos_api_service import _call_api


def dashboard_empacadores(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "consultar dashboard de empacadores",
        "/api/reportes/dashboard-empacadores",
        lambda api, token: api.reporte_dashboard_empacadores(params or None, token=token),
    )
    return data.get("metricas", [])


def errores_scan(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "consultar errores de escaneo",
        "/api/reportes/errores-scan",
        lambda api, token: api.reporte_errores_scan(params or None, token=token),
    )
    return data.get("errores", [])


def ranking_empacadores(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "consultar ranking de empacadores",
        "/api/reportes/ranking-empacadores",
        lambda api, token: api.reporte_ranking_empacadores(params or None, token=token),
    )
    return data.get("ranking", [])


def dashboard_ventas(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "consultar dashboard de ventas",
        "/api/reportes/dashboard-ventas",
        lambda api, token: api.reporte_dashboard_ventas(params or None, token=token),
    )
    return data.get("dashboard", {})


def estadisticas_almacen(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "consultar estadisticas de almacen",
        "/api/reportes/estadisticas-almacen",
        lambda api, token: api.reporte_estadisticas_almacen(params or None, token=token),
    )
    return data.get("estadisticas", [])
