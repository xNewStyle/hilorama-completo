"""Cliente y cache visual de la campana de notificaciones Desktop."""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable

try:
    from .productos_api_service import _call_api
    from ..utils.logger import log_error
except ImportError:
    from productos_api_service import _call_api
    from utils.logger import log_error


_lock = threading.RLock()
_ultimo_resumen: dict[str, Any] | None = None
_cache_generation = 0
_listeners: set[Callable[[bool], None]] = set()


def _seccion_vacia() -> dict[str, Any]:
    return {"total": 0, "categorias": {}, "notificaciones": []}


def resumen_vacio() -> dict[str, Any]:
    return {
        "ok": True,
        "total": 0,
        "urgentes": 0,
        "atencion": 0,
        "normales": 0,
        "operacion": _seccion_vacia(),
        "oportunidades": _seccion_vacia(),
        "oportunidades_actualizadas": False,
        "generado_en": None,
    }


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _normalizar_aviso(aviso: dict[str, Any], seccion: str) -> dict[str, Any] | None:
    data = dict(aviso or {})
    key = _texto(data.get("key") or data.get("id"))
    if not key:
        return None
    data["id"] = key
    data["key"] = key
    data["seccion"] = _texto(data.get("seccion") or seccion).upper()
    data["categoria"] = _texto(data.get("categoria") or "OTRA").upper()
    prioridad = _texto(data.get("prioridad") or "NORMAL").upper()
    data["prioridad"] = prioridad if prioridad in {"URGENTE", "ATENCION", "NORMAL"} else "NORMAL"
    data["titulo"] = _texto(data.get("titulo") or "Notificación")
    data["mensaje"] = _texto(data.get("mensaje"))
    data["accion_texto"] = _texto(data.get("accion_texto") or "Abrir")
    data["metadata"] = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    acciones = data.get("acciones_secundarias")
    data["acciones_secundarias"] = acciones if isinstance(acciones, list) else []
    return data


def _normalizar_seccion(data: Any, nombre: str) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    unicos = {}
    for aviso in data.get("notificaciones") or []:
        normalizado = _normalizar_aviso(aviso, nombre)
        if normalizado and normalizado["key"] not in unicos:
            unicos[normalizado["key"]] = normalizado
    notificaciones = list(unicos.values())
    categorias = {}
    for aviso in notificaciones:
        categoria = aviso["categoria"]
        categorias[categoria] = categorias.get(categoria, 0) + 1
    return {
        "total": len(notificaciones),
        "categorias": categorias,
        "notificaciones": notificaciones,
    }


def normalizar_resumen(data: Any) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    operacion = _normalizar_seccion(data.get("operacion"), "OPERACION")
    oportunidades = _normalizar_seccion(data.get("oportunidades"), "OPORTUNIDADES")
    avisos = operacion["notificaciones"] + oportunidades["notificaciones"]
    return {
        "ok": bool(data.get("ok", True)),
        "total": len(avisos),
        "urgentes": sum(1 for aviso in avisos if aviso["prioridad"] == "URGENTE"),
        "atencion": sum(1 for aviso in avisos if aviso["prioridad"] == "ATENCION"),
        "normales": sum(1 for aviso in avisos if aviso["prioridad"] == "NORMAL"),
        "operacion": operacion,
        "oportunidades": oportunidades,
        "oportunidades_actualizadas": bool(data.get("oportunidades_actualizadas", True)),
        "generado_en": data.get("generado_en"),
    }


def _combinar_oportunidades_previas(nuevo: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        anterior = copy.deepcopy(_ultimo_resumen)
    if nuevo.get("oportunidades_actualizadas") or not anterior:
        return nuevo
    combinado = dict(nuevo)
    combinado["oportunidades"] = anterior.get("oportunidades") or _seccion_vacia()
    combinado["oportunidades_actualizadas"] = False
    return normalizar_resumen(combinado)


def obtener_resumen(incluir_oportunidades=True) -> dict[str, Any]:
    global _ultimo_resumen
    with _lock:
        generation = _cache_generation
    data = _call_api(
        "consultar notificaciones",
        "/api/notificaciones/resumen",
        lambda api, token: api.obtener_resumen_notificaciones(
            incluir_oportunidades=incluir_oportunidades,
            token=token,
        ),
    )
    resumen = _combinar_oportunidades_previas(normalizar_resumen(data))
    with _lock:
        if generation == _cache_generation:
            _ultimo_resumen = copy.deepcopy(resumen)
    return resumen


def obtener_ultimo_resumen() -> dict[str, Any]:
    with _lock:
        return copy.deepcopy(_ultimo_resumen or resumen_vacio())


def invalidar_cache_sesion() -> None:
    """Impide que una respuesta de la sesión cerrada alimente la siguiente."""
    global _ultimo_resumen, _cache_generation
    with _lock:
        _cache_generation += 1
        _ultimo_resumen = None


def controlar_oportunidad(cliente_id, categoria, accion) -> dict[str, Any]:
    payload = {
        "categoria": _texto(categoria).upper(),
        "accion": _texto(accion).upper(),
    }
    data = _call_api(
        "guardar recordatorio de oportunidad",
        f"/api/notificaciones/oportunidades/{cliente_id}/control",
        lambda api, token: api.controlar_oportunidad_notificacion(
            cliente_id,
            payload,
            token=token,
        ),
    )
    _quitar_oportunidad_cache(cliente_id, payload["categoria"])
    emitir_actualizacion_notificaciones(incluir_oportunidades=True)
    return data.get("control") or {}


def _quitar_oportunidad_cache(cliente_id, categoria):
    with _lock:
        global _ultimo_resumen
        if not _ultimo_resumen:
            return
        resumen = copy.deepcopy(_ultimo_resumen)
        avisos = [
            aviso
            for aviso in resumen.get("oportunidades", {}).get("notificaciones", [])
            if not (
                str(aviso.get("cliente_id")) == str(cliente_id)
                and _texto(aviso.get("categoria")).upper() == _texto(categoria).upper()
            )
        ]
        resumen["oportunidades"] = {"notificaciones": avisos}
        _ultimo_resumen = normalizar_resumen(resumen)


def preparar_mensaje(aviso: dict[str, Any]) -> str:
    metadata = aviso.get("metadata") if isinstance(aviso.get("metadata"), dict) else {}
    sugerido = _texto(metadata.get("mensaje_sugerido"))
    if sugerido:
        return sugerido
    nombre = _texto(aviso.get("cliente_nombre"))
    nombre_corto = nombre.split()[0] if nombre else "Hola"
    if _texto(aviso.get("categoria")).upper() == "PENDIENTE_PAGO":
        folio = _texto(aviso.get("folio"))
        referencia = f" de tu pedido {folio}" if folio else " de tu pedido"
        return (
            f"Hola, {nombre_corto}. Te escribimos para dar seguimiento al pago{referencia}. "
            "Si necesitas que te compartamos nuevamente los datos, con gusto te ayudamos."
        )
    if _texto(aviso.get("categoria")).upper() == "DORMIDA":
        return (
            f"Hola, {nombre_corto}. Hace tiempo que no realizas un pedido con nosotros y "
            "queríamos saludarte. ¿Te gustaría que te enviemos opciones disponibles?"
        )
    return (
        f"Hola, {nombre_corto}. Te escribimos para saber si próximamente necesitarás más "
        "material. Puedo mostrarte los tonos disponibles."
    )


def registrar_listener_notificaciones(callback: Callable[[bool], None]) -> None:
    with _lock:
        _listeners.add(callback)


def quitar_listener_notificaciones(callback: Callable[[bool], None]) -> None:
    with _lock:
        _listeners.discard(callback)


def emitir_actualizacion_notificaciones(incluir_oportunidades=False) -> None:
    with _lock:
        listeners = list(_listeners)
    for callback in listeners:
        try:
            callback(bool(incluir_oportunidades))
        except Exception as exc:
            log_error("hilorama_desktop", "No se pudo notificar un cambio a la campana", exc)
