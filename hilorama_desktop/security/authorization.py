"""Autorizaciones locales temporales para flujos legacy.

La autorizacion fuerte debe vivir en el backend. Este modulo solo centraliza
claves heredadas mientras terminan de migrarse esos dialogos.
"""

from __future__ import annotations

import os


DEFAULT_ADMIN_OVERRIDE_KEY = "1"
DEFAULT_LEGACY_SALES_OVERRIDE_KEY = "12587987521"
ENV_ADMIN_OVERRIDE_KEY = "HILORAMA_ADMIN_OVERRIDE_KEY"


def _env_key():
    value = os.environ.get(ENV_ADMIN_OVERRIDE_KEY, "").strip()
    return value or None


def get_admin_override_key():
    return _env_key() or DEFAULT_ADMIN_OVERRIDE_KEY


def get_legacy_sales_override_key():
    return _env_key() or DEFAULT_LEGACY_SALES_OVERRIDE_KEY


def is_admin_override_key(value):
    return str(value or "") == get_admin_override_key()


def is_legacy_sales_override_key(value):
    return str(value or "") == get_legacy_sales_override_key()
