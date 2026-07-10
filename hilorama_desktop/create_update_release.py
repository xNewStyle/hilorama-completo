"""Crea una release local para publicar actualizaciones.

No sube archivos ni hace deploy. Solo prepara HiloramaCliente.exe, update.json
y RELEASE_NOTES.txt dentro de releases/HiloramaCliente/<version>/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from .config import APP_UPDATE_NAME, APP_VERSION
except ImportError:
    from config import APP_UPDATE_NAME, APP_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = PROJECT_ROOT / "dist_cliente" / "exe_prueba" / "HiloramaCliente.exe"
RELEASE_ROOT = PROJECT_ROOT / "releases" / "HiloramaCliente"


def main() -> int:
    args = _parse_args()
    exe_path = Path(args.exe).resolve()
    if not exe_path.exists():
        raise SystemExit(f"No existe EXE: {exe_path}")

    version = args.version or APP_VERSION
    release_dir = RELEASE_ROOT / version
    release_dir.mkdir(parents=True, exist_ok=True)

    target_exe = release_dir / "HiloramaCliente.exe"
    shutil.copy2(exe_path, target_exe)

    sha256 = _sha256_file(target_exe)
    notes = args.note or ["Actualizacion Hilorama Cliente."]
    update = {
        "app": APP_UPDATE_NAME,
        "latest_version": version,
        "min_required_version": args.min_required_version or APP_VERSION,
        "download_url": args.download_url or "URL_PUBLICA_DEL_EXE_O_ZIP",
        "sha256": sha256,
        "size_bytes": target_exe.stat().st_size,
        "mandatory": bool(args.mandatory),
        "notes": notes,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    update_path = release_dir / "update.json"
    notes_path = release_dir / "RELEASE_NOTES.txt"
    update_path.write_text(json.dumps(update, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    notes_path.write_text("\n".join(f"- {item}" for item in notes) + "\n", encoding="utf-8")

    print(f"Release creada: {release_dir}")
    print(f"EXE: {target_exe}")
    print(f"Manifest: {update_path}")
    print(f"SHA256: {sha256}")
    return 0


def _parse_args():
    parser = argparse.ArgumentParser(description="Crear release local de Hilorama Cliente")
    parser.add_argument("--exe", default=str(DEFAULT_EXE), help="Ruta de HiloramaCliente.exe generado")
    parser.add_argument("--version", default=APP_VERSION, help="Version a publicar")
    parser.add_argument("--min-required-version", default=APP_VERSION, help="Version minima requerida")
    parser.add_argument("--download-url", default="", help="URL publica final del EXE o ZIP")
    parser.add_argument("--mandatory", action="store_true", help="Marcar actualizacion como obligatoria")
    parser.add_argument("--note", action="append", help="Nota de version; puede repetirse")
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
