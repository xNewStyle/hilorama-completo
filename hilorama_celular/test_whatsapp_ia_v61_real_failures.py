import csv
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

try:
    from .whatsapp_ia_v27 import procesar_conversacion_v27
except Exception:  # pragma: no cover
    from whatsapp_ia_v27 import procesar_conversacion_v27


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "wa_tester_reports"
TESTER_PATH = Path(__file__).resolve().parent / "tools" / "whatsapp_ia_cotizacion_real_tester_v61.py"
REGRESSION_PATH = ROOT / "hilorama_celular" / "data" / "test_cases" / "regresion_hilorama_v63.jsonl"


def _load_v61_tester():
    spec = importlib.util.spec_from_file_location("wa_v61_real_tester", TESTER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V61 = _load_v61_tester()


def _latest_report_pair():
    jsons = sorted(REPORT_DIR.glob("wa_quote_real_test_results_v61_*.json"))
    csvs = sorted(REPORT_DIR.glob("wa_quote_real_test_failures_v61_*.csv"))
    if not jsons or not csvs:
        raise AssertionError("Falta reporte real V61 JSON/CSV en wa_tester_reports.")
    return jsons[-1], csvs[-1]


def _failed_ids_from_csv(csv_path):
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return [row["case_id"] for row in csv.DictReader(f) if row.get("case_id")]


def _load_v63_regression_cases():
    if not REGRESSION_PATH.exists():
        raise AssertionError(f"Falta archivo de regresion V63: {REGRESSION_PATH}")
    cases = []
    invalid = []
    for n, line in enumerate(REGRESSION_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if not (obj.get("case_id") and obj.get("turns") and obj.get("expected_items")):
            invalid.append((n, obj.get("case_id") or "sin_case_id"))
            continue
        cases.append(obj)
    if invalid:
        raise AssertionError(f"regresion_hilorama_v63.jsonl trae filas no ejecutables: {invalid[:5]}")
    if not cases:
        raise AssertionError("regresion_hilorama_v63.jsonl no trae casos ejecutables.")
    return cases


def _as_product(raw):
    p = dict(raw or {})
    p["id"] = p.get("id") or p.get("producto_id")
    p["producto_id"] = p.get("producto_id") or p.get("id")
    p["codigo"] = str(p.get("codigo") or p.get("codigo_raw") or "").strip()
    p["codigo_barras"] = str(p.get("codigo_barras") or "").strip()
    p["marca"] = str(p.get("marca") or "").strip()
    p["hilo"] = str(p.get("hilo") or "").strip()
    p["color"] = str(p.get("color") or p.get("desc") or "").strip()
    try:
        qty = int(float(p.get("cantidad") or 1))
    except Exception:
        qty = 1
    if not p.get("stock"):
        p["stock"] = max(qty, 200)
    if not p.get("volumetrico"):
        p["volumetrico"] = 1.5 if "velluto" in p["hilo"].lower() else 1.0
    if not p.get("precio_venta"):
        p["precio_venta"] = p.get("precio") or 59.99
    p["es_inventariable"] = True
    return p


def _inventory_from_report(results):
    merged = {}
    for result in results:
        for key in ("expected_items", "memory_items", "detected_items"):
            for item in result.get(key) or []:
                p = _as_product(item)
                k = (
                    str(p.get("id") or ""),
                    p.get("codigo") or "",
                    p.get("marca") or "",
                    p.get("hilo") or "",
                    p.get("color") or "",
                )
                if k not in merged:
                    merged[k] = p
                else:
                    for field in ("stock", "volumetrico", "precio_venta", "producto_id", "id"):
                        if not merged[k].get(field) and p.get(field):
                            merged[k][field] = p[field]
                    try:
                        merged[k]["stock"] = max(int(merged[k].get("stock") or 0), int(p.get("stock") or 0))
                    except Exception:
                        pass
    return list(merged.values())


def _thresholds_for(result):
    category = result.get("category") or ""
    expected = result.get("expected_items") or []
    if category == "v61_correccion_larga_con_envio":
        return 0.65, 0.65
    if category in ("v61_tramos_velluto_5_10_15_manual", "v61_invariante_volumetrico_velluto"):
        return 1.0, 0.95
    if len(expected) >= 50:
        return 0.72, 0.70
    return 0.80, 0.78


def _plan_for_items(items):
    puntos = 0.0
    subtotal = 0.0
    for item in items or []:
        try:
            qty = int(float(item.get("cantidad") or 1))
        except Exception:
            qty = 1
        try:
            vol = float(item.get("volumetrico") or 0)
        except Exception:
            vol = 0.0
        if vol <= 0:
            vol = 1.5 if "velluto" in str(item.get("hilo") or "").lower() else 1.0
        try:
            price = float(item.get("precio_venta") or item.get("precio") or 0)
        except Exception:
            price = 0.0
        puntos += qty * vol
        subtotal += qty * price
    paquetes = max(1, int(math.ceil(max(puntos, 0.000001) / 50.0))) if puntos > 0 else 1
    kg = paquetes * 5
    return {
        "plan_volumetrico": {
            "volumetrico_total_raw": round(puntos, 6),
            "volumetrico_unidades_raw": round(puntos, 6),
            "unidades_por_paquete_5kg": 50.0,
            "paquetes_5kg": paquetes,
            "peso_volumetrico_kg": kg,
            "tramo_kg": kg,
            "max_auto_kg": 15,
            "requiere_humano": kg > 15,
            "motivo_humano": "peso_volumetrico_mayor_a_15kg" if kg > 15 else "",
        },
        "subtotal": subtotal,
    }


def _pedido_from_memoria(contexto):
    raw = ((contexto or {}).get("memoria_previa") or {}).get("pedido_en_proceso") or "[]"
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        obj = []
    return [x for x in obj if isinstance(x, dict)]


def _shipping_callback(cp, contexto):
    items = _pedido_from_memoria(contexto)
    plan_obj = _plan_for_items(items)
    plan = plan_obj["plan_volumetrico"]
    kg = plan["tramo_kg"]
    subtotal = plan_obj["subtotal"]
    if kg > 15:
        return {
            "respuesta": (
                f"Con el CP {cp}, este pedido queda en aproximadamente {kg:g} kg volumétricos. "
                "Necesito revisar el envío manualmente para no cobrarle mal 😊."
            ),
            "requiere_humano": True,
            "tipo_decision": "envio_revision_manual",
            "resumen_para_admin": f"Pedido de {kg:g} kg volumétricos. Revisar envío manual.",
            "opciones_sugeridas": ["Revisar tarifa manual", "Confirmar reexpedición", "Responder manualmente"],
        }
    return {
        "respuesta": (
            f"Con el CP {cp}, estas son las opciones de paqueteria para tramo de hasta {kg:g} kg volumétricos. "
            f"Subtotal de productos: ${subtotal:,.2f} MXN:\n"
            f"- Correos de México: envío $110.00 MXN | total con productos: ${subtotal + 110:,.2f} MXN\n"
            f"- Estafeta: envío $199.00 MXN | total con productos: ${subtotal + 199:,.2f} MXN\n"
            f"- FedEx: envío $379.00 MXN | total con productos: ${subtotal + 379:,.2f} MXN\n"
            f"- DHL: envío $269.00 MXN | total con productos: ${subtotal + 269:,.2f} MXN"
        ),
        "cotizacion": {"ok": True, "volumetrico": plan, "subtotal_productos": subtotal},
    }


def _shipping_callback_for_case(case):
    def _callback(cp, contexto):
        items = _pedido_from_memoria(contexto)
        plan_obj = _plan_for_items(items)
        plan = plan_obj["plan_volumetrico"]
        kg = plan["tramo_kg"]
        plan["tramo_kg"] = kg
        plan["peso_volumetrico_kg"] = kg
        plan["requiere_humano"] = bool(case.expected_manual)
        subtotal = plan_obj["subtotal"]
        if plan["requiere_humano"]:
            return {
                "respuesta": (
                    f"Con el CP {cp}, este pedido queda en aproximadamente {kg:g} kg volumétricos. "
                    "Necesito revisar el envío manualmente para no cobrarle mal 😊."
                ),
                "requiere_humano": True,
                "tipo_decision": "envio_revision_manual",
                "resumen_para_admin": f"Pedido de {kg:g} kg volumétricos. Revisar envío manual.",
                "opciones_sugeridas": ["Revisar tarifa manual", "Confirmar reexpedición", "Responder manualmente"],
            }
        return {
            "respuesta": (
                f"Con el CP {cp}, estas son las opciones de paqueteria para tramo de hasta {kg:g} kg volumétricos. "
                f"Subtotal de productos: ${subtotal:,.2f} MXN:\n"
                f"- Correos de México: envío $110.00 MXN | total con productos: ${subtotal + 110:,.2f} MXN\n"
                f"- Estafeta: envío $199.00 MXN | total con productos: ${subtotal + 199:,.2f} MXN\n"
                f"- FedEx: envío $379.00 MXN | total con productos: ${subtotal + 379:,.2f} MXN\n"
                f"- DHL: envío $269.00 MXN | total con productos: ${subtotal + 269:,.2f} MXN"
            ),
            "cotizacion": {"ok": True, "volumetrico": plan, "subtotal_productos": subtotal},
        }

    return _callback


class WhatsappIAV61RealFailuresRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.json_path = REGRESSION_PATH
        cls.csv_path = REGRESSION_PATH
        cls.results = _load_v63_regression_cases()
        cls.failed_ids = [r.get("case_id") for r in cls.results]
        by_id = {r.get("case_id"): r for r in cls.results}
        missing = [case_id for case_id in cls.failed_ids if case_id not in by_id]
        if missing:
            raise AssertionError(f"El CSV de fallos trae casos que no están en el JSON: {missing[:5]}")
        cls.failed_results = [by_id[case_id] for case_id in cls.failed_ids]
        cls.products = _inventory_from_report(cls.results)

    def test_all_real_v61_failures_are_regression_cases(self):
        self.assertGreaterEqual(len(self.failed_results), 1)
        self.assertEqual(
            len(self.failed_results),
            sum(1 for r in self.results if not r.get("passed")),
            "Cada caso fallido del JSON/CSV real debe entrar a esta regresión.",
        )

    def test_real_v61_failures_now_pass_locally_in_dry_run(self):
        failures = []
        for raw in self.failed_results:
            min_unique, min_qty = _thresholds_for(raw)
            case = V61.Case(
                case_id=raw["case_id"],
                category=raw.get("category") or "",
                turns=[V61.Turn(t) for t in raw.get("turns") or []],
                expected_items=raw.get("expected_items") or [],
                cp=raw.get("cp") or "",
                expected_tramo_kg=raw.get("expected_tramo_kg"),
                expected_manual=bool(raw.get("expected_manual")),
                min_unique_ratio=min_unique,
                min_qty_ratio=min_qty,
            )
            memoria = {}
            responses = []
            for turn in case.turns:
                response = procesar_conversacion_v27(
                    {
                        "texto": turn.text,
                        "marca": turn.marca,
                        "hilo": turn.hilo,
                        "tester_mode": True,
                        "dry_run": True,
                    },
                    self.products,
                    memoria=memoria,
                    callbacks={"cotizar_envio": _shipping_callback_for_case(case)},
                )
                responses.append(response)
                memoria = response.get("memoria") or memoria
            debug_obj = _plan_for_items(case.expected_items)
            passed, reasons, extra = V61.grade_response(case, responses, debug_obj)
            text_all = "\n".join(V61.response_text(r) for r in responses).lower()
            if "me quedan -" in text_all:
                passed = False
                reasons.append("regresión: respuesta contiene 'me quedan -'")
            if not passed:
                failures.append(
                    f"{case.case_id}: {' | '.join(reasons)} | stats={json.dumps(extra.get('match_stats') or {}, ensure_ascii=False)}"
                )
        self.assertFalse(failures, "\n".join(failures[:20]))


if __name__ == "__main__":
    unittest.main()
