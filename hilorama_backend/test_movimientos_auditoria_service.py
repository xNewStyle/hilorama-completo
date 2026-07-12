"""Pruebas unitarias sin PostgreSQL para los helpers de FASE 9B."""

from __future__ import annotations

import unittest

from hilorama_backend.services.auditoria_service import diferencias_relevantes, limpiar_datos_sensibles
from hilorama_backend.services.movimientos_almacen_service import (
    normalizar_tipo_movimiento,
    registrar_movimiento_almacen,
)


MOVIMIENTO_COLUMNS = {
    "id", "fecha", "usuario", "tipo", "marca", "hilo", "color", "codigo",
    "stock_anterior", "stock_nuevo", "cantidad", "campo", "valor_anterior",
    "valor_nuevo", "motivo", "producto_id", "referencia_tipo", "referencia_id",
    "usuario_id", "cliente_sistema_id", "device_id", "idempotency_key", "metadata_json",
}


class _FakeConnection:
    def __init__(self, existing=None, fail_insert=False):
        self.existing = existing
        self.fail_insert = fail_insert
        self.calls = []
        self.current_row = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT id, tipo, cantidad" in sql:
            self.current_row = self.existing
        elif "INSERT INTO movimientos_almacen" in sql:
            if self.fail_insert:
                raise RuntimeError("fallo simulado de movimiento")
            self.current_row = {"id": 99}
        else:
            self.current_row = None
        return self

    def fetchone(self):
        return self.current_row


class MovimientosAlmacenServiceTests(unittest.TestCase):
    def test_normaliza_tipos_legacy_y_signo(self):
        self.assertEqual(normalizar_tipo_movimiento("AJUSTE", 4), "AJUSTE_POSITIVO")
        self.assertEqual(normalizar_tipo_movimiento("AJUSTE", -4), "AJUSTE_NEGATIVO")
        self.assertEqual(normalizar_tipo_movimiento("salida_stock_api", -1), "VENTA")
        self.assertEqual(normalizar_tipo_movimiento("tipo_desconocido", 1), "OTRO")

    def test_registra_movimiento_consistente(self):
        conn = _FakeConnection()
        resultado = registrar_movimiento_almacen(
            conn,
            MOVIMIENTO_COLUMNS,
            producto={"id": 5, "codigo": "429", "marca": "Velluto"},
            tipo="VENTA",
            cantidad=-2,
            stock_anterior=10,
            stock_nuevo=8,
            referencia_tipo="NOTA",
            referencia_id="COT-10",
            idempotency_key="VENTA:PAGO:COT-10:5",
        )
        self.assertTrue(resultado["creado"])
        self.assertEqual(resultado["movimiento"]["id"], 99)
        insert_sql = next(sql for sql, _ in conn.calls if "INSERT INTO movimientos_almacen" in sql)
        self.assertIn("idempotency_key", insert_sql)

    def test_repeticion_idempotente_no_inserta_otro_movimiento(self):
        existente = {"id": 44, "tipo": "VENTA", "cantidad": -2, "stock_anterior": 10, "stock_nuevo": 8}
        conn = _FakeConnection(existing=existente)
        resultado = registrar_movimiento_almacen(
            conn,
            MOVIMIENTO_COLUMNS,
            producto={"id": 5},
            tipo="VENTA",
            cantidad=-2,
            stock_anterior=10,
            stock_nuevo=8,
            idempotency_key="VENTA:PAGO:COT-10:5",
        )
        self.assertTrue(resultado["idempotente"])
        self.assertFalse(any("INSERT INTO movimientos_almacen" in sql for sql, _ in conn.calls))

    def test_movimiento_inconsistente_falla_antes_de_escribir(self):
        conn = _FakeConnection()
        with self.assertRaises(ValueError):
            registrar_movimiento_almacen(
                conn,
                MOVIMIENTO_COLUMNS,
                producto={"id": 5},
                tipo="VENTA",
                cantidad=-2,
                stock_anterior=10,
                stock_nuevo=9,
            )
        self.assertEqual(conn.calls, [])

    def test_fallo_del_insert_propagado_para_revertir_transaccion_externa(self):
        conn = _FakeConnection(fail_insert=True)
        with self.assertRaisesRegex(RuntimeError, "fallo simulado"):
            registrar_movimiento_almacen(
                conn,
                MOVIMIENTO_COLUMNS,
                producto={"id": 5},
                tipo="AJUSTE_NEGATIVO",
                cantidad=-1,
                stock_anterior=3,
                stock_nuevo=2,
            )
        self.assertTrue(any("ROLLBACK TO SAVEPOINT" in sql for sql, _ in conn.calls))


class AuditoriaServiceTests(unittest.TestCase):
    def test_oculta_secretos_en_objetos_anidados(self):
        limpio = limpiar_datos_sensibles(
            {
                "password": "no-visible",
                "anidado": {"access_token": "no-visible"},
                "lista": [{"clave_autorizacion": "no-visible"}],
                "normal": "si-se-conserva",
            }
        )
        self.assertEqual(limpio["password"], "[oculto]")
        self.assertEqual(limpio["anidado"]["access_token"], "[oculto]")
        self.assertEqual(limpio["lista"][0]["clave_autorizacion"], "[oculto]")
        self.assertEqual(limpio["normal"], "si-se-conserva")

    def test_diferencias_guarda_solo_campos_que_cambian(self):
        antes, despues = diferencias_relevantes(
            {"precio": 50, "activo": True, "token": "anterior"},
            {"precio": 55, "activo": True, "token": "nuevo"},
        )
        self.assertEqual(antes, {"precio": 50, "token": "[oculto]"})
        self.assertEqual(despues, {"precio": 55, "token": "[oculto]"})


if __name__ == "__main__":
    unittest.main()
