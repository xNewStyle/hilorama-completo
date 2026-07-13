"""Presentacion segura para datos que llegan desde el backend."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MEXICO_CITY_ZONE = "America/Mexico_City"
EMPTY_VALUE = "—"

try:
    _MEXICO_TZ = ZoneInfo(MEXICO_CITY_ZONE)
except ZoneInfoNotFoundError as exc:  # No ocultar una dependencia faltante en el EXE.
    raise RuntimeError(
        "No se encontro la zona America/Mexico_City. Instale la dependencia tzdata."
    ) from exc


_SENSITIVE_KEY_PARTS = (
    "password",
    "contrasena",
    "contraseña",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
    "session",
    "private_key",
    "clave_autorizacion",
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|contras(?:ena|eña)|token|access_token|refresh_token|"
    r"authorization|api[_-]?key|secret|cookie|session|clave_autorizacion)\b"
    r"\s*([:=])\s*(?:bearer\s+)?[^\s,;]+"
)
_CREDENTIAL_URL = re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql)://[^\s,;]+")
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+")
_PRIVATE_KEY = re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----.*?-----END(?: [A-Z]+)? PRIVATE KEY-----", re.S)


def optional_text(value: Any, default: str = EMPTY_VALUE) -> str:
    """Convierte nulos y cadenas vacias a un valor visual consistente."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def format_datetime_mexico(value: Any) -> str:
    """Muestra fechas con zona conocida en Mexico y marca fechas legacy naive."""
    if value in (None, ""):
        return EMPTY_VALUE

    parsed = value if isinstance(value, datetime) else _parse_datetime(value)
    if parsed is None:
        return EMPTY_VALUE
    if parsed.tzinfo is None:
        return f"{parsed.strftime('%d/%m/%Y %H:%M')} (registro legacy sin zona)"
    return parsed.astimezone(_MEXICO_TZ).strftime("%d/%m/%Y %H:%M %Z")


def redact_sensitive_data(value: Any):
    """Redacta valores sensibles de forma recursiva antes de mostrarlos o loguearlos."""
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                clean[key_text] = "[oculto]"
            else:
                clean[key_text] = redact_sensitive_data(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def safe_pretty_json(value: Any) -> str:
    """Convierte JSON valido, invalido o nulo en texto seguro para un detalle."""
    if value in (None, ""):
        return EMPTY_VALUE
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return json.dumps({"texto": _redact_text(value)}, ensure_ascii=False, indent=2)
    try:
        return json.dumps(redact_sensitive_data(data), ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return json.dumps({"texto": _redact_text(str(data))}, ensure_ascii=False, indent=2)


def format_support_identifier(value: Any) -> str:
    """Da una pista util para soporte sin exponer por completo una llave tecnica."""
    text = optional_text(value, default="")
    if not text:
        return EMPTY_VALUE
    if len(text) <= 10:
        return text
    return f"{text[:4]}…{text[-4:]}"


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_text(text: str) -> str:
    value = _PRIVATE_KEY.sub("[clave privada oculta]", str(text))
    value = _CREDENTIAL_URL.sub("[URL con credenciales oculta]", value)
    value = _BEARER_TOKEN.sub("Bearer [oculto]", value)
    return _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[oculto]",
        value,
    )
