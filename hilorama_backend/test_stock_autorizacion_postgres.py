"""Integracion opt-in de autorizacion de stock contra PostgreSQL efimero.

La prueba ignora ``DATABASE_URL`` como entrada. Solo acepta una base local,
vacia y desechable mediante ``HILORAMA_STOCK_AUTORIZACION_TEST_DATABASE_URL``.
"""

from __future__ import annotations

from ipaddress import ip_interface
import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_URL_ENV = "HILORAMA_STOCK_AUTORIZACION_TEST_DATABASE_URL"


SCHEMA_SQL = """
CREATE TABLE productos (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL,
    codigo_barras TEXT,
    marca TEXT NOT NULL,
    hilo TEXT NOT NULL,
    color TEXT,
    descripcion TEXT,
    stock INTEGER,
    estado TEXT NOT NULL DEFAULT 'OK',
    precio NUMERIC NOT NULL DEFAULT 0,
    costo_neto NUMERIC NOT NULL DEFAULT 0,
    volumetrico NUMERIC NOT NULL DEFAULT 1,
    tipo_producto TEXT NOT NULL DEFAULT 'INVENTARIO',
    es_inventariable BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    telefono TEXT NOT NULL,
    direccion JSONB NOT NULL
);

CREATE TABLE notas (
    id TEXT PRIMARY KEY,
    cliente_id INTEGER,
    cliente_nombre TEXT,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fecha_pago TIMESTAMPTZ,
    estado TEXT NOT NULL DEFAULT 'COTIZACION',
    total NUMERIC NOT NULL DEFAULT 0,
    envio JSONB,
    pedido TEXT,
    paqueteria TEXT,
    comprobante TEXT,
    observaciones TEXT,
    notas TEXT
);

CREATE TABLE items (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL REFERENCES notas(id) ON DELETE CASCADE,
    producto_id INTEGER REFERENCES productos(id),
    codigo TEXT NOT NULL,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    cantidad NUMERIC NOT NULL,
    empacadas NUMERIC NOT NULL DEFAULT 0,
    precio NUMERIC NOT NULL DEFAULT 0
);

CREATE TABLE pagos (
    id BIGSERIAL PRIMARY KEY,
    nota_id TEXT NOT NULL REFERENCES notas(id),
    comprobante TEXT,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE movimientos_almacen (
    id BIGSERIAL PRIMARY KEY,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    usuario TEXT DEFAULT 'ADMIN',
    tipo TEXT NOT NULL,
    marca TEXT,
    hilo TEXT,
    color TEXT,
    codigo TEXT,
    stock_anterior INTEGER,
    stock_nuevo INTEGER,
    cantidad INTEGER NOT NULL DEFAULT 0,
    campo TEXT,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    motivo TEXT,
    cliente_sistema_id INTEGER,
    producto_id INTEGER,
    referencia_tipo TEXT,
    referencia_id TEXT,
    usuario_id INTEGER,
    device_id TEXT,
    idempotency_key TEXT,
    metadata_json JSONB,
    fecha_creacion TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_stock_autorizacion_movimiento
    ON movimientos_almacen (COALESCE(cliente_sistema_id, 0), idempotency_key)
    WHERE idempotency_key IS NOT NULL;
"""


def _validar_url_prueba(url: str):
    texto = str(url or "").strip()
    if not texto:
        raise RuntimeError(f"Falta {TEST_URL_ENV}; DATABASE_URL no se usa como entrada.")
    parsed = urlparse(texto)
    host = str(parsed.hostname or "").strip().lower()
    database = str(parsed.path or "").lstrip("/").strip().lower()
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("La integracion requiere una URL PostgreSQL.")
    try:
        loopback = host == "localhost" or ip_interface(host).ip.is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise RuntimeError("Destino remoto rechazado; solo se permite loopback.")
    if parsed.password:
        raise RuntimeError("La base efimera no debe usar ni transportar una contrasena.")
    if "stock_autorizacion" not in database or not database.endswith("_test"):
        raise RuntimeError("La base debe contener stock_autorizacion y terminar en _test.")
    if database in {"postgres", "hilorama", "template0", "template1"} or "prod" in database:
        raise RuntimeError("Nombre de base de produccion o sistema rechazado.")
    if any(valor in texto.lower() for valor in ("render", "onrender", "amazonaws", "neon", "supabase")):
        raise RuntimeError("URL administrada o remota rechazada.")
    return parsed


def _producto(producto_id, stock, *, marca, hilo, color, codigo="1", descripcion=None):
    return (
        producto_id,
        codigo,
        f"TEST-{producto_id}",
        marca,
        hilo,
        color,
        descripcion or color,
        stock,
        "OK" if stock > 0 else "SIN STOCK",
        80,
        35,
        1,
        "INVENTARIO",
        True,
    )


def _item(producto_id=228, cantidad=2, **cambios):
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


def _huella(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COALESCE(SUM(stock), 0) FROM productos) AS stock_agregado,
                (SELECT COUNT(*) FROM movimientos_almacen) AS movimientos,
                (SELECT COUNT(*) FROM pagos) AS pagos,
                (SELECT COUNT(*) FROM notas) AS notas,
                (SELECT COUNT(*) FROM items) AS items
            """
        )
        stock, movimientos, pagos, notas, items = cur.fetchone()
    return {
        "stock_agregado": int(stock),
        "movimientos": int(movimientos),
        "pagos": int(pagos),
        "notas": int(notas),
        "items": int(items),
    }


def _sembrar_datos(conn):
    from psycopg2.extras import Json, execute_values

    productos = [
        _producto(228, 175, marca="KARINA", hilo="KOMFY MINI", color="BLANCO"),
        _producto(280, 0, marca="HILORAMA", hilo="ALFILER", color="CHICO", descripcion="CHICO"),
        _producto(281, 21, marca="KARINA", hilo="DUPLICADO 1", color="ROJO"),
        _producto(282, 22, marca="KARINA", hilo="DUPLICADO 2", color="AZUL"),
        _producto(283, 23, marca="KARINA", hilo="DUPLICADO 3", color="VERDE"),
        _producto(284, 24, marca="KARINA", hilo="DUPLICADO 4", color="NEGRO"),
        _producto(285, 25, marca="KARINA", hilo="DUPLICADO 5", color="AMARILLO"),
        _producto(286, 26, marca="KARINA", hilo="DUPLICADO 6", color="GRIS"),
        _producto(287, 0, marca="KARINA", hilo="KOMFY MINI", color="BLANCO"),
        _producto(500, 80, marca="KARINA", hilo="HISTORICO", color="UNICO", codigo="HIST-UNICO"),
        _producto(600, 0, marca="KARINA", hilo="SIN STOCK", color="CERO", codigo="ZERO"),
    ]
    notas = [
        ("VAL-175", "COTIZACION"),
        ("VAL-176", "COTIZACION"),
        ("VAL-CERO", "COTIZACION"),
        ("VAL-DOS-LINEAS", "COTIZACION"),
        ("VAL-DOS-BLANCOS", "COTIZACION"),
        ("HIST-UNICA", "COTIZACION"),
        ("HIST-AMBIGUA", "COTIZACION"),
    ]
    items = [
        ("VAL-175", 228, "1", "KARINA", "KOMFY MINI", "BLANCO", 175, 80),
        ("VAL-176", 228, "1", "KARINA", "KOMFY MINI", "BLANCO", 176, 80),
        ("VAL-CERO", 600, "ZERO", "KARINA", "SIN STOCK", "CERO", 1, 80),
        ("VAL-DOS-LINEAS", 228, "1", "KARINA", "KOMFY MINI", "BLANCO", 100, 80),
        ("VAL-DOS-LINEAS", 228, "1", "KARINA", "KOMFY MINI", "BLANCO", 76, 80),
        ("VAL-DOS-BLANCOS", 228, "1", "KARINA", "KOMFY MINI", "BLANCO", 1, 80),
        ("VAL-DOS-BLANCOS", 287, "1", "KARINA", "KOMFY MINI", "BLANCO", 1, 80),
        ("HIST-UNICA", None, "HIST-UNICO", "KARINA", "HISTORICO", "UNICO", 1, 80),
        ("HIST-AMBIGUA", None, "1", "KARINA", "KOMFY MINI", "BLANCO", 1, 80),
    ]
    direccion = {
        "calle": "CALLE FICTICIA",
        "numero_ext": "1",
        "colonia": "PRUEBAS",
        "codigo_postal": "00000",
        "estado": "PRUEBA",
        "municipio": "PRUEBA",
    }
    with conn.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO productos(
                   id,codigo,codigo_barras,marca,hilo,color,descripcion,stock,estado,
                   precio,costo_neto,volumetrico,tipo_producto,es_inventariable
               ) VALUES %s""",
            productos,
        )
        cur.execute(
            "INSERT INTO clientes(id,nombre,telefono,direccion) VALUES (1,%s,%s,%s)",
            ("CLIENTA FICTICIA", "0000000000", Json(direccion)),
        )
        execute_values(
            cur,
            "INSERT INTO notas(id,cliente_id,cliente_nombre,estado,envio) VALUES %s",
            [(nota_id, 1, "CLIENTA FICTICIA", estado, Json({"tipo": "PAQUETERIA", "precio": 0})) for nota_id, estado in notas],
        )
        execute_values(
            cur,
            """INSERT INTO items(
                   nota_id,producto_id,codigo,marca,hilo,color,cantidad,precio
               ) VALUES %s""",
            items,
        )
    conn.commit()


class StockAutorizacionPostgresTests(unittest.TestCase):
    def test_flujo_real_producto_id_y_descuento_idempotente(self):
        url = os.environ.get(TEST_URL_ENV, "")
        info = _validar_url_prueba(url)
        for destino_remoto in (
            "postgresql://usuario@192.168.1.10:5432/stock_autorizacion_test",
            "postgresql://usuario@10.0.0.5:5432/stock_autorizacion_test",
            "postgresql://usuario@db.example.com:5432/stock_autorizacion_test",
            "postgresql://usuario@servicio.onrender.com:5432/stock_autorizacion_test",
        ):
            with self.assertRaises(RuntimeError):
                _validar_url_prueba(destino_remoto)

        import psycopg2

        conn = psycopg2.connect(url)
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port()")
            database, _usuario, host_real, puerto_real = cur.fetchone()
            self.assertEqual(str(database).lower(), str(info.path).lstrip("/").lower())
            self.assertTrue(ip_interface(str(host_real)).ip.is_loopback)
            self.assertEqual(int(puerto_real), int(info.port))
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
            self.assertEqual(cur.fetchone()[0], 0, "La base efimera no empezo vacia.")
            cur.execute(SCHEMA_SQL)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """SELECT data_type FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='items' AND column_name='producto_id'"""
            )
            columna = cur.fetchone()
        self.assertEqual(columna, ("integer",), "El esquema no soporta items.producto_id; no se aplico ALTER automatico.")
        _sembrar_datos(conn)

        os.environ.pop("DATABASE_URL", None)
        os.environ["DATABASE_URL"] = url
        os.environ["HILORAMA_DATA_MODE"] = "local"
        db_connection = importlib.import_module("database.connection")
        if db_connection._pool is not None:
            db_connection._pool.closeall()
            db_connection._pool = None
        backend = importlib.import_module("hilorama_backend.app")
        visor = importlib.import_module("ver_cotizaciones")
        backend.app.config.update(TESTING=True)
        client = backend.app.test_client()
        auth = {"usuario_id": 900, "cliente_id": 901, "rol": "super_admin", "usuario": "PRUEBA"}

        def producto_api(producto_id):
            respuesta = client.get(f"/api/productos/{producto_id}")
            self.assertEqual(respuesta.status_code, 200, respuesta.get_json())
            return respuesta.get_json()["producto"]

        try:
            huella_lecturas_antes = _huella(conn)
            with patch.object(backend, "_require_license_api", return_value=(auth, None)):
                with backend.get_conn() as api_conn:
                    lineas, afectados = backend._items_stock_nota_api(api_conn, "VAL-175", bloquear=False)
                    self.assertEqual(afectados, [])
                    self.assertEqual(lineas[0][1]["id"], 228)

                    _, afectados = backend._items_stock_nota_api(api_conn, "VAL-176", bloquear=False)
                    self.assertEqual([(p["producto_id"], p["stock_actual"], p["faltante"]) for p in afectados], [(228, 175, 1)])

                    _, afectados = backend._items_stock_nota_api(api_conn, "VAL-CERO", bloquear=False)
                    self.assertEqual([(p["producto_id"], p["stock_actual"]) for p in afectados], [(600, 0)])

                    lineas, afectados = backend._items_stock_nota_api(api_conn, "VAL-DOS-LINEAS", bloquear=False)
                    self.assertEqual(len(lineas), 1)
                    self.assertEqual(int(lineas[0][0]["cantidad"]), 176)
                    self.assertEqual(afectados[0]["producto_id"], 228)

                    lineas, afectados = backend._items_stock_nota_api(api_conn, "VAL-DOS-BLANCOS", bloquear=False)
                    self.assertEqual({linea[1]["id"] for linea in lineas}, {228, 287})
                    self.assertEqual([p["producto_id"] for p in afectados], [287])

                    lineas, afectados = backend._items_stock_nota_api(api_conn, "HIST-UNICA", bloquear=False)
                    self.assertEqual(lineas[0][1]["id"], 500)
                    self.assertEqual(afectados, [])

                    with self.assertRaises(backend.InventarioNoComprobadoError):
                        backend._items_stock_nota_api(api_conn, "HIST-AMBIGUA", bloquear=False)
                    with self.assertRaisesRegex(backend.InventarioNoComprobadoError, "No se encontro"):
                        backend._buscar_producto_item_api(api_conn, _item(producto_id=999999), bloquear=False)
                    with self.assertRaisesRegex(backend.InventarioNoComprobadoError, "no coincide"):
                        backend._buscar_producto_item_api(
                            api_conn,
                            _item(producto_id=228, marca="HILORAMA", hilo="ALFILER"),
                            bloquear=False,
                        )

                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM productos WHERE codigo='1'")
                    self.assertEqual(cur.fetchone()[0], 9)

                with patch.object(visor, "obtener_producto_por_id", side_effect=producto_api):
                    self.assertEqual(visor._stock_afectado_items_ui([_item(cantidad=2)]), [])
                    self.assertEqual(visor._stock_afectado_items_ui([_item(cantidad=175)]), [])
                    afectados = visor._stock_afectado_items_ui([_item(cantidad=176)])
                    self.assertEqual((afectados[0]["producto_id"], afectados[0]["stock_actual"]), (228, 175))
                    afectados = visor._stock_afectado_items_ui([_item(cantidad=100), _item(cantidad=76)])
                    self.assertEqual((afectados[0]["cantidad_solicitada"], afectados[0]["faltante"]), (176, 1))
                with patch.object(visor, "obtener_producto_por_id", side_effect=producto_api), patch.object(
                    visor,
                    "pedir_autorizacion_stock",
                    return_value=True,
                ) as dialogo, patch.object(visor, "get_admin_override_key", return_value="CLAVE-TEST"):
                    permitido, _clave, afectados_dialogo = visor._pedir_autorizacion_stock_si_necesaria(
                        None,
                        [_item(cantidad=176)],
                    )
                self.assertTrue(permitido)
                self.assertEqual(afectados_dialogo[0]["producto_id"], 228)
                self.assertEqual(dialogo.call_args.args[1][0]["producto_id"], 228)

                with patch.object(visor, "obtener_producto_por_id", side_effect=RuntimeError("API no disponible")):
                    with self.assertRaises(visor.InventarioNoComprobadoError):
                        visor._stock_afectado_items_ui([_item()])
                with patch.object(visor, "obtener_producto_por_id", return_value=None):
                    with self.assertRaises(visor.InventarioNoComprobadoError):
                        visor._stock_afectado_items_ui([_item()])
                producto_sin_stock = producto_api(228)
                producto_sin_stock.pop("stock", None)
                with patch.object(visor, "obtener_producto_por_id", return_value=producto_sin_stock):
                    with self.assertRaises(visor.InventarioNoComprobadoError):
                        visor._stock_afectado_items_ui([_item()])

                with patch.object(
                    visor,
                    "obtener_producto_por_id",
                    side_effect=[RuntimeError("temporal"), producto_api(228)],
                ), patch.object(visor.messagebox, "askretrycancel", return_value=True):
                    self.assertEqual(visor._pedir_autorizacion_stock_si_necesaria(None, [_item()]), (True, None, []))
                with patch.object(visor, "obtener_producto_por_id", side_effect=RuntimeError("temporal")), patch.object(
                    visor.messagebox,
                    "askretrycancel",
                    return_value=False,
                ):
                    self.assertEqual(visor._pedir_autorizacion_stock_si_necesaria(None, [_item()]), (False, None, []))

                self.assertEqual(_huella(conn), huella_lecturas_antes)

                crear = client.post(
                    "/api/notas",
                    json={
                        "cliente_id": 1,
                        "cliente_nombre": "CLIENTA FICTICIA",
                        "estado": "COTIZACION",
                        "envio": {"tipo": "PAQUETERIA", "precio": 0},
                        "items": [_item(cantidad=2)],
                    },
                )
                self.assertEqual(crear.status_code, 201, crear.get_json())
                nota_id = crear.get_json()["nota"]["id"]

                detalle = client.get(f"/api/notas/{nota_id}/items")
                self.assertEqual(detalle.status_code, 200, detalle.get_json())
                item_guardado = detalle.get_json()["items"][0]
                self.assertEqual(item_guardado["producto_id"], 228)
                self.assertEqual(item_guardado["marca"], "KARINA")
                self.assertEqual(item_guardado["hilo"], "KOMFY MINI")

                huella_nota_creada = _huella(conn)
                self.assertEqual(huella_nota_creada["stock_agregado"], huella_lecturas_antes["stock_agregado"])
                self.assertEqual(huella_nota_creada["movimientos"], huella_lecturas_antes["movimientos"])
                self.assertEqual(huella_nota_creada["pagos"], huella_lecturas_antes["pagos"])
                with patch.object(visor, "obtener_producto_por_id", side_effect=producto_api):
                    self.assertEqual(visor._stock_afectado_items_ui(detalle.get_json()["items"]), [])
                self.assertEqual(_huella(conn), huella_nota_creada)

                convertir = client.post(
                    f"/api/notas/{nota_id}/convertir-a-venta",
                    json={"envio": {"tipo": "PAQUETERIA", "precio": 0}},
                )
                self.assertEqual(convertir.status_code, 200, convertir.get_json())
                huella_convertida = _huella(conn)
                self.assertEqual(huella_convertida["stock_agregado"], huella_nota_creada["stock_agregado"])
                self.assertEqual(huella_convertida["movimientos"], huella_nota_creada["movimientos"])

                pagar = client.post(
                    "/api/pagos",
                    json={"nota_id": nota_id, "comprobante": "comprobantes/PRUEBA-FICTICIA.png"},
                )
                self.assertEqual(pagar.status_code, 200, pagar.get_json())
                self.assertFalse(pagar.get_json()["idempotente"])
                huella_pagada = _huella(conn)
                self.assertEqual(huella_pagada["stock_agregado"], huella_convertida["stock_agregado"] - 2)
                self.assertEqual(huella_pagada["movimientos"], huella_convertida["movimientos"] + 1)
                self.assertEqual(huella_pagada["pagos"], huella_convertida["pagos"] + 1)

                with conn.cursor() as cur:
                    cur.execute("SELECT stock FROM productos WHERE id=228")
                    self.assertEqual(cur.fetchone()[0], 173)
                    cur.execute(
                        """SELECT producto_id,cantidad,stock_anterior,stock_nuevo,tipo
                           FROM movimientos_almacen WHERE referencia_id=%s""",
                        (nota_id,),
                    )
                    self.assertEqual(cur.fetchall(), [(228, -2, 175, 173, "VENTA")])

                pago_repetido = client.post(
                    "/api/pagos",
                    json={"nota_id": nota_id, "comprobante": "comprobantes/PRUEBA-FICTICIA.png"},
                )
                self.assertEqual(pago_repetido.status_code, 200, pago_repetido.get_json())
                self.assertTrue(pago_repetido.get_json()["idempotente"])
                detalle_repetido = client.get(f"/api/notas/{nota_id}/items")
                self.assertEqual(detalle_repetido.status_code, 200, detalle_repetido.get_json())
                self.assertEqual(detalle_repetido.get_json()["items"][0]["producto_id"], 228)
                self.assertEqual(_huella(conn), huella_pagada)
                print(
                    "STOCK_AUTORIZACION_POSTGRES_OK "
                    + json.dumps(
                        {
                            "database": str(info.path).lstrip("/"),
                            "loopback": True,
                            "productos_codigo_1": 9,
                            "producto_id": 228,
                            "stock_validado": 175,
                            "stock_final": 173,
                            "movimientos_venta": 1,
                            "pago_idempotente": True,
                            "huella_lecturas": huella_lecturas_antes,
                            "huella_final": huella_pagada,
                        },
                        sort_keys=True,
                    )
                )
        finally:
            if db_connection._pool is not None:
                db_connection._pool.closeall()
                db_connection._pool = None
            os.environ.pop("DATABASE_URL", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
