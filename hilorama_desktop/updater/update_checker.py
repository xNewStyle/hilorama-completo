"""Revision no bloqueante de actualizaciones.

Este modulo nunca debe tumbar la aplicacion: si no hay internet, si el
manifiesto no existe o si el JSON viene mal, devuelve un resultado controlado.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    from ..config import APP_VERSION, get_update_manifest_url
    from ..utils.logger import log_error, log_info
except ImportError:
    from config import APP_VERSION, get_update_manifest_url
    from utils.logger import log_error, log_info

from .update_models import UpdateCheckResult, UpdateManifest


def get_current_version() -> str:
    return APP_VERSION


def get_manifest_url() -> str:
    return get_update_manifest_url()


def fetch_update_manifest(url: str | None = None, timeout: int = 5) -> UpdateManifest | None:
    manifest_url = (url or get_manifest_url() or "").strip()
    if not manifest_url:
        return None

    try:
        text = _read_text_url_or_file(manifest_url, timeout=timeout)
        data = json.loads(text)
        manifest = UpdateManifest.from_dict(data)
        if not manifest.is_valid():
            log_info("hilorama_desktop", "Manifest de actualizacion incompleto")
            return None
        return manifest
    except (OSError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as exc:
        log_error("hilorama_desktop", "No se pudo leer manifest de actualizacion", exc)
        return None
    except Exception as exc:
        log_error("hilorama_desktop", "Error inesperado al revisar actualizaciones", exc)
        return None


def compare_versions(current: str, latest: str) -> int:
    current_parts = _version_key(current)
    latest_parts = _version_key(latest)
    if current_parts < latest_parts:
        return -1
    if current_parts > latest_parts:
        return 1
    return 0


def check_for_update(current_version: str | None = None, manifest_url: str | None = None) -> UpdateCheckResult:
    current = current_version or get_current_version()
    manifest = fetch_update_manifest(manifest_url)
    if not manifest:
        return UpdateCheckResult(ok=True, current_version=current, update_available=False)

    available = compare_versions(current, manifest.latest_version) < 0
    return UpdateCheckResult(
        ok=True,
        current_version=current,
        update_available=available,
        manifest=manifest,
    )


def _read_text_url_or_file(value: str, timeout: int = 5) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(value, headers={"User-Agent": "HiloramaCliente-Updater"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(parsed.path)).read_text(encoding="utf-8")

    path = Path(value)
    if path.exists():
        return path.read_text(encoding="utf-8")
    raise OSError("URL de manifest no soportada.")


def _version_key(value: str):
    parts = []
    for item in re.findall(r"\d+|[A-Za-z]+", str(value or "")):
        if item.isdigit():
            parts.append((1, int(item)))
        else:
            parts.append((0, item.lower()))
    return parts
