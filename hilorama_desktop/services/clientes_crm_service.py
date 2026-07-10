"""Lectura del CRM comercial de clientas mediante el backend API.

No abre conexiones locales ni modifica clientes, notas, pagos o inventario.
"""

from __future__ import annotations

from typing import Any

try:
    from .productos_api_service import _call_api
except ImportError:
    from productos_api_service import _call_api


SEGMENTOS = (
    "TODAS",
    "VIP",
    "FRECUENTE",
    "ACTIVA",
    "EN_RIESGO",
    "DORMIDA",
    "NUEVA",
    "SIN_COMPRAS",
)

_MENSAJES_WHATSAPP = {
    "VIP": "Hola {nombre}, tenemos novedades que podrian interesarte para tus pedidos frecuentes. Con gusto te comparto opciones.",
    "FRECUENTE": "Hola {nombre}, vi que normalmente compras cada {frecuencia} dias. Ya tenemos novedades que pueden interesarte.",
    "ACTIVA": "Hola {nombre}, tenemos tonos y novedades que pueden gustarte para tu siguiente proyecto. Con gusto te comparto opciones.",
    "EN_RIESGO": "Hola {nombre}, tenemos novedades que podrian interesarte. Con gusto reviso opciones segun los tonos que te gustan.",
    "DORMIDA": "Hola {nombre}, hace tiempo no te vemos por aqui. Tenemos novedades y con gusto te comparto opciones para tu siguiente proyecto.",
    "NUEVA": "Hola {nombre}, esperamos que hayas disfrutado tu compra. Cuando gustes te compartimos novedades para tu siguiente proyecto.",
    "SIN_COMPRAS": "Hola {nombre}, con gusto te ayudamos a encontrar los hilos y tonos ideales para tu proyecto.",
}


def obtener_resumen(filtros: dict[str, Any] | None = None) -> dict[str, Any]:
    params = _filtros(filtros)
    data = _call_api(
        "consultar resumen comercial de clientas",
        "/api/clientes/analytics/resumen",
        lambda api, token: api.get_clientes_analytics_resumen(token=token, **params),
    )
    return _normalizar_resumen(data.get("resumen") or {})


def listar_ranking(filtros: dict[str, Any] | None = None, orden="total_comprado", limit=100) -> list[dict[str, Any]]:
    params = _filtros(filtros)
    data = _call_api(
        "consultar ranking comercial de clientas",
        "/api/clientes/analytics/ranking",
        lambda api, token: api.get_clientes_analytics_ranking(
            orden=orden,
            limit=limit,
            token=token,
            **params,
        ),
    )
    return [_normalizar_ranking(fila) for fila in data.get("ranking", [])]


def obtener_analitica_clienta(cliente_id) -> dict[str, Any]:
    data = _call_api(
        "consultar ficha comercial de clienta",
        f"/api/clientes/{cliente_id}/analytics",
        lambda api, token: api.get_cliente_analytics(cliente_id, token=token),
    )
    return _normalizar_analitica(data.get("analitica") or {})


def obtener_historial_compras(cliente_id) -> list[dict[str, Any]]:
    data = _call_api(
        "consultar historial de compras de clienta",
        f"/api/clientes/{cliente_id}/historial-compras",
        lambda api, token: api.get_cliente_historial_compras(cliente_id, token=token),
    )
    return [_normalizar_historial(fila) for fila in data.get("historial", [])]


def obtener_graficas(filtros: dict[str, Any] | None = None) -> dict[str, Any]:
    params = _filtros(filtros)
    data = _call_api(
        "consultar graficas comerciales de clientas",
        "/api/clientes/analytics/graficas",
        lambda api, token: api.get_clientes_analytics_graficas(token=token, **params),
    )
    return data.get("graficas") or _graficas_vacias()


def generar_mensaje_whatsapp(analitica: dict[str, Any] | None) -> str:
    analitica = analitica or {}
    nombre = str(analitica.get("nombre") or "").strip() or ""
    segmento = str(analitica.get("segmento") or "SIN_COMPRAS").strip().upper()
    frecuencia = analitica.get("frecuencia_promedio_dias")
    try:
        frecuencia_texto = str(max(1, round(float(frecuencia))))
    except (TypeError, ValueError):
        frecuencia_texto = "unos"
    plantilla = _MENSAJES_WHATSAPP.get(segmento, _MENSAJES_WHATSAPP["ACTIVA"])
    return plantilla.format(nombre=nombre, frecuencia=frecuencia_texto).strip()


def _filtros(filtros: dict[str, Any] | None) -> dict[str, Any]:
    filtros = dict(filtros or {})
    return {
        "desde": str(filtros.get("desde") or "").strip() or None,
        "hasta": str(filtros.get("hasta") or "").strip() or None,
        "q": str(filtros.get("q") or "").strip() or None,
        "segmento": str(filtros.get("segmento") or "").strip() or None,
    }


def _numero(valor, default=0.0):
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return default


def _entero(valor, default=0):
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return default


def _normalizar_resumen(resumen: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_clientas": _entero(resumen.get("total_clientas")),
        "clientas_activas_30d": _entero(resumen.get("clientas_activas_30d")),
        "clientas_dormidas_60d": _entero(resumen.get("clientas_dormidas_60d")),
        "clientas_vip": _entero(resumen.get("clientas_vip")),
        "venta_total_periodo": _numero(resumen.get("venta_total_periodo")),
        "ticket_promedio_general": _numero(resumen.get("ticket_promedio_general")),
        "fecha_calculo": resumen.get("fecha_calculo"),
    }


def _normalizar_ranking(fila: dict[str, Any]) -> dict[str, Any]:
    data = dict(fila or {})
    data.update({
        "cliente_id": data.get("cliente_id"),
        "nombre": str(data.get("nombre") or "Sin nombre"),
        "telefono": str(data.get("telefono") or ""),
        "total_comprado": _numero(data.get("total_comprado")),
        "numero_compras": _entero(data.get("numero_compras")),
        "ticket_promedio": _numero(data.get("ticket_promedio")),
        "frecuencia_promedio_dias": data.get("frecuencia_promedio_dias"),
        "indice_compra": _entero(data.get("indice_compra")),
        "segmento": str(data.get("segmento") or "SIN_COMPRAS"),
    })
    return data


def _normalizar_analitica(analitica: dict[str, Any]) -> dict[str, Any]:
    data = _normalizar_ranking(analitica)
    data["direccion"] = analitica.get("direccion") or (analitica.get("clienta") or {}).get("direccion") or {}
    for campo in ("primera_compra", "ultima_compra", "proxima_compra_estimada"):
        data[campo] = analitica.get(campo) or None
    data["dias_desde_ultima_compra"] = analitica.get("dias_desde_ultima_compra")
    data["marcas_favoritas"] = list(analitica.get("marcas_favoritas") or [])
    data["productos_favoritos"] = list(analitica.get("productos_favoritos") or [])
    data["alertas_comerciales"] = list(analitica.get("alertas_comerciales") or [])
    data["historial_resumido"] = list(analitica.get("historial_resumido") or [])
    return data


def _normalizar_historial(fila: dict[str, Any]) -> dict[str, Any]:
    data = dict(fila or {})
    data["folio"] = str(data.get("folio") or data.get("nota_id") or "")
    data["fecha"] = data.get("fecha") or ""
    data["total"] = _numero(data.get("total"))
    data["estado"] = str(data.get("estado") or "")
    data["productos"] = list(data.get("productos") or [])
    data["marcas"] = list(data.get("marcas") or [])
    data["cantidad_total"] = _entero(data.get("cantidad_total"))
    return data


def _graficas_vacias() -> dict[str, Any]:
    return {
        "top_clientas_por_total": [],
        "top_clientas_por_compras": [],
        "ticket_promedio_top_clientas": [],
        "clientas_nuevas_por_mes": [],
        "clientas_dormidas": [],
        "ventas_por_mes": [],
        "segmentos": [],
    }
