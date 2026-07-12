"""Diagnostico de solo lectura para trazabilidad de inventario y auditoria.

No aplica migraciones, no modifica stock y no corrige registros. Ejecutar con
DATABASE_URL configurada en un entorno que tenga psycopg2 disponible.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from urllib.parse import urlparse


SENSITIVE_KEYS = (
    "password",
    "contrasena",
    "contrase",
    "token",
    "secret",
    "api_key",
    "authorization",
    "clave",
)


def _connection_summary(database_url: str) -> str:
    parsed = urlparse(database_url)
    host = parsed.hostname or "sin_host"
    port = parsed.port or "predeterminado"
    database = (parsed.path or "/").lstrip("/") or "sin_base"
    user = parsed.username or "sin_usuario"
    return f"host={host} port={port} database={database} usuario={user}"


def _table_columns(cursor, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (table_name,),
    )
    return {row["column_name"] for row in cursor.fetchall()}


def _print_findings(title: str, rows: list[dict], keys: tuple[str, ...]) -> int:
    print(f"\n{title}: {len(rows)}")
    for row in rows:
        resumen = ", ".join(f"{key}={row.get(key)}" for key in keys if key in row)
        print(f"  - {resumen}")
    return len(rows)


def _json_value(value):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {"valor_no_json": str(value)}


def _has_visible_secret(value) -> bool:
    if isinstance(value, dict):
        for key, content in value.items():
            key_lower = str(key).lower()
            if any(sensitive in key_lower for sensitive in SENSITIVE_KEYS):
                if content not in (None, "", "[oculto]", "***", "[redactado]"):
                    return True
            if _has_visible_secret(content):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_visible_secret(item) for item in value)
    return False


def fecha_referencia_movimiento(fecha, fecha_creacion):
    """Conserva la fecha original; fecha_creacion solo cubre legados sin fecha."""
    return fecha if fecha not in (None, "") else fecha_creacion


def _fecha_comparable(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(texto[:10])
        except ValueError:
            return None


def clasificar_movimiento_temporal(fecha, fecha_creacion, desde: str | None) -> str:
    """Clasifica sin atajos por tipo, id o nombre de producto."""
    referencia = _fecha_comparable(fecha_referencia_movimiento(fecha, fecha_creacion))
    if referencia is None:
        return "SIN_FECHA_REFERENCIA"
    if not desde:
        return "SIN_CORTE"
    return "DESDE_CORTE" if referencia >= date.fromisoformat(desde) else "HISTORICO"


def expresion_fecha_referencia_movimiento(columns: set[str], alias: str = "m") -> tuple[str | None, str]:
    """Regla SQL única para todos los filtros temporales de movimientos."""
    prefijo = f"{alias}." if alias else ""
    tiene_fecha = "fecha" in columns
    tiene_fecha_creacion = "fecha_creacion" in columns
    if tiene_fecha and tiene_fecha_creacion:
        return f"COALESCE({prefijo}fecha, {prefijo}fecha_creacion)", "COALESCE(fecha, fecha_creacion)"
    if tiene_fecha:
        return f"{prefijo}fecha", "fecha"
    if tiene_fecha_creacion:
        return f"{prefijo}fecha_creacion", "fecha_creacion"
    return None, "sin columna temporal"


def _diagnosticar_movimientos_sin_fecha(cursor, columns: set[str], expresion: str, limit: int) -> None:
    cursor.execute(
        f"""
        SELECT m.id, m.producto_id, m.codigo, m.tipo
        FROM movimientos_almacen m
        WHERE {expresion} IS NULL
        ORDER BY m.id DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    if rows:
        _print_findings(
            "Movimientos sin fecha de referencia (no se cuentan como nuevos)",
            rows,
            ("id", "producto_id", "codigo", "tipo"),
        )
        print("  Se requieren revisión manual; no hay evidencia temporal para clasificarlos desde el corte.")


def _diagnose_movimientos(
    cursor,
    columns: set[str],
    limit: int,
    *,
    desde: str | None = None,
    incluir_historicos: bool = False,
) -> int:
    problemas = 0
    expresion_fecha, regla_fecha = expresion_fecha_referencia_movimiento(columns, "m")
    etiqueta_temporal = (
        f"desde {desde} usando {regla_fecha}"
        if desde
        else (f"incluye históricos usando {regla_fecha}" if incluir_historicos else f"sin corte temporal usando {regla_fecha}")
    )
    print(f"\nRegla temporal de movimientos: {etiqueta_temporal}.")
    if desde and not expresion_fecha:
        print("Movimientos: no se pudieron clasificar por fecha; faltan fecha y fecha_creacion.")
        return 0
    expresion_select = expresion_fecha or "NULL"
    filtro_fecha = f" AND {expresion_fecha} >= %s" if desde else ""
    parametros_fecha: tuple[object, ...] = (desde,) if desde else ()
    if desde and expresion_fecha:
        _diagnosticar_movimientos_sin_fecha(cursor, columns, expresion_fecha, limit)

    required = {"id", "stock_anterior", "cantidad", "stock_nuevo"}
    if required.issubset(columns):
        cursor.execute(
            f"""
            SELECT m.id, m.producto_id, m.codigo, m.tipo, m.cantidad, m.stock_anterior, m.stock_nuevo,
                   {expresion_select} AS fecha_referencia
            FROM movimientos_almacen m
            WHERE stock_anterior IS NOT NULL
              AND stock_nuevo IS NOT NULL
              AND stock_anterior + cantidad <> stock_nuevo
              {filtro_fecha}
            ORDER BY fecha_referencia DESC NULLS LAST, m.id DESC
            LIMIT %s
            """,
            parametros_fecha + (limit,),
        )
        problemas += _print_findings(
            "Movimientos inconsistentes (anterior + cantidad != nuevo; " + etiqueta_temporal + ")",
            cursor.fetchall(),
            ("id", "producto_id", "codigo", "tipo", "stock_anterior", "cantidad", "stock_nuevo", "fecha_referencia"),
        )
    else:
        print("\nMovimientos inconsistentes: no se pudieron revisar; faltan columnas base.")

    if {"id", "referencia_id", "tipo"}.issubset(columns):
        agrupador = "producto_id" if "producto_id" in columns else "codigo"
        if agrupador in columns:
            having_fecha = f" AND MAX({expresion_fecha}) >= %s" if desde else ""
            cursor.execute(
                f"""
                SELECT m.referencia_id, m.{agrupador}, COUNT(*) AS repetidos,
                       MAX({expresion_select}) AS fecha_referencia
                FROM movimientos_almacen m
                WHERE UPPER(COALESCE(m.tipo, ''))='VENTA'
                  AND m.referencia_id IS NOT NULL
                GROUP BY m.referencia_id, m.{agrupador}
                HAVING COUNT(*) > 1 {having_fecha}
                ORDER BY fecha_referencia DESC NULLS LAST, repetidos DESC
                LIMIT %s
                """,
                parametros_fecha + (limit,),
            )
            problemas += _print_findings(
                "Movimientos de venta potencialmente duplicados (" + etiqueta_temporal + ")",
                cursor.fetchall(),
                ("referencia_id", agrupador, "repetidos", "fecha_referencia"),
            )
    else:
        print("\nMovimientos de venta duplicados: no se pudieron revisar; faltan columnas de referencia.")

    if {"producto_id"}.issubset(columns):
        cursor.execute(
            """
            SELECT m.id, m.producto_id, m.codigo, m.tipo, m.referencia_id,
                   {expresion_fecha} AS fecha_referencia
            FROM movimientos_almacen m
            LEFT JOIN productos p ON p.id=m.producto_id
            WHERE m.producto_id IS NOT NULL AND p.id IS NULL
              {filtro_fecha}
            ORDER BY fecha_referencia DESC NULLS LAST, m.id DESC
            LIMIT %s
            """.format(expresion_fecha=expresion_select, filtro_fecha=filtro_fecha),
            parametros_fecha + (limit,),
        )
        problemas += _print_findings(
            "Movimientos con producto_id inexistente (" + etiqueta_temporal + ")",
            cursor.fetchall(),
            ("id", "producto_id", "codigo", "tipo", "referencia_id", "fecha_referencia"),
        )
    return problemas


def debe_revisar_notas_pagadas(desde: str | None, incluir_historicos: bool) -> bool:
    """Evita declarar inconsistencia una venta anterior a FASE 9B."""
    return bool(str(desde or "").strip() or incluir_historicos)


def _diagnose_paid_notes_without_movements(
    cursor,
    movement_columns: set[str],
    limit: int,
    *,
    desde: str | None = None,
    incluir_historicos: bool = False,
) -> int:
    if not {"referencia_id", "referencia_tipo", "tipo"}.issubset(movement_columns):
        print("\nNotas pagadas sin movimientos: no se pudieron revisar; faltan referencias de movimiento.")
        return 0
    if not debe_revisar_notas_pagadas(desde, incluir_historicos):
        print("\nNotas pagadas sin movimientos: omitidas para no marcar ventas historicas como error. Usa --desde AAAA-MM-DD o --incluir-historicos.")
        return 0

    notas_columns = _table_columns(cursor, "notas")
    fecha_columna = next((campo for campo in ("fecha_pago", "fecha", "fecha_creacion") if campo in notas_columns), None)
    filtro_fecha = ""
    valores: list[object] = []
    if desde:
        if not fecha_columna:
            print("\nNotas pagadas sin movimientos: no se pudieron filtrar por fecha; faltan fecha_pago, fecha y fecha_creacion.")
            return 0
        filtro_fecha = f" AND n.{fecha_columna} >= %s"
        valores.append(desde)
    cursor.execute(
        f"""
        SELECT n.id, n.estado{f', n.{fecha_columna} AS fecha_referencia' if fecha_columna else ''}
        FROM notas n
        WHERE UPPER(COALESCE(CAST(n.estado AS TEXT), '')) IN ('PAGADA', 'PAGADO', 'COMPLETA', 'VENTA_PAGADA')
          {filtro_fecha}
          AND NOT EXISTS (
              SELECT 1
              FROM movimientos_almacen m
              WHERE UPPER(COALESCE(m.tipo, ''))='VENTA'
                AND UPPER(COALESCE(m.referencia_tipo, ''))='NOTA'
                AND m.referencia_id=CAST(n.id AS TEXT)
          )
        ORDER BY n.id DESC
        LIMIT %s
        """,
        tuple(valores + [limit]),
    )
    rows = cursor.fetchall()
    return _print_findings("Notas pagadas sin movimiento VENTA", rows, ("id", "estado", "fecha_referencia"))


def _diagnose_auditoria(cursor, columns: set[str], limit: int) -> int:
    campos_json = [field for field in ("datos_anteriores_json", "datos_nuevos_json") if field in columns]
    if not campos_json:
        print("\nAuditorias con datos sensibles visibles: no se pudieron revisar; faltan campos JSON.")
        return 0
    select_fields = ["id", "accion", "modulo", "fecha_creacion", *campos_json]
    cursor.execute(
        f"SELECT {', '.join(select_fields)} FROM auditoria_general ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    hallazgos = []
    for row in cursor.fetchall():
        if any(_has_visible_secret(_json_value(row.get(field))) for field in campos_json):
            hallazgos.append(row)
    return _print_findings(
        "Auditorias con datos sensibles visibles",
        hallazgos,
        ("id", "accion", "modulo", "fecha_creacion"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostica movimientos y auditoria sin modificar datos.")
    parser.add_argument("--limit", type=int, default=100, help="Maximo de hallazgos por regla (predeterminado: 100).")
    parser.add_argument("--desde", help="Revisa ventas pagadas desde AAAA-MM-DD; evita falsos positivos historicos.")
    parser.add_argument("--incluir-historicos", action="store_true", help="Incluye ventas previas a FASE 9B bajo confirmacion explicita.")
    parser.add_argument("--strict", action="store_true", help="Devuelve codigo 1 si detecta inconsistencias.")
    args = parser.parse_args()
    limit = max(1, min(args.limit, 1000))
    desde = str(args.desde or "").strip() or None
    if desde:
        try:
            date.fromisoformat(desde)
        except ValueError:
            print("--desde debe usar el formato AAAA-MM-DD.")
            return 2
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("Falta DATABASE_URL. El diagnostico no se ejecuto.")
        return 2

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        print("Falta psycopg2. Ejecuta este diagnostico desde el entorno del backend.")
        return 2

    print("Diagnostico FASE 9B (solo lectura)")
    print(_connection_summary(database_url))
    problemas = 0
    try:
        with psycopg2.connect(database_url, cursor_factory=RealDictCursor) as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor() as cursor:
                mov_columns = _table_columns(cursor, "movimientos_almacen")
                audit_columns = _table_columns(cursor, "auditoria_general")
                if not mov_columns:
                    print("No existe movimientos_almacen. Aplica la migracion FASE 9B antes de diagnosticar.")
                else:
                    problemas += _diagnose_movimientos(
                        cursor,
                        mov_columns,
                        limit,
                        desde=desde,
                        incluir_historicos=args.incluir_historicos,
                    )
                    problemas += _diagnose_paid_notes_without_movements(
                        cursor,
                        mov_columns,
                        limit,
                        desde=desde,
                        incluir_historicos=args.incluir_historicos,
                    )
                if not audit_columns:
                    print("No existe auditoria_general. Aplica la migracion FASE 9B antes de diagnosticar.")
                else:
                    problemas += _diagnose_auditoria(cursor, audit_columns, limit)
    except Exception as exc:
        print(f"No se pudo ejecutar el diagnostico: {exc.__class__.__name__}: {exc}")
        return 2

    print(f"\nResultado: {problemas} hallazgo(s). No se modifico ningun dato.")
    return 1 if args.strict and problemas else 0


if __name__ == "__main__":
    sys.exit(main())
