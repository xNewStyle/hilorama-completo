"""Pruebas del health check movil sin PostgreSQL real ni cambios de esquema."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hilorama_celular import app as mobile


class _CursorSalud:
    def __init__(self, row=(1,)):
        self.row = row
        self.queries = []
        self.closed = False

    def execute(self, sql):
        self.queries.append(sql)

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class _ConexionSalud:
    def __init__(self, cursor=None):
        self.health_cursor = cursor or _CursorSalud()
        self.rollbacks = 0
        self.commits = 0

    def cursor(self):
        return self.health_cursor

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1


class _PoolSalud:
    def __init__(self, conn=None, error=None):
        self.conn = conn or _ConexionSalud()
        self.error = error
        self.dev_begin = 0
        self.dev_end = 0

    def getconn(self):
        self.dev_begin += 1
        if self.error:
            raise self.error
        return self.conn

    def putconn(self, conn):
        self.dev_end += 1
        if conn is not self.conn:
            raise AssertionError("Se devolvio una conexion distinta al pool.")


class HealthSinDDLTests(unittest.TestCase):
    def setUp(self):
        mobile.app.config.update(TESTING=True)
        self.client = mobile.app.test_client()

    def test_health_responde_ok_y_solo_ejecuta_select(self):
        conn = _ConexionSalud()
        pool = _PoolSalud(conn=conn)
        with patch.object(mobile, "get_pool", return_value=pool), patch.object(
            mobile, "ensure_schema"
        ) as ensure_schema, patch.object(mobile, "require_pin") as require_pin:
            for _ in range(3):
                response = self.client.get("/api/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {
                    "status": "ok",
                    "service": "hilorama-celular",
                })

        ensure_schema.assert_not_called()
        require_pin.assert_not_called()
        self.assertEqual(conn.health_cursor.queries, ["SELECT 1"] * 3)
        self.assertFalse(any(
            token in query.upper()
            for query in conn.health_cursor.queries
            for token in ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")
        ))
        self.assertEqual(conn.rollbacks, 3)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(pool.dev_begin, 3)
        self.assertEqual(pool.dev_end, 3)

    def test_raiz_y_recursos_estaticos_no_ejecutan_esquema(self):
        with patch.object(mobile, "ensure_schema") as ensure_schema, patch.object(
            mobile, "require_pin"
        ) as require_pin:
            for path in ("/", "/manifest.webmanifest", "/icon-192.png"):
                response = self.client.get(path)
                try:
                    self.assertEqual(response.status_code, 200)
                finally:
                    response.close()
        ensure_schema.assert_not_called()
        require_pin.assert_not_called()

    def test_ruta_comercial_conserva_ensure_schema(self):
        with patch.object(mobile, "ensure_schema") as ensure_schema, patch.object(
            mobile, "require_pin", return_value=("PIN requerido", 418)
        ) as require_pin:
            response = self.client.get("/api/resumen")

        self.assertEqual(response.status_code, 418)
        ensure_schema.assert_called_once_with()
        require_pin.assert_called_once_with()

    def test_fallo_de_base_es_controlado_y_no_filtra_detalles(self):
        detalle_sensible = "detalle-interno-sensible-que-no-debe-aparecer"
        pool = _PoolSalud(error=RuntimeError(detalle_sensible))
        with patch.object(mobile, "get_pool", return_value=pool), patch.object(
            mobile, "ensure_schema"
        ) as ensure_schema, patch.object(mobile, "require_pin") as require_pin:
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {
            "status": "degraded",
            "service": "hilorama-celular",
            "database": "unavailable",
        })
        self.assertNotIn(detalle_sensible, response.get_data(as_text=True))
        ensure_schema.assert_not_called()
        require_pin.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
