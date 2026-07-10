"""Prepara una release local y su copia para un sitio Render Static.

No sube archivos ni hace deploy. Genera la copia historica en releases/ y la
carpeta publica updates_public/ que el usuario puede publicar manualmente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from .config import APP_UPDATE_NAME, APP_VERSION, DEFAULT_UPDATE_STATIC_BASE_URL
except ImportError:
    from config import APP_UPDATE_NAME, APP_VERSION, DEFAULT_UPDATE_STATIC_BASE_URL


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = PROJECT_ROOT / "dist_cliente" / "exe_prueba" / "HiloramaCliente.exe"
RELEASE_ROOT = PROJECT_ROOT / "releases" / "HiloramaCliente"
DEFAULT_STATIC_ROOT = PROJECT_ROOT / "updates_public"
PUBLIC_RELEASE_RELATIVE = Path("updates") / APP_UPDATE_NAME


def main() -> int:
    args = _parse_args()
    exe_path = Path(args.exe).resolve()
    if not exe_path.exists():
        raise SystemExit(f"No existe EXE: {exe_path}")

    version = args.version or APP_VERSION
    if version != APP_VERSION and not args.allow_version_mismatch:
        raise SystemExit(
            "La version de release debe coincidir con APP_VERSION "
            f"({APP_VERSION}). Actualiza APP_VERSION, vuelve a compilar el EXE "
            "y ejecuta de nuevo el comando."
        )
    release_dir = RELEASE_ROOT / version
    release_dir.mkdir(parents=True, exist_ok=True)
    static_root = Path(args.static_dir).resolve()
    public_release_dir = static_root / PUBLIC_RELEASE_RELATIVE
    public_release_dir.mkdir(parents=True, exist_ok=True)

    target_exe = release_dir / "HiloramaCliente.exe"
    shutil.copy2(exe_path, target_exe)
    public_exe = public_release_dir / target_exe.name
    shutil.copy2(target_exe, public_exe)

    sha256 = _sha256_file(public_exe)
    notes = args.note or ["Actualizacion Hilorama Cliente."]
    static_base_url = _normalizar_static_base_url(args.static_base_url)
    download_url = args.download_url.strip() or _public_url(static_base_url, public_exe.name)
    update = {
        "app": APP_UPDATE_NAME,
        "latest_version": version,
        "min_required_version": args.min_required_version or APP_VERSION,
        "download_url": download_url,
        "sha256": sha256,
        "size_bytes": public_exe.stat().st_size,
        "mandatory": bool(args.mandatory),
        "notes": notes,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    update_path = release_dir / "update.json"
    notes_path = release_dir / "RELEASE_NOTES.txt"
    update_path.write_text(json.dumps(update, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    notes_path.write_text("\n".join(f"- {item}" for item in notes) + "\n", encoding="utf-8")
    public_update_path = public_release_dir / update_path.name
    public_notes_path = public_release_dir / notes_path.name
    shutil.copy2(update_path, public_update_path)
    shutil.copy2(notes_path, public_notes_path)

    print(f"Release creada: {release_dir}")
    print(f"EXE: {target_exe}")
    print(f"Manifest: {update_path}")
    print(f"Publico Static: {public_release_dir}")
    print(f"Manifest publico: {public_update_path}")
    print(f"Download URL: {download_url}")
    print(f"Tamano: {public_exe.stat().st_size} bytes")
    print(f"SHA256: {sha256}")
    return 0


def _parse_args():
    parser = argparse.ArgumentParser(description="Crear release local de Hilorama Cliente")
    parser.add_argument("--exe", default=str(DEFAULT_EXE), help="Ruta de HiloramaCliente.exe generado")
    parser.add_argument("--version", default=APP_VERSION, help="Version a publicar")
    parser.add_argument("--min-required-version", default=APP_VERSION, help="Version minima requerida")
    parser.add_argument(
        "--static-base-url",
        default=DEFAULT_UPDATE_STATIC_BASE_URL,
        help="URL base del servicio Render Static, por ejemplo https://mi-static.onrender.com",
    )
    parser.add_argument(
        "--static-dir",
        default=str(DEFAULT_STATIC_ROOT),
        help="Carpeta local que se usara como raiz publicable de Render Static",
    )
    parser.add_argument(
        "--download-url",
        default="",
        help="Override excepcional para la URL publica de descarga",
    )
    parser.add_argument(
        "--allow-version-mismatch",
        action="store_true",
        help="Solo para pruebas: permite publicar una version distinta de APP_VERSION.",
    )
    parser.add_argument("--mandatory", action="store_true", help="Marcar actualizacion como obligatoria")
    parser.add_argument("--note", action="append", help="Nota de version; puede repetirse")
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalizar_static_base_url(value: str) -> str:
    base_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("--static-base-url debe ser una URL http(s) valida.")
    return base_url


def _public_url(static_base_url: str, filename: str) -> str:
    return f"{static_base_url}/{PUBLIC_RELEASE_RELATIVE.as_posix()}/{filename}"


if __name__ == "__main__":
    raise SystemExit(main())
