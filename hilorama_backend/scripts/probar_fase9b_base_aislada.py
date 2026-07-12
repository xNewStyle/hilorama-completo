"""Ensayo FASE 9B contra una base PostgreSQL local y desechable.

Este script nunca usa DATABASE_URL como entrada. Solo acepta
HILORAMA_FASE9B_TEST_DATABASE_URL y rechaza hosts remotos y bases cuyo nombre
no termine en ``_test``. No crea, borra ni reemplaza bases de datos: exige una
base local, vacia y creada previamente por la persona que ejecuta el ensayo.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from ipaddress import ip_interface
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROOT = REPO_ROOT
TEST_DATABASE_URL_ENV = "HILORAMA_FASE9B_TEST_DATABASE_URL"
LOCAL_POSTGRES_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
BLOCKED_HOST_PARTS = ("render", "onrender", "amazonaws", "railway", "neon", "supabase", "production")
BACKEND_REQUIRED_MODULES = (
    "hilorama_backend.services.movimientos_almacen_service",
    "hilorama_backend.services.auditoria_service",
    "hilorama_backend.app",
)
BASE_TABLES = (
    "productos",
    "clientes",
    "notas",
    "items",
    "pagos",
    "movimientos_almacen",
    "auditoria_general",
    "clientes_sistema",
    "usuarios_sistema",
    "dispositivos_autorizados",
    "sesiones_activas",
    "licencias_eventos",
)


class BaseAisladaError(RuntimeError):
    """Se levanta antes de conectarse cuando la URL no es de ensayo local."""


@dataclass(frozen=True)
class ConexionPrueba:
    host: str
    puerto: int | None
    database: str
    usuario: str
    origen: str = TEST_DATABASE_URL_ENV

    def reporte_seguro(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "puerto": self.puerto,
            "database": self.database,
            "usuario": self.usuario,
            "origen": self.origen,
            "password": "[oculta]",
            "aislada": True,
        }


BASE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS productos (
    id SERIAL PRIMARY KEY,
    codigo TEXT NOT NULL,
    codigo_barras TEXT,
    marca TEXT NOT NULL,
    hilo TEXT NOT NULL,
    color TEXT NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'OK',
    precio NUMERIC NOT NULL DEFAULT 0,
    costo_neto NUMERIC NOT NULL DEFAULT 0,
    volumetrico NUMERIC NOT NULL DEFAULT 1,
    tipo_producto TEXT NOT NULL DEFAULT 'INVENTARIO',
    es_inventariable BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    telefono TEXT,
    direccion JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS notas (
    id TEXT PRIMARY KEY,
    cliente_id INTEGER,
    cliente TEXT,
    estado TEXT NOT NULL DEFAULT 'COTIZACION',
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fecha_pago TIMESTAMPTZ,
    total NUMERIC NOT NULL DEFAULT 0,
    envio JSONB,
    paqueteria TEXT,
    comprobante TEXT,
    observaciones TEXT,
    notas TEXT,
    pedido TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    codigo TEXT NOT NULL,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    cantidad NUMERIC NOT NULL,
    precio NUMERIC NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pagos (
    id SERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    comprobante TEXT,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Simula la tabla legacy previa a FASE 9B para ensayar ALTER e indices.
CREATE TABLE IF NOT EXISTS movimientos_almacen (
    id BIGSERIAL PRIMARY KEY,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    usuario TEXT DEFAULT 'ADMIN',
    tipo TEXT NOT NULL,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    codigo TEXT,
    stock_anterior INTEGER,
    stock_nuevo INTEGER,
    cantidad INTEGER NOT NULL DEFAULT 0,
    campo TEXT,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    motivo TEXT,
    -- Estado parcial temprano de FASE 9B: permite probar que el indice
    -- global anterior se elimina y se reemplaza por el compuesto.
    idempotency_key TEXT
);
"""


class ConexionCompat:
    """Adaptador minimo para reutilizar servicios con una conexion psycopg2."""

    def __init__(self, conn, cursor_factory):
        self.conn = conn
        self.cur = conn.cursor(cursor_factory=cursor_factory)

    def execute(self, query, params=None):
        self.cur.execute(query, params or ())
        return self

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

    def close(self):
        self.cur.close()


def validar_url_base_prueba(database_url: str, origen: str = TEST_DATABASE_URL_ENV) -> ConexionPrueba:
    """Valida una URL sin conectarse ni revelar password."""
    texto = str(database_url or "").strip()
    if not texto:
        raise BaseAisladaError(f"Falta {origen}. DATABASE_URL se ignora deliberadamente.")
    parsed = urlparse(texto)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise BaseAisladaError("La base de prueba debe usar una URL PostgreSQL.")
    host = (parsed.hostname or "").strip().lower()
    database = (parsed.path or "").lstrip("/").strip().lower()
    usuario = (parsed.username or "").strip() or "sin_usuario"
    if not host or not database:
        raise BaseAisladaError("La URL de prueba debe incluir host y nombre de base.")
    if any(parte in host for parte in BLOCKED_HOST_PARTS):
        raise BaseAisladaError("Host de produccion/remoto detectado. Solo se permite PostgreSQL local.")
    if host not in LOCAL_POSTGRES_HOSTS:
        raise BaseAisladaError("No se puede demostrar aislamiento: solo se permiten localhost, 127.0.0.1 o ::1.")
    if not database.endswith("_test"):
        raise BaseAisladaError("Base de prueba requerida: el nombre debe terminar en _test.")
    if database in {"postgres", "template0", "template1"} or "prod" in database:
        raise BaseAisladaError("El nombre de la base no es seguro para un ensayo de prueba.")
    return ConexionPrueba(host=host, puerto=parsed.port, database=database, usuario=usuario, origen=origen)


def obtener_url_base_prueba(environ=None) -> tuple[str, ConexionPrueba]:
    environ = os.environ if environ is None else environ
    url = environ.get(TEST_DATABASE_URL_ENV, "")
    return url, validar_url_base_prueba(url)


_URL_POSTGRES_SENSIBLE_RE = re.compile(r"(?i)postgres(?:ql)?://[^\s'\"<>]+")
_CAMPO_SENSIBLE_DIAGNOSTICO_RE = re.compile(
    r"(?i)\b(password|password_hash|token|access_token|refresh_token|authorization|cookie|secret|database_url)\b"
    r"\s*([:=])\s*([^\s,;]+)"
)
_MARCAS_VARIABLE_ENTORNO_SENSIBLE = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY", "CREDENTIAL")


def _sanitizar_texto_diagnostico(valor: Any) -> str:
    """Conserva el diagnostico util del hijo sin revelar credenciales."""
    texto = str(valor or "")
    texto = _URL_POSTGRES_SENSIBLE_RE.sub("postgresql://[oculta]", texto)
    return _CAMPO_SENSIBLE_DIAGNOSTICO_RE.sub(
        lambda coincidencia: f"{coincidencia.group(1)}{coincidencia.group(2)}[oculto]",
        texto,
    )


def _destino_diagnostico_seguro(info: ConexionPrueba) -> dict[str, Any]:
    return {
        "host": info.host,
        "puerto": info.puerto,
        "database": info.database,
        "aislada": True,
    }


def _entorno_diagnostico_aislado(database_url: str) -> tuple[dict[str, str], ConexionPrueba]:
    """Entrega al diagnostico solo la URL validada del ensayo local.

    El diagnostico legacy lee DATABASE_URL; se la asignamos exclusivamente desde
    HILORAMA_FASE9B_TEST_DATABASE_URL ya validada, nunca desde el ambiente normal.
    """
    info = validar_url_base_prueba(database_url, origen=TEST_DATABASE_URL_ENV)
    entorno = dict(os.environ)
    for clave in tuple(entorno):
        clave_normalizada = str(clave).upper()
        if (
            clave_normalizada in {"DATABASE_URL", TEST_DATABASE_URL_ENV}
            or any(marca in clave_normalizada for marca in _MARCAS_VARIABLE_ENTORNO_SENSIBLE)
        ):
            entorno.pop(clave, None)
    entorno[TEST_DATABASE_URL_ENV] = database_url
    entorno["DATABASE_URL"] = entorno[TEST_DATABASE_URL_ENV]
    return entorno, info


def _cargar_psycopg():
    try:
        import psycopg2
        from psycopg2.extras import Json, RealDictCursor
    except ImportError as exc:
        raise BaseAisladaError(
            "Falta psycopg2 en este entorno. Instala dependencias del backend antes de ejecutar --run."
        ) from exc
    return psycopg2, Json, RealDictCursor


def _validar_importaciones_backend() -> None:
    """Confirma imports requeridos antes de abrir PostgreSQL o modificar la base."""
    try:
        for modulo in BACKEND_REQUIRED_MODULES:
            importlib.import_module(modulo)
    except Exception as exc:
        raise BaseAisladaError(
            "No se pudieron importar los modulos backend requeridos antes de abrir PostgreSQL. "
            "Verifica dependencias e importaciones del backend."
        ) from exc


def _sql_path(nombre: str) -> Path:
    path = ROOT / "hilorama_backend" / "migrations" / nombre
    if not path.exists():
        raise BaseAisladaError(f"No se encontro la migracion requerida: {path}")
    return path


def _table_exists(cur, tabla: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables
            WHERE table_schema='public' AND table_name=%s
        ) AS existe
        """,
        (tabla,),
    )
    return bool(cur.fetchone()["existe"])


def _count(cur, tabla: str) -> int:
    if not _table_exists(cur, tabla):
        return 0
    cur.execute(f"SELECT COUNT(*) AS total FROM {tabla}")
    return int(cur.fetchone()["total"] or 0)


def _conteos(cur) -> dict[str, int]:
    cur.execute(
        """
        SELECT COUNT(*) AS total
        FROM information_schema.tables
        WHERE table_schema='public'
        """
    )
    return {
        "tablas": int(cur.fetchone()["total"] or 0),
        "productos": _count(cur, "productos"),
        "notas": _count(cur, "notas"),
        "movimientos": _count(cur, "movimientos_almacen"),
        "auditorias": _count(cur, "auditoria_general"),
    }


def _asegurar_base_vacia(cur):
    existentes = []
    for tabla in BASE_TABLES:
        total = _count(cur, tabla)
        if total:
            existentes.append(f"{tabla}={total}")
    if existentes:
        raise BaseAisladaError(
            "La base de prueba no esta vacia. El ensayo no borra ni reemplaza datos existentes: "
            + ", ".join(existentes)
        )


def _ejecutar_sql(conn, sql_path: Path):
    sql = sql_path.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _crear_esquema_base(conn):
    try:
        with conn.cursor() as cur:
            cur.execute(BASE_SCHEMA_SQL)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _crear_indice_legacy(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_movimientos_almacen_idempotency_key
            ON movimientos_almacen(idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
    conn.commit()


def _indice_existe(cur, nombre: str) -> bool:
    cur.execute("SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=%s) AS existe", (nombre,))
    return bool(cur.fetchone()["existe"])


def _columnas(cur, tabla: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (tabla,),
    )
    return {row["column_name"] for row in cur.fetchall()}


def _verificar_migracion(conn, legado_esperado: bool) -> dict[str, Any]:
    with conn.cursor() as cur:
        mov_cols = _columnas(cur, "movimientos_almacen")
        audit_cols = _columnas(cur, "auditoria_general")
        requeridas_mov = {
            "cliente_sistema_id", "producto_id", "referencia_tipo", "referencia_id",
            "usuario_id", "device_id", "idempotency_key", "metadata_json", "fecha_creacion",
        }
        requeridas_audit = {
            "cliente_sistema_id", "usuario_id", "accion", "modulo", "entidad_tipo",
            "entidad_id", "descripcion", "datos_anteriores_json", "datos_nuevos_json",
            "resultado", "codigo_error", "device_id", "request_id", "fecha_creacion",
        }
        if not requeridas_mov.issubset(mov_cols):
            raise AssertionError("Faltan columnas de movimientos tras la migracion.")
        if not requeridas_audit.issubset(audit_cols):
            raise AssertionError("Faltan columnas de auditoria tras la migracion.")
        global_old = _indice_existe(cur, "uq_movimientos_almacen_idempotency_key")
        compuesto = _indice_existe(cur, "uq_movimientos_almacen_cliente_idempotency_key")
        if legado_esperado and global_old:
            raise AssertionError("El indice global legacy no fue eliminado.")
        if not compuesto:
            raise AssertionError("No existe el indice compuesto de idempotencia por cliente.")
        return {
            "columnas_movimientos": len(mov_cols),
            "columnas_auditoria": len(audit_cols),
            "indice_global_legacy": global_old,
            "indice_compuesto_cliente": compuesto,
        }


def _sembrar_datos_legacy(conn, run_tag: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO productos(codigo, marca, hilo, color, stock, estado, precio, costo_neto, volumetrico, tipo_producto, es_inventariable)
            VALUES (%s,'F9B','LEGACY','LEGACY',20,'OK',80,35,1,'INVENTARIO',TRUE)
            """,
            (f"{run_tag}-LEGACY",),
        )
        cur.execute(
            """
            INSERT INTO movimientos_almacen(tipo, codigo, cantidad, stock_anterior, stock_nuevo, motivo)
            VALUES ('STOCK_INICIAL',%s,20,0,20,'Registro legacy ficticio para ensayo FASE 9B')
            """,
            (f"{run_tag}-LEGACY",),
        )
    conn.commit()


def _insertar_clientes_sistema(conn, run_tag: str) -> dict[str, int]:
    resultado = {}
    with conn.cursor() as cur:
        for etiqueta in ("CLIENTE_A", "CLIENTE_B"):
            cur.execute(
                """
                INSERT INTO clientes_sistema(nombre_negocio, contacto, estado, fecha_vencimiento, max_dispositivos, puede_actualizar, plan)
                VALUES (%s,'FASE9B TEST','activo',CURRENT_DATE + 30,10,FALSE,'test')
                RETURNING id
                """,
                (f"{run_tag}-{etiqueta}",),
            )
            resultado[etiqueta] = cur.fetchone()["id"]
    conn.commit()
    return resultado


def _seed_producto(conn, codigo: str, stock: int, color: str = "PRUEBA") -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO productos(codigo, marca, hilo, color, stock, estado, precio, costo_neto, volumetrico, tipo_producto, es_inventariable)
            VALUES (%s,'F9B','HILO_TEST',%s,%s,'OK',80,35,1,'INVENTARIO',TRUE)
            RETURNING *
            """,
            (codigo, color, stock),
        )
        producto = cur.fetchone()
    conn.commit()
    return dict(producto)


def _probar_idempotencia_servicio(conn, cursor_factory, clientes: dict[str, int], producto: dict[str, Any]) -> dict[str, Any]:
    from hilorama_backend.services.movimientos_almacen_service import registrar_movimiento_almacen

    with conn.cursor(cursor_factory=cursor_factory) as cur:
        columnas = _columnas(cur, "movimientos_almacen")
    adapter = ConexionCompat(conn, cursor_factory)
    try:
        datos = {
            "producto": producto,
            "tipo": "CORRECCION",
            "cantidad": 0,
            "stock_anterior": int(producto["stock"]),
            "stock_nuevo": int(producto["stock"]),
            "motivo": "Ensayo idempotencia entre empresas",
            "referencia_tipo": "ENSAYO",
            "referencia_id": "123",
            "idempotency_key": "VENTA:PAGO:123",
        }
        primero_a = registrar_movimiento_almacen(adapter, columnas, cliente_sistema_id=clientes["CLIENTE_A"], **datos)
        repetido_a = registrar_movimiento_almacen(adapter, columnas, cliente_sistema_id=clientes["CLIENTE_A"], **datos)
        primero_b = registrar_movimiento_almacen(adapter, columnas, cliente_sistema_id=clientes["CLIENTE_B"], **datos)
        repetido_b = registrar_movimiento_almacen(adapter, columnas, cliente_sistema_id=clientes["CLIENTE_B"], **datos)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        adapter.close()

    with conn.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute(
            """
            SELECT cliente_sistema_id, COUNT(*) AS total
            FROM movimientos_almacen
            WHERE idempotency_key='VENTA:PAGO:123'
            GROUP BY cliente_sistema_id
            ORDER BY cliente_sistema_id
            """
        )
        filas = cur.fetchall()
    if not primero_a["creado"] or not primero_b["creado"] or not repetido_a["idempotente"] or not repetido_b["idempotente"]:
        raise AssertionError("La idempotencia por cliente no devolvio los estados esperados.")
    if len(filas) != 2 or any(int(fila["total"]) != 1 for fila in filas):
        raise AssertionError("La misma llave no quedo registrada una vez por cada cliente ficticio.")
    return {"registros_validos": len(filas), "misma_llave": "VENTA:PAGO:123"}


def _configurar_backend_prueba(database_url: str):
    """Importa Flask solo despues de validar y preparar la base aislada."""
    os.environ["DATABASE_URL"] = database_url
    os.environ["HILORAMA_DATA_MODE"] = "local"
    try:
        from hilorama_backend import app as backend
    except Exception as exc:
        raise BaseAisladaError(
            "No se pudo importar el backend para la prueba HTTP local. "
            "Verifica Flask, flask-cors y dependencias del backend."
        ) from exc
    backend.app.config.update(TESTING=True)
    return backend


def _sembrar_usuario(conn, backend, cliente_id: int, usuario: str, rol: str, password: str) -> None:
    password_hash = backend._hash_password_sistema(password)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO usuarios_sistema(cliente_id, nombre, usuario, password_hash, rol, activo)
            VALUES (%s,%s,%s,%s,%s,TRUE)
            """,
            (cliente_id, f"Usuario {rol}", usuario, password_hash, rol),
        )
    conn.commit()


def _login(flask_app, usuario: str, password: str, device: str) -> str:
    respuesta = flask_app.test_client().post(
        "/api/auth/login",
        json={
            "usuario": usuario,
            "password": password,
            "device_id_hash": device,
            "modulo_actual": "fase9b_test",
            "nombre_equipo": "FASE9B TEST",
            "sistema_operativo": "test",
            "app_version": "fase9b-test",
        },
    )
    data = respuesta.get_json() or {}
    if respuesta.status_code != 200 or not data.get("token"):
        raise AssertionError(f"Login de prueba fallo: HTTP {respuesta.status_code}.")
    return data["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _insertar_cliente_comercial(conn, json_adapter, run_tag: str) -> int:
    direccion = {
        "calle": "Calle Prueba",
        "numero_ext": "1",
        "colonia": "Centro",
        "codigo_postal": "01000",
        "estado": "CDMX",
        "municipio": "Alvaro Obregon",
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO clientes(nombre, telefono, direccion) VALUES (%s,'5512345678',%s) RETURNING id",
            (f"Cliente comercial {run_tag}", json_adapter(direccion)),
        )
        cliente_id = cur.fetchone()["id"]
    conn.commit()
    return cliente_id


def _insertar_nota(conn, json_adapter, nota_id: str, cliente_id: int, estado: str, items: list[dict[str, Any]], *, fecha_historica=None):
    envio = {"tipo": "Prueba", "paqueteria": "Prueba", "precio": 25}
    subtotal = sum(float(item["cantidad"]) * float(item["precio"]) for item in items)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notas(id, cliente_id, cliente, estado, fecha, fecha_pago, total, envio, paqueteria, observaciones)
            VALUES (%s,%s,'Cliente prueba',%s,%s,%s,%s,%s,'Prueba','Nota ficticia FASE9B')
            """,
            (
                nota_id,
                cliente_id,
                estado,
                fecha_historica or datetime.now(),
                fecha_historica if estado == "PAGADA" else None,
                subtotal,
                json_adapter(envio),
            ),
        )
        for item in items:
            cur.execute(
                """
                INSERT INTO items(nota_id, codigo, marca, hilo, color, cantidad, precio)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    nota_id,
                    item["codigo"],
                    item.get("marca", "F9B"),
                    item.get("hilo", "HILO_TEST"),
                    item.get("color", "PRUEBA"),
                    item["cantidad"],
                    item["precio"],
                ),
            )
    conn.commit()


def _scalar(conn, query: str, params=()) -> Any:
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    return row["valor"] if row else None


def _instalar_fallo_movimiento(conn, producto_id: int):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE OR REPLACE FUNCTION f9b_fallar_movimiento() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.producto_id = {int(producto_id)} AND UPPER(COALESCE(NEW.tipo, '')) = 'VENTA' THEN
                    RAISE EXCEPTION 'F9B_TEST_FORCED_MOVEMENT_FAILURE';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        cur.execute("CREATE TRIGGER trg_f9b_fallar_movimiento BEFORE INSERT ON movimientos_almacen FOR EACH ROW EXECUTE FUNCTION f9b_fallar_movimiento()")
    conn.commit()


def _retirar_fallo_movimiento(conn):
    # El endpoint HTTP usa otra conexion. Un rollback local es inocuo si esta
    # limpia y recupera esta conexion si una prueba previa la dejo abortada.
    try:
        conn.rollback()
    except Exception:
        pass
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS trg_f9b_fallar_movimiento ON movimientos_almacen")
        cur.execute("DROP FUNCTION IF EXISTS f9b_fallar_movimiento()")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                EXISTS(
                    SELECT 1
                    FROM pg_trigger
                    WHERE tgname=%s AND NOT tgisinternal
                ) AS trigger_existe,
                EXISTS(
                    SELECT 1
                    FROM pg_proc
                    WHERE proname=%s
                ) AS funcion_existe
            """,
            ("trg_f9b_fallar_movimiento", "f9b_fallar_movimiento"),
        )
        estado = cur.fetchone() or {}
    conn.commit()
    if estado.get("trigger_existe") or estado.get("funcion_existe"):
        raise AssertionError("No se pudo confirmar la limpieza del trigger de fallo FASE 9B.")


def _contar_movimientos_nota(conn, nota_id: str, tipo=None) -> int:
    query = "SELECT COUNT(*) AS valor FROM movimientos_almacen WHERE referencia_tipo='NOTA' AND referencia_id=%s"
    params: tuple[Any, ...] = (nota_id,)
    if tipo:
        query += " AND tipo=%s"
        params += (tipo,)
    return int(_scalar(conn, query, params) or 0)


def _contar_pagos_nota(conn, nota_id: str) -> int:
    return int(_scalar(conn, "SELECT COUNT(*) AS valor FROM pagos WHERE nota_id=%s", (nota_id,)) or 0)


def _resumen_movimientos_nota(conn, nota_id: str, tipos=None) -> list[dict[str, Any]]:
    """Devuelve solo campos no sensibles para diagnosticar un escenario FASE 9B."""
    filtros = ["UPPER(COALESCE(referencia_tipo, ''))='NOTA'", "referencia_id=%s"]
    valores: list[Any] = [str(nota_id)]
    if tipos:
        tipos_normalizados = tuple(sorted({str(tipo).strip().upper() for tipo in tipos if str(tipo).strip()}))
        if tipos_normalizados:
            filtros.append("UPPER(COALESCE(tipo, '')) IN (" + ",".join(["%s"] * len(tipos_normalizados)) + ")")
            valores.extend(tipos_normalizados)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT producto_id, tipo, cantidad, stock_anterior, stock_nuevo
            FROM movimientos_almacen
            WHERE {' AND '.join(filtros)}
            ORDER BY id ASC
            """,
            tuple(valores),
        )
        rows = cur.fetchall()
    resumen = []
    for row in rows:
        movimiento = dict(row or {})
        resumen.append(
            {
                "producto_id": movimiento.get("producto_id"),
                "tipo": str(movimiento.get("tipo") or ""),
                "cantidad": int(movimiento.get("cantidad") or 0),
                "stock_anterior": movimiento.get("stock_anterior"),
                "stock_nuevo": movimiento.get("stock_nuevo"),
            }
        )
    return resumen


def _probar_http_local(database_url: str, psycopg2, json_adapter, cursor_factory, clientes_sistema: dict[str, int], run_tag: str) -> dict[str, Any]:
    backend = _configurar_backend_prueba(database_url)
    flask_app = backend.app
    password = "F9B-temporal-local"
    usuarios = {
        "admin": f"f9b_admin_{run_tag}",
        "almacen_a": f"f9b_almacen_a_{run_tag}",
        "vendedor": f"f9b_vendedor_{run_tag}",
        "almacen_b": f"f9b_almacen_b_{run_tag}",
    }
    with psycopg2.connect(database_url, cursor_factory=cursor_factory) as conn:
        _sembrar_usuario(conn, backend, clientes_sistema["CLIENTE_A"], usuarios["admin"], "super_admin", password)
        _sembrar_usuario(conn, backend, clientes_sistema["CLIENTE_A"], usuarios["almacen_a"], "almacen", password)
        _sembrar_usuario(conn, backend, clientes_sistema["CLIENTE_A"], usuarios["vendedor"], "vendedor", password)
        _sembrar_usuario(conn, backend, clientes_sistema["CLIENTE_B"], usuarios["almacen_b"], "almacen", password)
        cliente_comercial = _insertar_cliente_comercial(conn, json_adapter, run_tag)

        producto_repetido = _seed_producto(conn, f"{run_tag}-REP", 20, "REPETIDO")
        producto_bueno = _seed_producto(conn, f"{run_tag}-OK", 100, "BUENO")
        producto_falla = _seed_producto(conn, f"{run_tag}-FAIL", 100, "FALLA")
        producto_concurrente = _seed_producto(conn, f"{run_tag}-CON", 100, "CONCURRENCIA")
        producto_ajuste = _seed_producto(conn, f"{run_tag}-AJ", 100, "AJUSTE")
        productos_escenarios = {
            int(producto_repetido["id"]),
            int(producto_bueno["id"]),
            int(producto_falla["id"]),
            int(producto_concurrente["id"]),
            int(producto_ajuste["id"]),
        }
        if len(productos_escenarios) != 5:
            raise AssertionError("Los escenarios FASE 9B reutilizan productos de prueba por error.")
        stock_inicial_repetido = int(producto_repetido["stock"])

        nota_repetida = f"{run_tag}-REPETIDA"
        _insertar_nota(
            conn,
            json_adapter,
            nota_repetida,
            cliente_comercial,
            "VENTA",
            [
                {"codigo": producto_repetido["codigo"], "cantidad": 3, "precio": 80, "color": "REPETIDO"},
                {"codigo": producto_repetido["codigo"], "cantidad": 4, "precio": 80, "color": "REPETIDO"},
                {"codigo": producto_repetido["codigo"], "cantidad": 2, "precio": 80, "color": "REPETIDO"},
            ],
        )

        respuesta_login_invalido = flask_app.test_client().post(
            "/api/auth/login",
            json={"usuario": usuarios["admin"], "password": "incorrecta", "device_id_hash": f"{run_tag}-invalid"},
        )
        if respuesta_login_invalido.status_code != 401:
            raise AssertionError("El login invalido no devolvio HTTP 401.")

        token_admin = _login(flask_app, usuarios["admin"], password, f"{run_tag}-admin-device")
        token_almacen_a = _login(flask_app, usuarios["almacen_a"], password, f"{run_tag}-almacen-a")
        token_vendedor = _login(flask_app, usuarios["vendedor"], password, f"{run_tag}-vendedor")
        _login(flask_app, usuarios["almacen_b"], password, f"{run_tag}-almacen-b")

        resultados_http: list[dict[str, Any]] = []

        def limpiar_diagnostico_http(valor):
            campos_sensibles = {"password", "password_hash", "token", "access_token", "refresh_token", "authorization", "cookie", "secret", "database_url"}
            if isinstance(valor, dict):
                return {
                    clave: "[oculto]" if str(clave).strip().lower() in campos_sensibles else limpiar_diagnostico_http(dato)
                    for clave, dato in valor.items()
                }
            if isinstance(valor, list):
                return [limpiar_diagnostico_http(dato) for dato in valor]
            return valor

        def esperar(nombre: str, respuesta, esperado: int, contexto=None):
            data = respuesta.get_json(silent=True) or {}
            resultados_http.append({"caso": nombre, "http": respuesta.status_code, "esperado": esperado})
            if respuesta.status_code != esperado:
                raise AssertionError(
                    f"{nombre}: se esperaba HTTP {esperado} y se obtuvo {respuesta.status_code}; "
                    f"respuesta={limpiar_diagnostico_http(data)}; "
                    f"contexto={limpiar_diagnostico_http(contexto or {})}"
                )
            return data

        resultados_http.append({"caso": "login_invalido", "http": respuesta_login_invalido.status_code, "esperado": 401})
        productos_data = esperar("listar_productos", flask_app.test_client().get("/api/productos", headers=_headers(token_admin)), 200)
        if not isinstance(productos_data.get("productos"), list):
            raise AssertionError("/api/productos no devolvio la estructura esperada.")

        esperar(
            "alta_producto",
            flask_app.test_client().post(
                "/api/almacen/productos",
                headers=_headers(token_admin),
                json={
                    "marca": "F9B",
                    "hilo": "HILO_TEST",
                    "color": "HTTP",
                    "codigo": f"{run_tag}-HTTP",
                    "stock": 60,
                    "precio": 80,
                    "costo_neto": 35,
                    "volumetrico": 1,
                    "tipo_producto": "INVENTARIO",
                    "motivo": "Alta ficticia para auditoria FASE9B",
                },
            ),
            200,
        )

        usuario_creado = esperar(
            "crear_usuario_cliente",
            flask_app.test_client().post(
                f"/api/admin/clientes/{clientes_sistema['CLIENTE_B']}/usuarios",
                headers=_headers(token_admin),
                json={
                    "nombre": "Usuario F9B",
                    "username": f"f9b_nuevo_{run_tag}",
                    "password_temporal": "TemporalF9B1",
                    "rol": "vendedor",
                    "activo": True,
                },
            ),
            200,
        )
        usuario_creado_id = (usuario_creado.get("usuario") or {}).get("id")
        if not usuario_creado_id:
            raise AssertionError("No se obtuvo el usuario creado para probar cambio de acceso.")
        esperar(
            "reset_password_usuario",
            flask_app.test_client().post(
                f"/api/admin/usuarios/{usuario_creado_id}/reset-password",
                headers=_headers(token_admin),
                json={"nueva_password_temporal": "TemporalF9B2"},
            ),
            200,
        )

        respuesta_pago = flask_app.test_client().post(
            "/api/pagos",
            headers=_headers(token_admin),
            json={"nota_id": nota_repetida, "comprobante": f"comprobantes/{run_tag}.png", "autorizacion_stock": "1"},
        )
        pago_data = esperar("pago_producto_repetido", respuesta_pago, 200)
        if pago_data.get("idempotente"):
            raise AssertionError("El primer pago no puede quedar idempotente.")
        stock_repetido = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_repetido["id"],)))
        if stock_repetido != stock_inicial_repetido - 9 or _contar_movimientos_nota(conn, nota_repetida, "VENTA") != 1 or _contar_pagos_nota(conn, nota_repetida) != 1:
            raise AssertionError("El pago con producto repetido no desconto exactamente 9 piezas en un movimiento.")

        repetido_data = esperar(
            "pago_repetido",
            flask_app.test_client().post(
                "/api/pagos",
                headers=_headers(token_admin),
                json={"nota_id": nota_repetida, "comprobante": f"comprobantes/{run_tag}.png", "autorizacion_stock": "1"},
            ),
            200,
        )
        if not repetido_data.get("idempotente"):
            raise AssertionError("El segundo pago no devolvio resultado idempotente.")
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_repetido["id"],))) != 11:
            raise AssertionError("El pago repetido modifico stock.")

        nota_rollback = f"{run_tag}-ROLLBACK"
        if nota_rollback == nota_repetida:
            raise AssertionError("Los escenarios de rollback y anulacion comparten nota por error.")
        _insertar_nota(
            conn,
            json_adapter,
            nota_rollback,
            cliente_comercial,
            "VENTA",
            [
                {"codigo": producto_bueno["codigo"], "cantidad": 2, "precio": 80, "color": "BUENO"},
                {"codigo": producto_falla["codigo"], "cantidad": 2, "precio": 80, "color": "FALLA"},
            ],
        )
        _instalar_fallo_movimiento(conn, int(producto_falla["id"]))
        try:
            esperar(
                "rollback_forzado",
                flask_app.test_client().post(
                    "/api/pagos",
                    headers=_headers(token_admin),
                    json={"nota_id": nota_rollback, "comprobante": f"comprobantes/{run_tag}-rollback.png"},
                ),
                500,
            )
        finally:
            _retirar_fallo_movimiento(conn)
        for producto in (producto_bueno, producto_falla):
            if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto["id"],))) != 100:
                raise AssertionError("El rollback dejo stock parcial modificado.")
        if _contar_movimientos_nota(conn, nota_rollback) or _contar_pagos_nota(conn, nota_rollback):
            raise AssertionError("El rollback dejo movimientos o pagos parciales.")
        if _scalar(conn, "SELECT estado AS valor FROM notas WHERE id=%s", (nota_rollback,)) != "VENTA":
            raise AssertionError("El rollback dejo la nota como pagada.")
        esperar(
            "reintento_tras_rollback",
            flask_app.test_client().post(
                "/api/pagos",
                headers=_headers(token_admin),
                json={"nota_id": nota_rollback, "comprobante": f"comprobantes/{run_tag}-rollback.png"},
            ),
            200,
        )
        if _contar_movimientos_nota(conn, nota_rollback, "VENTA") != 2 or _contar_pagos_nota(conn, nota_rollback) != 1:
            raise AssertionError("El reintento posterior al rollback no completo la transaccion.")

        nota_concurrente = f"{run_tag}-CONCURRENTE"
        _insertar_nota(
            conn,
            json_adapter,
            nota_concurrente,
            cliente_comercial,
            "VENTA",
            [{"codigo": producto_concurrente["codigo"], "cantidad": 3, "precio": 80, "color": "CONCURRENCIA"}],
        )
        respuestas_concurrentes: list[tuple[int, dict[str, Any]]] = []

        def pagar_concurrente():
            respuesta = flask_app.test_client().post(
                "/api/pagos",
                headers=_headers(token_admin),
                json={"nota_id": nota_concurrente, "comprobante": f"comprobantes/{run_tag}-con.png"},
            )
            respuestas_concurrentes.append((respuesta.status_code, respuesta.get_json() or {}))

        hilos = [threading.Thread(target=pagar_concurrente) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=20)
        if any(hilo.is_alive() for hilo in hilos):
            raise AssertionError("La prueba de concurrencia dejo un hilo bloqueado.")
        if sorted(status for status, _ in respuestas_concurrentes) != [200, 200]:
            raise AssertionError("Las solicitudes concurrentes no devolvieron respuesta controlada.")
        if sum(bool(data.get("idempotente")) for _, data in respuestas_concurrentes) != 1:
            raise AssertionError("La concurrencia no produjo exactamente un pago idempotente.")
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_concurrente["id"],))) != 97:
            raise AssertionError("La concurrencia dejo stock incorrecto.")
        if _contar_movimientos_nota(conn, nota_concurrente, "VENTA") != 1 or _contar_pagos_nota(conn, nota_concurrente) != 1:
            raise AssertionError("La concurrencia duplico movimientos o pagos.")

        ajustes: list[int] = []

        def ajustar_stock(valor: int, llave: str):
            respuesta = flask_app.test_client().patch(
                f"/api/almacen/productos/{producto_ajuste['id']}/stock",
                headers=_headers(token_almacen_a),
                json={"stock_nuevo": valor, "motivo": "Ensayo ajuste concurrente", "idempotency_key": llave},
            )
            ajustes.append(respuesta.status_code)

        hilos_ajuste = [
            threading.Thread(target=ajustar_stock, args=(110, f"{run_tag}-AJ-1")),
            threading.Thread(target=ajustar_stock, args=(120, f"{run_tag}-AJ-2")),
        ]
        for hilo in hilos_ajuste:
            hilo.start()
        for hilo in hilos_ajuste:
            hilo.join(timeout=20)
        if any(hilo.is_alive() for hilo in hilos_ajuste) or sorted(ajustes) != [200, 200]:
            raise AssertionError("Los ajustes concurrentes no terminaron correctamente.")
        final_ajuste = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_ajuste["id"],)))
        if final_ajuste not in {110, 120}:
            raise AssertionError("Los ajustes concurrentes dejaron un stock invalido.")

        stock_antes_anular = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_repetido["id"],)))
        ventas_antes_anular = _resumen_movimientos_nota(conn, nota_repetida, {"VENTA"})
        reposiciones_antes_anular = _resumen_movimientos_nota(
            conn,
            nota_repetida,
            {"CANCELACION_VENTA", "DEVOLUCION", "DEVOLUCION_POR_ANULACION", "STOCK_RESTABLECIDO_NOTA_PAGADA"},
        )
        salidas_venta = sum(abs(movimiento["cantidad"]) for movimiento in ventas_antes_anular if movimiento["cantidad"] < 0)
        reposiciones_previas = sum(movimiento["cantidad"] for movimiento in reposiciones_antes_anular if movimiento["cantidad"] > 0)
        stock_esperado_anulacion = stock_antes_anular + max(salidas_venta - reposiciones_previas, 0)
        respuesta_anulacion = flask_app.test_client().post(
            f"/api/notas/{nota_repetida}/anular",
            headers=_headers(token_admin),
            json={"autorizacion_stock": "1"},
        )
        datos_anulacion = respuesta_anulacion.get_json(silent=True) or {}
        resultados_http.append({"caso": "anular_venta_pagada", "http": respuesta_anulacion.status_code, "esperado": 200})
        respuesta_anulacion_segura = {
            "ok": datos_anulacion.get("ok"),
            "stock_devuelto": datos_anulacion.get("stock_devuelto"),
            "productos_devueltos": datos_anulacion.get("productos_devueltos") or [],
        }
        if respuesta_anulacion.status_code != 200:
            raise AssertionError(
                "anular_venta_pagada no devolvio respuesta esperada: "
                f"nota={nota_repetida}, producto={producto_repetido['id']}, "
                f"http={respuesta_anulacion.status_code}, respuesta={respuesta_anulacion_segura}"
            )
        stock_despues_anular = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_repetido["id"],)))
        ventas_despues_anular = _resumen_movimientos_nota(conn, nota_repetida, {"VENTA"})
        reposiciones_despues_anular = _resumen_movimientos_nota(
            conn,
            nota_repetida,
            {"CANCELACION_VENTA", "DEVOLUCION", "DEVOLUCION_POR_ANULACION", "STOCK_RESTABLECIDO_NOTA_PAGADA"},
        )
        estado_anulacion = _scalar(conn, "SELECT estado AS valor FROM notas WHERE id=%s", (nota_repetida,))
        if stock_despues_anular != stock_esperado_anulacion:
            raise AssertionError(
                "La anulacion no repuso el stock exacto: "
                f"nota={nota_repetida}, producto={producto_repetido['id']}, "
                f"stock_inicial={stock_inicial_repetido}, antes_anular={stock_antes_anular}, "
                f"despues={stock_despues_anular}, esperado={stock_esperado_anulacion}, "
                f"ventas_antes={ventas_antes_anular}, ventas_despues={ventas_despues_anular}, "
                f"reposiciones_antes={reposiciones_antes_anular}, reposiciones_despues={reposiciones_despues_anular}, "
                f"estado={estado_anulacion}, http={respuesta_anulacion.status_code}, "
                f"respuesta={respuesta_anulacion_segura}"
            )
        if _contar_movimientos_nota(conn, nota_repetida, "CANCELACION_VENTA") != 1:
            raise AssertionError(
                "La anulacion no registro movimiento de devolucion: "
                f"nota={nota_repetida}, reposiciones={reposiciones_despues_anular}"
            )
        stock_antes_anulacion_repetida = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_repetido["id"],)))
        devoluciones_antes_anulacion_repetida = _contar_movimientos_nota(conn, nota_repetida, "CANCELACION_VENTA")
        anulacion_repetida = esperar(
            "anulacion_repetida",
            flask_app.test_client().post(
                f"/api/notas/{nota_repetida}/anular",
                headers=_headers(token_admin),
                json={"autorizacion_stock": "1"},
            ),
            200,
        )
        if not anulacion_repetida.get("idempotente"):
            raise AssertionError("La segunda anulacion no respondio de forma idempotente.")
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_repetido["id"],))) != stock_antes_anulacion_repetida:
            raise AssertionError("La segunda anulacion modifico stock.")
        if _contar_movimientos_nota(conn, nota_repetida, "CANCELACION_VENTA") != devoluciones_antes_anulacion_repetida:
            raise AssertionError("La segunda anulacion creo una reposicion duplicada.")

        producto_reparacion = _seed_producto(conn, f"{run_tag}-REPARAR", 20, "REPARAR")
        nota_reparacion = f"{run_tag}-REPARAR"
        if int(producto_reparacion["id"]) in productos_escenarios:
            raise AssertionError("El escenario de reparacion reutilizo un producto de otro caso.")
        _insertar_nota(
            conn,
            json_adapter,
            nota_reparacion,
            cliente_comercial,
            "VENTA",
            [{"codigo": producto_reparacion["codigo"], "cantidad": 9, "precio": 80, "color": "REPARAR"}],
        )
        estado_pre_pago_reparacion = _scalar(conn, "SELECT estado AS valor FROM notas WHERE id=%s", (nota_reparacion,))
        stock_pre_pago_reparacion = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_reparacion["id"],)))
        if estado_pre_pago_reparacion != "VENTA" or stock_pre_pago_reparacion != 20:
            raise AssertionError("El escenario de reparacion no inicio con nota VENTA y stock 20.")
        if _contar_pagos_nota(conn, nota_reparacion) or _contar_movimientos_nota(conn, nota_reparacion):
            raise AssertionError("El escenario de reparacion reutilizo pago o movimientos previos.")
        clave_venta_reparacion = f"VENTA:PAGO:{nota_reparacion}:{producto_reparacion['id']}"
        if int(_scalar(conn, "SELECT COUNT(*) AS valor FROM movimientos_almacen WHERE idempotency_key=%s", (clave_venta_reparacion,)) or 0):
            raise AssertionError("El escenario de reparacion reutilizo una llave idempotente de venta.")
        pago_reparacion = esperar(
            "pago_para_reparacion_anulada",
            flask_app.test_client().post(
                "/api/pagos",
                headers=_headers(token_admin),
                json={
                    "nota_id": nota_reparacion,
                    "comprobante": f"comprobantes/{run_tag}-reparar.png",
                    "autorizacion_stock": "1",
                },
            ),
            200,
            contexto={
                "nota": nota_reparacion,
                "estado": estado_pre_pago_reparacion,
                "producto_id": producto_reparacion["id"],
                "stock": stock_pre_pago_reparacion,
                "movimientos": _resumen_movimientos_nota(conn, nota_reparacion),
            },
        )
        if pago_reparacion.get("idempotente"):
            raise AssertionError("El pago inicial del escenario de reparacion no puede ser idempotente.")
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_reparacion["id"],))) != 11:
            raise AssertionError("El escenario de reparacion no desconto las 9 piezas esperadas.")
        if _scalar(conn, "SELECT estado AS valor FROM notas WHERE id=%s", (nota_reparacion,)) != "PAGADA":
            raise AssertionError("El pago inicial no marco la nota de reparacion como PAGADA.")
        if _contar_movimientos_nota(conn, nota_reparacion, "VENTA") != 1 or _contar_pagos_nota(conn, nota_reparacion) != 1:
            raise AssertionError("El escenario de reparacion no dejo una venta y pago iniciales validos.")
        venta_reparacion = _resumen_movimientos_nota(conn, nota_reparacion, ("VENTA",))
        if venta_reparacion != [{
            "producto_id": producto_reparacion["id"],
            "tipo": "VENTA",
            "cantidad": -9,
            "stock_anterior": 20,
            "stock_nuevo": 11,
        }]:
            raise AssertionError(f"El pago inicial no genero la salida VENTA esperada: {venta_reparacion}")
        if int(_scalar(conn, "SELECT COUNT(*) AS valor FROM movimientos_almacen WHERE idempotency_key=%s", (clave_venta_reparacion,)) or 0) != 1:
            raise AssertionError("El pago inicial no uso una unica llave idempotente de venta.")
        with conn.cursor() as cur:
            cur.execute("UPDATE notas SET estado='ANULADA' WHERE id=%s", (nota_reparacion,))
        conn.commit()
        estado_historico_reparacion = _scalar(conn, "SELECT estado AS valor FROM notas WHERE id=%s", (nota_reparacion,))
        if estado_historico_reparacion != "ANULADA":
            raise AssertionError("No se pudo simular el estado historico ANULADA del escenario de reparacion.")
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_reparacion["id"],))) != 11:
            raise AssertionError("La simulacion historica altero el stock que debia permanecer en 11.")
        if _contar_movimientos_nota(conn, nota_reparacion, "CANCELACION_VENTA") != 0:
            raise AssertionError("La simulacion historica creo una reposicion que no corresponde.")
        esperar(
            "pago_anulada_rechazado",
            flask_app.test_client().post(
                "/api/pagos",
                headers=_headers(token_admin),
                json={"nota_id": nota_reparacion, "comprobante": f"comprobantes/{run_tag}-reparar.png"},
            ),
            409,
            contexto={
                "nota": nota_reparacion,
                "estado": estado_historico_reparacion,
                "producto_id": producto_reparacion["id"],
                "stock": int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_reparacion["id"],))),
                "movimientos": _resumen_movimientos_nota(conn, nota_reparacion),
            },
        )
        reparacion_anulada = esperar(
            "reparar_anulada_con_venta_pendiente",
            flask_app.test_client().post(
                f"/api/notas/{nota_reparacion}/anular",
                headers=_headers(token_admin),
                json={"autorizacion_stock": "1"},
            ),
            200,
        )
        if not reparacion_anulada.get("stock_devuelto") or reparacion_anulada.get("idempotente"):
            raise AssertionError("La nota anulada con venta pendiente no reparo el stock pendiente.")
        productos_devueltos = reparacion_anulada.get("productos_devueltos") or []
        if productos_devueltos != [{
            "producto_id": producto_reparacion["id"],
            "codigo": producto_reparacion["codigo"],
            "marca": "F9B",
            "hilo": "HILO_TEST",
            "color": "REPARAR",
            "cantidad": 9,
            "stock_anterior": 11,
            "stock_nuevo": 20,
        }]:
            raise AssertionError(f"La reparacion no devolvio exactamente 9 piezas: {productos_devueltos}")
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_reparacion["id"],))) != 20:
            raise AssertionError("La reparacion de nota anulada no repuso las 9 piezas pendientes.")
        if _contar_movimientos_nota(conn, nota_reparacion, "CANCELACION_VENTA") != 1:
            raise AssertionError("La reparacion de nota anulada no registro una unica reposicion.")
        cancelacion_reparacion = _resumen_movimientos_nota(conn, nota_reparacion, ("CANCELACION_VENTA",))
        if cancelacion_reparacion != [{
            "producto_id": producto_reparacion["id"],
            "tipo": "CANCELACION_VENTA",
            "cantidad": 9,
            "stock_anterior": 11,
            "stock_nuevo": 20,
        }]:
            raise AssertionError(f"La reparacion no registro la CANCELACION_VENTA +9 esperada: {cancelacion_reparacion}")

        nota_pendiente = f"{run_tag}-PENDIENTE"
        _insertar_nota(
            conn,
            json_adapter,
            nota_pendiente,
            cliente_comercial,
            "VENTA",
            [{"codigo": producto_bueno["codigo"], "cantidad": 1, "precio": 80, "color": "BUENO"}],
        )
        stock_antes_pendiente = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_bueno["id"],)))
        esperar("anular_venta_pendiente", flask_app.test_client().post(f"/api/notas/{nota_pendiente}/anular", headers=_headers(token_admin), json={}), 200)
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_bueno["id"],))) != stock_antes_pendiente:
            raise AssertionError("Una venta pendiente aumento stock indebidamente.")
        if _contar_movimientos_nota(conn, nota_pendiente):
            raise AssertionError("Una venta pendiente genero movimiento de inventario.")

        # Esta nota cubre solo la anulacion legacy. La evidencia historica que
        # consume el diagnostico se crea al final y nunca se reutiliza aqui.
        nota_historica_anulable = f"{run_tag}-HISTORICA-ANULABLE"
        _insertar_nota(
            conn,
            json_adapter,
            nota_historica_anulable,
            cliente_comercial,
            "PAGADA",
            [{"codigo": producto_bueno["codigo"], "cantidad": 1, "precio": 80, "color": "BUENO"}],
            fecha_historica=datetime(2020, 1, 1, 12, 0, 0),
        )
        stock_antes_historica = int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_bueno["id"],)))
        esperar("anular_historica_sin_movimientos", flask_app.test_client().post(f"/api/notas/{nota_historica_anulable}/anular", headers=_headers(token_admin), json={}), 200)
        if int(_scalar(conn, "SELECT stock AS valor FROM productos WHERE id=%s", (producto_bueno["id"],))) != stock_antes_historica:
            raise AssertionError("La venta historica sin movimiento repuso inventario.")
        if _contar_movimientos_nota(conn, nota_historica_anulable):
            raise AssertionError("La venta historica invento movimientos retroactivos.")

        movimientos_a = esperar(
            "movimientos_cliente_a",
            flask_app.test_client().get("/api/almacen/movimientos?limit=1&tipo=VENTA", headers=_headers(token_almacen_a)),
            200,
        )
        if not isinstance(movimientos_a.get("items"), list) or "pagination" not in movimientos_a:
            raise AssertionError("El listado de movimientos no mantuvo estructura paginada.")
        if any(item.get("cliente_sistema_id") != clientes_sistema["CLIENTE_A"] for item in movimientos_a["items"]):
            raise AssertionError("Un almacenista recibio movimientos de otra empresa.")
        esperar("movimientos_vendedor_denegado", flask_app.test_client().get("/api/almacen/movimientos", headers=_headers(token_vendedor)), 403)

        legacy_auditoria = esperar("auditoria_legacy", flask_app.test_client().get("/api/admin/auditoria", headers=_headers(token_admin)), 200)
        if not isinstance(legacy_auditoria, list):
            raise AssertionError("/api/admin/auditoria no preservo el contrato legacy de lista.")
        auditoria_general = esperar("auditoria_general", flask_app.test_client().get("/api/admin/auditoria-general?limit=5", headers=_headers(token_admin)), 200)
        if not isinstance(auditoria_general.get("items"), list) or "pagination" not in auditoria_general:
            raise AssertionError("La auditoria general no devolvio contrato paginado.")
        esperar("auditoria_general_denegada", flask_app.test_client().get("/api/admin/auditoria-general", headers=_headers(token_almacen_a)), 403)

        from hilorama_backend.services.auditoria_service import registrar_auditoria

        adapter = ConexionCompat(conn, cursor_factory)
        try:
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                audit_cols = _columnas(cur, "auditoria_general")
            registrar_auditoria(
                adapter,
                audit_cols,
                accion="ENSAYO_SECRETOS",
                modulo="fase9b_test",
                descripcion="Authorization: Bearer SECRETO_4",
                datos_nuevos={
                    "password": "SECRETO_1",
                    "nested": {"access_token": "SECRETO_2", "items": [{"cookie": "SECRETO_3"}]},
                    "session": "SECRETO_5",
                },
                cliente_sistema_id=clientes_sistema["CLIENTE_A"],
            )
            conn.commit()
        finally:
            adapter.close()
        secretos = ("SECRETO_1", "SECRETO_2", "SECRETO_3", "SECRETO_4", "SECRETO_5")
        for secreto in secretos:
            total = int(_scalar(
                conn,
                """
                SELECT COUNT(*) AS valor FROM auditoria_general
                WHERE CONCAT_WS(' ',
                    descripcion,
                    datos_anteriores_json::text,
                    datos_nuevos_json::text,
                    codigo_error,
                    ip,
                    user_agent,
                    device_id,
                    request_id
                ) ILIKE %s
                """,
                (f"%{secreto}%",),
            ) or 0)
            if total:
                raise AssertionError("Se encontro un secreto ficticio sin censurar en auditoria.")

        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute("SELECT DISTINCT accion FROM auditoria_general")
            acciones = {fila["accion"] for fila in cur.fetchall()}
        acciones_requeridas = {
            "INICIO_SESION_CORRECTO",
            "INICIO_SESION_FALLIDO",
            "PRODUCTO_CREADO",
            "AJUSTE_STOCK_MANUAL",
            "PAGO_REGISTRADO",
            "VENTA_ANULADA",
            "USUARIO_CREADO",
            "PASSWORD_RESTABLECIDO",
            "AUTORIZACION_STOCK_ESPECIAL",
        }
        faltantes = acciones_requeridas - acciones
        if faltantes:
            raise AssertionError("Faltan eventos de auditoria esperados: " + ", ".join(sorted(faltantes)))

        # Registro legacy exclusivo para el diagnostico. Se siembra al final
        # para que ningun escenario HTTP posterior lo pague, anule o repare.
        producto_historica_diagnostico = _seed_producto(
            conn,
            f"{run_tag}-HISTORICA-DIAGNOSTICO",
            100,
            "HISTORICA_DIAGNOSTICO",
        )
        if int(producto_historica_diagnostico["id"]) in productos_escenarios:
            raise AssertionError("La nota historica del diagnostico reutilizo un producto de otro escenario.")
        nota_historica = f"{run_tag}-HISTORICA-DIAGNOSTICO"
        fecha_historica_diagnostico = datetime(2020, 1, 1, 12, 0, 0)
        _insertar_nota(
            conn,
            json_adapter,
            nota_historica,
            cliente_comercial,
            "PAGADA",
            [{
                "codigo": producto_historica_diagnostico["codigo"],
                "cantidad": 1,
                "precio": 80,
                "color": "HISTORICA_DIAGNOSTICO",
            }],
            fecha_historica=fecha_historica_diagnostico,
        )
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute(
                "INSERT INTO pagos(nota_id, comprobante, fecha) VALUES (%s,%s,%s)",
                (nota_historica, f"comprobantes/{run_tag}-historica.png", fecha_historica_diagnostico),
            )
            cur.execute(
                "SELECT estado, fecha, fecha_pago FROM notas WHERE id=%s",
                (nota_historica,),
            )
            nota_historica_row = cur.fetchone()
        conn.commit()
        if str((nota_historica_row or {}).get("estado") or "").upper() != "PAGADA":
            raise AssertionError("La nota heredada del diagnostico no quedo PAGADA.")
        for campo_fecha in ("fecha", "fecha_pago"):
            valor_fecha = (nota_historica_row or {}).get(campo_fecha)
            if not valor_fecha or str(valor_fecha)[:10] != "2020-01-01":
                raise AssertionError(f"La nota heredada no conserva {campo_fecha} anterior al corte del diagnostico.")
        if _contar_pagos_nota(conn, nota_historica) != 1:
            raise AssertionError("La nota heredada del diagnostico no conserva evidencia de pago.")
        if int(_scalar(conn, "SELECT COUNT(*) AS valor FROM items WHERE nota_id=%s", (nota_historica,)) or 0) != 1:
            raise AssertionError("La nota heredada del diagnostico no conserva su item legacy.")
        if _contar_movimientos_nota(conn, nota_historica, "VENTA") != 0:
            raise AssertionError("La nota heredada del diagnostico no debe tener movimiento VENTA.")
        if _contar_movimientos_nota(conn, nota_historica, "CANCELACION_VENTA") != 0:
            raise AssertionError("La nota heredada del diagnostico no debe tener CANCELACION_VENTA.")
        if _contar_movimientos_nota(conn, nota_historica) != 0:
            raise AssertionError("La nota heredada del diagnostico no debe compartir referencias de movimientos.")

    return {
        "http": resultados_http,
        "nota_historica": nota_historica,
        "producto_historica": producto_historica_diagnostico["id"],
        "fecha_desde": date.today().isoformat(),
        "concurrencia_pago": "una aplicacion y una respuesta idempotente",
        "concurrencia_ajuste": f"stock final {final_ajuste}",
        "secretos_encontrados": 0,
    }


def _resultado_subproceso_diagnostico(nombre: str, script: Path, argumentos: list[str], resultado, destino: dict[str, Any]) -> dict[str, Any]:
    return {
        "nombre": nombre,
        "returncode": int(resultado.returncode),
        "script": str(script),
        "argumentos": list(argumentos),
        "destino": dict(destino),
        "stdout": _sanitizar_texto_diagnostico(resultado.stdout),
        "stderr": _sanitizar_texto_diagnostico(resultado.stderr),
    }


def _probar_diagnostico(database_url: str, fecha_desde: str, nota_historica: str) -> dict[str, Any]:
    script = ROOT / "hilorama_backend" / "scripts" / "diagnosticar_movimientos_auditoria.py"
    if not script.exists():
        raise BaseAisladaError(f"No se encontro el script de diagnostico: {script}")
    nota_historica = str(nota_historica or "").strip()
    if not nota_historica:
        raise BaseAisladaError("Falta el identificador de la nota heredada esperada para el diagnostico.")

    entorno, info = _entorno_diagnostico_aislado(database_url)
    destino = _destino_diagnostico_seguro(info)
    argumentos_normal = ["--desde", fecha_desde, "--strict"]
    argumentos_historico = ["--incluir-historicos", "--strict"]
    comando_normal = [sys.executable, str(script), *argumentos_normal]
    comando_historico = [sys.executable, str(script), *argumentos_historico]
    try:
        normal = subprocess.run(
            comando_normal,
            cwd=str(ROOT),
            env=entorno,
            text=True,
            capture_output=True,
            timeout=60,
        )
        historico = subprocess.run(
            comando_historico,
            cwd=str(ROOT),
            env=entorno,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError(
            "No se pudo ejecutar el subproceso de diagnostico aislado: "
            f"script={script}; destino={destino}; error={exc.__class__.__name__}: "
            f"{_sanitizar_texto_diagnostico(exc)}"
        ) from exc

    resultado_normal = _resultado_subproceso_diagnostico(
        "normal",
        script,
        argumentos_normal,
        normal,
        destino,
    )
    resultado_historico = _resultado_subproceso_diagnostico(
        "historico",
        script,
        argumentos_historico,
        historico,
        destino,
    )
    if normal.returncode != 0:
        raise AssertionError(
            "El diagnostico normal marco inconsistencias nuevas inexistentes. "
            f"normal={json.dumps(resultado_normal, ensure_ascii=False)}; "
            f"historico={json.dumps(resultado_historico, ensure_ascii=False)}"
        )
    if nota_historica in resultado_normal["stdout"]:
        raise AssertionError(
            "El diagnostico normal no ignoro la nota heredada anterior al corte. "
            f"normal={json.dumps(resultado_normal, ensure_ascii=False)}; "
            f"historico={json.dumps(resultado_historico, ensure_ascii=False)}"
        )
    if historico.returncode != 1 or nota_historica not in resultado_historico["stdout"]:
        raise AssertionError(
            "El diagnostico historico no obtuvo el resultado esperado para la nota heredada. "
            f"nota_historica={nota_historica}; "
            f"normal={json.dumps(resultado_normal, ensure_ascii=False)}; "
            f"historico={json.dumps(resultado_historico, ensure_ascii=False)}"
        )
    return {
        "normal_strict": resultado_normal,
        "historico_strict": resultado_historico,
        "nota_historica": nota_historica,
    }


def ejecutar_ensayo(database_url: str, info: ConexionPrueba) -> dict[str, Any]:
    _validar_importaciones_backend()
    psycopg2, json_adapter, cursor_factory = _cargar_psycopg()
    run_tag = f"F9B-{uuid.uuid4().hex[:8].upper()}"
    reporte: dict[str, Any] = {
        "base": info.reporte_seguro(),
        "run_tag": run_tag,
        "migracion": {},
        "pruebas": {},
        "notas": ["Base usada solo para FASE 9B. El script no borra tablas ni bases."],
    }
    with psycopg2.connect(database_url, cursor_factory=cursor_factory) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    current_database() AS database,
                    current_user AS usuario,
                    inet_server_addr()::text AS host,
                    inet_server_port() AS puerto
                """
            )
            real = cur.fetchone()

            database_real = str(real["database"] or "").strip().lower()
            usuario_real = str(real["usuario"] or "").strip().lower()
            host_real = str(real["host"] or "").strip()
            puerto_real = int(real["puerto"] or 0)

            try:
                host_es_local = ip_interface(host_real).ip.is_loopback
            except ValueError:
                host_es_local = False

            if (
                database_real != str(info.database).strip().lower()
                or usuario_real != str(info.usuario).strip().lower()
                or puerto_real != int(info.puerto)
                or not host_es_local
            ):
                raise BaseAisladaError(
                    "La conexion abierta no coincide con la base local de prueba validada."
                )
            _asegurar_base_vacia(cur)

        _crear_esquema_base(conn)
        _sembrar_datos_legacy(conn, run_tag)
        _crear_indice_legacy(conn)
        with conn.cursor() as cur:
            conteos_antes = _conteos(cur)
            legado_antes = _indice_existe(cur, "uq_movimientos_almacen_idempotency_key")
        if not legado_antes:
            raise AssertionError("No se pudo preparar el indice global legacy para el ensayo.")

        _ejecutar_sql(conn, _sql_path("001_fase2_control_acceso.sql"))
        _ejecutar_sql(conn, _sql_path("002_fase9_movimientos_auditoria.sql"))
        with conn.cursor() as cur:
            verificacion_primera = _verificar_migracion(conn, legado_esperado=True)
            conteos_primera = _conteos(cur)
        if conteos_primera["productos"] != conteos_antes["productos"] or conteos_primera["movimientos"] != conteos_antes["movimientos"]:
            raise AssertionError("La primera migracion altero registros legacy ficticios.")

        _ejecutar_sql(conn, _sql_path("002_fase9_movimientos_auditoria.sql"))
        with conn.cursor() as cur:
            verificacion_segunda = _verificar_migracion(conn, legado_esperado=False)
            conteos_segunda = _conteos(cur)
        if conteos_segunda != conteos_primera:
            raise AssertionError("La segunda migracion cambio conteos; no fue idempotente.")
        reporte["migracion"] = {
            "antes": conteos_antes,
            "primera": conteos_primera,
            "segunda": conteos_segunda,
            "verificacion_primera": verificacion_primera,
            "verificacion_segunda": verificacion_segunda,
        }

        clientes = _insertar_clientes_sistema(conn, run_tag)
        producto_idempotencia = _seed_producto(conn, f"{run_tag}-IDEMP", 20, "IDEMPOTENCIA")
        reporte["pruebas"]["idempotencia_multicliente"] = _probar_idempotencia_servicio(
            conn,
            cursor_factory,
            clientes,
            producto_idempotencia,
        )

    reporte["pruebas"]["http"] = _probar_http_local(
        database_url,
        psycopg2,
        json_adapter,
        cursor_factory,
        clientes,
        run_tag,
    )
    reporte["pruebas"]["diagnostico"] = _probar_diagnostico(
        database_url,
        reporte["pruebas"]["http"]["fecha_desde"],
        reporte["pruebas"]["http"]["nota_historica"],
    )
    return reporte


def _imprimir_reporte(reporte: dict[str, Any]) -> None:
    print("\nENSAYO FASE 9B - RESULTADO")
    print(json.dumps(reporte, ensure_ascii=True, indent=2, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ensaya FASE 9B solo contra PostgreSQL local *_test.")
    parser.add_argument("--run", action="store_true", help="Conecta y ejecuta el ensayo completo sobre una base vacia de prueba.")
    parser.add_argument("--check-config", action="store_true", help="Valida URL y protecciones sin abrir conexion.")
    args = parser.parse_args(argv)
    try:
        database_url, info = obtener_url_base_prueba()
        print("Configuracion de base aislada:")
        for clave, valor in info.reporte_seguro().items():
            print(f"- {clave}: {valor}")
        print("- DATABASE_URL: ignorada por este script")
        if not args.run:
            print("No se abrio conexion. Use --run solo despues de confirmar que la base local esta vacia y es desechable.")
            return 0
        reporte = ejecutar_ensayo(database_url, info)
        _imprimir_reporte(reporte)
        return 0
    except BaseAisladaError as exc:
        print(f"BLOQUEADO: {exc}")
        return 2
    except AssertionError as exc:
        print(f"FALLO DE ENSAYO: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR CONTROLADO: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
