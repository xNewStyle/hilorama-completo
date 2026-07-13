"""Envios y guias por API para Hilorama Desktop."""

try:
    from .productos_api_service import _call_api
except ImportError:
    from productos_api_service import _call_api


def listar_envios(filtros=None):
    params = dict(filtros or {})
    data = _call_api(
        "listar envios",
        "/api/envios/notas",
        lambda api, token: api.listar_envios_notas(params or None, token=token),
    )
    return data.get("envios", [])


def actualizar_envio_nota(nota_id, datos):
    payload = dict(datos or {})
    data = _call_api(
        "actualizar envio de nota",
        f"/api/envios/notas/{nota_id}",
        lambda api, token: api.actualizar_envio_nota(nota_id, payload, token=token),
    )
    return data.get("envio")


def actualizar_estado_envio(nota_id, estado, motivo=None):
    payload = {"estado_envio": estado}
    if motivo:
        payload["observaciones_envio"] = motivo
    return actualizar_envio_nota(nota_id, payload)


def marcar_envio_nota(nota_id):
    return _call_api(
        "marcar envio de nota",
        f"/api/envios/notas/{nota_id}/marcar-enviado",
        lambda api, token: api.marcar_envio_nota(nota_id, token=token),
    )
