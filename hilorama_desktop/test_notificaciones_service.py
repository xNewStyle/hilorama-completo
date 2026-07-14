"""Pruebas sin red para el servicio Desktop de notificaciones."""

import copy
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.services import notificaciones_service as service
from hilorama_desktop.services import clientes_api_service
from hilorama_desktop.services import envios_api_service
from hilorama_desktop.services import notas_api_service
from hilorama_desktop.services import pedidos_api_service


def _respuesta(operacion=None, oportunidades=None, actualizadas=True):
    return {
        "ok": True,
        "operacion": {"notificaciones": list(operacion or [])},
        "oportunidades": {"notificaciones": list(oportunidades or [])},
        "oportunidades_actualizadas": actualizadas,
        "generado_en": "2026-07-13T12:00:00",
    }


def _aviso(key, seccion="OPERACION", prioridad="NORMAL", categoria="OTRA"):
    return {
        "key": key,
        "seccion": seccion,
        "prioridad": prioridad,
        "categoria": categoria,
        "titulo": f"Aviso {key}",
        "mensaje": "Detalle controlado",
    }


class NotificacionesDesktopServiceTests(unittest.TestCase):
    def setUp(self):
        with service._lock:
            service._ultimo_resumen = None
            service._cache_generation = 0
            service._listeners.clear()

    def tearDown(self):
        with service._lock:
            service._ultimo_resumen = None
            service._cache_generation = 0
            service._listeners.clear()

    def test_normaliza_deduplica_y_recalcula_contadores(self):
        urgente = _aviso("venta:1", prioridad="URGENTE", categoria="PENDIENTE_PAGO")
        normal = _aviso("cliente:2", "OPORTUNIDADES", "NORMAL", "DORMIDA")
        resumen = service.normalizar_resumen(
            _respuesta([urgente, copy.deepcopy(urgente)], [normal])
        )

        self.assertEqual(resumen["total"], 2)
        self.assertEqual(resumen["urgentes"], 1)
        self.assertEqual(resumen["normales"], 1)
        self.assertEqual(resumen["operacion"]["categorias"], {"PENDIENTE_PAGO": 1})

    @patch("hilorama_desktop.services.notificaciones_service._call_api")
    def test_actualizacion_operativa_conserva_oportunidades_diarias(self, call_api):
        call_api.side_effect = [
            _respuesta(
                [_aviso("venta:1")],
                [_aviso("cliente:2", "OPORTUNIDADES", categoria="PROXIMA_COMPRA")],
                actualizadas=True,
            ),
            _respuesta([_aviso("venta:3")], [], actualizadas=False),
        ]

        service.obtener_resumen(incluir_oportunidades=True)
        segundo = service.obtener_resumen(incluir_oportunidades=False)

        self.assertEqual(segundo["operacion"]["notificaciones"][0]["key"], "venta:3")
        self.assertEqual(segundo["oportunidades"]["notificaciones"][0]["key"], "cliente:2")
        self.assertEqual(call_api.call_count, 2)

    def test_mensaje_de_pago_es_borrador_y_no_envia(self):
        texto = service.preparar_mensaje({
            "categoria": "PENDIENTE_PAGO",
            "cliente_nombre": "María López",
            "folio": "VEN-25",
        })
        self.assertIn("María", texto)
        self.assertIn("VEN-25", texto)
        self.assertNotIn("pred", texto.lower())
        self.assertNotIn("whatsapp", texto.lower())

    def test_evento_notifica_listeners_sin_persistir_datos(self):
        eventos = []
        callback = eventos.append
        service.registrar_listener_notificaciones(callback)

        service.emitir_actualizacion_notificaciones(incluir_oportunidades=True)
        service.quitar_listener_notificaciones(callback)
        service.emitir_actualizacion_notificaciones(incluir_oportunidades=False)

        self.assertEqual(eventos, [True])

    @patch("hilorama_desktop.services.notificaciones_service._call_api")
    def test_control_temporal_elimina_solo_oportunidad_local(self, call_api):
        call_api.return_value = {"ok": True, "control": {"accion": "RECORDAR_3"}}
        oportunidad = _aviso("proxima_compra:7", "OPORTUNIDADES", categoria="PROXIMA_COMPRA")
        oportunidad["cliente_id"] = 7
        with service._lock:
            service._ultimo_resumen = service.normalizar_resumen(_respuesta([], [oportunidad]))

        resultado = service.controlar_oportunidad(7, "PROXIMA_COMPRA", "RECORDAR_3")

        self.assertEqual(resultado["accion"], "RECORDAR_3")
        self.assertEqual(service.obtener_ultimo_resumen()["total"], 0)

    @patch("hilorama_desktop.services.notificaciones_service._call_api")
    def test_respuesta_lenta_de_sesion_cerrada_no_rellena_cache(self, call_api):
        inicio = threading.Event()
        continuar = threading.Event()

        def respuesta_lenta(*_args, **_kwargs):
            inicio.set()
            continuar.wait(timeout=2)
            return _respuesta([_aviso("sesion-anterior")], [])

        call_api.side_effect = respuesta_lenta
        worker = threading.Thread(target=service.obtener_resumen, daemon=True)
        worker.start()
        self.assertTrue(inicio.wait(timeout=1))

        service.invalidar_cache_sesion()
        continuar.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(service.obtener_ultimo_resumen()["total"], 0)

    def test_eventos_se_emiten_despues_de_una_sola_operacion_comercial(self):
        casos = (
            (
                notas_api_service,
                "registrar_pago",
                (71,),
                {"pago": {"id": 1}},
                {"incluir_oportunidades": True},
            ),
            (
                pedidos_api_service,
                "asignar_notas_empacador",
                ([71], 4),
                {"ok": True},
                {},
            ),
            (
                envios_api_service,
                "actualizar_envio_nota",
                (71, {"guia": "GUIA-FICTICIA"}),
                {"envio": {"guia": "GUIA-FICTICIA"}},
                {},
            ),
            (
                envios_api_service,
                "marcar_envio_nota",
                (71,),
                {"ok": True},
                {},
            ),
            (
                clientes_api_service,
                "actualizar_cliente",
                (8, {"nombre": "Clienta ficticia"}),
                {"cliente": {"id": 8}},
                {},
            ),
        )
        for modulo, funcion, argumentos, respuesta, kwargs_evento in casos:
            with self.subTest(funcion=funcion), patch.object(
                modulo,
                "_call_api",
                return_value=respuesta,
            ) as call_api, patch.object(modulo, "_emitir_cambio_notificaciones") as emitir:
                getattr(modulo, funcion)(*argumentos)
                call_api.assert_called_once()
                emitir.assert_called_once_with(**kwargs_evento)

    def test_fallo_comercial_no_emite_actualizacion_falsa(self):
        with patch.object(
            notas_api_service,
            "_call_api",
            side_effect=RuntimeError("fallo controlado"),
        ) as call_api, patch.object(
            notas_api_service,
            "_emitir_cambio_notificaciones",
        ) as emitir:
            with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                notas_api_service.registrar_pago(72)
        call_api.assert_called_once()
        emitir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
