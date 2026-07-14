"""Contrato API y regresiones del envio individual y por lote, sin base real."""

from contextlib import nullcontext
import inspect
import unittest
from unittest.mock import ANY, patch

import hilorama_backend.app as backend


class _Resultado:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _ConexionEnvio:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT * FROM notas" in sql:
            return _Resultado({
                "id": "N-LOCAL",
                "estado": "ENVIADO",
                "guia": None,
                "fecha_envio": "2026-07-14T03:00:00+00:00",
            })
        return _Resultado()


class EnviosApiTests(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True)
        self.client = backend.app.test_client()

    def test_ruta_lote_requiere_sesion(self):
        respuesta = self.client.post(
            "/api/envios/notas/marcar-enviadas",
            json={"nota_ids": ["N-1"]},
        )
        self.assertIn(respuesta.status_code, {401, 403})

    def test_payload_invalido_no_abre_base(self):
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "get_conn") as get_conn,
        ):
            respuesta = self.client.post(
                "/api/envios/notas/marcar-enviadas",
                json={"nota_ids": []},
            )
        self.assertEqual(respuesta.status_code, 400)
        get_conn.assert_not_called()

    def test_endpoint_lote_devuelve_resultados_individuales(self):
        resultado = {
            "ok": True,
            "procesados": 1,
            "omitidos": 1,
            "resultados": [
                {"nota_id": "N-1", "ok": True, "estado": "ENVIADO"},
                {"nota_id": "N-2", "ok": False, "error": "La nota no tiene guía."},
            ],
        }
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "get_conn", return_value=nullcontext(object())),
            patch.object(backend, "_procesar_envios_lote_api_conn", return_value=resultado) as procesar,
        ):
            respuesta = self.client.post(
                "/api/envios/notas/marcar-enviadas",
                json={"nota_ids": ["N-1", "N-2", "N-1"]},
            )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json(), resultado)
        procesar.assert_called_once_with(
            ANY,
            ["N-1", "N-2"],
            {"usuario_id": 1},
        )

    def test_lote_parcial_usa_savepoint_y_audita_solo_exitos(self):
        conn = _ConexionEnvio()

        def marcar(_conn, nota_id):
            if nota_id == "N-OK":
                return (
                    nota_id,
                    {
                        "id": nota_id,
                        "estado": "ENVIADO",
                        "guia": "GUIA-1",
                        "paqueteria": "Estafeta",
                        "fecha_envio": "2026-07-14T03:00:00+00:00",
                    },
                    False,
                    True,
                )
            if nota_id == "N-YA":
                return nota_id, {"estado": "ENVIADO"}, True, True
            raise backend.NotaPagoNoPermitido("Guarda la guia antes de marcar el envio.", 409)

        with (
            patch.object(backend, "_marcar_nota_enviada_api_conn", side_effect=marcar),
            patch.object(backend, "_registrar_auditoria_general_api") as auditoria,
        ):
            resultado = backend._procesar_envios_lote_api_conn(
                conn,
                ["N-OK", "N-YA", "N-SIN"],
                {"usuario_id": 1},
            )

        self.assertEqual(resultado["procesados"], 1)
        self.assertEqual(resultado["omitidos"], 2)
        self.assertEqual([item["ok"] for item in resultado["resultados"]], [True, False, False])
        auditoria.assert_called_once()
        sql = "\n".join(call[0] for call in conn.calls)
        self.assertEqual(
            sum(call[0].startswith("SAVEPOINT ") for call in conn.calls),
            3,
        )
        self.assertIn("ROLLBACK TO SAVEPOINT envio_lote_2", sql)

    def test_lote_con_error_completo_no_audita_ni_reporta_exitos(self):
        conn = _ConexionEnvio()
        with (
            patch.object(
                backend,
                "_marcar_nota_enviada_api_conn",
                side_effect=backend.NotaPagoNoPermitido("Estado no permitido.", 409),
            ),
            patch.object(backend, "_registrar_auditoria_general_api") as auditoria,
        ):
            resultado = backend._procesar_envios_lote_api_conn(
                conn,
                ["N-INVALIDA-1", "N-INVALIDA-2"],
                {"usuario_id": 1},
            )

        self.assertEqual(resultado["procesados"], 0)
        self.assertEqual(resultado["omitidos"], 2)
        self.assertTrue(all(not item["ok"] for item in resultado["resultados"]))
        auditoria.assert_not_called()
        sql = "\n".join(call[0] for call in conn.calls)
        self.assertIn("ROLLBACK TO SAVEPOINT envio_lote_0", sql)
        self.assertIn("ROLLBACK TO SAVEPOINT envio_lote_1", sql)

    def test_entrega_personal_no_exige_guia(self):
        conn = _ConexionEnvio()
        nota = {
            "id": "N-LOCAL",
            "estado": "COMPLETA",
            "guia": None,
            "envio": {"tipo": "RECOLECCION LOCAL"},
        }
        with (
            patch.object(backend, "_resolver_nota_api", return_value=("N-LOCAL", nota)),
            patch.object(
                backend,
                "_columnas_tabla_api",
                return_value={"id", "estado", "guia", "fecha_envio"},
            ),
        ):
            resultado = backend._marcar_nota_enviada_api_conn(conn, "N-LOCAL")
        self.assertFalse(resultado[2])
        sql = "\n".join(call[0] for call in conn.calls)
        self.assertIn("estado='ENVIADO'", sql)
        self.assertIn("fecha_envio=COALESCE(fecha_envio, NOW())", sql)

    def test_paqueteria_sin_guia_sigue_rechazada(self):
        nota = {
            "id": "N-SIN",
            "estado": "COMPLETA",
            "guia": None,
            "envio": {"tipo": "PAQUETERIA"},
        }
        with patch.object(backend, "_resolver_nota_api", return_value=("N-SIN", nota)):
            with self.assertRaises(backend.NotaPagoNoPermitido):
                backend._marcar_nota_enviada_api_conn(_ConexionEnvio(), "N-SIN")

    def test_filtros_backend_respetan_entrega_local(self):
        pendiente = {"estado": "COMPLETA", "guia": "", "requiere_guia": True}
        local = {"estado": "COMPLETA", "guia": "", "requiere_guia": False}
        enviada = {"estado": "ENVIADO", "guia": "G", "requiere_guia": True}
        self.assertTrue(backend._envio_coincide_filtro_api(pendiente, "PENDIENTES_GUIA"))
        self.assertFalse(backend._envio_coincide_filtro_api(local, "PENDIENTES_GUIA"))
        self.assertTrue(backend._envio_coincide_filtro_api(local, "LISTAS_ENVIAR"))
        self.assertTrue(backend._envio_coincide_filtro_api(enviada, "ENVIADAS"))
        self.assertTrue(backend._envio_coincide_filtro_api(enviada, "TODAS"))

    def test_no_hay_rutas_lote_duplicadas(self):
        reglas = [
            regla
            for regla in backend.app.url_map.iter_rules()
            if regla.rule == "/api/envios/notas/marcar-enviadas" and "POST" in regla.methods
        ]
        self.assertEqual(len(reglas), 1)
        self.assertEqual(reglas[0].endpoint, "api_envios_notas_marcar_enviadas")

    def test_envio_no_toca_stock_pagos_o_movimientos(self):
        source = "\n".join((
            inspect.getsource(backend._marcar_nota_enviada_api_conn),
            inspect.getsource(backend._procesar_envios_lote_api_conn),
            inspect.getsource(backend.api_envios_notas_marcar_enviadas),
        )).lower()
        for prohibido in (
            "update productos",
            "insert into pagos",
            "insert into movimientos_almacen",
            "descontar_stock",
        ):
            self.assertNotIn(prohibido, source)

    def test_guia_y_paqueteria_se_conservan_en_resultado(self):
        conn = _ConexionEnvio()
        with (
            patch.object(
                backend,
                "_marcar_nota_enviada_api_conn",
                return_value=(
                    "N-1",
                    {
                        "estado": "ENVIADO",
                        "guia": "GUIA-CONSERVADA",
                        "paqueteria": "DHL",
                        "fecha_envio": "2026-07-14T03:00:00+00:00",
                    },
                    False,
                    True,
                ),
            ),
            patch.object(backend, "_registrar_auditoria_general_api"),
        ):
            resultado = backend._procesar_envios_lote_api_conn(
                conn,
                ["N-1"],
                {"usuario_id": 1},
            )
        item = resultado["resultados"][0]
        self.assertEqual(item["guia"], "GUIA-CONSERVADA")
        self.assertEqual(item["paqueteria"], "DHL")
        self.assertIsNotNone(item["fecha_envio"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
