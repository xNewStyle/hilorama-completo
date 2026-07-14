"""Validacion opt-in de la campana contra PostgreSQL local y desechable.

La prueba ignora ``DATABASE_URL`` como entrada. Solo acepta
``HILORAMA_NOTIFICACIONES_TEST_DATABASE_URL`` y rechaza cualquier destino que
no sea loopback o cuyo nombre no termine en ``_test``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from ipaddress import ip_interface
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_URL_ENV = "HILORAMA_NOTIFICACIONES_TEST_DATABASE_URL"
MIGRATIONS = ROOT / "hilorama_backend" / "migrations"
DATA_TABLES = (
    "productos",
    "clientes",
    "notas",
    "items",
    "pagos",
    "movimientos_almacen",
    "cola_impresion",
    "errores_scan",
    "notificaciones_oportunidades_control",
)


BASE_SCHEMA_SQL = """
CREATE TABLE productos (
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

CREATE TABLE clientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    telefono TEXT,
    direccion JSONB NOT NULL DEFAULT '{}'::jsonb,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    estado TEXT NOT NULL DEFAULT 'ACTIVO'
);

CREATE TABLE empacadores (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE notas (
    id TEXT PRIMARY KEY,
    cliente_id INTEGER,
    cliente TEXT,
    estado TEXT NOT NULL DEFAULT 'COTIZACION',
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fecha_pago TIMESTAMPTZ,
    fecha_asignacion TIMESTAMPTZ,
    fecha_finalizacion TIMESTAMPTZ,
    total NUMERIC NOT NULL DEFAULT 0,
    envio JSONB,
    paqueteria TEXT,
    guia TEXT,
    comprobante TEXT,
    observaciones TEXT,
    notas TEXT,
    pedido TEXT,
    empacador_id INTEGER
);

CREATE TABLE items (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    codigo TEXT NOT NULL,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    cantidad NUMERIC NOT NULL,
    empacadas NUMERIC NOT NULL DEFAULT 0,
    precio NUMERIC NOT NULL DEFAULT 0
);

CREATE TABLE pagos (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    comprobante TEXT,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE movimientos_almacen (
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
    motivo TEXT
);

CREATE TABLE cola_impresion (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'ETIQUETA',
    estado TEXT NOT NULL DEFAULT 'PENDIENTE',
    intentos INTEGER NOT NULL DEFAULT 0,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE errores_scan (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    codigo TEXT,
    empacador_id INTEGER,
    motivo TEXT,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resuelto BOOLEAN NOT NULL DEFAULT FALSE
);
"""


def _validar_destino_prueba(url: str):
    texto = str(url or "").strip()
    if not texto:
        raise RuntimeError(f"Falta {TEST_URL_ENV}; DATABASE_URL no se usa como entrada.")
    parsed = urlparse(texto)
    host = str(parsed.hostname or "").strip().lower()
    database = str(parsed.path or "").lstrip("/").strip().lower()
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("La prueba requiere una URL PostgreSQL local.")
    if host == "localhost":
        loopback = True
    else:
        try:
            loopback = ip_interface(host).ip.is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise RuntimeError("Destino remoto rechazado; solo se permite loopback.")
    if not database.endswith("_test") or "notificaciones" not in database:
        raise RuntimeError("La base debe identificar claramente notificaciones y terminar en _test.")
    if database in {"postgres", "hilorama", "template0", "template1"} or "prod" in database:
        raise RuntimeError("Nombre de base de produccion o sistema rechazado.")
    if any(part in host for part in ("render", "onrender", "amazonaws", "neon", "supabase")):
        raise RuntimeError("Host administrado/remoto rechazado.")
    return parsed


def _leer_migracion(nombre: str) -> str:
    return (MIGRATIONS / nombre).read_text(encoding="utf-8")


def _aplicar_sql(conn, sql: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _huella_esquema(conn) -> dict[str, object]:
    consulta = """
        WITH objetos AS (
            SELECT 'T|' || table_name AS valor
            FROM information_schema.tables
            WHERE table_schema='public'
            UNION ALL
            SELECT 'C|' || table_name || '|' || column_name || '|' || data_type || '|' ||
                   is_nullable || '|' || COALESCE(column_default, '')
            FROM information_schema.columns
            WHERE table_schema='public'
            UNION ALL
            SELECT 'I|' || tablename || '|' || indexname || '|' || indexdef
            FROM pg_indexes
            WHERE schemaname='public'
        )
        SELECT COUNT(*) AS objetos,
               MD5(COALESCE(STRING_AGG(valor, '||' ORDER BY valor), '')) AS sha
        FROM objetos
    """
    with conn.cursor() as cur:
        cur.execute(consulta)
        objetos, sha = cur.fetchone()
    return {"objetos": int(objetos), "sha": sha}


def _huella_datos(conn) -> dict[str, dict[str, object]]:
    resultado = {}
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        existentes = {row[0] for row in cur.fetchall()}
        for tabla in DATA_TABLES:
            if tabla not in existentes:
                resultado[tabla] = {"total": 0, "sha": None}
                continue
            cur.execute(f"""
                SELECT COUNT(*) AS total,
                       MD5(COALESCE(STRING_AGG(firma, '||' ORDER BY firma), '')) AS sha
                FROM (
                    SELECT MD5(ROW_TO_JSON(t)::text) AS firma
                    FROM {tabla} t
                ) filas
            """)
            total, sha = cur.fetchone()
            resultado[tabla] = {"total": int(total), "sha": sha}
    return resultado


def _insertar_datos_ficticios(conn, ahora):
    from psycopg2.extras import Json, execute_values

    clientes = []
    for cliente_id in range(1, 501):
        clientes.append((cliente_id, f"Clienta Ficticia {cliente_id:03d}", f"TEST-{cliente_id:06d}", Json({})))
    especiales = {
        501: "Clienta Ficticia Compra Unica",
        502: "Clienta Ficticia Activa",
        503: "Clienta Ficticia Proxima",
        504: "Clienta Ficticia Atrasada",
        505: "Clienta Ficticia Dormida",
        506: "Clienta Ficticia VIP Vigente",
        507: "Clienta Ficticia VIP Atrasada",
        508: "Clienta Ficticia Recurrente Atrasada",
        509: "Clienta Ficticia Cotizacion Activa",
        510: "Clienta Ficticia Venta Pendiente",
        511: "Clienta Ficticia Compra Reciente",
        512: "Clienta Ficticia Sin Telefono",
        513: "Clienta Ficticia Dos Compras Mismo Dia",
        514: "Clienta Ficticia Venta Anulada",
        515: "Clienta Ficticia Archivada Sin Pago",
        516: "Clienta Ficticia Archivada Con Pago",
        517: "Clienta Ficticia con un nombre deliberadamente largo para validar el ajuste visual",
        518: "Clienta Ficticia Repetida",
        519: "Clienta Ficticia Repetida",
        520: "Clienta Ficticia Estados Posteriores al Pago",
    }
    for cliente_id, nombre in especiales.items():
        telefono = "" if cliente_id == 512 else f"TEST-{cliente_id:06d}"
        clientes.append((cliente_id, nombre, telefono, Json({"calle": "DOMICILIO FICTICIO"})))

    notas = []
    items = []
    pagos = []

    def agregar_nota(
        nota_id,
        cliente_id,
        estado,
        fecha,
        *,
        total=400,
        fecha_pago=True,
        fecha_asignacion=None,
        fecha_finalizacion=None,
        envio=None,
        guia=None,
        empacador_id=None,
        cantidad=3,
        empacadas=0,
    ):
        fecha_pago_valor = fecha if fecha_pago and estado not in {"COTIZACION", "VENTA_PENDIENTE", "ANULADA", "CANCELADA"} else None
        notas.append((
            nota_id,
            cliente_id,
            especiales.get(cliente_id, f"Clienta Ficticia {cliente_id:03d}"),
            estado,
            fecha,
            fecha_pago_valor,
            fecha_asignacion,
            fecha_finalizacion,
            total,
            Json(envio or {"tipo": "PAQUETERIA"}),
            "PAQUETERIA",
            guia,
            empacador_id,
        ))
        for indice in range(3):
            items.append((
                nota_id,
                f"TEST-COD-{(indice % 3) + 1}",
                "MARCA FICTICIA",
                "HILO FICTICIO",
                f"COLOR FICTICIO {indice + 1}",
                cantidad,
                empacadas,
                round(float(total) / max(cantidad * 3, 1), 2),
            ))

    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO clientes(id,nombre,telefono,direccion) VALUES %s",
            clientes,
            page_size=500,
        )
        cur.execute("SELECT setval(pg_get_serial_sequence('clientes','id'), 520, TRUE)")
        cur.execute("INSERT INTO empacadores(id,nombre) VALUES (1,'Empacador Ficticio')")
        execute_values(
            cur,
            """INSERT INTO productos(
                   id,codigo,marca,hilo,color,stock,estado,precio,costo_neto,tipo_producto,es_inventariable
               ) VALUES %s""",
            [
                (1, "TEST-COD-1", "MARCA FICTICIA", "HILO FICTICIO", "OK", 50, "OK", 80, 35, "INVENTARIO", True),
                (2, "TEST-COD-2", "MARCA FICTICIA", "HILO FICTICIO", "BAJO", 4, "RESURTIR", 80, 35, "INVENTARIO", True),
                (3, "TEST-COD-3", "MARCA FICTICIA", "HILO FICTICIO", "CERO", 0, "SIN STOCK", 80, 35, "INVENTARIO", True),
            ],
        )

        for cliente_id in range(1, 501):
            for indice, dias in enumerate((45, 30, 15, 0), start=1):
                agregar_nota(
                    f"BULK-{cliente_id:03d}-{indice}",
                    cliente_id,
                    "ENVIADO",
                    ahora - timedelta(days=dias),
                    total=400,
                    fecha_finalizacion=ahora - timedelta(days=dias),
                    guia=f"GUIA-BULK-{cliente_id:03d}-{indice}",
                    cantidad=1,
                    empacadas=1,
                )

        patrones = {
            501: ([-10], 400),
            502: ([-30, -15, 0], 450),
            503: ([-38, -18], 800),
            504: ([-65, -45, -25], 200),
            505: ([-100, -80], 400),
            506: ([-150, -120, -90, -60, -30, 0], 1000),
            507: ([-140, -120, -100, -80, -60, -40], 1000),
            508: ([-90, -70, -50, -30], 500),
            509: ([-65, -45, -25], 300),
            510: ([-65, -45, -25], 300),
            511: ([-40, -20, 0], 400),
            512: ([-100, -80], 400),
            513: ([-10, -10], 250),
            517: ([-40, -20], 600),
            518: ([-40, -20], 600),
            519: ([-45, -25], 600),
        }
        for cliente_id, (dias_lista, total) in patrones.items():
            for indice, dias in enumerate(dias_lista, start=1):
                agregar_nota(
                    f"CRM-{cliente_id}-{indice}",
                    cliente_id,
                    "PAGADA",
                    ahora + timedelta(days=dias),
                    total=total,
                )

        agregar_nota("CRM-509-COT", 509, "COTIZACION", ahora - timedelta(days=1), fecha_pago=False)
        agregar_nota("CRM-510-VP", 510, "VENTA_PENDIENTE", ahora - timedelta(days=1), fecha_pago=False)
        agregar_nota("CRM-514-ANU", 514, "ANULADA", ahora - timedelta(days=20), fecha_pago=False)
        agregar_nota("CRM-515-ARCH", 515, "ARCHIVADA", ahora - timedelta(days=20), fecha_pago=False)
        agregar_nota("CRM-516-ARCH", 516, "ARCHIVADA", ahora - timedelta(days=20), fecha_pago=False)
        pagos.append(("CRM-516-ARCH", "comprobantes/FICTICIO.png", ahora - timedelta(days=20)))
        for indice, estado in enumerate(("PAGADA", "EN_PROCESO", "INCOMPLETA", "COMPLETA", "ENVIADO"), start=1):
            agregar_nota(
                f"CRM-520-{indice}",
                520,
                estado,
                ahora - timedelta(days=30 - indice * 5),
                total=100,
                fecha_asignacion=ahora - timedelta(days=30 - indice * 5),
                fecha_finalizacion=ahora - timedelta(days=30 - indice * 5) if estado in {"COMPLETA", "ENVIADO"} else None,
                guia=f"GUIA-520-{indice}" if estado in {"COMPLETA", "ENVIADO"} else None,
                empacadas=1 if estado in {"COMPLETA", "ENVIADO"} else 0,
                cantidad=1,
            )

        operaciones = [
            ("OP-COT", "COTIZACION", 2, None, None, None, None, 0),
            ("OP-VP-REC", "VENTA_PENDIENTE", 2, None, None, None, None, 0),
            ("OP-VP-OLD", "VENTA_PENDIENTE", 30, None, None, None, None, 0),
            ("OP-PAG-SIN", "PAGADA", 10, None, None, None, None, 0),
            ("OP-PAG-ASIG", "PAGADA", 10, 1, ahora - timedelta(hours=10), None, None, 0),
            ("OP-PROCESO", "EN_PROCESO", 5, 1, ahora - timedelta(hours=5), None, None, 2),
            ("OP-INCOMPLETA", "INCOMPLETA", 9, 1, ahora - timedelta(hours=9), None, None, 6),
            ("OP-COMP-SIN", "COMPLETA", 6, 1, ahora - timedelta(hours=8), ahora - timedelta(hours=6), None, 10),
            ("OP-COMP-GUIA", "COMPLETA", 14, 1, ahora - timedelta(hours=16), ahora - timedelta(hours=14), "GUIA-TEST", 10),
            ("OP-ENVIADA", "ENVIADO", 20, 1, ahora - timedelta(hours=22), ahora - timedelta(hours=20), "GUIA-ENVIADA", 10),
            ("OP-ANULADA", "ANULADA", 20, None, None, None, None, 0),
            ("OP-ARCHIVADA", "ARCHIVADA", 20, None, None, None, None, 0),
        ]
        for nota_id, estado, horas, empacador, asignacion, finalizacion, guia, avance in operaciones:
            agregar_nota(
                nota_id,
                1,
                estado,
                ahora - timedelta(hours=horas),
                fecha_pago=estado not in {"COTIZACION", "VENTA_PENDIENTE", "ANULADA", "ARCHIVADA"},
                fecha_asignacion=asignacion,
                fecha_finalizacion=finalizacion,
                guia=guia,
                empacador_id=empacador,
                cantidad=10,
                empacadas=avance,
            )
        agregar_nota(
            "OP-LOCAL",
            1,
            "COMPLETA",
            ahora - timedelta(hours=4),
            fecha_finalizacion=ahora - timedelta(hours=4),
            envio={"tipo": "RECOLECCION LOCAL"},
            cantidad=1,
            empacadas=1,
        )
        agregar_nota(
            "OP-INCONSISTENTE",
            1,
            "COMPLETA",
            ahora - timedelta(hours=3),
            fecha_pago=True,
            fecha_finalizacion=None,
            cantidad=10,
            empacadas=4,
        )

        execute_values(
            cur,
            """INSERT INTO notas(
                   id,cliente_id,cliente,estado,fecha,fecha_pago,fecha_asignacion,
                   fecha_finalizacion,total,envio,paqueteria,guia,empacador_id
               ) VALUES %s""",
            notas,
            page_size=500,
        )
        execute_values(
            cur,
            """INSERT INTO items(
                   nota_id,codigo,marca,hilo,color,cantidad,empacadas,precio
               ) VALUES %s""",
            items,
            page_size=1000,
        )
        execute_values(cur, "INSERT INTO pagos(nota_id,comprobante,fecha) VALUES %s", pagos)
        execute_values(
            cur,
            "INSERT INTO cola_impresion(nota_id,tipo,estado,intentos,creado_en,actualizado_en) VALUES %s",
            [
                ("OP-COMP-GUIA", "ETIQUETA", "PENDIENTE", 0, ahora - timedelta(hours=2), ahora - timedelta(hours=2)),
                ("OP-ENVIADA", "ETIQUETA", "IMPRESA", 1, ahora - timedelta(hours=3), ahora - timedelta(hours=2)),
                ("OP-COMP-SIN", "ETIQUETA", "FALLIDA", 3, ahora - timedelta(hours=5), ahora - timedelta(hours=1)),
            ],
        )
        cur.execute(
            """INSERT INTO errores_scan(nota_id,codigo,empacador_id,motivo,fecha,resuelto)
               VALUES (%s,%s,%s,%s,%s,FALSE)""",
            ("OP-INCOMPLETA", "TEST-COD-X", 1, "ERROR FICTICIO", ahora - timedelta(hours=1)),
        )
    conn.commit()


def _sembrar_acceso(conn):
    from werkzeug.security import generate_password_hash

    password = secrets.token_urlsafe(24)
    usuario = f"notif_test_{secrets.token_hex(4)}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO clientes_sistema(nombre_negocio,estado,max_dispositivos)
               VALUES ('NEGOCIO FICTICIO NOTIFICACIONES','activo',5) RETURNING id"""
        )
        cliente_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO usuarios_sistema(cliente_id,nombre,usuario,password_hash,rol,activo)
               VALUES (%s,'Usuario Ficticio',%s,%s,'super_admin',TRUE)""",
            (cliente_id, usuario, generate_password_hash(password)),
        )
    conn.commit()
    return usuario, password


def _columnas_control(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='notificaciones_oportunidades_control'
            ORDER BY ordinal_position
        """)
        return [dict(zip(("nombre", "tipo", "nullable", "default"), row)) for row in cur.fetchall()]


def _etiqueta_consulta(sql: str) -> str:
    texto = " ".join(str(sql or "").split()).lower()
    for etiqueta, marca in (
        ("notas_operacion", "from notas n"),
        ("ventas_crm", "select n.*, it.subtotal_productos"),
        ("items_crm", "from items i"),
        ("clientes_crm", "from clientes"),
        ("autenticacion", "from sesiones_activas"),
        ("impresiones", "from cola_impresion"),
        ("errores_scan", "from errores_scan"),
        ("productos", "from productos"),
        ("metadata", "information_schema"),
    ):
        if marca in texto:
            return etiqueta
    return "consulta_select"


class NotificacionesPostgresIntegracionTests(unittest.TestCase):
    maxDiff = None

    def test_campana_con_postgresql_real(self):
        url = os.environ.get(TEST_URL_ENV, "")
        info = _validar_destino_prueba(url)

        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(url)
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()
            """)
            database, usuario_real, host_real, puerto_real = cur.fetchone()
            try:
                host_local = ip_interface(str(host_real)).ip.is_loopback
            except ValueError:
                host_local = False
            self.assertTrue(host_local)
            self.assertEqual(str(database).lower(), str(info.path).lstrip("/").lower())
            self.assertEqual(int(puerto_real), int(info.port))
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
            self.assertEqual(cur.fetchone()[0], 0, "La base efimera no estaba vacia.")

        _aplicar_sql(conn, BASE_SCHEMA_SQL)
        for nombre in (
            "001_fase2_control_acceso.sql",
            "002_fase9_movimientos_auditoria.sql",
            "003_fecha_envio_notas.sql",
        ):
            _aplicar_sql(conn, _leer_migracion(nombre))

        ahora = datetime.now(timezone.utc).replace(microsecond=0)
        _insertar_datos_ficticios(conn, ahora)
        usuario_login, password_login = _sembrar_acceso(conn)

        os.environ["DATABASE_URL"] = url
        os.environ["HILORAMA_DATA_MODE"] = "local"
        db_connection = importlib.import_module("database.connection")
        db_connection._pool = None
        backend = importlib.import_module("hilorama_backend.app")
        backend.app.config.update(TESTING=True)
        client = backend.app.test_client()

        sin_auth = client.get("/api/notificaciones/resumen")
        self.assertIn(sin_auth.status_code, {401, 403})
        login = client.post(
            "/api/auth/login",
            json={
                "usuario": usuario_login,
                "password": password_login,
                "device_id_hash": f"DEVICE-TEST-{secrets.token_hex(8)}",
                "modulo_actual": "notificaciones_test",
            },
        )
        self.assertEqual(login.status_code, 200, login.get_json())
        sesion = login.get_json()
        token = sesion.get("token")
        self.assertTrue(token)
        headers = {"Authorization": f"Bearer {token}"}

        resumen_sin_004 = client.get("/api/notificaciones/resumen", headers=headers)
        self.assertEqual(resumen_sin_004.status_code, 200, resumen_sin_004.get_json())
        control_sin_004 = client.post(
            "/api/notificaciones/oportunidades/503/control",
            headers=headers,
            json={"categoria": "PROXIMA_COMPRA", "accion": "RECORDAR_3"},
        )
        self.assertEqual(control_sin_004.status_code, 409, control_sin_004.get_json())

        sql_004 = _leer_migracion("004_notificaciones_oportunidades.sql")
        sha_004 = hashlib.sha256(sql_004.encode("utf-8")).hexdigest()
        datos_antes_004 = _huella_datos(conn)
        _aplicar_sql(conn, sql_004)
        esquema_primera_004 = _huella_esquema(conn)
        datos_primera_004 = _huella_datos(conn)
        _aplicar_sql(conn, sql_004)
        esquema_segunda_004 = _huella_esquema(conn)
        datos_segunda_004 = _huella_datos(conn)
        self.assertEqual(esquema_primera_004, esquema_segunda_004)
        for tabla in DATA_TABLES:
            if tabla != "notificaciones_oportunidades_control":
                self.assertEqual(datos_antes_004[tabla], datos_primera_004[tabla])
                self.assertEqual(datos_primera_004[tabla], datos_segunda_004[tabla])

        columnas_control = _columnas_control(conn)
        self.assertEqual(
            [columna["nombre"] for columna in columnas_control],
            ["id", "cliente_id", "categoria", "pospuesto_hasta", "oculto_hasta", "fecha_accion", "usuario"],
        )

        consultas_operativas = []
        original_execute_operativo = db_connection.PGConnection.execute

        def execute_operativo(instancia, query, params=None):
            consultas_operativas.append(str(query))
            return original_execute_operativo(instancia, query, params)

        analitica_original = backend._analitica_clientas_conn_api
        with (
            patch.object(db_connection.PGConnection, "execute", execute_operativo),
            patch.object(
                backend,
                "_analitica_clientas_conn_api",
                wraps=analitica_original,
            ) as analitica_crm,
        ):
            inicio_operativo = time.perf_counter()
            respuesta_operativa = client.get(
                "/api/notificaciones/resumen?incluir_oportunidades=false",
                headers=headers,
            )
            tiempo_operativo = round((time.perf_counter() - inicio_operativo) * 1000, 2)
        self.assertEqual(respuesta_operativa.status_code, 200, respuesta_operativa.get_json())
        self.assertFalse(respuesta_operativa.get_json()["oportunidades_actualizadas"])
        self.assertEqual(respuesta_operativa.get_json()["oportunidades"]["total"], 0)
        analitica_crm.assert_not_called()

        huella_esquema_antes = _huella_esquema(conn)
        huella_datos_antes = _huella_datos(conn)
        registros_sql = []
        original_execute = db_connection.PGConnection.execute

        def execute_medido(instancia, query, params=None):
            inicio = time.perf_counter()
            resultado = original_execute(instancia, query, params)
            registros_sql.append({
                "sql": str(query),
                "params": params,
                "ms": round((time.perf_counter() - inicio) * 1000, 3),
            })
            return resultado

        tiempos = []
        respuestas = []
        with patch.object(db_connection.PGConnection, "execute", execute_medido):
            for _ in range(3):
                inicio = time.perf_counter()
                respuesta = client.get("/api/notificaciones/resumen", headers=headers)
                tiempos.append(round((time.perf_counter() - inicio) * 1000, 2))
                self.assertEqual(respuesta.status_code, 200, respuesta.get_json())
                respuestas.append(respuesta)

        huella_esquema_despues = _huella_esquema(conn)
        huella_datos_despues = _huella_datos(conn)
        self.assertEqual(huella_esquema_antes, huella_esquema_despues)
        self.assertEqual(huella_datos_antes, huella_datos_despues)
        for registro in registros_sql:
            sql_normalizado = re.sub(r"^\s+", "", registro["sql"]).upper()
            self.assertTrue(sql_normalizado.startswith(("SELECT", "WITH")), sql_normalizado[:80])

        resumen = respuestas[-1].get_json()
        avisos_operacion = resumen["operacion"]["notificaciones"]
        avisos_oportunidad = resumen["oportunidades"]["notificaciones"]
        keys = {aviso["key"] for aviso in avisos_operacion}
        categorias_nota = {
            (aviso.get("nota_id"), aviso.get("categoria"))
            for aviso in avisos_operacion
        }
        self.assertIn(("OP-VP-REC", "PENDIENTE_PAGO"), categorias_nota)
        self.assertIn(("OP-VP-OLD", "PENDIENTE_PAGO"), categorias_nota)
        avisos_por_nota = {
            aviso.get("nota_id"): aviso
            for aviso in avisos_operacion
            if aviso.get("nota_id")
        }
        self.assertEqual(avisos_por_nota["OP-VP-REC"]["prioridad"], "NORMAL")
        self.assertEqual(avisos_por_nota["OP-VP-OLD"]["prioridad"], "URGENTE")
        self.assertIn(("OP-PAG-SIN", "PAGADA_SIN_EMPAQUETAR"), categorias_nota)
        self.assertIn(("OP-PAG-ASIG", "PAGADA_SIN_EMPAQUETAR"), categorias_nota)
        self.assertIn(("OP-PROCESO", "EMPAQUE_INCOMPLETO"), categorias_nota)
        self.assertIn(("OP-INCOMPLETA", "EMPAQUE_INCOMPLETO"), categorias_nota)
        self.assertIn(("OP-COMP-SIN", "COMPLETA_SIN_GUIA"), categorias_nota)
        self.assertIn(("OP-COMP-GUIA", "GUIA_SIN_ENVIO"), categorias_nota)
        self.assertIn("impresion:1", keys)
        self.assertIn("impresion:3", keys)
        self.assertIn("error_scan:1", keys)
        self.assertIn("inventario_bajo:2", keys)
        self.assertIn("inventario_bajo:3", keys)
        self.assertTrue(any(key.startswith("inconsistencia:") for key in keys))
        for nota_terminal in ("OP-COT", "OP-ENVIADA", "OP-ANULADA", "OP-ARCHIVADA", "OP-LOCAL"):
            self.assertFalse(any(aviso.get("nota_id") == nota_terminal for aviso in avisos_operacion))
        self.assertEqual(resumen["total"], len(avisos_operacion) + len(avisos_oportunidad))
        self.assertEqual(len(keys), len(avisos_operacion))
        todas_las_keys = [
            aviso["key"]
            for aviso in avisos_operacion + avisos_oportunidad
        ]
        self.assertEqual(len(todas_las_keys), len(set(todas_las_keys)))
        self.assertEqual(
            {aviso["key"] for aviso in respuestas[0].get_json()["operacion"]["notificaciones"]},
            keys,
        )
        self.assertEqual(
            {
                aviso["key"]
                for aviso in respuestas[0].get_json()["oportunidades"]["notificaciones"]
            },
            {aviso["key"] for aviso in avisos_oportunidad},
        )

        oportunidades_por_cliente = {int(aviso["cliente_id"]): aviso for aviso in avisos_oportunidad}
        self.assertEqual(oportunidades_por_cliente[503]["categoria"], "PROXIMA_COMPRA")
        self.assertEqual(oportunidades_por_cliente[504]["categoria"], "ATRASADA")
        self.assertEqual(oportunidades_por_cliente[505]["categoria"], "DORMIDA")
        self.assertNotIn(506, oportunidades_por_cliente)
        self.assertEqual(oportunidades_por_cliente[507]["categoria"], "VIP_RECUPERAR")
        self.assertEqual(oportunidades_por_cliente[508]["categoria"], "RECURRENTE_ATRASADA")
        for excluido in (509, 510, 511, 512):
            self.assertNotIn(excluido, oportunidades_por_cliente)

        with backend.get_conn() as api_conn:
            analitica = backend._analitica_clientas_conn_api(
                api_conn,
                incluir_historial=False,
                incluir_favoritos=False,
                incluir_graficas=False,
            )
        metricas = {int(fila["cliente_id"]): fila for fila in analitica["clientes"]}
        self.assertEqual(metricas[513]["numero_compras"], 2)
        self.assertIsNone(metricas[513]["frecuencia_promedio_dias"])
        self.assertEqual(metricas[514]["numero_compras"], 0)
        self.assertEqual(metricas[515]["numero_compras"], 0)
        self.assertEqual(metricas[516]["numero_compras"], 1)
        self.assertEqual(metricas[520]["numero_compras"], 5)
        self.assertIn(518, metricas)
        self.assertIn(519, metricas)

        datos_antes_control = _huella_datos(conn)
        for accion, dias, campo in (
            ("RECORDAR_3", 3, "pospuesto_hasta"),
            ("RECORDAR_7", 7, "pospuesto_hasta"),
            ("OCULTAR_30", 30, "oculto_hasta"),
        ):
            respuesta = client.post(
                "/api/notificaciones/oportunidades/503/control",
                headers=headers,
                json={"categoria": "PROXIMA_COMPRA", "accion": accion},
            )
            self.assertEqual(respuesta.status_code, 200, respuesta.get_json())
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT cliente_id,categoria,pospuesto_hasta,oculto_hasta,fecha_accion
                    FROM notificaciones_oportunidades_control
                    WHERE cliente_id=503 AND categoria='PROXIMA_COMPRA'
                """)
                control = cur.fetchone()
            self.assertIsNotNone(control[campo])
            self.assertIsNotNone(control[campo].tzinfo)
            diferencia = control[campo] - datetime.now(timezone.utc)
            self.assertGreater(diferencia.total_seconds(), (dias - 0.1) * 86400)

        repetida = client.post(
            "/api/notificaciones/oportunidades/503/control",
            headers=headers,
            json={"categoria": "PROXIMA_COMPRA", "accion": "OCULTAR_30"},
        )
        self.assertEqual(repetida.status_code, 200, repetida.get_json())
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM notificaciones_oportunidades_control WHERE cliente_id=503")
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute("""
                UPDATE notificaciones_oportunidades_control
                SET pospuesto_hasta=NOW()-INTERVAL '1 second', oculto_hasta=NOW()-INTERVAL '1 second'
                WHERE cliente_id=503 AND categoria='PROXIMA_COMPRA'
            """)
        conn.commit()
        reaparece = client.get("/api/notificaciones/resumen", headers=headers).get_json()
        self.assertTrue(any(int(aviso["cliente_id"]) == 503 for aviso in reaparece["oportunidades"]["notificaciones"]))

        self.assertEqual(
            client.post(
                "/api/notificaciones/oportunidades/999999/control",
                headers=headers,
                json={"categoria": "DORMIDA", "accion": "RECORDAR_3"},
            ).status_code,
            404,
        )
        self.assertEqual(
            client.post(
                "/api/notificaciones/oportunidades/503/control",
                headers=headers,
                json={"categoria": "DORMIDA", "accion": "BORRAR"},
            ).status_code,
            400,
        )
        self.assertIn(
            client.post(
                "/api/notificaciones/oportunidades/503/control",
                json={"categoria": "DORMIDA", "accion": "RECORDAR_3"},
            ).status_code,
            {401, 403},
        )
        datos_despues_control = _huella_datos(conn)
        for tabla in ("clientes", "notas", "items", "productos", "movimientos_almacen"):
            self.assertEqual(datos_antes_control[tabla], datos_despues_control[tabla])

        from werkzeug.serving import make_server
        servidor = make_server("127.0.0.1", 0, backend.app)
        hilo_servidor = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo_servidor.start()
        try:
            base_url = f"http://127.0.0.1:{servidor.server_port}"
            render_client_module = importlib.import_module("hilorama_desktop.api_client.render_api_client")
            productos_service = importlib.import_module("hilorama_desktop.services.productos_api_service")
            desktop_service = importlib.import_module("hilorama_desktop.services.notificaciones_service")
            with (
                patch.object(render_client_module, "RENDER_API_BASE_URL", base_url),
                patch.object(productos_service, "_session_actual", return_value=sesion),
            ):
                desktop_resumen = desktop_service.obtener_resumen(incluir_oportunidades=True)
            self.assertEqual(desktop_resumen["total"], reaparece["total"])
        finally:
            servidor.shutdown()
            servidor.server_close()
            hilo_servidor.join(timeout=5)

        consultas_tercera = registros_sql[-max(len(registros_sql) // 3, 1):]
        consultas_datos = [
            registro for registro in consultas_tercera
            if registro["sql"].lstrip().upper().startswith(("SELECT", "WITH"))
        ]
        top_costosas = sorted(consultas_datos, key=lambda item: item["ms"], reverse=True)[:5]
        explains = []
        with conn.cursor() as cur:
            for registro in top_costosas[:3]:
                if "information_schema" in registro["sql"].lower():
                    continue
                cur.execute(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + registro["sql"],
                    registro["params"] or (),
                )
                plan = cur.fetchone()[0][0]
                explains.append({
                    "consulta": _etiqueta_consulta(registro["sql"]),
                    "execution_ms": round(float(plan.get("Execution Time") or 0), 3),
                    "planning_ms": round(float(plan.get("Planning Time") or 0), 3),
                })
        conn.rollback()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM clientes")
            total_clientes = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM notas")
            total_notas = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM items")
            total_items = cur.fetchone()[0]
        self.assertGreaterEqual(total_clientes, 500)
        self.assertGreaterEqual(total_notas, 2000)
        self.assertGreaterEqual(total_items, 5000)
        consultas_por_peticion = round(len(registros_sql) / 3, 2)
        self.assertLess(consultas_por_peticion, 60, "Patron de consultas compatible con N+1 detectado.")

        reporte = {
            "destino": {
                "host": str(info.hostname),
                "puerto": int(info.port),
                "database": str(info.path).lstrip("/"),
                "usuario": str(usuario_real),
                "loopback": True,
            },
            "migraciones": ["001", "002", "003", "004", "004 segunda aplicacion"],
            "migracion_004_sha256": sha_004,
            "migracion_004_columnas": columnas_control,
            "datos_ficticios": {
                "clientes": int(total_clientes),
                "notas": int(total_notas),
                "items": int(total_items),
            },
            "endpoint": {
                "status": respuestas[-1].status_code,
                "total": resumen["total"],
                "operacion": resumen["operacion"]["total"],
                "oportunidades": resumen["oportunidades"]["total"],
                "bytes": len(respuestas[-1].data),
                "tiempos_ms": tiempos,
                "consultas_por_peticion": consultas_por_peticion,
                "consultas_costosas": [
                    {"consulta": _etiqueta_consulta(item["sql"]), "ms": item["ms"]}
                    for item in top_costosas
                ],
                "explain": explains,
            },
            "refresco_operativo": {
                "status": respuesta_operativa.status_code,
                "tiempo_ms": tiempo_operativo,
                "consultas": len(consultas_operativas),
                "analitica_crm_invocada": False,
                "bytes": len(respuesta_operativa.data),
            },
            "huellas_lectura_sin_cambios": {
                "esquema": huella_esquema_antes == huella_esquema_despues,
                "datos": huella_datos_antes == huella_datos_despues,
            },
            "desktop_api_loopback": True,
            "controles": {"recordar_3": True, "recordar_7": True, "ocultar_30": True, "idempotente": True},
        }
        print("NOTIFICACIONES_POSTGRES_REPORT=" + json.dumps(reporte, ensure_ascii=True, sort_keys=True))

        pool = getattr(db_connection, "_pool", None)
        if pool is not None:
            pool.closeall()
            db_connection._pool = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
