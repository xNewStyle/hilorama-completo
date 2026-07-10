"""Descarga segura de paquetes de actualizacion."""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from ..config import BUILD_CHANNEL, HILORAMA_ENV
    from ..utils.logger import log_error, log_info
except ImportError:
    from config import BUILD_CHANNEL, HILORAMA_ENV
    from utils.logger import log_error, log_info

from .update_models import DownloadResult


def updates_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    path = Path(root) / "HiloramaDesktop" / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_update(download_url: str, expected_sha256: str, destination_dir: str | Path | None = None) -> DownloadResult:
    if not download_url:
        return DownloadResult(ok=False, error="Falta URL de descarga.")
    if not expected_sha256:
        return DownloadResult(ok=False, error="Falta checksum sha256.")

    destination = Path(destination_dir) if destination_dir else updates_dir()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / _filename_from_url(download_url)

    try:
        _copy_or_download(download_url, target)
        actual = verify_sha256(target, expected_sha256)
        if not actual:
            try:
                target.unlink()
            except OSError:
                pass
            return DownloadResult(ok=False, error="El checksum no coincide. Actualizacion cancelada.")
        log_info("hilorama_desktop", f"Actualizacion descargada y verificada: {target}")
        return DownloadResult(ok=True, file_path=str(target), sha256=actual)
    except Exception as exc:
        log_error("hilorama_desktop", "No se pudo descargar actualizacion", exc)
        return DownloadResult(ok=False, error=str(exc))


def verify_sha256(file_path: str | Path, expected_sha256: str) -> str | None:
    expected = str(expected_sha256 or "").strip().lower()
    if not expected:
        return None
    actual = _sha256_file(Path(file_path))
    return actual if actual == expected else None


def _copy_or_download(download_url: str, target: Path) -> None:
    parsed = urlparse(download_url)
    if parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(download_url, headers={"User-Agent": "HiloramaCliente-Updater"})
        with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        return

    if parsed.scheme == "file":
        _ensure_local_download_allowed()
        shutil.copy2(Path(urllib.request.url2pathname(parsed.path)), target)
        return

    path = Path(download_url)
    if path.exists():
        _ensure_local_download_allowed()
        shutil.copy2(path, target)
        return

    raise urllib.error.URLError("URL de descarga no soportada.")


def _ensure_local_download_allowed() -> None:
    allow = os.environ.get("HILORAMA_ALLOW_LOCAL_UPDATE_URL", "0") == "1"
    dev = HILORAMA_ENV == "development" or BUILD_CHANNEL != "production"
    if not (allow or dev):
        raise PermissionError("Las descargas locales solo estan permitidas en desarrollo.")


def _filename_from_url(download_url: str) -> str:
    parsed = urlparse(download_url)
    name = Path(unquote(parsed.path)).name if parsed.path else ""
    if not name:
        name = "HiloramaCliente_update.exe"
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}).strip(".")
    return safe or "HiloramaCliente_update.exe"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
