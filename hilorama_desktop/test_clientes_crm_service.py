"""Pruebas sin red para servicio, navegacion y ciclo de vida del CRM."""

import inspect
import queue
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.services import clientes_crm_service as crm
from hilorama_desktop.ui import main_window
from hilorama_desktop.ui.clientes_crm_view import ClientesCrmWindow


class ClientesCrmServiceTests(unittest.TestCase):
    def test_mensaje_vip_no_envia_y_menciona_nombre(self):
        mensaje = crm.generar_mensaje_whatsapp({"nombre": "Ana", "segmento": "VIP"})
        self.assertIn("Ana", mensaje)
        self.assertIn("novedades", mensaje.lower())

    def test_mensaje_frecuente_usa_cadencia(self):
        mensaje = crm.generar_mensaje_whatsapp({
            "nombre": "Luz",
            "segmento": "FRECUENTE",
            "frecuencia_promedio_dias": 24,
        })
        self.assertIn("24", mensaje)

    def test_normalizacion_acepta_respuesta_vacia(self):
        resumen = crm._normalizar_resumen({})
        self.assertEqual(resumen["total_clientas"], 0)
        self.assertEqual(resumen["ticket_promedio_general"], 0.0)
        self.assertEqual(crm._graficas_vacias()["segmentos"], [])

    @patch("hilorama_desktop.services.clientes_crm_service._call_api")
    def test_panoramica_usa_un_solo_endpoint_con_resumen(self, call_api):
        call_api.return_value = {
            "resumen": {"total_clientas": 1, "ticket_promedio_general": 55},
            "ranking": [{"cliente_id": 8, "nombre": "Ana", "total_comprado": 55}],
            "total": 1,
            "limit": 100,
            "orden": "total_comprado",
        }

        panoramica = crm.cargar_panoramica(limit=100)

        self.assertEqual(call_api.call_count, 1)
        self.assertEqual(panoramica["resumen"]["total_clientas"], 1)
        self.assertEqual(panoramica["ranking"][0]["cliente_id"], 8)


class ClientesCrmNavigationTests(unittest.TestCase):
    def test_boton_clientes_monta_crm_sin_ruta_legacy(self):
        factory = object()
        app = SimpleNamespace(
            _crear_vista_clientes_api=factory,
            _mostrar_modulo=Mock(),
        )

        main_window.HiloramaDesktopApp.mostrar_clientes(app)

        app._mostrar_modulo.assert_called_once_with("clientes", factory)
        self.assertNotIn(
            "abrir_clientes",
            inspect.getsource(main_window.HiloramaDesktopApp.mostrar_clientes),
        )

    def test_factory_crea_clientes_crm_view_embebida(self):
        parent = object()
        callback = object()
        expected = object()
        app = SimpleNamespace(_editar_cliente_desde_crm=callback)

        with patch(
            "hilorama_desktop.ui.clientes_crm_view.ClientesCRMView",
            return_value=expected,
        ) as view_class:
            result = main_window.HiloramaDesktopApp._crear_vista_clientes_api(app, parent)

        self.assertIs(result, expected)
        view_class.assert_called_once_with(parent, editar_cliente_callback=callback)

    def test_modulo_clientes_se_monta_en_content(self):
        loading = Mock()
        content = object()
        view = object()
        factory = Mock(return_value=view)
        app = SimpleNamespace(
            content=content,
            views_cache={},
            current_view=None,
            current_module=None,
            _set_modulo_actual=Mock(),
            _set_view=Mock(),
            update_idletasks=Mock(),
            _log_tiempo=Mock(),
        )

        with (
            patch.object(main_window, "_crear_placeholder", return_value=loading),
            patch.object(main_window, "log_info"),
        ):
            main_window.HiloramaDesktopApp._mostrar_modulo(app, "clientes", factory)

        factory.assert_called_once_with(content)
        self.assertIs(app.views_cache["clientes"], view)
        self.assertEqual(app.current_module, "clientes")
        app._set_view.assert_any_call(view)
        loading.destroy.assert_called_once_with()

    def test_vista_avanzada_conserva_filtros_y_metricas(self):
        source = inspect.getsource(ClientesCrmWindow._construir)
        for text in (
            '"Buscar"',
            '"Segmento"',
            '"Desde"',
            '"Hasta"',
            '"Orden"',
            '"Mostrar"',
            '"Total clientas"',
            '"Dormidas"',
            '"VIP"',
            '"Ticket promedio"',
        ):
            self.assertIn(text, source)

    def test_error_de_red_mantiene_vista_y_muestra_estado_controlado(self):
        controller = object.__new__(ClientesCrmWindow)
        controller._carga_ranking_en_curso = True
        controller._firma_carga_en_curso = ("pendiente",)
        controller._recarga_pendiente = False
        controller.btn_actualizar = Mock()
        controller.estado_carga_var = Mock()
        controller._mostrar_vacio_detalle = Mock()

        with patch("hilorama_desktop.ui.clientes_crm_view.log_error"):
            controller._aplicar_panoramica(
                {"error": RuntimeError("backend no disponible"), "firma": ("pendiente",)},
                0.01,
            )

        controller.btn_actualizar.configure.assert_called_once_with(state="normal")
        controller._mostrar_vacio_detalle.assert_called_once()
        self.assertFalse(controller._carga_ranking_en_curso)

    def test_respuesta_tardia_no_actualiza_vista_destruida(self):
        class DestroyedHost:
            def winfo_exists(self):
                return False

            def after(self, *_args):
                raise AssertionError("No debe programar callbacks en una vista destruida")

        controller = object.__new__(ClientesCrmWindow)
        controller.win = DestroyedHost()
        controller._resultados_async = queue.Queue()
        controller._resultados_async.put({"tipo": "panoramica", "resultado": {}})
        controller._aplicar_resultado_async = Mock()

        controller._procesar_resultados_async()

        controller._aplicar_resultado_async.assert_not_called()


if __name__ == "__main__":
    unittest.main()
