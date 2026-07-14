"""Pruebas sin base de datos para el calculo del CRM comercial."""

from datetime import datetime, timedelta
import unittest

from hilorama_backend.services.clientes_analytics_service import construir_analitica_clientas


AHORA = datetime(2026, 7, 10, 12, 0, 0)


def _venta(nota_id, cliente_id, fecha, total, estado="PAGADA"):
    return {
        "id": nota_id,
        "cliente_id": cliente_id,
        "fecha": fecha.strftime("%Y-%m-%d"),
        "estado": estado,
        "total_final": total,
    }


class ClientesAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.clientes = [
            {"id": 1, "nombre": "Sin compras", "telefono": "5550000001", "direccion": {}},
            {"id": 2, "nombre": "Nueva", "telefono": "5550000002", "direccion": {}},
            {"id": 3, "nombre": "VIP", "telefono": "5550000003", "direccion": {}},
            {"id": 4, "nombre": "Dormida", "telefono": "5550000004", "direccion": {}},
        ]
        self.ventas = [
            _venta("COT-1", 2, AHORA - timedelta(days=7), 450),
            _venta("COT-COTIZACION", 2, AHORA - timedelta(days=2), 500, estado="COTIZACION"),
            *[
                _venta(f"VIP-{indice}", 3, AHORA - timedelta(days=indice * 14), 1000)
                for indice in range(6)
            ],
            *[
                _venta(f"DORM-{indice}", 4, AHORA - timedelta(days=90 + indice * 14), 700)
                for indice in range(4)
            ],
        ]
        self.items = [
            {
                "nota_id": "VIP-0",
                "marca": "Velluto",
                "hilo": "Velluto",
                "codigo": "429",
                "color": "Rosa",
                "cantidad": 3,
                "precio": 1000 / 3,
            }
        ]

    def _metricas(self):
        return construir_analitica_clientas(
            self.clientes,
            self.ventas,
            self.items,
            ahora=AHORA,
            incluir_historial=True,
        )

    def test_cliente_sin_compras_permanece_visible(self):
        filas = {fila["cliente_id"]: fila for fila in self._metricas()["clientes"]}
        self.assertEqual(filas[1]["segmento"], "SIN_COMPRAS")
        self.assertEqual(filas[1]["numero_compras"], 0)

    def test_compra_reciente_unica_es_nueva_y_no_cuenta_cotizacion(self):
        filas = {fila["cliente_id"]: fila for fila in self._metricas()["clientes"]}
        self.assertEqual(filas[2]["segmento"], "NUEVA")
        self.assertEqual(filas[2]["numero_compras"], 1)
        self.assertEqual(filas[2]["total_comprado"], 450)

    def test_clienta_frecuente_de_alto_valor_es_vip(self):
        filas = {fila["cliente_id"]: fila for fila in self._metricas()["clientes"]}
        self.assertEqual(filas[3]["segmento"], "VIP")
        self.assertGreaterEqual(filas[3]["indice_compra"], 85)
        self.assertEqual(filas[3]["marcas_favoritas"][0]["marca"], "Velluto")

    def test_clienta_dormida_tiene_indice_acotado(self):
        filas = {fila["cliente_id"]: fila for fila in self._metricas()["clientes"]}
        self.assertEqual(filas[4]["segmento"], "DORMIDA")
        self.assertLessEqual(filas[4]["indice_compra"], 19)

    def test_ranking_y_graficas_se_crean_con_datos_finales(self):
        data = self._metricas()
        self.assertEqual(data["clientes"][0]["cliente_id"], 3)
        self.assertTrue(data["graficas"]["top_clientas_por_total"])
        self.assertGreater(data["resumen"]["venta_total_periodo"], 0)

    def test_ranking_ligero_omite_favoritos_e_historial(self):
        data = construir_analitica_clientas(
            self.clientes,
            self.ventas,
            self.items,
            ahora=AHORA,
            incluir_historial=False,
            incluir_favoritos=False,
            incluir_graficas=False,
        )
        filas = {fila["cliente_id"]: fila for fila in data["clientes"]}
        self.assertEqual(filas[3]["marcas_favoritas"], [])
        self.assertEqual(filas[3]["productos_favoritos"], [])
        self.assertNotIn("historial_resumido", filas[3])
        self.assertEqual(data["graficas"], {})

    def test_estados_posteriores_al_pago_cuentan_como_compras(self):
        ventas = [
            _venta("PROC-1", 2, AHORA - timedelta(days=12), 100, estado="EN_PROCESO"),
            _venta("INC-1", 2, AHORA - timedelta(days=8), 200, estado="INCOMPLETA"),
            _venta("ENV-1", 2, AHORA - timedelta(days=3), 300, estado="ENVIADO"),
        ]
        data = construir_analitica_clientas(self.clientes, ventas, [], ahora=AHORA)
        fila = next(item for item in data["clientes"] if item["cliente_id"] == 2)
        self.assertEqual(fila["numero_compras"], 3)
        self.assertEqual(fila["total_comprado"], 600)

    def test_archivada_solo_cuenta_con_evidencia_de_pago(self):
        pagada = _venta("ARCH-P", 2, AHORA - timedelta(days=20), 250, estado="ARCHIVADA")
        pagada["fecha_pago"] = (AHORA - timedelta(days=20)).isoformat()
        sin_pago = _venta("ARCH-C", 2, AHORA - timedelta(days=10), 900, estado="ARCHIVADA")
        data = construir_analitica_clientas(self.clientes, [pagada, sin_pago], [], ahora=AHORA)
        fila = next(item for item in data["clientes"] if item["cliente_id"] == 2)
        self.assertEqual(fila["numero_compras"], 1)
        self.assertEqual(fila["total_comprado"], 250)

    def test_anulada_y_venta_pendiente_no_cuentan_como_compra(self):
        ventas = [
            _venta("ANU-1", 2, AHORA - timedelta(days=5), 800, estado="ANULADA"),
            _venta("PEN-1", 2, AHORA - timedelta(days=4), 600, estado="VENTA_PENDIENTE"),
        ]
        data = construir_analitica_clientas(self.clientes, ventas, [], ahora=AHORA)
        fila = next(item for item in data["clientes"] if item["cliente_id"] == 2)
        self.assertEqual(fila["numero_compras"], 0)
        self.assertEqual(fila["total_comprado"], 0)

    def test_venta_duplicada_por_id_solo_cuenta_una_vez(self):
        venta = _venta("DUP-1", 2, AHORA - timedelta(days=5), 400)
        data = construir_analitica_clientas(self.clientes, [venta, dict(venta)], [], ahora=AHORA)
        fila = next(item for item in data["clientes"] if item["cliente_id"] == 2)
        self.assertEqual(fila["numero_compras"], 1)
        self.assertEqual(fila["total_comprado"], 400)

    def test_compras_distintas_el_mismo_dia_se_conservan(self):
        ventas = [
            _venta("MISMO-1", 2, AHORA - timedelta(days=5), 120),
            _venta("MISMO-2", 2, AHORA - timedelta(days=5), 180),
        ]
        data = construir_analitica_clientas(self.clientes, ventas, [], ahora=AHORA)
        fila = next(item for item in data["clientes"] if item["cliente_id"] == 2)
        self.assertEqual(fila["numero_compras"], 2)
        self.assertEqual(fila["total_comprado"], 300)
        self.assertIsNone(fila["frecuencia_promedio_dias"])


if __name__ == "__main__":
    unittest.main()
