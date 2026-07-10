"""Crea una carpeta limpia de Hilorama Cliente para modo API.

No compila exe y no modifica los archivos originales del proyecto.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "dist_cliente"
PACKAGE_ROOT = OUTPUT_ROOT / "HiloramaCliente"
REPORT_NAME = "REPORTE_PAQUETE_CLIENTE.txt"


ROOT_FILES = {
    "main_ventas.py": "Modulo legacy de Ventas embebido por Desktop.",
    "almacen_colores.py": "Modulo legacy de Almacen embebido por Desktop.",
    "notas.py": "Notas/cotizaciones usadas por Ventas y visores.",
    "pagos.py": "Lectura y flujo de pagos/comprobantes migrado a API.",
    "clientes.py": "Clientes usados por Ventas y visores.",
    "pedidos.py": "Pedidos usados por Ventas.",
    "pedido_estado.py": "Pedido activo usado por Ventas.",
    "empacadores.py": "Empacadores usados por asignacion de pedidos.",
    "ver_cotizaciones.py": "Visor principal de notas/cotizaciones.",
    "ver_notas_completo.py": "Visor alterno de notas.",
    "ver_clientes.py": "Pantalla legacy de clientes.",
    "visor_imagen.py": "Visor de comprobantes/imagenes.",
    "ventas_logic.py": "Calculos auxiliares de ventas.",
    "parser_whatsapp.py": "Parser de listas usado por Ventas.",
    "ocr.py": "OCR usado por carga desde imagen.",
    "ui_imagen.py": "UI auxiliar de imagen/OCR.",
    "impresion_etiquetas.py": "Etiquetas de envio.",
    "pdf_cotizacion.py": "Generacion de PDF de cotizacion.",
    "generar_pdf_venta_premium.py": "Generacion de PDF premium.",
    "pdf_utils.py": "Utilidades de PDF.",
    "cp_api.py": "Busqueda de codigo postal.",
    "envios_config.py": "Calculo/configuracion local de envios.",
    "envios_config.json": "Configuracion no sensible de envios.",
    "cp_offline.json": "Catalogo offline de codigos postales.",
    "admin_errores.py": "Modulo legacy de errores, bloqueado en API para base local.",
    "admin_metricas.py": "Modulo legacy de metricas, bloqueado en API para base local.",
    "auditoria.py": "Auditoria legacy, bloqueada en API para base local.",
    "main.py": "Entrada legacy que importa main_ventas.",
    "requirements.txt": "Dependencias del cliente si existe.",
    "PlayfairDisplay-Italic.ttf": "Fuente usada por PDFs.",
    "logo_hilorama.png": "Logo de la aplicacion/PDF.",
    "marca_agua.png": "Marca de agua para PDFs.",
    "fondo_papel.jpg": "Fondo de PDF.",
    "fondo_premium.png": "Fondo premium de PDF.",
    "fondo_premium1.png": "Fondo premium alterno.",
    "marco.png": "Marco de PDF.",
    "mi_imagen.png": "Imagen decorativa de PDF.",
    "trash.png.png": "Icono de Ventas.",
    "shipping.png": "Icono de envio.",
    "edit.png": "Icono de edicion.",
    "edit_sale.png": "Icono de venta.",
    "convert.png": "Icono de convertir.",
    "asignar.png": "Icono de asignacion.",
}

INCLUDE_DIRS = {
    "hilorama_desktop": "Desktop, servicios API, seguridad local y UI.",
    "core": "Fachada de almacen usada por Ventas/Almacen.",
    "logo_hilorama": "Assets de logo.",
    "velluto": "Repositorio visual local de tonos/productos.",
}

EMPTY_RUNTIME_DIRS = (
    "cotizaciones_pdf",
    "ventas_pdf",
)

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "backups",
    "backups_central",
    "build",
    "comprobantes",
    "database",
    "dist",
    "dist_cliente",
    "hilorama-frontend",
    "hilorama_backend",
    "hilorama_celular",
    "hilorama_central",
    "logs",
    "migrations",
    "node_modules",
    "releases",
    "scripts",
    "venv",
    "wa_tester_reports",
}

EXCLUDED_NAMES = {
    ".env",
    ".ds_store",
    "_temp_comprobante.png",
    "credentials.json",
    "ia_hilorama_memoria.json",
    "ia_ventas_programa_v14.py",
    "preparar_zip_revision.py",
    "secrets.json",
    "thumbs.db",
    "ver_estructura.py",
}

EXCLUDED_RELATIVE = {
    Path("hilorama_desktop") / "HiloramaCliente.spec",
    Path("hilorama_desktop") / "build_exe.py",
    Path("hilorama_desktop") / "build_client_package.py",
    Path("hilorama_desktop") / "create_update_release.py",
    Path("hilorama_desktop") / "test_fase2_security.py",
}

EXCLUDED_SUFFIXES = {
    ".bak",
    ".db",
    ".exe",
    ".key",
    ".log",
    ".pdf",
    ".pem",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".temp",
    ".tmp",
    ".zip",
}

TEXT_SUFFIXES = {".py", ".json", ".txt", ".md", ".ini", ".cfg"}

RISK_PATTERNS = (
    (re.compile(r"\bPASSWORD(_OVERRIDE)?\s*="), "password hardcodeado"),
    (re.compile(r"\bDATABASE_URL\b"), "mencion a DATABASE_URL"),
    (re.compile(r"\bSECRET\b|\bapi_key\b|\bAPI_KEY\b|\brefresh_token\b", re.I), "posible secreto/token"),
    (re.compile(r"C:\\Users\\jorge|OneDrive\\Escritorio\\Hilorama", re.I), "ruta local absoluta"),
    (re.compile(r"TESSDATA_PREFIX", re.I), "ruta local de OCR"),
)


def main() -> int:
    summary = build_client_package()
    print(f"Paquete cliente creado en: {summary['package_root']}")
    print(f"Archivos copiados: {summary['copied_files']}")
    print(f"Reporte: {summary['report_path']}")
    return 0


def build_client_package() -> dict:
    _validate_project()
    _reset_output_dir()

    copied_files: list[str] = []
    skipped_sensitive: list[str] = []
    missing_optional: list[str] = []

    for relative_name in sorted(ROOT_FILES):
        source = PROJECT_ROOT / relative_name
        if not source.exists():
            missing_optional.append(relative_name)
            continue
        _copy_path(source, Path(relative_name), copied_files, skipped_sensitive)

    for dirname in sorted(INCLUDE_DIRS):
        source_dir = PROJECT_ROOT / dirname
        if not source_dir.exists():
            missing_optional.append(dirname)
            continue
        for source in sorted(source_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(PROJECT_ROOT)
            _copy_path(source, relative, copied_files, skipped_sensitive)

    for dirname in EMPTY_RUNTIME_DIRS:
        (PACKAGE_ROOT / dirname).mkdir(parents=True, exist_ok=True)

    risks = _scan_risks(copied_files)
    report_path = _write_report(copied_files, skipped_sensitive, missing_optional, risks)

    return {
        "package_root": PACKAGE_ROOT,
        "report_path": report_path,
        "copied_files": len(copied_files),
        "skipped_sensitive": skipped_sensitive,
        "missing_optional": missing_optional,
        "risks": risks,
    }


def _validate_project() -> None:
    required = (
        "hilorama_desktop/main.py",
        "hilorama_desktop/config.py",
        "main_ventas.py",
        "almacen_colores.py",
        "core",
    )
    missing = [item for item in required if not (PROJECT_ROOT / item).exists()]
    if missing:
        raise RuntimeError("Faltan archivos requeridos: " + ", ".join(missing))


def _reset_output_dir() -> None:
    output = PACKAGE_ROOT.resolve()
    allowed_parent = OUTPUT_ROOT.resolve()
    if output.exists():
        if allowed_parent not in output.parents:
            raise RuntimeError(f"Ruta de salida insegura: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def _copy_path(source: Path, relative: Path, copied_files: list[str], skipped_sensitive: list[str]) -> None:
    if _is_excluded(relative):
        if _is_sensitive(relative):
            skipped_sensitive.append(relative.as_posix())
        return

    destination = PACKAGE_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    copied_files.append(relative.as_posix())


def _is_excluded(relative: Path) -> bool:
    parts_lower = {part.lower() for part in relative.parts}
    if parts_lower & {part.lower() for part in EXCLUDED_DIRS}:
        return True

    if relative in EXCLUDED_RELATIVE:
        return True

    name = relative.name.lower()
    stem = relative.stem.lower()
    if name in {item.lower() for item in EXCLUDED_NAMES}:
        return True
    if name.startswith(("~", ".~", "~$", "_temp")):
        return True
    if "_temp" in stem or "temp_" in stem:
        return True
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def _is_sensitive(relative: Path) -> bool:
    name = relative.name.lower()
    return (
        name in {".env", "credentials.json", "secrets.json"}
        or relative.suffix.lower() in {".key", ".pem"}
        or "comprobante" in relative.as_posix().lower()
    )


def _scan_risks(copied_files: list[str]) -> list[str]:
    risks: list[str] = []
    for relative_text in copied_files:
        relative = Path(relative_text)
        if relative.suffix.lower() not in TEXT_SUFFIXES:
            continue
        path = PACKAGE_ROOT / relative
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            for pattern, label in RISK_PATTERNS:
                if pattern.search(line):
                    risks.append(f"{relative.as_posix()}:{number}: {label}")
                    break
            if len(risks) >= 120:
                risks.append("... auditoria truncada a 120 avisos")
                return risks
    return risks


def _api_base_url_para_reporte() -> str:
    try:
        from hilorama_desktop.config import get_api_base_url

        return get_api_base_url()
    except Exception:
        return "No disponible"


def _write_report(
    copied_files: list[str],
    skipped_sensitive: list[str],
    missing_optional: list[str],
    risks: list[str],
) -> Path:
    report_path = PACKAGE_ROOT / REPORT_NAME
    lines = [
        "REPORTE PAQUETE CLIENTE HILORAMA",
        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "Origen: proyecto Hilorama local",
        "Destino: dist_cliente/HiloramaCliente",
        "",
        "Este paquete es para Hilorama Cliente en modo API.",
        "No incluye backend, Hilorama Central, base local, scripts privados ni datos reales.",
        "No es un exe compilado.",
        "",
        "CONFIGURACION API CLIENTE",
        f"- API base URL configurada: {_api_base_url_para_reporte()}",
        "- La variable HILORAMA_RENDER_API_BASE_URL puede sobreescribirla para pruebas locales.",
        "- No usa conexion directa a base local.",
        "- Incluye modulo updater para revisar update.json.",
        "",
        "ARCHIVOS/DIRECTORIOS BASE INCLUIDOS",
    ]

    for name, reason in sorted(ROOT_FILES.items()):
        if (PACKAGE_ROOT / name).exists():
            lines.append(f"- {name}: {reason}")
    for name, reason in sorted(INCLUDE_DIRS.items()):
        if (PACKAGE_ROOT / name).exists():
            lines.append(f"- {name}/: {reason}")

    lines.extend([
        "",
        "EXCLUSIONES IMPORTANTES",
        "- hilorama_backend/",
        "- hilorama_central/",
        "- hilorama_celular/",
        "- database/",
        "- comprobantes/",
        "- logs/",
        "- backups/ y backups_central/",
        "- releases/ y dist/build previos",
        "- .env, llaves, credenciales, zips, exe, pyc, __pycache__",
        "- PDFs existentes de cotizaciones/ventas; solo se crean carpetas vacias para runtime.",
        "",
        f"TOTAL ARCHIVOS COPIADOS: {len(copied_files)}",
    ])

    if missing_optional:
        lines.append("")
        lines.append("OPCIONALES NO ENCONTRADOS")
        lines.extend(f"- {item}" for item in missing_optional)

    if skipped_sensitive:
        lines.append("")
        lines.append("SENSIBLES EXCLUIDOS")
        lines.extend(f"- {item}" for item in sorted(set(skipped_sensitive)))

    if risks:
        lines.append("")
        lines.append("RIESGOS A REVISAR EN ARCHIVOS INCLUIDOS")
        lines.append("No se imprimen valores completos; revisar antes de compilar exe.")
        lines.extend(f"- {item}" for item in risks)
    else:
        lines.append("")
        lines.append("RIESGOS A REVISAR EN ARCHIVOS INCLUIDOS")
        lines.append("- No se detectaron patrones sensibles basicos.")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


if __name__ == "__main__":
    raise SystemExit(main())
