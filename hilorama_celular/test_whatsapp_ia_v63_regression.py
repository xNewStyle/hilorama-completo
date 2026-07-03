import json
import unittest

from .test_whatsapp_ia_v61_real_failures import (
    REGRESSION_PATH,
    V61,
    _inventory_from_report,
    _load_v63_regression_cases,
    _plan_for_items,
    _shipping_callback_for_case,
    _thresholds_for,
)
from .whatsapp_ia_v27 import procesar_conversacion_v27


class WhatsappIAV63RegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = _load_v63_regression_cases()
        cls.products = _inventory_from_report(cls.cases)

    def test_regresion_v63_no_tiene_filas_saltadas(self):
        line_count = sum(1 for line in REGRESSION_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
        self.assertEqual(line_count, len(self.cases))
        self.assertGreaterEqual(len(self.cases), 7)

    def _run_case(self, raw):
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
            reasons.append("regresion: respuesta contiene 'me quedan -'")
        if not passed:
            self.fail(
                f"{case.case_id}: {' | '.join(reasons)} | "
                f"stats={json.dumps(extra.get('match_stats') or {}, ensure_ascii=False)}"
            )


def _safe_name(case_id):
    clean = "".join(ch if ch.isalnum() else "_" for ch in str(case_id or "caso"))
    return clean[:180]


def _make_test(case_id):
    def _test(self):
        raw = next(r for r in self.cases if r.get("case_id") == case_id)
        self._run_case(raw)

    return _test


try:
    for _raw in _load_v63_regression_cases():
        setattr(
            WhatsappIAV63RegressionTest,
            "test_caso_real_" + _safe_name(_raw.get("case_id")),
            _make_test(_raw.get("case_id")),
        )
except Exception:
    pass


if __name__ == "__main__":
    unittest.main()
