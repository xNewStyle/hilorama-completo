"""Regresiones deterministas de estados sin Flask ni PostgreSQL.

Las pruebas cargan helpers puros y revisan los contratos de las rutas de forma
estatica. No leen DATABASE_URL, no abren conexiones y no modifican datos.
"""

from __future__ import annotations

import ast
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_PATH = ROOT / "hilorama_backend" / "app.py"
MOBILE_PATH = ROOT / "hilorama_celular" / "app.py"
MOBILE_HTML_PATH = ROOT / "hilorama_celular" / "index.html"
DESKTOP_VENTAS_PATH = ROOT / "main_ventas.py"
FECHA_ENVIO_MIGRATION_PATH = (
    ROOT / "hilorama_backend" / "migrations" / "003_fecha_envio_notas.sql"
)


def _source(path):
    return path.read_text(encoding="utf-8")


def _function_node(path, name):
    tree = ast.parse(_source(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"No se encontro la funcion {name} en {path.name}.")


def _function_source(path, name):
    code = _source(path)
    return ast.get_source_segment(code, _function_node(path, name)) or ""


def _load_function(path, name, namespace=None):
    node = _function_node(path, name)
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    scope = dict(namespace or {})
    exec(compile(module, str(path), "exec"), scope)
    return scope[name]


def _literal_assignment(path, name):
    tree = ast.parse(_source(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"No se encontro la constante {name} en {path.name}.")


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _ItemsConnection:
    def execute(self, _sql, _params=None):
        return _RowsResult([
            {
                "codigo": "SERVICIO",
                "marca": "Especial",
                "hilo": "No inventariable",
                "color": "",
                "cantidad": 1,
                "precio": 10,
            }
        ])


class _PrintCancelConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _RowsResult([
            {"nota_id": "COT-PRINT"},
            {"nota_id": "COT-PRINT"},
        ])


class _NotaPagoNoPermitidoPrueba(Exception):
    def __init__(self, mensaje, status):
        super().__init__(mensaje)
        self.status = status


class _EnvioConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "SELECT * FROM notas" in sql:
            return _SingleRowResult({"id": "COT-ENVIO", "estado": "ENVIADO"})
        return _SingleRowResult(None)


class _SingleRowResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class EstabilizacionEstadosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.estado_backend = staticmethod(
            _load_function(BACKEND_PATH, "_estado_empaque_por_totales")
        )
        cls.estado_movil = staticmethod(
            _load_function(MOBILE_PATH, "_estado_empaque_movil")
        )
        cls.asignables = _literal_assignment(BACKEND_PATH, "ESTADOS_EMPAQUE_ASIGNABLES")
        cls.estados_movil = _literal_assignment(MOBILE_PATH, "ESTADOS_EMPAQUE_MOVIL")

    def test_01_cotizacion_no_puede_asignarse(self):
        self.assertNotIn("COTIZACION", self.asignables)

    def test_02_venta_pendiente_no_puede_asignarse(self):
        self.assertNotIn("VENTA_PENDIENTE", self.asignables)

    def test_03_pagada_si_puede_asignarse(self):
        self.assertIn("PAGADA", self.asignables)
        source = _function_source(BACKEND_PATH, "api_notas_asignar_empacador")
        self.assertIn("ESTADOS_EMPAQUE_ASIGNABLES", source)
        self.assertIn("FOR UPDATE", source)

    def test_04_avance_de_empaque_normaliza_estados(self):
        self.assertEqual(self.estado_backend(9, 0), "EN_PROCESO")
        self.assertEqual(self.estado_backend(9, 1), "INCOMPLETA")
        self.assertEqual(self.estado_backend(9, 9), "COMPLETA")
        source = _function_source(BACKEND_PATH, "_actualizar_estado_empaque_nota_api")
        self.assertIn("fecha_finalizacion=COALESCE(fecha_finalizacion, NOW())", source)
        self.assertIn("fecha_finalizacion=NULL", source)

    def test_05_aplicacion_movil_completa_y_guarda_fecha(self):
        self.assertEqual(self.estado_movil(5, 0), "EN_PROCESO")
        self.assertEqual(self.estado_movil(5, 2), "INCOMPLETA")
        self.assertEqual(self.estado_movil(5, 5), "COMPLETA")
        source = _function_source(MOBILE_PATH, "actualizar_empacado_item")
        self.assertIn("_estado_empaque_movil", source)
        self.assertIn("fecha_finalizacion=COALESCE", source)
        self.assertIn("fecha_finalizacion=NULL", source)
        self.assertNotIn("descontar_stock", source)

    def test_06_guardar_guia_no_marca_enviado(self):
        legacy = _function_source(BACKEND_PATH, "agregar_guia")
        moderno = _function_source(BACKEND_PATH, "api_envios_nota_actualizar")
        self.assertIn("SET guia=%s", legacy)
        self.assertNotIn("estado='ENVIADO'", legacy)
        self.assertIn("Usa la accion Marcar como enviado", moderno)
        self.assertNotIn('cambios["estado"]', moderno)

    def test_07_marcar_enviado_es_transicion_explicita(self):
        source = _function_source(BACKEND_PATH, "_marcar_nota_enviada_api_conn")
        self.assertIn('estado_actual != "COMPLETA"', source)
        self.assertIn('nota.get("guia")', source)
        self.assertIn("estado='ENVIADO'", source)
        self.assertIn("fecha_envio=COALESCE(fecha_envio, NOW())", source)

    def test_08_anulada_no_aparece_en_colas_operativas(self):
        asignacion = _function_source(BACKEND_PATH, "_notas_asignacion_empacador_api")
        envios = _function_source(BACKEND_PATH, "api_envios_notas_listar")
        empaque_movil = _function_source(MOBILE_PATH, "empacador_notas")
        impresion = _function_source(BACKEND_PATH, "obtener_cola")
        for estado in ("ANULADA", "ARCHIVADA", "ENVIADO"):
            self.assertNotIn(f"'{estado}'", asignacion)
            self.assertIn(f"'{estado}'", envios)
        self.assertNotIn("ANULADA", empaque_movil)
        self.assertNotIn("ARCHIVADA", empaque_movil)
        self.assertIn("ANULADA", impresion)
        self.assertIn("ARCHIVADA", impresion)

    def test_09_anulacion_cancela_impresion_y_conserva_idempotencia(self):
        source = _function_source(BACKEND_PATH, "api_notas_anular")
        self.assertIn("_nota_requiere_devolucion_stock_api", source)
        self.assertIn("_devolver_stock_nota_api", source)
        self.assertIn("_cancelar_impresiones_pendientes_nota_api", source)
        self.assertIn("idempotente = ya_anulada and not productos_devueltos", source)

    def test_10_no_inventariable_no_provoca_ciclo_infinito(self):
        function = _load_function(
            BACKEND_PATH,
            "_items_stock_nota_api",
            {
                "_resolver_nota_api": lambda _conn, nota_id: (nota_id, {}),
                "_row_dict": lambda row: dict(row) if row else {},
                "_buscar_producto_item_api": lambda *_args, **_kwargs: {
                    "id": 1,
                    "codigo": "SERVICIO",
                    "stock": 0,
                    "es_inventariable": False,
                },
                "_agrupar_lineas_movimiento": lambda lineas: list(lineas),
                "_cantidad_item_stock_api": lambda item: int(item.get("cantidad") or 0),
                "_producto_inventariable_api": lambda producto: bool(
                    producto.get("es_inventariable", True)
                ),
                "STOCK_MINIMO_API": 10,
            },
        )
        resultado = []
        error = []

        def ejecutar():
            try:
                resultado.append(function(_ItemsConnection(), "COT-PRUEBA"))
            except Exception as exc:  # pragma: no cover - solo diagnostico del hilo
                error.append(exc)

        thread = threading.Thread(target=ejecutar, daemon=True)
        thread.start()
        thread.join(1.0)
        self.assertFalse(thread.is_alive(), "La validacion de stock entro en un ciclo indefinido.")
        self.assertFalse(error, error[0] if error else None)
        lineas, afectados = resultado[0]
        self.assertEqual(len(lineas), 1)
        self.assertEqual(afectados, [])

    def test_11_enviada_no_regresa_a_empaque(self):
        self.assertNotIn("ENVIADO", self.asignables)
        self.assertNotIn("ENVIADO", self.estados_movil)
        escaneo = _function_source(BACKEND_PATH, "escanear_producto")
        self.assertIn("ESTADOS_EMPAQUE_ASIGNABLES", escaneo)

    def test_12_colas_no_incluyen_cotizaciones_ni_pendientes(self):
        asignacion = _function_source(BACKEND_PATH, "_notas_asignacion_empacador_api")
        empaque_movil = _function_source(MOBILE_PATH, "empacador_notas")
        for estado in ("COTIZACION", "VENTA_PENDIENTE"):
            self.assertNotIn(f"'{estado}'", asignacion)
            self.assertNotIn(f"'{estado}'", empaque_movil)

    def test_13_frontend_movil_conserva_pago_en_estados_posteriores(self):
        html = _source(MOBILE_HTML_PATH)
        for estado in ("PAGADA", "EN_PROCESO", "INCOMPLETA", "COMPLETA", "ENVIADO"):
            self.assertIn(estado, html)

    def test_14_desktop_filtra_y_valida_asignacion(self):
        source = _function_source(DESKTOP_VENTAS_PATH, "abrir_panel_asignacion")
        self.assertIn("WHERE n.estado IN ('PAGADA','EN_PROCESO','INCOMPLETA')", source)
        self.assertIn('{"PAGADA", "EN_PROCESO", "INCOMPLETA"}', source)
        self.assertNotIn("VENTA_PENDIENTE", source)

    def test_15_desktop_separa_guia_de_envio(self):
        guia = _function_source(DESKTOP_VENTAS_PATH, "asignar_guia")
        enviado = _function_source(DESKTOP_VENTAS_PATH, "marcar_como_enviado")
        self.assertNotIn("estado='ENVIADO'", guia)
        self.assertIn("estado='ENVIADO'", enviado)
        self.assertIn("fecha_envio=COALESCE(fecha_envio, NOW())", enviado)

    def test_16_desktop_bloquea_reimpresion_terminal(self):
        source = _function_source(DESKTOP_VENTAS_PATH, "abrir_opciones_impresion")
        for estado in ("ANULADA", "CANCELADA", "ELIMINADA", "ARCHIVADA"):
            self.assertIn(estado, source)

    def test_17_filtro_todas_pagadas_incluye_empaque(self):
        backend = _function_source(BACKEND_PATH, "api_envios_notas_listar")
        desktop = _function_source(DESKTOP_VENTAS_PATH, "abrir_panel_envios")
        estados = "('PAGADA','EN_PROCESO','INCOMPLETA','COMPLETA')"
        self.assertIn(estados, backend)
        self.assertIn(estados, desktop)

    def test_18_archivada_es_terminal_para_pago_y_anulacion(self):
        pago = _function_source(BACKEND_PATH, "_rechazar_pago_nota_anulada_api")
        anulacion = _function_source(BACKEND_PATH, "api_notas_anular")
        self.assertIn("ARCHIVADA", pago)
        self.assertIn('estado == "ARCHIVADA"', anulacion)

    def _marcar_enviado(self, columnas):
        function = _load_function(
            BACKEND_PATH,
            "_marcar_nota_enviada_api_conn",
            {
                "_resolver_nota_api": lambda _conn, nota_id, bloquear=False: (
                    nota_id,
                    {"id": nota_id, "estado": "COMPLETA", "guia": "GUIA-1"},
                ),
                "_normalizar_estado_pago_api": lambda estado: str(estado or "").upper(),
                "_columnas_tabla_api": lambda _conn, _tabla: set(columnas),
                "_row_dict": lambda row: dict(row) if row else {},
                "_json_field": lambda valor, default: valor if isinstance(valor, dict) else default,
                "_guia_nota_notificaciones": lambda nota: str(nota.get("guia") or "").strip(),
                "_requiere_guia_notificaciones": lambda _nota: True,
                "NotaPagoNoPermitido": _NotaPagoNoPermitidoPrueba,
            },
        )
        conn = _EnvioConnection()
        resultado = function(conn, "COT-ENVIO")
        return conn, resultado

    def test_19_marcar_enviado_guarda_fecha_si_columna_existe(self):
        conn, resultado = self._marcar_enviado({"id", "estado", "guia", "fecha_envio"})
        sql = "\n".join(call[0] for call in conn.calls)
        self.assertIn("fecha_envio=COALESCE(fecha_envio, NOW())", sql)
        self.assertTrue(resultado[3])

    def test_20_marcar_enviado_funciona_sin_fecha_envio(self):
        conn, resultado = self._marcar_enviado({"id", "estado", "guia"})
        sql = "\n".join(call[0] for call in conn.calls)
        self.assertIn("estado='ENVIADO'", sql)
        self.assertNotIn("fecha_envio=", sql)
        self.assertFalse(resultado[3])

    def test_21_guardar_guia_no_establece_fecha_envio(self):
        legacy = _function_source(BACKEND_PATH, "agregar_guia")
        self.assertNotIn("fecha_envio", legacy)

    def test_22_migracion_fecha_envio_es_separada_e_idempotente(self):
        sql = _source(FECHA_ENVIO_MIGRATION_PATH).upper()
        self.assertIn("ALTER TABLE NOTAS", sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS FECHA_ENVIO TIMESTAMPTZ", sql)
        self.assertNotIn("UPDATE NOTAS", sql)

    def test_23_contador_impresiones_canceladas_usa_filas_reales(self):
        function = _load_function(
            BACKEND_PATH,
            "_cancelar_impresiones_pendientes_nota_api",
            {
                "_columnas_tabla_api": lambda _conn, _tabla: {"nota_id", "estado"},
            },
        )
        conn = _PrintCancelConnection()
        self.assertEqual(function(conn, "COT-PRINT"), 2)
        self.assertIn("RETURNING nota_id", conn.calls[0][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
