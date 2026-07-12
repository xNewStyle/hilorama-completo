# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


source_root = Path(os.environ.get("HILORAMA_PYINSTALLER_SOURCE", Path.cwd())).resolve()
entrypoint = source_root / "hilorama_desktop" / "main.py"

if not entrypoint.exists():
    raise SystemExit(f"No existe entrypoint: {entrypoint}")


def _safe_collect_data(package_name):
    try:
        return collect_data_files(package_name)
    except Exception:
        return []


def _safe_collect_submodules(package_name):
    try:
        return collect_submodules(package_name)
    except Exception:
        return [package_name]


datas = []

for package in ("customtkinter", "tkinterdnd2", "tzdata"):
    datas += _safe_collect_data(package)

root_assets = (
    "PlayfairDisplay-Italic.ttf",
    "logo_hilorama.png",
    "marca_agua.png",
    "fondo_papel.jpg",
    "fondo_premium.png",
    "fondo_premium1.png",
    "marco.png",
    "mi_imagen.png",
    "trash.png.png",
    "shipping.png",
    "edit.png",
    "edit_sale.png",
    "convert.png",
    "asignar.png",
    "cp_offline.json",
    "envios_config.json",
)

for name in root_assets:
    path = source_root / name
    if path.exists():
        datas.append((str(path), "."))

for dirname in ("logo_hilorama", "velluto"):
    path = source_root / dirname
    if path.exists():
        datas.append((str(path), dirname))


hiddenimports = []
for package in (
    "customtkinter",
    "tkinterdnd2",
    "PIL",
    "reportlab",
    "pytesseract",
    "barcode",
    "qrcode",
    "tzdata",
    "hilorama_desktop.updater",
):
    hiddenimports += _safe_collect_submodules(package)


excludes = [
    "flask",
    "flask_cors",
    "gunicorn",
    "psycopg2",
    "psycopg2_binary",
    "database",
    "hilorama_backend",
    "hilorama_central",
    "hilorama_celular",
]


a = Analysis(
    [str(entrypoint)],
    pathex=[str(source_root)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HiloramaCliente",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
