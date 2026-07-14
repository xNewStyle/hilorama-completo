"""Integracion opt-in de envios contra PostgreSQL local y desechable."""

from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_interface
import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_URL_ENV = "HILORAMA_ENVIOS_TEST_DATABASE_URL"


def _validar_url_prueba(url):
    parsed = urlparse(str(url or "").strip())
    database = str(parsed.path or "").lstrip("/").lower()
    host = str(parsed.hostname or "").lower()
    try:
        loopback = host == "localhost" or ip_interface(host).ip.is_loopback
    except ValueError:
        loopback = False
    if parsed.scheme not in {"postgres", "postgresql"} or not loopback:
        raise RuntimeError("La prueba de envios solo acepta PostgreSQL en loopback.")
    if "envios" not in database or not database.endswith("_test"):
        raise RuntimeError("La base aislada debe contener envios y terminar en _test.")
    return parsed


SCHEMA = """
CREATE TABLE clientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT,
    telefono TEXT,
    direccion JSONB
);
CREATE TABLE empacadores (
    id SERIAL PRIMARY KEY,
    nombre TEXT
);
CREATE TABLE notas (
    id TEXT PRIMARY KEY,
    cliente_id INTEGER,
    cliente_nombre TEXT,
    pedido TEXT,
    estado TEXT NOT NULL,
    total NUMERIC DEFAULT 0,
    envio JSONB,
    paqueteria TEXT,
    guia TEXT,
    fecha TIMESTAMPTZ DEFAULT NOW(),
    costo_envio NUMERIC DEFAULT 0,
    estado_envio TEXT,
    fecha_envio TIMESTAMPTZ,
    observaciones_envio TEXT,
    observaciones TEXT,
    notas TEXT,
    empacador_id INTEGER
);
CREATE TABLE items (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL,
    cantidad NUMERIC NOT NULL
);
CREATE TABLE productos (
    id SERIAL PRIMARY KEY,
    stock INTEGER NOT NULL
);
CREATE TABLE pagos (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL
);
CREATE TABLE movimientos_almacen (
    id BIGSERIAL PRIMARY KEY,
    cantidad INTEGER NOT NULL DEFAULT 0
);
"""


class EnviosPostgresTests(unittest.TestCase):
    def test_filtros_y_lote_sin_efectos_comerciales(self):
        url = os.environ.get(TEST_URL_ENV, "")
        info = _validar_url_prueba(url)

        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(url)
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), inet_server_addr()::text, inet_server_port()")
            database, host_real, puerto_real = cur.fetchone()
            self.assertEqual(str(database).lower(), str(info.path).lstrip("/").lower())
            self.assertTrue(ip_interface(str(host_real)).ip.is_loopback)
            self.assertEqual(int(puerto_real), int(info.port))
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute(SCHEMA)
            cur.execute("INSERT INTO clientes(nombre,telefono,direccion) VALUES ('CLIENTA FICTICIA','000','{}')")
            cur.execute("INSERT INTO empacadores(nombre) VALUES ('EMPACADOR FICTICIO')")
            notas = [
                ("N-PEND", "COMPLETA", None, "Estafeta", {"tipo": "PAQUETERIA"}, None),
                ("N-READY", "COMPLETA", "GUIA-READY", "DHL", {"tipo": "PAQUETERIA"}, None),
                ("N-LOCAL", "COMPLETA", None, None, {"tipo": "RECOLECCION LOCAL"}, None),
                ("N-SENT", "ENVIADO", "GUIA-SENT", "FedEx", {"tipo": "PAQUETERIA"}, "2026-07-13T20:35:00+00:00"),
                ("N-ANNULLED", "ANULADA", "GUIA-X", "DHL", {"tipo": "PAQUETERIA"}, None),
                ("N-PROCESS", "EN_PROCESO", None, None, {"tipo": "PAQUETERIA"}, None),
            ]
            for indice, (nota_id, estado, guia, paqueteria, envio, fecha_envio) in enumerate(notas):
                cur.execute(
                    """
                    INSERT INTO notas(
                        id,cliente_id,cliente_nombre,pedido,estado,envio,paqueteria,guia,
                        fecha,fecha_envio,observaciones,empacador_id
                    )
                    VALUES (%s,1,'CLIENTA FICTICIA',%s,%s,%s::jsonb,%s,%s,
                            NOW()-(%s || ' minutes')::interval,%s,'PRUEBA AISLADA',1)
                    """,
                    (
                        nota_id,
                        f"PED-{indice}",
                        estado,
                        json.dumps(envio),
                        paqueteria,
                        guia,
                        indice,
                        fecha_envio,
                    ),
                )
                cur.execute("INSERT INTO items(nota_id,cantidad) VALUES (%s,2),(%s,3)", (nota_id, nota_id))
            cur.execute("INSERT INTO productos(stock) VALUES (20),(15)")
            cur.execute("INSERT INTO pagos(nota_id) VALUES ('HISTORICO')")
            cur.execute("INSERT INTO movimientos_almacen(cantidad) VALUES (-2)")
        conn.commit()

        def huella_comercial():
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                      (SELECT COALESCE(SUM(stock),0) FROM productos) AS stock,
                      (SELECT COUNT(*) FROM pagos) AS pagos,
                      (SELECT COUNT(*) FROM movimientos_almacen) AS movimientos
                """)
                return dict(cur.fetchone())

        huella_antes = huella_comercial()
        os.environ["DATABASE_URL"] = url
        os.environ["HILORAMA_DATA_MODE"] = "local"
        db_connection = importlib.import_module("database.connection")
        db_connection._pool = None
        backend = importlib.import_module("hilorama_backend.app")
        backend.app.config.update(TESTING=True)
        client = backend.app.test_client()
        auth = {"usuario_id": 900, "cliente_id": 901, "rol": "super_admin"}

        with patch.object(backend, "_require_license_api", return_value=(auth, None)):
            def ids(filtro):
                respuesta = client.get(f"/api/envios/notas?estado={filtro}&limit=100")
                self.assertEqual(respuesta.status_code, 200, respuesta.get_json())
                return {item["id"] for item in respuesta.get_json()["envios"]}

            self.assertEqual(ids("PENDIENTES_GUIA"), {"N-PEND"})
            self.assertEqual(ids("LISTAS_ENVIAR"), {"N-READY", "N-LOCAL"})
            self.assertEqual(ids("ENVIADAS"), {"N-SENT"})
            self.assertEqual(ids("TODAS"), {"N-PEND", "N-READY", "N-LOCAL", "N-SENT"})

            respuesta = client.post(
                "/api/envios/notas/marcar-enviadas",
                json={"nota_ids": ["N-READY", "N-LOCAL", "N-PEND", "N-SENT", "N-ANNULLED"]},
            )
            self.assertEqual(respuesta.status_code, 200, respuesta.get_json())
            lote = respuesta.get_json()
            self.assertEqual(lote["procesados"], 2)
            self.assertEqual(lote["omitidos"], 3)

            repetida = client.post(
                "/api/envios/notas/marcar-enviadas",
                json={"nota_ids": ["N-READY", "N-LOCAL"]},
            )
            self.assertEqual(repetida.status_code, 200, repetida.get_json())
            self.assertEqual(repetida.get_json()["procesados"], 0)

        conn.rollback()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id,estado,guia,paqueteria,fecha_envio
                FROM notas
                WHERE id IN ('N-READY','N-LOCAL','N-PEND','N-SENT')
                ORDER BY id
            """)
            finales = {row["id"]: dict(row) for row in cur.fetchall()}
        self.assertEqual(finales["N-READY"]["estado"], "ENVIADO")
        self.assertEqual(finales["N-READY"]["guia"], "GUIA-READY")
        self.assertEqual(finales["N-READY"]["paqueteria"], "DHL")
        self.assertIsNotNone(finales["N-READY"]["fecha_envio"].tzinfo)
        self.assertEqual(finales["N-LOCAL"]["estado"], "ENVIADO")
        self.assertIsNone(finales["N-LOCAL"]["guia"])
        self.assertIsNotNone(finales["N-LOCAL"]["fecha_envio"].tzinfo)
        self.assertEqual(finales["N-PEND"]["estado"], "COMPLETA")
        self.assertEqual(
            finales["N-SENT"]["fecha_envio"].astimezone(timezone.utc),
            datetime(2026, 7, 13, 20, 35, tzinfo=timezone.utc),
        )
        self.assertEqual(huella_comercial(), huella_antes)

        if db_connection._pool is not None:
            db_connection._pool.closeall()
            db_connection._pool = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
