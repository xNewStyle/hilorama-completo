"""Regresiones del cambio de pedido y la presentación de envíos."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import envios_config
import generar_pdf_venta_premium
import notas
import pdf_cotizacion
from hilorama_desktop.services import notas_api_service


class _CanvasSpy:
    def __init__(self):
        self.textos = []
        self.cajas = []

    def saveState(self):
        return None

    def restoreState(self):
        return None

    def setFillColor(self, _color):
        return None

    def setStrokeColor(self, _color):
        return None

    def setLineWidth(self, _ancho):
        return None

    def setFont(self, _fuente, _tamano):
        return None

    def roundRect(self, x, y, ancho, alto, radio, fill=0, stroke=1):
        self.cajas.append((x, y, ancho, alto, radio, fill, stroke))

    def drawCentredString(self, _x, _y, texto):
        self.textos.append(texto)

    def drawRightString(self, _x, _y, texto):
        self.textos.append(texto)


class PedidoEnvioPdfTests(unittest.TestCase):
    def test_uber_y_didi_requieren_precio_manual(self):
        opciones = envios_config.cargar_envios()
        self.assertIn("Uber", opciones)
        self.assertIn("Didi", opciones)
        self.assertTrue(envios_config.requiere_precio_manual("Uber"))
        self.assertTrue(envios_config.requiere_precio_manual("Didi"))

    def test_envio_gratis_no_se_presenta_como_cero_pesos(self):
        envio = {"paqueteria": "Estafeta", "precio": 0, "gratis": True}
        self.assertEqual(envios_config.formatear_costo_envio(envio), "Envío gratis")
        self.assertEqual(
            envios_config.formatear_resumen_envio(envio),
            "Estafeta | Envío gratis",
        )

    def test_cambiar_pedido_api_envia_unicamente_el_pedido(self):
        respuesta = {"ok": True, "nota": {"id": "COT-1", "pedido": 39}}
        with (
            patch.object(notas_api_service, "_call_api", return_value=respuesta) as call_api,
            patch.object(notas_api_service, "_emitir_cambio_notificaciones") as emitir,
        ):
            nota = notas_api_service.cambiar_pedido_nota("COT-1", "39")

        self.assertEqual(nota["pedido"], 39)
        self.assertEqual(call_api.call_args.args[:2], (
            "cambiar pedido de nota",
            "/api/notas/COT-1",
        ))

        invocar = call_api.call_args.args[2]

        class _Api:
            def actualizar_nota(self, nota_id, data, token=None):
                self.llamada = (nota_id, data, token)
                return respuesta

        api = _Api()
        invocar(api, "token-ficticio")
        self.assertEqual(api.llamada, ("COT-1", {"pedido": 39}, "token-ficticio"))
        emitir.assert_called_once()

    def test_cambiar_pedido_local_no_toca_stock_items_ni_pagos(self):
        class _Conexion:
            def __init__(self):
                self.llamadas = []
                self.confirmado = False
                self.cerrado = False

            def execute(self, sql, params=None):
                self.llamadas.append((sql, tuple(params or ())))

            def commit(self):
                self.confirmado = True

            def close(self):
                self.cerrado = True

        conn = _Conexion()
        with (
            patch.object(notas, "_modo_api", return_value=False),
            patch.object(notas, "get_conn", return_value=conn),
        ):
            self.assertTrue(notas.cambiar_pedido_nota("COT-1", 39))

        self.assertEqual(len(conn.llamadas), 1)
        sql, params = conn.llamadas[0]
        self.assertEqual(" ".join(sql.split()).upper(), "UPDATE NOTAS SET PEDIDO=%S WHERE ID=%S")
        self.assertEqual(params, (39, "COT-1"))
        self.assertTrue(conn.confirmado)
        self.assertTrue(conn.cerrado)
        for prohibido in ("PRODUCTOS", "ITEMS", "PAGOS", "MOVIMIENTOS_ALMACEN"):
            self.assertNotIn(prohibido, sql.upper())

    def test_ambos_pdf_destacan_fecha_en_un_recuadro(self):
        for modulo in (pdf_cotizacion, generar_pdf_venta_premium):
            with self.subTest(modulo=modulo.__name__):
                canvas = _CanvasSpy()
                modulo.draw_info_cliente_envio_fechas(canvas, "2026-09-04")
                self.assertEqual(len(canvas.cajas), 1)
                self.assertIn("FECHA ESTIMADA DE ENVÍO", canvas.textos)
                self.assertIn("04/09/2026 - 06/09/2026", canvas.textos)

    def test_ambos_pdf_escriben_envio_gratis_sin_precio_cero(self):
        for modulo in (pdf_cotizacion, generar_pdf_venta_premium):
            with self.subTest(modulo=modulo.__name__):
                canvas = _CanvasSpy()
                modulo.draw_totales_fuera_tabla(
                    canvas,
                    subtotal=200,
                    envio=0,
                    total=200,
                    envio_gratis=True,
                )
                self.assertIn("Envío gratis", canvas.textos)
                self.assertFalse(any("$0.00" in texto for texto in canvas.textos))


if __name__ == "__main__":
    unittest.main()
