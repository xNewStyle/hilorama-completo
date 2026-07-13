"""Pruebas puras de fechas y redaccion para FASE 9C."""

import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hilorama_desktop.utils.presentation import (
    EMPTY_VALUE,
    MEXICO_CITY_ZONE,
    format_datetime_mexico,
    redact_sensitive_data,
    safe_pretty_json,
)


class PresentationTests(unittest.TestCase):
    def test_zoneinfo_mexico_city_is_available(self):
        self.assertEqual(str(ZoneInfo(MEXICO_CITY_ZONE)), MEXICO_CITY_ZONE)

    def test_utc_is_converted_to_mexico_city(self):
        rendered = format_datetime_mexico("2026-07-12T18:30:00Z")
        self.assertIn("12:30", rendered)

    def test_naive_legacy_date_is_not_treated_as_utc(self):
        rendered = format_datetime_mexico("2026-07-12 18:30:00")
        self.assertIn("registro legacy sin zona", rendered)
        self.assertIn("18:30", rendered)

    def test_missing_or_invalid_date_uses_empty_value(self):
        self.assertEqual(format_datetime_mexico(None), EMPTY_VALUE)
        self.assertEqual(format_datetime_mexico("fecha-invalida"), EMPTY_VALUE)

    def test_recursive_redaction_hides_sensitive_keys_and_text(self):
        original = {
            "password": "valor-privado",
            "nested": {"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"},
            "url": "postgresql://usuario:secreto@host/base",
            "safe": "visible",
        }
        clean = redact_sensitive_data(original)
        rendered = safe_pretty_json(clean)
        self.assertEqual(clean["password"], "[oculto]")
        self.assertEqual(clean["nested"]["Authorization"], "[oculto]")
        self.assertNotIn("valor-privado", rendered)
        self.assertNotIn("usuario:secreto", rendered)
        self.assertIn("visible", rendered)

    def test_safe_pretty_json_handles_valid_invalid_and_null_values(self):
        self.assertIn('"uno": 1', safe_pretty_json('{"uno": 1}'))
        self.assertIn("texto", safe_pretty_json("json roto"))
        self.assertEqual(safe_pretty_json(None), EMPTY_VALUE)


if __name__ == "__main__":
    unittest.main()
