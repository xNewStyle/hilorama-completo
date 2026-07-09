"""Clientes por API.

Permite consulta y creación mínima de cliente para guardar cotizaciones.
"""

try:
    from .productos_api_service import _call_api
except ImportError:
    from productos_api_service import _call_api


def listar_clientes(params=None):
    params_base = dict(params or {})
    if "limit" in params_base:
        data = _call_api(
            "listar clientes",
            "/api/clientes",
            lambda api, token: api.listar_clientes(params_base, token=token),
        )
        return data.get("clientes", [])

    clientes = []
    limit = 500
    offset = 0
    total = None
    while True:
        params_pagina = dict(params_base)
        params_pagina["limit"] = limit
        params_pagina["offset"] = offset
        data = _call_api(
            "listar clientes",
            "/api/clientes",
            lambda api, token: api.listar_clientes(params_pagina, token=token),
        )
        pagina = data.get("clientes", [])
        clientes.extend(pagina)
        total = data.get("total", total)
        offset += limit
        if not pagina or (total is not None and len(clientes) >= int(total)):
            break
    return clientes


def obtener_cliente(cliente_id):
    data = _call_api(
        "obtener cliente",
        f"/api/clientes/{cliente_id}",
        lambda api, token: api.obtener_cliente(cliente_id, token=token),
    )
    return data.get("cliente")


def crear_cliente(nombre, telefono="", direccion=None):
    payload = {
        "nombre": nombre,
        "telefono": telefono or "",
        "direccion": direccion or {},
    }
    data = _call_api(
        "crear cliente",
        "/api/clientes",
        lambda api, token: api.crear_cliente(payload, token=token),
    )
    return data.get("cliente")


def actualizar_cliente(cliente_id, cliente):
    payload = {
        "nombre": cliente.get("nombre", ""),
        "telefono": cliente.get("telefono", ""),
        "direccion": cliente.get("direccion") or {},
    }
    data = _call_api(
        "actualizar cliente",
        f"/api/clientes/{cliente_id}",
        lambda api, token: api.actualizar_cliente(cliente_id, payload, token=token),
    )
    return data.get("cliente")


def buscar_clientes(params=None):
    data = _call_api(
        "buscar clientes",
        "/api/clientes/buscar",
        lambda api, token: api.buscar_clientes(params or {}, token=token),
    )
    return data.get("clientes", [])


def buscar_cliente_por_telefono(telefono):
    clientes = buscar_clientes({"telefono": telefono, "limit": 1})
    return clientes[0] if clientes else None
