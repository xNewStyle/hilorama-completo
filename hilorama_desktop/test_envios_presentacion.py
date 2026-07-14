"""Pruebas puras del panel de Gestion de Envios."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from hilorama_desktop.api_client.render_api_client import RenderApiClient
from hilorama_desktop.services import envios_api_service
from hilorama_desktop.services.envios_presentacion import (
    buscar_envios,
    clasificar_seleccion_envios,
    filtrar_envios,
    formatear_fecha_envio,
    resumir_seleccion_envios,
)


ROOT = Path(__file__).resolve().parents[1]
MAIN_VENTAS = ROOT / "main_ventas.py"


def _function_source(nombre):
    source = MAIN_VENTAS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nombre:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"No se encontro {nombre}.")


class EnviosPresentacionTests(unittest.TestCase):
    def setUp(self):
        self.pendiente = {
            "id": "N-PENDIENTE",
            "estado": "COMPLETA",
            "guia": "",
            "requiere_guia": True,
            "cliente_nombre": "Ana",
        }
        self.lista = {
            "id": "N-LISTA",
            "estado": "COMPLETA",
            "guia": "GUIA-1",
            "requiere_guia": True,
            "cliente_nombre": "Beatriz",
        }
        self.local = {
            "id": "N-LOCAL",
            "estado": "COMPLETA",
            "guia": "",
            "requiere_guia": False,
            "tipo_entrega": "RECOLECCION LOCAL",
            "cliente_nombre": "Carla",
        }
        self.enviada = {
            "id": "N-ENVIADA",
            "estado": "ENVIADO",
            "guia": "GUIA-2",
            "requiere_guia": True,
            "fecha_envio": "2026-07-14T02:35:00+00:00",
        }
        self.anulada = {"id": "N-ANULADA", "estado": "ANULADA", "guia": "GUIA-X"}
        self.notas = [self.pendiente, self.lista, self.local, self.enviada, self.anulada]

    def test_filtros_operativos(self):
        self.assertEqual(
            [nota["id"] for nota in filtrar_envios(self.notas, "PENDIENTES DE GUÍA")],
            ["N-PENDIENTE"],
        )
        self.assertEqual(
            [nota["id"] for nota in filtrar_envios(self.notas, "LISTAS PARA ENVIAR")],
            ["N-LISTA", "N-LOCAL"],
        )
        self.assertEqual(
            [nota["id"] for nota in filtrar_envios(self.notas, "ENVIADAS")],
            ["N-ENVIADA"],
        )
        self.assertEqual(
            [nota["id"] for nota in filtrar_envios(self.notas, "TODAS")],
            ["N-PENDIENTE", "N-LISTA", "N-LOCAL", "N-ENVIADA"],
        )

    def test_una_y_varias_selecciones(self):
        una = clasificar_seleccion_envios([self.lista])
        self.assertEqual([nota["id"] for nota in una["validos"]], ["N-LISTA"])
        varias = clasificar_seleccion_envios(
            [self.lista, self.pendiente, self.enviada, self.anulada, self.local]
        )
        self.assertEqual(
            [nota["id"] for nota in varias["validos"]],
            ["N-LISTA", "N-LOCAL"],
        )
        self.assertEqual(varias["motivos"]["SIN_GUIA"], 1)
        self.assertEqual(varias["motivos"]["YA_ENVIADO"], 1)
        self.assertEqual(varias["motivos"]["TERMINAL"], 1)

    def test_resumen_multiple_conserva_guia_y_estado(self):
        resumen = resumir_seleccion_envios([self.lista, self.local, self.enviada])
        self.assertEqual(
            resumen,
            {
                "seleccionados": 3,
                "con_guia": 2,
                "sin_guia": 1,
                "ya_enviados": 1,
                "listos": 2,
            },
        )

    def test_busqueda_no_modifica_datos(self):
        original = [dict(nota) for nota in self.notas]
        self.assertEqual(
            [nota["id"] for nota in buscar_envios(self.notas, "beat", "cliente")],
            ["N-LISTA"],
        )
        self.assertEqual(self.notas, original)

    def test_fecha_local_es_compacta_y_nulos_no_se_muestran(self):
        self.assertEqual(formatear_fecha_envio(None), "—")
        fecha = formatear_fecha_envio(self.enviada["fecha_envio"])
        self.assertRegex(fecha, r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$")
        self.assertNotIn("None", fecha)

    def test_treeview_usa_seleccion_extendida_real(self):
        source = _function_source("_abrir_panel_envios_api")
        self.assertIn('selectmode="extended"', source)
        self.assertIn("for iid in tabla.selection()", source)
        self.assertIn("Ctrl o Shift", source)

    def test_solicitud_lenta_no_bloquea_tk(self):
        source = _function_source("_abrir_panel_envios_api")
        self.assertIn("threading.Thread", source)
        self.assertIn("win.after(80, esperar_lote)", source)
        self.assertNotIn(".join()", source)

    def test_refresca_tabla_y_muestra_omisiones_despues_del_lote(self):
        source = _function_source("_abrir_panel_envios_api")
        self.assertIn('trabajo["envios"] = cargar_datos(filtro_capturado)', source)
        self.assertIn('datos_cargados.extend(trabajo.get("envios") or [])', source)
        self.assertIn("pedidos fueron omitidos", source)

    def test_panel_muestra_estado_fecha_y_detalle(self):
        source = _function_source("_abrir_panel_envios_api")
        for texto in (
            '"Estado": "Estado"',
            '"FechaEnvio": "Fecha de envío"',
            "Fecha de guía:",
            "Tipo de entrega:",
            "Empacador:",
            "Artículos:",
            "Observaciones:",
        ):
            self.assertIn(texto, source)

    def test_asignar_guia_rechaza_seleccion_multiple(self):
        source = _function_source("_abrir_panel_envios_api")
        self.assertIn("Selecciona una sola nota para asignar la guía.", source)

    def test_panel_no_contiene_escrituras_de_stock_o_pagos(self):
        source = _function_source("_abrir_panel_envios_api").lower()
        for prohibido in ("descontar_stock", "update productos", "insert into pagos"):
            self.assertNotIn(prohibido, source)

    def test_cliente_y_servicio_usan_endpoint_lote(self):
        api = RenderApiClient(base_url="http://127.0.0.1:1")
        with patch.object(api, "post", return_value={"ok": True}) as post:
            api.marcar_envios_notas(["N-1", "N-2"], token="token-ficticio")
        post.assert_called_once_with(
            "/api/envios/notas/marcar-enviadas",
            {"nota_ids": ["N-1", "N-2"]},
            token="token-ficticio",
        )

        respuesta = {"ok": True, "procesados": 2, "omitidos": 0, "resultados": []}
        with (
            patch.object(envios_api_service, "_call_api", return_value=respuesta) as call_api,
            patch.object(envios_api_service, "_emitir_cambio_notificaciones") as emitir,
        ):
            self.assertEqual(envios_api_service.marcar_envios_lote(["N-1", "N-2"]), respuesta)
        self.assertEqual(call_api.call_args.args[:2], (
            "marcar envios por lote",
            "/api/envios/notas/marcar-enviadas",
        ))
        emitir.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
