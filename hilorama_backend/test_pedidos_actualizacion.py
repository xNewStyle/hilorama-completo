"""Regresiones de actualizacion de fechas de pedidos sin base real."""

from contextlib import nullcontext
from datetime import date
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hilorama_backend.app as backend


class _Resultado:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _ConexionPedidos:
    def __init__(self):
        self.pedido = {
            "numero": 37,
            "desde": date(2026, 8, 1),
            "hasta": date(2026, 8, 31),
            "activo": True,
        }
        self.calls = []

    def execute(self, sql, params=None):
        params = tuple(params or ())
        self.calls.append((sql, params))
        normalizada = " ".join(sql.split()).upper()
        if normalizada.startswith("SELECT") and "FROM PEDIDOS" in normalizada:
            return _Resultado(dict(self.pedido))
        if normalizada.startswith("UPDATE PEDIDOS SET"):
            if "DESDE=%S" in normalizada:
                self.pedido["desde"] = params[0]
            if "HASTA=%S" in normalizada:
                indice = 1 if "DESDE=%S" in normalizada else 0
                self.pedido["hasta"] = params[indice]
        return _Resultado()


def _columnas(_conn, tabla):
    if tabla == "pedidos":
        return {"numero", "desde", "hasta", "activo"}
    return set()


class PedidosActualizacionTests(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True)
        self.client = backend.app.test_client()

    def test_actualiza_fechas_sin_crear_otro_pedido(self):
        conn = _ConexionPedidos()
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            pedido = backend._actualizar_pedido_api(
                conn,
                37,
                {"desde": "01/08/2026", "hasta": "31/12/2026"},
            )

        self.assertEqual(pedido["numero"], 37)
        self.assertEqual(pedido["desde"], "2026-08-01")
        self.assertEqual(pedido["hasta"], "2026-12-31")
        sql = "\n".join(call[0] for call in conn.calls).upper()
        self.assertIn("UPDATE PEDIDOS SET", sql)
        self.assertNotIn("INSERT INTO PEDIDOS", sql)

    def test_rechaza_hasta_anterior_sin_actualizar(self):
        conn = _ConexionPedidos()
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            with self.assertRaisesRegex(ValueError, "Hasta"):
                backend._actualizar_pedido_api(
                    conn,
                    37,
                    {"desde": "01/08/2026", "hasta": "01/01/2026"},
                )
        self.assertFalse(any("UPDATE PEDIDOS" in sql.upper() for sql, _ in conn.calls))

    def test_endpoint_actualiza_y_requiere_sesion(self):
        sin_sesion = self.client.patch(
            "/api/pedidos/37",
            json={"desde": "01/08/2026", "hasta": "31/12/2026"},
        )
        self.assertIn(sin_sesion.status_code, {401, 403})

        conn = _ConexionPedidos()
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "get_conn", return_value=nullcontext(conn)),
            patch.object(backend, "_columnas_tabla_api", side_effect=_columnas),
        ):
            respuesta = self.client.patch(
                "/api/pedidos/37",
                json={"desde": "01/08/2026", "hasta": "31/12/2026"},
            )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.get_json()["ok"])

    def test_actualizacion_no_toca_notas_stock_ni_pagos(self):
        source = inspect.getsource(backend._actualizar_pedido_api).lower()
        for prohibido in (
            "update notas",
            "update productos",
            "insert into pagos",
            "movimientos_almacen",
        ):
            self.assertNotIn(prohibido, source)


if __name__ == "__main__":
    unittest.main()
