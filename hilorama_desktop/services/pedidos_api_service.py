"""Pedidos, pedido activo y empacadores por API para Hilorama Desktop."""

try:
    from .productos_api_service import _call_api
except ImportError:
    from productos_api_service import _call_api


def listar_pedidos(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "listar pedidos",
        "/api/pedidos",
        lambda api, token: api.listar_pedidos(params or None, token=token),
    )
    return data.get("pedidos", [])


def crear_pedido(numero, desde, hasta):
    payload = {
        "numero": numero,
        "desde": desde,
        "hasta": hasta,
    }
    data = _call_api(
        "crear pedido",
        "/api/pedidos",
        lambda api, token: api.crear_pedido(payload, token=token),
    )
    return data.get("pedido")


def actualizar_pedido(numero, desde, hasta):
    payload = {
        "desde": desde,
        "hasta": hasta,
    }
    endpoint = f"/api/pedidos/{numero}"
    data = _call_api(
        "actualizar pedido",
        endpoint,
        lambda api, token: api.actualizar_pedido(numero, payload, token=token),
    )
    return data.get("pedido")


def obtener_pedido(numero):
    pedidos = listar_pedidos({"q": numero, "limit": 50})
    numero_txt = str(numero or "").strip()
    for pedido in pedidos:
        if str(pedido.get("numero") or "").strip() == numero_txt:
            return pedido
    return None


def obtener_pedido_activo():
    data = _call_api(
        "obtener pedido activo",
        "/api/pedidos/activo",
        lambda api, token: api.obtener_pedido_activo(token=token),
    )
    return data.get("pedido")


def activar_pedido(numero):
    payload = {"numero": numero}
    data = _call_api(
        "activar pedido",
        "/api/pedidos/activo",
        lambda api, token: api.activar_pedido(payload, token=token),
    )
    return data.get("pedido")


def limpiar_pedido_activo():
    return _call_api(
        "limpiar pedido activo",
        "/api/pedidos/activo",
        lambda api, token: api.limpiar_pedido_activo(token=token),
    )


def listar_empacadores(activos=True):
    params = {"activo": "true" if activos else "false"}
    data = _call_api(
        "listar empacadores",
        "/api/empacadores",
        lambda api, token: api.listar_empacadores(params, token=token),
    )
    return data.get("empacadores", [])


def listar_notas_asignacion_empacador():
    data = _call_api(
        "listar notas para asignacion",
        "/api/notas/asignacion-empacador",
        lambda api, token: api.listar_notas_asignacion_empacador(token=token),
    )
    return data.get("notas", [])


def asignar_notas_empacador(nota_ids, empacador_id):
    payload = {
        "nota_ids": list(nota_ids or []),
        "empacador_id": empacador_id,
    }
    data = _call_api(
        "asignar empacador",
        "/api/notas/asignar-empacador",
        lambda api, token: api.asignar_notas_empacador(payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data


def desasignar_notas_empacador(nota_ids):
    payload = {"nota_ids": list(nota_ids or [])}
    data = _call_api(
        "desasignar empacador",
        "/api/notas/desasignar-empacador",
        lambda api, token: api.desasignar_notas_empacador(payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data


def _emitir_cambio_notificaciones():
    try:
        from .notificaciones_service import emitir_actualizacion_notificaciones
    except ImportError:
        try:
            from notificaciones_service import emitir_actualizacion_notificaciones
        except ImportError:
            return
    try:
        emitir_actualizacion_notificaciones()
    except Exception:
        return
