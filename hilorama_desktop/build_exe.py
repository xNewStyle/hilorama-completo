"""Prepara y ejecuta build interno de Hilorama Cliente con PyInstaller.

No crea instalador. El exe queda en dist_cliente/exe_prueba cuando PyInstaller
esta instalado y se ejecuta sin --check-only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "dist_cliente" / "HiloramaCliente"
EXE_DIST = PROJECT_ROOT / "dist_cliente" / "exe_prueba"
WORK_DIR = PROJECT_ROOT / "dist_cliente" / "pyinstaller_work"
REPORT_PATH = PROJECT_ROOT / "dist_cliente" / "REPORTE_BUILD_EXE.txt"
SPEC_PATH = PROJECT_ROOT / "hilorama_desktop" / "HiloramaCliente.spec"
EXE_PATH = EXE_DIST / "HiloramaCliente.exe"

FORBIDDEN_DIRS = {
    ".git",
    "__pycache__",
    "backups",
    "backups_central",
    "comprobantes",
    "database",
    "dist",
    "hilorama_backend",
    "hilorama_celular",
    "hilorama_central",
    "logs",
    "releases",
}

FORBIDDEN_FILE_NAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
}

FORBIDDEN_SUFFIXES = {
    ".exe",
    ".key",
    ".pem",
    ".pyc",
    ".pyo",
    ".zip",
}

FORBIDDEN_REQUIREMENTS = {
    "flask",
    "flask-cors",
    "gunicorn",
    "psycopg2",
    "psycopg2-binary",
}


def main() -> int:
    args = _parse_args()
    report: list[str] = []
    _add_report_header(report)

    try:
        requirements = _audit_requirements(report)
        summary = _regenerar_paquete(report)
        _validar_paquete_limpio(report)
        _validar_import_basico(report)

        if args.check_only:
            report.append("")
            report.append("RESULTADO: verificacion previa correcta. No se ejecuto PyInstaller.")
            _write_report(report)
            print(f"Verificacion correcta. Reporte: {REPORT_PATH}")
            return 0

        _verificar_pyinstaller(report)
        _ejecutar_pyinstaller(report)
        _validar_exe_generado(report)

        report.append("")
        report.append("RESULTADO: build PyInstaller finalizado.")
        report.append(f"EXE: {EXE_PATH}")
        _write_report(report)
        print(f"EXE generado: {EXE_PATH}")
        return 0
    except Exception as exc:
        report.append("")
        report.append(f"RESULTADO: error - {exc}")
        _write_report(report)
        print(f"No se pudo preparar el build: {exc}")
        print(f"Reporte: {REPORT_PATH}")
        return 1


def _parse_args():
    parser = argparse.ArgumentParser(description="Build interno Hilorama Cliente")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Regenera y audita el paquete, pero no ejecuta PyInstaller.",
    )
    return parser.parse_args()


def _add_report_header(report: list[str]) -> None:
    api_base_url = _api_base_url_para_reporte()
    app_version, manifest_url = _updater_config_para_reporte()
    report.extend([
        "REPORTE BUILD EXE HILORAMA CLIENTE",
        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Proyecto: {PROJECT_ROOT}",
        f"Paquete fuente: {PACKAGE_ROOT}",
        f"Spec: {SPEC_PATH}",
        f"Version cliente: {app_version}",
        f"API base URL configurada: {api_base_url}",
        f"Update manifest URL: {manifest_url or 'No configurada'}",
        "La API base URL no es DATABASE_URL ni conexion directa a base local.",
        "HILORAMA_RENDER_API_BASE_URL tiene prioridad para pruebas locales.",
        "El modulo updater se incluye en el cliente.",
        "",
    ])


def _api_base_url_para_reporte() -> str:
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from hilorama_desktop.config import get_api_base_url

        return get_api_base_url()
    except Exception:
        return "No disponible"


def _updater_config_para_reporte() -> tuple[str, str]:
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from hilorama_desktop.config import APP_VERSION, get_update_manifest_url

        return APP_VERSION, get_update_manifest_url()
    except Exception:
        return "No disponible", ""


def _audit_requirements(report: list[str]) -> list[str]:
    req_path = PROJECT_ROOT / "hilorama_desktop" / "requirements_cliente.txt"
    if not req_path.exists():
        raise RuntimeError("No existe hilorama_desktop/requirements_cliente.txt")

    requirements = [
        line.strip()
        for line in req_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    normalized = {line.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].strip().lower() for line in requirements}
    forbidden = sorted(normalized & FORBIDDEN_REQUIREMENTS)
    if forbidden:
        raise RuntimeError("requirements_cliente incluye dependencias de servidor: " + ", ".join(forbidden))

    report.append("DEPENDENCIAS CLIENTE")
    report.extend(f"- {item}" for item in requirements)
    report.append("- Sin Flask, gunicorn, psycopg2 ni dependencias backend.")
    return requirements


def _regenerar_paquete(report: list[str]) -> dict:
    sys.path.insert(0, str(PROJECT_ROOT))
    from hilorama_desktop.build_client_package import build_client_package

    summary = build_client_package()
    report.append("")
    report.append("PAQUETE LIMPIO")
    report.append(f"- Ruta: {summary['package_root']}")
    report.append(f"- Archivos copiados: {summary['copied_files']}")
    report.append(f"- Reporte paquete: {summary['report_path']}")
    return summary


def _validar_paquete_limpio(report: list[str]) -> None:
    if not PACKAGE_ROOT.exists():
        raise RuntimeError("No existe dist_cliente/HiloramaCliente")

    problemas: list[str] = []
    textos_prohibidos = [
        value
        for value in (
            os.environ.get("HILORAMA_FORBIDDEN_LEGACY_KEY", "").strip(),
        )
        if value
    ]
    for path in PACKAGE_ROOT.rglob("*"):
        relative = path.relative_to(PACKAGE_ROOT)
        parts_lower = {part.lower() for part in relative.parts}
        if path.is_dir():
            if path.name.lower() in FORBIDDEN_DIRS:
                problemas.append(f"Directorio prohibido: {relative.as_posix()}")
            continue

        if parts_lower & FORBIDDEN_DIRS:
            problemas.append(f"Archivo dentro de directorio prohibido: {relative.as_posix()}")
        if path.name.lower() in FORBIDDEN_FILE_NAMES:
            problemas.append(f"Archivo sensible prohibido: {relative.as_posix()}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problemas.append(f"Extension prohibida: {relative.as_posix()}")
        if path.suffix.lower() in {".py", ".txt", ".json", ".md", ".cfg", ".ini"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for texto_prohibido in textos_prohibidos:
                if texto_prohibido in text:
                    problemas.append(f"Texto sensible prohibido en paquete: {relative.as_posix()}")

    if problemas:
        raise RuntimeError("Paquete cliente no esta limpio:\n" + "\n".join(problemas[:30]))

    report.append("")
    report.append("VALIDACION PAQUETE")
    report.append("- No contiene backend, Central, database, celular, comprobantes, logs ni .env.")
    report.append("- No contiene pyc, zip, exe ni llaves.")
    if textos_prohibidos:
        report.append("- No contiene los textos sensibles configurados para auditoria local.")


def _validar_import_basico(report: list[str]) -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("HILORAMA_RENDER_API_BASE_URL", None)
    env["HILORAMA_DATA_MODE"] = "api"
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    code = (
        "import os; "
        "assert 'DATABASE_URL' not in os.environ; "
        "assert 'HILORAMA_RENDER_API_BASE_URL' not in os.environ; "
        "from hilorama_desktop.config import RENDER_API_BASE_URL; "
        "import hilorama_desktop.main; "
        "print('IMPORT_OK', RENDER_API_BASE_URL)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PACKAGE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError("Import basico fallo:\n" + (result.stderr or result.stdout))

    report.append("")
    report.append("PRUEBA SIN DATABASE_URL")
    report.append("- Import basico de hilorama_desktop.main correcto en modo API.")
    report.append(f"- Resultado: {result.stdout.strip()}")


def _verificar_pyinstaller(report: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "PyInstaller no esta instalado. Instala con: "
            f"{sys.executable} -m pip install pyinstaller"
        )
    report.append("")
    report.append(f"PYINSTALLER: {result.stdout.strip()}")


def _ejecutar_pyinstaller(report: list[str]) -> None:
    if not SPEC_PATH.exists():
        raise RuntimeError("No existe hilorama_desktop/HiloramaCliente.spec")

    EXE_DIST.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HILORAMA_PYINSTALLER_SOURCE"] = str(PACKAGE_ROOT)
    env.setdefault("HILORAMA_DATA_MODE", "api")
    env.pop("DATABASE_URL", None)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(EXE_DIST),
        "--workpath",
        str(WORK_DIR),
        str(SPEC_PATH),
    ]
    report.append("")
    report.append("COMANDO PYINSTALLER")
    report.append(" ".join(f'"{part}"' if " " in part else part for part in cmd))

    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )
    report.append("")
    report.append("SALIDA PYINSTALLER")
    report.append(result.stdout[-6000:])
    if result.stderr:
        report.append("")
        report.append("ERRORES/WARNINGS PYINSTALLER")
        report.append(result.stderr[-6000:])
    if result.returncode != 0:
        raise RuntimeError("PyInstaller fallo. Revisa REPORTE_BUILD_EXE.txt")


def _validar_exe_generado(report: list[str]) -> None:
    if not EXE_PATH.exists():
        raise RuntimeError(f"No se encontro el exe esperado: {EXE_PATH}")
    size_mb = EXE_PATH.stat().st_size / (1024 * 1024)
    report.append("")
    report.append("EXE")
    report.append(f"- Ruta: {EXE_PATH}")
    report.append(f"- Tamano: {size_mb:.2f} MB")


def _write_report(report: list[str]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
