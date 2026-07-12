"""Pruebas de seguridad del runner aislado FASE 9B.2, sin PostgreSQL."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hilorama_backend.scripts.probar_fase9b_base_aislada import (
    BASE_SCHEMA_SQL,
    BaseAisladaError,
    ConexionPrueba,
    TEST_DATABASE_URL_ENV,
    _probar_diagnostico,
    ejecutar_ensayo,
    obtener_url_base_prueba,
    validar_url_base_prueba,
)


ROOT = REPO_ROOT
APP_PATH = ROOT / "hilorama_backend" / "app.py"
CLIENT_PATH = ROOT / "hilorama_desktop" / "api_client" / "render_api_client.py"
RUNNER_PATH = ROOT / "hilorama_backend" / "scripts" / "probar_fase9b_base_aislada.py"


class _DetenerDespuesDeValidacion(RuntimeError):
    """Evita que la prueba llegue a crear esquema o migraciones."""


class BaseAisladaTests(unittest.TestCase):
    def _ejecutar_hasta_validacion_de_conexion(self, host: str):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "database": "hilorama_fase9b_test",
            "usuario": "hilorama_fase9b_tester",
            "host": host,
            "puerto": 5432,
        }
        conexion = MagicMock()
        conexion.cursor.return_value.__enter__.return_value = cursor
        psycopg2 = MagicMock()
        psycopg2.connect.return_value.__enter__.return_value = conexion
        info = ConexionPrueba(
            host="127.0.0.1",
            puerto=5432,
            database="hilorama_fase9b_test",
            usuario="hilorama_fase9b_tester",
        )

        with (
            patch(
                "hilorama_backend.scripts.probar_fase9b_base_aislada._validar_importaciones_backend"
            ),
            patch(
                "hilorama_backend.scripts.probar_fase9b_base_aislada._cargar_psycopg",
                return_value=(psycopg2, MagicMock(), MagicMock()),
            ),
            patch(
                "hilorama_backend.scripts.probar_fase9b_base_aislada._asegurar_base_vacia",
                side_effect=_DetenerDespuesDeValidacion,
            ),
        ):
            ejecutar_ensayo("postgresql://url-ficticia", info)

    def test_importaciones_backend_se_validan_antes_de_cargar_driver_o_conectar(self):
        with (
            patch(
                "hilorama_backend.scripts.probar_fase9b_base_aislada._validar_importaciones_backend",
                side_effect=BaseAisladaError("importacion de prueba bloqueada"),
            ),
            patch(
                "hilorama_backend.scripts.probar_fase9b_base_aislada._cargar_psycopg"
            ) as cargar_psycopg,
        ):
            with self.assertRaisesRegex(BaseAisladaError, "importacion de prueba bloqueada"):
                ejecutar_ensayo(
                    "postgresql://url-ficticia",
                    ConexionPrueba(
                        host="127.0.0.1",
                        puerto=5432,
                        database="hilorama_fase9b_test",
                        usuario="hilorama_fase9b_tester",
                    ),
                )
        cargar_psycopg.assert_not_called()

    def test_acepta_unicamente_postgres_local_con_sufijo_test(self):
        info = validar_url_base_prueba("postgresql://tester:dummy@localhost:5432/hilorama_fase9b_test")
        self.assertEqual(info.host, "localhost")
        self.assertEqual(info.database, "hilorama_fase9b_test")
        self.assertEqual(info.origen, TEST_DATABASE_URL_ENV)

    def test_esquema_aislado_de_pagos_conserva_fecha_legacy_con_default(self):
        inicio = BASE_SCHEMA_SQL.index("CREATE TABLE IF NOT EXISTS pagos")
        fin = BASE_SCHEMA_SQL.index(");", inicio) + 2
        contrato_pagos = BASE_SCHEMA_SQL[inicio:fin].upper()
        self.assertIn("NOTA_ID TEXT NOT NULL", contrato_pagos)
        self.assertIn("COMPROBANTE TEXT", contrato_pagos)
        self.assertIn("FECHA TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", contrato_pagos)

    def test_rechaza_base_sin_sufijo_test(self):
        with self.assertRaisesRegex(BaseAisladaError, "terminar en _test"):
            validar_url_base_prueba("postgresql://tester:dummy@localhost:5432/hilorama")

    def test_rechaza_host_render_o_remoto(self):
        with self.assertRaises(BaseAisladaError):
            validar_url_base_prueba("postgresql://tester:dummy@hilorama.onrender.com:5432/hilorama_fase9b_test")
        with self.assertRaises(BaseAisladaError):
            validar_url_base_prueba("postgresql://tester:dummy@10.0.0.8:5432/hilorama_fase9b_test")

    def test_no_hace_fallback_a_database_url(self):
        with self.assertRaisesRegex(BaseAisladaError, TEST_DATABASE_URL_ENV):
            obtener_url_base_prueba({"DATABASE_URL": "postgresql://real:secret@localhost:5432/hilorama_real"})

    def test_ejecucion_directa_check_config_no_falla_por_import_de_backend(self):
        entorno = dict(os.environ)
        entorno.pop(TEST_DATABASE_URL_ENV, None)
        entorno.pop("DATABASE_URL", None)
        resultado = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "--check-config"],
            cwd=str(ROOT),
            env=entorno,
            capture_output=True,
            text=True,
            check=False,
        )
        salida = f"{resultado.stdout}\n{resultado.stderr}"
        self.assertNotIn("No module named 'hilorama_backend'", salida)
        self.assertIn(f"BLOQUEADO: Falta {TEST_DATABASE_URL_ENV}", salida)
        self.assertEqual(resultado.returncode, 2)

    def test_acepta_direcciones_loopback_reportadas_por_postgresql(self):
        for host in ("127.0.0.1", "127.0.0.1/32", "::1", "::1/128"):
            with self.subTest(host=host):
                with self.assertRaises(_DetenerDespuesDeValidacion):
                    self._ejecutar_hasta_validacion_de_conexion(host)

    def test_rechaza_direcciones_no_loopback_reportadas_por_postgresql(self):
        for host in ("192.168.1.10", "10.0.0.5", "8.8.8.8", "example.com"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(BaseAisladaError, "conexion abierta"):
                    self._ejecutar_hasta_validacion_de_conexion(host)

    def test_contrato_legacy_y_general_de_auditoria(self):
        codigo = APP_PATH.read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        rutas = {}
        funciones = {}
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef):
                funciones[nodo.name] = ast.get_source_segment(codigo, nodo) or ""
                for decorador in nodo.decorator_list:
                    if isinstance(decorador, ast.Call) and decorador.args and isinstance(decorador.args[0], ast.Constant):
                        rutas[decorador.args[0].value] = nodo.name
        self.assertEqual(rutas["/api/admin/auditoria"], "api_admin_auditoria")
        self.assertEqual(rutas["/api/admin/auditoria-general"], "api_admin_auditoria_general")
        self.assertIn("licencias_eventos", funciones["api_admin_auditoria"])
        self.assertIn("pagination", funciones["api_admin_auditoria_general"])

    def test_desktop_consumira_auditoria_general_paginada(self):
        codigo = CLIENT_PATH.read_text(encoding="utf-8")
        self.assertIn('self.get("/api/admin/auditoria-general", params=params, token=token)', codigo)

    def test_diagnosticos_usan_url_test_validada_y_conservan_contrato(self):
        url_test = "postgresql://tester:clave-ficticia@localhost:5432/hilorama_fase9b_test"
        nota_historica = "F9B-PRUEBA-HISTORICA-DIAGNOSTICO"
        resultados = [
            subprocess.CompletedProcess([], 0, "Resultado: 0 hallazgo(s).", ""),
            subprocess.CompletedProcess([], 1, f"Notas pagadas sin movimiento VENTA\n{nota_historica}", ""),
        ]
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://produccion:secreto@render.example/hilorama",
                    TEST_DATABASE_URL_ENV: "postgresql://otra:clave@localhost:5432/otra_test",
                    "GITHUB_TOKEN": "token-que-no-debe-heredarse",
                },
                clear=False,
            ),
            patch(
                "hilorama_backend.scripts.probar_fase9b_base_aislada.subprocess.run",
                side_effect=resultados,
            ) as ejecutar,
        ):
            reporte = _probar_diagnostico(url_test, "2026-07-11", nota_historica)

        self.assertEqual(reporte["normal_strict"]["returncode"], 0)
        self.assertEqual(reporte["historico_strict"]["returncode"], 1)
        self.assertIn(nota_historica, reporte["historico_strict"]["stdout"])
        self.assertEqual(ejecutar.call_count, 2)
        for llamada in ejecutar.call_args_list:
            entorno = llamada.kwargs["env"]
            self.assertEqual(entorno["DATABASE_URL"], url_test)
            self.assertEqual(entorno[TEST_DATABASE_URL_ENV], url_test)
            self.assertNotIn("GITHUB_TOKEN", entorno)
            info = validar_url_base_prueba(entorno["DATABASE_URL"])
            self.assertTrue(info.database.endswith("_test"))
            self.assertIn(info.host, {"localhost", "127.0.0.1", "::1"})

    def test_error_del_subproceso_muestra_evidencia_saneada(self):
        url_test = "postgresql://tester:clave-ficticia@localhost:5432/hilorama_fase9b_test"
        nota_historica = "F9B-PRUEBA-HISTORICA-DIAGNOSTICO"
        resultados = [
            subprocess.CompletedProcess(
                [],
                2,
                "DATABASE_URL=postgresql://usuario:password-real@localhost:5432/hilorama_fase9b_test",
                "token=token-real",
            ),
            subprocess.CompletedProcess([], 1, nota_historica, ""),
        ]
        with patch(
            "hilorama_backend.scripts.probar_fase9b_base_aislada.subprocess.run",
            side_effect=resultados,
        ):
            with self.assertRaises(AssertionError) as contexto:
                _probar_diagnostico(url_test, "2026-07-11", nota_historica)

        mensaje = str(contexto.exception)
        self.assertIn("diagnostico normal", mensaje)
        self.assertIn('"returncode": 2', mensaje)
        self.assertIn('"stdout"', mensaje)
        self.assertIn('"stderr"', mensaje)
        self.assertNotIn("password-real", mensaje)
        self.assertNotIn("token-real", mensaje)


if __name__ == "__main__":
    unittest.main()
