"""Reglas puras de presentacion y seleccion para Gestion de Envios."""

from __future__ import annotations

from collections import Counter

try:
    from ..utils.presentation import EMPTY_VALUE, format_datetime_mexico, optional_text
except ImportError:
    from utils.presentation import EMPTY_VALUE, format_datetime_mexico, optional_text


FILTROS_ENVIO = {
    "PENDIENTES DE GUÍA": "PENDIENTES_GUIA",
    "LISTAS PARA ENVIAR": "LISTAS_ENVIAR",
    "ENVIADAS": "ENVIADAS",
    "TODAS": "TODAS",
}
ESTADOS_TERMINALES_ENVIO = {"ANULADA", "CANCELADA", "ELIMINADA", "ARCHIVADA"}


def normalizar_estado_envio(valor):
    return str(valor or "").strip().upper()


def filtro_api_envios(etiqueta):
    return FILTROS_ENVIO.get(str(etiqueta or "").strip().upper(), "LISTAS_ENVIAR")


def guia_envio(nota):
    envio = nota.get("envio") if isinstance(nota, dict) else {}
    if not isinstance(envio, dict):
        envio = {}
    return str(
        (nota or {}).get("guia")
        or envio.get("guia")
        or envio.get("numero_guia")
        or ""
    ).strip()


def requiere_guia_envio(nota):
    return bool((nota or {}).get("requiere_guia", True))


def estado_operativo_envio(nota):
    """Devuelve una etiqueta visual sin crear estados comerciales nuevos."""
    nota = nota or {}
    estado = normalizar_estado_envio(nota.get("estado"))
    if estado == "ENVIADO":
        return "ENVIADO"
    if estado == "COMPLETA":
        if requiere_guia_envio(nota) and not guia_envio(nota):
            return "PENDIENTE DE GUÍA"
        return "LISTO PARA ENVIAR"
    return estado or "SIN ESTADO"


def resumir_panel_envios(notas):
    resumen = {
        "visibles": 0,
        "pendientes_guia": 0,
        "listas_enviar": 0,
        "enviadas": 0,
    }
    for nota in list(notas or []):
        resumen["visibles"] += 1
        situacion = estado_operativo_envio(nota)
        if situacion == "PENDIENTE DE GUÍA":
            resumen["pendientes_guia"] += 1
        elif situacion == "LISTO PARA ENVIAR":
            resumen["listas_enviar"] += 1
        elif situacion == "ENVIADO":
            resumen["enviadas"] += 1
    return resumen


def coincide_filtro_envio(nota, filtro):
    estado = normalizar_estado_envio((nota or {}).get("estado"))
    tiene_guia = bool(guia_envio(nota or {}))
    requiere_guia = requiere_guia_envio(nota or {})
    etiqueta = str(filtro or "").strip().upper()
    filtro = FILTROS_ENVIO.get(etiqueta, etiqueta)
    if filtro == "PENDIENTES_GUIA":
        return estado == "COMPLETA" and requiere_guia and not tiene_guia
    if filtro == "LISTAS_ENVIAR":
        return estado == "COMPLETA" and (tiene_guia or not requiere_guia)
    if filtro == "ENVIADAS":
        return estado == "ENVIADO"
    if filtro == "TODAS":
        return estado in {"COMPLETA", "ENVIADO"}
    return False


def filtrar_envios(notas, filtro):
    return [nota for nota in list(notas or []) if coincide_filtro_envio(nota, filtro)]


def buscar_envios(notas, texto, campo):
    consulta = str(texto or "").strip().casefold()
    if not consulta:
        return list(notas or [])
    campos = {
        "nota": ("id", "nota_id", "folio"),
        "cliente": ("cliente_nombre", "cliente"),
        "telefono": ("telefono",),
        "pedido": ("pedido",),
    }
    llaves = campos.get(str(campo or "").strip().lower(), ("id", "nota_id", "folio"))
    resultado = []
    for nota in notas or []:
        if any(consulta in str(nota.get(llave) or "").casefold() for llave in llaves):
            resultado.append(nota)
    return resultado


def clasificar_seleccion_envios(notas):
    validos = []
    invalidos = []
    for nota in list(notas or []):
        estado = normalizar_estado_envio(nota.get("estado"))
        if estado == "ENVIADO":
            invalidos.append({"nota": nota, "categoria": "YA_ENVIADO", "error": "Ya estaba enviado."})
        elif estado in ESTADOS_TERMINALES_ENVIO:
            invalidos.append({"nota": nota, "categoria": "TERMINAL", "error": f"Estado {estado}."})
        elif estado != "COMPLETA":
            invalidos.append({
                "nota": nota,
                "categoria": "ESTADO_INVALIDO",
                "error": f"Estado {estado or 'SIN ESTADO'}.",
            })
        elif requiere_guia_envio(nota) and not guia_envio(nota):
            invalidos.append({"nota": nota, "categoria": "SIN_GUIA", "error": "No tiene guía."})
        else:
            validos.append(nota)
    return {
        "validos": validos,
        "invalidos": invalidos,
        "motivos": dict(Counter(item["categoria"] for item in invalidos)),
    }


def resumir_seleccion_envios(notas):
    seleccion = list(notas or [])
    clasificacion = clasificar_seleccion_envios(seleccion)
    con_guia = sum(bool(guia_envio(nota)) for nota in seleccion)
    enviados = sum(normalizar_estado_envio(nota.get("estado")) == "ENVIADO" for nota in seleccion)
    return {
        "seleccionados": len(seleccion),
        "con_guia": con_guia,
        "sin_guia": len(seleccion) - con_guia,
        "ya_enviados": enviados,
        "listos": len(clasificacion["validos"]),
    }


def formatear_fecha_envio(valor):
    texto = format_datetime_mexico(valor)
    if texto == EMPTY_VALUE:
        return EMPTY_VALUE
    partes = texto.split()
    return " ".join(partes[:2]) if len(partes) >= 2 else texto


def texto_envio(valor):
    return optional_text(valor)


def texto_cantidad(valor):
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return "0"
    return str(int(numero)) if numero.is_integer() else f"{numero:g}"
