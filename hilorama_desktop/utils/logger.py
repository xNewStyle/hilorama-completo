"""Logging central para Hilorama Desktop.

No guardar secretos aqui: cualquier mensaje pasa por un filtro simple para
ocultar passwords dentro de URLs y variables sensibles conocidas.
"""

from __future__ import annotations

import logging
import re
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

_LOGGERS: dict[str, logging.Logger] = {}


_URL_PASSWORD_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s]+:)([^@\s]+)(@)")
_SENSITIVE_ENV_RE = re.compile(
    r"(?i)\b(DATABASE_URL|WHATSAPP_TOKEN|WHATSAPP_VERIFY_TOKEN|"
    r"HILORAMA_RENDER_TOKEN|TOKEN|PASSWORD|CONTRASENA|CONTRASEÑA)\s*=\s*([^\s]+)"
)


def _sanitize(value) -> str:
    text = "" if value is None else str(value)
    text = _URL_PASSWORD_RE.sub(r"\1***\3", text)
    text = _SENSITIVE_ENV_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return text


def _log_file_for(nombre: str) -> Path:
    limpio = (nombre or "hilorama_desktop").strip().lower().replace(" ", "_")
    if limpio in {"desktop", "hilorama", "hilorama_desktop"}:
        archivo = "hilorama_desktop.log"
    elif limpio in {"ventas", "almacen", "errores"}:
        archivo = f"{limpio}.log"
    else:
        archivo = f"{limpio}.log"
    return LOG_DIR / archivo


def get_logger(nombre: str) -> logging.Logger:
    nombre = (nombre or "hilorama_desktop").strip().lower()
    if nombre in _LOGGERS:
        return _LOGGERS[nombre]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"hilorama.{nombre}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            _log_file_for(nombre),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    _LOGGERS[nombre] = logger
    return logger


def _format_exception(exc=None) -> str:
    if exc is None:
        formatted = traceback.format_exc()
        return "" if formatted.strip() == "NoneType: None" else formatted

    if isinstance(exc, tuple) and len(exc) == 3:
        return "".join(traceback.format_exception(exc[0], exc[1], exc[2]))

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def log_info(nombre_modulo: str, mensaje: str):
    get_logger(nombre_modulo).info(_sanitize(mensaje))


def log_error(nombre_modulo: str, mensaje: str, exc=None):
    detalle = _format_exception(exc)
    texto = _sanitize(mensaje)
    if detalle:
        texto = f"{texto}\n{_sanitize(detalle)}"

    get_logger(nombre_modulo).error(texto)
    if nombre_modulo != "errores":
        get_logger("errores").error(f"[{nombre_modulo}] {texto}")

