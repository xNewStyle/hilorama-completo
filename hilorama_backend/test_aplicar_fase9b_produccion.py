"""Pruebas sin PostgreSQL del aplicador protegido de FASE 9B producción."""

from __future__ import annotations

import contextlib
import io
import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hilorama_backend.scripts import aplicar_fase9b_produccion as aplicador


URL_PRODUCCION = "postgresql://operador:clave-ficticia@hilorama-db.example:5432/hilorama"


class _CursorFalso:
    def __init__(self, *, falla_sql=None):
        self.falla_sql = falla_sql
        self.calls = []
        self.cerrado = False
        self._row = {"adquirido": True}

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql == self.falla_sql:
            raise RuntimeError("fallo simulado de migracion")
        if "pg_try_advisory_lock" in sql:
            self._row = {"adquirido": True}
        return self

    def fetchone(self):
        return self._row

    def close(self):
        self.cerrado = True


class _ConexionFalsa:
    def __init__(self, cursor):
        self.cursor_falso = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_falso

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class AplicarFase9BProduccionTests(unittest.TestCase):
    def setUp(self):
        self.info = aplicador.validar_url_produccion(URL_PRODUCCION)

    def test_rechaza_url_ausente_e_ignora_ambientes_legacy(self):
        with self.assertRaisesRegex(aplicador.ProduccionFase9BError, aplicador.PROD_DATABASE_URL_ENV):
            aplicador.obtener_url_produccion({})
        with self.assertRaisesRegex(aplicador.ProduccionFase9BError, aplicador.PROD_DATABASE_URL_ENV):
            aplicador.obtener_url_produccion(
                {
                    "DATABASE_URL": "postgresql://real:secreto@host/hilorama",
                    "HILORAMA_FASE9B_TEST_DATABASE_URL": "postgresql://test:secreto@localhost/prueba_test",
                }
            )

    def test_rechaza_hosts_loopback(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(aplicador.ProduccionFase9BError, "loopback"):
                    aplicador.validar_url_produccion(f"postgresql://u:p@{host}:5432/hilorama")

    def test_rechaza_bases_test(self):
        for database in ("hilorama_test", "hilorama_fase9b_test"):
            with self.subTest(database=database):
                with self.assertRaisesRegex(aplicador.ProduccionFase9BError, "prueba"):
                    aplicador.validar_url_produccion(
                        f"postgresql://u:p@hilorama-db.example:5432/{database}"
                    )

    def test_reporte_oculta_password_y_texto_sensible(self):
        reporte = self.info.reporte_seguro()
        self.assertEqual(reporte["password"], "[oculta]")
        self.assertNotIn("clave-ficticia", str(reporte))
        saneado = aplicador._sanitizar_texto(
            "DATABASE_URL=postgresql://u:clave-real@host/base token=secreto-real"
        )
        self.assertNotIn("clave-real", saneado)
        self.assertNotIn("secreto-real", saneado)

    def test_check_config_no_carga_driver_ni_conecta(self):
        salida = io.StringIO()
        with (
            patch.object(aplicador, "_cargar_psycopg") as cargar_psycopg,
            contextlib.redirect_stdout(salida),
        ):
            resultado = aplicador.main(["--check-config"], {aplicador.PROD_DATABASE_URL_ENV: URL_PRODUCCION})
        self.assertEqual(resultado, 0)
        cargar_psycopg.assert_not_called()
        self.assertNotIn("clave-ficticia", salida.getvalue())

    def test_preflight_es_solo_lectura_por_contrato(self):
        codigo = inspect.getsource(aplicador.recolectar_preflight).upper()
        self.assertNotIn("INSERT ", codigo)
        self.assertNotIn("UPDATE ", codigo)
        self.assertNotIn("DELETE ", codigo)
        self.assertNotIn("DROP ", codigo)
        preflight = inspect.getsource(aplicador.ejecutar_preflight)
        self.assertIn("readonly=True", preflight)
        self.assertIn("autocommit=True", preflight)

    def test_apply_exige_confirmaciones(self):
        with self.assertRaisesRegex(aplicador.ProduccionFase9BError, "confirm-production"):
            aplicador._confirmaciones_apply_validas(None, True)
        with self.assertRaisesRegex(aplicador.ProduccionFase9BError, "backup-confirmed"):
            aplicador._confirmaciones_apply_validas(aplicador.PRODUCTION_RESOURCE_CONFIRMATION, False)
        aplicador._confirmaciones_apply_validas(aplicador.PRODUCTION_RESOURCE_CONFIRMATION, True)

    def test_apply_standalone_exige_preflight_misma_ejecucion(self):
        parser = aplicador._construir_parser()
        args = parser.parse_args(["--apply"])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                aplicador._validar_modos(args, parser)

    def test_aplicar_solicita_lock_y_verifica_en_transaccion(self):
        cursor = _CursorFalso()
        conexion = _ConexionFalsa(cursor)
        estados = iter(
            (
                {"bloqueos": [], "estructura_fase9b_completa": False},
                {"bloqueos": [], "estructura_fase9b_completa": True},
            )
        )
        resultado = aplicador.aplicar_en_conexion(
            conexion,
            self.info,
            "DDL_FASE9B",
            recolector=lambda _cur, _info: next(estados),
            validador_destino=lambda _cur, _info: None,
        )
        self.assertTrue(resultado["aplicada"])
        self.assertFalse(resultado["idempotente"])
        sqls = [sql for sql, _ in cursor.calls]
        self.assertTrue(any("pg_try_advisory_lock" in sql for sql in sqls))
        self.assertIn("DDL_FASE9B", sqls)
        self.assertTrue(any("pg_advisory_unlock" in sql for sql in sqls))
        self.assertGreaterEqual(conexion.commits, 2)
        self.assertEqual(conexion.rollbacks, 0)

    def test_error_de_apply_hace_rollback_y_libera_lock(self):
        cursor = _CursorFalso(falla_sql="DDL_FALLA")
        conexion = _ConexionFalsa(cursor)
        with self.assertRaisesRegex(RuntimeError, "fallo simulado"):
            aplicador.aplicar_en_conexion(
                conexion,
                self.info,
                "DDL_FALLA",
                recolector=lambda _cur, _info: {"bloqueos": [], "estructura_fase9b_completa": False},
                validador_destino=lambda _cur, _info: None,
            )
        sqls = [sql for sql, _ in cursor.calls]
        self.assertEqual(conexion.rollbacks, 1)
        self.assertTrue(any("pg_advisory_unlock" in sql for sql in sqls))

    def test_segunda_aplicacion_es_idempotente_y_no_ejecuta_ddl(self):
        cursor = _CursorFalso()
        conexion = _ConexionFalsa(cursor)
        resultado = aplicador.aplicar_en_conexion(
            conexion,
            self.info,
            "DDL_NO_DEBE_EJECUTARSE",
            recolector=lambda _cur, _info: {"bloqueos": [], "estructura_fase9b_completa": True},
            validador_destino=lambda _cur, _info: None,
        )
        self.assertFalse(resultado["aplicada"])
        self.assertTrue(resultado["idempotente"])
        self.assertNotIn("DDL_NO_DEBE_EJECUTARSE", [sql for sql, _ in cursor.calls])

    def test_aplicador_no_contiene_operaciones_prohibidas_ni_seed(self):
        codigo = Path(aplicador.__file__).read_text(encoding="utf-8").upper()
        self.assertNotIn("INSERT INTO PRODUCTOS", codigo)
        self.assertNotIn("INSERT INTO NOTAS", codigo)
        self.assertNotIn("INSERT INTO PAGOS", codigo)
        self.assertNotIn("PROBAR_FASE9B_BASE_AISLADA", codigo)
        sql, _ = aplicador.cargar_migracion()
        self.assertNotIn("DROP DATABASE", sql.upper())
        self.assertNotIn("DROP TABLE", sql.upper())

    def test_migracion_no_contiene_ddl_incompatible_con_transaccion(self):
        _, auditoria = aplicador.cargar_migracion()
        self.assertFalse(auditoria["tiene_create_index_concurrently"])
        self.assertFalse(auditoria["tiene_dml"])


if __name__ == "__main__":
    unittest.main()
