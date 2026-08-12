"""Pruebas del contrato HTTP real de la campana, sin abrir base de datos."""

from contextlib import nullcontext
import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

import hilorama_backend.app as backend


RESPUESTA = {
    "ok": True,
    "total": 1,
    "urgentes": 0,
    "atencion": 1,
    "normales": 0,
    "operacion": {
        "total": 1,
        "categorias": {"PAGADA_SIN_EMPAQUETAR": 1},
        "notificaciones": [{"key": "pagada_sin_empaquetar:N-1"}],
    },
    "oportunidades": {"total": 0, "categorias": {}, "notificaciones": []},
    "oportunidades_actualizadas": True,
    "generado_en": "2026-07-13T12:00:00",
}


class NotificacionesApiTests(unittest.TestCase):
    def setUp(self):
        backend.app.config.update(TESTING=True)
        self.client = backend.app.test_client()

    def test_endpoint_requiere_sesion_real(self):
        respuesta = self.client.get("/api/notificaciones/resumen")
        self.assertEqual(respuesta.status_code, 401)
        self.assertFalse(respuesta.get_json()["ok"])

    def test_endpoint_devuelve_un_solo_resumen_estable(self):
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "_construir_resumen_notificaciones_api", return_value=RESPUESTA) as construir,
        ):
            respuesta = self.client.get("/api/notificaciones/resumen?incluir_oportunidades=false")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.get_json(), RESPUESTA)
        construir.assert_called_once_with(False)

    def test_error_interno_no_expone_sql(self):
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "_construir_resumen_notificaciones_api", side_effect=RuntimeError("SELECT secreto")),
            patch.object(backend.app.logger, "exception"),
        ):
            respuesta = self.client.get("/api/notificaciones/resumen")
        self.assertEqual(respuesta.status_code, 500)
        cuerpo = respuesta.get_json()
        self.assertEqual(cuerpo["error"], "No se pudieron actualizar las notificaciones.")
        self.assertNotIn("SELECT", str(cuerpo))

    def test_control_rechaza_accion_invalida_antes_de_abrir_base(self):
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "get_conn") as get_conn,
        ):
            respuesta = self.client.post(
                "/api/notificaciones/oportunidades/10/control",
                json={"categoria": "DORMIDA", "accion": "BORRAR"},
            )
        self.assertEqual(respuesta.status_code, 400)
        get_conn.assert_not_called()

    def test_control_sin_migracion_responde_409_sin_crear_tabla(self):
        with (
            patch.object(backend, "_require_license_api", return_value=({"usuario_id": 1}, None)),
            patch.object(backend, "get_conn", return_value=nullcontext(object())),
            patch.object(backend, "_tabla_existe_api", return_value=False),
        ):
            respuesta = self.client.post(
                "/api/notificaciones/oportunidades/10/control",
                json={"categoria": "DORMIDA", "accion": "RECORDAR_3"},
            )
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn("migración", respuesta.get_json()["error"])

    def test_no_hay_ruta_posterior_que_sobrescriba_el_resumen(self):
        reglas = [
            regla
            for regla in backend.app.url_map.iter_rules()
            if regla.rule == "/api/notificaciones/resumen" and "GET" in regla.methods
        ]
        self.assertEqual(len(reglas), 1)
        self.assertEqual(reglas[0].endpoint, "api_notificaciones_resumen")

    def test_cotizacion_y_venta_pendiente_excluyen_oportunidades(self):
        ids = backend._cliente_ids_con_pendiente_notificaciones([
            {"cliente_id": 10, "estado": "COTIZACION"},
            {"cliente_id": 11, "estado": "VENTA_PENDIENTE"},
            {"cliente_id": 12, "estado": "PAGADA"},
            {"cliente_id": 13, "estado": "COTIZACION_PENDIENTE"},
            {"cliente_id": 14, "estado": "VENTA"},
        ])
        self.assertEqual(ids, {10, 11})

    def test_consulta_de_notas_usa_solo_estados_actuales(self):
        self.assertEqual(
            backend.ESTADOS_NOTIFICACIONES_NOTAS,
            (
                "COTIZACION",
                "VENTA_PENDIENTE",
                "PAGADA",
                "EN_PROCESO",
                "INCOMPLETA",
                "COMPLETA",
                "ENVIADO",
            ),
        )

    def test_consulta_de_resumen_no_contiene_escrituras_ni_ddl(self):
        funciones = (
            backend._consultar_notas_notificaciones_api,
            backend._consultar_impresiones_notificaciones_api,
            backend._consultar_errores_scan_notificaciones_api,
            backend._consultar_productos_notificaciones_api,
            backend._consultar_controles_notificaciones_api,
            backend._construir_resumen_notificaciones_api,
        )
        source = "\n".join(inspect.getsource(funcion).upper() for funcion in funciones)
        for sentencia in ("INSERT INTO ", "UPDATE ", "DELETE FROM ", "CREATE TABLE ", "ALTER TABLE "):
            self.assertNotIn(sentencia, source)

    def test_refresco_operativo_no_recalcula_analitica_comercial(self):
        conn = object()
        with (
            patch.object(backend, "get_conn", return_value=nullcontext(conn)),
            patch.object(backend, "_consultar_notas_notificaciones_api", return_value=[]),
            patch.object(backend, "_consultar_impresiones_notificaciones_api", return_value=[]),
            patch.object(backend, "_consultar_errores_scan_notificaciones_api", return_value=[]),
            patch.object(backend, "_consultar_productos_notificaciones_api", return_value=[]),
            patch.object(backend, "_analitica_clientas_conn_api") as analitica,
        ):
            resumen = backend._construir_resumen_notificaciones_api(False)

        analitica.assert_not_called()
        self.assertFalse(resumen["oportunidades_actualizadas"])
        self.assertEqual(resumen["oportunidades"]["total"], 0)

    def test_consulta_crm_incorpora_evidencia_de_tabla_pagos(self):
        class Conn:
            def __init__(self):
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append(query)
                return self

            def fetchall(self):
                return []

        conn = Conn()
        with (
            patch.object(backend, "_tabla_existe_api", return_value=True),
            patch.object(
                backend,
                "_columnas_tabla_api",
                side_effect=lambda _conn, tabla: {
                    "notas": {"id", "cliente_id", "estado", "fecha"},
                    "pagos": {"id", "nota_id", "fecha"},
                }.get(tabla, set()),
            ),
        ):
            backend._consultar_ventas_crm_api(conn)

        consulta = conn.queries[-1]
        self.assertIn("EXISTS (SELECT 1 FROM pagos pg WHERE pg.nota_id = n.id)", consulta)
        self.assertIn("AS pagado", consulta)

    def test_migracion_control_es_separada_e_idempotente(self):
        ruta = Path(__file__).resolve().parent / "migrations" / "004_notificaciones_oportunidades.sql"
        sql = ruta.read_text(encoding="utf-8").upper()
        self.assertIn("BEGIN;", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS NOTIFICACIONES_OPORTUNIDADES_CONTROL", sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS", sql)
        self.assertIn("COMMIT;", sql)
        self.assertNotIn("ALTER TABLE NOTAS", sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("TRUNCATE", sql)


if __name__ == "__main__":
    unittest.main()
