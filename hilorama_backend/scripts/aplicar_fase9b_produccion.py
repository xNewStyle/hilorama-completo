"""Aplicador protegido de FASE 9B para producción.

Este script nunca toma DATABASE_URL ni la URL de pruebas como entrada. Solo
acepta HILORAMA_FASE9B_PROD_DATABASE_URL y separa validación, preflight,
aplicación transaccional y verificación. No siembra ni modifica datos
comerciales: la única escritura posible es el DDL de la migración 002.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
PROD_DATABASE_URL_ENV = "HILORAMA_FASE9B_PROD_DATABASE_URL"
IGNORED_DATABASE_ENVIRONMENTS = ("DATABASE_URL", "HILORAMA_FASE9B_TEST_DATABASE_URL")
PRODUCTION_RESOURCE_CONFIRMATION = "hilorama-db"
MIGRATION_ID = "002_fase9_movimientos_auditoria"
ADVISORY_LOCK_KEY = 9_090_002
LOCK_TIMEOUT = "15s"
STATEMENT_TIMEOUT = "15min"

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
LEGACY_REQUIRED_TABLES = (
    "productos",
    "notas",
    "pagos",
    "clientes_sistema",
    "usuarios_sistema",
)
CONTADORES_PRELIGHT = (
    "productos",
    "notas",
    "movimientos_almacen",
    "auditoria_general",
    "pagos",
)
TABLAS_VERSIONES_CONOCIDAS = (
    "schema_migrations",
    "migration_versions",
    "migrations",
    "hilorama_migrations",
)
MOVIMIENTOS_CORE_COLUMNS = frozenset(
    {
        "id", "fecha", "usuario", "tipo", "marca", "hilo", "color", "codigo",
        "stock_anterior", "stock_nuevo", "cantidad", "campo", "valor_anterior",
        "valor_nuevo", "motivo",
    }
)
MOVIMIENTOS_FASE9B_COLUMNS = MOVIMIENTOS_CORE_COLUMNS | frozenset(
    {
        "cliente_sistema_id", "producto_id", "referencia_tipo", "referencia_id",
        "usuario_id", "device_id", "idempotency_key", "metadata_json", "fecha_creacion",
    }
)
AUDITORIA_FASE9B_COLUMNS = frozenset(
    {
        "id", "cliente_sistema_id", "usuario_id", "accion", "modulo", "entidad_tipo",
        "entidad_id", "descripcion", "datos_anteriores_json", "datos_nuevos_json",
        "resultado", "codigo_error", "ip", "user_agent", "device_id", "request_id",
        "fecha_creacion",
    }
)
INDICES_FASE9B = frozenset(
    {
        "idx_movimientos_almacen_fecha_desc",
        "idx_movimientos_almacen_producto_fecha",
        "idx_movimientos_almacen_referencia",
        "idx_movimientos_almacen_tipo_fecha",
        "uq_movimientos_almacen_cliente_idempotency_key",
        "idx_auditoria_general_fecha_desc",
        "idx_auditoria_general_cliente_fecha",
        "idx_auditoria_general_usuario_fecha",
        "idx_auditoria_general_modulo_accion_fecha",
    }
)
INDICE_LEGACY_GLOBAL = "uq_movimientos_almacen_idempotency_key"
_URL_SENSIBLE_RE = re.compile(r"(?i)postgres(?:ql)?://[^\s'\"<>]+")
_TEXTO_SENSIBLE_RE = re.compile(
    r"(?i)\b(password|password_hash|token|access_token|refresh_token|authorization|cookie|secret|database_url)\b"
    r"\s*([:=])\s*([^\s,;]+)"
)


class ProduccionFase9BError(RuntimeError):
    """Error controlado del aplicador de producción."""


@dataclass(frozen=True)
class ConexionProduccion:
    host: str
    puerto: int | None
    database: str
    usuario: str
    origen: str = PROD_DATABASE_URL_ENV

    def reporte_seguro(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "puerto": self.puerto,
            "database": self.database,
            "usuario": self.usuario,
            "origen": self.origen,
            "password": "[oculta]",
        }


def _sanitizar_texto(valor: Any) -> str:
    texto = str(valor or "")
    texto = _URL_SENSIBLE_RE.sub("postgresql://[oculta]", texto)
    return _TEXTO_SENSIBLE_RE.sub(
        lambda coincidencia: f"{coincidencia.group(1)}{coincidencia.group(2)}[oculto]",
        texto,
    )


def ruta_migracion() -> Path:
    return ROOT / "hilorama_backend" / "migrations" / f"{MIGRATION_ID}.sql"


def cargar_migracion() -> tuple[str, dict[str, Any]]:
    path = ruta_migracion()
    if not path.exists():
        raise ProduccionFase9BError(f"No se encontró la migración requerida: {path}")
    sql = path.read_text(encoding="utf-8")
    prohibidas = ("DROP DATABASE", "DROP TABLE", "DELETE FROM", "TRUNCATE ")
    encontradas = [sentencia for sentencia in prohibidas if sentencia in sql.upper()]
    if encontradas:
        raise ProduccionFase9BError(
            "La migración contiene operaciones no permitidas: " + ", ".join(encontradas)
        )
    return sql, {
        "id": MIGRATION_ID,
        "ruta": str(path),
        "sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "tiene_create_index_concurrently": "CREATE INDEX CONCURRENTLY" in sql.upper(),
        "tiene_dml": any(f"{palabra} " in sql.upper() for palabra in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")),
    }


def validar_url_produccion(database_url: str, origen: str = PROD_DATABASE_URL_ENV) -> ConexionProduccion:
    texto = str(database_url or "").strip()
    if not texto:
        raise ProduccionFase9BError(
            f"Falta {origen}. DATABASE_URL y HILORAMA_FASE9B_TEST_DATABASE_URL se ignoran deliberadamente."
        )
    parsed = urlparse(texto)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ProduccionFase9BError("La URL de producción debe usar PostgreSQL.")
    host = str(parsed.hostname or "").strip().lower()
    database = str(parsed.path or "").lstrip("/").strip().lower()
    usuario = str(parsed.username or "").strip() or "sin_usuario"
    if not host or not database:
        raise ProduccionFase9BError("La URL de producción debe incluir host y nombre de base.")
    if host in LOOPBACK_HOSTS:
        raise ProduccionFase9BError("Producción no puede apuntar a localhost o una dirección loopback.")
    if database.endswith("_test") or database == "hilorama_fase9b_test":
        raise ProduccionFase9BError("La base de producción no puede ser una base de prueba _test.")
    return ConexionProduccion(
        host=host,
        puerto=parsed.port,
        database=database,
        usuario=usuario,
        origen=origen,
    )


def obtener_url_produccion(environ=None) -> tuple[str, ConexionProduccion]:
    environ = os.environ if environ is None else environ
    url = environ.get(PROD_DATABASE_URL_ENV, "")
    return str(url or ""), validar_url_produccion(url)


def _cargar_psycopg():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise ProduccionFase9BError(
            "Falta psycopg2 en este entorno. Instala dependencias del backend antes de usar preflight o apply."
        ) from exc
    return psycopg2, RealDictCursor


def _row_dict(row) -> dict[str, Any]:
    return dict(row or {})


def _tabla_existe(cur, tabla: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables
            WHERE table_schema='public' AND table_name=%s
        ) AS existe
        """,
        (tabla,),
    )
    return bool(_row_dict(cur.fetchone()).get("existe"))


def _tablas_publicas(cur) -> set[str]:
    cur.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public'
        """
    )
    return {str(_row_dict(row).get("table_name") or "") for row in cur.fetchall()}


def _columnas_tabla(cur, tabla: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
        """,
        (tabla,),
    )
    return {str(_row_dict(row).get("column_name") or "") for row in cur.fetchall()}


def _indices_tabla(cur, tabla: str) -> set[str]:
    cur.execute(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname='public' AND tablename=%s
        """,
        (tabla,),
    )
    return {str(_row_dict(row).get("indexname") or "") for row in cur.fetchall()}


def _conteo_tabla(cur, tabla: str, existe: bool) -> int | None:
    if not existe:
        return None
    # tabla viene únicamente de CONTADORES_PRELIGHT, no de entrada externa.
    cur.execute(f"SELECT COUNT(*) AS total FROM {tabla}")
    return int(_row_dict(cur.fetchone()).get("total") or 0)


def _duplicados_idempotencia(cur, existe: bool, columnas: set[str]) -> int | None:
    if not existe or not {"cliente_sistema_id", "idempotency_key"}.issubset(columnas):
        return None
    cur.execute(
        """
        SELECT COUNT(*) AS total
        FROM (
            SELECT COALESCE(cliente_sistema_id, 0), idempotency_key
            FROM movimientos_almacen
            WHERE idempotency_key IS NOT NULL
            GROUP BY COALESCE(cliente_sistema_id, 0), idempotency_key
            HAVING COUNT(*) > 1
        ) AS duplicados
        """
    )
    return int(_row_dict(cur.fetchone()).get("total") or 0)


def _versiones_migracion(tablas: set[str]) -> dict[str, Any]:
    existente = next((tabla for tabla in TABLAS_VERSIONES_CONOCIDAS if tabla in tablas), None)
    return {
        "tabla": existente,
        "registro_aplicable": False,
        "accion": (
            "No se crea una tabla de versiones automáticamente; FASE 9B mantiene el alcance de la migración 002."
            if not existente
            else "Existe una tabla de versiones; el registro debe revisarse manualmente antes de usarla."
        ),
    }


def _estructura_final_valida(reporte: dict[str, Any]) -> bool:
    movimientos = set(reporte.get("columnas_movimientos") or ())
    auditoria = set(reporte.get("columnas_auditoria") or ())
    indices = set(reporte.get("indices") or ())
    return (
        MOVIMIENTOS_FASE9B_COLUMNS.issubset(movimientos)
        and AUDITORIA_FASE9B_COLUMNS.issubset(auditoria)
        and INDICES_FASE9B.issubset(indices)
        and INDICE_LEGACY_GLOBAL not in indices
    )


def recolectar_preflight(cur, info: ConexionProduccion) -> dict[str, Any]:
    """Consulta estructura y conteos; no ejecuta DDL ni DML."""
    cur.execute(
        """
        SELECT version() AS version_postgresql,
               current_database() AS database_actual,
               current_user AS usuario_actual
        """
    )
    servidor = _row_dict(cur.fetchone())
    tablas = _tablas_publicas(cur)
    existencia = {tabla: tabla in tablas for tabla in (*LEGACY_REQUIRED_TABLES, "movimientos_almacen", "auditoria_general")}
    columnas_movimientos = _columnas_tabla(cur, "movimientos_almacen") if existencia["movimientos_almacen"] else set()
    columnas_auditoria = _columnas_tabla(cur, "auditoria_general") if existencia["auditoria_general"] else set()
    indices = set()
    if existencia["movimientos_almacen"]:
        indices.update(_indices_tabla(cur, "movimientos_almacen"))
    if existencia["auditoria_general"]:
        indices.update(_indices_tabla(cur, "auditoria_general"))
    conteos = {tabla: _conteo_tabla(cur, tabla, tabla in tablas) for tabla in CONTADORES_PRELIGHT}
    cur.execute("SELECT COUNT(*) AS total FROM pg_stat_activity WHERE datname=current_database()")
    conexiones_activas = int(_row_dict(cur.fetchone()).get("total") or 0)

    bloqueos: list[str] = []
    advertencias: list[str] = []
    faltantes_legacy = [tabla for tabla in LEGACY_REQUIRED_TABLES if not existencia[tabla]]
    if faltantes_legacy:
        bloqueos.append("Faltan tablas legacy o de FASE 2: " + ", ".join(faltantes_legacy))
    if existencia["movimientos_almacen"]:
        faltantes_core = sorted(MOVIMIENTOS_CORE_COLUMNS - columnas_movimientos)
        if faltantes_core:
            bloqueos.append(
                "movimientos_almacen existe pero no tiene su contrato legacy mínimo: " + ", ".join(faltantes_core)
            )
    if existencia["auditoria_general"]:
        faltantes_auditoria = sorted(AUDITORIA_FASE9B_COLUMNS - columnas_auditoria)
        if faltantes_auditoria:
            bloqueos.append(
                "auditoria_general ya existe incompleta; la migración 002 no agrega sus columnas faltantes: "
                + ", ".join(faltantes_auditoria)
            )
    duplicados = _duplicados_idempotencia(cur, existencia["movimientos_almacen"], columnas_movimientos)
    if duplicados:
        bloqueos.append(
            f"Hay {duplicados} llave(s) idempotentes duplicadas por cliente; el índice único no podrá crearse."
        )
    if existencia["movimientos_almacen"] and INDICE_LEGACY_GLOBAL in indices:
        advertencias.append(
            "Se detectó el índice global legacy de idempotencia; 002 lo elimina y crea el índice compuesto por cliente."
        )
    if (conteos.get("movimientos_almacen") or 0) > 0:
        advertencias.append(
            "CREATE INDEX sin CONCURRENTLY bloqueará escrituras de movimientos mientras construye los índices."
        )
    if (conteos.get("auditoria_general") or 0) > 0:
        advertencias.append(
            "CREATE INDEX sin CONCURRENTLY bloqueará escrituras de auditoría mientras construye los índices."
        )
    if str(servidor.get("database_actual") or "").strip().lower() != info.database:
        bloqueos.append("La base abierta no coincide con el nombre de base validado en la URL de producción.")

    reporte = {
        "servidor": {
            "version_postgresql": str(servidor.get("version_postgresql") or ""),
            "database_actual": str(servidor.get("database_actual") or ""),
            "usuario_actual": str(servidor.get("usuario_actual") or ""),
        },
        "destino": info.reporte_seguro(),
        "tablas_publicas": len(tablas),
        "existencia_tablas": existencia,
        "columnas_movimientos": sorted(columnas_movimientos),
        "columnas_auditoria": sorted(columnas_auditoria),
        "movimientos_columnas_fase9b_presentes": len(MOVIMIENTOS_FASE9B_COLUMNS & columnas_movimientos),
        "auditoria_columnas_fase9b_presentes": len(AUDITORIA_FASE9B_COLUMNS & columnas_auditoria),
        "indices": sorted(indices),
        "conteos": conteos,
        "conexiones_activas": conexiones_activas,
        "duplicados_idempotencia": duplicados,
        "versiones_migracion": _versiones_migracion(tablas),
        "bloqueos": bloqueos,
        "advertencias": advertencias,
    }
    reporte["estructura_fase9b_completa"] = _estructura_final_valida(reporte)
    reporte["puede_aplicarse"] = not bloqueos
    return reporte


def _entorno_diagnostico(database_url: str) -> dict[str, str]:
    entorno = dict(os.environ)
    for clave in tuple(entorno):
        normalizada = str(clave).upper()
        if normalizada == "DATABASE_URL" or any(marca in normalizada for marca in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            entorno.pop(clave, None)
    entorno["DATABASE_URL"] = database_url
    return entorno


def ejecutar_diagnostico_previo(database_url: str, argumentos: list[str]) -> dict[str, Any]:
    script = ROOT / "hilorama_backend" / "scripts" / "diagnosticar_movimientos_auditoria.py"
    if not script.exists():
        return {"disponible": False, "motivo": "No se encontró el script de diagnóstico."}
    try:
        resultado = subprocess.run(
            [sys.executable, str(script), *argumentos],
            cwd=str(ROOT),
            env=_entorno_diagnostico(database_url),
            text=True,
            capture_output=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "disponible": False,
            "motivo": f"{exc.__class__.__name__}: {_sanitizar_texto(exc)}",
        }
    return {
        "disponible": True,
        "script": str(script),
        "argumentos": list(argumentos),
        "returncode": int(resultado.returncode),
        "stdout": _sanitizar_texto(resultado.stdout),
        "stderr": _sanitizar_texto(resultado.stderr),
    }


def ejecutar_preflight(database_url: str, info: ConexionProduccion, *, incluir_diagnostico: bool = True) -> dict[str, Any]:
    psycopg2, cursor_factory = _cargar_psycopg()
    try:
        with psycopg2.connect(database_url, cursor_factory=cursor_factory) as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor() as cur:
                reporte = recolectar_preflight(cur, info)
    except Exception as exc:
        raise ProduccionFase9BError(
            f"No se pudo completar el preflight de solo lectura: {exc.__class__.__name__}: {_sanitizar_texto(exc)}"
        ) from exc
    if incluir_diagnostico:
        reporte["diagnostico_previo"] = ejecutar_diagnostico_previo(database_url, ["--limit", "50"])
    return reporte


def _validar_destino_conectado(cur, info: ConexionProduccion) -> None:
    cur.execute(
        """
        SELECT current_database() AS database_actual,
               current_user AS usuario_actual,
               inet_server_addr()::text AS host_servidor,
               inet_server_port() AS puerto_servidor
        """
    )
    real = _row_dict(cur.fetchone())
    database_actual = str(real.get("database_actual") or "").strip().lower()
    host_servidor = str(real.get("host_servidor") or "").strip().lower().split("/", 1)[0]
    if database_actual != info.database:
        raise ProduccionFase9BError("La conexión abierta no coincide con la base de producción validada.")
    if host_servidor in LOOPBACK_HOSTS:
        raise ProduccionFase9BError("La conexión abierta reportó un servidor loopback; se cancela por seguridad.")


def _confirmaciones_apply_validas(confirm_production: str | None, backup_confirmed: bool) -> None:
    if confirm_production != PRODUCTION_RESOURCE_CONFIRMATION:
        raise ProduccionFase9BError(
            f"Falta --confirm-production {PRODUCTION_RESOURCE_CONFIRMATION} para aplicar en producción."
        )
    if not backup_confirmed:
        raise ProduccionFase9BError("Falta --backup-confirmed. Confirma primero el respaldo de producción.")


def aplicar_en_conexion(
    conn,
    info: ConexionProduccion,
    sql: str,
    *,
    recolector: Callable[[Any, ConexionProduccion], dict[str, Any]] = recolectar_preflight,
    validador_destino: Callable[[Any, ConexionProduccion], None] = _validar_destino_conectado,
) -> dict[str, Any]:
    """Aplica sólo el DDL de 002 y hace rollback ante cualquier fallo."""
    cur = conn.cursor()
    lock_adquirido = False
    try:
        cur.execute("SELECT pg_try_advisory_lock(%s) AS adquirido", (ADVISORY_LOCK_KEY,))
        lock_adquirido = bool(_row_dict(cur.fetchone()).get("adquirido"))
        if not lock_adquirido:
            raise ProduccionFase9BError("Otra ejecución de FASE 9B ya tiene el advisory lock. No se aplicó nada.")
        cur.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
        validador_destino(cur, info)
        antes = recolector(cur, info)
        if antes.get("bloqueos"):
            raise ProduccionFase9BError("Preflight bloqueó la migración: " + " | ".join(antes["bloqueos"]))
        if antes.get("estructura_fase9b_completa"):
            conn.commit()
            return {
                "ok": True,
                "aplicada": False,
                "idempotente": True,
                "preflight": antes,
                "verificacion": antes,
            }
        cur.execute(sql)
        despues = recolector(cur, info)
        if not despues.get("estructura_fase9b_completa"):
            raise ProduccionFase9BError(
                "La verificación dentro de la transacción no encontró el contrato completo de FASE 9B."
            )
        conn.commit()
        return {
            "ok": True,
            "aplicada": True,
            "idempotente": False,
            "preflight": antes,
            "verificacion": despues,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            if lock_adquirido:
                cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
                conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass


def aplicar_migracion(database_url: str, info: ConexionProduccion) -> dict[str, Any]:
    sql, migracion = cargar_migracion()
    psycopg2, cursor_factory = _cargar_psycopg()
    try:
        with psycopg2.connect(database_url, cursor_factory=cursor_factory) as conn:
            resultado = aplicar_en_conexion(conn, info, sql)
    except Exception as exc:
        if isinstance(exc, ProduccionFase9BError):
            raise
        raise ProduccionFase9BError(
            f"No se aplicó FASE 9B. Se solicitó rollback: {exc.__class__.__name__}: {_sanitizar_texto(exc)}"
        ) from exc
    resultado["migracion"] = migracion
    resultado["versiones_migracion"] = {
        "registrada": False,
        "motivo": "No existe una tabla de versiones conocida; este aplicador no crea metadatos nuevos automáticamente.",
    }
    return resultado


def verificar_migracion(database_url: str, info: ConexionProduccion, fecha_desde: str) -> dict[str, Any]:
    reporte = ejecutar_preflight(database_url, info, incluir_diagnostico=False)
    normal = ejecutar_diagnostico_previo(database_url, ["--desde", fecha_desde, "--strict"])
    historico = ejecutar_diagnostico_previo(database_url, ["--incluir-historicos"])
    return {
        "estructura_fase9b_completa": reporte.get("estructura_fase9b_completa"),
        "regla_temporal_movimientos": "COALESCE(fecha, fecha_creacion): fecha conserva la cronología canónica y fecha_creacion solo cubre nulos.",
        "alcance_diagnosticos": {
            "normal": f"Hallazgos con fecha_referencia_movimiento desde {fecha_desde}.",
            "historico": "Hallazgos informativos sin corte temporal; no bloquean por sí mismos el deploy.",
        },
        "preflight": reporte,
        "diagnostico_normal_desde": normal,
        "diagnostico_historico": historico,
    }


def _imprimir_reporte(titulo: str, reporte: dict[str, Any]) -> None:
    print(titulo)
    print(json.dumps(reporte, ensure_ascii=False, indent=2, default=str))


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aplicador protegido de FASE 9B para producción.")
    parser.add_argument("--check-config", action="store_true", help="Valida URL y destino sin abrir PostgreSQL.")
    parser.add_argument("--preflight", action="store_true", help="Ejecuta únicamente verificaciones de lectura.")
    parser.add_argument("--apply", action="store_true", help="Aplica sólo si también se indica --preflight en la misma ejecución.")
    parser.add_argument("--preflight-and-apply", action="store_true", help="Atajo seguro equivalente a --preflight --apply.")
    parser.add_argument("--verify", action="store_true", help="Verifica estructura y diagnóstico sin modificar datos.")
    parser.add_argument("--migration-date", default=date.today().isoformat(), help="Fecha AAAA-MM-DD para diagnóstico normal en verify.")
    parser.add_argument("--confirm-production", help=f"Debe ser literalmente {PRODUCTION_RESOURCE_CONFIRMATION} para aplicar.")
    parser.add_argument("--backup-confirmed", action="store_true", help="Confirma que existe un respaldo de producción verificado.")
    return parser


def _validar_modos(args, parser: argparse.ArgumentParser) -> tuple[bool, bool, bool, bool]:
    if args.preflight_and_apply:
        args.preflight = True
        args.apply = True
    if args.check_config and any((args.preflight, args.apply, args.verify)):
        parser.error("--check-config no se combina con otros modos.")
    if args.verify and any((args.preflight, args.apply)):
        parser.error("--verify no se combina con preflight ni apply.")
    if not any((args.check_config, args.preflight, args.apply, args.verify)):
        parser.error("Indica uno de: --check-config, --preflight, --preflight-and-apply o --verify.")
    if args.apply and not args.preflight:
        parser.error("--apply exige --preflight en la misma ejecución o --preflight-and-apply.")
    return args.check_config, args.preflight, args.apply, args.verify


def main(argv=None, environ=None) -> int:
    parser = _construir_parser()
    args = parser.parse_args(argv)
    check_config, preflight_solicitado, apply_solicitado, verify_solicitado = _validar_modos(args, parser)
    try:
        database_url, info = obtener_url_produccion(environ)
        _, migracion = cargar_migracion()
    except ProduccionFase9BError as exc:
        print(f"BLOQUEADO: {_sanitizar_texto(exc)}")
        return 2

    configuracion = {"destino": info.reporte_seguro(), "migracion": migracion, "ignora": list(IGNORED_DATABASE_ENVIRONMENTS)}
    if check_config:
        _imprimir_reporte("Configuración válida; no se abrió PostgreSQL.", configuracion)
        return 0

    if apply_solicitado:
        try:
            _confirmaciones_apply_validas(args.confirm_production, args.backup_confirmed)
        except ProduccionFase9BError as exc:
            print(f"BLOQUEADO: {_sanitizar_texto(exc)}")
            return 2

    try:
        if preflight_solicitado:
            preflight = ejecutar_preflight(database_url, info)
            _imprimir_reporte("Preflight FASE 9B (solo lectura)", preflight)
            if preflight.get("bloqueos"):
                return 2
        if apply_solicitado:
            resultado = aplicar_migracion(database_url, info)
            _imprimir_reporte("Aplicación FASE 9B", resultado)
        if verify_solicitado:
            try:
                date.fromisoformat(args.migration_date)
            except ValueError as exc:
                raise ProduccionFase9BError("--migration-date debe usar AAAA-MM-DD.") from exc
            verificacion = verificar_migracion(database_url, info, args.migration_date)
            _imprimir_reporte("Verificación FASE 9B (solo lectura)", verificacion)
            normal = verificacion["diagnostico_normal_desde"]
            return 1 if normal.get("disponible") and normal.get("returncode") == 1 else 0
    except ProduccionFase9BError as exc:
        print(f"BLOQUEADO: {_sanitizar_texto(exc)}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
