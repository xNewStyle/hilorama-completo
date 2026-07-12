"""Helpers transaccionales para movimientos de inventario.

No abre conexiones ni cambia stock por su cuenta: el backend llama este helper
dentro de la misma transaccion que actualiza el producto.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

try:
    from hilorama_backend.services.auditoria_service import limpiar_datos_sensibles, limpiar_texto_sensible
except ImportError:
    from services.auditoria_service import limpiar_datos_sensibles, limpiar_texto_sensible


TIPOS_MOVIMIENTO = frozenset({
    "ENTRADA_MANUAL",
    "SALIDA_MANUAL",
    "AJUSTE_POSITIVO",
    "AJUSTE_NEGATIVO",
    "VENTA",
    "CANCELACION_VENTA",
    "DEVOLUCION",
    "STOCK_INICIAL",
    "CORRECCION",
    "OTRO",
})

_TIPOS_LEGACY = {
    "ALTA_PRODUCTO": "STOCK_INICIAL",
    "AJUSTE_STOCK_MANUAL": "AJUSTE",
    "SALIDA_STOCK": "VENTA",
    "SALIDA_STOCK_API": "VENTA",
    "DEVOLUCION_POR_ANULACION": "CANCELACION_VENTA",
    "STOCK_RESTABLECIDO_NOTA_PAGADA": "CANCELACION_VENTA",
    "AJUSTE_ADMIN_NOTA_PAGADA_DESCUENTO": "CORRECCION",
    "AJUSTE_ADMIN_NOTA_PAGADA_DEVOLUCION": "CORRECCION",
}


def normalizar_tipo_movimiento(tipo: Any, cantidad: Any = 0) -> str:
    clave = str(tipo or "OTRO").strip().upper()
    clave = _TIPOS_LEGACY.get(clave, clave)
    try:
        cantidad_numero = int(cantidad or 0)
    except (TypeError, ValueError):
        cantidad_numero = 0
    if clave == "AJUSTE":
        return "AJUSTE_POSITIVO" if cantidad_numero >= 0 else "AJUSTE_NEGATIVO"
    return clave if clave in TIPOS_MOVIMIENTO else "OTRO"


def _json_seguro(valor: Any) -> str:
    return json.dumps(limpiar_datos_sensibles(valor or {}), ensure_ascii=False, default=str, separators=(",", ":"))


def _producto_valor(producto: dict[str, Any] | None, campo: str, default=None):
    return (producto or {}).get(campo, default)


def clave_producto_movimiento(producto: dict[str, Any] | None, item: dict[str, Any] | None = None) -> tuple:
    """Genera una clave estable para agrupar lineas que descuentan el mismo producto."""
    producto = dict(producto or {})
    item = dict(item or {})
    producto_id = producto.get("id")
    if producto_id in (None, ""):
        producto_id = producto.get("producto_id")
    if producto_id not in (None, ""):
        return ("producto_id", str(producto_id))
    return (
        "producto",
        str(producto.get("marca") or item.get("marca") or "").strip().upper(),
        str(producto.get("hilo") or item.get("hilo") or "").strip().upper(),
        str(producto.get("codigo") or item.get("codigo") or "").strip().upper(),
    )


def agrupar_lineas_producto(lineas: list[tuple[dict[str, Any], dict[str, Any], Any]]) -> list[tuple[dict[str, Any], dict[str, Any], Any]]:
    """Suma cantidades repetidas para crear un solo movimiento por producto."""
    grupos: dict[tuple, tuple[dict[str, Any], dict[str, Any], Any]] = {}
    for item, producto, afectado in lineas:
        item_normalizado = dict(item or {})
        producto_normalizado = dict(producto or {})
        try:
            cantidad = int(float(item_normalizado.get("cantidad") or 0))
        except (TypeError, ValueError):
            cantidad = 0
        clave = clave_producto_movimiento(producto_normalizado, item_normalizado)
        if clave not in grupos:
            item_normalizado["cantidad"] = cantidad
            grupos[clave] = (item_normalizado, producto_normalizado, afectado)
            continue
        item_existente, producto_existente, afectado_existente = grupos[clave]
        item_existente["cantidad"] = int(item_existente.get("cantidad") or 0) + cantidad
        grupos[clave] = (item_existente, producto_existente, afectado_existente or afectado)
    return [grupos[clave] for clave in sorted(grupos, key=lambda valor: tuple(str(parte) for parte in valor))]


def cantidad_reintegrable(cantidad_salida: Any, cantidad_ya_reintegrada: Any = 0) -> int:
    """Evita que una anulacion reponga mas piezas de las que salieron."""
    try:
        salida = abs(int(cantidad_salida or 0))
        reintegrada = abs(int(cantidad_ya_reintegrada or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Las cantidades de movimientos deben ser enteras.") from exc
    return max(salida - reintegrada, 0)


def _buscar_idempotencia(conn, columnas: set[str], idempotency_key: str, cliente_sistema_id: int | None):
    if "idempotency_key" not in columnas:
        return None
    if "cliente_sistema_id" in columnas:
        return conn.execute(
            """
            SELECT id, tipo, cantidad, stock_anterior, stock_nuevo
            FROM movimientos_almacen
            WHERE idempotency_key=%s
              AND COALESCE(cliente_sistema_id, 0)=COALESCE(%s, 0)
            LIMIT 1
            """,
            (idempotency_key, cliente_sistema_id),
        ).fetchone()
    return conn.execute(
        "SELECT id, tipo, cantidad, stock_anterior, stock_nuevo FROM movimientos_almacen WHERE idempotency_key=%s LIMIT 1",
        (idempotency_key,),
    ).fetchone()


def registrar_movimiento_almacen(
    conn,
    columnas: set[str],
    *,
    producto: dict[str, Any] | None,
    tipo: str,
    cantidad: int,
    stock_anterior: int,
    stock_nuevo: int,
    motivo: str | None = None,
    referencia_tipo: str | None = None,
    referencia_id: str | int | None = None,
    usuario_id: int | None = None,
    cliente_sistema_id: int | None = None,
    usuario: str | None = None,
    device_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inserta un movimiento; si se repite su llave, devuelve el existente.

    Las excepciones se propagan para que el contexto transaccional exterior
    revierta tambien el cambio de stock.
    """
    if not columnas:
        raise RuntimeError("Falta la tabla movimientos_almacen. Aplica la migracion FASE 9B.")
    try:
        cantidad = int(cantidad)
        stock_anterior = int(stock_anterior)
        stock_nuevo = int(stock_nuevo)
    except (TypeError, ValueError) as exc:
        raise ValueError("El movimiento requiere stock anterior, nuevo y cantidad enteros.") from exc
    if stock_anterior + cantidad != stock_nuevo:
        raise ValueError("El movimiento no es consistente: stock_anterior + cantidad debe igualar stock_nuevo.")

    tipo_normalizado = normalizar_tipo_movimiento(tipo, cantidad)
    idempotency_key = str(idempotency_key or "").strip() or None
    if idempotency_key and "idempotency_key" in columnas:
        existente = _buscar_idempotencia(conn, columnas, idempotency_key, cliente_sistema_id)
        if existente:
            return {"creado": False, "idempotente": True, "movimiento": dict(existente)}

    valores = {
        "fecha": datetime.now(),
        "usuario": usuario or "usuario_desconocido",
        "tipo": tipo_normalizado,
        "marca": _producto_valor(producto, "marca"),
        "hilo": _producto_valor(producto, "hilo"),
        "color": _producto_valor(producto, "color"),
        "codigo": _producto_valor(producto, "codigo"),
        "stock_anterior": stock_anterior,
        "stock_nuevo": stock_nuevo,
        "cantidad": cantidad,
        "campo": "stock",
        "valor_anterior": str(stock_anterior),
        "valor_nuevo": str(stock_nuevo),
        "motivo": limpiar_texto_sensible(motivo).strip() or None,
        "cliente_sistema_id": cliente_sistema_id,
        "producto_id": _producto_valor(producto, "id"),
        "referencia_tipo": str(referencia_tipo or "").strip() or None,
        "referencia_id": str(referencia_id) if referencia_id not in (None, "") else None,
        "usuario_id": usuario_id,
        "device_id": str(device_id or "").strip() or None,
        "idempotency_key": idempotency_key,
        "metadata_json": _json_seguro(metadata),
    }
    campos = [campo for campo in valores if campo in columnas]
    if not campos:
        raise RuntimeError("La tabla movimientos_almacen no tiene columnas compatibles.")
    placeholders = ",".join(["%s"] * len(campos))
    retorno = " RETURNING id" if "id" in columnas else ""
    try:
        conn.execute("SAVEPOINT sp_movimiento_almacen_fase9")
        row = conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders}){retorno}",
            tuple(valores[campo] for campo in campos),
        ).fetchone() if retorno else None
        conn.execute("RELEASE SAVEPOINT sp_movimiento_almacen_fase9")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_almacen_fase9")
        finally:
            try:
                conn.execute("RELEASE SAVEPOINT sp_movimiento_almacen_fase9")
            except Exception:
                # La transaccion exterior conserva la responsabilidad de rollback.
                pass
        if idempotency_key and "idempotency_key" in columnas:
            existente = _buscar_idempotencia(conn, columnas, idempotency_key, cliente_sistema_id)
            if existente:
                return {"creado": False, "idempotente": True, "movimiento": dict(existente)}
        raise
    return {"creado": True, "idempotente": False, "movimiento": dict(row or {})}
