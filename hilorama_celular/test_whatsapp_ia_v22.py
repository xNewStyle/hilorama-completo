import unittest
import sys
import types


if "psycopg2" not in sys.modules:
    psycopg2_stub = types.ModuleType("psycopg2")
    pool_stub = types.ModuleType("psycopg2.pool")
    extras_stub = types.ModuleType("psycopg2.extras")

    class SimpleConnectionPool:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("DB no disponible en pruebas unitarias aisladas")

    pool_stub.SimpleConnectionPool = SimpleConnectionPool
    extras_stub.RealDictCursor = object
    psycopg2_stub.pool = pool_stub
    psycopg2_stub.extras = extras_stub
    sys.modules["psycopg2"] = psycopg2_stub
    sys.modules["psycopg2.pool"] = pool_stub
    sys.modules["psycopg2.extras"] = extras_stub

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")

    class _JsonResponse:
        def __init__(self, data):
            self._data = data

        def get_json(self):
            return self._data

    class Flask:
        def __init__(self, *args, **kwargs):
            self.view_functions = {}

        def route(self, *args, **kwargs):
            def deco(func):
                endpoint = kwargs.get("endpoint") or func.__name__
                self.view_functions[endpoint] = func
                return func
            return deco

        def errorhandler(self, *args, **kwargs):
            def deco(func):
                return func
            return deco

        def before_request(self, *args, **kwargs):
            def deco(func):
                return func
            return deco

        def test_request_context(self, *args, **kwargs):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False
            return _Ctx()

    class _Request:
        path = ""
        args = {}

        @staticmethod
        def get_json(*args, **kwargs):
            return {}

    flask_stub.Flask = Flask
    flask_stub.request = _Request()
    flask_stub.jsonify = lambda data=None, *args, **kwargs: _JsonResponse(data)
    flask_stub.send_from_directory = lambda *args, **kwargs: None
    flask_stub.send_file = lambda *args, **kwargs: None
    sys.modules["flask"] = flask_stub

if "flask_cors" not in sys.modules:
    cors_stub = types.ModuleType("flask_cors")
    cors_stub.CORS = lambda *args, **kwargs: None
    sys.modules["flask_cors"] = cors_stub

import hilorama_celular.app as wa


def prod(pid, codigo, hilo, color, stock=5, precio=65, marca="ALIZE"):
    return {
        "id": pid,
        "codigo": codigo,
        "codigo_barras": "",
        "marca": marca,
        "hilo": hilo,
        "color": color,
        "stock": stock,
        "precio_venta": precio,
        "es_inventariable": True,
    }


PRODUCTOS = [
    prod(1, "55", "VELLUTO", "Blanco", 8, 65),
    prod(2, "56", "VELLUTO", "Rojo", 4, 65),
    prod(3, "60", "VELLUTO", "Negro", 2, 65),
    prod(4, "310", "VELLUTO", "Beige", 2, 65),
    prod(5, "107", "VELLUTO", "Rosa", 2, 65),
    prod(6, "329", "VELLUTO", "Mostaza", 2, 65),
    prod(7, "466", "VELLUTO", "Verde", 2, 65),
    prod(8, "26", "VELLUTO", "Hueso", 2, 65),
    prod(9, "87", "VELLUTO", "Azul", 2, 65),
    prod(10, "428", "VELLUTO", "Gris", 2, 65),
    prod(11, "13", "VELLUTO", "Rosa Pastel", 2, 65),
    prod(12, "31", "VELLUTO", "Cafe", 2, 65),
    prod(13, "550", "VELLUTO", "Mandarina", 5, 65),
    prod(14, "493", "VELLUTO", "Cafe Oscuro", 5, 65),
    prod(15, "216", "VELLUTO", "Canario", 5, 65),
    prod(16, "429", "VELLUTO", "Uva", 1, 65),
    prod(17, "01", "KOMFY MINI", "Blanco", 5, 42, "KARINA"),
    prod(18, "06", "KOMFY MINI", "Cielo", 5, 42, "KARINA"),
    prod(19, "08", "KOMFY MINI", "Turquesa", 0, 42, "KARINA"),
    prod(20, "14", "KOMFY MINI", "Rosa Bebe", 3, 42, "KARINA"),
    prod(21, "25", "KURUMI", "Piel", 7, 38, "KARINA"),
]


class WhatsAppIAV22Tests(unittest.TestCase):
    def test_precio_sale_del_almacen(self):
        resp = wa._v6_respuesta_consulta("Cuanto cuesta el Velluto?", PRODUCTOS)
        self.assertIn("$65.00", resp)
        self.assertIn("Velluto", resp)

    def test_gama_usa_biblioteca_ia(self):
        old_buscar = wa._wa_v7_buscar_recurso
        old_resp = wa._wa_v7_respuesta_de_recurso
        old_mem = wa._wa_memoria_productos_min
        try:
            wa._wa_v7_buscar_recurso = lambda texto, categoria=None: {
                "id": 9,
                "categoria": "carta_colores",
                "respuesta": "Claro 😊 le comparto la carta de colores de Velluto.",
                "archivo_url": "/static/recursos_ia/Velluto Carta de Colores/004.png",
            } if categoria == "carta_colores" else None
            wa._wa_v7_respuesta_de_recurso = lambda recurso: recurso["respuesta"] + "\n📎 " + recurso["archivo_url"]
            wa._wa_memoria_productos_min = lambda: PRODUCTOS
            parsed = {"pedidos": [], "preguntas": [], "errores": [], "advertencias": []}
            meta = {"intencion": "pregunta_stock", "confianza": "media", "accion_recomendada": "responder", "puede_auto_enviar": False}
            resp, motor = wa._generar_respuesta_wa_con_openai("Me manda la gama de Velluto?", parsed, meta, {})
            self.assertIn("carta de colores", resp)
            self.assertIn("/static/recursos_ia", resp)
            self.assertIn("biblioteca", motor)
        finally:
            wa._wa_v7_buscar_recurso = old_buscar
            wa._wa_v7_respuesta_de_recurso = old_resp
            wa._wa_memoria_productos_min = old_mem

    def test_foto_tono_exacta(self):
        old_exact = wa._wa_v10_tone_resource_from_code
        old_resp = wa._wa_v7_respuesta_de_recurso
        old_mem = wa._wa_memoria_productos_min
        try:
            wa._wa_v10_tone_resource_from_code = lambda texto: {
                "id": 429,
                "categoria": "foto_tono",
                "respuesta": "Claro 😊 le comparto la foto del tono Velluto 429.",
                "archivo_url": "/static/recursos_ia/Velluto Colores/429.webp",
            }
            wa._wa_v7_respuesta_de_recurso = lambda recurso: recurso["respuesta"] + "\n📎 " + recurso["archivo_url"]
            wa._wa_memoria_productos_min = lambda: PRODUCTOS
            parsed = {"pedidos": [], "preguntas": [], "errores": [], "advertencias": []}
            meta = {"intencion": "pregunta_stock", "confianza": "media", "accion_recomendada": "responder", "puede_auto_enviar": False}
            resp, motor = wa._generar_respuesta_wa_con_openai("Me muestra el tono 429?", parsed, meta, {})
            self.assertIn("429", resp)
            self.assertIn("429.webp", resp)
            self.assertIn("tono", motor)
        finally:
            wa._wa_v10_tone_resource_from_code = old_exact
            wa._wa_v7_respuesta_de_recurso = old_resp
            wa._wa_memoria_productos_min = old_mem

    def test_lista_codigos_puros_con_contexto_velluto(self):
        texto = "60\n310\n107\n329\n466\n26\n87\n428\n13\n31"
        items, es_lista = wa._wa_v17_extraer_items_lista(texto)
        pedidos, preguntas, errores, _advertencias = wa._wa_v17_resolver_items_lista(items, PRODUCTOS, "", "VELLUTO")
        self.assertTrue(es_lista)
        self.assertEqual(len(pedidos), 10)
        self.assertFalse(preguntas)
        self.assertFalse(errores)
        self.assertTrue(all(p["cantidad"] == 1 for p in pedidos))

    def test_lista_mixta_de_pedido(self):
        texto = """me puede poner esta lista 550 x2
493
216 canario - 4
Blanco 01- 2
Rojo escolar- 2
Hueso 26- 1"""
        items, es_lista = wa._wa_v17_extraer_items_lista(texto)
        pedidos, preguntas, errores, _advertencias = wa._wa_v17_resolver_items_lista(items, PRODUCTOS, "", "VELLUTO")
        cantidades = {str(p["codigo"]).lstrip("0"): p["cantidad"] for p in pedidos}
        self.assertTrue(es_lista)
        self.assertEqual(cantidades.get("550"), 2)
        self.assertEqual(cantidades.get("493"), 1)
        self.assertEqual(cantidades.get("216"), 4)
        self.assertEqual(cantidades.get("55"), 2)
        self.assertEqual(cantidades.get("56"), 2)
        self.assertEqual(cantidades.get("26"), 1)
        self.assertFalse(preguntas)
        self.assertFalse(errores)

    def test_confirmacion_todo_velluto_resuelve_lista_anterior(self):
        ok, marca, hilo = wa._wa_v19_es_confirmacion_todo_hilo("todo seria Velluto", PRODUCTOS)
        self.assertTrue(ok)
        self.assertEqual(hilo, "VELLUTO")
        self.assertEqual(marca, "ALIZE")

    def test_colores_disponibles_komfy_mini_salen_de_stock(self):
        resp = wa._v6_respuesta_consulta("Que colores tiene de Komfy Mini disponibles?", PRODUCTOS)
        self.assertIn("01 Blanco", resp)
        self.assertIn("06 Cielo", resp)
        self.assertIn("14 Rosa Bebe", resp)
        self.assertNotIn("08 Turquesa", resp)

    def test_abuelita_no_se_inventa_en_almacen(self):
        resp = wa._v6_respuesta_consulta("Manejan La Abuelita?", PRODUCTOS)
        self.assertIn("por el momento no la manejamos", resp)
        self.assertIn("Kurumi", resp)
        self.assertIn("Komfy Mini", resp)

    def test_cp_responde_envio_si_hay_contexto(self):
        meta = wa._clasificar_intencion_wa("Mi CP es 78174", {"pedidos": [], "preguntas": [], "errores": [], "advertencias": []})
        resp = wa._fallback_respuesta_wa("Mi CP es 78174", {"pedidos": [], "preguntas": [], "errores": []}, meta)
        self.assertEqual(meta["intencion"], "pregunta_envio")
        self.assertIn("78174", resp)
        self.assertTrue("paqueteria" in resp.lower() or "opciones" in resp.lower())

    def test_pago_pide_comprobante_y_revision(self):
        parsed = {"pedidos": [], "preguntas": [], "errores": [], "advertencias": []}
        meta = wa._clasificar_intencion_wa("ya quedo el pago", parsed)
        resp = wa._fallback_respuesta_wa("ya quedo el pago", parsed, meta)
        self.assertEqual(meta["intencion"], "comprobante_pago")
        self.assertFalse(meta["puede_auto_enviar"])
        self.assertIn("comprobante", resp)
        self.assertIn("revision", resp)


if __name__ == "__main__":
    unittest.main()
