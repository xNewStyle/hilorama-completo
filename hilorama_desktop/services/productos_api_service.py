"""Lecturas de productos por API para Hilorama Desktop.

Este servicio solo consulta datos. No modifica stock, notas, pagos ni ventas.
"""

import copy
import time

try:
    from ..api_client.render_api_client import RenderApiClient, RenderApiError
    from ..config import RENDER_API_BASE_URL
    from ..security.local_secure_store import LocalSecureStore
    from ..utils.logger import log_error, log_info
except ImportError:
    from api_client.render_api_client import RenderApiClient, RenderApiError
    from config import RENDER_API_BASE_URL
    from security.local_secure_store import LocalSecureStore
    from utils.logger import log_error, log_info


class ProductosApiError(Exception):
    pass


_CACHE_VISUAL_TTL_SEGUNDOS = 180
_cache_visual = {}
_CAMPOS_PRODUCTO_EDITABLES_API = {
    "color",
    "codigo_barras",
    "costo_neto",
    "precio",
    "volumetrico",
    "tipo_producto",
    "estado",
}


def _clave_cache_visual(nombre, params=None):
    if not params:
        params_key = ()
    else:
        params_key = tuple(sorted((str(k), str(v)) for k, v in dict(params).items()))
    return nombre, params_key


def _cache_visual_get(nombre, params=None):
    clave = _clave_cache_visual(nombre, params)
    item = _cache_visual.get(clave)
    if not item:
        return None
    creado, valor = item
    if time.time() - creado > _CACHE_VISUAL_TTL_SEGUNDOS:
        _cache_visual.pop(clave, None)
        return None
    return copy.deepcopy(valor)


def _cache_visual_set(nombre, params, valor):
    _cache_visual[_clave_cache_visual(nombre, params)] = (time.time(), copy.deepcopy(valor))
    return valor


def limpiar_cache_visual():
    _cache_visual.clear()


def listar_productos(params=None):
    cache = _cache_visual_get("listar_productos", params)
    if cache is not None:
        return cache
    data = _call_api(
        "listar productos",
        "/api/productos",
        lambda api, token: api.listar_productos(params or {}, token=token),
    )
    return _cache_visual_set("listar_productos", params, data.get("productos", []))


def listar_todos_los_productos(params=None):
    cache = _cache_visual_get("listar_todos_los_productos", params)
    if cache is not None:
        return cache
    params_base = dict(params or {})
    limit = int(params_base.get("limit") or 500)
    limit = max(1, min(limit, 500))
    offset = int(params_base.get("offset") or 0)

    productos = []
    total = None
    while True:
        params_pagina = dict(params_base)
        params_pagina["limit"] = limit
        params_pagina["offset"] = offset
        data = _call_api(
            "listar todos los productos",
            "/api/productos",
            lambda api, token: api.listar_productos(params_pagina, token=token),
        )
        pagina = data.get("productos", [])
        productos.extend(pagina)
        total = data.get("total", total)
        offset += limit
        if not pagina or (total is not None and len(productos) >= int(total)):
            break
    return _cache_visual_set("listar_todos_los_productos", params, productos)


def obtener_producto(producto_id):
    data = _call_api(
        "obtener producto",
        f"/api/productos/{producto_id}",
        lambda api, token: api.obtener_producto(producto_id, token=token),
    )
    return data.get("producto")


def obtener_producto_por_codigo(codigo):
    data = _call_api(
        "obtener producto por codigo",
        f"/api/productos/codigo/{codigo}",
        lambda api, token: api.obtener_producto_por_codigo(codigo, token=token),
    )
    return data.get("producto")


def obtener_producto_por_codigo_barras(codigo):
    return obtener_producto_por_codigo(codigo)


def obtener_producto_por_marca_hilo_codigo(marca, hilo, codigo):
    params = {
        "marca": marca,
        "hilo": hilo,
        "codigo": codigo,
        "limit": 1,
        "incluir_items_cotizacion": "true",
    }
    data = _call_api(
        "obtener producto exacto",
        "/api/productos",
        lambda api, token: api.listar_productos(params, token=token),
    )
    productos = data.get("productos", [])
    return productos[0] if productos else None


def listar_marcas():
    cache = _cache_visual_get("listar_marcas")
    if cache is not None:
        return cache
    data = _call_api("listar marcas", "/api/marcas", lambda api, token: api.listar_marcas(token=token))
    return _cache_visual_set("listar_marcas", None, data.get("marcas", []))


def listar_hilos(marca=None):
    params_cache = {"marca": marca} if marca else None
    cache = _cache_visual_get("listar_hilos", params_cache)
    if cache is not None:
        return cache
    data = _call_api("listar hilos", "/api/hilos", lambda api, token: api.listar_hilos(marca=marca, token=token))
    return _cache_visual_set("listar_hilos", params_cache, data.get("hilos", []))


def obtener_resumen_almacen():
    return _call_api(
        "obtener resumen de almacen",
        "/api/almacen/resumen",
        lambda api, token: api.obtener_resumen_almacen(token=token),
    )


def listar_movimientos_almacen(filtros=None):
    params = dict(filtros or {})
    return _call_api(
        "listar movimientos de almacen",
        "/api/almacen/movimientos",
        lambda api, token: api.listar_movimientos_almacen(params, token=token),
    )


def listar_movimientos_producto_almacen(producto_id, filtros=None):
    if not producto_id:
        raise ProductosApiError("Seleccione un producto para consultar su historial.")
    params = dict(filtros or {})
    return _call_api(
        "consultar historial de producto",
        f"/api/almacen/productos/{producto_id}/movimientos",
        lambda api, token: api.listar_movimientos_producto_almacen(
            producto_id,
            params=params,
            token=token,
        ),
    )


def obtener_movimiento_almacen(movimiento_id):
    if not movimiento_id:
        raise ProductosApiError("Seleccione un movimiento para ver su detalle.")
    data = _call_api(
        "consultar detalle de movimiento",
        f"/api/almacen/movimientos/{movimiento_id}",
        lambda api, token: api.obtener_movimiento_almacen(movimiento_id, token=token),
    )
    return data.get("movimiento") or {}


def listar_precios(params=None):
    cache = _cache_visual_get("listar_precios", params)
    if cache is not None:
        return cache
    data = _call_api(
        "listar precios",
        "/api/precios",
        lambda api, token: api.listar_precios(params or {}, token=token),
    )
    return _cache_visual_set("listar_precios", params, data.get("precios", []))


def obtener_precios_marca(marca):
    cache = _cache_visual_get("obtener_precios_marca", {"marca": marca})
    if cache is not None:
        return cache
    data = _call_api(
        "obtener precios por marca",
        f"/api/precios/marca/{marca}",
        lambda api, token: api.obtener_precios_marca(marca, token=token),
    )
    return _cache_visual_set("obtener_precios_marca", {"marca": marca}, data.get("precios", []))


def obtener_precio_venta(marca=None, hilo=None, codigo=None):
    data = _obtener_precio_producto(marca=marca, hilo=hilo, codigo=codigo)
    return data.get("precio_venta") or 0


def obtener_precio_distribuidor(marca=None, hilo=None, codigo=None):
    data = _obtener_precio_producto(marca=marca, hilo=hilo, codigo=codigo)
    return data.get("precio_distribuidor") or data.get("costo_neto") or 0


def _obtener_precio_producto(marca=None, hilo=None, codigo=None):
    params = {"marca": marca, "hilo": hilo, "codigo": codigo}
    cache = _cache_visual_get("obtener_precio_producto", params)
    if cache is not None:
        return cache
    data = _call_api(
        "obtener precio de producto",
        "/api/precios/producto",
        lambda api, token: api.obtener_precio_producto(
            marca=marca,
            hilo=hilo,
            codigo=codigo,
            token=token,
        ),
    )
    return _cache_visual_set("obtener_precio_producto", params, data)


def actualizar_producto(producto_id, cambios, motivo=None):
    if not producto_id:
        raise ProductosApiError("No se encontro el id del producto para editarlo por API.")
    cambios = dict(cambios or {})
    if len(cambios) != 1:
        raise ProductosApiError("Solo se permite editar un campo de producto por vez.")
    campo, valor = next(iter(cambios.items()))
    if campo not in _CAMPOS_PRODUCTO_EDITABLES_API:
        raise ProductosApiError(f"El campo {campo} no esta disponible para edicion por API.")
    payload = {
        "campo": campo,
        "valor": valor,
        "motivo": motivo or "Edicion manual desde Almacen",
    }
    data = _call_api(
        "actualizar producto de almacen",
        f"/api/almacen/productos/{producto_id}",
        lambda api, token: api.actualizar_producto_almacen(producto_id, payload, token=token),
    )
    limpiar_cache_visual()
    return data.get("producto")


def actualizar_stock_producto(producto_id, stock_nuevo, motivo=None, clave_autorizacion=None):
    if not producto_id:
        raise ProductosApiError("No se encontro el id del producto para actualizar stock por API.")
    payload = {
        "stock_nuevo": stock_nuevo,
        "motivo": motivo or "Ajuste manual de stock desde Almacen",
    }
    if clave_autorizacion:
        payload["clave_autorizacion"] = clave_autorizacion
    data = _call_api(
        "actualizar stock de producto",
        f"/api/almacen/productos/{producto_id}/stock",
        lambda api, token: api.actualizar_stock_producto_almacen(producto_id, payload, token=token),
    )
    limpiar_cache_visual()
    return data.get("producto")


def actualizar_tipo_producto(producto_id, tipo_producto, es_inventariable, stock_inicial=None, motivo=None):
    if not producto_id:
        raise ProductosApiError("No se encontro el id del producto para cambiar tipo por API.")
    payload = {
        "tipo_producto": tipo_producto,
        "es_inventariable": bool(es_inventariable),
        "motivo": motivo or "Cambio de tipo de producto desde Almacen",
    }
    if stock_inicial is not None:
        payload["stock_inicial"] = stock_inicial
    data = _call_api(
        "cambiar tipo de producto",
        f"/api/almacen/productos/{producto_id}/tipo",
        lambda api, token: api.actualizar_tipo_producto_almacen(producto_id, payload, token=token),
    )
    limpiar_cache_visual()
    return data.get("producto")


def anular_producto(producto_id, clave_autorizacion, motivo=None):
    if not producto_id:
        raise ProductosApiError("No se encontro el id del producto para anular por API.")
    payload = {
        "clave_autorizacion": clave_autorizacion,
        "motivo": motivo or "Anulacion de tono desde Almacen",
    }
    data = _call_api(
        "anular producto",
        f"/api/almacen/productos/{producto_id}/anular",
        lambda api, token: api.anular_producto_almacen(producto_id, payload, token=token),
    )
    limpiar_cache_visual()
    return data


def actualizar_precio_marca(marca, distribuidor, venta, motivo=None):
    payload = {
        "distribuidor": distribuidor,
        "venta": venta,
        "motivo": motivo or "Actualizacion masiva de precio por marca",
    }
    data = _call_api(
        "actualizar precio por marca",
        f"/api/almacen/precios/marca/{marca}",
        lambda api, token: api.actualizar_precio_marca_almacen(marca, payload, token=token),
    )
    limpiar_cache_visual()
    return data


def actualizar_precio_hilo(marca, hilo, precio, motivo=None):
    payload = {
        "marca": marca,
        "hilo": hilo,
        "precio": precio,
        "motivo": motivo or "Actualizacion masiva de precio por hilo",
    }
    data = _call_api(
        "actualizar precio por hilo",
        "/api/almacen/precios/hilo",
        lambda api, token: api.actualizar_precio_hilo_almacen(payload, token=token),
    )
    limpiar_cache_visual()
    return data


def actualizar_volumetrico_hilo(marca, hilo, volumetrico, motivo=None):
    payload = {
        "marca": marca,
        "hilo": hilo,
        "volumetrico": volumetrico,
        "motivo": motivo or "Actualizacion masiva de volumetrico por hilo",
    }
    data = _call_api(
        "actualizar volumetrico por hilo",
        "/api/almacen/volumetrico/hilo",
        lambda api, token: api.actualizar_volumetrico_hilo_almacen(payload, token=token),
    )
    limpiar_cache_visual()
    return data


def actualizar_volumetrico_multiple(items, motivo=None):
    payload = {
        "items": list(items or []),
        "motivo": motivo or "Actualizacion multiple de volumetrico",
    }
    data = _call_api(
        "actualizar volumetrico multiple",
        "/api/almacen/volumetrico/multiple",
        lambda api, token: api.actualizar_volumetrico_multiple_almacen(payload, token=token),
    )
    limpiar_cache_visual()
    return data


def crear_producto(datos):
    payload = dict(datos or {})
    data = _call_api(
        "crear producto de almacen",
        "/api/almacen/productos",
        lambda api, token: api.crear_producto_almacen(payload, token=token),
    )
    limpiar_cache_visual()
    return data.get("producto")


def _call_api(accion, endpoint, callback):
    inicio = time.perf_counter()
    session = _session_actual()
    token = _extraer_token(session)
    api = RenderApiClient()
    try:
        data = callback(api, token)
    except RenderApiError as exc:
        mensaje = _mensaje_controlado(exc)
        _registrar_diagnostico_api(accion, endpoint, api, session, exc, mensaje)
        raise ProductosApiError(mensaje) from exc
    except Exception as exc:
        log_error(
            "hilorama_desktop",
            f"Error inesperado al {accion} por API | {_resumen_contexto_api(endpoint, api, session)}",
            exc,
        )
        raise ProductosApiError(f"No se pudo {accion}.") from exc

    if not data.get("ok", True):
        mensaje = data.get("error") or data.get("mensaje") or f"No se pudo {accion}."
        log_error(
            "hilorama_desktop",
            f"Respuesta API no exitosa al {accion}: {mensaje} | {_resumen_contexto_api(endpoint, api, session)}",
        )
        raise ProductosApiError(mensaje)
    duracion = time.perf_counter() - inicio
    log_info("hilorama_desktop", f"API {accion} {endpoint}: {duracion:.2f}s")
    return data


def _session_actual():
    session = LocalSecureStore().load()
    if not session:
        raise ProductosApiError("Modo API requiere login real con backend. No hay sesion activa.")
    if _es_sesion_dev(session):
        raise ProductosApiError(
            "Modo API requiere login real con backend. El bypass de desarrollo no genera token."
        )
    token = _extraer_token(session)
    if not token:
        raise ProductosApiError("Modo API requiere login real con backend. No hay token de sesion.")
    return session


def _extraer_token(session):
    if not session:
        return None
    for campo in ("token", "access_token", "session_token", "auth_token"):
        valor = session.get(campo)
        if valor:
            return valor
    return None


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


def _mensaje_controlado(exc):
    if exc.status == 401:
        return "No autorizado. Revisa sesion o token."
    if exc.status == 403:
        return "Licencia bloqueada, suspendida o vencida."
    texto = str(exc)
    if not RENDER_API_BASE_URL:
        return "Falta HILORAMA_RENDER_API_BASE_URL."
    if "Backend no disponible" in texto or exc.status is None:
        return "Backend no disponible."
    return texto or "No se pudo consultar el backend."


def _registrar_diagnostico_api(accion, endpoint, api, session, exc, mensaje):
    log_error(
        "hilorama_desktop",
        (
            f"Error API al {accion}: {mensaje} | "
            f"status={exc.status or 'sin_status'} | "
            f"{_resumen_contexto_api(endpoint, api, session)}"
        ),
        exc,
    )


def _resumen_contexto_api(endpoint, api, session):
    usuario = session.get("usuario") or {}
    rol = usuario.get("rol") or "sin_rol"
    nombre = usuario.get("usuario") or usuario.get("nombre") or "sin_usuario"
    return (
        f"url_backend={api.base_url or 'sin_url'} | "
        f"endpoint={endpoint} | "
        f"token_presente={'si' if _extraer_token(session) else 'no'} | "
        f"usuario={nombre} | rol={rol}"
    )
