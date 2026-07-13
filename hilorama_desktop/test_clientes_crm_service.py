"""Pruebas sin red para normalizacion y mensajes del CRM de clientas."""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.services import clientes_crm_service as crm


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


if __name__ == "__main__":
    unittest.main()
