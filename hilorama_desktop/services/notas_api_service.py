"""Notas/cotizaciones por API.

Permite crear y editar cotizaciones. Pagos, comprobantes y stock siguen fuera
de este servicio.
"""

try:
    from .productos_api_service import _call_api
except ImportError:
    from productos_api_service import _call_api


def _emitir_cambio_notificaciones(incluir_oportunidades=False):
    try:
        from .notificaciones_service import emitir_actualizacion_notificaciones
    except ImportError:
        try:
            from notificaciones_service import emitir_actualizacion_notificaciones
        except ImportError:
            return
    try:
        emitir_actualizacion_notificaciones(incluir_oportunidades=incluir_oportunidades)
    except Exception:
        return


def listar_notas(params=None):
    params_base = dict(params or {})
    if "limit" in params_base:
        data = _call_api(
            "listar notas",
            "/api/notas",
            lambda api, token: api.listar_notas(params_base, token=token),
        )
        return data.get("notas", [])

    notas = []
    limit = 500
    offset = 0
    total = None
    while True:
        params_pagina = dict(params_base)
        params_pagina["limit"] = limit
        params_pagina["offset"] = offset
        data = _call_api(
            "listar notas",
            "/api/notas",
            lambda api, token: api.listar_notas(params_pagina, token=token),
        )
        pagina = data.get("notas", [])
        notas.extend(pagina)
        total = data.get("total", total)
        offset += limit
        if not pagina or (total is not None and len(notas) >= int(total)):
            break
    return notas


def obtener_nota(nota_id):
    data = _call_api(
        "obtener nota",
        f"/api/notas/{nota_id}",
        lambda api, token: api.obtener_nota(nota_id, token=token),
    )
    return data.get("nota")


def obtener_items_nota(nota_id):
    data = _call_api(
        "obtener items de nota",
        f"/api/notas/{nota_id}/items",
        lambda api, token: api.obtener_items_nota(nota_id, token=token),
    )
    return data.get("items", [])


def obtener_pagos_nota(nota_id):
    data = _call_api(
        "obtener pagos de nota",
        f"/api/notas/{nota_id}/pagos",
        lambda api, token: api.obtener_pagos_nota(nota_id, token=token),
    )
    return data.get("pagos", [])


def obtener_detalle_completo_nota(nota_id):
    data = _call_api(
        "obtener detalle completo de nota",
        f"/api/notas/{nota_id}/detalle-completo",
        lambda api, token: api.obtener_detalle_completo_nota(nota_id, token=token),
    )
    nota = data.get("nota") or {}
    nota["items"] = data.get("items", nota.get("items", []))
    nota["pagos"] = data.get("pagos", nota.get("pagos", []))
    nota["cliente"] = data.get("cliente", nota.get("cliente"))
    nota["envio"] = data.get("envio", nota.get("envio", {}))
    nota["comprobante"] = data.get("comprobante", nota.get("comprobante"))
    if data.get("totales"):
        nota["totales"] = data.get("totales")
    return nota


def listar_pagos(nota_id):
    data = _call_api(
        "listar pagos",
        "/api/pagos",
        lambda api, token: api.listar_pagos({"nota_id": nota_id}, token=token),
    )
    return data.get("pagos", [])


def registrar_pago(nota_id, comprobante=None):
    payload = {
        "nota_id": nota_id,
        "comprobante": comprobante,
    }
    data = _call_api(
        "registrar pago",
        "/api/pagos",
        lambda api, token: api.registrar_pago(payload, token=token),
    )
    _emitir_cambio_notificaciones(incluir_oportunidades=True)
    return data.get("pago")


def marcar_nota_pagada(nota_id, comprobante=None, fecha_pago=None, autorizacion_stock=None):
    payload = {
        "comprobante": comprobante,
        "fecha_pago": fecha_pago,
    }
    # Clave temporal autorizada por el admin cuando hay stock bajo/insuficiente.
    # Se agrega desde la nota en notas.guardar_nota_actualizada().
    if autorizacion_stock:
        payload["autorizacion_stock"] = autorizacion_stock
    return _marcar_nota_pagada_payload(nota_id, payload)


def _marcar_nota_pagada_payload(nota_id, payload):
    data = _call_api(
        "marcar nota pagada",
        f"/api/notas/{nota_id}/pago",
        lambda api, token: api.marcar_nota_pagada(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones(incluir_oportunidades=True)
    return data.get("nota")


def guardar_comprobante_nota(nota_id, comprobante):
    payload = {"comprobante": comprobante}
    data = _call_api(
        "guardar comprobante de nota",
        f"/api/notas/{nota_id}/comprobante",
        lambda api, token: api.guardar_comprobante_nota(nota_id, payload, token=token),
    )
    return data.get("nota")


def obtener_comprobante_nota(nota_id):
    data = _call_api(
        "obtener comprobante de nota",
        f"/api/notas/{nota_id}/comprobante",
        lambda api, token: api.obtener_comprobante_nota(nota_id, token=token),
    )
    return data.get("comprobante")


def anular_nota(nota_id, autorizacion_stock=None):
    payload = {}
    if autorizacion_stock:
        payload["autorizacion_stock"] = autorizacion_stock
        payload["clave_autorizacion"] = autorizacion_stock
        payload["authorization_code"] = autorizacion_stock
    payload["motivo"] = "Anulacion administrativa de nota pagada"
    try:
        data = _call_api(
            "anular nota",
            f"/api/notas/{nota_id}/anular",
            lambda api, token: api.anular_nota(nota_id, payload, token=token),
        )
    except Exception as exc:
        mensaje = str(exc)
        if mensaje.lower().startswith("no se pudo anular"):
            raise
        raise RuntimeError(f"No se pudo anular: {mensaje}") from exc
    _emitir_cambio_notificaciones(incluir_oportunidades=True)
    return data


def buscar_nota_por_texto(texto):
    nota_id = str(texto or "").strip()
    if not nota_id:
        return None
    return obtener_nota(nota_id)


def crear_cotizacion(cliente, items, envio=None, pedido=None):
    payload = {
        "cliente": cliente or {},
        "items": list(items or []),
        "envio": envio or None,
        "pedido": pedido,
    }
    data = _call_api(
        "crear cotizacion",
        "/api/notas",
        lambda api, token: api.crear_nota(payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data.get("nota")


def convertir_a_venta(nota_id, items, cliente, envio=None, autorizacion_stock=None):
    payload = {
        "cliente": cliente or {},
        "items": list(items or []),
        "envio": envio or {},
    }
    if autorizacion_stock:
        payload["autorizacion_stock"] = autorizacion_stock
    data = _call_api(
        "convertir cotizacion a venta",
        f"/api/notas/{nota_id}/convertir-a-venta",
        lambda api, token: api.convertir_nota_a_venta(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data.get("nota")


def actualizar_nota(nota):
    nota_id = str((nota or {}).get("id") or "").strip()
    if not nota_id:
        raise ValueError("Falta id de nota.")
    payload = {
        "cliente_id": nota.get("cliente_id"),
        "cliente_nombre": nota.get("cliente_nombre"),
        "estado": nota.get("estado"),
        "total": nota.get("total"),
        "envio": nota.get("envio") or None,
        "pedido": nota.get("pedido"),
        "paqueteria": nota.get("paqueteria"),
        "observaciones": nota.get("observaciones"),
        "notas": nota.get("notas"),
    }
    data = _call_api(
        "actualizar nota",
        f"/api/notas/{nota_id}",
        lambda api, token: api.actualizar_nota(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data.get("nota")


def actualizar_nota_admin(nota_id, nota, clave_autorizacion=None):
    if not nota_id:
        raise ValueError("Falta id de nota.")
    payload = {}
    if nota.get("cliente_id") and nota.get("cliente_nombre"):
        payload["cliente_id"] = nota.get("cliente_id")
        payload["cliente_nombre"] = nota.get("cliente_nombre")
    if "envio" in nota:
        payload["envio"] = nota.get("envio") or None
    for campo in ("pedido", "paqueteria", "observaciones", "notas", "comprobante"):
        if campo in nota:
            payload[campo] = nota.get(campo)
    if clave_autorizacion:
        payload["clave_autorizacion"] = clave_autorizacion
    data = _call_api(
        "actualizar datos administrativos de nota",
        f"/api/notas/{nota_id}/admin",
        lambda api, token: api.actualizar_nota_admin(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data.get("nota")


def ajustar_items_nota_pagada_admin(
    nota_id,
    items,
    clave_autorizacion,
    envio=None,
    observaciones=None,
    comprobante=None,
    motivo=None,
):
    payload = {
        "clave_autorizacion": clave_autorizacion,
        "items": list(items or []),
        "motivo": motivo or "Ajuste administrativo de nota pagada",
    }
    if envio is not None:
        payload["envio"] = envio
        if isinstance(envio, dict):
            payload["paqueteria"] = envio.get("paqueteria") or envio.get("tipo")
    if observaciones is not None:
        payload["observaciones"] = observaciones
    if comprobante is not None:
        payload["comprobante"] = comprobante
    data = _call_api(
        "ajustar items de nota pagada",
        f"/api/notas/{nota_id}/admin-ajustar-items",
        lambda api, token: api.ajustar_items_nota_pagada_admin(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones(incluir_oportunidades=True)
    return data


def actualizar_items_nota(nota_id, items):
    payload = {"items": list(items or [])}
    data = _call_api(
        "actualizar items de nota",
        f"/api/notas/{nota_id}/items",
        lambda api, token: api.actualizar_items_nota(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data.get("nota")


def cambiar_cliente_nota(nota_id, cliente):
    payload = {
        "cliente": cliente or {},
    }
    data = _call_api(
        "cambiar cliente de nota",
        f"/api/notas/{nota_id}",
        lambda api, token: api.actualizar_nota(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones(incluir_oportunidades=True)
    return data.get("nota")


def cambiar_pedido_nota(nota_id, pedido):
    nota_id = str(nota_id or "").strip()
    if not nota_id:
        raise ValueError("Falta id de nota.")
    try:
        pedido = int(str(pedido).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("El pedido destino no es válido.") from exc
    if pedido <= 0:
        raise ValueError("El pedido destino no es válido.")

    payload = {"pedido": pedido}
    data = _call_api(
        "cambiar pedido de nota",
        f"/api/notas/{nota_id}",
        lambda api, token: api.actualizar_nota(nota_id, payload, token=token),
    )
    _emitir_cambio_notificaciones()
    return data.get("nota")
