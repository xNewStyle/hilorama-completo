"""Calculos puros para el CRM comercial de clientas.

Este modulo no abre conexiones ni modifica datos. El backend le entrega solo
ventas finales y sus items, por lo que se puede probar sin una base real.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import sqrt
from typing import Any, Iterable


SEGMENTOS_CRM = (
    "VIP",
    "FRECUENTE",
    "ACTIVA",
    "EN_RIESGO",
    "DORMIDA",
    "NUEVA",
    "SIN_COMPRAS",
)

# Coincide con los estados que Hilorama reconoce como una venta cuyo pago ya
# ocurrio. ARCHIVADA requiere evidencia adicional de pago para no convertir
# cotizaciones historicas en compras.
ESTADOS_VENTAS_PAGADAS = frozenset({
    "PAGADA",
    "EN_PROCESO",
    "INCOMPLETA",
    "COMPLETA",
    "ENVIADO",
    "VENTA_PAGADA",
})
ESTADOS_VENTAS_FINALES = frozenset(set(ESTADOS_VENTAS_PAGADAS) | {"ARCHIVADA"})


def normalizar_segmento(valor: Any) -> str:
    texto = str(valor or "").strip().upper().replace(" ", "_")
    equivalencias = {
        "ENRIESGO": "EN_RIESGO",
        "EN_RIESGO": "EN_RIESGO",
        "SINCOMPRAS": "SIN_COMPRAS",
        "SIN_COMPRAS": "SIN_COMPRAS",
    }
    return equivalencias.get(texto, texto)


def normalizar_estado(valor: Any) -> str:
    return str(valor or "").strip().upper().replace("\u00d3", "O")


def _valor_verdadero(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor > 0
    return str(valor or "").strip().lower() in {"1", "true", "si", "yes", "pagada", "pagado"}


def tiene_evidencia_pago(venta: dict[str, Any]) -> bool:
    """Reconoce evidencia ya guardada; no infiere pagos por el total o estado."""
    pagos = venta.get("pagos")
    return bool(
        venta.get("fecha_pago")
        or venta.get("pago_id")
        or (isinstance(pagos, (list, tuple, set, dict)) and len(pagos) > 0)
        or _valor_verdadero(venta.get("pagado"))
    )


def es_venta_comercial(
    venta: dict[str, Any],
    estados_finales: Iterable[str] | None = None,
) -> bool:
    """Valida si una nota cuenta como compra sin duplicar la logica del CRM."""
    permitidos = {
        normalizar_estado(estado)
        for estado in (estados_finales or ESTADOS_VENTAS_FINALES)
    }
    estado = normalizar_estado(venta.get("estado"))
    if estado not in permitidos:
        return False
    if estado == "ARCHIVADA":
        return tiene_evidencia_pago(venta)
    return True


def parsear_fecha(valor: Any) -> datetime | None:
    """Acepta fechas de API/DB sin depender del tipo original de la columna."""
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None)
    if isinstance(valor, date):
        return datetime.combine(valor, datetime.min.time())
    if not valor:
        return None

    texto = str(valor).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(texto).replace(tzinfo=None)
    except ValueError:
        pass

    for formato in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(texto[:19], formato)
        except ValueError:
            continue
    return None


def _fecha_iso(valor: datetime | None) -> str | None:
    return valor.date().isoformat() if valor else None


def _numero(valor: Any, default: float = 0.0) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return default


def _numero_preferido(*valores: Any) -> float:
    for valor in valores:
        if valor not in (None, ""):
            return _numero(valor)
    return 0.0


def _entero(valor: Any, default: int = 0) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return default


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _fecha_venta(venta: dict[str, Any]) -> datetime | None:
    return parsear_fecha(venta.get("fecha_comercial") or venta.get("fecha_pago") or venta.get("fecha"))


def _intervalos_compra(fechas: list[datetime]) -> list[int]:
    fechas_ordenadas = sorted(set(fechas))
    return [
        (actual - anterior).days
        for anterior, actual in zip(fechas_ordenadas, fechas_ordenadas[1:])
        if (actual - anterior).days > 0
    ]


def _puntaje_recencia(dias: int | None) -> float:
    if dias is None:
        return 0.0
    if dias <= 15:
        return 30.0
    if dias <= 30:
        return 25.0
    if dias <= 45:
        return 18.0
    if dias <= 60:
        return 12.0
    if dias <= 90:
        return 6.0
    return 0.0


def _puntaje_constancia(intervalos: list[int]) -> float:
    """Mide la regularidad de la cadencia sin castigar compras aisladas."""
    if not intervalos:
        return 0.0
    if len(intervalos) == 1:
        return 5.0
    promedio = sum(intervalos) / len(intervalos)
    if promedio <= 0:
        return 0.0
    desviacion = sqrt(sum((valor - promedio) ** 2 for valor in intervalos) / len(intervalos))
    coeficiente_variacion = desviacion / promedio
    return max(0.0, min(10.0, 10.0 * (1.0 - coeficiente_variacion)))


def calcular_indice_compra(
    numero_compras: int,
    total_comprado: float,
    ticket_promedio: float,
    dias_desde_ultima_compra: int | None,
    intervalos_compra: list[int],
) -> tuple[int, dict[str, float]]:
    """Calcula un indice de 0 a 100 con pesos fijos y auditables.

    Pesos: recencia 30, frecuencia 25, monto acumulado 20, ticket 15 y
    constancia 10. Las referencias de monto ($5,000) y ticket ($800) son
    limites de saturacion: superar esos montos no da mas de los puntos del
    componente. Una clienta sin compra en 60 dias se limita a 19 puntos para
    que la clasificacion "DORMIDA" no se diluya por compras historicas.
    """
    recencia = _puntaje_recencia(dias_desde_ultima_compra)
    frecuencia = min(max(numero_compras, 0) / 6.0, 1.0) * 25.0
    monto = min(max(total_comprado, 0.0) / 5000.0, 1.0) * 20.0
    ticket = min(max(ticket_promedio, 0.0) / 800.0, 1.0) * 15.0
    constancia = _puntaje_constancia(intervalos_compra)
    bruto = recencia + frecuencia + monto + ticket + constancia

    if dias_desde_ultima_compra is not None and dias_desde_ultima_compra >= 60:
        bruto = min(bruto, 19.0)

    componentes = {
        "recencia": round(recencia, 2),
        "frecuencia": round(frecuencia, 2),
        "monto": round(monto, 2),
        "ticket": round(ticket, 2),
        "constancia": round(constancia, 2),
    }
    return int(round(max(0.0, min(100.0, bruto)))), componentes


def determinar_segmento(
    numero_compras: int,
    indice_compra: int,
    dias_desde_ultima_compra: int | None,
) -> str:
    if numero_compras <= 0:
        return "SIN_COMPRAS"
    if numero_compras == 1 and dias_desde_ultima_compra is not None and dias_desde_ultima_compra <= 60:
        return "NUEVA"
    if dias_desde_ultima_compra is not None and dias_desde_ultima_compra >= 60:
        return "DORMIDA"
    if indice_compra >= 85:
        return "VIP"
    if indice_compra >= 65:
        return "FRECUENTE"
    if indice_compra >= 40:
        return "ACTIVA"
    if indice_compra >= 20:
        return "EN_RIESGO"
    return "DORMIDA"


def _coincide_busqueda(cliente: dict[str, Any], consulta: str) -> bool:
    if not consulta:
        return True
    direccion = cliente.get("direccion") or {}
    if isinstance(direccion, dict):
        direccion_texto = " ".join(_texto(valor) for valor in direccion.values())
    else:
        direccion_texto = _texto(direccion)
    acumulado = " ".join((
        _texto(cliente.get("nombre")),
        _texto(cliente.get("telefono")),
        direccion_texto,
    )).lower()
    return consulta.lower() in acumulado


def _resumen_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    productos = []
    marcas = set()
    for item in items:
        marca = _texto(item.get("marca"))
        hilo = _texto(item.get("hilo"))
        codigo = _texto(item.get("codigo"))
        color = _texto(item.get("color"))
        if marca:
            marcas.add(marca)
        productos.append({
            "codigo": codigo,
            "marca": marca,
            "hilo": hilo,
            "color": color,
            "cantidad": _entero(item.get("cantidad")),
            "precio": round(_numero(item.get("precio")), 2),
            "subtotal": round(_numero_preferido(
                item.get("subtotal"),
                _numero(item.get("cantidad")) * _numero(item.get("precio")),
            ), 2),
        })
    return productos, sorted(marcas, key=str.lower)


def _favoritos(items: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    marcas: dict[str, dict[str, Any]] = {}
    productos: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in items:
        cantidad = _entero(item.get("cantidad"))
        precio = _numero(item.get("precio"))
        subtotal = _numero_preferido(item.get("subtotal"), cantidad * precio)
        marca = _texto(item.get("marca")) or "Sin marca"
        hilo = _texto(item.get("hilo"))
        codigo = _texto(item.get("codigo"))
        color = _texto(item.get("color"))

        marca_data = marcas.setdefault(marca, {"marca": marca, "cantidad": 0, "total": 0.0})
        marca_data["cantidad"] += cantidad
        marca_data["total"] += subtotal

        clave = (marca, hilo, codigo, color)
        producto = productos.setdefault(clave, {
            "marca": marca,
            "hilo": hilo,
            "codigo": codigo,
            "color": color,
            "cantidad": 0,
            "total": 0.0,
        })
        producto["cantidad"] += cantidad
        producto["total"] += subtotal

    marcas_ordenadas = sorted(marcas.values(), key=lambda fila: (fila["total"], fila["cantidad"]), reverse=True)
    productos_ordenados = sorted(productos.values(), key=lambda fila: (fila["cantidad"], fila["total"]), reverse=True)
    for fila in marcas_ordenadas + productos_ordenados:
        fila["total"] = round(fila["total"], 2)
    return marcas_ordenadas[:5], productos_ordenados[:8]


def _alertas_comerciales(metricas: dict[str, Any]) -> list[dict[str, str]]:
    alertas: list[dict[str, str]] = []
    segmento = metricas.get("segmento")
    dias = metricas.get("dias_desde_ultima_compra")
    if segmento == "SIN_COMPRAS":
        alertas.append({"tipo": "sin_compras", "mensaje": "Aun no registra compras pagadas o confirmadas."})
    elif segmento == "VIP":
        alertas.append({"tipo": "vip", "mensaje": "Clienta VIP: conviene avisarle primero de novedades relevantes."})
    elif segmento == "FRECUENTE":
        alertas.append({"tipo": "frecuente", "mensaje": "Compra con recurrencia: puede ser buen momento para seguimiento."})
    elif segmento == "NUEVA":
        alertas.append({"tipo": "nueva", "mensaje": "Compra reciente: conviene dar seguimiento despues de su primera experiencia."})
    elif segmento == "EN_RIESGO":
        alertas.append({"tipo": "riesgo", "mensaje": "Su ritmo de compra bajo: sugiera novedades o tonos relacionados."})
    elif segmento == "DORMIDA":
        alertas.append({"tipo": "dormida", "mensaje": "No ha comprado recientemente: requiere reactivacion comercial cuidadosa."})
    if dias is not None and dias >= 90:
        alertas.append({"tipo": "sin_contacto", "mensaje": f"Han pasado {dias} dias desde su ultima compra."})
    return alertas


def construir_metricas_clienta(
    cliente: dict[str, Any],
    ventas: Iterable[dict[str, Any]],
    items_por_nota: dict[str, list[dict[str, Any]]],
    ahora: datetime | None = None,
    incluir_historial: bool = False,
    incluir_favoritos: bool | None = None,
) -> dict[str, Any]:
    ahora = (ahora or datetime.now()).replace(tzinfo=None)
    ventas_normalizadas = []
    for venta in ventas:
        fecha = _fecha_venta(venta)
        if not fecha:
            continue
        registro = dict(venta)
        registro["_fecha"] = fecha
        registro["_total"] = _numero_preferido(venta.get("total_final"), venta.get("total"))
        ventas_normalizadas.append(registro)
    ventas_normalizadas.sort(key=lambda fila: fila["_fecha"])

    fechas = [fila["_fecha"] for fila in ventas_normalizadas]
    ultima = fechas[-1] if fechas else None
    primera = fechas[0] if fechas else None
    dias_desde_ultima = max((ahora.date() - ultima.date()).days, 0) if ultima else None
    intervalos = _intervalos_compra(fechas)
    frecuencia_promedio = round(sum(intervalos) / len(intervalos), 1) if intervalos else None
    proxima = ultima + timedelta(days=round(frecuencia_promedio)) if ultima and frecuencia_promedio else None
    total = round(sum(fila["_total"] for fila in ventas_normalizadas), 2)
    numero_compras = len(ventas_normalizadas)
    ticket_promedio = round(total / numero_compras, 2) if numero_compras else 0.0
    indice, componentes = calcular_indice_compra(
        numero_compras,
        total,
        ticket_promedio,
        dias_desde_ultima,
        intervalos,
    )
    segmento = determinar_segmento(numero_compras, indice, dias_desde_ultima)

    if incluir_favoritos is None:
        incluir_favoritos = incluir_historial

    todos_items: list[dict[str, Any]] = []
    historial = []
    if incluir_favoritos or incluir_historial:
        for venta in reversed(ventas_normalizadas):
            nota_id = str(venta.get("id") or venta.get("nota_id") or "")
            items = list(items_por_nota.get(nota_id, []))
            if incluir_favoritos:
                todos_items.extend(items)
            if incluir_historial:
                productos, marcas = _resumen_items(items)
                historial.append({
                    "nota_id": nota_id,
                    "folio": _texto(venta.get("folio") or venta.get("id")),
                    "fecha": _fecha_iso(venta["_fecha"]),
                    "total": round(venta["_total"], 2),
                    "estado": _texto(venta.get("estado")),
                    "productos": productos,
                    "marcas": marcas,
                    "cantidad_total": sum(_entero(item.get("cantidad")) for item in items),
                })

    if incluir_favoritos:
        marcas_favoritas, productos_favoritos = _favoritos(todos_items)
    else:
        marcas_favoritas, productos_favoritos = [], []
    metricas = {
        "cliente_id": cliente.get("id"),
        "nombre": _texto(cliente.get("nombre")) or "Sin nombre",
        "telefono": _texto(cliente.get("telefono")),
        "direccion": cliente.get("direccion") or {},
        "total_comprado": total,
        "numero_compras": numero_compras,
        "ticket_promedio": ticket_promedio,
        "primera_compra": _fecha_iso(primera),
        "ultima_compra": _fecha_iso(ultima),
        "dias_desde_ultima_compra": dias_desde_ultima,
        "frecuencia_promedio_dias": frecuencia_promedio,
        "proxima_compra_estimada": _fecha_iso(proxima),
        "indice_compra": indice,
        "componentes_indice": componentes,
        "segmento": segmento,
        "marcas_favoritas": marcas_favoritas,
        "productos_favoritos": productos_favoritos,
    }
    metricas["alertas_comerciales"] = _alertas_comerciales(metricas)
    if incluir_historial:
        metricas["historial_resumido"] = historial
    return metricas


def construir_analitica_clientas(
    clientes: Iterable[dict[str, Any]],
    ventas: Iterable[dict[str, Any]],
    items: Iterable[dict[str, Any]],
    filtros: dict[str, Any] | None = None,
    ahora: datetime | None = None,
    incluir_historial: bool = False,
    incluir_favoritos: bool | None = None,
    incluir_graficas: bool = True,
    estados_finales: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Agrupa ventas finales por clienta y devuelve ranking, resumen y graficas."""
    filtros = dict(filtros or {})
    ahora = (ahora or datetime.now()).replace(tzinfo=None)
    if incluir_favoritos is None:
        incluir_favoritos = incluir_historial
    estados_finales = {
        normalizar_estado(estado)
        for estado in (estados_finales or ESTADOS_VENTAS_FINALES)
    }
    desde = parsear_fecha(filtros.get("desde"))
    hasta = parsear_fecha(filtros.get("hasta"))
    if filtros.get("desde") and not desde:
        raise ValueError("La fecha desde no es valida. Usa AAAA-MM-DD.")
    if filtros.get("hasta") and not hasta:
        raise ValueError("La fecha hasta no es valida. Usa AAAA-MM-DD.")
    if desde and hasta and desde.date() > hasta.date():
        raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")

    consulta = _texto(filtros.get("q"))
    segmento_filtro = normalizar_segmento(filtros.get("segmento"))
    clientes_filtrados = [
        dict(cliente) for cliente in clientes
        if _coincide_busqueda(cliente, consulta)
    ]
    clientes_por_id = {str(cliente.get("id")): cliente for cliente in clientes_filtrados if cliente.get("id") is not None}

    ventas_por_cliente: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ventas_filtradas: list[dict[str, Any]] = []
    ventas_vistas: set[str] = set()
    for indice_venta, venta_original in enumerate(ventas):
        venta = dict(venta_original)
        cliente_id = str(venta.get("cliente_id") or "")
        fecha = _fecha_venta(venta)
        if not cliente_id or cliente_id not in clientes_por_id or not fecha:
            continue
        if not es_venta_comercial(venta, estados_finales):
            continue
        if desde and fecha.date() < desde.date():
            continue
        if hasta and fecha.date() > hasta.date():
            continue
        nota_id = str(venta.get("id") or venta.get("nota_id") or "").strip()
        clave_venta = f"nota:{nota_id}" if nota_id else f"sin_id:{indice_venta}"
        if clave_venta in ventas_vistas:
            continue
        ventas_vistas.add(clave_venta)
        venta["fecha_comercial"] = _fecha_iso(fecha)
        ventas_por_cliente[cliente_id].append(venta)
        ventas_filtradas.append(venta)

    items_por_nota: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if incluir_favoritos or incluir_historial:
        notas_incluidas = {str(venta.get("id") or venta.get("nota_id") or "") for venta in ventas_filtradas}
        for item in items:
            nota_id = str(item.get("nota_id") or "")
            if nota_id and nota_id in notas_incluidas:
                items_por_nota[nota_id].append(dict(item))

    metricas = [
        construir_metricas_clienta(
            cliente,
            ventas_por_cliente.get(cliente_id, []),
            items_por_nota,
            ahora=ahora,
            incluir_historial=incluir_historial,
            incluir_favoritos=incluir_favoritos,
        )
        for cliente_id, cliente in clientes_por_id.items()
    ]
    if segmento_filtro and segmento_filtro not in {"TODAS", "TODOS"}:
        metricas = [fila for fila in metricas if fila.get("segmento") == segmento_filtro]

    metricas.sort(
        key=lambda fila: (fila["total_comprado"], fila["numero_compras"], fila["nombre"].lower()),
        reverse=True,
    )
    resumen = _crear_resumen(metricas, ahora)
    graficas = _crear_graficas(metricas, ventas_filtradas) if incluir_graficas else {}
    return {
        "clientes": metricas,
        "resumen": resumen,
        "graficas": graficas,
        "filtros": {
            "desde": _fecha_iso(desde),
            "hasta": _fecha_iso(hasta),
            "q": consulta,
            "segmento": segmento_filtro,
        },
    }


def _crear_resumen(metricas: list[dict[str, Any]], ahora: datetime) -> dict[str, Any]:
    con_compras = [fila for fila in metricas if fila["numero_compras"] > 0]
    ventas_total = round(sum(fila["total_comprado"] for fila in con_compras), 2)
    compras_total = sum(fila["numero_compras"] for fila in con_compras)
    return {
        "total_clientas": len(metricas),
        "clientas_activas_30d": sum(
            1 for fila in con_compras
            if fila.get("dias_desde_ultima_compra") is not None and fila["dias_desde_ultima_compra"] <= 30
        ),
        "clientas_dormidas_60d": sum(
            1 for fila in con_compras
            if fila.get("dias_desde_ultima_compra") is not None and fila["dias_desde_ultima_compra"] >= 60
        ),
        "clientas_vip": sum(1 for fila in metricas if fila.get("segmento") == "VIP"),
        "venta_total_periodo": ventas_total,
        "ticket_promedio_general": round(ventas_total / compras_total, 2) if compras_total else 0.0,
        "fecha_calculo": _fecha_iso(ahora),
    }


def _crear_graficas(metricas: list[dict[str, Any]], ventas: list[dict[str, Any]]) -> dict[str, Any]:
    top_total = [
        {"nombre": fila["nombre"], "total_comprado": fila["total_comprado"], "cliente_id": fila["cliente_id"]}
        for fila in sorted(metricas, key=lambda fila: fila["total_comprado"], reverse=True)[:10]
    ]
    top_compras = [
        {"nombre": fila["nombre"], "numero_compras": fila["numero_compras"], "cliente_id": fila["cliente_id"]}
        for fila in sorted(metricas, key=lambda fila: fila["numero_compras"], reverse=True)[:10]
    ]
    ticket_top = [
        {"nombre": fila["nombre"], "ticket_promedio": fila["ticket_promedio"], "cliente_id": fila["cliente_id"]}
        for fila in sorted(
            (fila for fila in metricas if fila["numero_compras"] > 0),
            key=lambda fila: fila["ticket_promedio"],
            reverse=True,
        )[:10]
    ]

    ventas_por_mes: dict[str, float] = defaultdict(float)
    for venta in ventas:
        fecha = _fecha_venta(venta)
        if not fecha:
            continue
        ventas_por_mes[fecha.strftime("%Y-%m")] += _numero_preferido(venta.get("total_final"), venta.get("total"))

    nuevas_por_mes: dict[str, int] = defaultdict(int)
    for fila in metricas:
        if fila.get("primera_compra"):
            nuevas_por_mes[str(fila["primera_compra"])[:7]] += 1

    segmentos: dict[str, int] = {segmento: 0 for segmento in SEGMENTOS_CRM}
    for fila in metricas:
        segmentos[fila.get("segmento") or "SIN_COMPRAS"] = segmentos.get(fila.get("segmento") or "SIN_COMPRAS", 0) + 1

    return {
        "top_clientas_por_total": top_total,
        "top_clientas_por_compras": top_compras,
        "ticket_promedio_top_clientas": ticket_top,
        "clientas_nuevas_por_mes": [
            {"mes": mes, "cantidad": cantidad}
            for mes, cantidad in sorted(nuevas_por_mes.items())
        ],
        "clientas_dormidas": [
            {
                "cliente_id": fila["cliente_id"],
                "nombre": fila["nombre"],
                "dias_desde_ultima_compra": fila["dias_desde_ultima_compra"],
            }
            for fila in metricas
            if fila.get("segmento") == "DORMIDA"
        ],
        "ventas_por_mes": [
            {"mes": mes, "total": round(total, 2)}
            for mes, total in sorted(ventas_por_mes.items())
        ],
        "segmentos": [
            {"segmento": segmento, "cantidad": cantidad}
            for segmento, cantidad in segmentos.items()
            if cantidad
        ],
    }
