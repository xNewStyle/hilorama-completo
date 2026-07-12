"""Regresiones deterministas de FASE 9B.1 sin Flask ni PostgreSQL.

Las pruebas de base real quedan deliberadamente fuera: esta auditoria no abre
DATABASE_URL ni aplica la migracion. Los contratos SQL se verifican de forma
estatica y los helpers se prueban con conexiones simuladas.
"""

from __future__ import annotations

import ast
import contextlib
import io
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hilorama_backend.scripts.diagnosticar_movimientos_auditoria import (
    _diagnose_movimientos,
    clasificar_movimiento_temporal,
    debe_revisar_notas_pagadas,
    expresion_fecha_referencia_movimiento,
    fecha_referencia_movimiento,
)
from hilorama_backend.services.auditoria_service import (
    limpiar_datos_sensibles,
    limpiar_texto_sensible,
    registrar_auditoria,
)
from hilorama_backend.services.movimientos_almacen_service import (
    agrupar_lineas_producto,
    cantidad_reintegrable,
    clave_producto_movimiento,
    normalizar_tipo_movimiento,
    registrar_movimiento_almacen,
)


ROOT = REPO_ROOT
APP_PATH = ROOT / "hilorama_backend" / "app.py"
MIGRATION_PATH = ROOT / "hilorama_backend" / "migrations" / "002_fase9_movimientos_auditoria.sql"
RUNNER_PATH = ROOT / "hilorama_backend" / "scripts" / "probar_fase9b_base_aislada.py"
DIAGNOSTICO_PATH = ROOT / "hilorama_backend" / "scripts" / "diagnosticar_movimientos_auditoria.py"

MOVIMIENTO_COLUMNS = {
    "id", "fecha", "usuario", "tipo", "marca", "hilo", "color", "codigo",
    "stock_anterior", "stock_nuevo", "cantidad", "campo", "valor_anterior",
    "valor_nuevo", "motivo", "producto_id", "referencia_tipo", "referencia_id",
    "usuario_id", "cliente_sistema_id", "device_id", "idempotency_key", "metadata_json",
}


class _FakeConnection:
    def __init__(self, existing_by_client=None, fail_insert=False):
        self.existing_by_client = dict(existing_by_client or {})
        self.fail_insert = fail_insert
        self.calls = []
        self.current_row = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM movimientos_almacen" in sql and "idempotency_key" in sql:
            cliente_id = params[1] if params and len(params) > 1 else None
            self.current_row = self.existing_by_client.get(cliente_id)
        elif "INSERT INTO movimientos_almacen" in sql:
            if self.fail_insert:
                raise RuntimeError("fallo simulado")
            self.current_row = {"id": 100 + len(self.calls)}
        else:
            self.current_row = None
        return self

    def fetchone(self):
        return self.current_row


class _FakeAuditConnection:
    def __init__(self):
        self.calls = []
        self.current_row = {"id": 1}

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.current_row


class _TemporalDiagnosticCursor:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return self.respuestas.pop(0) if self.respuestas else []


class Fase9BRegresionTests(unittest.TestCase):
    @staticmethod
    def _app_function_source(nombre):
        codigo = APP_PATH.read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
                return ast.get_source_segment(codigo, nodo) or ""
        raise AssertionError(f"No se encontro la funcion {nombre}.")

    def _registrar(self, conn, **kwargs):
        data = {
            "producto": {"id": 5, "codigo": "429", "marca": "Velluto", "hilo": "Velluto"},
            "tipo": "VENTA",
            "cantidad": -2,
            "stock_anterior": 10,
            "stock_nuevo": 8,
            "referencia_tipo": "NOTA",
            "referencia_id": "COT-10",
            "cliente_sistema_id": 7,
            "idempotency_key": "VENTA:PAGO:COT-10:5",
        }
        data.update(kwargs)
        return registrar_movimiento_almacen(conn, MOVIMIENTO_COLUMNS, **data)

    def test_01_normaliza_tipo_positivo(self):
        self.assertEqual(normalizar_tipo_movimiento("ajuste", 2), "AJUSTE_POSITIVO")

    def test_02_normaliza_tipo_negativo(self):
        self.assertEqual(normalizar_tipo_movimiento("ajuste", -2), "AJUSTE_NEGATIVO")

    def test_03_registra_salida_con_ecuacion_correcta(self):
        resultado = self._registrar(_FakeConnection())
        self.assertTrue(resultado["creado"])

    def test_04_rechaza_ecuacion_de_stock_invalida(self):
        with self.assertRaises(ValueError):
            self._registrar(_FakeConnection(), stock_nuevo=9)

    def test_05_fallo_movimiento_propagado_para_rollback_externo(self):
        conn = _FakeConnection(fail_insert=True)
        with self.assertRaisesRegex(RuntimeError, "fallo simulado"):
            self._registrar(conn)
        self.assertTrue(any("ROLLBACK TO SAVEPOINT" in sql for sql, _ in conn.calls))

    def test_06_repeticion_mismo_cliente_es_idempotente(self):
        existente = {"id": 7, "tipo": "VENTA", "cantidad": -2, "stock_anterior": 10, "stock_nuevo": 8}
        resultado = self._registrar(_FakeConnection(existing_by_client={7: existente}))
        self.assertTrue(resultado["idempotente"])
        self.assertFalse(resultado["creado"])

    def test_07_misma_llave_en_otro_cliente_no_colisiona(self):
        existente = {"id": 7, "tipo": "VENTA", "cantidad": -2, "stock_anterior": 10, "stock_nuevo": 8}
        conn = _FakeConnection(existing_by_client={7: existente})
        resultado = self._registrar(conn, cliente_sistema_id=8)
        self.assertTrue(resultado["creado"])
        consultas = [params for sql, params in conn.calls if "COALESCE(cliente_sistema_id" in sql]
        self.assertIn(("VENTA:PAGO:COT-10:5", 8), consultas)

    def test_08_agrupar_lineas_repetidas_descontaria_una_sola_vez(self):
        lineas = [
            ({"codigo": "429", "cantidad": 2}, {"id": 5, "codigo": "429"}, None),
            ({"codigo": "429", "cantidad": 3}, {"id": 5, "codigo": "429"}, None),
        ]
        agrupadas = agrupar_lineas_producto(lineas)
        self.assertEqual(len(agrupadas), 1)
        self.assertEqual(agrupadas[0][0]["cantidad"], 5)

    def test_09_agrupar_lineas_distingue_productos(self):
        lineas = [
            ({"codigo": "429", "cantidad": 2}, {"id": 5, "codigo": "429"}, None),
            ({"codigo": "550", "cantidad": 3}, {"id": 6, "codigo": "550"}, None),
        ]
        self.assertEqual(len(agrupar_lineas_producto(lineas)), 2)

    def test_10_reintegro_no_supera_salida(self):
        self.assertEqual(cantidad_reintegrable(5, 2), 3)
        self.assertEqual(cantidad_reintegrable(5, 8), 0)

    def test_11_diagnostico_no_revisa_historicos_por_defecto(self):
        self.assertFalse(debe_revisar_notas_pagadas(None, False))

    def test_12_diagnostico_revisa_desde_fecha_de_activacion(self):
        self.assertTrue(debe_revisar_notas_pagadas("2026-07-12", False))
        self.assertTrue(debe_revisar_notas_pagadas(None, True))

    def test_13_sanitiza_secretos_anidados_y_listas(self):
        limpio = limpiar_datos_sensibles({
            "nested": {"access_token": "abc"},
            "items": [{"Clave_Autorizacion": "uno"}],
            "cookie": "session=abc",
        })
        self.assertEqual(limpio["nested"]["access_token"], "[oculto]")
        self.assertEqual(limpio["items"][0]["Clave_Autorizacion"], "[oculto]")
        self.assertEqual(limpio["cookie"], "[oculto]")

    def test_14_sanitiza_secretos_incrustados_en_texto(self):
        texto = limpiar_texto_sensible("fallo authorization: Bearer abc123; password=secreto")
        self.assertNotIn("abc123", texto)
        self.assertNotIn("secreto", texto)
        self.assertEqual(limpiar_texto_sensible("postgresql://u:clave@host/base"), "[oculto]")

    def test_15_auditoria_no_persiste_secretos_en_descripcion_ni_metadata(self):
        conn = _FakeAuditConnection()
        columnas = {
            "id", "accion", "modulo", "descripcion", "datos_anteriores_json", "datos_nuevos_json",
            "codigo_error", "request_id", "user_agent", "resultado",
        }
        registrar_auditoria(
            conn,
            columnas,
            accion="PRUEBA",
            modulo="test",
            descripcion="token=abc123",
            datos_nuevos={"metadata": {"refresh_token": "xyz"}},
            codigo_error="password=secreto",
        )
        valores = " ".join(str(valor) for valor in conn.calls[-1][1])
        self.assertNotIn("abc123", valores)
        self.assertNotIn("xyz", valores)
        self.assertNotIn("secreto", valores)

    def test_16_migracion_no_borra_datos_ni_tablas(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8").upper()
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("TRUNCATE", sql)
        self.assertNotIn("DELETE FROM", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS", sql)

    def test_17_migracion_hace_idempotencia_por_cliente(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("uq_movimientos_almacen_cliente_idempotency_key", sql)
        self.assertIn("COALESCE(cliente_sistema_id, 0), idempotency_key", sql)

    def test_18_rutas_movimientos_son_solo_lectura(self):
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        rutas = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                ruta = decorator.args[0]
                if isinstance(ruta, ast.Constant) and "/api/almacen/movimientos" in str(ruta.value):
                    methods = next((kw.value for kw in decorator.keywords if kw.arg == "methods"), None)
                    rutas.append((str(ruta.value), ast.literal_eval(methods)))
        self.assertTrue(rutas)
        self.assertTrue(all(metodos == ["GET"] for _, metodos in rutas))

    def test_19_contrato_backend_bloquea_y_agrupa_stock(self):
        codigo = APP_PATH.read_text(encoding="utf-8")
        self.assertIn("FOR UPDATE", codigo)
        self.assertIn("_agrupar_lineas_movimiento", codigo)
        self.assertIn("_cantidades_salida_nota_api", codigo)

    def test_20_simulacion_concurrente_no_descuenta_mas_de_lo_disponible(self):
        class LibroStock:
            def __init__(self):
                self.stock = 10
                self.lock = threading.Lock()

            def vender(self, cantidad):
                with self.lock:
                    if cantidad > self.stock:
                        return False
                    self.stock -= cantidad
                    return True

        libro = LibroStock()
        resultados = []
        hilos = [threading.Thread(target=lambda: resultados.append(libro.vender(7))) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        self.assertEqual(sorted(resultados), [False, True])
        self.assertEqual(libro.stock, 3)

    def test_21_metadata_de_movimiento_no_persiste_secretos(self):
        conn = _FakeConnection()
        self._registrar(conn, metadata={"token": "no-visible", "nested": {"clave": "no-visible"}})
        insert_params = next(params for sql, params in conn.calls if "INSERT INTO movimientos_almacen" in sql)
        valores = " ".join(str(valor) for valor in insert_params)
        self.assertNotIn("no-visible", valores)
        self.assertIn("[oculto]", valores)

    def test_22_pago_repetido_bloquea_nota_y_no_depende_de_request_id(self):
        codigo = self._app_function_source("api_notas_marcar_pago")
        self.assertIn("_resolver_nota_api(conn, nota_id, bloquear=True)", codigo)
        self.assertIn("_nota_pago_ya_aplicado_api", codigo)
        self.assertIn("PAGO_REPETIDO", codigo)

    def test_23_pago_y_movimientos_comparten_contexto_transaccional(self):
        codigo = self._app_function_source("api_pagos_registrar")
        self.assertIn("with get_conn() as conn:", codigo)
        self.assertLess(
            codigo.index("_rechazar_pago_nota_anulada_api(actual)"),
            codigo.index("_nota_pago_ya_aplicado_api(conn, actual)"),
        )
        self.assertIn("_descontar_stock_nota_api(\n                    conn,", codigo)
        self.assertIn("UPDATE notas SET", codigo)
        self.assertIn("_insertar_pago_api(conn", codigo)

    def test_24_pago_multilinea_agrupa_antes_de_validar_stock(self):
        codigo = self._app_function_source("_items_stock_nota_api")
        self.assertIn("_agrupar_lineas_movimiento", codigo)
        self.assertIn("bloquear=True", self._app_function_source("_descontar_stock_nota_api"))

    def test_25_cancelar_cotizacion_o_venta_pendiente_no_devuelve_sin_salida(self):
        codigo = self._app_function_source("_nota_requiere_devolucion_stock_api")
        self.assertIn("_cantidades_pendientes_devolucion_nota_api", codigo)
        self.assertNotIn("ESTADOS_NOTA_PAGADA_API", codigo)

    def test_26_anulacion_repetida_es_idempotente_y_anulada_incompleta_se_repara(self):
        codigo = self._app_function_source("api_notas_anular")
        self.assertIn("ya_anulada", codigo)
        self.assertIn("idempotente = ya_anulada and not productos_devueltos", codigo)
        self.assertIn('"idempotente": idempotente', codigo)
        self.assertNotIn("_devolucion_stock_existente_api(conn, nota_id_real, auth)", codigo)

    def test_27_venta_historica_pagada_sin_movimiento_no_reintegra(self):
        codigo = self._app_function_source("_nota_requiere_devolucion_stock_api")
        self.assertIn("return bool(_cantidades_pendientes_devolucion_nota_api", codigo)

    def test_28_movimientos_se_filtran_por_cliente_en_backend(self):
        codigo = self._app_function_source("_restriccion_cliente_movimientos_api")
        self.assertIn("cliente_sistema_id=%s", codigo)
        self.assertIn("super_admin", codigo)

    def test_29_auditoria_requiere_super_admin_en_backend(self):
        codigo = self._app_function_source("_validar_acceso_auditoria_general_api")
        self.assertIn('get("rol") != "super_admin"', codigo)

    def test_30_respuesta_movimientos_conserva_campos_legacy(self):
        codigo = self._app_function_source("_respuesta_movimientos_paginada_api")
        for campo in ('"movimientos": items', '"total": total', '"limit": per_page', '"offset": offset'):
            self.assertIn(campo, codigo)

    def test_31_no_hay_rutas_duplicadas(self):
        codigo = APP_PATH.read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        vistas = {}
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorador in nodo.decorator_list:
                if not isinstance(decorador, ast.Call) or not decorador.args:
                    continue
                if not isinstance(decorador.args[0], ast.Constant):
                    continue
                metodos = next((ast.literal_eval(argumento.value) for argumento in decorador.keywords if argumento.arg == "methods"), ["GET"])
                clave = (decorador.args[0].value, tuple(metodos))
                self.assertNotIn(clave, vistas, f"Ruta duplicada: {clave}")
                vistas[clave] = nodo.name

    def test_32_todas_las_rutas_se_definen_antes_del_arranque(self):
        codigo = APP_PATH.read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        arranque = next(
            (nodo.lineno for nodo in arbol.body if isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Compare)),
            10 ** 9,
        )
        rutas = [
            nodo.lineno
            for nodo in ast.walk(arbol)
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(decorador, ast.Call) for decorador in nodo.decorator_list)
        ]
        self.assertTrue(all(linea < arranque for linea in rutas))

    def test_33_pagos_api_y_runner_comparten_contrato_fecha_legacy(self):
        codigo_runner = RUNNER_PATH.read_text(encoding="utf-8")
        inicio = codigo_runner.index("CREATE TABLE IF NOT EXISTS pagos")
        fin = codigo_runner.index(");", inicio) + 2
        contrato_pagos = codigo_runner[inicio:fin].upper()
        self.assertIn("FECHA TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", contrato_pagos)
        consulta_pagos = self._app_function_source("_pagos_nota_api_conn")
        self.assertIn("ORDER BY fecha DESC", consulta_pagos)

    def test_34_runner_cubre_pago_repetido_sin_stock_extra_y_rollback(self):
        codigo_runner = RUNNER_PATH.read_text(encoding="utf-8")
        for etiqueta in (
            '"pago_producto_repetido"',
            '"pago_repetido"',
            '"rollback_forzado"',
            '"reintento_tras_rollback"',
        ):
            self.assertIn(etiqueta, codigo_runner)
        self.assertIn("El pago repetido modifico stock.", codigo_runner)
        self.assertIn("El rollback dejo movimientos o pagos parciales.", codigo_runner)

    def test_35_anulacion_calcula_reposicion_desde_movimientos_venta_reales(self):
        codigo = self._app_function_source("_devolver_stock_nota_api")
        self.assertIn("_cantidades_salida_nota_api(conn, nota_id, auth)", codigo)
        self.assertIn("_cantidades_reintegradas_nota_api(conn, nota_id, auth)", codigo)
        self.assertIn("_cantidades_pendientes_devolucion_nota_api(conn, nota_id, auth)", codigo)
        self.assertIn("_producto_por_clave_movimiento_api", codigo)
        self.assertIn('tipo="CANCELACION_VENTA"', codigo)
        self.assertIn("SALIDA:{cantidad_salida}:REINTEGRADA:{cantidad_reintegrada}", codigo)

    def test_36_reintegro_no_supera_salidas_efectivas(self):
        self.assertEqual(cantidad_reintegrable(9, 0), 9)
        self.assertEqual(cantidad_reintegrable(9, 4), 5)
        self.assertEqual(cantidad_reintegrable(9, 9), 0)
        self.assertEqual(cantidad_reintegrable(9, 12), 0)

    def test_37_runner_audita_trigger_y_stock_desde_movimientos_reales(self):
        codigo_runner = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn("def _resumen_movimientos_nota", codigo_runner)
        self.assertIn("stock_esperado_anulacion", codigo_runner)
        self.assertIn("reposiciones_despues_anular", codigo_runner)
        self.assertIn("conn.rollback()", codigo_runner)
        self.assertIn("No se pudo confirmar la limpieza del trigger", codigo_runner)

    def test_38_clave_de_movimiento_usa_producto_id_para_venta_y_reposicion(self):
        movimiento = {"producto_id": 3, "marca": "F9B", "hilo": "HILO_TEST", "codigo": "REP"}
        producto = {"id": 3, "marca": "F9B", "hilo": "HILO_TEST", "codigo": "REP"}
        self.assertEqual(
            clave_producto_movimiento(movimiento, movimiento),
            clave_producto_movimiento(producto, producto),
        )

    def test_39_runner_cubre_reparacion_de_anulada_con_venta_pendiente(self):
        codigo_runner = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn('"reparar_anulada_con_venta_pendiente"', codigo_runner)
        self.assertIn('"pago_anulada_rechazado"', codigo_runner)
        self.assertIn("UPDATE notas SET estado='ANULADA'", codigo_runner)
        self.assertIn('"cantidad": 9', codigo_runner)
        self.assertIn("La reparacion de nota anulada no repuso las 9 piezas pendientes.", codigo_runner)

    def test_40_runner_diagnostica_http_inesperado_y_pago_inicial_autorizado(self):
        codigo_runner = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn("respuesta={limpiar_diagnostico_http(data)}", codigo_runner)
        self.assertIn("contexto={limpiar_diagnostico_http(contexto or {})}", codigo_runner)
        inicio = codigo_runner.index('"pago_para_reparacion_anulada"')
        fin = codigo_runner.index("UPDATE notas SET estado='ANULADA'", inicio)
        bloque_pago = codigo_runner[inicio:fin]
        self.assertIn('"autorizacion_stock": "1"', bloque_pago)
        self.assertIn('"cantidad": -9', bloque_pago)
        self.assertIn("clave_venta_reparacion", bloque_pago)

    def test_41_pago_anulado_o_cancelado_se_rechaza_antes_de_idempotencia(self):
        codigo_app = APP_PATH.read_text(encoding="utf-8")
        self.assertIn('ESTADOS_NOTA_ANULADA_API = {"ANULADA", "CANCELADA", "ELIMINADA"}', codigo_app)
        helper = self._app_function_source("_rechazar_pago_nota_anulada_api")
        self.assertIn("ESTADOS_NOTA_ANULADA_API", helper)
        self.assertIn("NotaPagoNoPermitido", helper)
        self.assertIn(", 409)", helper)
        for endpoint in ("api_notas_marcar_pago", "api_pagos_registrar"):
            codigo = self._app_function_source(endpoint)
            self.assertLess(
                codigo.index("_rechazar_pago_nota_anulada_api(actual)"),
                codigo.index("_nota_pago_ya_aplicado_api(conn, actual)"),
            )

    def test_42_runner_separa_nota_anulable_de_evidencia_historica_diagnostico(self):
        codigo_runner = RUNNER_PATH.read_text(encoding="utf-8")
        inicio_anulable = codigo_runner.index('nota_historica_anulable = f"{run_tag}-HISTORICA-ANULABLE"')
        inicio_diagnostico = codigo_runner.index('nota_historica = f"{run_tag}-HISTORICA-DIAGNOSTICO"')
        self.assertLess(inicio_anulable, inicio_diagnostico)
        bloque_diagnostico = codigo_runner[inicio_diagnostico:codigo_runner.index("return {", inicio_diagnostico)]
        self.assertIn("INSERT INTO pagos(nota_id, comprobante, fecha)", bloque_diagnostico)
        self.assertIn('"PAGADA"', bloque_diagnostico)
        self.assertIn("fecha_historica_diagnostico = datetime(2020, 1, 1, 12, 0, 0)", bloque_diagnostico)
        self.assertIn('_contar_movimientos_nota(conn, nota_historica, "VENTA") != 0', bloque_diagnostico)
        self.assertIn('_contar_movimientos_nota(conn, nota_historica, "CANCELACION_VENTA") != 0', bloque_diagnostico)
        self.assertNotIn("/anular", bloque_diagnostico)

    def test_43_diagnostico_historico_exige_estado_pagado_y_ausencia_de_venta(self):
        codigo = DIAGNOSTICO_PATH.read_text(encoding="utf-8")
        self.assertIn("('PAGADA', 'PAGADO', 'COMPLETA', 'VENTA_PAGADA')", codigo)
        self.assertIn('fecha_columna = next((campo for campo in ("fecha_pago", "fecha", "fecha_creacion")', codigo)
        self.assertIn("AND NOT EXISTS", codigo)
        self.assertIn("UPPER(COALESCE(m.tipo, ''))='VENTA'", codigo)
        self.assertIn("m.referencia_id=CAST(n.id AS TEXT)", codigo)
        self.assertIn("return 1 if args.strict and problemas else 0", codigo)

    def test_44_fecha_original_prevalece_sobre_fecha_creacion_de_migracion(self):
        fecha_legacy = datetime(2020, 1, 1, 10, 0, 0)
        fecha_migracion = datetime(2026, 7, 12, 9, 0, 0)
        self.assertEqual(fecha_referencia_movimiento(fecha_legacy, fecha_migracion), fecha_legacy)
        self.assertEqual(
            clasificar_movimiento_temporal(fecha_legacy, fecha_migracion, "2026-07-12"),
            "HISTORICO",
        )
        self.assertEqual(
            clasificar_movimiento_temporal(fecha_migracion, fecha_migracion, "2026-07-12"),
            "DESDE_CORTE",
        )

    def test_45_fecha_referencia_tiene_fallback_y_nulos_explicitos(self):
        fecha_nueva = datetime(2026, 7, 13, 10, 0, 0)
        self.assertEqual(fecha_referencia_movimiento(None, fecha_nueva), fecha_nueva)
        self.assertEqual(
            clasificar_movimiento_temporal(None, fecha_nueva, "2026-07-12"),
            "DESDE_CORTE",
        )
        self.assertEqual(
            clasificar_movimiento_temporal(fecha_nueva, None, "2026-07-12"),
            "DESDE_CORTE",
        )
        self.assertEqual(
            clasificar_movimiento_temporal(None, None, "2026-07-12"),
            "SIN_FECHA_REFERENCIA",
        )

    def test_46_corte_temporal_aplica_a_las_tres_reglas_de_movimientos(self):
        columnas = set(MOVIMIENTO_COLUMNS) | {"fecha_creacion"}
        cursor = _TemporalDiagnosticCursor(
            [
                [],
                [{"id": 81, "tipo": "VENTA", "stock_anterior": 10, "cantidad": -2, "stock_nuevo": 9}],
                [],
                [],
            ]
        )
        with contextlib.redirect_stdout(io.StringIO()):
            problemas = _diagnose_movimientos(cursor, columnas, 20, desde="2026-07-12")
        self.assertEqual(problemas, 1)
        consultas = "\n".join(sql for sql, _ in cursor.calls)
        self.assertIn("COALESCE(m.fecha, m.fecha_creacion) >= %s", consultas)
        self.assertIn("MAX(COALESCE(m.fecha, m.fecha_creacion)) >= %s", consultas)
        self.assertIn("Movimientos con producto_id inexistente", DIAGNOSTICO_PATH.read_text(encoding="utf-8"))
        self.assertIn("return 1 if args.strict and problemas else 0", DIAGNOSTICO_PATH.read_text(encoding="utf-8"))

    def test_47_historicos_siguen_informativos_sin_excepciones_por_tipo(self):
        columnas = set(MOVIMIENTO_COLUMNS) | {"fecha_creacion"}
        cursor = _TemporalDiagnosticCursor(
            [[{"id": 14, "tipo": "SALIDA_ITEM_COTIZACION"}], [], []]
        )
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            problemas = _diagnose_movimientos(cursor, columnas, 20, incluir_historicos=True)
        self.assertEqual(problemas, 1)
        self.assertIn("incluye históricos", salida.getvalue())
        codigo = DIAGNOSTICO_PATH.read_text(encoding="utf-8")
        self.assertNotIn("SALIDA_ITEM_COTIZACION", codigo)
        self.assertNotIn("AUTORIZACION_STOCK", codigo)

    def test_48_verify_etiqueta_hallazgos_nuevos_e_historicos_por_separado(self):
        codigo = (ROOT / "hilorama_backend" / "scripts" / "aplicar_fase9b_produccion.py").read_text(encoding="utf-8")
        self.assertIn("regla_temporal_movimientos", codigo)
        self.assertIn("diagnostico_normal_desde", codigo)
        self.assertIn("diagnostico_historico", codigo)


if __name__ == "__main__":
    unittest.main()
