"""Pruebas puras de filtros, badge y contrato visual de la campana."""

import inspect
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.ui.notificaciones_view import (
    NotificationBellController,
    NotificationContent,
    NotificationPanel,
    filtrar_notificaciones,
    geometria_panel,
    geometria_vista_completa,
    texto_badge,
)
from hilorama_desktop.ui.main_window import HiloramaDesktopApp


def _aviso(indice, seccion="OPERACION", categoria="PENDIENTE_PAGO", prioridad="NORMAL"):
    return {
        "key": f"aviso:{indice}",
        "seccion": seccion,
        "categoria": categoria,
        "prioridad": prioridad,
        "titulo": f"Venta pendiente {indice}",
        "mensaje": "Clienta María requiere atención",
        "cliente_nombre": "María López",
        "folio": f"VEN-{indice:03d}",
        "metadata": {"codigo": f"COD-{indice}"},
    }


def _resumen(operacion=None, oportunidades=None):
    return {
        "total": len(operacion or []) + len(oportunidades or []),
        "urgentes": 0,
        "atencion": 0,
        "normales": 0,
        "operacion": {"notificaciones": list(operacion or [])},
        "oportunidades": {"notificaciones": list(oportunidades or [])},
    }


class NotificacionesViewTests(unittest.TestCase):
    def test_badge_cero_uno_y_99_mas(self):
        self.assertEqual(texto_badge(0), "")
        self.assertEqual(texto_badge(1), "1")
        self.assertEqual(texto_badge(99), "99")
        self.assertEqual(texto_badge(100), "99+")

    def test_filtros_seccion_prioridad_categoria_y_busqueda_son_locales(self):
        urgente = _aviso(1, prioridad="URGENTE")
        envio = _aviso(2, categoria="GUIA_SIN_ENVIO")
        dormida = _aviso(3, "OPORTUNIDADES", "DORMIDA")
        data = _resumen([urgente, envio], [dormida])

        self.assertEqual(len(filtrar_notificaciones(data, filtro="Urgentes")), 1)
        self.assertEqual(filtrar_notificaciones(data, filtro="Envíos")[0]["key"], "aviso:2")
        self.assertEqual(
            filtrar_notificaciones(data, seccion="Oportunidades 1")[0]["key"],
            "aviso:3",
        )
        self.assertEqual(filtrar_notificaciones(data, busqueda="VEN-002")[0]["key"], "aviso:2")
        self.assertEqual(filtrar_notificaciones(data, busqueda="COD-1")[0]["key"], "aviso:1")

    def test_panel_compacto_limita_a_20_sin_perder_total(self):
        data = _resumen([_aviso(i) for i in range(25)])
        self.assertEqual(len(filtrar_notificaciones(data, limite=20)), 20)
        self.assertEqual(len(filtrar_notificaciones(data)), 25)

    def test_vista_completa_cabe_en_resoluciones_comunes(self):
        for pantalla in ((1024, 720), (1366, 768), (1920, 1080)):
            ancho, alto, x, y = geometria_vista_completa(*pantalla)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + ancho, pantalla[0])
            self.assertLessEqual(y + alto, pantalla[1])
        self.assertLess(geometria_vista_completa(1366, 768)[1], 700)

    def test_panel_cabe_debajo_de_campana_en_1024_por_720(self):
        ancho, alto, x, y = geometria_panel(1024, 720, 970, 31, 42, 48)
        self.assertGreaterEqual(x, 8)
        self.assertGreaterEqual(y, 31 + 48)
        self.assertLessEqual(x + ancho, 1024 - 8)
        self.assertLessEqual(y + alto, 720 - 8)

    def test_contrato_visual_incluye_error_reintento_escape_y_panel_unico(self):
        contenido = inspect.getsource(NotificationContent._build)
        panel = inspect.getsource(NotificationPanel)
        toggle = inspect.getsource(NotificationBellController.toggle_panel)
        self.assertIn('text="Reintentar"', contenido)
        self.assertIn('bind("<Escape>"', panel)
        self.assertIn("self.panel.close()", toggle)

    def test_refresco_es_asincrono_y_serializado(self):
        refresh = inspect.getsource(NotificationBellController.refresh)
        self.assertIn("threading.Thread", refresh)
        self.assertIn("self._refreshing", refresh)
        self.assertIn("self._pending_refresh", refresh)

    def test_evento_comercial_no_comparte_bandera_con_refresco_en_curso(self):
        root = Mock()
        root.after.return_value = "event-job"
        controller = SimpleNamespace(
            _event_include_opportunities=False,
            _pending_opportunities=False,
            _event_job=None,
            root=root,
            _run_event_refresh=Mock(),
        )

        NotificationBellController._debounce_event(controller, True)

        self.assertTrue(controller._event_include_opportunities)
        self.assertFalse(controller._pending_opportunities)
        self.assertEqual(controller._event_job, "event-job")

    def test_refresco_pendiente_conserva_solicitud_de_oportunidades(self):
        controller = SimpleNamespace(
            _stopped=False,
            _refreshing=True,
            _pending_refresh=False,
            _pending_opportunities=False,
            _lock=threading.Lock(),
        )

        iniciado = NotificationBellController.refresh(controller, True)

        self.assertFalse(iniciado)
        self.assertTrue(controller._pending_refresh)
        self.assertTrue(controller._pending_opportunities)

    def test_shutdown_cancela_todos_los_temporizadores(self):
        root = Mock()
        panel = Mock()
        full_view = Mock()
        controller = SimpleNamespace(
            _stopped=False,
            root=root,
            panel=panel,
            full_view=full_view,
            _startup_job="startup",
            _periodic_job="periodic",
            _event_job="event",
            _poll_job="poll",
            _followup_job="followup",
            _on_service_event=Mock(),
        )

        with patch("hilorama_desktop.ui.notificaciones_view.servicio") as servicio:
            NotificationBellController.shutdown(controller)

        self.assertTrue(controller._stopped)
        self.assertEqual(root.after_cancel.call_count, 5)
        servicio.invalidar_cache_sesion.assert_called_once_with()
        panel.close.assert_called_once_with()
        full_view.close.assert_called_once_with()

    def test_error_de_red_conserva_datos_anteriores(self):
        anterior = _resumen([_aviso(41)])
        controller = SimpleNamespace(
            _stopped=False,
            resumen=anterior,
            error=None,
            _lock=threading.Lock(),
            _refreshing=True,
            _pending_refresh=False,
            _pending_opportunities=False,
            _apply_counts=Mock(),
            _update_views=Mock(),
            root=Mock(),
            _followup_job=None,
        )

        NotificationBellController._finish_refresh(
            controller,
            None,
            TimeoutError("timeout de prueba"),
            False,
        )

        self.assertIs(controller.resumen, anterior)
        self.assertIn("reintentar", controller.error.lower())
        self.assertFalse(controller._refreshing)
        controller._apply_counts.assert_called_once_with()
        controller._update_views.assert_called_once_with(loading=False)

    def test_navegacion_usa_ids_internos_y_pantallas_existentes(self):
        app = SimpleNamespace(
            _abrir_cliente_notificacion=Mock(),
            _abrir_producto_notificacion=Mock(),
            _abrir_panel_ventas_notificacion=Mock(),
            _abrir_venta_notificacion=Mock(),
        )
        HiloramaDesktopApp._navegar_notificacion(
            app,
            {"cliente_id": 27, "destino_id": "nombre-no-usado"},
            "ABRIR_CLIENTE",
        )
        HiloramaDesktopApp._navegar_notificacion(
            app,
            {"nota_id": "VEN-55", "destino_id": "folio-no-usado"},
            "ABRIR_VENTA",
        )
        app._abrir_cliente_notificacion.assert_called_once_with(27, abrir_historial=False)
        app._abrir_venta_notificacion.assert_called_once_with("VEN-55")

    def test_todas_las_acciones_de_navegacion_tienen_destino(self):
        casos = {
            "ABRIR_CLIENTE": ("cliente", (27,), {"abrir_historial": False}),
            "VER_PRODUCTOS_FRECUENTES": ("cliente", (27,), {"abrir_historial": False}),
            "VER_HISTORIAL_CLIENTE": ("cliente", (27,), {"abrir_historial": True}),
            "ABRIR_PRODUCTO": ("producto", None, None),
            "ABRIR_ALMACEN": ("producto", None, None),
            "ABRIR_ENVIOS": ("panel", ("abrir_panel_envios",), {}),
            "ABRIR_ASIGNACION": ("panel", ("abrir_panel_asignacion",), {}),
            "ABRIR_PEDIDO": ("panel", ("abrir_panel_asignacion",), {}),
            "ABRIR_REPORTE_ESCANEO": ("panel", ("abrir_panel_errores",), {}),
            "ABRIR_IMPRESION": ("venta", (71,), {"imprimir": True}),
            "ABRIR_VENTA": ("venta", (71,), {}),
        }
        for accion, (destino, argumentos, kwargs) in casos.items():
            with self.subTest(accion=accion):
                app = SimpleNamespace(
                    _abrir_cliente_notificacion=Mock(),
                    _abrir_producto_notificacion=Mock(),
                    _abrir_panel_ventas_notificacion=Mock(),
                    _abrir_venta_notificacion=Mock(),
                )
                aviso = {"cliente_id": 27, "nota_id": 71, "producto_id": 9}
                HiloramaDesktopApp._navegar_notificacion(app, aviso, accion)
                llamado = {
                    "cliente": app._abrir_cliente_notificacion,
                    "producto": app._abrir_producto_notificacion,
                    "panel": app._abrir_panel_ventas_notificacion,
                    "venta": app._abrir_venta_notificacion,
                }[destino]
                if destino == "producto":
                    llamado.assert_called_once_with(aviso)
                else:
                    llamado.assert_called_once_with(*argumentos, **kwargs)

    def test_preparar_mensaje_solo_abre_borrador(self):
        controller = SimpleNamespace(root=Mock())
        aviso = _aviso(12, "OPORTUNIDADES", "DORMIDA")
        with patch(
            "hilorama_desktop.ui.notificaciones_view.MessageDraftWindow",
        ) as borrador:
            NotificationBellController.handle_action(
                controller,
                aviso,
                "PREPARAR_MENSAJE",
            )
        borrador.assert_called_once_with(controller.root, aviso)


if __name__ == "__main__":
    unittest.main()
