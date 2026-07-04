import json
import re
import unicodedata
import unittest
from pathlib import Path

from .whatsapp_ia_v27 import procesar_conversacion_v27


REGRESSION_PATH = Path(__file__).resolve().parent / "data" / "test_cases" / "regresion_conversacional_v64.jsonl"


def _norm_assert(texto):
    texto = "" if texto is None else str(texto)
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower().replace("\u00d7", "x")
    return re.sub(r"\s+", " ", texto).strip()


def _load_cases():
    cases = []
    for lineno, line in enumerate(REGRESSION_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        raw["_lineno"] = lineno
        cases.append(raw)
    return cases


def _product(producto_id, marca, hilo, codigo, color, precio, stock=40, volumetrico=1.0):
    return {
        "id": producto_id,
        "producto_id": producto_id,
        "marca": marca,
        "hilo": hilo,
        "codigo": codigo,
        "color": color,
        "stock": stock,
        "precio_venta": precio,
        "volumetrico": volumetrico,
        "es_inventariable": True,
    }


def _inventory_v64():
    return [
        _product(1, "Alize", "Velluto", "429", "Camel", 57.20, volumetrico=1.5),
        _product(2, "Alize", "Velluto", "550", "Mandarina", 57.20, volumetrico=1.5),
        _product(3, "Alize", "Velluto", "16", "Ocean", 57.20, volumetrico=1.5),
        _product(4, "Alize", "Velluto", "493", "Cafe Oscuro", 57.20, volumetrico=1.5),
        _product(5, "Alize", "Velluto", "329", "Tabaco", 57.20, volumetrico=1.5),
        _product(6, "Alize", "Velluto", "60", "Negro", 57.20, volumetrico=1.5),
        _product(7, "Karina", "Komfy Mini", "73", "Cafe", 34.00, volumetrico=0.5),
        _product(8, "Karina", "Komfy Mini", "99", "Negro", 34.00, volumetrico=0.5),
        _product(9, "Karina", "Komfy Mini", "06", "Cielo", 34.00, volumetrico=0.5),
        _product(10, "Karina", "Kurumi", "12", "Crema", 29.00, volumetrico=0.3),
    ]


def _resource_callback(intencion, normalizado, contexto, extraccion):
    principal = intencion.get("principal")
    texto = normalizado.get("texto") or ""
    if principal == "pide_gama":
        hilo = _norm_assert(contexto.get("hilo_actual") or "")
        if "velluto" in hilo:
            return {"respuesta": "Claro 😊 le comparto la gama de Velluto: /static/gama/velluto.jpg"}
        if "komfy" in hilo:
            return {"respuesta": "Claro 😊 le comparto la gama de Komfy Mini: /static/gama/komfy_mini.jpg"}
        return {"respuesta": "Claro 😊 le comparto la gama disponible: /static/gama/hilorama.jpg"}
    if principal == "pide_foto_tono":
        codigos = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto)
        rutas = []
        for codigo in codigos[:6]:
            rutas.append(f"/static/tonos/velluto_{codigo}.jpg")
        return {"respuesta": "Claro 😊 le comparto foto de los tonos " + ", ".join(codigos[:6]) + ": " + " ".join(rutas)}
    return {}


def _pedido_memoria(memoria):
    raw = (memoria or {}).get("pedido_en_proceso") or "[]"
    if isinstance(raw, list):
        return raw
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    return obj if isinstance(obj, list) else []


def _qty_by_code(pedidos):
    out = {}
    for item in pedidos or []:
        codigo = str(item.get("codigo") or item.get("codigo_raw") or "").strip().lstrip("0")
        if not codigo:
            continue
        out[codigo] = out.get(codigo, 0) + int(item.get("cantidad") or 1)
    return out


class WhatsappIAV64ConversacionalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = _load_cases()
        cls.products = _inventory_v64()

    def test_regresion_v64_no_tiene_filas_saltadas(self):
        line_count = sum(1 for line in REGRESSION_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
        self.assertEqual(line_count, len(self.cases))
        self.assertGreaterEqual(len(self.cases), 21)

    def _run_case(self, raw):
        memoria = dict(raw.get("initial_memory") or {})
        responses = []
        for msg in raw.get("user_messages") or []:
            response = procesar_conversacion_v27(
                {"texto": msg, "tester_mode": True, "dry_run": True},
                self.products,
                memoria=memoria,
                callbacks={"buscar_recurso": _resource_callback},
            )
            self.assertTrue(response.get("tester_mode"), raw["case_id"])
            self.assertTrue(response.get("dry_run"), raw["case_id"])
            responses.append(response)
            memoria = response.get("memoria") or memoria

        self.assertTrue(responses, raw["case_id"])
        final = responses[-1]
        response_text = final.get("respuesta") or ""
        response_norm = _norm_assert(response_text)
        expected_intent = raw.get("expected_intent")
        if isinstance(expected_intent, list):
            self.assertIn(final.get("intencion", {}).get("principal"), expected_intent, raw["case_id"])
        elif expected_intent:
            self.assertEqual(expected_intent, final.get("intencion", {}).get("principal"), raw["case_id"])

        for phrase in raw.get("expected_response_contains") or []:
            self.assertIn(_norm_assert(phrase), response_norm, f"{raw['case_id']} missing {phrase!r}: {response_text}")
        for phrase in raw.get("expected_response_not_contains") or []:
            self.assertNotIn(_norm_assert(phrase), response_norm, f"{raw['case_id']} should not contain {phrase!r}: {response_text}")

        for cold in ("entrada invalida", "producto no encontrado", "procesando", "no entendi", "apartar", "apartado"):
            self.assertNotIn(cold, response_norm, f"{raw['case_id']} cold/forbidden phrase: {response_text}")

        if raw.get("should_send_resources"):
            self.assertIn("/static/", response_text, raw["case_id"])

        if raw.get("should_request_clarification"):
            useful_prompt = any(
                token in response_norm
                for token in (
                    "?",
                    "pasame",
                    "mandeme",
                    "me confirma",
                    "confirma",
                    "ubicacion",
                    "colonia",
                    "que productos",
                    "lo busca",
                    "que tamano",
                    "que tamaño",
                    "proyecto",
                )
            )
            self.assertTrue(useful_prompt, f"{raw['case_id']} did not guide the customer: {response_text}")

        if raw.get("requires_human"):
            self.assertTrue(final.get("requiere_humano"), raw["case_id"])
            self.assertEqual("requiere_humano", final.get("confianza", {}).get("accion_recomendada"), raw["case_id"])

        pedidos = _pedido_memoria(final.get("memoria") or {})
        qty = _qty_by_code(pedidos)
        if raw.get("should_add_products"):
            self.assertTrue(pedidos, f"{raw['case_id']} expected products in memory")
            for expected in raw.get("expected_items") or []:
                codigo = str(expected.get("codigo") or "").strip().lstrip("0")
                self.assertEqual(int(expected.get("cantidad") or 1), qty.get(codigo), f"{raw['case_id']} qty for {codigo}")
        else:
            self.assertFalse(pedidos, f"{raw['case_id']} should not leave products in memory: {pedidos}")
            self.assertFalse((final.get("memoria") or {}).get("cotizacion_activa"), raw["case_id"])

        for codigo in raw.get("expected_absent_codes") or []:
            self.assertNotIn(str(codigo).strip().lstrip("0"), qty, raw["case_id"])


def _safe_name(case_id):
    clean = "".join(ch if ch.isalnum() else "_" for ch in str(case_id or "caso"))
    return clean[:180]


def _make_test(case_id):
    def _test(self):
        raw = next(r for r in self.cases if r.get("case_id") == case_id)
        self._run_case(raw)

    return _test


try:
    for _raw in _load_cases():
        setattr(
            WhatsappIAV64ConversacionalTest,
            "test_caso_" + _safe_name(_raw.get("case_id")),
            _make_test(_raw.get("case_id")),
        )
except Exception:
    pass


if __name__ == "__main__":
    unittest.main()
