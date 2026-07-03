import json
import random
import unittest

from hilorama_celular.whatsapp_ia_v27 import procesar_conversacion_v27


def prod(pid, codigo, hilo, color, stock=200, precio=57.20, marca="ALIZE", volumetrico=1.5):
    return {
        "id": pid,
        "codigo": str(codigo),
        "codigo_barras": "",
        "marca": marca,
        "hilo": hilo,
        "color": color,
        "stock": stock,
        "precio_venta": precio,
        "volumetrico": volumetrico,
        "es_inventariable": True,
    }


VELLUTO = [
    ("55", "Blanco"), ("56", "Rojo"), ("60", "Negro"), ("87", "Azul"),
    ("107", "Rosa"), ("216", "Canario"), ("310", "Beige"), ("329", "Mostaza"),
    ("428", "Gris"), ("429", "Uva"), ("493", "Cafe Oscuro"), ("532", "Lila"),
    ("550", "Mandarina"), ("646", "Verde"), ("798", "Turquesa"), ("993", "Hueso"),
]
KOMFY = [
    ("01", "Blanco"), ("06", "Cielo"), ("08", "Turquesa"), ("14", "Rosa Bebe"),
    ("20", "Negro"), ("25", "Piel"), ("99", "Lila"),
]

PRODUCTOS = []
pid = 1
for code, color in VELLUTO:
    PRODUCTOS.append(prod(pid, code, "VELLUTO", color, stock=220, precio=57.20, marca="ALIZE", volumetrico=1.5))
    pid += 1
for code, color in KOMFY:
    PRODUCTOS.append(prod(pid, code, "KOMFY MINI", color, stock=180, precio=42.00, marca="KARINA", volumetrico=0.8))
    pid += 1
PRODUCTOS.append(prod(pid, "777", "VELLUTO", "Sin Stock", stock=0, precio=57.20, marca="ALIZE", volumetrico=1.5))
pid += 1
PRODUCTOS.append(prod(pid, "999", "VELLUTO", "Muy Poco Stock", stock=2, precio=57.20, marca="ALIZE", volumetrico=1.5))
pid += 1
PRODUCTOS.append(prod(pid, "25", "KURUMI", "Piel", stock=120, precio=38.00, marca="KARINA", volumetrico=1.0))


def _json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _resource_callback(intencion, normalizado, contexto, extraccion):
    principal = (intencion or {}).get("principal") or ""
    secundaria = (intencion or {}).get("secundaria") or ""
    texto = (normalizado or {}).get("texto") or ""
    nums = [x for x in texto.replace("#", " ").split() if x.isdigit()]
    if principal == "pide_foto_tono":
        code = nums[0] if nums else "429"
        return {"respuesta": f"Claro, le comparto la foto del tono {code}\n/static/recursos_ia/Velluto Colores/{code}.webp"}
    if principal == "pide_gama":
        return {"respuesta": "Claro, le comparto la gama Velluto\n/static/recursos_ia/Velluto Carta de Colores/004.png"}
    if secundaria == "ficha_hilo":
        return {"respuesta": "Claro, le comparto la ficha tecnica local\n/static/recursos_ia/repositorio_visual/hilos/KARINA/ALIZE/VELLUTO/ficha/velluto.png"}
    if secundaria in ("foto_accesorio", "accesorio_especifico"):
        return {"respuesta": "Claro, le comparto imagen del accesorio\n/static/recursos_ia/repositorio_visual/accesorios/ganchos/ganchos.png"}
    if principal == "envio":
        return {"respuesta": "Claro, le comparto informacion de envios\n/static/recursos_ia/repositorio_visual/envios/costos/envios.png"}
    if principal == "pago":
        return {"respuesta": "Claro, le comparto datos de pago\n/static/recursos_ia/repositorio_visual/pagos/datos_pago/pago.png"}
    return {}


def _shipping_callback(cp, contexto):
    memoria = (contexto or {}).get("memoria_previa") or {}
    items = _json_list(memoria.get("pedido_en_proceso"))
    puntos = 0.0
    for item in items:
        try:
            cantidad = int(float(item.get("cantidad") or 1))
            puntos += cantidad * float(item.get("volumetrico") or 0)
        except Exception:
            pass
    if puntos <= 0:
        puntos = 10.0
    if puntos > 150:
        return {
            "respuesta": "Claro, este envio pasa a revision por volumen.",
            "requiere_humano": True,
            "tipo_decision": "envio_revision_manual",
            "resumen_para_admin": f"Pedido con {puntos:.1f} puntos volumetricos para CP {cp}.",
            "opciones_sugeridas": ["Revisar tarifa manual", "Dividir envio", "Responder manualmente"],
        }
    kg = 5 if puntos <= 50 else 10 if puntos <= 100 else 15
    extra = " con posible reexpedicion" if str(cp).startswith("99") else ""
    return {
        "respuesta": f"Envio seguro para CP {cp}: tramo {kg} kg volumetricos{extra}.",
        "cotizacion": {"ok": True, "opciones": [{"precio_publico": 180, "nombre": "Paqueteria"}], "peso_volumetrico_kg": kg},
    }


CALLBACKS = {"buscar_recurso": _resource_callback, "cotizar_envio": _shipping_callback}


def _run_conversation(mensajes):
    memoria = {}
    history = []
    for msg in mensajes:
        result = procesar_conversacion_v27(
            {"texto": msg, "tester_mode": True, "dry_run": True},
            PRODUCTOS,
            memoria=memoria,
            callbacks=CALLBACKS,
        )
        history.append(result)
        memoria = result.get("memoria") or memoria
    return history


def _pedidos(result):
    return result.get("resolucion", {}).get("pedidos") or []


def _mem_pedidos(result):
    return _json_list((result.get("memoria") or {}).get("pedido_en_proceso"))


def _assert_base(history):
    for result in history:
        assert result.get("tester_mode") is True, "no_regresa_tester_mode_true"
        assert result.get("dry_run") is True, "no_regresa_dry_run_true"
        assert "apartar" not in (result.get("respuesta") or "").lower(), "lenguaje_apartar"
        assert "http://" not in (result.get("respuesta") or "").lower(), "url_externa_http"
        assert "https://" not in (result.get("respuesta") or "").lower(), "url_externa_https"


def _case(idx, rng):
    code, _ = rng.choice(VELLUTO)
    code2, _ = rng.choice([x for x in VELLUTO if x[0] != code])
    qty = rng.randint(1, 5)
    cp = rng.choice(["64000", "78174", "97000", "99010"])
    kind = idx % 20

    if kind == 0:
        return ("foto_tono", [f"me muestras el {code} de velluto?"], lambda h: (not _pedidos(h[-1])) and "/static/" in h[-1]["respuesta"])
    if kind == 1:
        return ("consulta_tono", [f"que color es {code}?"], lambda h: not _pedidos(h[-1]))
    if kind == 2:
        return ("pedido", [f"ponme {qty} del {code} de velluto"], lambda h: bool(_pedidos(h[-1])) and "Subtotal productos" in h[-1]["respuesta"])
    if kind == 3:
        return ("cotizacion", [f"cotizame {qty} del {code} de velluto"], lambda h: bool(_pedidos(h[-1])))
    if kind == 4:
        n = rng.randint(20, 80)
        rows = []
        for _i in range(n):
            c, _color = rng.choice(VELLUTO)
            rows.append(f"{c} x{rng.randint(1, 3)}")
        return ("lista_larga", ["quiero cotizar un pedido de velluto\n" + "\n".join(rows)], lambda h: len(_pedidos(h[-1])) >= 8)
    if kind == 5:
        kcode, _ = rng.choice(KOMFY)
        return ("marcas_mixtas", [f"velluto {code} x{qty} y komfy {kcode} x2"], lambda h: {"VELLUTO", "KOMFY MINI"}.issubset({p.get("hilo") for p in _pedidos(h[-1])}))
    if kind == 6:
        return ("quitar", [f"ponme 2 del {code} y 1 del {code2} de velluto", f"quitame el {code2}"], lambda h: all(str(p.get("codigo")) != code2 for p in _mem_pedidos(h[-1])))
    if kind == 7:
        return ("sustituir", [f"ponme 2 del {code} de velluto", f"cambia {code} por {code2}"], lambda h: any(str(p.get("codigo")) == code2 for p in _mem_pedidos(h[-1])))
    if kind == 8:
        return ("envio_volumetrico", [f"ponme 34 del {code} de velluto", cp], lambda h: "kg volumetricos" in h[-1]["respuesta"])
    if kind == 9:
        return ("envio_revision", [f"ponme 110 del {code} de velluto", cp], lambda h: h[-1].get("requiere_humano") and h[-1].get("decision_pendiente", {}).get("tipo_decision"))
    if kind == 10:
        return ("stock_insuficiente", ["ponme 10 del 999 de velluto"], lambda h: h[-1].get("requiere_humano") and h[-1]["decision_pendiente"]["tipo_decision"] == "stock_insuficiente")
    if kind == 11:
        return ("sin_stock", ["ponme 1 del 777 de velluto"], lambda h: h[-1].get("requiere_humano"))
    if kind == 12:
        return ("codigo_equivocado", ["ponme 2 del 4444 de velluto"], lambda h: (not _pedidos(h[-1])) and ("confirma" in h[-1]["respuesta"].lower() or h[-1].get("resolucion", {}).get("errores")))
    if kind == 13:
        return ("descuento", [f"si compro {qty + 5} madejas de velluto me mejora el precio?"], lambda h: h[-1].get("requiere_humano") and h[-1]["decision_pendiente"]["tipo_decision"] == "descuento")
    if kind == 14:
        return ("promocion", ["tienen promocion o 2x1 en velluto?"], lambda h: h[-1].get("requiere_humano"))
    if kind == 15:
        return ("pago_sin_comprobante", ["ya pague"], lambda h: h[-1].get("requiere_humano") and h[-1]["decision_pendiente"]["tipo_decision"] == "pago_sin_comprobante")
    if kind == 16:
        return ("queja", ["estoy molesta, si no responden voy a profeco"], lambda h: h[-1].get("requiere_humano") and h[-1]["decision_pendiente"]["tipo_decision"] == "queja_amenaza")
    if kind == 17:
        return ("ficha", ["me mandas la ficha tecnica de velluto?"], lambda h: "/static/" in h[-1]["respuesta"] and not _pedidos(h[-1]))
    if kind == 18:
        return ("recomendacion", ["quiero hacer un amigurumi suave y economico, que hilo me recomiendas?"], lambda h: not _pedidos(h[-1]))
    return ("pregunta_y_compra", [f"foto del {code}", f"me llevo {qty} del {code} de velluto"], lambda h: (not _pedidos(h[0])) and bool(_pedidos(h[-1])))


def generar_tanda(total=1000, seed=63063):
    rng = random.Random(seed)
    return [_case(i, rng) for i in range(total)]


def ejecutar_tanda(total=1000, seed=63063):
    failures = []
    counts = {}
    cases = generar_tanda(total=total, seed=seed)
    for idx, (kind, mensajes, checker) in enumerate(cases):
        counts[kind] = counts.get(kind, 0) + 1
        try:
            history = _run_conversation(mensajes)
            _assert_base(history)
            if not checker(history):
                raise AssertionError("checker_false")
        except Exception as exc:
            failures.append({
                "idx": idx,
                "tipo": kind,
                "mensajes": mensajes,
                "fallo": type(exc).__name__,
                "detalle": str(exc)[:240],
            })
    passed = total - len(failures)
    return {
        "tester_mode": True,
        "dry_run": True,
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "pass_rate": passed / float(total or 1),
        "counts": counts,
        "failures": failures[:25],
    }


def auto_mejora_controlada(max_ciclos=5, objetivo=0.99):
    """Clasifica fallos y aplica los criterios de paro sin tocar datos reales."""
    regresion = []
    vistos = set()
    tandas_ok = 0
    resumenes = []
    for ciclo in range(1, max_ciclos + 1):
        summary = ejecutar_tanda(total=1000, seed=63063 + ciclo)
        resumenes.append(summary)
        if not summary.get("tester_mode"):
            return {"stop": "no_regresa_tester_mode=true", "ciclo": ciclo, "resumenes": resumenes}
        if summary["pass_rate"] < objetivo:
            firma = tuple((f["tipo"], f["detalle"]) for f in summary["failures"][:5])
            if firma in vistos:
                return {"stop": "se_repite_el_mismo_fallo", "ciclo": ciclo, "resumenes": resumenes}
            vistos.add(firma)
            regresion.extend(summary["failures"])
            return {"stop": "clasificar_fallo_y_corregir_minimo", "ciclo": ciclo, "regresion": regresion[:25], "resumenes": resumenes}
        tandas_ok += 1
        if tandas_ok >= 3:
            return {"stop": "3_tandas_nuevas_con_minimo_99", "ciclo": ciclo, "resumenes": resumenes}
    return {"stop": "5_ciclos", "resumenes": resumenes}


class WhatsAppIAV29AutoTester(unittest.TestCase):
    def test_1000_conversaciones_complejas_dry_run(self):
        summary = ejecutar_tanda(total=1000, seed=63063)
        self.assertTrue(summary["tester_mode"])
        self.assertGreaterEqual(summary["pass_rate"], 0.99, json.dumps(summary["failures"][:10], ensure_ascii=False))


if __name__ == "__main__":
    print(json.dumps(ejecutar_tanda(total=1000, seed=63063), ensure_ascii=False, indent=2))
