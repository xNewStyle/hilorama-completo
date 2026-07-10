"""Limpieza segura de bytecode dentro de un paquete cliente generado."""

from __future__ import annotations

import shutil
from pathlib import Path


PYTHON_BYTECODE_SUFFIXES = {".pyc", ".pyo"}


def clean_python_artifacts(package_root) -> dict:
    """Elimina __pycache__, .pyc y .pyo solo dentro de package_root.

    El resultado contiene los artefactos eliminados o los errores que deben
    bloquear la validacion del paquete cliente.
    """
    root = Path(package_root).resolve()
    result = {
        "ok": False,
        "package_root": root,
        "removed_dirs": [],
        "removed_files": [],
        "errors": [],
    }
    if not root.exists() or not root.is_dir():
        result["errors"].append(f"No existe carpeta de paquete para limpiar: {root}")
        return result

    cache_dirs = []
    bytecode_files = []
    try:
        for path in root.rglob("*"):
            if not _is_inside_root(root, path):
                result["errors"].append(f"Ruta insegura fuera del paquete: {path}")
                continue
            if path.is_dir() and path.name.lower() == "__pycache__":
                cache_dirs.append(path)
            elif path.is_file() and path.suffix.lower() in PYTHON_BYTECODE_SUFFIXES:
                bytecode_files.append(path)
    except OSError as exc:
        result["errors"].append(f"No se pudo recorrer el paquete: {exc}")
        return result

    for cache_dir in sorted(cache_dirs, key=lambda item: len(item.parts), reverse=True):
        if not cache_dir.exists():
            continue
        if not _is_inside_root(root, cache_dir):
            result["errors"].append(f"No se limpio directorio inseguro: {cache_dir}")
            continue
        try:
            shutil.rmtree(cache_dir)
            result["removed_dirs"].append(cache_dir.relative_to(root).as_posix())
        except OSError as exc:
            result["errors"].append(f"No se pudo eliminar {cache_dir}: {exc}")

    for bytecode_file in bytecode_files:
        if not bytecode_file.exists():
            continue
        if not _is_inside_root(root, bytecode_file):
            result["errors"].append(f"No se limpio archivo inseguro: {bytecode_file}")
            continue
        try:
            bytecode_file.unlink()
            result["removed_files"].append(bytecode_file.relative_to(root).as_posix())
        except OSError as exc:
            result["errors"].append(f"No se pudo eliminar {bytecode_file}: {exc}")

    result["ok"] = not result["errors"]
    return result


def format_cleanup_summary(result: dict) -> str:
    if not result.get("ok"):
        details = "; ".join(result.get("errors") or ["Error de limpieza no especificado."])
        return f"Limpieza de bytecode fallida: {details}"
    return (
        "Limpieza de bytecode: "
        f"{len(result.get('removed_dirs', []))} carpetas __pycache__ y "
        f"{len(result.get('removed_files', []))} archivos .pyc/.pyo eliminados."
    )


def _is_inside_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False
