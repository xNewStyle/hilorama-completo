"""Auditoria general segura y reutilizable para el backend."""

from __future__ import annotations

import json
import re
from typing import Any


_CLAVES_SENSIBLES = (
    "password",
    "contrasena",
    "contraseña",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "authorization",
    "clave",
    "cookie",
    "session",
)

_PATRON_TEXTO_SENSIBLE = re.compile(
    r"(?i)\b(password|contras(?:ena|eña)|token|access_token|refresh_token|"
    r"authorization|api[_-]?key|secret|clave(?:_autorizacion)?|cookie|session)\b"
    r"\s*([:=])\s*(?:bearer\s+)?[^\s,;]+"
)
_PATRON_URL_CREDENCIALES = re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql)://[^\s,;]+")


def limpiar_texto_sensible(valor: Any) -> str:
    """Oculta valores sensibles incrustados en descripciones y errores."""
    texto = str(valor or "")
    texto = _PATRON_TEXTO_SENSIBLE.sub(lambda match: f"{match.group(1)}{match.group(2)}[oculto]", texto)
    return _PATRON_URL_CREDENCIALES.sub("[oculto]", texto)


def limpiar_datos_sensibles(valor: Any):
    """Elimina secretos antes de persistir datos de auditoria."""
    if isinstance(valor, dict):
        limpio = {}
        for clave, contenido in valor.items():
            nombre = str(clave).strip().casefold()
            if any(sensible in nombre for sensible in _CLAVES_SENSIBLES):
                limpio[str(clave)] = "[oculto]"
            else:
                limpio[str(clave)] = limpiar_datos_sensibles(contenido)
        return limpio
    if isinstance(valor, (list, tuple)):
        return [limpiar_datos_sensibles(item) for item in valor]
    if isinstance(valor, str):
        return limpiar_texto_sensible(valor)
    return valor


def diferencias_relevantes(anterior: dict[str, Any] | None, nuevo: dict[str, Any] | None, campos=None):
    anterior = dict(anterior or {})
    nuevo = dict(nuevo or {})
    claves = list(campos or sorted(set(anterior) | set(nuevo)))
    antes, despues = {}, {}
    for clave in claves:
        if anterior.get(clave) != nuevo.get(clave):
            antes[clave] = anterior.get(clave)
            despues[clave] = nuevo.get(clave)
    return limpiar_datos_sensibles(antes), limpiar_datos_sensibles(despues)


def _json_seguro(valor: Any):
    return json.dumps(limpiar_datos_sensibles(valor), ensure_ascii=False, default=str, separators=(",", ":"))


def registrar_auditoria(
    conn,
    columnas: set[str],
    *,
    accion: str,
    modulo: str,
    entidad_tipo: str | None = None,
    entidad_id: str | int | None = None,
    descripcion: str | None = None,
    datos_anteriores: dict[str, Any] | None = None,
    datos_nuevos: dict[str, Any] | None = None,
    resultado: str = "OK",
    codigo_error: str | None = None,
    usuario_id: int | None = None,
    cliente_sistema_id: int | None = None,
    device_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> int | None:
    if not columnas:
        raise RuntimeError("Falta la tabla auditoria_general. Aplica la migracion FASE 9B.")
    valores = {
        "cliente_sistema_id": cliente_sistema_id,
        "usuario_id": usuario_id,
        "accion": str(accion or "").strip() or "ACCION_SIN_NOMBRE",
        "modulo": str(modulo or "").strip() or "GENERAL",
        "entidad_tipo": str(entidad_tipo or "").strip() or None,
        "entidad_id": str(entidad_id) if entidad_id not in (None, "") else None,
        "descripcion": limpiar_texto_sensible(descripcion).strip() or None,
        "datos_anteriores_json": _json_seguro(datos_anteriores),
        "datos_nuevos_json": _json_seguro(datos_nuevos),
        "resultado": str(resultado or "OK").strip() or "OK",
        "codigo_error": limpiar_texto_sensible(codigo_error).strip() or None,
        "ip": limpiar_texto_sensible(ip).strip() or None,
        "user_agent": limpiar_texto_sensible(user_agent).strip()[:500] or None,
        "device_id": str(device_id or "").strip() or None,
        "request_id": limpiar_texto_sensible(request_id).strip() or None,
    }
    campos = [campo for campo in valores if campo in columnas]
    if not campos:
        raise RuntimeError("La tabla auditoria_general no tiene columnas compatibles.")
    placeholders = ",".join(["%s"] * len(campos))
    retorno = " RETURNING id" if "id" in columnas else ""
    row = conn.execute(
        f"INSERT INTO auditoria_general({','.join(campos)}) VALUES ({placeholders}){retorno}",
        tuple(valores[campo] for campo in campos),
    ).fetchone() if retorno else None
    return dict(row or {}).get("id") if row else None
