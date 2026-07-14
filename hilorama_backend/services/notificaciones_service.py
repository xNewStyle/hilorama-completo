"""Deteccion pura de pendientes y oportunidades para la campana Desktop.

El modulo no abre conexiones ni modifica datos. Recibe filas ya consultadas
por el backend y devuelve un contrato estable, deduplicable y facil de probar.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Iterable


PRIORIDAD_URGENTE = "URGENTE"
PRIORIDAD_ATENCION = "ATENCION"
PRIORIDAD_NORMAL = "NORMAL"
ORDEN_PRIORIDAD = {
    PRIORIDAD_URGENTE: 0,
    PRIORIDAD_ATENCION: 1,
    PRIORIDAD_NORMAL: 2,
}

ESTADOS_TERMINALES = {"ANULADA", "CANCELADA", "ELIMINADA", "ARCHIVADA"}
ESTADOS_EMPAQUE_ACTIVO = {"PAGADA", "EN_PROCESO", "INCOMPLETA"}
ESTADOS_ENTREGA_LOCAL = {
    "RECOLECCION",
    "RECOGER",
    "RECOGE",
    "ENTREGA LOCAL",
    "LOCAL",
    "EN TIENDA",
    "PERSONAL",
    "SIN ENVIO",
    "SIN PAQUETERIA",
}

ORDEN_OPORTUNIDADES = {
    "VIP_RECUPERAR": 0,
    "RECURRENTE_ATRASADA": 1,
    "PROXIMA_COMPRA": 2,
    "ATRASADA": 3,
    "DORMIDA": 4,
}


def normalizar_estado(valor: Any) -> str:
    return str(valor or "").strip().upper().replace("Ó", "O")


def parsear_fecha(valor: Any) -> datetime | None:
    if isinstance(valor, datetime):
        fecha = valor
    elif isinstance(valor, date):
        fecha = datetime.combine(valor, datetime.min.time())
    elif valor:
        texto = str(valor).strip().replace("Z", "+00:00")
        try:
            fecha = datetime.fromisoformat(texto)
        except ValueError:
            fecha = None
            for formato in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y",
            ):
                try:
                    fecha = datetime.strptime(texto[:19], formato)
                    break
                except ValueError:
                    continue
            if fecha is None:
                return None
    else:
        return None

    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


def _ahora_naive(ahora: datetime | None) -> datetime:
    valor = ahora or datetime.now(timezone.utc)
    if valor.tzinfo is not None:
        valor = valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def _fecha_iso(valor: Any) -> str | None:
    fecha = parsear_fecha(valor)
    return fecha.isoformat(timespec="seconds") if fecha else None


def _numero(valor: Any, default: float = 0.0) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return default


def _entero(valor: Any, default: int = 0) -> int:
    try:
        return int(round(float(valor or 0)))
    except (TypeError, ValueError):
        return default


def _horas_transcurridas(fecha: Any, ahora: datetime) -> float | None:
    referencia = parsear_fecha(fecha)
    if referencia is None:
        return None
    return max((ahora - referencia).total_seconds() / 3600.0, 0.0)


def _texto_tiempo(horas: float | None) -> str | None:
    if horas is None:
        return None
    if horas < 1:
        minutos = max(int(round(horas * 60)), 1)
        return f"hace {minutos} min"
    if horas < 48:
        return f"hace {int(horas)} h"
    return f"hace {int(horas // 24)} días"


def _prioridad_por_horas(horas: float | None, atencion: float, urgente: float) -> str:
    if horas is None:
        return PRIORIDAD_NORMAL
    if horas > urgente:
        return PRIORIDAD_URGENTE
    if horas >= atencion:
        return PRIORIDAD_ATENCION
    return PRIORIDAD_NORMAL


def _envio(nota: dict[str, Any]) -> dict[str, Any]:
    valor = nota.get("envio")
    return valor if isinstance(valor, dict) else {}


def guia_nota(nota: dict[str, Any]) -> str:
    envio = _envio(nota)
    return str(nota.get("guia") or envio.get("guia") or envio.get("numero_guia") or "").strip()


def requiere_guia(nota: dict[str, Any]) -> bool:
    envio = _envio(nota)
    tipo = normalizar_estado(
        envio.get("tipo")
        or envio.get("metodo")
        or nota.get("paqueteria")
        or nota.get("tipo_entrega")
    ).replace("_", " ")
    if not tipo:
        return True
    return not any(etiqueta in tipo for etiqueta in ESTADOS_ENTREGA_LOCAL)


def _cliente_nombre(registro: dict[str, Any]) -> str:
    return str(
        registro.get("cliente_nombre")
        or registro.get("cliente")
        or registro.get("nombre_cliente")
        or "Cliente sin nombre"
    ).strip()


def _notificacion(
    *,
    key: str,
    seccion: str,
    categoria: str,
    prioridad: str,
    titulo: str,
    mensaje: str,
    fecha_referencia: Any = None,
    destino_tipo: str,
    destino_id: Any,
    accion: str,
    accion_texto: str,
    nota_id: Any = None,
    cliente_id: Any = None,
    producto_id: Any = None,
    folio: Any = None,
    cliente_nombre: str | None = None,
    metadata: dict[str, Any] | None = None,
    acciones_secundarias: list[dict[str, Any]] | None = None,
    horas: float | None = None,
) -> dict[str, Any]:
    return {
        "id": key,
        "key": key,
        "seccion": seccion,
        "categoria": categoria,
        "prioridad": prioridad,
        "titulo": titulo,
        "mensaje": mensaje,
        "fecha_referencia": _fecha_iso(fecha_referencia),
        "tiempo_transcurrido": _texto_tiempo(horas),
        "horas_transcurridas": round(horas, 2) if horas is not None else None,
        "destino_tipo": destino_tipo,
        "destino_id": destino_id,
        "accion": accion,
        "accion_texto": accion_texto,
        "nota_id": nota_id,
        "cliente_id": cliente_id,
        "producto_id": producto_id,
        "folio": folio,
        "cliente_nombre": cliente_nombre,
        "metadata": dict(metadata or {}),
        "acciones_secundarias": list(acciones_secundarias or []),
    }


def _aviso_nota(
    nota: dict[str, Any],
    *,
    key: str,
    categoria: str,
    prioridad: str,
    titulo: str,
    mensaje: str,
    fecha: Any,
    horas: float | None,
    destino_tipo: str = "VENTA",
    accion: str = "ABRIR_VENTA",
    accion_texto: str = "Abrir venta",
    metadata: dict[str, Any] | None = None,
    acciones_secundarias: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nota_id = nota.get("id") or nota.get("nota_id")
    return _notificacion(
        key=key,
        seccion="OPERACION",
        categoria=categoria,
        prioridad=prioridad,
        titulo=titulo,
        mensaje=mensaje,
        fecha_referencia=fecha,
        destino_tipo=destino_tipo,
        destino_id=nota_id,
        accion=accion,
        accion_texto=accion_texto,
        nota_id=nota_id,
        cliente_id=nota.get("cliente_id"),
        folio=nota_id,
        cliente_nombre=_cliente_nombre(nota),
        metadata=metadata,
        acciones_secundarias=acciones_secundarias,
        horas=horas,
    )


def _inconsistencia_nota(
    nota: dict[str, Any],
    codigo: str,
    mensaje: str,
    *,
    prioridad: str = PRIORIDAD_URGENTE,
) -> dict[str, Any]:
    nota_id = nota.get("id") or nota.get("nota_id")
    return _aviso_nota(
        nota,
        key=f"inconsistencia:{codigo}:{nota_id}",
        categoria="INCONSISTENCIA_OPERATIVA",
        prioridad=prioridad,
        titulo="Revisar inconsistencia operativa",
        mensaje=mensaje,
        fecha=nota.get("fecha_finalizacion") or nota.get("fecha_pago") or nota.get("fecha"),
        horas=None,
        metadata={"inconsistencia": codigo},
    )


def _notificaciones_por_notas(notas: Iterable[dict[str, Any]], ahora: datetime) -> list[dict[str, Any]]:
    avisos: list[dict[str, Any]] = []
    for nota_original in notas:
        nota = dict(nota_original or {})
        nota_id = nota.get("id") or nota.get("nota_id")
        if nota_id in (None, ""):
            continue
        estado = normalizar_estado(nota.get("estado"))
        cliente = _cliente_nombre(nota)
        total_piezas = max(_entero(nota.get("piezas_totales") or nota.get("requeridas")), 0)
        empacadas = max(_entero(nota.get("piezas_empacadas") or nota.get("empacadas")), 0)
        porcentaje = round((empacadas / total_piezas) * 100) if total_piezas else 0

        if estado == "VENTA_PENDIENTE":
            fecha = nota.get("fecha")
            horas = _horas_transcurridas(fecha, ahora)
            tiempo = _texto_tiempo(horas)
            mensaje = f"La venta {nota_id} de {cliente} sigue pendiente de pago"
            if tiempo:
                mensaje += f" {tiempo}"
            mensaje += "."
            avisos.append(_aviso_nota(
                nota,
                key=f"pendiente_pago:{nota_id}",
                categoria="PENDIENTE_PAGO",
                prioridad=_prioridad_por_horas(horas, 12, 24),
                titulo="Venta pendiente de pago",
                mensaje=mensaje,
                fecha=fecha,
                horas=horas,
                acciones_secundarias=[
                    {"accion": "ABRIR_CLIENTE", "texto": "Ver cliente"},
                    {"accion": "PREPARAR_RECORDATORIO_PAGO", "texto": "Preparar recordatorio"},
                ],
            ))

        elif estado == "PAGADA":
            fecha = nota.get("fecha_pago")
            horas = _horas_transcurridas(fecha, ahora)
            empacador = str(nota.get("empacador_nombre") or nota.get("empacador_actual") or "").strip()
            if not empacador:
                detalle = "todavía no tiene empacador asignado"
            elif empacadas <= 0:
                detalle = f"está asignada a {empacador}, pero el empaque no ha comenzado"
            else:
                detalle = "requiere revisar su avance de empaque"
            avisos.append(_aviso_nota(
                nota,
                key=f"pagada_sin_empaquetar:{nota_id}",
                categoria="PAGADA_SIN_EMPAQUETAR",
                prioridad=_prioridad_por_horas(horas, 8, 24),
                titulo="Venta pagada sin empaquetar",
                mensaje=f"La venta {nota_id} de {cliente} {detalle}.",
                fecha=fecha,
                horas=horas,
                destino_tipo="ASIGNACION",
                accion="ABRIR_ASIGNACION",
                accion_texto="Abrir asignación",
                metadata={"empacador": empacador, "piezas_empacadas": empacadas},
                acciones_secundarias=[{"accion": "ABRIR_VENTA", "texto": "Abrir venta"}],
            ))

        elif estado in {"EN_PROCESO", "INCOMPLETA"}:
            fecha = nota.get("fecha_asignacion")
            horas = _horas_transcurridas(fecha, ahora)
            empacador = str(nota.get("empacador_nombre") or nota.get("empacador_actual") or "Sin asignar").strip()
            avisos.append(_aviso_nota(
                nota,
                key=f"empaque_incompleto:{nota_id}",
                categoria="EMPAQUE_INCOMPLETO",
                prioridad=_prioridad_por_horas(horas, 8, 24),
                titulo="Empaque en curso",
                mensaje=(
                    f"La venta {nota_id} de {cliente} lleva {empacadas} de {total_piezas} "
                    f"piezas ({porcentaje}%)."
                ),
                fecha=fecha,
                horas=horas,
                destino_tipo="PEDIDO",
                accion="ABRIR_PEDIDO",
                accion_texto="Abrir pedido",
                metadata={
                    "empacador": empacador,
                    "piezas_totales": total_piezas,
                    "piezas_empacadas": empacadas,
                    "porcentaje": porcentaje,
                },
                acciones_secundarias=[
                    {"accion": "ABRIR_ASIGNACION", "texto": "Ver artículos faltantes"},
                    {"accion": "ABRIR_VENTA", "texto": "Abrir venta"},
                ],
            ))

        elif estado == "COMPLETA":
            fecha = nota.get("fecha_finalizacion")
            horas = _horas_transcurridas(fecha, ahora)
            guia = guia_nota(nota)
            if requiere_guia(nota) and not guia:
                avisos.append(_aviso_nota(
                    nota,
                    key=f"completa_sin_guia:{nota_id}",
                    categoria="COMPLETA_SIN_GUIA",
                    prioridad=_prioridad_por_horas(horas, 4, 12),
                    titulo="Pedido completo sin guía",
                    mensaje=f"El pedido {nota_id} de {cliente} terminó de empaquetarse y necesita guía.",
                    fecha=fecha,
                    horas=horas,
                    destino_tipo="ENVIO",
                    accion="ABRIR_ENVIOS",
                    accion_texto="Abrir envíos",
                    acciones_secundarias=[{"accion": "ABRIR_VENTA", "texto": "Abrir venta"}],
                ))
            elif guia:
                avisos.append(_aviso_nota(
                    nota,
                    key=f"guia_sin_envio:{nota_id}",
                    categoria="GUIA_SIN_ENVIO",
                    prioridad=_prioridad_por_horas(horas, 12, 24),
                    titulo="Guía lista, envío pendiente",
                    mensaje=f"El pedido {nota_id} de {cliente} ya tiene guía y falta marcarlo como enviado.",
                    fecha=fecha,
                    horas=horas,
                    destino_tipo="ENVIO",
                    accion="ABRIR_ENVIOS",
                    accion_texto="Abrir envíos",
                    metadata={"guia": guia},
                    acciones_secundarias=[{"accion": "ABRIR_VENTA", "texto": "Abrir venta"}],
                ))

        if estado == "PAGADA" and not nota.get("fecha_pago"):
            avisos.append(_inconsistencia_nota(
                nota,
                "pagada_sin_fecha",
                "Esta venta aparece como pagada, pero no tiene fecha de pago.",
            ))
        if estado == "COMPLETA" and not nota.get("fecha_finalizacion"):
            avisos.append(_inconsistencia_nota(
                nota,
                "completa_sin_fecha",
                "El pedido aparece completo, pero no tiene fecha de finalización.",
            ))
        if estado == "ENVIADO" and requiere_guia(nota) and not guia_nota(nota):
            avisos.append(_inconsistencia_nota(
                nota,
                "enviado_sin_guia",
                "El pedido aparece enviado, pero no tiene una guía registrada.",
            ))
        if total_piezas > 0:
            if estado == "COMPLETA" and empacadas < total_piezas:
                avisos.append(_inconsistencia_nota(
                    nota,
                    "completa_con_piezas_pendientes",
                    "El pedido aparece completo, pero todavía tiene piezas pendientes de empaque.",
                ))
            elif estado in {"EN_PROCESO", "INCOMPLETA"} and empacadas >= total_piezas:
                avisos.append(_inconsistencia_nota(
                    nota,
                    "empaque_terminado_estado_pendiente",
                    "Todas las piezas están empacadas, pero el pedido aún aparece en proceso.",
                ))
            elif estado == "PAGADA" and empacadas > 0:
                avisos.append(_inconsistencia_nota(
                    nota,
                    "pagada_con_avance",
                    "La venta todavía aparece como pagada aunque ya tiene piezas empacadas.",
                    prioridad=PRIORIDAD_ATENCION,
                ))
    return avisos


def _notificaciones_impresion(tareas: Iterable[dict[str, Any]], ahora: datetime) -> list[dict[str, Any]]:
    avisos: list[dict[str, Any]] = []
    for tarea_original in tareas:
        tarea = dict(tarea_original or {})
        estado = normalizar_estado(tarea.get("estado"))
        if estado not in {"PENDIENTE", "FALLIDA"}:
            continue
        nota_id = tarea.get("nota_id")
        tarea_id = tarea.get("id") or f"{nota_id}:{tarea.get('tipo') or 'etiqueta'}"
        estado_nota = normalizar_estado(tarea.get("estado_nota"))
        if estado_nota in ESTADOS_TERMINALES:
            nota = {
                "id": nota_id,
                "cliente_id": tarea.get("cliente_id"),
                "cliente_nombre": _cliente_nombre(tarea),
                "fecha": tarea.get("creado_en"),
            }
            avisos.append(_inconsistencia_nota(
                nota,
                "impresion_terminal",
                "Una tarea de impresión pendiente pertenece a una nota anulada o archivada.",
            ))
            continue
        fecha = tarea.get("actualizado_en") or tarea.get("creado_en") or tarea.get("fecha")
        horas = _horas_transcurridas(fecha, ahora)
        intentos = _entero(tarea.get("intentos"))
        prioridad = PRIORIDAD_URGENTE if estado == "FALLIDA" or intentos >= 3 else _prioridad_por_horas(horas, 4, 12)
        categoria = "IMPRESION_FALLIDA" if estado == "FALLIDA" else "IMPRESION_PENDIENTE"
        titulo = "Impresión fallida" if estado == "FALLIDA" else "Impresión pendiente"
        avisos.append(_notificacion(
            key=f"impresion:{tarea_id}",
            seccion="OPERACION",
            categoria=categoria,
            prioridad=prioridad,
            titulo=titulo,
            mensaje=f"La etiqueta de la venta {nota_id} requiere atención.",
            fecha_referencia=fecha,
            destino_tipo="IMPRESION",
            destino_id=tarea_id,
            accion="ABRIR_IMPRESION",
            accion_texto="Abrir impresión",
            nota_id=nota_id,
            cliente_id=tarea.get("cliente_id"),
            folio=nota_id,
            cliente_nombre=_cliente_nombre(tarea),
            metadata={"tipo": tarea.get("tipo"), "intentos": intentos},
            acciones_secundarias=[{"accion": "ABRIR_VENTA", "texto": "Ver venta"}],
            horas=horas,
        ))
    return avisos


def _notificaciones_errores_scan(errores: Iterable[dict[str, Any]], ahora: datetime) -> list[dict[str, Any]]:
    avisos: list[dict[str, Any]] = []
    for error_original in errores:
        error = dict(error_original or {})
        nota_id = error.get("nota_id")
        if nota_id in (None, ""):
            continue
        estado_nota = normalizar_estado(error.get("estado_nota"))
        if estado_nota and estado_nota not in ESTADOS_EMPAQUE_ACTIVO:
            continue
        error_id = error.get("id") or ":".join((
            str(nota_id),
            str(error.get("codigo") or "sin_codigo"),
            str(error.get("fecha") or "sin_fecha"),
        ))
        fecha = error.get("fecha")
        horas = _horas_transcurridas(fecha, ahora)
        codigo = str(error.get("codigo") or "sin código")
        avisos.append(_notificacion(
            key=f"error_scan:{error_id}",
            seccion="OPERACION",
            categoria="ERROR_ESCAN",
            prioridad=PRIORIDAD_URGENTE,
            titulo="Error de escaneo pendiente",
            mensaje=f"La venta {nota_id} registró un problema al escanear el código {codigo}.",
            fecha_referencia=fecha,
            destino_tipo="ESCANEO",
            destino_id=nota_id,
            accion="ABRIR_REPORTE_ESCANEO",
            accion_texto="Ver errores",
            nota_id=nota_id,
            folio=nota_id,
            metadata={
                "codigo": codigo,
                "motivo": error.get("motivo"),
                "empacador": error.get("empacador") or error.get("nombre"),
            },
            acciones_secundarias=[{"accion": "ABRIR_PEDIDO", "texto": "Abrir pedido"}],
            horas=horas,
        ))
    return avisos


def _notificaciones_inventario(productos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    avisos: list[dict[str, Any]] = []
    for producto_original in productos:
        producto = dict(producto_original or {})
        estado = normalizar_estado(producto.get("estado"))
        if estado not in {"RESURTIR", "SIN STOCK", "STOCK BAJO"}:
            continue
        producto_id = producto.get("id") or producto.get("producto_id")
        if producto_id in (None, ""):
            continue
        codigo = str(producto.get("codigo") or "sin código")
        nombre = " · ".join(
            texto for texto in (
                str(producto.get("marca") or "").strip(),
                str(producto.get("hilo") or "").strip(),
                str(producto.get("color") or "").strip(),
            ) if texto
        ) or f"Producto {codigo}"
        stock = _numero(producto.get("stock"))
        prioridad = PRIORIDAD_URGENTE if estado == "SIN STOCK" else PRIORIDAD_ATENCION
        avisos.append(_notificacion(
            key=f"inventario_bajo:{producto_id}",
            seccion="OPERACION",
            categoria="INVENTARIO_BAJO",
            prioridad=prioridad,
            titulo="Producto con inventario bajo",
            mensaje=f"{nombre} tiene {stock:g} piezas disponibles ({estado.title()}).",
            destino_tipo="PRODUCTO",
            destino_id=producto_id,
            accion="ABRIR_PRODUCTO",
            accion_texto="Abrir producto",
            producto_id=producto_id,
            metadata={
                "codigo": codigo,
                "marca": producto.get("marca"),
                "hilo": producto.get("hilo"),
                "color": producto.get("color"),
                "stock": stock,
                "estado_inventario": estado,
            },
            acciones_secundarias=[{"accion": "ABRIR_ALMACEN", "texto": "Abrir almacén"}],
        ))
    return avisos


def _orden_operacion(aviso: dict[str, Any]) -> tuple[Any, ...]:
    horas = aviso.get("horas_transcurridas")
    return (
        ORDEN_PRIORIDAD.get(aviso.get("prioridad"), 9),
        -float(horas or 0),
        str(aviso.get("categoria") or ""),
        str(aviso.get("folio") or aviso.get("cliente_nombre") or ""),
    )


def _deduplicar(avisos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unicos: dict[str, dict[str, Any]] = {}
    for aviso in avisos:
        key = str(aviso.get("key") or "").strip()
        if key and key not in unicos:
            unicos[key] = aviso
    return list(unicos.values())


def construir_notificaciones_operacion(
    notas: Iterable[dict[str, Any]],
    impresiones: Iterable[dict[str, Any]] = (),
    errores_scan: Iterable[dict[str, Any]] = (),
    productos: Iterable[dict[str, Any]] = (),
    ahora: datetime | None = None,
) -> list[dict[str, Any]]:
    ahora = _ahora_naive(ahora)
    avisos = [
        *_notificaciones_por_notas(notas, ahora),
        *_notificaciones_impresion(impresiones, ahora),
        *_notificaciones_errores_scan(errores_scan, ahora),
        *_notificaciones_inventario(productos),
    ]
    return sorted(_deduplicar(avisos), key=_orden_operacion)


def _cliente_inactivo(cliente: dict[str, Any]) -> bool:
    activo = cliente.get("activo")
    if activo is not None and str(activo).strip().lower() in {"0", "false", "no", "inactivo"}:
        return True
    estado = normalizar_estado(cliente.get("estado"))
    if estado in {"INACTIVO", "ELIMINADO", "FUSIONADO", "BAJA"}:
        return True
    return bool(
        cliente.get("eliminado_en")
        or cliente.get("fusionado_en")
        or cliente.get("fusionado_con_id")
    )


def _controles_por_clave(controles: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    resultado = {}
    for control in controles or ():
        cliente_id = str(control.get("cliente_id") or "")
        categoria = normalizar_estado(control.get("categoria") or control.get("tipo_oportunidad"))
        if cliente_id and categoria:
            resultado[(cliente_id, categoria)] = dict(control)
    return resultado


def _control_vigente(
    control: dict[str, Any] | None,
    ahora: datetime,
    ultima_compra: Any = None,
) -> bool:
    if not control:
        return False
    fecha_accion = parsear_fecha(control.get("fecha_accion"))
    compra = parsear_fecha(ultima_compra)
    if fecha_accion and compra and compra > fecha_accion:
        return False
    for campo in ("oculto_hasta", "pospuesto_hasta"):
        fecha = parsear_fecha(control.get(campo))
        if fecha and fecha > ahora:
            return True
    return False


def _mensaje_sugerido(categoria: str, nombre: str) -> str:
    nombre_corto = (nombre or "").split()[0] or "Hola"
    if categoria == "DORMIDA":
        return (
            f"Hola, {nombre_corto}. Hace tiempo que no realizas un pedido con nosotros y "
            "queríamos saludarte. Tenemos nuevos tonos y disponibilidad en varios productos. "
            "¿Te gustaría que te enviemos opciones?"
        )
    return (
        f"Hola, {nombre_corto}. Te escribimos para saber si próximamente necesitarás más "
        "material. Tenemos disponibilidad y puedo mostrarte los tonos actuales."
    )


def _oportunidad_cliente(
    metrica: dict[str, Any],
    categoria: str,
    prioridad: str,
    dias_restantes: int | None,
    dias_atraso: int,
) -> dict[str, Any]:
    cliente_id = metrica.get("cliente_id")
    nombre = str(metrica.get("nombre") or "Clienta sin nombre").strip()
    segmento = normalizar_estado(metrica.get("segmento"))
    frecuencia = metrica.get("frecuencia_promedio_dias")
    ticket = _numero(metrica.get("ticket_promedio"))
    compras = _entero(metrica.get("numero_compras"))

    if categoria == "PROXIMA_COMPRA":
        titulo = "Próxima compra habitual"
        mensaje = f"{nombre} suele comprar cada {frecuencia:g} días y está cerca de su fecha habitual."
    elif categoria == "RECURRENTE_ATRASADA":
        titulo = "Clienta frecuente atrasada"
        mensaje = f"{nombre} superó por {dias_atraso} días su frecuencia habitual de compra."
    elif categoria == "VIP_RECUPERAR":
        titulo = "Oportunidad con clienta VIP"
        mensaje = f"{nombre} es VIP y tiene una oportunidad concreta de seguimiento comercial."
    elif categoria == "DORMIDA":
        titulo = "Clienta dormida por recuperar"
        mensaje = f"{nombre} está clasificada como dormida según la analítica actual del CRM."
    else:
        titulo = "Clienta atrasada respecto a su frecuencia"
        mensaje = f"{nombre} lleva {dias_atraso} días de atraso respecto a su compra habitual."

    key = f"{categoria.lower()}:{cliente_id}"
    return _notificacion(
        key=key,
        seccion="OPORTUNIDADES",
        categoria=categoria,
        prioridad=prioridad,
        titulo=titulo,
        mensaje=mensaje,
        fecha_referencia=metrica.get("proxima_compra_estimada") or metrica.get("ultima_compra"),
        destino_tipo="CLIENTE",
        destino_id=cliente_id,
        accion="PREPARAR_MENSAJE",
        accion_texto="Preparar mensaje",
        cliente_id=cliente_id,
        cliente_nombre=nombre,
        metadata={
            "telefono": metrica.get("telefono"),
            "segmento": segmento,
            "ultima_compra": metrica.get("ultima_compra"),
            "dias_desde_ultima_compra": metrica.get("dias_desde_ultima_compra"),
            "frecuencia_promedio_dias": frecuencia,
            "proxima_compra_estimada": metrica.get("proxima_compra_estimada"),
            "dias_restantes": dias_restantes,
            "dias_atraso": dias_atraso,
            "numero_compras": compras,
            "ticket_promedio": ticket,
            "total_comprado": _numero(metrica.get("total_comprado")),
            "marcas_favoritas": metrica.get("marcas_favoritas") or [],
            "productos_favoritos": metrica.get("productos_favoritos") or [],
            "mensaje_sugerido": _mensaje_sugerido(categoria, nombre),
        },
        acciones_secundarias=[
            {"accion": "ABRIR_CLIENTE", "texto": "Abrir cliente"},
            {"accion": "VER_HISTORIAL_CLIENTE", "texto": "Ver historial"},
            {"accion": "VER_PRODUCTOS_FRECUENTES", "texto": "Ver productos frecuentes"},
            {"accion": "RECORDAR_3", "texto": "Recordar en 3 días"},
            {"accion": "RECORDAR_7", "texto": "Recordar en 7 días"},
            {"accion": "OCULTAR_30", "texto": "Ocultar 30 días"},
        ],
    )


def construir_oportunidades_venta(
    metricas_clientes: Iterable[dict[str, Any]],
    clientes: Iterable[dict[str, Any]] = (),
    cliente_ids_con_pendiente: Iterable[Any] = (),
    controles: Iterable[dict[str, Any]] = (),
    ahora: datetime | None = None,
) -> list[dict[str, Any]]:
    """Selecciona acciones utiles usando exclusivamente metricas del CRM."""
    ahora = _ahora_naive(ahora)
    clientes_por_id = {
        str(cliente.get("id")): dict(cliente)
        for cliente in clientes or ()
        if cliente.get("id") is not None
    }
    excluidos = {str(cliente_id) for cliente_id in cliente_ids_con_pendiente or ()}
    controles_clave = _controles_por_clave(controles)
    avisos = []

    for metrica_original in metricas_clientes or ():
        metrica = dict(metrica_original or {})
        cliente_id = str(metrica.get("cliente_id") or "")
        if not cliente_id or cliente_id in excluidos:
            continue
        if not str(metrica.get("telefono") or "").strip():
            continue
        cliente = clientes_por_id.get(cliente_id, {})
        if _cliente_inactivo(cliente):
            continue

        segmento = normalizar_estado(metrica.get("segmento"))
        proxima = parsear_fecha(metrica.get("proxima_compra_estimada"))
        dias_restantes = (proxima.date() - ahora.date()).days if proxima else None
        dias_atraso = max(-(dias_restantes or 0), 0) if dias_restantes is not None else 0
        cerca = dias_restantes is not None and 0 <= dias_restantes <= 7
        atrasada = dias_restantes is not None and dias_restantes < 0
        dormida = segmento == "DORMIDA"

        if segmento == "VIP" and (cerca or atrasada):
            categoria = "VIP_RECUPERAR"
            prioridad = PRIORIDAD_ATENCION
        elif segmento == "FRECUENTE" and atrasada:
            categoria = "RECURRENTE_ATRASADA"
            prioridad = PRIORIDAD_ATENCION
        elif dormida:
            categoria = "DORMIDA"
            prioridad = PRIORIDAD_NORMAL
        elif atrasada:
            categoria = "ATRASADA"
            prioridad = PRIORIDAD_ATENCION
        elif cerca:
            categoria = "PROXIMA_COMPRA"
            prioridad = PRIORIDAD_NORMAL
        else:
            continue

        if _control_vigente(
            controles_clave.get((cliente_id, categoria)),
            ahora,
            metrica.get("ultima_compra"),
        ):
            continue
        avisos.append(_oportunidad_cliente(
            metrica,
            categoria,
            prioridad,
            dias_restantes,
            dias_atraso,
        ))

    unicos_por_cliente: dict[str, dict[str, Any]] = {}
    for aviso in avisos:
        cliente_id = str(aviso.get("cliente_id") or "")
        if cliente_id and cliente_id not in unicos_por_cliente:
            unicos_por_cliente[cliente_id] = aviso
    return sorted(
        unicos_por_cliente.values(),
        key=lambda aviso: (
            ORDEN_PRIORIDAD.get(aviso.get("prioridad"), 9),
            ORDEN_OPORTUNIDADES.get(aviso.get("categoria"), 9),
            str(aviso.get("cliente_nombre") or "").lower(),
        ),
    )


def _seccion(avisos: Iterable[dict[str, Any]]) -> dict[str, Any]:
    lista = list(avisos or ())
    return {
        "total": len(lista),
        "categorias": dict(Counter(aviso.get("categoria") for aviso in lista)),
        "notificaciones": lista,
    }


def construir_resumen_notificaciones(
    operacion: Iterable[dict[str, Any]],
    oportunidades: Iterable[dict[str, Any]],
    *,
    oportunidades_actualizadas: bool = True,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    operacion_data = _seccion(operacion)
    oportunidades_data = _seccion(oportunidades)
    todas = operacion_data["notificaciones"] + oportunidades_data["notificaciones"]
    return {
        "ok": True,
        "total": len(todas),
        "urgentes": sum(1 for aviso in todas if aviso.get("prioridad") == PRIORIDAD_URGENTE),
        "atencion": sum(1 for aviso in todas if aviso.get("prioridad") == PRIORIDAD_ATENCION),
        "normales": sum(1 for aviso in todas if aviso.get("prioridad") == PRIORIDAD_NORMAL),
        "operacion": operacion_data,
        "oportunidades": oportunidades_data,
        "oportunidades_actualizadas": bool(oportunidades_actualizadas),
        "generado_en": _ahora_naive(ahora).isoformat(timespec="seconds"),
    }
