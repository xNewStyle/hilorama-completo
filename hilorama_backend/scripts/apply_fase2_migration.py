"""Aplicador seguro de migracion FASE 2.

No ejecuta seed. No crea usuarios automaticamente.
Lee DATABASE_URL desde el entorno y aplica la migracion en una transaccion.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor


TABLAS_FASE2 = (
    "clientes_sistema",
    "usuarios_sistema",
    "dispositivos_autorizados",
    "sesiones_activas",
    "licencias_eventos",
)


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL no configurado.")
        print("Configure DATABASE_URL antes de ejecutar este script.")
        return 1

    sql_path = _migration_path()
    if not sql_path.exists():
        print(f"ERROR: no se encontro la migracion: {sql_path}")
        return 1

    _mostrar_resumen(database_url, sql_path)

    if input("Escriba APLICAR_FASE2 para continuar: ").strip() != "APLICAR_FASE2":
        print("Cancelado. No se aplico ningun cambio.")
        return 1

    if _parece_base_real(database_url):
        print("")
        print("ATENCION: DATABASE_URL parece apuntar a una base real o remota.")
        print("Confirme que ya tiene respaldo antes de continuar.")
        if input("Escriba ENTIENDO_QUE_ES_BASE_REAL para continuar: ").strip() != "ENTIENDO_QUE_ES_BASE_REAL":
            print("Cancelado. No se aplico ningun cambio.")
            return 1

    sql = sql_path.read_text(encoding="utf-8")

    try:
        with psycopg2.connect(database_url, cursor_factory=RealDictCursor) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    existentes = _verificar_tablas(cur)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    except Exception as exc:
        print("")
        print("ERROR: no se pudo aplicar la migracion FASE 2.")
        print("Se hizo rollback; no deberian quedar cambios parciales.")
        print(f"Detalle controlado: {type(exc).__name__}: {exc}")
        return 1

    faltantes = [tabla for tabla in TABLAS_FASE2 if tabla not in existentes]
    print("")
    if faltantes:
        print("Migracion ejecutada, pero faltan tablas al verificar:")
        for tabla in faltantes:
            print(f"- {tabla}")
        return 1

    print("Migracion FASE 2 aplicada correctamente.")
    print("Tablas verificadas:")
    for tabla in TABLAS_FASE2:
        print(f"- {tabla}")
    print("")
    print("No se ejecuto seed. No se crearon usuarios automaticamente.")
    return 0


def _migration_path():
    root = Path(__file__).resolve().parents[2]
    return root / "hilorama_backend" / "migrations" / "001_fase2_control_acceso.sql"


def _mostrar_resumen(database_url, sql_path):
    info = _parse_database_url(database_url)
    print("Aplicador seguro FASE 2")
    print("")
    print("Conexion detectada:")
    print(f"- host: {info.get('host') or '(sin host)'}")
    print(f"- puerto: {info.get('port') or '(default)'}")
    print(f"- database: {info.get('database') or '(sin database)'}")
    print(f"- usuario: {info.get('user') or '(sin usuario)'}")
    print("- password: [OCULTA]")
    print("")
    print(f"SQL: {sql_path}")
    print("")
    print("Tablas que se van a crear si no existen:")
    for tabla in TABLAS_FASE2:
        print(f"- {tabla}")
    print("")
    print("Advertencia: este script modifica estructura agregando tablas nuevas.")
    print("No toca productos, notas, pagos, ventas, stock ni inventario.")
    print("No ejecuta seed y no crea usuarios automaticamente.")
    print("")


def _parse_database_url(database_url):
    parsed = urlparse(database_url)
    database = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "database": database,
        "user": parsed.username,
    }


def _parece_base_real(database_url):
    info = _parse_database_url(database_url)
    host = (info.get("host") or "").lower()
    database = (info.get("database") or "").lower()
    safe_words = ("test", "prueba", "local", "dev", "sandbox")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return not any(word in database for word in safe_words)
    return True


def _verificar_tablas(cur):
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
          AND table_name = ANY(%s)
        """,
        (list(TABLAS_FASE2),),
    )
    return {row["table_name"] for row in cur.fetchall()}


if __name__ == "__main__":
    sys.exit(main())
