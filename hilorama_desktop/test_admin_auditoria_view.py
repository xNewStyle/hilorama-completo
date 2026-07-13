"""Pruebas simuladas para Auditoria dentro de Administracion."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.api_client.render_api_client import RenderApiError
from hilorama_desktop.services.auditoria_api_service import AuditoriaApiService
from hilorama_desktop.services.read_api_support import ApiReadError, PermissionDeniedError, SessionExpiredError
from hilorama_desktop.ui.admin_view import _es_super_admin
from hilorama_desktop.utils.presentation import safe_pretty_json
from hilorama_desktop.build_client_package import EXCLUDED_RELATIVE


def _session(role="super_admin"):
    return {"token": "token-de-prueba", "usuario": {"rol": role}}


class FakeAuditoriaApi:
    def __init__(self):
        self.calls = []
        self.error = None
        self.response = {
            "ok": True,
            "auditoria": [{"id": 4, "accion": "PRODUCTO_EDITADO", "datos_nuevos_json": {"color": "rojo"}}],
            "pagination": {"page": 1, "per_page": 50, "total": 1, "pages": 1},
        }

    def listar_auditoria_general(self, params=None, token=None):
        self.calls.append(("GET auditoria", params, token))
        if self.error:
            raise self.error
        return self.response

    def obtener_auditoria_general(self, auditoria_id, token=None):
        self.calls.append(("GET detalle auditoria", auditoria_id, token))
        if self.error:
            raise self.error
        return {"ok": True, "auditoria": {"id": auditoria_id, "datos_anteriores_json": "json roto", "datos_nuevos_json": None}}


class AuditoriaAdminTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAuditoriaApi()
        self.service = AuditoriaApiService(api_client=self.api, session_provider=lambda: _session())

    def test_only_super_admin_is_authorized_for_view(self):
        self.assertTrue(_es_super_admin(_session("super_admin")))
        self.assertFalse(_es_super_admin(_session("almacen")))

    def test_list_filters_pagination_and_detail_use_get_methods(self):
        result = self.service.listar_auditoria({"modulo": "almacen", "usuario": "ana", "page": 2, "per_page": 50})
        self.assertEqual(result["items"][0]["id"], 4)
        name, params, token = self.api.calls[0]
        self.assertEqual(name, "GET auditoria")
        self.assertEqual(params["modulo"], "almacen")
        self.assertEqual(params["page"], 2)
        self.assertNotIn("cliente_sistema_id", params)
        self.assertEqual(token, "token-de-prueba")
        detail = self.service.obtener_auditoria(4)
        self.assertEqual(detail["id"], 4)
        self.assertEqual(self.api.calls[1][0], "GET detalle auditoria")

    def test_401_403_500_are_controlled_without_body_leak(self):
        self.api.error = RenderApiError("rechazado", status=401)
        with self.assertRaises(SessionExpiredError):
            self.service.listar_auditoria()
        self.api.error = RenderApiError("Permiso denegado", status=403)
        with self.assertRaises(PermissionDeniedError):
            self.service.listar_auditoria()
        self.api.error = RenderApiError("Bearer token-secreto-de-prueba", status=500)
        with patch("hilorama_desktop.services.read_api_support.log_error") as logger:
            with self.assertRaises(ApiReadError) as error:
                self.service.listar_auditoria()
        self.assertNotIn("token-secreto-de-prueba", str(error.exception))
        self.assertNotIn("token-secreto-de-prueba", " ".join(str(call.args) for call in logger.call_args_list))

    def test_404_is_controlled(self):
        self.api.error = RenderApiError("no encontrado", status=404)
        with self.assertRaises(ApiReadError) as error:
            self.service.obtener_auditoria(4)
        self.assertIn("no fue encontrado", str(error.exception))

    def test_json_invalid_null_and_optional_fields_are_safe(self):
        detail = self.service.obtener_auditoria(4)
        self.assertIn("texto", safe_pretty_json(detail.get("datos_anteriores_json")))
        self.assertEqual(safe_pretty_json(detail.get("datos_nuevos_json")), "—")

    def test_new_phase_tests_are_excluded_from_client_package(self):
        excluded = {str(path).replace("\\", "/") for path in EXCLUDED_RELATIVE}
        self.assertIn("hilorama_desktop/test_admin_auditoria_view.py", excluded)
        self.assertIn("hilorama_desktop/test_movimientos_almacen_view.py", excluded)


if __name__ == "__main__":
    unittest.main()
