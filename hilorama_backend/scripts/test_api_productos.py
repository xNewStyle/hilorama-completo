"""Prueba local segura para endpoints de lectura de productos/almacen.

Uso recomendado:
    python hilorama_backend/scripts/test_api_productos.py

Variables opcionales:
    HILORAMA_RENDER_API_BASE_URL
    HILORAMA_TEST_USER
    HILORAMA_TEST_PASSWORD
    HILORAMA_TEST_LICENSE
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


DEFAULT_BASE_URL = "http://127.0.0.1:10000"
TIMEOUT = 15
REQUIRED_PRODUCT_FIELDS = {
    "id",
    "codigo",
    "marca",
    "hilo",
    "color",
    "stock",
    "estado",
    "precio_venta",
    "costo_neto",
    "tipo_producto",
    "es_inventariable",
}


class ApiTestError(Exception):
    def __init__(self, message, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def main():
    args = _parse_args()
    base_url = (args.base_url or os.environ.get("HILORAMA_RENDER_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    print("Prueba API productos/almacen Hilorama")
    print(f"Backend: {base_url}")
    print("Modo: solo lectura para productos/almacen")
    print("")

    usuario = args.usuario or os.environ.get("HILORAMA_TEST_USER") or input("Usuario: ").strip()
    password = args.password or os.environ.get("HILORAMA_TEST_PASSWORD")
    if not password:
        password = getpass.getpass("Contrasena: ")
    licencia = args.licencia or os.environ.get("HILORAMA_TEST_LICENSE") or ""

    try:
        token = _login(base_url, usuario, password, licencia)
    except ApiTestError as exc:
        _print_login_error(exc)
        return 1

    print("Login OK. Token recibido y oculto.")
    print("")

    fallos = 0
    productos = []
    marcas = []

    ok, data = _probar_endpoint(
        "GET /api/productos",
        lambda: _request_json(base_url, "GET", "/api/productos", token=token, params={"limit": 10}),
        validar=_validar_productos,
    )
    fallos += 0 if ok else 1
    if ok:
        productos = data.get("productos") or []

    ok, data = _probar_endpoint(
        "GET /api/marcas",
        lambda: _request_json(base_url, "GET", "/api/marcas", token=token),
        validar=_validar_marcas,
    )
    fallos += 0 if ok else 1
    if ok:
        marcas = data.get("marcas") or []

    ok, _ = _probar_endpoint(
        "GET /api/hilos",
        lambda: _request_json(base_url, "GET", "/api/hilos", token=token),
        validar=_validar_hilos,
    )
    fallos += 0 if ok else 1

    if marcas:
        marca = marcas[0]
        ok, _ = _probar_endpoint(
            f"GET /api/hilos?marca={marca}",
            lambda: _request_json(base_url, "GET", "/api/hilos", token=token, params={"marca": marca}),
            validar=_validar_hilos,
        )
        fallos += 0 if ok else 1

    ok, _ = _probar_endpoint(
        "GET /api/almacen/resumen",
        lambda: _request_json(base_url, "GET", "/api/almacen/resumen", token=token),
        validar=_validar_resumen,
    )
    fallos += 0 if ok else 1

    if productos:
        producto = productos[0]
        producto_id = producto.get("id")
        codigo = producto.get("codigo")

        if producto_id is not None:
            ok, _ = _probar_endpoint(
                f"GET /api/productos/{producto_id}",
                lambda: _request_json(base_url, "GET", f"/api/productos/{producto_id}", token=token),
                validar=_validar_producto_unico,
            )
            fallos += 0 if ok else 1

        if codigo:
            ok, _ = _probar_endpoint(
                f"GET /api/productos/codigo/{codigo}",
                lambda: _request_json(
                    base_url,
                    "GET",
                    f"/api/productos/codigo/{urllib.parse.quote(str(codigo), safe='')}",
                    token=token,
                ),
                validar=_validar_producto_unico,
            )
            fallos += 0 if ok else 1
    else:
        print("INFO: /api/productos no devolvio productos; se omiten pruebas por id/codigo.")

    print("")
    if fallos:
        print(f"Resultado: FALLARON {fallos} validaciones. Revise mensajes anteriores y logs backend.")
        return 1

    print("Resultado: OK. Endpoints de productos/almacen respondieron con estructura esperada.")
    print("Campos para migrar core/almacen_api.py: suficientes para lectura inicial.")
    return 0


def _parse_args():
    parser = argparse.ArgumentParser(description="Prueba endpoints API productos/almacen Hilorama.")
    parser.add_argument("--base-url", default=None, help="URL base del backend. Default: HILORAMA_RENDER_API_BASE_URL o localhost.")
    parser.add_argument("--usuario", default=None, help="Usuario de prueba. Tambien HILORAMA_TEST_USER.")
    parser.add_argument("--password", default=None, help="Password de prueba. Tambien HILORAMA_TEST_PASSWORD.")
    parser.add_argument("--licencia", default=None, help="Licencia/negocio opcional. Tambien HILORAMA_TEST_LICENSE.")
    return parser.parse_args()


def _login(base_url, usuario, password, licencia):
    payload = {
        "usuario": usuario,
        "password": password,
        "licencia": licencia or "",
        "modulo_actual": "api_productos_test",
        **_device_profile(),
    }
    data = _request_json(base_url, "POST", "/api/auth/login", payload=payload)
    if not data.get("permitido"):
        raise ApiTestError("Login falló. Revisa usuario, contraseña o licencia.", status=403, detail=data)
    token = data.get("token")
    if not token:
        raise ApiTestError("Login falló. El backend no devolvió token.", detail=data)
    return token


def _device_profile():
    raw = "|".join([
        platform.node() or "equipo",
        platform.system() or "sistema",
        platform.release() or "release",
        str(uuid.getnode()),
    ])
    return {
        "device_id_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "nombre_equipo": platform.node() or "equipo",
        "sistema_operativo": f"{platform.system()} {platform.release()}".strip(),
        "app_version": "api-productos-test",
    }


def _request_json(base_url, method, path, payload=None, token=None, params=None):
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        path = f"{path}?{query}"

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = _json_error_detail(exc)
        raise ApiTestError(_message_for_status(exc.code), status=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise ApiTestError(
            "Backend no disponible. Levanta hilorama_backend/app.py primero.",
            detail=str(exc.reason),
        ) from exc
    except TimeoutError as exc:
        raise ApiTestError("Backend no disponible. Levanta hilorama_backend/app.py primero.", detail="timeout") from exc
    except json.JSONDecodeError as exc:
        raise ApiTestError("Respuesta no es JSON valido.", detail=str(exc)) from exc


def _json_error_detail(exc):
    try:
        raw = exc.read().decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _message_for_status(status):
    if status == 401:
        return "No autorizado."
    if status == 403:
        return "Licencia o cliente bloqueado/suspendido/vencido."
    if status == 500:
        return "Error 500. Revise logs backend."
    return f"Solicitud rechazada por backend. HTTP {status}."


def _probar_endpoint(nombre, llamada, validar):
    print(f"Probando {nombre}...")
    try:
        data = llamada()
        validar(data)
        _imprimir_resumen(nombre, data)
        return True, data
    except ApiTestError as exc:
        print(f"  FAIL: {exc}")
        if exc.status:
            print(f"  HTTP: {exc.status}")
        return False, None
    except AssertionError as exc:
        print(f"  FAIL validacion: {exc}")
        return False, None


def _validar_productos(data):
    assert data.get("ok") is True, "ok debe ser true"
    productos = data.get("productos")
    assert isinstance(productos, list), "productos debe ser lista"
    assert isinstance(data.get("total"), int), "total debe ser entero"
    if productos:
        faltantes = REQUIRED_PRODUCT_FIELDS - set(productos[0])
        assert not faltantes, f"faltan campos en producto: {', '.join(sorted(faltantes))}"


def _validar_producto_unico(data):
    assert data.get("ok") is True, "ok debe ser true"
    producto = data.get("producto")
    assert isinstance(producto, dict), "producto debe ser objeto"
    faltantes = REQUIRED_PRODUCT_FIELDS - set(producto)
    assert not faltantes, f"faltan campos en producto: {', '.join(sorted(faltantes))}"


def _validar_marcas(data):
    assert data.get("ok") is True, "ok debe ser true"
    assert isinstance(data.get("marcas"), list), "marcas debe ser lista"


def _validar_hilos(data):
    assert data.get("ok") is True, "ok debe ser true"
    assert isinstance(data.get("hilos"), list), "hilos debe ser lista"


def _validar_resumen(data):
    assert data.get("ok") is True, "ok debe ser true"
    assert isinstance(data.get("grupos"), list), "grupos debe ser lista"
    total_general = data.get("total_general")
    assert isinstance(total_general, dict), "total_general debe ser objeto"
    for campo in ("piezas", "valor_costo", "valor_venta", "ganancia_estimada"):
        assert campo in total_general, f"falta {campo} en total_general"


def _imprimir_resumen(nombre, data):
    if "productos" in data:
        print(f"  OK productos={len(data.get('productos') or [])} total={data.get('total')}")
    elif "producto" in data:
        producto = data.get("producto") or {}
        print(f"  OK producto={producto.get('codigo')} {producto.get('marca')} {producto.get('hilo')}")
    elif "marcas" in data:
        print(f"  OK marcas={len(data.get('marcas') or [])}")
    elif "hilos" in data:
        print(f"  OK hilos={len(data.get('hilos') or [])}")
    elif "total_general" in data:
        total = data.get("total_general") or {}
        print(
            "  OK resumen "
            f"piezas={total.get('piezas')} "
            f"valor_venta={total.get('valor_venta')}"
        )
    else:
        print(f"  OK {nombre}")


def _print_login_error(exc):
    if exc.status == 401:
        print("Login falló. Revisa usuario, contraseña o licencia.")
    elif exc.status == 403:
        print("Licencia o cliente bloqueado/suspendido/vencido.")
    else:
        print(str(exc))


if __name__ == "__main__":
    sys.exit(main())
