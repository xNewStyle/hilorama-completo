"""Preparacion de reemplazo del EXE en Windows.

El EXE en ejecucion no puede reemplazarse a si mismo de forma confiable, por
eso se prepara un .bat auxiliar. En esta fase queda en modo dry-run por defecto.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from ..utils.logger import log_info
except ImportError:
    from utils.logger import log_info


def current_executable_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.argv[0]).resolve()


def prepare_windows_update(downloaded_file: str | Path, target_exe: str | Path | None = None, dry_run: bool = True) -> dict:
    source = Path(downloaded_file).resolve()
    if not source.exists():
        raise FileNotFoundError(f"No existe actualizacion descargada: {source}")

    target = Path(target_exe).resolve() if target_exe else current_executable_path()
    helper = source.parent / "aplicar_actualizacion_hilorama.bat"
    content = _bat_content(source, target, dry_run=dry_run)
    helper.write_text(content, encoding="utf-8")
    log_info("hilorama_desktop", f"Helper de actualizacion preparado: {helper}")
    return {
        "ok": True,
        "dry_run": dry_run,
        "helper_path": str(helper),
        "downloaded_file": str(source),
        "target_exe": str(target),
    }


def _bat_content(source: Path, target: Path, dry_run: bool) -> str:
    reopen = f'start "" "{target}"'
    replace_commands = [
        "@echo off",
        "setlocal",
        "echo Preparando actualizacion de HiloramaCliente...",
        "timeout /t 3 /nobreak > nul",
    ]
    if dry_run:
        replace_commands.extend([
            "echo MODO PREPARACION: no se reemplazo el ejecutable.",
            f'echo Archivo descargado: "{source}"',
            f'echo Ejecutable destino: "{target}"',
            "pause",
        ])
    else:
        replace_commands.extend([
            f'copy /Y "{source}" "{target}"',
            "if errorlevel 1 (",
            "  echo No se pudo reemplazar HiloramaCliente.exe",
            "  pause",
            "  exit /b 1",
            ")",
            reopen,
        ])
    replace_commands.append("endlocal")
    return "\r\n".join(replace_commands) + "\r\n"
