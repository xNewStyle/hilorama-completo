"""Entrada principal de Hilorama Desktop.

Fase 1A: ventana base sin integrar todavia los modulos reales.
"""
from pathlib import Path
import sys


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
for path in (PROJECT_ROOT, APP_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

try:
    from .ui.main_window import run_app
    from .ui.login_window import solicitar_login
    from .services.auth_service import AuthService
    from .utils.logger import log_error, log_info
except ImportError:  # Permite ejecutar: python hilorama_desktop/main.py
    from ui.main_window import run_app
    from ui.login_window import solicitar_login
    from services.auth_service import AuthService
    from utils.logger import log_error, log_info


def main():
    log_info("hilorama_desktop", "Iniciando Hilorama Desktop")
    try:
        auth_service = AuthService()
        session = auth_service.require_access(modulo="desktop")
        if not session:
            log_info("hilorama_desktop", "Solicitando login de usuario")
            session = solicitar_login(auth_service=auth_service, modulo="desktop")
        if not session:
            log_info("hilorama_desktop", "Inicio cancelado: sin sesion autorizada")
            return
        log_info("hilorama_desktop", "Acceso validado, abriendo ventana principal")
        run_app(auth_service=auth_service, session=session)
    except Exception as exc:
        log_error("hilorama_desktop", "Error al iniciar Desktop o validar acceso", exc)
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "Hilorama Desktop",
                "Ocurrió un error al iniciar. Se guardó el detalle en logs."
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
