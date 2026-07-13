"""Pruebas sin red ni ventana visible para Movimientos de almacen."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.api_client.render_api_client import RenderApiError
from hilorama_desktop.services.movimientos_api_service import MovimientosApiService
from hilorama_desktop.services.read_api_support import ApiReadError, PermissionDeniedError, SessionExpiredError
from hilorama_desktop.ui.movimientos_almacen_dialog import build_movimientos_filters, handle_session_expired, safe_after


def _session():
    return {"token": "token-de-prueba", "usuario": {"rol": "almacen"}}


class FakeMovimientosApi:
    def __init__(self):
        self.calls = []
        self.response = {
            "ok": True,
            "items": [{"id": 7, "cantidad": -2, "codigo": "ABC"}],
            "pagination": {"page": 1, "per_page": 50, "total": 1, "pages": 1},
        }
        self.error = None

    def listar_movimientos_almacen(self, params=None, token=None):
        self.calls.append(("GET movimientos", params, token))
        if self.error:
            raise self.error
        return self.response

    def listar_movimientos_producto_almacen(self, producto_id, params=None, token=None):
        self.calls.append(("GET movimientos producto", producto_id, params, token))
        if self.error:
            raise self.error
        return self.response

    def obtener_movimiento_almacen(self, movimiento_id, token=None):
        self.calls.append(("GET detalle movimiento", movimiento_id, token))
        if self.error:
            raise self.error
        return {"ok": True, "movimiento": {"id": movimiento_id, "metadata_json": {"token": "oculto"}}}


class DestroyedWidget:
    def winfo_exists(self):
        return False

    def after(self, *_args):
        raise AssertionError("No debe programarse una ventana destruida")


class SessionOwner:
    def __init__(self):
        self.master = None
        self.message = None

    def manejar_sesion_expirada(self, message):
        self.message = message


class MovimientosAlmacenTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeMovimientosApi()
        self.service = MovimientosApiService(api_client=self.api, session_provider=_session)

    def test_listado_normaliza_items_y_no_envia_cliente_manual(self):
        result = self.service.listar_movimientos({"q": "rojo", "page": 2, "per_page": 50, "cliente_sistema_id": 99})
        self.assertEqual(result["movimientos"][0]["id"], 7)
        name, params, token = self.api.calls[0]
        self.assertEqual(name, "GET movimientos")
        self.assertEqual(params["q"], "rojo")
        self.assertEqual(params["page"], 2)
        self.assertNotIn("cliente_sistema_id", params)
        self.assertEqual(token, "token-de-prueba")

    def test_all_relevant_filters_are_preserved(self):
        params = build_movimientos_filters(
            {key: key for key in ("q", "producto", "codigo", "marca", "hilo", "color", "tipo", "usuario", "referencia", "desde", "hasta")},
            page=3,
            per_page=50,
        )
        self.assertEqual(params["page"], 3)
        self.assertEqual(params["per_page"], 50)
        self.assertEqual(set(params) - {"page", "per_page"}, {"q", "producto", "codigo", "marca", "hilo", "color", "tipo", "usuario", "referencia", "desde", "hasta"})

    def test_empty_response_and_detail_are_supported(self):
        self.api.response = {"ok": True, "movimientos": [], "pagination": {"page": 1, "per_page": 50, "total": 0, "pages": 0}}
        self.assertEqual(self.service.listar_movimientos()["items"], [])
        detail = self.service.obtener_movimiento(7)
        self.assertEqual(detail["id"], 7)

    def test_product_history_uses_get_only(self):
        self.service.listar_movimientos_producto(9, {"codigo": "A"})
        self.assertEqual(self.api.calls[0][0], "GET movimientos producto")
        self.assertEqual(self.api.calls[0][1], 9)

    def test_401_403_500_and_network_are_controlled(self):
        self.api.error = RenderApiError("rechazado", status=401)
        with self.assertRaises(SessionExpiredError):
            self.service.listar_movimientos()
        self.api.error = RenderApiError("Permiso denegado", status=403)
        with self.assertRaises(PermissionDeniedError):
            self.service.listar_movimientos()
        self.api.error = RenderApiError("fallo interno", status=500)
        with self.assertRaises(ApiReadError) as server_error:
            self.service.listar_movimientos()
        self.assertNotIn("fallo interno", str(server_error.exception))
        self.api.error = RenderApiError("sin red", status=None)
        with self.assertRaises(ApiReadError) as network_error:
            self.service.listar_movimientos()
        self.assertIn("Backend no disponible", str(network_error.exception))

    def test_404_is_controlled(self):
        self.api.error = RenderApiError("no encontrado", status=404)
        with self.assertRaises(ApiReadError) as error:
            self.service.obtener_movimiento(7)
        self.assertIn("no fue encontrado", str(error.exception))

    def test_invalid_pagination_is_rejected_before_http(self):
        with self.assertRaises(ValueError):
            self.service.listar_movimientos({"per_page": 101})
        self.assertEqual(self.api.calls, [])

    def test_destroyed_window_does_not_schedule_callback(self):
        self.assertIsNone(safe_after(DestroyedWidget(), 0, lambda: self.fail("No debe ejecutarse")))

    def test_session_expiration_reaches_central_owner(self):
        owner = SessionOwner()
        self.assertTrue(handle_session_expired(owner, "Sesion expirada"))
        self.assertEqual(owner.message, "Sesion expirada")

    def test_logs_do_not_include_token_when_backend_rejects(self):
        self.api.error = RenderApiError("Bearer token-secreto-de-prueba", status=500)
        with patch("hilorama_desktop.services.read_api_support.log_error") as logger:
            with self.assertRaises(ApiReadError):
                self.service.listar_movimientos()
        rendered = " ".join(str(call.args) for call in logger.call_args_list)
        self.assertNotIn("token-secreto-de-prueba", rendered)


if __name__ == "__main__":
    unittest.main()
