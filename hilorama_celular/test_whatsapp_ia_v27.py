import unittest

from hilorama_celular.whatsapp_ia_v27 import procesar_conversacion_v27


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
    prod(3, "60", "VELLUTO", "Negro", 12, 65),
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


def run(texto, memoria=None, callbacks=None):
    return procesar_conversacion_v27(
        {"texto": texto},
        PRODUCTOS,
        memoria=memoria or {},
        callbacks=callbacks or {},
    )


def pedidos_por_codigo(resultado):
    return {str(p.get("codigo")): p for p in resultado["resolucion"].get("pedidos", [])}


class WhatsAppIAV27Tests(unittest.TestCase):
    def test_pedido_combinado_normaliza_y_respeta_cantidades(self):
        resultado = run(
            "buenas trades quiero cotizar un pwdido de belluto, "
            "son 15 madejas, 5 del 55 y 10 del 60"
        )
        pedidos = pedidos_por_codigo(resultado)

        self.assertEqual(resultado["normalizado"]["texto"].split(",")[0], "buenas tardes quiero cotizar un pedido de velluto")
        self.assertEqual(resultado["intencion"]["principal"], "pedido_lista")
        self.assertEqual(resultado["contexto"]["hilo_actual"], "VELLUTO")
        self.assertEqual(pedidos["55"]["cantidad"], 5)
        self.assertEqual(pedidos["60"]["cantidad"], 10)
        self.assertEqual(sum(p["cantidad"] for p in pedidos.values()), 15)
        self.assertFalse(resultado["resolucion"]["preguntas"])
        self.assertFalse(resultado["resolucion"]["errores"])
        self.assertNotIn("confianza", resultado["respuesta"].lower())
        self.assertNotIn("parser", resultado["respuesta"].lower())

    def test_memoria_resuelve_pedido_en_dos_mensajes(self):
        primero = run("quiero cotizar un pedido de velluto")
        segundo = run("5 del 55 y 10 del 60", memoria=primero["memoria"])
        pedidos = pedidos_por_codigo(segundo)

        self.assertEqual(primero["memoria"]["hilo_actual"], "VELLUTO")
        self.assertEqual(segundo["contexto"]["origen_contexto"], "memoria")
        self.assertEqual(pedidos["55"]["cantidad"], 5)
        self.assertEqual(pedidos["60"]["cantidad"], 10)
        self.assertFalse(segundo["resolucion"]["preguntas"])

    def test_lista_pendiente_se_resuelve_con_confirmacion_todo_velluto(self):
        lista = """me puede poner esta lista
550 x2
493
216 canario - 4
Blanco 01- 2
Rojo escolar- 2
Hueso 26- 1"""
        primero = run(lista)
        segundo = run("todo seria velluto", memoria=primero["memoria"])
        pedidos = pedidos_por_codigo(segundo)

        self.assertTrue(primero["memoria"].get("ultima_lista_pendiente"))
        self.assertEqual(segundo["contexto"]["hilo_actual"], "VELLUTO")
        self.assertEqual(pedidos["550"]["cantidad"], 2)
        self.assertEqual(pedidos["493"]["cantidad"], 1)
        self.assertEqual(pedidos["216"]["cantidad"], 4)
        self.assertEqual(pedidos["55"]["cantidad"], 2)
        self.assertEqual(pedidos["56"]["cantidad"], 2)
        self.assertEqual(pedidos["26"]["cantidad"], 1)
        self.assertFalse(segundo["resolucion"]["preguntas"])
        self.assertFalse(segundo["resolucion"]["errores"])

    def test_codigos_puros_usan_contexto_velluto(self):
        texto = "60\n310\n107\n329\n466\n26\n87\n428\n13\n31"
        resultado = run(texto, memoria={"hilo_actual": "VELLUTO", "marca_actual": "ALIZE"})
        pedidos = resultado["resolucion"]["pedidos"]

        self.assertEqual(len(pedidos), 10)
        self.assertTrue(all(p["hilo"] == "VELLUTO" for p in pedidos))
        self.assertTrue(all(p["cantidad"] == 1 for p in pedidos))

    def test_komfy_mini_stock_excluye_agotados(self):
        resultado = run("que colores tiene de Komfy Mini disponibles?")
        respuesta = resultado["respuesta"]

        self.assertEqual(resultado["intencion"]["principal"], "consulta_stock")
        self.assertIn("01 Blanco", respuesta)
        self.assertIn("06 Cielo", respuesta)
        self.assertIn("14 Rosa Bebe", respuesta)
        self.assertNotIn("08 Turquesa", respuesta)

    def test_gama_usa_callback_de_recursos(self):
        def recurso_cb(intencion, normalizado, contexto, extraccion):
            return {"respuesta": "Claro, le comparto la gama Velluto\n/gama-velluto.png"}

        resultado = run("me manda la gama de Velluto?", callbacks={"buscar_recurso": recurso_cb})

        self.assertEqual(resultado["intencion"]["principal"], "pide_gama")
        self.assertIn("/gama-velluto.png", resultado["respuesta"])
        self.assertFalse(resultado["resolucion"]["pedidos"])

    def test_foto_de_tono_usa_callback_y_no_agrega_producto(self):
        def recurso_cb(intencion, normalizado, contexto, extraccion):
            return {"respuesta": "Claro, le comparto la foto del tono 429\n/429.webp"}

        resultado = run("me muestra foto del 429?", callbacks={"buscar_recurso": recurso_cb})

        self.assertEqual(resultado["intencion"]["principal"], "pide_foto_tono")
        self.assertIn("429.webp", resultado["respuesta"])
        self.assertFalse(resultado["resolucion"]["pedidos"])

    def test_envio_sin_cp_pide_codigo_postal(self):
        resultado = run("cuanto sale el envio?")

        self.assertEqual(resultado["intencion"]["principal"], "envio")
        self.assertIn("codigo postal", resultado["respuesta"].lower())

    def test_cp_usa_callback_de_cotizacion(self):
        resultado = run(
            "78174",
            memoria={"estado_actual": "esperando_cp", "datos_envio_pendientes": True},
            callbacks={"cotizar_envio": lambda cp, contexto: {"respuesta": f"Envio seguro para CP {cp}"}},
        )

        self.assertEqual(resultado["intencion"]["principal"], "cp_envio")
        self.assertIn("78174", resultado["respuesta"])

    def test_pago_pide_comprobante_y_nunca_autoenvia(self):
        resultado = run("ya quedo el pago")

        self.assertEqual(resultado["intencion"]["principal"], "comprobante")
        self.assertIn("comprobante", resultado["respuesta"].lower())
        self.assertFalse(resultado["confianza"]["puede_auto_enviar"])

    def test_producto_no_manejado_sugiere_alternativas_reales(self):
        resultado = run("manejan La Abuelita?")

        self.assertEqual(resultado["intencion"]["principal"], "producto_no_manejado")
        self.assertIn("por el momento no la manejamos", resultado["respuesta"])
        self.assertIn("Kurumi", resultado["respuesta"])
        self.assertIn("Komfy Mini", resultado["respuesta"])

    def test_color_ambiguo_con_contexto_sale_del_almacen(self):
        resultado = run(
            "azul cielo",
            memoria={"hilo_actual": "VELLUTO", "marca_actual": "ALIZE", "estado_actual": "esperando_lista_de_colores"},
        )
        pedidos = pedidos_por_codigo(resultado)

        self.assertIn("87", pedidos)
        self.assertEqual(pedidos["87"]["color"], "Azul")
        self.assertIn("Cuantas piezas", resultado["respuesta"])
        self.assertNotIn("azul cielo x", resultado["respuesta"].lower())


if __name__ == "__main__":
    unittest.main()
