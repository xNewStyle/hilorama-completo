"""Regresiones de autorizacion de stock sin red ni base de datos real."""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HILORAMA_DATA_MODE", "api")

import ver_cotizaciones as visor
from hilorama_backend import app as backend


def _producto(producto_id, stock=180, **cambios):
    data = {
        "id": producto_id,
        "codigo": "1",
        "codigo_barras": f"B-{producto_id}",
        "marca": "KARINA",
        "hilo": "KOMFY MINI",
        "color": "BLANCO",
        "stock": stock,
        "estado": "OK",
        "es_inventariable": True,
    }
    data.update(cambios)
    return data


def _linea(producto_id=228, cantidad=1, **cambios):
    data = {
        "producto_id": producto_id,
        "codigo": "1",
        "marca": "KARINA",
        "hilo": "KOMFY MINI",
        "color": "BLANCO",
        "cantidad": cantidad,
        "precio": 80,
    }
    data.update(cambios)
    return data


class _Resultado:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Conexion:
    def __init__(self, productos=None, items=None):
        self.productos = [dict(p) for p in (productos or [])]
        self.items = [dict(i) for i in (items or [])]
        self.calls = []

    def execute(self, sql, params=None):
        params = tuple(params or ())
        self.calls.append((sql, params))
        normalizada = " ".join(sql.split()).upper()
        if "FROM ITEMS" in normalizada:
            return _Resultado(self.items)
        if "FROM PRODUCTOS WHERE ID=%S" in normalizada:
            producto_id = int(params[0])
            return _Resultado([p for p in self.productos if int(p.get("id")) == producto_id])
        if "FROM PRODUCTOS" in normalizada and "UPPER(CAST(MARCA AS TEXT))" in normalizada:
            marca, hilo = str(params[0]).upper(), str(params[1]).upper()
            codigos = {str(valor) for valor in params[2:]}
            rows = [
                p for p in self.productos
                if str(p.get("marca") or "").upper() == marca
                and str(p.get("hilo") or "").upper() == hilo
                and ({str(p.get("codigo") or ""), str(p.get("codigo_barras") or "")} & codigos)
            ]
            return _Resultado(sorted(rows, key=lambda p: int(p.get("id") or 0))[:2])
        return _Resultado()


def _columnas(_conn, tabla):
    if tabla == "productos":
        return {
            "id", "codigo", "codigo_barras", "marca", "hilo", "color",
            "stock", "estado", "es_inventariable", "tipo_producto",
        }
    if tabla == "items":
        return {"nota_id", "producto_id", "codigo", "marca", "hilo", "color", "cantidad", "precio"}
    return set()


class StockAutorizacionDesktopTests(unittest.TestCase):
    def test_stock_180_no_pide_autorizacion_para_1_ni_20(self):
        with patch.object(visor, "obtener_producto_por_id", return_value=_producto(228, 180)) as obtener:
            self.assertEqual(visor._stock_afectado_items_ui([_linea(cantidad=1)]), [])
            self.assertEqual(visor._stock_afectado_items_ui([_linea(cantidad=20)]), [])
        self.assertEqual([call.args[0] for call in obtener.call_args_list], [228, 228])

    def test_stock_10_venta_11_muestra_faltante_real(self):
        with patch.object(visor, "obtener_producto_por_id", return_value=_producto(228, 10)):
            afectados = visor._stock_afectado_items_ui([_linea(cantidad=11)])
        self.assertEqual(len(afectados), 1)
        self.assertEqual(afectados[0]["producto_id"], 228)
        self.assertEqual(afectados[0]["stock_actual"], 10)
        self.assertEqual(afectados[0]["faltante"], 1)

    def test_stock_cero_real_se_muestra_como_cero(self):
        with patch.object(visor, "obtener_producto_por_id", return_value=_producto(228, 0)):
            afectados = visor._stock_afectado_items_ui([_linea(cantidad=1)])
        self.assertEqual(afectados[0]["stock_actual"], 0)
        self.assertEqual(afectados[0]["estado"], "STOCK NULO")

    def test_existencia_es_alias_valido_sin_convertir_ausencia_en_cero(self):
        producto = _producto(228)
        producto.pop("stock")
        producto["existencia"] = 180
        with patch.object(visor, "obtener_producto_por_id", return_value=producto):
            self.assertEqual(visor._stock_afectado_items_ui([_linea(cantidad=20)]), [])

    def test_none_y_error_api_bloquean_sin_afirmar_stock_cero(self):
        with patch.object(visor, "obtener_producto_por_id", return_value=None):
            with self.assertRaises(visor.InventarioNoComprobadoError):
                visor._stock_afectado_items_ui([_linea()])
        with patch.object(visor, "obtener_producto_por_id", side_effect=RuntimeError("sin red")):
            with self.assertRaisesRegex(visor.InventarioNoComprobadoError, "No fue posible consultar"):
                visor._stock_afectado_items_ui([_linea()])

    def test_producto_id_distingue_dos_blancos_y_nombres_iguales(self):
        productos = {
            228: _producto(228, 180),
            34: _producto(34, 5, codigo="55", marca="ALIZE", hilo="VELLUTO"),
        }
        consultados = []

        def obtener(producto_id):
            consultados.append(producto_id)
            return productos[producto_id]

        lineas = [
            _linea(228, 1),
            _linea(34, 6, codigo="55", marca="ALIZE", hilo="VELLUTO"),
        ]
        with patch.object(visor, "obtener_producto_por_id", side_effect=obtener):
            afectados = visor._stock_afectado_items_ui(lineas)
        self.assertEqual(consultados, [228, 34])
        self.assertEqual([p["producto_id"] for p in afectados], [34])

    def test_registro_inactivo_en_cero_no_sustituye_al_activo_con_180(self):
        activo = _producto(228, 180)
        inactivo = _producto(999, 0, estado="INACTIVO", tipo_producto="INACTIVO")
        productos = {228: activo, 999: inactivo}
        with patch.object(visor, "obtener_producto_por_id", side_effect=lambda producto_id: productos[producto_id]) as obtener:
            self.assertEqual(visor._stock_afectado_items_ui([_linea(228, 20)]), [])
        obtener.assert_called_once_with(228)

    def test_dos_lineas_del_mismo_producto_se_suman_antes_de_comparar(self):
        with patch.object(visor, "obtener_producto_por_id", return_value=_producto(228, 10)) as obtener:
            afectados = visor._stock_afectado_items_ui([_linea(cantidad=6), _linea(cantidad=5)])
        obtener.assert_called_once_with(228)
        self.assertEqual(afectados[0]["cantidad_solicitada"], 11)
        self.assertEqual(afectados[0]["faltante"], 1)

    def test_linea_sin_producto_id_no_busca_por_codigo(self):
        with self.assertRaisesRegex(visor.InventarioNoComprobadoError, "no tiene producto_id"):
            visor._stock_afectado_items_ui([_linea(producto_id=None)])

    def test_error_permite_reintentar_y_cancelar(self):
        error = visor.InventarioNoComprobadoError("consulta temporal")
        with patch.object(visor, "_stock_afectado_items_ui", side_effect=[error, []]) as validar:
            with patch.object(visor.messagebox, "askretrycancel", return_value=True):
                self.assertEqual(visor._pedir_autorizacion_stock_si_necesaria(None, [_linea()]), (True, None, []))
        self.assertEqual(validar.call_count, 2)

        with patch.object(visor, "_stock_afectado_items_ui", side_effect=error):
            with patch.object(visor.messagebox, "askretrycancel", return_value=False):
                self.assertEqual(visor._pedir_autorizacion_stock_si_necesaria(None, [_linea()]), (False, None, []))

    def test_cancelar_autorizacion_detiene_flujo(self):
        afectado = [{"producto_id": 228, "stock_actual": 10, "faltante": 1}]
        with patch.object(visor, "_stock_afectado_items_ui", return_value=afectado):
            with patch.object(visor, "pedir_autorizacion_stock", return_value=False):
                self.assertEqual(
                    visor._pedir_autorizacion_stock_si_necesaria(None, [_linea(cantidad=11)]),
                    (False, None, afectado),
                )


class StockAutorizacionBackendTests(unittest.TestCase):
    def test_producto_id_gana_sobre_codigo_duplicado(self):
        conn = _Conexion([
            _producto(280, 0, marca="HILORAMA", hilo="ALFILER", color="CHICO"),
            _producto(228, 180),
        ])
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            producto = backend._buscar_producto_item_api(conn, _linea(228), bloquear=False)
        self.assertEqual(producto["id"], 228)
        self.assertEqual(producto["stock"], 180)

    def test_legacy_solo_resuelve_coincidencia_compuesta_unica(self):
        conn = _Conexion([
            _producto(280, 0, marca="HILORAMA", hilo="ALFILER", color="CHICO"),
            _producto(228, 180),
        ])
        item = _linea(producto_id=None)
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            producto = backend._buscar_producto_item_api(conn, item, bloquear=False)
        self.assertEqual(producto["id"], 228)

    def test_legacy_ambiguo_o_sin_identidad_se_bloquea(self):
        duplicado = _producto(229, 180)
        conn = _Conexion([_producto(228, 180), duplicado])
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            with self.assertRaises(backend.InventarioNoComprobadoError):
                backend._buscar_producto_item_api(conn, _linea(producto_id=None), bloquear=False)
            with self.assertRaises(backend.InventarioNoComprobadoError):
                backend._buscar_producto_item_api(
                    conn,
                    {"producto_id": None, "codigo": "1", "marca": "", "hilo": ""},
                    bloquear=False,
                )

    def test_comprobacion_agrupa_y_solo_hace_select(self):
        conn = _Conexion([_producto(228, 180)], [_linea(228, 1), _linea(228, 20)])
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            with patch.object(backend, "_resolver_nota_api", return_value=("COT-TEST", {})):
                lineas, afectados = backend._items_stock_nota_api(conn, "COT-TEST", bloquear=False)
        self.assertEqual(len(lineas), 1)
        self.assertEqual(lineas[0][0]["cantidad"], 21)
        self.assertEqual(afectados, [])
        sql = " ".join(query.upper() for query, _ in conn.calls)
        for escritura in ("UPDATE ", "INSERT ", "DELETE "):
            self.assertNotIn(escritura, sql)

    def test_stock_ausente_no_se_convierte_en_cero(self):
        producto = _producto(228, 180)
        producto.pop("stock")
        conn = _Conexion([producto], [_linea(228, 1)])
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            with patch.object(backend, "_resolver_nota_api", return_value=("COT-TEST", {})):
                with self.assertRaises(backend.InventarioNoComprobadoError):
                    backend._items_stock_nota_api(conn, "COT-TEST", bloquear=False)

    def test_producto_id_se_normaliza_y_se_inserta_en_items(self):
        item = backend._normalizar_item_payload_api(_linea(228, 1))
        conn = _Conexion([_producto(228, 180)])
        with patch.object(backend, "_columnas_tabla_api", side_effect=_columnas):
            backend._insertar_items_nota_api(conn, "COT-TEST", [item])
        insert_sql, params = conn.calls[-1]
        self.assertIn("producto_id", insert_sql)
        self.assertIn(228, params)

    def test_validacion_ocurre_antes_del_unico_descuento(self):
        source = inspect.getsource(backend._descontar_stock_nota_api)
        self.assertLess(source.index("_items_stock_nota_api"), source.index("_cambiar_stock_con_movimiento_api"))
        self.assertEqual(source.count("_cambiar_stock_con_movimiento_api("), 1)

    def test_carrito_y_detalle_conservan_producto_id(self):
        ventas = (ROOT / "main_ventas.py").read_text(encoding="utf-8")
        backend_source = (ROOT / "hilorama_backend" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"producto_id": producto_id', ventas)
        self.assertIn("{producto_id_expr} AS producto_id", backend_source)


if __name__ == "__main__":
    unittest.main()
