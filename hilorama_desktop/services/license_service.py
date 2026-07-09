"""Helpers de licencia para validaciones puntuales."""

try:
    from .auth_service import AuthService
except ImportError:
    from auth_service import AuthService


def validar_acceso(modulo="desktop"):
    return AuthService().require_access(modulo=modulo)
