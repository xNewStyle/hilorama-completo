from core.almacen_api import obtener_producto_por_codigo_barras

from flask_cors import CORS
from flask import Flask, request, jsonify, render_template



app = Flask(__name__)
CORS(app)
import hashlib
import json
import os
import time
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

SECRET = "MI_CLAVE_INTERNA_ULTRA_SECRETA"
def generar_token(empacador_id):
    timestamp = int(time.time())
    raw = f"{empacador_id}.{timestamp}.{SECRET}"
    firma = hashlib.sha256(raw.encode()).hexdigest()
    return f"{empacador_id}.{timestamp}.{firma}"


# =========================
# VALIDAR TOKEN
# =========================
import time

def validar_token(req):
    auth = req.headers.get("Authorization")

    if not auth or not auth.startswith("Bearer "):
        return None

    token = auth.replace("Bearer ", "")

    try:
        empacador_id, timestamp, firma = token.split(".")

        raw = f"{empacador_id}.{timestamp}.{SECRET}"
        firma_correcta = hashlib.sha256(raw.encode()).hexdigest()

        if firma != firma_correcta:
            return None

        # 🔒 EXPIRACIÓN 8 HORAS
        if int(time.time()) - int(timestamp) > 60 * 60 * 8:
            return None

        empacador_id = int(empacador_id)

        with get_conn() as conn:
            row = conn.execute("""
                SELECT id, rol
                FROM empacadores
                WHERE id=%s AND activo=TRUE
            """,(empacador_id,)).fetchone()


        if not row:
            return None

        return {
            "empacador_id": row["id"],
            "rol": row["rol"]
        }

    except:
        return None



# =========================
# HOME
# =========================

def evaluar_estado_nota(nota):
    total = 0
    requeridas = 0

    for p in nota["productos"]:
        total += p["pz_empacadas"]
        requeridas += p["pz_requeridas"]

    if total == 0:
        nota["estado"] = "EN_PROCESO"
    elif total < requeridas:
        nota["estado"] = "INCOMPLETA"
    else:
        nota["estado"] = "COMPLETA"


from database.connection import get_conn
try:
    from hilorama_backend.services.productos_service import (
        listar_hilos,
        listar_marcas,
        listar_precios,
        listar_productos,
        obtener_producto_por_codigo as api_obtener_producto_por_codigo,
        obtener_producto_por_id,
        obtener_precio_producto,
        obtener_precios_marca,
        resumen_almacen,
    )
except ImportError:
    from services.productos_service import (
        listar_hilos,
        listar_marcas,
        listar_precios,
        listar_productos,
        obtener_producto_por_codigo as api_obtener_producto_por_codigo,
        obtener_producto_por_id,
        obtener_precio_producto,
        obtener_precios_marca,
        resumen_almacen,
    )

def registrar_error(nota_id, codigo, empacador_id, motivo):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO errores_scan (
                nota_id,
                empacador_id,
                codigo,
                motivo
            )
            VALUES (%s,%s,%s,%s)
        """,(nota_id, empacador_id, codigo, motivo))





@app.route("/")
def home():
    return {"status": "Hilorama backend activo"}

# =========================
# LOGIN
# =========================
from database.connection import get_conn

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    usuario = data.get("usuario")
    password = data.get("password")

    with get_conn() as conn:
        row = conn.execute("""
            SELECT id, nombre, password, rol
            FROM empacadores
            WHERE usuario=%s AND activo=TRUE
        """,(usuario,)).fetchone()

        if not row or row["password"] != password:
            return jsonify({"error": "Credenciales inválidas"}), 401


    token = generar_token(row["id"])



    return jsonify({
        "token": token,
        "nombre": row["nombre"],
        "empacador_id": row["id"],
        "rol": row["rol"]
    })

        

 
# =========================
# FASE 2 - CONTROL DE ACCESO DESKTOP
# =========================
ESTADOS_CLIENTE_BLOQUEO = {
    "suspendido",
    "vencido",
    "bloqueado",
    "bloqueado_permanente",
}


def _body_json():
    return request.get_json(silent=True) or {}


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _check_password_sistema(password_hash, password):
    if not password_hash or not password:
        return False
    try:
        if password_hash.startswith("$2"):
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        from werkzeug.security import check_password_hash
        return check_password_hash(password_hash, password)
    except Exception:
        return False


def _hash_password_sistema(password):
    if not password:
        raise ValueError("La contrasena es obligatoria.")
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    except Exception:
        from werkzeug.security import generate_password_hash
        return generate_password_hash(password)


def _registrar_evento_licencia(conn, cliente_id, usuario_id, device_id_hash, evento, detalle=""):
    conn.execute("""
        INSERT INTO licencias_eventos (
            cliente_id, usuario_id, device_id_hash, evento, detalle, ip
        )
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (
        cliente_id,
        usuario_id,
        device_id_hash,
        evento,
        detalle,
        request.headers.get("X-Forwarded-For", request.remote_addr),
    ))


def _auth_sistema(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token_hash = _hash_token(auth.replace("Bearer ", "", 1))
    ttl_hours = int(os.environ.get("HILORAMA_SESSION_TTL_HOURS", "8"))

    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                s.id AS sesion_id,
                s.cliente_id,
                s.usuario_id,
                s.device_id_hash,
                s.estado AS sesion_estado,
                s.created_at AS sesion_created_at,
                u.nombre AS usuario_nombre,
                u.usuario,
                u.rol,
                c.nombre_negocio,
                c.estado AS cliente_estado,
                c.fecha_vencimiento
            FROM sesiones_activas s
            JOIN usuarios_sistema u ON u.id = s.usuario_id
            JOIN clientes_sistema c ON c.id = s.cliente_id
            WHERE s.token_hash=%s
              AND s.estado IN ('activa','bloqueada')
              AND s.created_at >= NOW() - (%s * INTERVAL '1 hour')
              AND u.activo=TRUE
        """, (token_hash, ttl_hours)).fetchone()

    return row


def _cliente_permitido(row):
    if row.get("sesion_estado") == "bloqueada":
        return False, "bloqueado", "Sesion bloqueada."
    estado = row.get("cliente_estado") or row.get("estado")
    if estado in ESTADOS_CLIENTE_BLOQUEO:
        return False, estado, f"Licencia {estado}."
    fecha_vencimiento = row.get("fecha_vencimiento")
    if fecha_vencimiento and fecha_vencimiento < date.today():
        return False, "vencido", "Licencia vencida."
    return True, "activo", "Acceso permitido."


def _respuesta_sesion(row, token=None, permitido=True, estado="activo", mensaje="Acceso permitido."):
    data = {
        "permitido": permitido,
        "estado": estado,
        "mensaje": mensaje,
        "permisos": [row.get("rol")] if row.get("rol") else [],
        "usuario": {
            "id": row.get("usuario_id") or row.get("id"),
            "nombre": row.get("usuario_nombre") or row.get("nombre"),
            "usuario": row.get("usuario"),
            "rol": row.get("rol"),
        },
        "cliente": {
            "id": row.get("cliente_id"),
            "nombre_negocio": row.get("nombre_negocio"),
        },
    }
    if token:
        data["token"] = token
    return jsonify(data)


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = _body_json()
    usuario = (data.get("usuario") or "").strip()
    password = data.get("password") or ""
    device_id_hash = data.get("device_id_hash") or ""
    modulo_actual = data.get("modulo_actual") or "desktop"

    if not usuario or not password or not device_id_hash:
        return jsonify({"permitido": False, "estado": "rechazado", "mensaje": "Datos incompletos"}), 400

    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                u.id AS usuario_id,
                u.cliente_id,
                u.nombre AS usuario_nombre,
                u.usuario,
                u.password_hash,
                u.rol,
                c.nombre_negocio,
                c.estado AS cliente_estado,
                c.fecha_vencimiento,
                c.max_dispositivos
            FROM usuarios_sistema u
            JOIN clientes_sistema c ON c.id = u.cliente_id
            WHERE u.usuario=%s
              AND u.activo=TRUE
        """, (usuario,)).fetchone()

        if not row or not _check_password_sistema(row["password_hash"], password):
            return jsonify({"permitido": False, "estado": "rechazado", "mensaje": "Credenciales invalidas"}), 401

        permitido, estado, mensaje = _cliente_permitido(row)
        if not permitido:
            _registrar_evento_licencia(conn, row["cliente_id"], row["usuario_id"], device_id_hash, "login_bloqueado", estado)
            return _respuesta_sesion(row, permitido=False, estado=estado, mensaje=mensaje), 403

        dispositivo = conn.execute("""
            SELECT id, estado
            FROM dispositivos_autorizados
            WHERE cliente_id=%s AND device_id_hash=%s
        """, (row["cliente_id"], device_id_hash)).fetchone()

        if dispositivo and dispositivo["estado"] == "bloqueado":
            return _respuesta_sesion(row, permitido=False, estado="bloqueado", mensaje="Dispositivo bloqueado."), 403

        if not dispositivo:
            total = conn.execute("""
                SELECT COUNT(*) AS total
                FROM dispositivos_autorizados
                WHERE cliente_id=%s AND estado='activo'
            """, (row["cliente_id"],)).fetchone()["total"]
            if total >= row["max_dispositivos"]:
                return _respuesta_sesion(row, permitido=False, estado="bloqueado", mensaje="Limite de dispositivos alcanzado."), 403
            conn.execute("""
                INSERT INTO dispositivos_autorizados (
                    cliente_id, usuario_id, device_id_hash, nombre_equipo,
                    sistema_operativo, app_version, estado, ultimo_acceso, ultima_ip
                )
                VALUES (%s,%s,%s,%s,%s,%s,'activo',NOW(),%s)
            """, (
                row["cliente_id"],
                row["usuario_id"],
                device_id_hash,
                data.get("nombre_equipo"),
                data.get("sistema_operativo"),
                data.get("app_version"),
                request.headers.get("X-Forwarded-For", request.remote_addr),
            ))
        else:
            conn.execute("""
                UPDATE dispositivos_autorizados
                SET usuario_id=%s, nombre_equipo=%s, sistema_operativo=%s,
                    app_version=%s, ultimo_acceso=NOW(), ultima_ip=%s, updated_at=NOW()
                WHERE id=%s
            """, (
                row["usuario_id"],
                data.get("nombre_equipo"),
                data.get("sistema_operativo"),
                data.get("app_version"),
                request.headers.get("X-Forwarded-For", request.remote_addr),
                dispositivo["id"],
            ))

        token = secrets.token_urlsafe(32)
        conn.execute("""
            INSERT INTO sesiones_activas (
                cliente_id, usuario_id, device_id_hash, token_hash, modulo_actual,
                app_version, ip, ultimo_heartbeat, estado
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),'activa')
        """, (
            row["cliente_id"],
            row["usuario_id"],
            device_id_hash,
            _hash_token(token),
            modulo_actual,
            data.get("app_version"),
            request.headers.get("X-Forwarded-For", request.remote_addr),
        ))
        conn.execute("UPDATE usuarios_sistema SET ultimo_login=NOW(), updated_at=NOW() WHERE id=%s", (row["usuario_id"],))
        _registrar_evento_licencia(conn, row["cliente_id"], row["usuario_id"], device_id_hash, "login_ok", modulo_actual)

    return _respuesta_sesion(row, token=token)


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    auth = _auth_sistema(request)
    if not auth:
        return jsonify({"ok": True})
    token_hash = _hash_token(request.headers.get("Authorization", "").replace("Bearer ", "", 1))
    with get_conn() as conn:
        conn.execute("UPDATE sesiones_activas SET estado='cerrada', updated_at=NOW() WHERE token_hash=%s", (token_hash,))
        _registrar_evento_licencia(conn, auth["cliente_id"], auth["usuario_id"], auth["device_id_hash"], "logout")
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    auth = _auth_sistema(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    permitido, estado, mensaje = _cliente_permitido(auth)
    return _respuesta_sesion(auth, permitido=permitido, estado=estado, mensaje=mensaje)


@app.route("/api/license/validate", methods=["POST"])
def api_license_validate():
    auth = _auth_sistema(request)
    if not auth:
        return jsonify({"permitido": False, "estado": "sin_sesion", "mensaje": "Sesion no valida"}), 401
    permitido, estado, mensaje = _cliente_permitido(auth)
    data = _body_json()
    with get_conn() as conn:
        conn.execute("""
            UPDATE sesiones_activas
            SET modulo_actual=%s, app_version=%s, ultimo_heartbeat=NOW(), updated_at=NOW()
            WHERE id=%s
        """, (data.get("modulo_actual"), data.get("app_version"), auth["sesion_id"]))
    return _respuesta_sesion(auth, permitido=permitido, estado=estado, mensaje=mensaje)


@app.route("/api/license/heartbeat", methods=["POST"])
def api_license_heartbeat():
    auth = _auth_sistema(request)
    if not auth:
        return jsonify({"permitido": False, "estado": "sin_sesion", "mensaje": "Sesion no valida"}), 401
    permitido, estado, mensaje = _cliente_permitido(auth)
    data = _body_json()
    with get_conn() as conn:
        conn.execute("""
            UPDATE sesiones_activas
            SET modulo_actual=%s, app_version=%s, ip=%s, ultimo_heartbeat=NOW(), updated_at=NOW(),
                estado=CASE WHEN %s THEN 'activa' ELSE 'bloqueada' END
            WHERE id=%s
        """, (
            data.get("modulo_actual"),
            data.get("app_version"),
            request.headers.get("X-Forwarded-For", request.remote_addr),
            permitido,
            auth["sesion_id"],
        ))
    return _respuesta_sesion(auth, permitido=permitido, estado=estado, mensaje=mensaje)


@app.route("/api/license/status", methods=["GET"])
def api_license_status():
    auth = _auth_sistema(request)
    if not auth:
        return jsonify({"permitido": False, "estado": "sin_sesion"}), 401
    permitido, estado, mensaje = _cliente_permitido(auth)
    return _respuesta_sesion(auth, permitido=permitido, estado=estado, mensaje=mensaje)


def _require_license_api():
    auth = _auth_sistema(request)
    if not auth:
        return None, (jsonify({
            "ok": False,
            "error": "No autorizado",
            "estado": "sin_sesion",
        }), 401)

    permitido, estado, mensaje = _cliente_permitido(auth)
    if not permitido:
        return None, (jsonify({
            "ok": False,
            "error": mensaje,
            "estado": estado,
        }), 403)

    return auth, None


BACKEND_LEGACY_ADMIN_OVERRIDE_FALLBACK = "12587987521"


def _backend_admin_override_key():
    return (
        os.environ.get("HILORAMA_ADMIN_OVERRIDE_KEY", "").strip()
        or BACKEND_LEGACY_ADMIN_OVERRIDE_FALLBACK
    )


@app.route("/api/autorizaciones/validar", methods=["POST"])
def api_autorizaciones_validar():
    auth, error = _require_license_api()
    if error:
        return error

    data = _body_json()
    tipo = str(data.get("tipo") or "").strip()
    clave = str(data.get("clave") or "")
    contexto = data.get("contexto") if isinstance(data.get("contexto"), dict) else {}
    accion = str(contexto.get("accion") or "").strip()

    if tipo != "admin_legacy":
        return jsonify({
            "ok": False,
            "autorizado": False,
            "error": "Tipo de autorizacion no soportado.",
        }), 400

    esperado = _backend_admin_override_key()
    autorizado = bool(esperado) and secrets.compare_digest(clave, esperado)
    if not autorizado:
        app.logger.warning(
            "Autorizacion rechazada tipo=%s accion=%s usuario_id=%s",
            tipo,
            accion,
            auth.get("usuario_id"),
        )

    return jsonify({
        "ok": True,
        "autorizado": autorizado,
    })


@app.route("/api/productos", methods=["GET"])
def api_productos_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = listar_productos(request.args)
        return jsonify({"ok": True, **data})
    except Exception as exc:
        app.logger.exception("Error al consultar productos")
        return jsonify({"ok": False, "error": "No se pudo consultar productos."}), 500


@app.route("/api/productos/<int:producto_id>", methods=["GET"])
def api_productos_obtener(producto_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        producto = obtener_producto_por_id(producto_id)
        if not producto:
            return jsonify({"ok": False, "error": "Producto no encontrado."}), 404
        return jsonify({"ok": True, "producto": producto})
    except Exception as exc:
        app.logger.exception("Error al consultar producto por id")
        return jsonify({"ok": False, "error": "No se pudo consultar el producto."}), 500


@app.route("/api/productos/codigo/<path:codigo>", methods=["GET"])
def api_productos_obtener_por_codigo(codigo):
    _, error = _require_license_api()
    if error:
        return error
    try:
        producto = api_obtener_producto_por_codigo(codigo)
        if not producto:
            return jsonify({"ok": False, "error": "Producto no encontrado."}), 404
        return jsonify({"ok": True, "producto": producto})
    except Exception as exc:
        app.logger.exception("Error al consultar producto por codigo")
        return jsonify({"ok": False, "error": "No se pudo consultar el producto."}), 500


@app.route("/api/marcas", methods=["GET"])
def api_productos_marcas():
    _, error = _require_license_api()
    if error:
        return error
    try:
        return jsonify({"ok": True, "marcas": listar_marcas()})
    except Exception as exc:
        app.logger.exception("Error al listar marcas")
        return jsonify({"ok": False, "error": "No se pudieron consultar las marcas."}), 500


@app.route("/api/hilos", methods=["GET"])
def api_productos_hilos():
    _, error = _require_license_api()
    if error:
        return error
    try:
        return jsonify({"ok": True, "hilos": listar_hilos(request.args.get("marca"))})
    except Exception as exc:
        app.logger.exception("Error al listar hilos")
        return jsonify({"ok": False, "error": "No se pudieron consultar los hilos."}), 500


@app.route("/api/almacen/resumen", methods=["GET"])
def api_almacen_resumen():
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = resumen_almacen()
        return jsonify({"ok": True, **data})
    except Exception as exc:
        app.logger.exception("Error al consultar resumen de almacen")
        return jsonify({"ok": False, "error": "No se pudo consultar el resumen de almacen."}), 500


@app.route("/api/precios", methods=["GET"])
def api_precios_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        return jsonify({"ok": True, "precios": listar_precios(request.args)})
    except Exception as exc:
        app.logger.exception("Error al consultar precios")
        return jsonify({"ok": False, "error": "No se pudieron consultar los precios."}), 500


@app.route("/api/precios/marca/<path:marca>", methods=["GET"])
def api_precios_marca(marca):
    _, error = _require_license_api()
    if error:
        return error
    try:
        return jsonify({"ok": True, "precios": obtener_precios_marca(marca)})
    except Exception as exc:
        app.logger.exception("Error al consultar precios por marca")
        return jsonify({"ok": False, "error": "No se pudieron consultar los precios de la marca."}), 500


@app.route("/api/precios/producto", methods=["GET"])
def api_precio_producto():
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = obtener_precio_producto(
            marca=request.args.get("marca"),
            hilo=request.args.get("hilo"),
            codigo=request.args.get("codigo"),
        )
        return jsonify({"ok": True, **data})
    except Exception as exc:
        app.logger.exception("Error al consultar precio de producto")
        return jsonify({"ok": False, "error": "No se pudo consultar el precio del producto."}), 500


ALMACEN_PRODUCTO_CAMPOS_EDITABLES_API = {
    "color",
    "codigo_barras",
    "costo_neto",
    "precio",
    "volumetrico",
    "tipo_producto",
    "estado",
}

ALMACEN_TIPOS_PRODUCTO_API = {
    "INVENTARIO": "INVENTARIO",
    "ITEM": "ITEM",
    "ITEM_COTIZACION": "ITEM",
    "ITEM COTIZACION": "ITEM",
    "ANULADO": "ANULADO",
    "INACTIVO": "ANULADO",
    "COTIZACION": "COTIZACION",
    "PAQUETE": "PAQUETE",
    "PAQUETES": "PAQUETES",
    "COMBO": "COMBO",
    "COMBOS": "COMBOS",
    "SERVICIO": "SERVICIO",
}

ALMACEN_ESTADOS_PRODUCTO_API = {
    "OK": "OK",
    "RESURTIR": "RESURTIR",
    "STOCK BAJO": "RESURTIR",
    "STOCK_BAJO": "RESURTIR",
    "SIN STOCK": "SIN STOCK",
    "SIN_STOCK": "SIN STOCK",
    "ANULADO": "ANULADO",
    "INACTIVO": "ANULADO",
    "ITEM": "ITEM",
}


def _normalizar_clave_almacen_api(valor):
    return str(valor or "").strip().upper().replace("-", "_")


def _valor_producto_edicion_api(campo, valor):
    if campo == "color":
        valor = str(valor or "").strip().upper()
        if not valor:
            raise ValueError("Color invalido.")
        return valor
    if campo == "codigo_barras":
        return str(valor or "").strip()
    if campo in {"costo_neto", "precio"}:
        try:
            numero = float(str(valor).replace("$", "").replace(",", ".").strip())
        except Exception:
            raise ValueError(f"{campo} debe ser numerico.")
        if numero < 0:
            raise ValueError(f"{campo} no puede ser negativo.")
        return numero
    if campo == "volumetrico":
        try:
            numero = float(str(valor).replace(",", ".").strip())
        except Exception:
            raise ValueError("Volumetrico debe ser numerico.")
        if numero <= 0:
            raise ValueError("Volumetrico debe ser mayor a 0.")
        return numero
    if campo == "tipo_producto":
        clave = _normalizar_clave_almacen_api(valor).replace(" ", "_")
        if clave not in ALMACEN_TIPOS_PRODUCTO_API:
            raise ValueError("Tipo de producto no permitido.")
        return ALMACEN_TIPOS_PRODUCTO_API[clave]
    if campo == "estado":
        clave = _normalizar_clave_almacen_api(valor)
        if clave not in ALMACEN_ESTADOS_PRODUCTO_API:
            raise ValueError("Estado de producto no permitido.")
        return ALMACEN_ESTADOS_PRODUCTO_API[clave]
    raise ValueError("Campo no permitido.")


def _texto_obligatorio_producto_api(data, campo):
    valor = str((data or {}).get(campo) or "").strip()
    if not valor:
        raise ValueError(f"El campo {campo} es obligatorio.")
    if campo in {"marca", "hilo", "color"}:
        return valor.upper()
    return valor


def _stock_alta_producto_api(valor):
    if valor is None or valor == "":
        raise ValueError("El stock es obligatorio.")
    try:
        numero = float(str(valor).replace(",", ".").strip())
    except Exception:
        raise ValueError("Stock invalido.")
    if numero < 0:
        raise ValueError("No se permite stock negativo en alta de producto.")
    if not numero.is_integer():
        raise ValueError("Stock debe ser un numero entero.")
    return int(numero)


def _tipo_producto_alta_api(data):
    tipo = data.get("tipo_producto") or data.get("tipo") or "INVENTARIO"
    return _valor_producto_edicion_api("tipo_producto", tipo)


def _es_inventariable_tipo_api(tipo_producto):
    tipo = _normalizar_clave_almacen_api(tipo_producto).replace(" ", "_")
    return tipo not in {
        "ITEM",
        "ITEM_COTIZACION",
        "ANULADO",
        "INACTIVO",
        "COTIZACION",
        "PAQUETE",
        "PAQUETES",
        "COMBO",
        "COMBOS",
        "SERVICIO",
    }


def _estado_alta_producto_api(data, stock, inventariable):
    if not inventariable:
        return "ITEM"
    if data.get("estado") not in (None, ""):
        return _valor_producto_edicion_api("estado", data.get("estado"))
    if stock <= 0:
        return "SIN STOCK"
    if stock < STOCK_MINIMO_API:
        return "RESURTIR"
    return "OK"


def _cambio_producto_payload_api(data):
    permitidos_payload = ALMACEN_PRODUCTO_CAMPOS_EDITABLES_API | {"campo", "valor", "motivo"}
    desconocidos = set(data or {}) - permitidos_payload
    if desconocidos:
        raise ValueError(f"Campos no permitidos: {', '.join(sorted(desconocidos))}.")

    campo = (data.get("campo") or "").strip()
    if campo:
        extras = set(data or {}) & ALMACEN_PRODUCTO_CAMPOS_EDITABLES_API
        if extras:
            raise ValueError("No mezcle campo/valor con campos directos en la misma solicitud.")
        cambios = {campo: data.get("valor")}
    else:
        if "valor" in data:
            raise ValueError("valor solo se permite cuando tambien envia campo.")
        cambios = {k: data[k] for k in ALMACEN_PRODUCTO_CAMPOS_EDITABLES_API if k in data}

    if len(cambios) != 1:
        raise ValueError("Solo se permite editar un campo por solicitud.")

    campo, valor = next(iter(cambios.items()))
    if campo not in ALMACEN_PRODUCTO_CAMPOS_EDITABLES_API:
        raise ValueError("Campo no permitido.")
    return campo, _valor_producto_edicion_api(campo, valor)


def _payload_alta_producto_api(data):
    data = data or {}
    marca = _texto_obligatorio_producto_api(data, "marca")
    hilo = _texto_obligatorio_producto_api(data, "hilo")
    color = _texto_obligatorio_producto_api(data, "color")
    codigo = _texto_obligatorio_producto_api(data, "codigo")
    tipo_producto = _tipo_producto_alta_api(data)
    inventariable = _es_inventariable_tipo_api(tipo_producto)
    stock = _stock_alta_producto_api(data.get("stock", 0 if not inventariable else None))
    if not inventariable:
        stock = 0
    return {
        "marca": marca,
        "hilo": hilo,
        "color": color,
        "codigo": codigo,
        "codigo_barras": str(data.get("codigo_barras") or "").strip(),
        "stock": stock,
        "costo_neto": _valor_producto_edicion_api("costo_neto", data.get("costo_neto", 0)),
        "precio": _valor_producto_edicion_api("precio", data.get("precio", 0)),
        "volumetrico": _valor_producto_edicion_api("volumetrico", data.get("volumetrico", 1)),
        "tipo_producto": tipo_producto,
        "es_inventariable": inventariable,
        "estado": _estado_alta_producto_api(data, stock, inventariable),
        "motivo": data.get("motivo") or "Alta rapida desde Almacen",
    }


def _registrar_movimiento_producto_edicion_api(conn, campo, anterior, valor_nuevo, motivo, auth):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": "EDICION_PRODUCTO",
        "marca": anterior.get("marca"),
        "hilo": anterior.get("hilo"),
        "color": anterior.get("color"),
        "codigo": anterior.get("codigo"),
        "stock_anterior": anterior.get("stock"),
        "stock_nuevo": anterior.get("stock"),
        "cantidad": 0,
        "campo": campo,
        "valor_anterior": anterior.get(campo),
        "valor_nuevo": valor_nuevo,
        "motivo": motivo or "Edicion manual desde Almacen",
    }
    campos = [col for col in valores if col in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_producto_edicion")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[col] for col in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_producto_edicion")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_producto_edicion")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_producto_edicion")
        except Exception:
            pass
        app.logger.warning("No se pudo registrar movimiento de edicion de producto", exc_info=True)


def _registrar_movimiento_producto_alta_api(conn, producto, motivo, auth):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    stock = int((producto or {}).get("stock") or 0)
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": "ALTA_PRODUCTO" if _es_inventariable_tipo_api(producto.get("tipo_producto")) else "ALTA_ITEM_COTIZACION",
        "marca": producto.get("marca"),
        "hilo": producto.get("hilo"),
        "color": producto.get("color"),
        "codigo": producto.get("codigo"),
        "stock_anterior": 0,
        "stock_nuevo": stock,
        "cantidad": stock,
        "campo": "alta",
        "valor_anterior": "",
        "valor_nuevo": stock,
        "motivo": motivo or "Alta rapida desde Almacen",
    }
    campos = [col for col in valores if col in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_producto_alta")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[col] for col in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_producto_alta")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_producto_alta")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_producto_alta")
        except Exception:
            pass
        app.logger.warning("No se pudo registrar movimiento de alta de producto", exc_info=True)


@app.route("/api/almacen/productos", methods=["POST"])
def api_almacen_crear_producto():
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        producto = _payload_alta_producto_api(data)
        motivo = producto.pop("motivo")

        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "productos")
            requeridas = {"id", "marca", "hilo", "color", "codigo", "stock"}
            faltantes = requeridas - columnas
            if faltantes:
                raise ValueError(f"La tabla productos no tiene columnas requeridas: {', '.join(sorted(faltantes))}.")

            duplicado = conn.execute("""
                SELECT id
                FROM productos
                WHERE marca=%s AND hilo=%s AND color=%s AND codigo=%s
                LIMIT 1
            """, (
                producto["marca"],
                producto["hilo"],
                producto["color"],
                producto["codigo"],
            )).fetchone()
            if duplicado:
                raise ValueError("Ya existe un producto con ese codigo/marca/hilo/color.")

            if producto.get("codigo_barras") and "codigo_barras" in columnas:
                duplicado_barras = conn.execute("""
                    SELECT id
                    FROM productos
                    WHERE codigo_barras=%s
                    LIMIT 1
                """, (producto["codigo_barras"],)).fetchone()
                if duplicado_barras:
                    raise ValueError("Ya existe un producto con ese codigo de barras.")

            campos = [campo for campo in producto if campo in columnas]
            placeholders = ",".join(["%s"] * len(campos))
            row = conn.execute(
                f"INSERT INTO productos({','.join(campos)}) VALUES ({placeholders}) RETURNING *",
                tuple(producto[campo] for campo in campos),
            ).fetchone()
            producto_creado = _row_dict(row) or {}
            _registrar_movimiento_producto_alta_api(conn, producto_creado, motivo, auth)

        producto_id = producto_creado.get("id")
        producto_respuesta = obtener_producto_por_id(producto_id) if producto_id else producto_creado
        return jsonify({"ok": True, "producto": producto_respuesta})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al crear producto por API")
        return jsonify({"ok": False, "error": "No se pudo crear el producto."}), 500


def _stock_nuevo_manual_api(data):
    if "stock_nuevo" not in (data or {}):
        raise ValueError("stock_nuevo es obligatorio.")
    try:
        numero = float(str(data.get("stock_nuevo")).replace(",", ".").strip())
    except Exception:
        raise ValueError("stock_nuevo debe ser numerico.")
    if not numero.is_integer():
        raise ValueError("El stock manual debe ser un numero entero.")
    stock_nuevo = int(numero)
    if stock_nuevo < 0 and not _clave_stock_autorizada_api(data):
        raise PermissionError("Stock negativo requiere clave de autorizacion.")
    return stock_nuevo


def _estado_por_stock_manual_api(stock_nuevo):
    if stock_nuevo <= 0:
        return "SIN STOCK"
    if stock_nuevo < STOCK_MINIMO_API:
        return "RESURTIR"
    return "OK"


@app.route("/api/almacen/productos/<int:producto_id>/stock", methods=["PATCH"])
def api_almacen_actualizar_stock_producto(producto_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        stock_nuevo = _stock_nuevo_manual_api(data)
        motivo = data.get("motivo") or "Ajuste manual de stock desde Almacen"

        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "productos")
            if "id" not in columnas or "stock" not in columnas:
                raise ValueError("La tabla productos no tiene columnas requeridas para stock.")

            producto_row = conn.execute(
                "SELECT * FROM productos WHERE id=%s FOR UPDATE",
                (producto_id,),
            ).fetchone()
            producto = _row_dict(producto_row)
            if not producto:
                raise LookupError("Producto no encontrado.")
            if not _producto_inventariable_api(producto):
                raise PermissionError("Este producto no maneja stock fisico.")

            stock_anterior = int(producto.get("stock") or 0)
            diferencia = stock_nuevo - stock_anterior
            estado_nuevo = _estado_por_stock_manual_api(stock_nuevo)
            if "estado" in columnas:
                conn.execute(
                    "UPDATE productos SET stock=%s, estado=%s WHERE id=%s",
                    (stock_nuevo, estado_nuevo, producto_id),
                )
            else:
                conn.execute(
                    "UPDATE productos SET stock=%s WHERE id=%s",
                    (stock_nuevo, producto_id),
                )

            producto_mov = dict(producto)
            producto_mov["_stock_nuevo"] = stock_nuevo
            _registrar_movimiento_almacen_api(
                conn,
                "AJUSTE_STOCK_MANUAL",
                producto,
                producto_mov,
                diferencia,
                motivo,
                auth,
            )

        producto_respuesta = obtener_producto_por_id(producto_id)
        return jsonify({"ok": True, "producto": producto_respuesta})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al actualizar stock manual por API")
        return jsonify({"ok": False, "error": "No se pudo actualizar el stock."}), 500


def _bool_tipo_producto_api(data, campo, default):
    if campo not in (data or {}):
        return default
    valor = data.get(campo)
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    texto = str(valor or "").strip().lower()
    if texto in {"1", "true", "si", "sí", "yes", "y"}:
        return True
    if texto in {"0", "false", "no", "n", "item"}:
        return False
    raise ValueError(f"{campo} debe ser booleano.")


def _stock_inicial_tipo_producto_api(data, producto, inventariable):
    stock_actual = producto.get("stock")
    if not inventariable:
        return 0
    if "stock_inicial" not in (data or {}) and stock_actual not in (None, ""):
        try:
            return int(float(stock_actual or 0))
        except Exception:
            return 0
    try:
        numero = float(str(data.get("stock_inicial", 0)).replace(",", ".").strip())
    except Exception:
        raise ValueError("stock_inicial debe ser numerico.")
    if not numero.is_integer():
        raise ValueError("stock_inicial debe ser un numero entero.")
    stock = int(numero)
    if stock < 0:
        raise ValueError("stock_inicial no puede ser negativo.")
    return stock


def _estado_por_tipo_producto_api(inventariable, stock):
    if not inventariable:
        return "ITEM"
    if stock <= 0:
        return "SIN STOCK"
    if stock < STOCK_MINIMO_API:
        return "RESURTIR"
    return "OK"


def _registrar_movimiento_tipo_producto_api(conn, anterior, tipo_nuevo, inventariable_nuevo, stock_nuevo, motivo, auth):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    stock_anterior = int((anterior or {}).get("stock") or 0)
    tipo_anterior = (anterior or {}).get("tipo_producto") or (anterior or {}).get("tipo") or "INVENTARIO"
    inventariable_anterior = _producto_inventariable_api(anterior)
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": "CAMBIO_TIPO_PRODUCTO",
        "marca": anterior.get("marca"),
        "hilo": anterior.get("hilo"),
        "color": anterior.get("color"),
        "codigo": anterior.get("codigo"),
        "stock_anterior": stock_anterior,
        "stock_nuevo": stock_nuevo,
        "cantidad": stock_nuevo - stock_anterior,
        "campo": "tipo_producto",
        "valor_anterior": f"tipo={tipo_anterior}; es_inventariable={inventariable_anterior}",
        "valor_nuevo": f"tipo={tipo_nuevo}; es_inventariable={inventariable_nuevo}",
        "motivo": motivo,
    }
    campos = [campo for campo in valores if campo in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_tipo_producto")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo] for campo in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_tipo_producto")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_tipo_producto")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_tipo_producto")
        except Exception:
            pass
        app.logger.warning("No se pudo registrar movimiento de cambio de tipo de producto", exc_info=True)


@app.route("/api/almacen/productos/<int:producto_id>/tipo", methods=["POST"])
def api_almacen_actualizar_tipo_producto(producto_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        tipo_producto = _valor_producto_edicion_api("tipo_producto", data.get("tipo_producto", "INVENTARIO"))
        inventariable = _bool_tipo_producto_api(
            data,
            "es_inventariable",
            _es_inventariable_tipo_api(tipo_producto),
        )
        if not inventariable:
            tipo_producto = tipo_producto if tipo_producto != "INVENTARIO" else "ITEM"
        motivo = data.get("motivo") or "Cambio de tipo de producto desde Almacen"

        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "productos")
            if "id" not in columnas:
                raise ValueError("La tabla productos no tiene id para edicion segura.")
            if not ({"tipo_producto", "es_inventariable"} & columnas):
                raise ValueError("La tabla productos no tiene columnas de tipo/inventario.")

            anterior_row = conn.execute(
                "SELECT * FROM productos WHERE id=%s FOR UPDATE",
                (producto_id,),
            ).fetchone()
            anterior = _row_dict(anterior_row)
            if not anterior:
                raise LookupError("Producto no encontrado.")

            stock_nuevo = _stock_inicial_tipo_producto_api(data, anterior, inventariable)
            estado_nuevo = _estado_por_tipo_producto_api(inventariable, stock_nuevo)
            cambios = {}
            if "tipo_producto" in columnas:
                cambios["tipo_producto"] = tipo_producto
            if "es_inventariable" in columnas:
                cambios["es_inventariable"] = inventariable
            if "stock" in columnas:
                cambios["stock"] = stock_nuevo
            if "estado" in columnas:
                cambios["estado"] = estado_nuevo
            if not cambios:
                raise ValueError("No hay columnas disponibles para actualizar el tipo.")

            sets = ", ".join(f"{campo}=%s" for campo in cambios)
            conn.execute(
                f"UPDATE productos SET {sets} WHERE id=%s",
                tuple(cambios.values()) + (producto_id,),
            )
            _registrar_movimiento_tipo_producto_api(
                conn,
                anterior,
                tipo_producto,
                inventariable,
                stock_nuevo,
                motivo,
                auth,
            )

        producto = obtener_producto_por_id(producto_id)
        return jsonify({"ok": True, "producto": producto})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al cambiar tipo de producto por API")
        return jsonify({"ok": False, "error": "No se pudo cambiar el tipo de producto."}), 500


def _producto_ya_anulado_api(producto):
    estado = str((producto or {}).get("estado") or "").strip().upper().replace(" ", "_")
    tipo = str((producto or {}).get("tipo_producto") or (producto or {}).get("tipo") or "").strip().upper().replace(" ", "_")
    return estado in {"ANULADO", "INACTIVO", "ELIMINADO"} or tipo in {"ANULADO", "INACTIVO", "ELIMINADO"}


def _advertencias_anulacion_producto_api(conn, producto, stock_anterior):
    advertencias = []
    if stock_anterior > 0:
        advertencias.append(f"Este producto tiene stock actual {stock_anterior}. Quedara fuera del inventario fisico.")
    try:
        mov_cols = _columnas_tabla_api(conn, "movimientos_almacen")
        if {"codigo"}.issubset(mov_cols):
            row = conn.execute(
                "SELECT 1 FROM movimientos_almacen WHERE codigo=%s LIMIT 1",
                (producto.get("codigo"),),
            ).fetchone()
            if row:
                advertencias.append("Este producto tiene movimientos de almacen.")
    except Exception:
        pass
    try:
        items_cols = _columnas_tabla_api(conn, "items")
        filtros = []
        valores = []
        if "codigo" in items_cols and producto.get("codigo"):
            filtros.append("codigo=%s")
            valores.append(producto.get("codigo"))
        if "producto_id" in items_cols and producto.get("id"):
            filtros.append("producto_id=%s")
            valores.append(producto.get("id"))
        if filtros:
            row = conn.execute(f"SELECT 1 FROM items WHERE {' OR '.join(filtros)} LIMIT 1", tuple(valores)).fetchone()
            if row:
                advertencias.append("Este producto aparece en notas o cotizaciones.")
    except Exception:
        pass
    return advertencias


def _registrar_movimiento_anulacion_producto_api(conn, producto, stock_anterior, motivo, auth, advertencias=None):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    tipo_anterior = producto.get("tipo_producto") or producto.get("tipo") or "INVENTARIO"
    motivo_final = motivo
    if advertencias:
        motivo_final = f"{motivo} | Advertencias: {'; '.join(advertencias)}"
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": "ANULACION_PRODUCTO",
        "marca": producto.get("marca"),
        "hilo": producto.get("hilo"),
        "color": producto.get("color"),
        "codigo": producto.get("codigo"),
        "stock_anterior": stock_anterior,
        "stock_nuevo": 0,
        "cantidad": -stock_anterior,
        "campo": "estado",
        "valor_anterior": f"estado={producto.get('estado')}; tipo={tipo_anterior}",
        "valor_nuevo": "estado=ANULADO; tipo=ANULADO; es_inventariable=False",
        "motivo": motivo_final,
    }
    campos = [campo for campo in valores if campo in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_anulacion_producto")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo] for campo in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_anulacion_producto")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_anulacion_producto")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_anulacion_producto")
        except Exception:
            pass
        app.logger.warning("No se pudo registrar movimiento de anulacion de producto", exc_info=True)


@app.route("/api/almacen/productos/<int:producto_id>/anular", methods=["POST"])
def api_almacen_anular_producto(producto_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        if not _clave_stock_autorizada_api(data):
            raise PermissionError("Clave de autorizacion incorrecta.")
        motivo = data.get("motivo") or "Anulacion de tono desde Almacen"

        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "productos")
            if "id" not in columnas:
                raise ValueError("La tabla productos no tiene id para anulacion segura.")
            columnas_anulacion = {"estado", "tipo_producto", "es_inventariable", "stock"} & columnas
            if not columnas_anulacion:
                raise ValueError("No hay columnas disponibles para anular sin borrar fisicamente.")

            producto_row = conn.execute(
                "SELECT * FROM productos WHERE id=%s FOR UPDATE",
                (producto_id,),
            ).fetchone()
            producto = _row_dict(producto_row)
            if not producto:
                raise LookupError("Producto no encontrado.")
            if _producto_ya_anulado_api(producto):
                return jsonify({
                    "ok": False,
                    "error": "Este producto ya esta anulado.",
                    "producto": producto,
                }), 409

            stock_anterior = int(float(producto.get("stock") or 0))
            advertencias = _advertencias_anulacion_producto_api(conn, producto, stock_anterior)
            cambios = {}
            if "estado" in columnas:
                cambios["estado"] = "ANULADO"
            if "tipo_producto" in columnas:
                cambios["tipo_producto"] = "ANULADO"
            if "es_inventariable" in columnas:
                cambios["es_inventariable"] = False
            if "stock" in columnas:
                cambios["stock"] = 0
            sets = ", ".join(f"{campo}=%s" for campo in cambios)
            conn.execute(
                f"UPDATE productos SET {sets} WHERE id=%s",
                tuple(cambios.values()) + (producto_id,),
            )
            _registrar_movimiento_anulacion_producto_api(
                conn,
                producto,
                stock_anterior,
                motivo,
                auth,
                advertencias=advertencias,
            )

        producto_actualizado = obtener_producto_por_id(producto_id)
        return jsonify({
            "ok": True,
            "producto": producto_actualizado,
            "advertencias": advertencias,
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al anular producto por API")
        return jsonify({"ok": False, "error": "No se pudo anular el producto."}), 500


def _select_movimiento_almacen_api(columnas):
    campos = []
    for columna in (
        "id",
        "fecha",
        "usuario",
        "tipo",
        "marca",
        "hilo",
        "color",
        "codigo",
        "stock_anterior",
        "stock_nuevo",
        "cantidad",
        "campo",
        "valor_anterior",
        "valor_nuevo",
        "motivo",
    ):
        if columna in columnas:
            campos.append(f"{columna} AS {columna}")
        else:
            campos.append(f"NULL AS {columna}")
    return ", ".join(campos)


def _movimiento_row_api(row):
    data = _row_dict(row) or {}
    fecha = data.get("fecha")
    if hasattr(fecha, "isoformat"):
        fecha = fecha.isoformat(sep=" ", timespec="seconds")
    return {
        "id": data.get("id"),
        "fecha": fecha,
        "usuario": data.get("usuario") or "",
        "tipo": data.get("tipo") or "",
        "marca": data.get("marca") or "",
        "hilo": data.get("hilo") or "",
        "color": data.get("color") or "",
        "codigo": data.get("codigo") or "",
        "stock_anterior": data.get("stock_anterior"),
        "stock_nuevo": data.get("stock_nuevo"),
        "cantidad": data.get("cantidad"),
        "campo": data.get("campo") or "",
        "valor_anterior": data.get("valor_anterior") or "",
        "valor_nuevo": data.get("valor_nuevo") or "",
        "motivo": data.get("motivo") or "",
    }


def _filtros_movimientos_almacen_api(conn, columnas, args):
    filtros = []
    valores = []

    def filtro_texto(param, columna):
        valor = str(args.get(param) or "").strip()
        if valor and columna in columnas:
            filtros.append(f"{columna} ILIKE %s")
            valores.append(f"%{valor}%")

    producto_id = str(args.get("producto_id") or "").strip()
    if producto_id:
        producto = conn.execute("SELECT * FROM productos WHERE id=%s LIMIT 1", (producto_id,)).fetchone()
        producto = _row_dict(producto)
        if not producto:
            raise LookupError("Producto no encontrado.")
        condiciones_producto = []
        valores_producto = []
        if "producto_id" in columnas:
            condiciones_producto.append("producto_id=%s")
            valores_producto.append(producto_id)
        if "codigo" in columnas and producto.get("codigo"):
            condiciones_producto.append("codigo=%s")
            valores_producto.append(producto.get("codigo"))
        for campo in ("marca", "hilo", "color"):
            if campo in columnas and producto.get(campo):
                condiciones_producto.append(f"UPPER({campo})=UPPER(%s)")
                valores_producto.append(producto.get(campo))
        if condiciones_producto:
            filtros.append("(" + " AND ".join(condiciones_producto) + ")")
            valores.extend(valores_producto)

    for param in ("codigo", "marca", "hilo", "color", "tipo"):
        filtro_texto(param, param)

    q = str(args.get("q") or "").strip()
    if q:
        campos_q = [campo for campo in ("marca", "hilo", "color", "codigo", "tipo", "campo", "motivo", "usuario") if campo in columnas]
        if campos_q:
            like = f"%{q}%"
            filtros.append("(" + " OR ".join(f"{campo} ILIKE %s" for campo in campos_q) + ")")
            valores.extend([like] * len(campos_q))

    desde = str(args.get("desde") or "").strip()
    if desde and "fecha" in columnas:
        filtros.append("fecha >= %s")
        valores.append(desde)
    hasta = str(args.get("hasta") or "").strip()
    if hasta and "fecha" in columnas:
        filtros.append("fecha <= %s")
        valores.append(hasta)

    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, tuple(valores)


@app.route("/api/almacen/movimientos", methods=["GET"])
def api_almacen_movimientos():
    _, error = _require_license_api()
    if error:
        return error
    try:
        limit = _api_limite(request.args.get("limit"), default=100, maximo=500)
        offset = _api_offset(request.args.get("offset"))
        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "movimientos_almacen")
            if not columnas:
                return jsonify({"ok": True, "movimientos": [], "total": 0, "limit": limit, "offset": offset})
            where, valores = _filtros_movimientos_almacen_api(conn, columnas, request.args)
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM movimientos_almacen {where}",
                valores,
            ).fetchone()
            fecha_order = "fecha DESC" if "fecha" in columnas else "id DESC"
            rows = conn.execute(
                f"""
                SELECT {_select_movimiento_almacen_api(columnas)}
                FROM movimientos_almacen
                {where}
                ORDER BY {fecha_order}
                LIMIT %s OFFSET %s
                """,
                valores + (limit, offset),
            ).fetchall()
        return jsonify({
            "ok": True,
            "movimientos": [_movimiento_row_api(row) for row in rows],
            "total": int((total_row or {}).get("total") or 0),
            "limit": limit,
            "offset": offset,
        })
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al consultar movimientos de almacen")
        return jsonify({"ok": False, "error": "No se pudieron consultar los movimientos de almacen."}), 500


def _texto_masivo_almacen_api(data, campo):
    valor = str((data or {}).get(campo) or "").strip()
    if not valor:
        raise ValueError(f"El campo {campo} es obligatorio.")
    return valor.upper()


def _productos_por_marca_hilo_api(conn, marca, hilo=None, bloquear=True):
    filtros = ["UPPER(marca)=UPPER(%s)"]
    valores = [marca]
    if hilo is not None:
        filtros.append("UPPER(hilo)=UPPER(%s)")
        valores.append(hilo)
    bloqueo = " FOR UPDATE" if bloquear else ""
    rows = conn.execute(
        f"SELECT * FROM productos WHERE {' AND '.join(filtros)} ORDER BY marca, hilo, color, codigo{bloqueo}",
        tuple(valores),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def _resumen_productos_afectados_api(productos, limite=25):
    resumen = []
    for producto in (productos or [])[:limite]:
        resumen.append({
            "id": producto.get("id"),
            "codigo": producto.get("codigo"),
            "marca": producto.get("marca"),
            "hilo": producto.get("hilo"),
            "color": producto.get("color"),
            "stock": producto.get("stock"),
            "precio": producto.get("precio"),
            "volumetrico": producto.get("volumetrico"),
        })
    return resumen


def _registrar_movimiento_masivo_producto_api(conn, tipo, campo, producto, valor_nuevo, motivo, auth):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": tipo,
        "marca": producto.get("marca"),
        "hilo": producto.get("hilo"),
        "color": producto.get("color"),
        "codigo": producto.get("codigo"),
        "stock_anterior": producto.get("stock"),
        "stock_nuevo": producto.get("stock"),
        "cantidad": 0,
        "campo": campo,
        "valor_anterior": producto.get(campo),
        "valor_nuevo": valor_nuevo,
        "motivo": motivo,
    }
    campos = [campo_valor for campo_valor in valores if campo_valor in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_masivo_producto")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo_valor] for campo_valor in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_masivo_producto")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_masivo_producto")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_masivo_producto")
        except Exception:
            pass
        app.logger.warning("No se pudo registrar movimiento masivo de producto", exc_info=True)


def _registrar_movimiento_precio_marca_api(conn, marca, anterior, distribuidor, venta, cantidad, motivo, auth):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    valor_anterior = (
        f"distribuidor={anterior.get('distribuidor')}, venta={anterior.get('venta')}"
        if anterior else "sin precio previo"
    )
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": "ACTUALIZACION_PRECIO_MASIVA",
        "marca": marca,
        "hilo": None,
        "color": None,
        "codigo": None,
        "stock_anterior": None,
        "stock_nuevo": None,
        "cantidad": cantidad,
        "campo": "precios_marca",
        "valor_anterior": valor_anterior,
        "valor_nuevo": f"distribuidor={distribuidor}, venta={venta}",
        "motivo": motivo,
    }
    campos = [campo for campo in valores if campo in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_precio_marca")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo] for campo in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_precio_marca")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_precio_marca")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_precio_marca")
        except Exception:
            pass
        app.logger.warning("No se pudo registrar movimiento masivo de precio por marca", exc_info=True)


@app.route("/api/almacen/precios/marca/<path:marca>", methods=["PATCH"])
def api_almacen_actualizar_precio_marca(marca):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        marca = str(marca or "").strip().upper()
        if not marca:
            raise ValueError("La marca es obligatoria.")
        distribuidor = _valor_producto_edicion_api("costo_neto", data.get("distribuidor", data.get("costo_neto")))
        venta = _valor_producto_edicion_api("precio", data.get("venta", data.get("precio")))
        motivo = data.get("motivo") or "Actualizacion masiva de precio por marca"

        with get_conn() as conn:
            precios_cols = _columnas_tabla_api(conn, "precios")
            requeridas = {"marca", "distribuidor", "venta"}
            if not requeridas.issubset(precios_cols):
                raise ValueError("La tabla precios no tiene las columnas requeridas.")

            productos = _productos_por_marca_hilo_api(conn, marca, bloquear=False)
            if not productos:
                raise LookupError("No hay productos afectados para esa marca.")

            anterior = _row_dict(conn.execute(
                "SELECT distribuidor, venta FROM precios WHERE UPPER(marca)=UPPER(%s) LIMIT 1",
                (marca,),
            ).fetchone())

            conn.execute("""
                INSERT INTO precios(marca, distribuidor, venta)
                VALUES (%s,%s,%s)
                ON CONFLICT(marca)
                DO UPDATE SET
                    distribuidor=excluded.distribuidor,
                    venta=excluded.venta
            """, (marca, distribuidor, venta))
            _registrar_movimiento_precio_marca_api(
                conn,
                marca,
                anterior,
                distribuidor,
                venta,
                len(productos),
                motivo,
                auth,
            )

        return jsonify({
            "ok": True,
            "cantidad_actualizada": len(productos),
            "marca": marca,
            "hilo": None,
            "valor_anterior": anterior,
            "valor_nuevo": {"distribuidor": distribuidor, "venta": venta},
            "productos_afectados": _resumen_productos_afectados_api(productos),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al actualizar precio por marca")
        return jsonify({"ok": False, "error": "No se pudo actualizar el precio por marca."}), 500


@app.route("/api/almacen/precios/hilo", methods=["PATCH"])
def api_almacen_actualizar_precio_hilo():
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        marca = _texto_masivo_almacen_api(data, "marca")
        hilo = _texto_masivo_almacen_api(data, "hilo")
        precio = _valor_producto_edicion_api("precio", data.get("precio"))
        motivo = data.get("motivo") or "Actualizacion masiva de precio por hilo"

        with get_conn() as conn:
            productos_cols = _columnas_tabla_api(conn, "productos")
            if "precio" not in productos_cols:
                raise ValueError("La tabla productos no tiene columna precio.")
            productos = _productos_por_marca_hilo_api(conn, marca, hilo, bloquear=True)
            if not productos:
                raise LookupError("No hay productos afectados para esa marca/hilo.")

            conn.execute(
                "UPDATE productos SET precio=%s WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)",
                (precio, marca, hilo),
            )
            for producto in productos:
                _registrar_movimiento_masivo_producto_api(
                    conn,
                    "ACTUALIZACION_PRECIO_MASIVA",
                    "precio",
                    producto,
                    precio,
                    motivo,
                    auth,
                )

        return jsonify({
            "ok": True,
            "cantidad_actualizada": len(productos),
            "marca": marca,
            "hilo": hilo,
            "valor_anterior": productos[0].get("precio") if productos else None,
            "valor_nuevo": precio,
            "productos_afectados": _resumen_productos_afectados_api(productos),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al actualizar precio por hilo")
        return jsonify({"ok": False, "error": "No se pudo actualizar el precio por hilo."}), 500


@app.route("/api/almacen/volumetrico/hilo", methods=["PATCH"])
def api_almacen_actualizar_volumetrico_hilo():
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        marca = _texto_masivo_almacen_api(data, "marca")
        hilo = _texto_masivo_almacen_api(data, "hilo")
        volumetrico = _valor_producto_edicion_api("volumetrico", data.get("volumetrico"))
        motivo = data.get("motivo") or "Actualizacion masiva de volumetrico por hilo"

        with get_conn() as conn:
            productos_cols = _columnas_tabla_api(conn, "productos")
            if "volumetrico" not in productos_cols:
                raise ValueError("La tabla productos no tiene columna volumetrico.")
            productos = _productos_por_marca_hilo_api(conn, marca, hilo, bloquear=True)
            if not productos:
                raise LookupError("No hay productos afectados para esa marca/hilo.")

            conn.execute(
                "UPDATE productos SET volumetrico=%s WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)",
                (volumetrico, marca, hilo),
            )
            for producto in productos:
                _registrar_movimiento_masivo_producto_api(
                    conn,
                    "ACTUALIZACION_VOLUMETRICO_MASIVA",
                    "volumetrico",
                    producto,
                    volumetrico,
                    motivo,
                    auth,
                )

        return jsonify({
            "ok": True,
            "cantidad_actualizada": len(productos),
            "marca": marca,
            "hilo": hilo,
            "valor_anterior": productos[0].get("volumetrico") if productos else None,
            "valor_nuevo": volumetrico,
            "productos_afectados": _resumen_productos_afectados_api(productos),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al actualizar volumetrico por hilo")
        return jsonify({"ok": False, "error": "No se pudo actualizar el volumetrico por hilo."}), 500


@app.route("/api/almacen/volumetrico/multiple", methods=["PATCH"])
def api_almacen_actualizar_volumetrico_multiple():
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        items = data.get("items") or []
        if not isinstance(items, list) or not items:
            raise ValueError("Debe enviar una lista de items.")
        motivo = data.get("motivo") or "Actualizacion multiple de volumetrico"

        normalizados = []
        for item in items:
            normalizados.append({
                "marca": _texto_masivo_almacen_api(item, "marca"),
                "hilo": _texto_masivo_almacen_api(item, "hilo"),
                "volumetrico": _valor_producto_edicion_api("volumetrico", item.get("volumetrico")),
            })

        productos_afectados = []
        with get_conn() as conn:
            productos_cols = _columnas_tabla_api(conn, "productos")
            if "volumetrico" not in productos_cols:
                raise ValueError("La tabla productos no tiene columna volumetrico.")

            grupos = []
            for item in normalizados:
                productos = _productos_por_marca_hilo_api(conn, item["marca"], item["hilo"], bloquear=True)
                if not productos:
                    raise LookupError(f"No hay productos afectados para {item['marca']} / {item['hilo']}.")
                grupos.append((item, productos))

            for item, productos in grupos:
                conn.execute(
                    "UPDATE productos SET volumetrico=%s WHERE UPPER(marca)=UPPER(%s) AND UPPER(hilo)=UPPER(%s)",
                    (item["volumetrico"], item["marca"], item["hilo"]),
                )
                for producto in productos:
                    _registrar_movimiento_masivo_producto_api(
                        conn,
                        "ACTUALIZACION_VOLUMETRICO_MASIVA",
                        "volumetrico",
                        producto,
                        item["volumetrico"],
                        motivo,
                        auth,
                    )
                productos_afectados.extend(productos)

        return jsonify({
            "ok": True,
            "cantidad_actualizada": len(productos_afectados),
            "marca": None,
            "hilo": None,
            "valor_anterior": None,
            "valor_nuevo": normalizados,
            "productos_afectados": _resumen_productos_afectados_api(productos_afectados),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al actualizar volumetrico multiple")
        return jsonify({"ok": False, "error": "No se pudo actualizar el volumetrico multiple."}), 500


@app.route("/api/almacen/productos/<int:producto_id>", methods=["PATCH"])
def api_almacen_actualizar_producto(producto_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        campo, valor = _cambio_producto_payload_api(data)
        motivo = data.get("motivo") or "Edicion manual desde Almacen"

        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "productos")
            if "id" not in columnas:
                raise ValueError("La tabla productos no tiene id para edicion segura.")
            if campo not in columnas:
                raise ValueError(f"El campo {campo} no existe en productos.")

            anterior_row = conn.execute(
                "SELECT * FROM productos WHERE id=%s FOR UPDATE",
                (producto_id,),
            ).fetchone()
            anterior = _row_dict(anterior_row)
            if not anterior:
                raise LookupError("Producto no encontrado.")

            if campo == "color":
                duplicado = conn.execute("""
                    SELECT id
                    FROM productos
                    WHERE id<>%s
                      AND marca=%s
                      AND hilo=%s
                      AND codigo=%s
                      AND color=%s
                    LIMIT 1
                """, (
                    producto_id,
                    anterior.get("marca"),
                    anterior.get("hilo"),
                    anterior.get("codigo"),
                    valor,
                )).fetchone()
                if duplicado:
                    raise ValueError("Ya existe un producto con esa marca, hilo, codigo y color.")

            conn.execute(f"UPDATE productos SET {campo}=%s WHERE id=%s", (valor, producto_id))
            _registrar_movimiento_producto_edicion_api(conn, campo, anterior, valor, motivo, auth)

        producto = obtener_producto_por_id(producto_id)
        return jsonify({"ok": True, "producto": producto})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al editar producto por API")
        return jsonify({"ok": False, "error": "No se pudo editar el producto."}), 500


def _api_limite(valor, default=200, maximo=500):
    try:
        limit = int(valor)
    except Exception:
        limit = default
    return max(1, min(limit, maximo))


def _api_offset(valor):
    try:
        offset = int(valor)
    except Exception:
        offset = 0
    return max(0, offset)


def _json_safe(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if hasattr(valor, "isoformat"):
        try:
            return valor.isoformat()
        except Exception:
            pass
    if isinstance(valor, dict):
        return {k: _json_safe(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json_safe(v) for v in valor]
    return valor


def _row_dict(row):
    return _json_safe(dict(row)) if row else None


def _json_field(valor, default):
    if not valor:
        return default
    if isinstance(valor, (dict, list)):
        return valor
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except Exception:
            return default
    return default


def _normalizar_cliente_api(row):
    data = _row_dict(row)
    if not data:
        return None
    data["direccion"] = _json_field(data.get("direccion"), {})
    return data


def _normalizar_nota_api(row):
    data = _row_dict(row)
    if not data:
        return None
    data["envio"] = _json_field(data.get("envio"), {})
    total_guardado = _float_api(data.get("total"))
    tiene_subtotal = data.get("subtotal_productos") is not None
    subtotal_productos = _float_api(data.get("subtotal_productos")) if tiene_subtotal else total_guardado
    envio_precio = _precio_envio_api(data)
    total_final = subtotal_productos + envio_precio if tiene_subtotal else total_guardado
    data["subtotal_productos"] = round(subtotal_productos, 2)
    data["envio_precio"] = round(envio_precio, 2)
    data["total_final"] = round(total_final, 2)
    return data


def _float_api(valor, default=0.0):
    if valor is None or valor == "":
        return default
    try:
        return float(valor)
    except Exception:
        return default


def _precio_envio_api(nota):
    envio = nota.get("envio") or {}
    if not isinstance(envio, dict):
        return 0.0
    return _float_api(envio.get("precio"))


def _join_subtotal_items_nota_api():
    return """
        LEFT JOIN (
            SELECT
                nota_id,
                COALESCE(SUM(COALESCE(cantidad, 0) * COALESCE(precio, 0)), 0) AS subtotal_productos
            FROM items
            GROUP BY nota_id
        ) it ON it.nota_id = n.id
    """


def _columnas_tabla_api(conn, tabla):
    rows = conn.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name=%s
    """, (tabla,)).fetchall()
    return {row["column_name"] for row in rows}


def _sql_text_col(alias, columna, columnas, default="NULL"):
    if columna not in columnas:
        return default
    return f"NULLIF(CAST({alias}.{columna} AS TEXT), '')"


def _sql_num_col(alias, columna, columnas):
    if columna not in columnas:
        return "0"
    return f"COALESCE({alias}.{columna}, 0)"


def _join_producto_para_item(items_cols, productos_cols):
    if not productos_cols:
        return "", False

    condiciones = []
    if "producto_id" in items_cols and "id" in productos_cols:
        condiciones.append("p.id = i.producto_id")
    if "codigo" in items_cols and "codigo" in productos_cols:
        condiciones.append("CAST(p.codigo AS TEXT) = CAST(i.codigo AS TEXT)")
    if "codigo" in items_cols and "codigo_barras" in productos_cols:
        condiciones.append("CAST(p.codigo_barras AS TEXT) = CAST(i.codigo AS TEXT)")
    if "codigo_barras" in items_cols and "codigo_barras" in productos_cols:
        condiciones.append("CAST(p.codigo_barras AS TEXT) = CAST(i.codigo_barras AS TEXT)")
    if "codigo_barras" in items_cols and "codigo" in productos_cols:
        condiciones.append("CAST(p.codigo AS TEXT) = CAST(i.codigo_barras AS TEXT)")

    where = " OR ".join(condiciones) if condiciones else "FALSE"
    order = "p.id" if "id" in productos_cols else ("p.codigo" if "codigo" in productos_cols else "1")
    return f"""
        LEFT JOIN LATERAL (
            SELECT *
            FROM productos p
            WHERE {where}
            ORDER BY {order}
            LIMIT 1
        ) p ON TRUE
    """, True


def _normalizar_item_nota_api(row):
    data = _row_dict(row) or {}
    cantidad = data.get("cantidad") or 0
    precio = data.get("precio") or 0
    try:
        subtotal = float(cantidad) * float(precio)
    except Exception:
        subtotal = data.get("subtotal") or 0
    data["codigo"] = data.get("codigo") or ""
    data["marca"] = data.get("marca") or "No encontrado"
    data["hilo"] = data.get("hilo") or "No encontrado"
    data["color"] = data.get("color") or ""
    data["cantidad"] = cantidad
    data["precio"] = precio
    data["subtotal"] = round(float(subtotal or 0), 2)
    return data


def _items_nota_api_conn(conn, nota_id_real):
    items_cols = _columnas_tabla_api(conn, "items")
    productos_cols = _columnas_tabla_api(conn, "productos")
    join_productos, tiene_join_producto = _join_producto_para_item(items_cols, productos_cols)

    codigo_expr = "COALESCE({})".format(", ".join([
        _sql_text_col("i", "codigo", items_cols),
        _sql_text_col("i", "codigo_barras", items_cols),
        _sql_text_col("p", "codigo", productos_cols) if tiene_join_producto else "NULL",
        "''",
    ]))
    marca_expr = "COALESCE({})".format(", ".join([
        _sql_text_col("i", "marca", items_cols),
        _sql_text_col("p", "marca", productos_cols) if tiene_join_producto else "NULL",
        "'No encontrado'",
    ]))
    hilo_expr = "COALESCE({})".format(", ".join([
        _sql_text_col("i", "hilo", items_cols),
        _sql_text_col("p", "hilo", productos_cols) if tiene_join_producto else "NULL",
        "'No encontrado'",
    ]))
    color_expr = "COALESCE({})".format(", ".join([
        _sql_text_col("i", "color", items_cols),
        _sql_text_col("p", "color", productos_cols) if tiene_join_producto else "NULL",
        "''",
    ]))
    cantidad_expr = _sql_num_col("i", "cantidad", items_cols)
    precio_expr = _sql_num_col("i", "precio", items_cols)

    rows = conn.execute(f"""
        SELECT
            {codigo_expr} AS codigo,
            {marca_expr} AS marca,
            {hilo_expr} AS hilo,
            {color_expr} AS color,
            {cantidad_expr} AS cantidad,
            {precio_expr} AS precio,
            ({cantidad_expr} * {precio_expr}) AS subtotal
        FROM items
        i
        {join_productos}
        WHERE i.nota_id=%s
    """, (nota_id_real,)).fetchall()
    return [_normalizar_item_nota_api(row) for row in rows]


def _items_nota_api(nota_id):
    with get_conn() as conn:
        nota_id_real, _ = _resolver_nota_api(conn, nota_id)
        return _items_nota_api_conn(conn, nota_id_real)


def _pagos_nota_api_conn(conn, nota_id_real):
    rows = conn.execute("""
        SELECT *
        FROM pagos
        WHERE nota_id=%s
        ORDER BY fecha DESC
    """, (nota_id_real,)).fetchall()
    return [_row_dict(row) for row in rows]


def _pagos_nota_api(nota_id):
    with get_conn() as conn:
        nota_id_real, _ = _resolver_nota_api(conn, nota_id)
        return _pagos_nota_api_conn(conn, nota_id_real)


def _insertar_pago_api(conn, nota_id, comprobante=None):
    pagos_cols = _columnas_tabla_api(conn, "pagos")
    if "nota_id" not in pagos_cols:
        raise ValueError("La tabla pagos no tiene nota_id.")

    comprobante_valor = str(comprobante or "").strip()
    if comprobante_valor and "comprobante" in pagos_cols:
        existente = conn.execute("""
            SELECT *
            FROM pagos
            WHERE nota_id=%s AND comprobante=%s
            LIMIT 1
        """, (nota_id, comprobante_valor)).fetchone()
        if existente:
            return existente

    valores = {"nota_id": nota_id}
    if "comprobante" in pagos_cols:
        valores["comprobante"] = comprobante_valor or None
    campos = [campo for campo in valores if campo in pagos_cols]
    placeholders = ",".join(["%s"] * len(campos))
    returning = " RETURNING *"
    try:
        return conn.execute(
            f"INSERT INTO pagos({','.join(campos)}) VALUES ({placeholders}){returning}",
            tuple(valores[campo] for campo in campos),
        ).fetchone()
    except Exception:
        conn.execute(
            f"INSERT INTO pagos({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo] for campo in campos),
        )
        return None


def _actualizar_comprobante_nota_api(conn, nota_id, comprobante):
    nota_id_real, _ = _resolver_nota_api(conn, nota_id)
    notas_cols = _columnas_tabla_api(conn, "notas")
    if "comprobante" not in notas_cols:
        raise ValueError("La tabla notas no tiene campo comprobante.")
    conn.execute(
        "UPDATE notas SET comprobante=%s WHERE id=%s",
        (comprobante or None, nota_id_real),
    )


def _generar_id_nota_api(conn):
    conn.execute("LOCK TABLE notas IN SHARE ROW EXCLUSIVE MODE")
    row = conn.execute("""
        SELECT COALESCE(MAX(id), 'COT-00000') AS ultimo
        FROM notas
    """).fetchone()
    ultimo = str((row or {}).get("ultimo") or "COT-00000")
    try:
        numero = int(ultimo.split("-")[1])
    except Exception:
        numero = 0
    return f"COT-{numero + 1:05d}"


def _json_dump_api(valor):
    if not valor:
        return None
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False)


def _normalizar_direccion_cliente_payload(data, direccion_actual=None):
    direccion = _json_field(data.get("direccion"), direccion_actual or {})
    if not isinstance(direccion, dict):
        direccion = {}
    else:
        direccion = dict(direccion)

    aliases = {
        "calle": ("calle",),
        "numero_ext": ("numero_ext", "numero_exterior"),
        "numero_int": ("numero_int", "numero_interior"),
        "codigo_postal": ("codigo_postal", "cp"),
        "estado": ("estado",),
        "municipio": ("municipio",),
        "colonia": ("colonia",),
        "referencia": ("referencia",),
    }
    for destino, fuentes in aliases.items():
        for fuente in fuentes:
            if fuente in data:
                direccion[destino] = str(data.get(fuente) or "").strip()
                break
    return direccion


def _paqueteria_envio_api(envio):
    if not isinstance(envio, dict):
        return None
    return envio.get("tipo") or envio.get("paqueteria")


def _cliente_payload_nota_api(data):
    cliente = data.get("cliente") or {}
    cliente_id = data.get("cliente_id") or cliente.get("id")
    cliente_nombre = data.get("cliente_nombre") or cliente.get("nombre")
    if not cliente_id:
        raise ValueError("Falta cliente_id.")
    if not cliente_nombre:
        raise ValueError("Falta cliente_nombre.")
    return int(cliente_id), str(cliente_nombre)


def _normalizar_item_payload_api(item):
    codigo = str(item.get("codigo") or "").strip()
    if not codigo:
        raise ValueError("Hay un item sin codigo.")
    cantidad = _float_api(item.get("cantidad"))
    precio = _float_api(item.get("precio"))
    if cantidad <= 0:
        raise ValueError(f"Cantidad invalida para el codigo {codigo}.")
    if precio < 0:
        raise ValueError(f"Precio invalido para el codigo {codigo}.")
    return {
        "codigo": codigo,
        "marca": item.get("marca") or "",
        "hilo": item.get("hilo") or "",
        "color": item.get("color") or "",
        "cantidad": cantidad,
        "precio": precio,
    }


def _items_payload_nota_api(data):
    items = data.get("items") or data.get("carrito") or []
    if not isinstance(items, list) or not items:
        raise ValueError("La nota debe tener al menos un item.")
    return [_normalizar_item_payload_api(item) for item in items]


def _subtotal_items_payload_api(items):
    return round(sum(item["cantidad"] * item["precio"] for item in items), 2)


def _insertar_items_nota_api(conn, nota_id, items):
    for item in items:
        conn.execute("""
            INSERT INTO items(nota_id, codigo, marca, hilo, color, cantidad, precio)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            nota_id,
            item["codigo"],
            item["marca"],
            item["hilo"],
            item.get("color"),
            item["cantidad"],
            item["precio"],
        ))


def _resolver_nota_api(conn, nota_ref, bloquear=False):
    ref = str(nota_ref or "").strip()
    if not ref:
        raise LookupError("Falta identificador de nota.")

    notas_cols = _columnas_tabla_api(conn, "notas")
    if not notas_cols:
        raise LookupError("No se encontro la tabla de notas.")

    campos_posibles = (
        "id",
        "folio",
        "folio_nota",
        "codigo_nota",
        "numero_nota",
        "pedido",
        "codigo",
        "numero",
        "referencia",
    )
    campos = []
    for campo in campos_posibles:
        if campo in notas_cols and campo not in campos:
            campos.append(campo)
    if not campos:
        raise LookupError("No hay campos disponibles para buscar la nota.")

    condiciones = [f"CAST({campo} AS TEXT)=%s" for campo in campos]
    valores = [ref] * len(campos)
    orden = ""
    if "id" in campos:
        orden = "ORDER BY CASE WHEN CAST(id AS TEXT)=%s THEN 0 ELSE 1 END"
        valores.append(ref)
    bloqueo = " FOR UPDATE" if bloquear else ""

    row = conn.execute(
        f"SELECT * FROM notas WHERE {' OR '.join(condiciones)} {orden} LIMIT 1{bloqueo}",
        tuple(valores),
    ).fetchone()
    if not row:
        raise LookupError(f"No se encontro la nota {ref}.")
    nota = _row_dict(row) or {}
    return nota.get("id"), nota


def _obtener_nota_raw_api(conn, nota_id):
    _, nota = _resolver_nota_api(conn, nota_id)
    return nota


MENSAJE_COTIZACION_NO_PAGABLE = (
    "No puedes marcar como pagada una cotización. Primero conviértela a venta "
    "y completa los datos de envío."
)
ESTADOS_COTIZACION_NO_PAGABLE = {"COTIZACION", "COTIZACION_PENDIENTE"}
ESTADOS_VENTA_PAGABLE = {"VENTA", "VENTA_PENDIENTE", "EN_PROCESO", "COMPLETA"}
ESTADOS_NOTA_PAGADA_API = {"PAGADA", "COMPLETA", "VENTA_PAGADA"}
STOCK_MINIMO_API = 50


class NotaPagoNoPermitido(Exception):
    def __init__(self, mensaje, status=400):
        super().__init__(mensaje)
        self.status = status


class StockAutorizacionRequerida(Exception):
    def __init__(self, productos):
        super().__init__("Algunos productos no tienen stock suficiente. Revisa la lista antes de continuar.")
        self.productos = productos


def _normalizar_estado_pago_api(estado):
    return str(estado or "").strip().upper().replace("Ó", "O")


def _nota_tiene_pagos_api(conn, nota_id):
    try:
        pagos_cols = _columnas_tabla_api(conn, "pagos")
        if "nota_id" not in pagos_cols:
            return False
        row = conn.execute("SELECT 1 FROM pagos WHERE nota_id=%s LIMIT 1", (nota_id,)).fetchone()
        return bool(row)
    except Exception:
        return False


def _nota_requiere_devolucion_stock_api(conn, nota):
    if not nota:
        return False
    estado = _normalizar_estado_pago_api(nota.get("estado"))
    if estado in ESTADOS_NOTA_PAGADA_API:
        return True
    if nota.get("fecha_pago"):
        return True
    return _nota_tiene_pagos_api(conn, nota.get("id"))


def _direccion_cliente_completa_api(direccion):
    if not isinstance(direccion, dict):
        return False
    campos = (
        direccion.get("calle"),
        direccion.get("numero_ext") or direccion.get("numero_exterior"),
        direccion.get("colonia"),
        direccion.get("codigo_postal") or direccion.get("cp"),
        direccion.get("estado"),
        direccion.get("municipio"),
    )
    return all(str(campo or "").strip() for campo in campos)


def _validar_nota_pagable_api(conn, nota):
    estado = _normalizar_estado_pago_api(nota.get("estado"))
    if estado in ESTADOS_COTIZACION_NO_PAGABLE:
        raise NotaPagoNoPermitido(MENSAJE_COTIZACION_NO_PAGABLE, 409)
    if estado not in ESTADOS_VENTA_PAGABLE:
        raise NotaPagoNoPermitido("Solo una venta puede marcarse como pagada.", 400)
    if nota.get("fecha_pago"):
        raise NotaPagoNoPermitido("Esta nota ya tiene pago registrado.", 409)
    pago_existente = conn.execute(
        "SELECT 1 FROM pagos WHERE nota_id=%s LIMIT 1",
        (nota.get("id"),),
    ).fetchone()
    if pago_existente:
        raise NotaPagoNoPermitido("Esta nota ya tiene pago registrado.", 409)

    envio = _json_field(nota.get("envio"), {})
    if not isinstance(envio, dict) or not envio:
        raise NotaPagoNoPermitido(
            "Primero completa los datos de envio antes de marcar la venta como pagada.",
            400,
        )

    cliente_id = nota.get("cliente_id")
    if not cliente_id:
        raise NotaPagoNoPermitido("Primero completa los datos del cliente.", 400)
    cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    if not cliente:
        raise NotaPagoNoPermitido("Primero completa los datos del cliente.", 400)

    telefono = str(cliente.get("telefono") or "").strip()
    direccion = _json_field(cliente.get("direccion"), {})
    if not cliente.get("nombre") or not telefono.isdigit() or len(telefono) != 10:
        raise NotaPagoNoPermitido("Primero completa los datos del cliente.", 400)
    if not _direccion_cliente_completa_api(direccion):
        raise NotaPagoNoPermitido("Primero completa la direccion de envio del cliente.", 400)


def _normalizar_estado_convertible_api(estado):
    return str(estado or "").strip().upper().replace("Ó", "O")


def _producto_inventariable_api(producto):
    if not producto:
        return True
    tipo = str(producto.get("tipo_producto") or producto.get("tipo") or "").strip().upper().replace(" ", "_").replace("-", "_")
    if tipo in {"ITEM", "ITEM_COTIZACION", "ANULADO", "INACTIVO", "COTIZACION", "PAQUETE", "PAQUETES", "COMBO", "COMBOS", "SERVICIO"}:
        return False
    valor = producto.get("es_inventariable", True)
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    if isinstance(valor, str):
        return valor.strip().lower() not in ("false", "f", "0", "no", "n", "item")
    return True


def _cantidad_item_stock_api(item):
    cantidad = _float_api(item.get("cantidad"))
    try:
        return int(cantidad)
    except Exception:
        return 0


def _buscar_producto_item_api(conn, item, bloquear=False):
    productos_cols = _columnas_tabla_api(conn, "productos")
    if not productos_cols:
        return None

    bloqueo = " FOR UPDATE" if bloquear else ""
    condiciones = []
    valores = []
    codigo = str(item.get("codigo") or "").strip()
    marca = str(item.get("marca") or "").strip()
    hilo = str(item.get("hilo") or "").strip()

    if codigo and marca and hilo and {"codigo", "marca", "hilo"}.issubset(productos_cols):
        exacto = conn.execute(
            f"SELECT * FROM productos WHERE marca=%s AND hilo=%s AND codigo=%s LIMIT 1{bloqueo}",
            (marca, hilo, codigo),
        ).fetchone()
        if exacto:
            return exacto
    if codigo and "codigo" in productos_cols:
        condiciones.append("CAST(codigo AS TEXT)=%s")
        valores.append(codigo)
    if codigo and "codigo_barras" in productos_cols:
        condiciones.append("CAST(codigo_barras AS TEXT)=%s")
        valores.append(codigo)
    if not condiciones:
        return None

    return conn.execute(
        f"SELECT * FROM productos WHERE {' OR '.join(condiciones)} LIMIT 1{bloqueo}",
        tuple(valores),
    ).fetchone()


def _items_stock_nota_api(conn, nota_id, bloquear=False):
    nota_id_real, _ = _resolver_nota_api(conn, nota_id)
    rows = conn.execute("""
        SELECT codigo, marca, hilo, color, cantidad, precio
        FROM items
        WHERE nota_id=%s
    """, (nota_id_real,)).fetchall()
    lineas = []
    afectados = []
    for row in rows:
        item = _row_dict(row) or {}
        producto = _buscar_producto_item_api(conn, item, bloquear=bloquear)
        producto_data = _row_dict(producto) or {}
        cantidad = _cantidad_item_stock_api(item)

        if producto_data and not _producto_inventariable_api(producto_data):
            lineas.append((item, producto_data, None))
            continue

        stock_actual = int((producto_data or {}).get("stock") or 0)
        faltante = max(cantidad - stock_actual, 0)
        estado_stock = None
        if not producto_data or stock_actual <= 0:
            estado_stock = "STOCK NULO"
            faltante = cantidad
        elif stock_actual < cantidad:
            estado_stock = "STOCK INSUFICIENTE"
        elif stock_actual < STOCK_MINIMO_API:
            estado_stock = "STOCK BAJO"
            faltante = 0

        afectado = None
        if estado_stock:
            afectado = {
                "codigo": item.get("codigo") or producto_data.get("codigo") or "",
                "marca": item.get("marca") or producto_data.get("marca") or "",
                "hilo": item.get("hilo") or producto_data.get("hilo") or "",
                "color": item.get("color") or producto_data.get("color") or "",
                "cantidad_solicitada": cantidad,
                "stock_actual": stock_actual,
                "faltante": faltante,
                "estado": estado_stock,
            }
            afectados.append(afectado)
        lineas.append((item, producto_data, afectado))
    return lineas, afectados


def _clave_stock_autorizada_api(data):
    clave = (
        data.get("autorizacion_stock")
        or data.get("clave_autorizacion")
        or data.get("clave")
        or data.get("authorization_code")
        or ""
    )
    return str(clave).strip() == "1"


def _usuario_auth_api(auth):
    if not auth:
        return "usuario_desconocido"
    return auth.get("usuario") or auth.get("usuario_nombre") or str(auth.get("usuario_id") or "usuario_desconocido")


def _registrar_movimiento_almacen_api(conn, tipo, item, producto, cantidad, motivo, auth):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return
    stock_anterior = int((producto or {}).get("stock") or 0) if producto else None
    stock_nuevo = (producto or {}).get("_stock_nuevo")
    tipos_salida = {"SALIDA_STOCK_API", "AJUSTE_ADMIN_NOTA_PAGADA_DESCUENTO"}
    if stock_nuevo is None:
        stock_nuevo = stock_anterior - int(cantidad) if stock_anterior is not None and tipo in tipos_salida else stock_anterior
    valores = {
        "fecha": datetime.now(),
        "usuario": _usuario_auth_api(auth),
        "tipo": tipo,
        "marca": (item or {}).get("marca") or (producto or {}).get("marca"),
        "hilo": (item or {}).get("hilo") or (producto or {}).get("hilo"),
        "color": (item or {}).get("color") or (producto or {}).get("color"),
        "codigo": (item or {}).get("codigo") or (producto or {}).get("codigo"),
        "stock_anterior": stock_anterior,
        "stock_nuevo": stock_nuevo,
        "cantidad": -int(cantidad) if tipo in tipos_salida else int(cantidad or 0),
        "campo": "stock",
        "valor_anterior": stock_anterior,
        "valor_nuevo": stock_nuevo,
        "motivo": motivo,
    }
    campos = [campo for campo in valores if campo in columnas]
    if not campos:
        return
    placeholders = ",".join(["%s"] * len(campos))
    try:
        conn.execute("SAVEPOINT sp_movimiento_almacen")
        conn.execute(
            f"INSERT INTO movimientos_almacen({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo] for campo in campos),
        )
        conn.execute("RELEASE SAVEPOINT sp_movimiento_almacen")
    except Exception:
        app.logger.warning("No se pudo registrar movimiento de almacen %s", tipo, exc_info=True)
        try:
            conn.execute("ROLLBACK TO SAVEPOINT sp_movimiento_almacen")
            conn.execute("RELEASE SAVEPOINT sp_movimiento_almacen")
        except Exception:
            pass


def _registrar_autorizacion_stock_api(conn, nota_id, productos, accion, auth):
    if not productos:
        return
    detalle_productos = "; ".join(
        f"{p.get('codigo')} solicitado={p.get('cantidad_solicitada')} stock={p.get('stock_actual')} estado={p.get('estado')}"
        for p in productos
    )
    usuario = _usuario_auth_api(auth)
    motivo = (
        f"Operacion autorizada con stock insuficiente | nota={nota_id} | "
        f"accion={accion} | usuario={usuario} | productos={detalle_productos}"
    )
    for producto in productos:
        item = {
            "codigo": producto.get("codigo"),
            "marca": producto.get("marca"),
            "hilo": producto.get("hilo"),
            "color": producto.get("color"),
        }
        _registrar_movimiento_almacen_api(
            conn,
            "AUTORIZACION_STOCK",
            item,
            {"stock": producto.get("stock_actual")},
            producto.get("cantidad_solicitada") or 0,
            motivo,
            auth,
        )
    notas_cols = _columnas_tabla_api(conn, "notas")
    campo_notas = "observaciones" if "observaciones" in notas_cols else ("notas" if "notas" in notas_cols else None)
    if campo_notas:
        row = conn.execute(f"SELECT {campo_notas} FROM notas WHERE id=%s", (nota_id,)).fetchone()
        anterior = (row or {}).get(campo_notas) or ""
        nuevo = f"{anterior}\n[{datetime.now().isoformat(timespec='seconds')}] {motivo}".strip()
        conn.execute(f"UPDATE notas SET {campo_notas}=%s WHERE id=%s", (nuevo, nota_id))


def _descontar_stock_nota_api(conn, nota_id, auth, autorizacion_stock=False):
    lineas, afectados = _items_stock_nota_api(conn, nota_id, bloquear=True)
    if afectados and not autorizacion_stock:
        raise StockAutorizacionRequerida(afectados)
    if afectados:
        _registrar_autorizacion_stock_api(conn, nota_id, afectados, "pago", auth)

    productos_cols = _columnas_tabla_api(conn, "productos")
    for item, producto, _ in lineas:
        if not producto or not _producto_inventariable_api(producto):
            continue
        cantidad = _cantidad_item_stock_api(item)
        stock_anterior = int(producto.get("stock") or 0)
        stock_nuevo = stock_anterior - cantidad
        estado_nuevo = "OK" if stock_nuevo >= STOCK_MINIMO_API else "RESURTIR"
        if "id" in productos_cols and producto.get("id") is not None:
            if "estado" in productos_cols:
                conn.execute(
                    "UPDATE productos SET stock=%s, estado=%s WHERE id=%s",
                    (stock_nuevo, estado_nuevo, producto.get("id")),
                )
            else:
                conn.execute(
                    "UPDATE productos SET stock=%s WHERE id=%s",
                    (stock_nuevo, producto.get("id")),
                )
        else:
            if "estado" in productos_cols:
                conn.execute(
                    "UPDATE productos SET stock=%s, estado=%s WHERE marca=%s AND hilo=%s AND codigo=%s",
                    (stock_nuevo, estado_nuevo, producto.get("marca"), producto.get("hilo"), producto.get("codigo")),
                )
            else:
                conn.execute(
                    "UPDATE productos SET stock=%s WHERE marca=%s AND hilo=%s AND codigo=%s",
                    (stock_nuevo, producto.get("marca"), producto.get("hilo"), producto.get("codigo")),
                )
        _registrar_movimiento_almacen_api(
            conn,
            "SALIDA_STOCK_API",
            item,
            producto,
            cantidad,
            f"Descuento por pago de nota {nota_id}",
            auth,
        )


def _devolucion_stock_existente_api(conn, nota_id):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if not columnas:
        return False
    filtros = []
    valores = []
    if "tipo" in columnas:
        filtros.append("tipo IN (%s,%s)")
        valores.extend(["DEVOLUCION_POR_ANULACION", "STOCK_RESTABLECIDO_NOTA_PAGADA"])
    if "motivo" in columnas:
        filtros.append("motivo ILIKE %s")
        valores.append(f"%{nota_id}%")
    if not filtros:
        return False
    row = conn.execute(
        f"SELECT 1 FROM movimientos_almacen WHERE {' AND '.join(filtros)} LIMIT 1",
        tuple(valores),
    ).fetchone()
    return bool(row)


def _devolver_stock_nota_api(conn, nota_id, auth):
    if _devolucion_stock_existente_api(conn, nota_id):
        raise NotaPagoNoPermitido("Esta nota ya fue anulada o el stock ya fue regresado.", 409)

    lineas, _ = _items_stock_nota_api(conn, nota_id, bloquear=True)
    productos_cols = _columnas_tabla_api(conn, "productos")
    productos_devueltos = []
    for item, producto, _ in lineas:
        if not producto:
            etiqueta = " ".join(
                str(item.get(campo) or "").strip()
                for campo in ("marca", "hilo", "color", "codigo")
                if str(item.get(campo) or "").strip()
            ) or str(item.get("codigo") or "sin codigo")
            raise ValueError(f"No se pudo resolver el producto {etiqueta} para regresar stock.")
        if not _producto_inventariable_api(producto):
            continue
        cantidad = _cantidad_item_stock_api(item)
        stock_anterior = int(producto.get("stock") or 0)
        stock_nuevo = stock_anterior + cantidad
        estado_nuevo = "OK" if stock_nuevo >= STOCK_MINIMO_API else "RESURTIR"
        if "id" in productos_cols and producto.get("id") is not None:
            if "estado" in productos_cols:
                conn.execute(
                    "UPDATE productos SET stock=%s, estado=%s WHERE id=%s",
                    (stock_nuevo, estado_nuevo, producto.get("id")),
                )
            else:
                conn.execute(
                    "UPDATE productos SET stock=%s WHERE id=%s",
                    (stock_nuevo, producto.get("id")),
                )
        else:
            if "estado" in productos_cols:
                conn.execute(
                    "UPDATE productos SET stock=%s, estado=%s WHERE marca=%s AND hilo=%s AND codigo=%s",
                    (stock_nuevo, estado_nuevo, producto.get("marca"), producto.get("hilo"), producto.get("codigo")),
                )
            else:
                conn.execute(
                    "UPDATE productos SET stock=%s WHERE marca=%s AND hilo=%s AND codigo=%s",
                    (stock_nuevo, producto.get("marca"), producto.get("hilo"), producto.get("codigo")),
                )
        producto_mov = dict(producto)
        producto_mov["_stock_nuevo"] = stock_nuevo
        _registrar_movimiento_almacen_api(
            conn,
            "DEVOLUCION_POR_ANULACION",
            item,
            producto_mov,
            cantidad,
            f"Stock regresado por anulacion de nota pagada autorizada. nota={nota_id}",
            auth,
        )
        productos_devueltos.append({
            "codigo": item.get("codigo") or producto.get("codigo") or "",
            "marca": item.get("marca") or producto.get("marca") or "",
            "hilo": item.get("hilo") or producto.get("hilo") or "",
            "color": item.get("color") or producto.get("color") or "",
            "cantidad": cantidad,
            "stock_anterior": stock_anterior,
            "stock_nuevo": stock_nuevo,
        })
    return productos_devueltos


def _items_actuales_nota_api(conn, nota_id, bloquear=False):
    bloqueo = " FOR UPDATE" if bloquear else ""
    nota_id_real, _ = _resolver_nota_api(conn, nota_id)
    rows = conn.execute(f"""
        SELECT codigo, marca, hilo, color, cantidad, precio
        FROM items
        WHERE nota_id=%s{bloqueo}
    """, (nota_id_real,)).fetchall()
    return [_normalizar_item_payload_api(_row_dict(row) or {}) for row in rows]


def _clave_producto_ajuste_api(producto, item):
    producto_data = _row_dict(producto) or {}
    if producto_data.get("id") is not None:
        return ("producto_id", str(producto_data.get("id")))
    return (
        "producto",
        str(item.get("marca") or "").strip().upper(),
        str(item.get("hilo") or "").strip().upper(),
        str(item.get("codigo") or "").strip().upper(),
    )


def _agrupar_items_ajuste_api(conn, items, bloquear=False):
    grupos = {}
    for item in items or []:
        producto = _buscar_producto_item_api(conn, item, bloquear=bloquear)
        producto_data = _row_dict(producto) or {}
        clave = _clave_producto_ajuste_api(producto_data, item)
        if clave not in grupos:
            grupos[clave] = {
                "cantidad": 0,
                "item": dict(item),
                "producto": producto_data,
            }
        grupos[clave]["cantidad"] += _cantidad_item_stock_api(item)
    return grupos


def _actualizar_stock_producto_api(conn, producto, stock_nuevo):
    productos_cols = _columnas_tabla_api(conn, "productos")
    estado_nuevo = "OK" if int(stock_nuevo) >= STOCK_MINIMO_API else "RESURTIR"
    if "id" in productos_cols and producto.get("id") is not None:
        if "estado" in productos_cols:
            conn.execute(
                "UPDATE productos SET stock=%s, estado=%s WHERE id=%s",
                (stock_nuevo, estado_nuevo, producto.get("id")),
            )
        else:
            conn.execute(
                "UPDATE productos SET stock=%s WHERE id=%s",
                (stock_nuevo, producto.get("id")),
            )
    else:
        if "estado" in productos_cols:
            conn.execute(
                "UPDATE productos SET stock=%s, estado=%s WHERE marca=%s AND hilo=%s AND codigo=%s",
                (stock_nuevo, estado_nuevo, producto.get("marca"), producto.get("hilo"), producto.get("codigo")),
            )
        else:
            conn.execute(
                "UPDATE productos SET stock=%s WHERE marca=%s AND hilo=%s AND codigo=%s",
                (stock_nuevo, producto.get("marca"), producto.get("hilo"), producto.get("codigo")),
            )


def _agregar_observacion_nota_api(conn, nota_id, detalle):
    notas_cols = _columnas_tabla_api(conn, "notas")
    campo_notas = "observaciones" if "observaciones" in notas_cols else ("notas" if "notas" in notas_cols else None)
    if not campo_notas:
        return
    row = conn.execute(f"SELECT {campo_notas} FROM notas WHERE id=%s", (nota_id,)).fetchone()
    anterior = (row or {}).get(campo_notas) or ""
    nuevo = f"{anterior}\n[{datetime.now().isoformat(timespec='seconds')}] {detalle}".strip()
    conn.execute(f"UPDATE notas SET {campo_notas}=%s WHERE id=%s", (nuevo, nota_id))


def _ajustar_stock_items_pagados_api(conn, nota_id, items_originales, items_nuevos, auth, motivo):
    grupos_originales = _agrupar_items_ajuste_api(conn, items_originales, bloquear=True)
    grupos_nuevos = _agrupar_items_ajuste_api(conn, items_nuevos, bloquear=True)
    claves = set(grupos_originales.keys()) | set(grupos_nuevos.keys())
    movimientos = []
    afectados = []

    for clave in claves:
        anterior = grupos_originales.get(clave, {})
        nuevo = grupos_nuevos.get(clave, {})
        cantidad_anterior = int(anterior.get("cantidad") or 0)
        cantidad_nueva = int(nuevo.get("cantidad") or 0)
        diferencia = cantidad_nueva - cantidad_anterior
        if diferencia == 0:
            continue

        item_base = nuevo.get("item") or anterior.get("item") or {}
        producto = nuevo.get("producto") or anterior.get("producto") or {}
        if not producto:
            raise ValueError(
                f"No se pudo localizar el producto {item_base.get('marca')} {item_base.get('hilo')} {item_base.get('codigo')} para ajustar stock."
            )
        if not _producto_inventariable_api(producto):
            continue

        stock_anterior = int(producto.get("stock") or 0)
        stock_nuevo = stock_anterior - diferencia
        if diferencia > 0:
            faltante = max(diferencia - stock_anterior, 0)
            if faltante > 0 or stock_nuevo < STOCK_MINIMO_API:
                afectados.append({
                    "codigo": item_base.get("codigo") or producto.get("codigo") or "",
                    "marca": item_base.get("marca") or producto.get("marca") or "",
                    "hilo": item_base.get("hilo") or producto.get("hilo") or "",
                    "color": item_base.get("color") or producto.get("color") or "",
                    "cantidad_solicitada": diferencia,
                    "stock_actual": stock_anterior,
                    "faltante": faltante,
                    "estado": "STOCK INSUFICIENTE" if faltante else "STOCK BAJO",
                })

        _actualizar_stock_producto_api(conn, producto, stock_nuevo)
        producto_mov = dict(producto)
        producto_mov["_stock_nuevo"] = stock_nuevo
        tipo_mov = (
            "AJUSTE_ADMIN_NOTA_PAGADA_DESCUENTO"
            if diferencia > 0
            else "AJUSTE_ADMIN_NOTA_PAGADA_DEVOLUCION"
        )
        detalle = (
            f"{motivo}. nota={nota_id}; cantidad_anterior={cantidad_anterior}; "
            f"cantidad_nueva={cantidad_nueva}; diferencia={diferencia}"
        )
        _registrar_movimiento_almacen_api(
            conn,
            tipo_mov,
            item_base,
            producto_mov,
            abs(diferencia),
            detalle,
            auth,
        )
        movimientos.append({
            "codigo": item_base.get("codigo") or producto.get("codigo") or "",
            "marca": item_base.get("marca") or producto.get("marca") or "",
            "hilo": item_base.get("hilo") or producto.get("hilo") or "",
            "color": item_base.get("color") or producto.get("color") or "",
            "cantidad_anterior": cantidad_anterior,
            "cantidad_nueva": cantidad_nueva,
            "diferencia": diferencia,
            "stock_anterior": stock_anterior,
            "stock_nuevo": stock_nuevo,
            "tipo": tipo_mov,
        })

    if afectados:
        _registrar_autorizacion_stock_api(conn, nota_id, afectados, "ajuste_admin_nota_pagada", auth)
    return movimientos, afectados


def _registrar_anulacion_nota_api(conn, nota_id, detalle):
    notas_cols = _columnas_tabla_api(conn, "notas")
    campo_notas = "observaciones" if "observaciones" in notas_cols else ("notas" if "notas" in notas_cols else None)
    if campo_notas:
        row = conn.execute(f"SELECT {campo_notas} FROM notas WHERE id=%s", (nota_id,)).fetchone()
        anterior = (row or {}).get(campo_notas) or ""
        nuevo = f"{anterior}\n[{datetime.now().isoformat(timespec='seconds')}] {detalle}".strip()
        conn.execute(f"UPDATE notas SET {campo_notas}=%s WHERE id=%s", (nuevo, nota_id))


def _respuesta_stock_requiere_autorizacion(exc):
    return jsonify({
        "ok": False,
        "error": "Algunos productos no tienen stock suficiente. Revisa la lista antes de continuar.",
        "requiere_autorizacion_stock": True,
        "productos_afectados": exc.productos,
    }), 409


def _nota_con_detalle_api(nota_id):
    with get_conn() as conn:
        nota_id_real, _ = _resolver_nota_api(conn, nota_id)
        row = conn.execute(f"""
            SELECT n.*, it.subtotal_productos
            FROM notas n
            {_join_subtotal_items_nota_api()}
            WHERE n.id=%s
        """, (nota_id_real,)).fetchone()
    nota = _normalizar_nota_api(row)
    if nota:
        nota["items"] = _items_nota_api(nota_id_real)
    return nota


def _cliente_nota_api_conn(conn, nota):
    cliente_id = (nota or {}).get("cliente_id")
    if not cliente_id:
        return None
    try:
        row = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
    except Exception:
        app.logger.exception("No se pudo consultar cliente de nota")
        return None
    return _normalizar_cliente_api(row)


def _detalle_completo_nota_api(nota_id):
    with get_conn() as conn:
        nota_id_real, _ = _resolver_nota_api(conn, nota_id)
        row = conn.execute(f"""
            SELECT n.*, it.subtotal_productos
            FROM notas n
            {_join_subtotal_items_nota_api()}
            WHERE n.id=%s
        """, (nota_id_real,)).fetchone()
        nota = _normalizar_nota_api(row)
        if not nota:
            raise LookupError(f"No se encontro la nota {nota_id}.")

        items = _items_nota_api_conn(conn, nota_id_real)
        pagos = _pagos_nota_api_conn(conn, nota_id_real)
        cliente = _cliente_nota_api_conn(conn, nota)

    nota["items"] = items
    nota["pagos"] = pagos
    nota["cliente"] = cliente
    totales = {
        "subtotal_productos": nota.get("subtotal_productos", 0),
        "envio_precio": nota.get("envio_precio", 0),
        "total_final": nota.get("total_final", 0),
    }
    return {
        "nota": nota,
        "items": items,
        "pagos": pagos,
        "cliente": cliente,
        "envio": nota.get("envio") or {},
        "comprobante": nota.get("comprobante"),
        "totales": totales,
        "estado": nota.get("estado"),
        "fecha_pago": nota.get("fecha_pago"),
        "observaciones": nota.get("observaciones") or nota.get("notas"),
    }


def _validar_no_escritura_restringida_nota_api(conn, nota_id, data):
    _, actual = _resolver_nota_api(conn, nota_id)

    estado_actual = actual.get("estado")
    estado_nuevo = data.get("estado")
    if estado_nuevo == "PAGADA":
        raise PermissionError("Marcar como pagada todavia no esta disponible en modo API.")
    if estado_nuevo and estado_nuevo != estado_actual:
        raise PermissionError("Cambiar el estado de la nota todavia no esta disponible en modo API.")

    if data.get("fecha_pago") not in (None, "", actual.get("fecha_pago")):
        raise PermissionError("Modificar pagos todavia no esta disponible en modo API.")
    if data.get("comprobante") not in (None, "", actual.get("comprobante")):
        raise PermissionError("Modificar comprobantes todavia no esta disponible en modo API.")

    return actual


def _respuesta_error_nota_api(exc, accion="guardar"):
    if isinstance(exc, StockAutorizacionRequerida):
        return _respuesta_stock_requiere_autorizacion(exc)
    if isinstance(exc, NotaPagoNoPermitido):
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    if isinstance(exc, ValueError):
        return jsonify({"ok": False, "error": str(exc)}), 400
    if isinstance(exc, LookupError):
        return jsonify({"ok": False, "error": str(exc)}), 404
    if isinstance(exc, PermissionError):
        return jsonify({"ok": False, "error": str(exc)}), 403
    app.logger.exception("Error al %s nota por API", accion)
    return jsonify({
        "ok": False,
        "error": f"No se pudo {accion} la nota. Revisa logs del backend para ver el detalle.",
    }), 500


@app.route("/api/clientes", methods=["GET"])
def api_clientes_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        q = (request.args.get("q") or "").strip()
        telefono = (request.args.get("telefono") or "").strip()
        limit = _api_limite(request.args.get("limit"))
        offset = _api_offset(request.args.get("offset"))
        filtros = []
        valores = []
        if telefono:
            filtros.append("telefono ILIKE %s")
            valores.append(f"%{telefono}%")
        if q:
            filtros.append("(nombre ILIKE %s OR telefono ILIKE %s)")
            valores.extend([f"%{q}%", f"%{q}%"])
        where = "WHERE " + " AND ".join(filtros) if filtros else ""

        with get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM clientes {where}",
                tuple(valores),
            ).fetchone()["total"]
            rows = conn.execute(f"""
                SELECT *
                FROM clientes
                {where}
                ORDER BY nombre
                LIMIT %s OFFSET %s
            """, tuple(valores) + (limit, offset)).fetchall()

        return jsonify({
            "ok": True,
            "clientes": [_normalizar_cliente_api(row) for row in rows],
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
        })
    except Exception:
        app.logger.exception("Error al listar clientes")
        return jsonify({"ok": False, "error": "No se pudieron consultar los clientes."}), 500


@app.route("/api/clientes", methods=["POST"])
def api_clientes_crear():
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        nombre = str(data.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"ok": False, "error": "Falta nombre del cliente."}), 400

        telefono = str(data.get("telefono") or "").strip()
        direccion = _json_field(data.get("direccion"), {})

        with get_conn() as conn:
            existente = conn.execute("""
                SELECT *
                FROM clientes
                WHERE LOWER(nombre)=LOWER(%s)
                LIMIT 1
            """, (nombre,)).fetchone()
            if existente:
                return jsonify({"ok": True, "cliente": _normalizar_cliente_api(existente), "creado": False})

            clientes_cols = _columnas_tabla_api(conn, "clientes")
            valores = {
                "nombre": nombre,
                "telefono": telefono,
                "direccion": _json_dump_api(direccion),
            }
            campos = [campo for campo in valores if campo in clientes_cols]
            placeholders = ",".join(["%s"] * len(campos))
            row = conn.execute(
                f"INSERT INTO clientes ({','.join(campos)}) VALUES ({placeholders}) RETURNING *",
                tuple(valores[campo] for campo in campos),
            ).fetchone()

        return jsonify({"ok": True, "cliente": _normalizar_cliente_api(row), "creado": True}), 201
    except Exception:
        app.logger.exception("Error al crear cliente")
        return jsonify({"ok": False, "error": "No se pudo crear el cliente."}), 500


@app.route("/api/clientes/buscar", methods=["GET"])
def api_clientes_buscar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        q = (request.args.get("q") or "").strip()
        telefono = (request.args.get("telefono") or "").strip()
        limit = _api_limite(request.args.get("limit"))
        offset = _api_offset(request.args.get("offset"))
        filtros = []
        valores = []
        if telefono:
            filtros.append("telefono=%s")
            valores.append(telefono)
        if q:
            filtros.append("(nombre ILIKE %s OR telefono ILIKE %s)")
            valores.extend([f"%{q}%", f"%{q}%"])
        where = "WHERE " + " AND ".join(filtros) if filtros else ""

        with get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM clientes {where}",
                tuple(valores),
            ).fetchone()["total"]
            rows = conn.execute(f"""
                SELECT *
                FROM clientes
                {where}
                ORDER BY nombre
                LIMIT %s OFFSET %s
            """, tuple(valores) + (limit, offset)).fetchall()

        return jsonify({
            "ok": True,
            "clientes": [_normalizar_cliente_api(row) for row in rows],
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
        })
    except Exception:
        app.logger.exception("Error al buscar clientes")
        return jsonify({"ok": False, "error": "No se pudieron buscar clientes."}), 500


@app.route("/api/clientes/<int:cliente_id>", methods=["GET"])
def api_clientes_obtener(cliente_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
        cliente = _normalizar_cliente_api(row)
        if not cliente:
            return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404
        return jsonify({"ok": True, "cliente": cliente})
    except Exception:
        app.logger.exception("Error al obtener cliente")
        return jsonify({"ok": False, "error": "No se pudo consultar el cliente."}), 500


@app.route("/api/clientes/<int:cliente_id>", methods=["PATCH"])
def api_clientes_actualizar(cliente_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        with get_conn() as conn:
            actual = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
            if not actual:
                return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404

            clientes_cols = _columnas_tabla_api(conn, "clientes")
            cambios = {}
            if "nombre" in data and "nombre" in clientes_cols:
                nombre = str(data.get("nombre") or "").strip()
                if not nombre:
                    return jsonify({"ok": False, "error": "Falta nombre del cliente."}), 400
                cambios["nombre"] = nombre
            if "telefono" in data and "telefono" in clientes_cols:
                cambios["telefono"] = str(data.get("telefono") or "").strip()

            campos_direccion = {
                "direccion",
                "calle",
                "numero_ext",
                "numero_exterior",
                "numero_int",
                "numero_interior",
                "cp",
                "codigo_postal",
                "estado",
                "municipio",
                "colonia",
                "referencia",
            }
            if campos_direccion.intersection(data.keys()) and "direccion" in clientes_cols:
                direccion_actual = _json_field(actual.get("direccion"), {})
                direccion = _normalizar_direccion_cliente_payload(data, direccion_actual)
                cambios["direccion"] = _json_dump_api(direccion)

            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE clientes SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (cliente_id,),
                )

            row = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()

        return jsonify({"ok": True, "cliente": _normalizar_cliente_api(row)})
    except Exception:
        app.logger.exception("Error al actualizar cliente")
        return jsonify({"ok": False, "error": "No se pudo actualizar el cliente."}), 500


@app.route("/api/notas", methods=["GET"])
def api_notas_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        limit = _api_limite(request.args.get("limit"))
        offset = _api_offset(request.args.get("offset"))
        filtros = []
        valores = []

        cliente = (request.args.get("cliente") or "").strip()
        telefono = (request.args.get("telefono") or "").strip()
        pedido = (request.args.get("pedido") or "").strip()
        estado = (request.args.get("estado") or "").strip()
        fecha_desde = (request.args.get("fecha_desde") or "").strip()
        fecha_hasta = (request.args.get("fecha_hasta") or "").strip()

        if cliente:
            if cliente.isdigit():
                filtros.append("n.cliente_id=%s")
                valores.append(int(cliente))
            else:
                filtros.append("(n.cliente_nombre ILIKE %s OR c.nombre ILIKE %s)")
                valores.extend([f"%{cliente}%", f"%{cliente}%"])
        if telefono:
            filtros.append("c.telefono ILIKE %s")
            valores.append(f"%{telefono}%")
        if pedido:
            filtros.append("CAST(n.pedido AS TEXT) ILIKE %s")
            valores.append(f"%{pedido}%")
        if estado:
            filtros.append("n.estado=%s")
            valores.append(estado)
        if fecha_desde:
            filtros.append("CAST(n.fecha AS TEXT) >= %s")
            valores.append(fecha_desde)
        if fecha_hasta:
            filtros.append("CAST(n.fecha AS TEXT) <= %s")
            valores.append(fecha_hasta)

        where = "WHERE " + " AND ".join(filtros) if filtros else ""
        joins = "LEFT JOIN clientes c ON c.id = n.cliente_id"
        join_subtotal = _join_subtotal_items_nota_api()

        with get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM notas n {joins} {where}",
                tuple(valores),
            ).fetchone()["total"]
            rows = conn.execute(f"""
                SELECT n.*, it.subtotal_productos
                FROM notas n
                {joins}
                {join_subtotal}
                {where}
                ORDER BY n.fecha DESC NULLS LAST, n.id DESC
                LIMIT %s OFFSET %s
            """, tuple(valores) + (limit, offset)).fetchall()

        return jsonify({
            "ok": True,
            "notas": [_normalizar_nota_api(row) for row in rows],
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
        })
    except Exception:
        app.logger.exception("Error al listar notas")
        return jsonify({"ok": False, "error": "No se pudieron consultar las notas."}), 500


@app.route("/api/notas", methods=["POST"])
def api_notas_crear():
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        cliente_id, cliente_nombre = _cliente_payload_nota_api(data)
        items = _items_payload_nota_api(data)
        envio = _json_field(data.get("envio"), {})
        total = _subtotal_items_payload_api(items)
        fecha = data.get("fecha") or datetime.now()
        estado = data.get("estado") or "COTIZACION"
        if estado != "COTIZACION":
            raise PermissionError("Solo se pueden crear cotizaciones en modo API.")

        with get_conn() as conn:
            nota_id = _generar_id_nota_api(conn)
            notas_cols = _columnas_tabla_api(conn, "notas")
            valores = {
                "id": nota_id,
                "cliente_id": cliente_id,
                "cliente_nombre": cliente_nombre,
                "fecha": fecha,
                "estado": "COTIZACION",
                "total": total,
                "envio": _json_dump_api(envio),
                "pedido": data.get("pedido"),
                "paqueteria": data.get("paqueteria") or _paqueteria_envio_api(envio),
                "observaciones": data.get("observaciones"),
                "notas": data.get("notas") or data.get("observaciones"),
            }
            campos = [campo for campo in valores if campo in notas_cols]
            placeholders = ",".join(["%s"] * len(campos))
            conn.execute(
                f"INSERT INTO notas ({','.join(campos)}) VALUES ({placeholders})",
                tuple(valores[campo] for campo in campos),
            )
            _insertar_items_nota_api(conn, nota_id, items)

        nota = _nota_con_detalle_api(nota_id)
        return jsonify({"ok": True, "nota": nota}), 201
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>", methods=["GET"])
def api_notas_obtener(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            nota_id_real, _ = _resolver_nota_api(conn, nota_id)
            row = conn.execute(f"""
                SELECT n.*, it.subtotal_productos
                FROM notas n
                {_join_subtotal_items_nota_api()}
                WHERE n.id=%s
            """, (nota_id_real,)).fetchone()
        nota = _normalizar_nota_api(row)
        if not nota:
            return jsonify({"ok": False, "error": "Nota no encontrada."}), 404
        nota["items"] = _items_nota_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="consultar")


@app.route("/api/notas/<string:nota_id>/detalle-completo", methods=["GET"])
def api_notas_detalle_completo(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        detalle = _detalle_completo_nota_api(nota_id)
        return jsonify({"ok": True, **detalle})
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="consultar detalle de")


@app.route("/api/notas/<string:nota_id>", methods=["PATCH"])
def api_notas_actualizar(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        with get_conn() as conn:
            nota_id_real, _ = _resolver_nota_api(conn, nota_id)
            _validar_no_escritura_restringida_nota_api(conn, nota_id_real, data)
            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}

            if "cliente" in data or "cliente_id" in data or "cliente_nombre" in data:
                cliente_id, cliente_nombre = _cliente_payload_nota_api(data)
                cambios["cliente_id"] = cliente_id
                cambios["cliente_nombre"] = cliente_nombre

            if "total" in data:
                cambios["total"] = _float_api(data.get("total"))

            if "envio" in data:
                envio = _json_field(data.get("envio"), {})
                cambios["envio"] = _json_dump_api(envio)
                cambios["paqueteria"] = data.get("paqueteria") or _paqueteria_envio_api(envio)
            elif "paqueteria" in data:
                cambios["paqueteria"] = data.get("paqueteria")

            if "pedido" in data:
                cambios["pedido"] = data.get("pedido")

            if "observaciones" in data:
                cambios["observaciones"] = data.get("observaciones")
            if "notas" in data:
                cambios["notas"] = data.get("notas")

            cambios = {campo: valor for campo, valor in cambios.items() if campo in notas_cols}
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/admin", methods=["PATCH"])
def api_notas_actualizar_admin(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        campos_bloqueados = {
            "items", "carrito", "total", "subtotal", "subtotal_productos",
            "total_final", "estado", "fecha_pago", "pagos",
        }
        if campos_bloqueados.intersection(data.keys()):
            raise PermissionError(
                "Esta nota pagada requiere ajuste administrativo de items para cambios de productos, cantidades o precios."
            )

        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)

            estado = _normalizar_estado_pago_api(actual.get("estado"))
            if estado in ESTADOS_NOTA_PAGADA_API and not _clave_stock_autorizada_api(data):
                raise NotaPagoNoPermitido(
                    "Esta nota ya esta pagada. Se requiere autorizacion para editar datos administrativos.",
                    409,
                )

            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}

            if "cliente" in data or "cliente_id" in data or "cliente_nombre" in data:
                cliente_id, cliente_nombre = _cliente_payload_nota_api(data)
                cambios["cliente_id"] = cliente_id
                cambios["cliente_nombre"] = cliente_nombre

            if "envio" in data:
                envio = _json_field(data.get("envio"), {})
                cambios["envio"] = _json_dump_api(envio)
                cambios["paqueteria"] = data.get("paqueteria") or _paqueteria_envio_api(envio)
            elif "paqueteria" in data:
                cambios["paqueteria"] = data.get("paqueteria")

            if "observaciones" in data:
                cambios["observaciones"] = data.get("observaciones")
            if "notas" in data:
                cambios["notas"] = data.get("notas")
            if "pedido" in data:
                cambios["pedido"] = data.get("pedido")
            if "comprobante" in data:
                cambios["comprobante"] = data.get("comprobante") or None

            cambios = {campo: valor for campo, valor in cambios.items() if campo in notas_cols}
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/admin-ajustar-items", methods=["POST"])
def api_notas_admin_ajustar_items(nota_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        if not _clave_stock_autorizada_api(data):
            raise NotaPagoNoPermitido("Clave de autorizacion incorrecta.", 403)

        items_nuevos = _items_payload_nota_api(data)
        motivo = str(data.get("motivo") or "Ajuste administrativo de nota pagada").strip()

        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)
            if _normalizar_estado_pago_api(actual.get("estado")) not in ESTADOS_NOTA_PAGADA_API:
                raise NotaPagoNoPermitido("Solo una nota pagada puede usar ajuste administrativo de items.", 409)

            items_originales = _items_actuales_nota_api(conn, nota_id_real, bloquear=True)
            subtotal_anterior = _subtotal_items_payload_api(items_originales)
            subtotal_nuevo = _subtotal_items_payload_api(items_nuevos)

            movimientos, afectados = _ajustar_stock_items_pagados_api(
                conn,
                nota_id_real,
                items_originales,
                items_nuevos,
                auth,
                motivo,
            )

            conn.execute("DELETE FROM items WHERE nota_id=%s", (nota_id_real,))
            _insertar_items_nota_api(conn, nota_id_real, items_nuevos)

            notas_cols = _columnas_tabla_api(conn, "notas")
            envio_actual = _json_field(actual.get("envio"), {})
            envio = _json_field(data.get("envio"), envio_actual) if "envio" in data else envio_actual
            envio_precio = _float_api((envio or {}).get("precio")) if isinstance(envio, dict) else 0.0
            cambios = {
                "total": subtotal_nuevo,
            }
            if "envio" in data:
                cambios["envio"] = _json_dump_api(envio)
                cambios["paqueteria"] = data.get("paqueteria") or _paqueteria_envio_api(envio)
            elif "paqueteria" in data:
                cambios["paqueteria"] = data.get("paqueteria")
            if "observaciones" in data:
                cambios["observaciones"] = data.get("observaciones")
            if "notas" in data:
                cambios["notas"] = data.get("notas")
            if "comprobante" in data:
                cambios["comprobante"] = data.get("comprobante") or None

            cambios = {campo: valor for campo, valor in cambios.items() if campo in notas_cols}
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )

            total_anterior_final = subtotal_anterior + _precio_envio_api(_normalizar_nota_api(actual) or {})
            total_nuevo_final = subtotal_nuevo + envio_precio
            detalle = (
                f"{motivo}. Autorizado por {_usuario_auth_api(auth)}. "
                f"Subtotal anterior ${subtotal_anterior:.2f}; subtotal nuevo ${subtotal_nuevo:.2f}; "
                f"total final anterior ${total_anterior_final:.2f}; total final nuevo ${total_nuevo_final:.2f}."
            )
            if round(total_anterior_final, 2) != round(total_nuevo_final, 2):
                detalle += " Total ajustado administrativamente. Revisar diferencia contra pago registrado."
            _agregar_observacion_nota_api(conn, nota_id_real, detalle)

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({
            "ok": True,
            "nota": nota,
            "movimientos": movimientos,
            "productos_afectados": afectados,
            "subtotal_anterior": round(subtotal_anterior, 2),
            "subtotal_nuevo": round(subtotal_nuevo, 2),
            "total_anterior": round(total_anterior_final, 2),
            "total_nuevo": round(total_nuevo_final, 2),
            "aviso_total_pago": round(total_anterior_final, 2) != round(total_nuevo_final, 2),
        })
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/convertir-a-venta", methods=["POST"])
def api_notas_convertir_a_venta(nota_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        envio = _json_field(data.get("envio"), {})
        if not isinstance(envio, dict) or not envio:
            raise ValueError("Primero completa los datos de envio.")
        if _float_api(envio.get("precio")) < 0:
            raise ValueError("El costo de envio no es valido.")

        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)
            estado = _normalizar_estado_convertible_api(actual.get("estado"))
            if estado not in ESTADOS_COTIZACION_NO_PAGABLE:
                raise NotaPagoNoPermitido("Solo una cotizacion puede convertirse a venta.", 409)

            cliente_id = actual.get("cliente_id")
            cliente_nombre = actual.get("cliente_nombre")
            if "cliente" in data or "cliente_id" in data or "cliente_nombre" in data:
                cliente_id, cliente_nombre = _cliente_payload_nota_api(data)

            cliente = conn.execute("SELECT * FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
            if not cliente:
                raise ValueError("Primero completa los datos del cliente.")
            telefono = str(cliente.get("telefono") or "").strip()
            direccion = _json_field(cliente.get("direccion"), {})
            if not cliente.get("nombre") or not telefono.isdigit() or len(telefono) != 10:
                raise ValueError("Primero completa los datos del cliente.")
            if not _direccion_cliente_completa_api(direccion):
                raise ValueError("Primero completa la direccion de envio del cliente.")

            if data.get("items") or data.get("carrito"):
                items = _items_payload_nota_api(data)
                conn.execute("DELETE FROM items WHERE nota_id=%s", (nota_id_real,))
                _insertar_items_nota_api(conn, nota_id_real, items)
                total = _subtotal_items_payload_api(items)
            else:
                subtotal = conn.execute("""
                    SELECT COALESCE(SUM(COALESCE(cantidad, 0) * COALESCE(precio, 0)), 0) AS total
                    FROM items
                    WHERE nota_id=%s
                """, (nota_id_real,)).fetchone()
                total = _float_api((subtotal or {}).get("total"))

            _, afectados = _items_stock_nota_api(conn, nota_id_real, bloquear=False)
            if afectados and not _clave_stock_autorizada_api(data):
                raise StockAutorizacionRequerida(afectados)
            if afectados:
                _registrar_autorizacion_stock_api(conn, nota_id_real, afectados, "conversion_a_venta", auth)

            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {
                "estado": "VENTA_PENDIENTE",
                "cliente_id": cliente_id,
                "cliente_nombre": cliente_nombre,
                "envio": _json_dump_api(envio),
                "total": total,
                "paqueteria": data.get("paqueteria") or _paqueteria_envio_api(envio),
            }
            cambios = {campo: valor for campo, valor in cambios.items() if campo in notas_cols}
            sets = ", ".join(f"{campo}=%s" for campo in cambios)
            conn.execute(
                f"UPDATE notas SET {sets} WHERE id=%s",
                tuple(cambios.values()) + (nota_id_real,),
            )

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/items", methods=["GET"])
def api_notas_items(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        return jsonify({"ok": True, "items": _items_nota_api(nota_id)})
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="consultar items de")


@app.route("/api/notas/<string:nota_id>/items", methods=["PATCH"])
def api_notas_actualizar_items(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        items = _items_payload_nota_api(data)
        total = _subtotal_items_payload_api(items)
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)
            if _normalizar_estado_pago_api(actual.get("estado")) in ESTADOS_NOTA_PAGADA_API:
                raise PermissionError("Editar items de una nota pagada todavia no esta disponible en modo API.")
            notas_cols = _columnas_tabla_api(conn, "notas")
            conn.execute("DELETE FROM items WHERE nota_id=%s", (nota_id_real,))
            _insertar_items_nota_api(conn, nota_id_real, items)
            if "total" in notas_cols:
                conn.execute("UPDATE notas SET total=%s WHERE id=%s", (total, nota_id_real))

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/pagos", methods=["GET"])
def api_notas_pagos(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        return jsonify({"ok": True, "pagos": _pagos_nota_api(nota_id)})
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="consultar pagos de")


@app.route("/api/notas/<string:nota_id>/pago", methods=["PATCH"])
def api_notas_marcar_pago(nota_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        comprobante = str(data.get("comprobante") or "").strip() or None
        fecha_pago = data.get("fecha_pago") or datetime.now().isoformat(timespec="seconds")
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)
            _validar_nota_pagable_api(conn, actual)
            _descontar_stock_nota_api(
                conn,
                nota_id_real,
                auth,
                autorizacion_stock=_clave_stock_autorizada_api(data),
            )
            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}
            if "estado" in notas_cols:
                cambios["estado"] = "PAGADA"
            if "fecha_pago" in notas_cols:
                cambios["fecha_pago"] = fecha_pago
            if comprobante and "comprobante" in notas_cols:
                cambios["comprobante"] = comprobante
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )
            if comprobante:
                _insertar_pago_api(conn, nota_id_real, comprobante)

        nota = _nota_con_detalle_api(nota_id_real)
        nota["pagos"] = _pagos_nota_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/comprobante", methods=["POST"])
def api_notas_guardar_comprobante(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        comprobante = str(data.get("comprobante") or "").strip()
        if not comprobante:
            raise ValueError("Falta ruta de comprobante.")
        with get_conn() as conn:
            nota_id_real, _ = _resolver_nota_api(conn, nota_id)
            _actualizar_comprobante_nota_api(conn, nota_id_real, comprobante)
        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota, "comprobante": comprobante})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/comprobante", methods=["GET"])
def api_notas_obtener_comprobante(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            nota_id_real, row = _resolver_nota_api(conn, nota_id)
        nota = _normalizar_nota_api(row)
        return jsonify({
            "ok": True,
            "nota_id": nota_id_real,
            "comprobante": nota.get("comprobante"),
        })
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/anular", methods=["POST"])
def api_notas_anular(nota_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id, bloquear=True)

            estado = _normalizar_estado_pago_api(actual.get("estado"))
            if estado in {"ANULADA", "CANCELADA", "ELIMINADA"} or _devolucion_stock_existente_api(conn, nota_id_real):
                raise NotaPagoNoPermitido("Esta nota ya fue anulada o el stock ya fue regresado.", 409)

            productos_devueltos = []
            requiere_devolver_stock = _nota_requiere_devolucion_stock_api(conn, actual)
            if requiere_devolver_stock:
                if not _clave_stock_autorizada_api(data):
                    raise NotaPagoNoPermitido(
                        "Esta nota ya fue pagada. Para anularla y regresar stock se requiere autorizacion.",
                        409,
                    )
                productos_devueltos = _devolver_stock_nota_api(conn, nota_id_real, auth)

            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}
            if "estado" in notas_cols:
                cambios["estado"] = "ANULADA"
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )

            detalle = (
                f"Nota anulada por {_usuario_auth_api(auth)}. "
                f"Stock devuelto: {len(productos_devueltos)} producto(s)."
            )
            _registrar_anulacion_nota_api(conn, nota_id_real, detalle)

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({
            "ok": True,
            "nota": nota,
            "productos_devueltos": productos_devueltos,
            "stock_devuelto": bool(productos_devueltos),
        })
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="anular")


@app.route("/api/pagos", methods=["GET"])
def api_pagos_listar():
    _, error = _require_license_api()
    if error:
        return error
    nota_id = (request.args.get("nota_id") or "").strip()
    if not nota_id:
        return jsonify({"ok": False, "error": "Falta nota_id."}), 400
    try:
        return jsonify({"ok": True, "pagos": _pagos_nota_api(nota_id)})
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="consultar pagos de")


@app.route("/api/pagos", methods=["POST"])
def api_pagos_registrar():
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        nota_id = str(data.get("nota_id") or "").strip()
        comprobante = str(data.get("comprobante") or "").strip() or None
        if not nota_id:
            raise ValueError("Falta nota_id.")
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)
            _validar_nota_pagable_api(conn, actual)
            _descontar_stock_nota_api(
                conn,
                nota_id_real,
                auth,
                autorizacion_stock=_clave_stock_autorizada_api(data),
            )
            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}
            if "estado" in notas_cols:
                cambios["estado"] = "PAGADA"
            if "fecha_pago" in notas_cols:
                cambios["fecha_pago"] = datetime.now().isoformat(timespec="seconds")
            if comprobante and "comprobante" in notas_cols:
                cambios["comprobante"] = comprobante
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )
            pago = _insertar_pago_api(conn, nota_id_real, comprobante)
        return jsonify({"ok": True, "pago": _row_dict(pago) if pago else None})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


def _estado_envio_filtro_api(valor):
    clave = str(valor or "").strip().upper()
    mapa = {
        "COMPLETAS": "COMPLETA",
        "COMPLETA": "COMPLETA",
        "EN_PROCESO": "EN_PROCESO",
        "INCOMPLETAS": "INCOMPLETA",
        "INCOMPLETA": "INCOMPLETA",
        "TODAS_PAGADAS": "PAGADA",
        "PAGADA": "PAGADA",
    }
    return mapa.get(clave, clave if clave else "")


def _normalizar_envio_nota_api(row):
    data = _row_dict(row) or {}
    envio = _json_field(data.get("envio"), {})
    if not isinstance(envio, dict):
        envio = {}
    paqueteria = data.get("paqueteria") or _paqueteria_envio_api(envio)
    costo_envio = data.get("costo_envio")
    if costo_envio is None:
        costo_envio = envio.get("precio")
    return {
        "nota_id": data.get("id"),
        "folio": data.get("id"),
        "id": data.get("id"),
        "cliente": data.get("cliente_nombre") or data.get("cliente") or "",
        "cliente_nombre": data.get("cliente_nombre") or data.get("cliente") or "",
        "telefono": data.get("telefono"),
        "direccion": _json_field(data.get("direccion"), {}) if data.get("direccion") else {},
        "pedido": data.get("pedido"),
        "estado": data.get("estado"),
        "total": data.get("total"),
        "envio": envio,
        "paqueteria": paqueteria,
        "costo_envio": _float_api(costo_envio, default=0.0),
        "guia": data.get("guia"),
        "estado_envio": data.get("estado_envio"),
        "fecha_envio": data.get("fecha_envio"),
        "observaciones_envio": data.get("observaciones_envio"),
        "fecha": data.get("fecha"),
    }


def _select_envios_notas_api(conn):
    notas_cols = _columnas_tabla_api(conn, "notas")
    clientes_cols = _columnas_tabla_api(conn, "clientes")
    if not notas_cols or "id" not in notas_cols:
        raise LookupError("No existe la tabla notas o falta id.")
    selects = [
        "n.id AS id",
        "n.cliente_nombre AS cliente_nombre" if "cliente_nombre" in notas_cols else "NULL AS cliente_nombre",
        "n.pedido AS pedido" if "pedido" in notas_cols else "NULL AS pedido",
        "n.estado AS estado" if "estado" in notas_cols else "NULL AS estado",
        "n.total AS total" if "total" in notas_cols else "NULL AS total",
        "n.envio AS envio" if "envio" in notas_cols else "NULL AS envio",
        "n.paqueteria AS paqueteria" if "paqueteria" in notas_cols else "NULL AS paqueteria",
        "n.guia AS guia" if "guia" in notas_cols else "NULL AS guia",
        "n.fecha AS fecha" if "fecha" in notas_cols else "NULL AS fecha",
        "n.costo_envio AS costo_envio" if "costo_envio" in notas_cols else "NULL AS costo_envio",
        "n.estado_envio AS estado_envio" if "estado_envio" in notas_cols else "NULL AS estado_envio",
        "n.fecha_envio AS fecha_envio" if "fecha_envio" in notas_cols else "NULL AS fecha_envio",
        "n.observaciones_envio AS observaciones_envio" if "observaciones_envio" in notas_cols else "NULL AS observaciones_envio",
        "c.telefono AS telefono" if {"cliente_id"}.issubset(notas_cols) and {"id", "telefono"}.issubset(clientes_cols) else "NULL AS telefono",
        "c.direccion AS direccion" if {"cliente_id"}.issubset(notas_cols) and {"id", "direccion"}.issubset(clientes_cols) else "NULL AS direccion",
    ]
    join = ""
    if "cliente_id" in notas_cols and "id" in clientes_cols:
        join = "LEFT JOIN clientes c ON c.id = n.cliente_id"
    return ", ".join(selects), join, notas_cols


@app.route("/api/envios/notas", methods=["GET"])
def api_envios_notas_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            selects, join, notas_cols = _select_envios_notas_api(conn)
            filtros = []
            valores = []
            estado = _estado_envio_filtro_api(request.args.get("estado"))
            if estado and "estado" in notas_cols:
                filtros.append("n.estado=%s")
                valores.append(estado)
            pedido_id = str(request.args.get("pedido_id") or "").strip()
            if pedido_id and "pedido" in notas_cols:
                filtros.append("CAST(n.pedido AS TEXT)=%s")
                valores.append(pedido_id)
            q = str(request.args.get("q") or "").strip()
            if q:
                partes = ["CAST(n.id AS TEXT) ILIKE %s"]
                valores.append(f"%{q}%")
                if "cliente_nombre" in notas_cols:
                    partes.append("n.cliente_nombre ILIKE %s")
                    valores.append(f"%{q}%")
                if "pedido" in notas_cols:
                    partes.append("CAST(n.pedido AS TEXT) ILIKE %s")
                    valores.append(f"%{q}%")
                if "guia" in notas_cols:
                    partes.append("n.guia ILIKE %s")
                    valores.append(f"%{q}%")
                filtros.append(f"({' OR '.join(partes)})")
            where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""
            limit = _api_limite(request.args.get("limit"), default=200, maximo=500)
            offset = _api_offset(request.args.get("offset"))
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM notas n {join} {where_sql}",
                tuple(valores),
            ).fetchone()
            order_col = "fecha" if "fecha" in notas_cols else "id"
            rows = conn.execute(
                f"""
                SELECT {selects}
                FROM notas n
                {join}
                {where_sql}
                ORDER BY n.{order_col} DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                tuple(valores + [limit, offset]),
            ).fetchall()
        envios = [_normalizar_envio_nota_api(row) for row in rows]
        return jsonify({"ok": True, "envios": envios, "total": int((total or {}).get("total") or 0)})
    except Exception:
        app.logger.exception("Error al consultar notas de envios")
        return jsonify({"ok": False, "error": "No se pudieron consultar los envios."}), 500


@app.route("/api/envios/notas/<string:nota_id>", methods=["PATCH"])
def api_envios_nota_actualizar(nota_id):
    _, error = _require_license_api()
    if error:
        return error
    data = _body_json()
    try:
        with get_conn() as conn:
            nota_id_real, nota = _resolver_nota_api(conn, nota_id, bloquear=True)
            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}
            for campo in ("guia", "paqueteria", "estado_envio", "fecha_envio", "observaciones_envio"):
                if campo in data:
                    if campo not in notas_cols:
                        raise ValueError(f"La tabla notas no tiene columna {campo}.")
                    cambios[campo] = str(data.get(campo) or "").strip() or None

            if "costo_envio" in data:
                if "costo_envio" in notas_cols:
                    cambios["costo_envio"] = _float_api(data.get("costo_envio"))
                elif "envio" in notas_cols:
                    envio = _json_field(nota.get("envio"), {})
                    if not isinstance(envio, dict):
                        envio = {}
                    envio["precio"] = _float_api(data.get("costo_envio"))
                    cambios["envio"] = _json_dump_api(envio)
                else:
                    raise ValueError("La tabla notas no permite guardar costo de envio.")

            if not cambios:
                raise ValueError("No hay cambios de envio para guardar.")
            sets = ", ".join(f"{campo}=%s" for campo in cambios)
            conn.execute(
                f"UPDATE notas SET {sets} WHERE id=%s",
                tuple(cambios.values()) + (nota_id_real,),
            )
            selects, join, _ = _select_envios_notas_api(conn)
            row = conn.execute(
                f"SELECT {selects} FROM notas n {join} WHERE n.id=%s",
                (nota_id_real,),
            ).fetchone()
        return jsonify({"ok": True, "envio": _normalizar_envio_nota_api(row)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al actualizar envio")
        return jsonify({"ok": False, "error": "No se pudo actualizar el envio."}), 500


def _tabla_existe_api(conn, tabla):
    row = conn.execute("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_name=%s
        ) AS existe
    """, (tabla,)).fetchone()
    return bool(row and row.get("existe"))


def _int_reporte_api(valor, default=0):
    try:
        if valor is None or valor == "":
            return default
        return int(float(valor))
    except Exception:
        return default


def _fecha_inicio_reporte_api(args, dias_default=90):
    desde = str(args.get("desde") or "").strip()
    if desde:
        try:
            return datetime.strptime(desde[:10], "%Y-%m-%d")
        except Exception:
            raise ValueError("Fecha desde invalida. Use YYYY-MM-DD.")
    dias = _int_reporte_api(args.get("dias"), dias_default)
    dias = max(1, min(dias, 3650))
    return datetime.now() - timedelta(days=dias)


def _fecha_fin_reporte_api(args):
    hasta = str(args.get("hasta") or "").strip()
    if not hasta:
        return None
    try:
        return datetime.strptime(hasta[:10], "%Y-%m-%d") + timedelta(days=1)
    except Exception:
        raise ValueError("Fecha hasta invalida. Use YYYY-MM-DD.")


def _cantidad_vendida_movimiento_api(row):
    cantidad = row.get("cantidad")
    if cantidad is not None:
        return abs(_int_reporte_api(cantidad))
    anterior = row.get("stock_anterior")
    nuevo = row.get("stock_nuevo")
    if anterior is not None and nuevo is not None:
        return max(0, _int_reporte_api(anterior) - _int_reporte_api(nuevo))
    return 0


def _tipo_no_inventario_sql_api(alias="p"):
    return (
        f"UPPER(COALESCE({alias}.tipo_producto, 'INVENTARIO')) NOT IN "
        "('ITEM','ITEM_COTIZACION','ANULADO','INACTIVO','COTIZACION','PAQUETE','PAQUETES','COMBO','COMBOS','SERVICIO')"
    )


def _producto_inventariable_where_api(cols, alias="p"):
    filtros = []
    if "es_inventariable" in cols:
        filtros.append(f"COALESCE({alias}.es_inventariable, TRUE)=TRUE")
    if "tipo_producto" in cols:
        filtros.append(_tipo_no_inventario_sql_api(alias))
    return " AND ".join(filtros) if filtros else "TRUE"


def _precio_producto_expr_api(cols, alias="p"):
    partes = []
    if "precio_venta" in cols:
        partes.append(f"NULLIF({alias}.precio_venta, 0)")
    if "precio" in cols:
        partes.append(f"NULLIF({alias}.precio, 0)")
    partes.append("0")
    return f"COALESCE({', '.join(partes)})"


def _costo_producto_expr_api(cols, alias="p"):
    partes = []
    if "costo_neto" in cols:
        partes.append(f"NULLIF({alias}.costo_neto, 0)")
    partes.append("0")
    return f"COALESCE({', '.join(partes)})"


@app.route("/api/reportes/dashboard-empacadores", methods=["GET"])
def api_reportes_dashboard_empacadores():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            if not _tabla_existe_api(conn, "empacadores") or not _tabla_existe_api(conn, "notas"):
                return jsonify({"ok": True, "metricas": []})
            emp_cols = _columnas_tabla_api(conn, "empacadores")
            notas_cols = _columnas_tabla_api(conn, "notas")
            err_existe = _tabla_existe_api(conn, "errores_scan")
            filtro_activo = "WHERE e.activo=TRUE" if "activo" in emp_cols else ""
            fecha_final = "n.fecha_finalizacion" if "fecha_finalizacion" in notas_cols else "NULL::timestamp"
            fecha_asig = "n.fecha_asignacion" if "fecha_asignacion" in notas_cols else "NULL::timestamp"
            errores_join = "LEFT JOIN errores_scan err ON err.empacador_id = e.id" if err_existe else ""
            errores_select = "COUNT(err.id) AS errores" if err_existe else "0 AS errores"
            rows = conn.execute(f"""
                SELECT
                    e.id,
                    e.nombre,
                    COUNT(n.id) FILTER (WHERE n.estado IS NOT NULL) AS total_notas,
                    COUNT(n.id) FILTER (WHERE n.estado = 'COMPLETA') AS completas,
                    COUNT(n.id) FILTER (WHERE n.estado = 'INCOMPLETA') AS incompletas,
                    {errores_select},
                    AVG(EXTRACT(EPOCH FROM ({fecha_final} - {fecha_asig}))/60)
                        FILTER (WHERE n.estado = 'COMPLETA' AND {fecha_final} IS NOT NULL AND {fecha_asig} IS NOT NULL)
                        AS tiempo_promedio_min
                FROM empacadores e
                LEFT JOIN notas n ON n.empacador_id = e.id
                {errores_join}
                {filtro_activo}
                GROUP BY e.id, e.nombre
                ORDER BY completas DESC
            """).fetchall()
        return jsonify({"ok": True, "metricas": [_row_dict(row) for row in rows]})
    except Exception:
        app.logger.exception("Error al consultar dashboard de empacadores")
        return jsonify({"ok": False, "error": "No se pudo consultar el dashboard."}), 500


@app.route("/api/reportes/errores-scan", methods=["GET"])
def api_reportes_errores_scan():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            if not _tabla_existe_api(conn, "errores_scan"):
                return jsonify({"ok": True, "errores": []})
            limit = _api_limite(request.args.get("limit"), default=200, maximo=1000)
            rows = conn.execute("""
                SELECT
                    e.fecha,
                    e.nota_id,
                    e.codigo,
                    e.motivo,
                    em.nombre
                FROM errores_scan e
                LEFT JOIN empacadores em ON em.id = e.empacador_id
                ORDER BY e.fecha DESC
                LIMIT %s
            """, (limit,)).fetchall()
        return jsonify({"ok": True, "errores": [_row_dict(row) for row in rows]})
    except Exception:
        app.logger.exception("Error al consultar errores de scan")
        return jsonify({"ok": False, "error": "No se pudieron consultar los errores."}), 500


@app.route("/api/reportes/ranking-empacadores", methods=["GET"])
def api_reportes_ranking_empacadores():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            if not _tabla_existe_api(conn, "empacadores") or not _tabla_existe_api(conn, "notas"):
                return jsonify({"ok": True, "ranking": []})
            limit = _api_limite(request.args.get("limit"), default=3, maximo=100)
            rows = conn.execute("""
                SELECT
                    e.nombre,
                    COUNT(n.id) AS completadas
                FROM empacadores e
                JOIN notas n ON n.empacador_id = e.id
                WHERE n.estado = 'COMPLETA'
                GROUP BY e.nombre
                ORDER BY completadas DESC
                LIMIT %s
            """, (limit,)).fetchall()
        return jsonify({"ok": True, "ranking": [_row_dict(row) for row in rows]})
    except Exception:
        app.logger.exception("Error al consultar ranking de empacadores")
        return jsonify({"ok": False, "error": "No se pudo consultar el ranking."}), 500


@app.route("/api/reportes/dashboard-ventas", methods=["GET"])
def api_reportes_dashboard_ventas():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            if not _tabla_existe_api(conn, "notas"):
                return jsonify({"ok": True, "dashboard": {}})
            notas_cols = _columnas_tabla_api(conn, "notas")
            fecha_col = "fecha" if "fecha" in notas_cols else None
            filtros = []
            valores = []
            desde = _fecha_inicio_reporte_api(request.args, dias_default=30)
            hasta = _fecha_fin_reporte_api(request.args)
            if fecha_col:
                filtros.append(f"n.{fecha_col} >= %s")
                valores.append(desde)
                if hasta:
                    filtros.append(f"n.{fecha_col} < %s")
                    valores.append(hasta)
            where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
            row = conn.execute(f"""
                SELECT
                    COUNT(*) AS total_notas,
                    COALESCE(SUM(COALESCE(total, 0)), 0) AS total_ventas,
                    COALESCE(AVG(NULLIF(total, 0)), 0) AS ticket_promedio,
                    COUNT(*) FILTER (WHERE estado IN ('PAGADA','COMPLETA','ENVIADO','VENTA_PAGADA')) AS ventas_pagadas,
                    COUNT(*) FILTER (WHERE estado NOT IN ('PAGADA','COMPLETA','ENVIADO','VENTA_PAGADA')) AS ventas_pendientes
                FROM notas n
                {where}
            """, tuple(valores)).fetchone()
            productos_vendidos = 0
            if _tabla_existe_api(conn, "items"):
                productos_row = conn.execute(f"""
                    SELECT COALESCE(SUM(COALESCE(i.cantidad, 0)), 0) AS productos_vendidos
                    FROM items i
                    JOIN notas n ON n.id = i.nota_id
                    {where}
                """, tuple(valores)).fetchone()
                productos_vendidos = _int_reporte_api((productos_row or {}).get("productos_vendidos"))
        dashboard = _row_dict(row) or {}
        dashboard["productos_vendidos"] = productos_vendidos
        dashboard["periodo"] = {
            "desde": desde.date().isoformat() if hasattr(desde, "date") else str(desde),
            "hasta": (hasta.date().isoformat() if hasta and hasattr(hasta, "date") else None),
        }
        return jsonify({"ok": True, "dashboard": dashboard})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Error al consultar dashboard de ventas")
        return jsonify({"ok": False, "error": "No se pudo consultar el dashboard de ventas."}), 500


@app.route("/api/reportes/estadisticas-almacen", methods=["GET"])
def api_reportes_estadisticas_almacen():
    _, error = _require_license_api()
    if error:
        return error
    try:
        dias = _int_reporte_api(request.args.get("dias"), 90)
        dias = max(1, min(dias, 3650))
        marca = str(request.args.get("marca") or "").strip().upper()
        fecha_inicio = datetime.now() - timedelta(days=dias)
        fecha_30 = datetime.now() - timedelta(days=30)
        fecha_7 = datetime.now() - timedelta(days=7)

        with get_conn() as conn:
            if not _tabla_existe_api(conn, "productos"):
                return jsonify({"ok": True, "estadisticas": []})
            prod_cols = _columnas_tabla_api(conn, "productos")
            costo_expr = _costo_producto_expr_api(prod_cols)
            venta_expr = _precio_producto_expr_api(prod_cols)
            inventario_where = _producto_inventariable_where_api(prod_cols)
            filtros_prod = [inventario_where]
            valores_prod = []
            if marca and "marca" in prod_cols:
                filtros_prod.append("UPPER(p.marca)=UPPER(%s)")
                valores_prod.append(marca)
            where_prod = " AND ".join(filtros_prod) if filtros_prod else "TRUE"
            order_cols = [f"p.{col}" for col in ("marca", "hilo", "color", "codigo") if col in prod_cols]
            order_sql = f"ORDER BY {', '.join(order_cols)}" if order_cols else ""
            productos = conn.execute(f"""
                SELECT
                    {"p.marca" if "marca" in prod_cols else "NULL"} AS marca,
                    {"p.hilo" if "hilo" in prod_cols else "NULL"} AS hilo,
                    {"p.color" if "color" in prod_cols else "NULL"} AS color,
                    {"p.codigo" if "codigo" in prod_cols else "NULL"} AS codigo,
                    {"COALESCE(p.stock, 0)" if "stock" in prod_cols else "0"} AS stock,
                    {"p.estado" if "estado" in prod_cols else "NULL"} AS estado,
                    {costo_expr} AS costo_unitario,
                    {venta_expr} AS venta_unitaria
                FROM productos p
                WHERE {where_prod}
                {order_sql}
            """, tuple(valores_prod)).fetchall()

            movs = []
            if _tabla_existe_api(conn, "movimientos_almacen"):
                mov_cols = _columnas_tabla_api(conn, "movimientos_almacen")
                if {"marca", "hilo", "color", "codigo", "fecha", "tipo"}.issubset(mov_cols):
                    filtros_mov = ["tipo='SALIDA_STOCK'", "fecha >= %s"]
                    valores_mov = [fecha_inicio]
                    if marca and "marca" in mov_cols:
                        filtros_mov.append("UPPER(marca)=UPPER(%s)")
                        valores_mov.append(marca)
                    cantidad_select = "cantidad" if "cantidad" in mov_cols else "NULL AS cantidad"
                    anterior_select = "stock_anterior" if "stock_anterior" in mov_cols else "NULL AS stock_anterior"
                    nuevo_select = "stock_nuevo" if "stock_nuevo" in mov_cols else "NULL AS stock_nuevo"
                    movs = conn.execute(f"""
                        SELECT marca, hilo, color, codigo, fecha,
                               {cantidad_select}, {anterior_select}, {nuevo_select}
                        FROM movimientos_almacen
                        WHERE {' AND '.join(filtros_mov)}
                    """, tuple(valores_mov)).fetchall()

        ventas = {}
        for mov in movs:
            key = (
                str(mov.get("marca") or "").upper().strip(),
                str(mov.get("hilo") or "").upper().strip(),
                str(mov.get("color") or "").upper().strip(),
                str(mov.get("codigo") or "").upper().strip(),
            )
            ventas.setdefault(key, {"vendidos_periodo": 0, "vendidos_30": 0, "vendidos_7": 0})
            cantidad = _cantidad_vendida_movimiento_api(mov)
            fecha = mov.get("fecha")
            ventas[key]["vendidos_periodo"] += cantidad
            if fecha and fecha >= fecha_30:
                ventas[key]["vendidos_30"] += cantidad
            if fecha and fecha >= fecha_7:
                ventas[key]["vendidos_7"] += cantidad

        filas = []
        for producto in productos:
            data = _row_dict(producto) or {}
            key = (
                str(data.get("marca") or "").upper().strip(),
                str(data.get("hilo") or "").upper().strip(),
                str(data.get("color") or "").upper().strip(),
                str(data.get("codigo") or "").upper().strip(),
            )
            venta = ventas.get(key, {"vendidos_periodo": 0, "vendidos_30": 0, "vendidos_7": 0})
            stock = _int_reporte_api(data.get("stock"))
            costo_unitario = _float_api(data.get("costo_unitario"))
            venta_unitaria = _float_api(data.get("venta_unitaria"))
            valor_costo = stock * costo_unitario
            valor_venta = stock * venta_unitaria
            promedio_periodo = venta["vendidos_periodo"] / dias
            promedio_30 = venta["vendidos_30"] / 30
            promedio_7 = venta["vendidos_7"] / 7
            constante = max(promedio_periodo, promedio_30, promedio_7)
            filas.append({
                "marca": data.get("marca") or "",
                "hilo": data.get("hilo") or "",
                "color": data.get("color") or "",
                "codigo": data.get("codigo") or "",
                "stock": stock,
                "estado": data.get("estado") or "",
                "costo_unitario": costo_unitario,
                "venta_unitaria": venta_unitaria,
                "ganancia_unitaria": venta_unitaria - costo_unitario,
                "valor_costo": valor_costo,
                "valor_venta": valor_venta,
                "ganancia_inventario": valor_venta - valor_costo,
                "vendidos_periodo": venta["vendidos_periodo"],
                "vendidos_30": venta["vendidos_30"],
                "vendidos_7": venta["vendidos_7"],
                "promedio_periodo": promedio_periodo,
                "promedio_30": promedio_30,
                "promedio_7": promedio_7,
                "constante_venta": constante,
                "dias_cobertura": (stock / constante) if constante > 0 else None,
            })
        return jsonify({"ok": True, "estadisticas": filas, "total": len(filas)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Error al consultar estadisticas de almacen")
        return jsonify({"ok": False, "error": "No se pudieron consultar las estadisticas de almacen."}), 500


def _require_super_admin():
    auth = _auth_sistema(request)
    if not auth or auth.get("rol") != "super_admin":
        return None
    return auth


@app.route("/api/admin/clientes", methods=["GET", "POST"])
def api_admin_clientes():
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    if request.method == "GET":
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT id, nombre_negocio, contacto, telefono, email, estado,
                       fecha_vencimiento, max_dispositivos, puede_actualizar, plan,
                       notas_admin, created_at, updated_at
                FROM clientes_sistema
                ORDER BY id DESC
            """).fetchall()
        return jsonify(rows)

    data = _body_json()
    with get_conn() as conn:
        row = conn.execute("""
            INSERT INTO clientes_sistema (
                nombre_negocio, contacto, telefono, email, estado,
                fecha_vencimiento, max_dispositivos, puede_actualizar, plan, notas_admin
            )
            VALUES (%s,%s,%s,%s,COALESCE(%s,'activo'),%s,COALESCE(%s,1),COALESCE(%s,FALSE),%s,%s)
            RETURNING id
        """, (
            data.get("nombre_negocio"),
            data.get("contacto"),
            data.get("telefono"),
            data.get("email"),
            data.get("estado"),
            data.get("fecha_vencimiento"),
            data.get("max_dispositivos"),
            data.get("puede_actualizar"),
            data.get("plan"),
            data.get("notas_admin"),
        )).fetchone()
    return jsonify({"ok": True, "id": row["id"]})


@app.route("/api/admin/clientes/<int:cliente_id>", methods=["PATCH"])
def api_admin_cliente_patch(cliente_id):
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    data = _body_json()
    campos = [
        "nombre_negocio", "contacto", "telefono", "email", "estado",
        "fecha_vencimiento", "max_dispositivos", "puede_actualizar", "plan", "notas_admin",
    ]
    sets = []
    params = []
    for campo in campos:
        if campo in data:
            sets.append(f"{campo}=%s")
            params.append(data[campo])
    if not sets:
        return jsonify({"ok": True})
    params.append(cliente_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE clientes_sistema SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s", tuple(params))
    return jsonify({"ok": True})


ROLES_USUARIO_CLIENTE = {"admin_cliente", "vendedor", "almacen", "solo_lectura"}


def _usuario_admin_payload(data):
    nombre = (data.get("nombre") or "").strip()
    usuario = (data.get("username") or data.get("usuario") or "").strip()
    password = data.get("password_temporal") or data.get("password") or ""
    rol = (data.get("rol") or "vendedor").strip()
    activo = bool(data.get("activo", True))

    if not nombre:
        raise ValueError("El nombre es obligatorio.")
    if not usuario:
        raise ValueError("El usuario es obligatorio.")
    if not password or len(password) < 6:
        raise ValueError("La contrasena temporal debe tener al menos 6 caracteres.")
    if rol not in ROLES_USUARIO_CLIENTE:
        raise ValueError("Rol no permitido para cliente.")

    return nombre, usuario, password, rol, activo


@app.route("/api/admin/clientes/<int:cliente_id>/usuarios", methods=["GET", "POST"])
def api_admin_usuarios_cliente(cliente_id):
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    if request.method == "GET":
        with get_conn() as conn:
            cliente = conn.execute("SELECT id FROM clientes_sistema WHERE id=%s", (cliente_id,)).fetchone()
            if not cliente:
                return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404
            rows = conn.execute("""
                SELECT id, cliente_id, nombre, usuario, rol, activo,
                       ultimo_login, created_at, updated_at
                FROM usuarios_sistema
                WHERE cliente_id=%s
                ORDER BY id DESC
            """, (cliente_id,)).fetchall()
        return jsonify({"ok": True, "usuarios": rows})

    data = _body_json()
    try:
        nombre, usuario, password, rol, activo = _usuario_admin_payload(data)
        password_hash = _hash_password_sistema(password)
        with get_conn() as conn:
            cliente = conn.execute("SELECT id FROM clientes_sistema WHERE id=%s", (cliente_id,)).fetchone()
            if not cliente:
                return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404
            existe = conn.execute("SELECT id FROM usuarios_sistema WHERE usuario=%s", (usuario,)).fetchone()
            if existe:
                return jsonify({"ok": False, "error": "Ese usuario ya existe."}), 409
            row = conn.execute("""
                INSERT INTO usuarios_sistema (
                    cliente_id, nombre, usuario, password_hash, rol, activo
                )
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id, cliente_id, nombre, usuario, rol, activo,
                          ultimo_login, created_at, updated_at
            """, (cliente_id, nombre, usuario, password_hash, rol, activo)).fetchone()
            _registrar_evento_licencia(
                conn,
                cliente_id,
                auth["usuario_id"],
                auth.get("device_id_hash"),
                "CREAR_USUARIO_CLIENTE",
                f"usuario_id={row['id']} usuario={usuario} rol={rol}",
            )
        return jsonify({"ok": True, "usuario": row, "mensaje": "Usuario creado correctamente."})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Error al crear usuario de cliente")
        return jsonify({"ok": False, "error": "No se pudo crear el usuario."}), 500


@app.route("/api/admin/usuarios/<int:usuario_id>/reset-password", methods=["POST"])
def api_admin_usuario_reset_password(usuario_id):
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    data = _body_json()
    password = data.get("nueva_password_temporal") or data.get("password_temporal") or data.get("password") or ""
    if not password or len(password) < 6:
        return jsonify({"ok": False, "error": "La nueva contrasena temporal debe tener al menos 6 caracteres."}), 400

    try:
        password_hash = _hash_password_sistema(password)
        with get_conn() as conn:
            row = conn.execute("""
                SELECT id, cliente_id, usuario, rol
                FROM usuarios_sistema
                WHERE id=%s
            """, (usuario_id,)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404
            if row["rol"] == "super_admin":
                return jsonify({"ok": False, "error": "No se puede resetear un super_admin desde este panel."}), 403
            conn.execute("""
                UPDATE usuarios_sistema
                SET password_hash=%s, updated_at=NOW()
                WHERE id=%s
            """, (password_hash, usuario_id))
            conn.execute("""
                UPDATE sesiones_activas
                SET estado='cerrada', updated_at=NOW()
                WHERE usuario_id=%s AND estado='activa'
            """, (usuario_id,))
            _registrar_evento_licencia(
                conn,
                row["cliente_id"],
                auth["usuario_id"],
                auth.get("device_id_hash"),
                "RESET_PASSWORD_USUARIO",
                f"usuario_id={usuario_id} usuario={row['usuario']}",
            )
        return jsonify({"ok": True, "mensaje": "Contrasena restablecida."})
    except Exception:
        app.logger.exception("Error al restablecer password de usuario")
        return jsonify({"ok": False, "error": "No se pudo restablecer la contrasena."}), 500


def _admin_set_activo_usuario(usuario_id, activo):
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    with get_conn() as conn:
        row = conn.execute("""
            SELECT id, cliente_id, usuario, rol
            FROM usuarios_sistema
            WHERE id=%s
        """, (usuario_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Usuario no encontrado."}), 404
        if row["rol"] == "super_admin":
            return jsonify({"ok": False, "error": "No se puede cambiar un super_admin desde este panel."}), 403
        conn.execute("UPDATE usuarios_sistema SET activo=%s, updated_at=NOW() WHERE id=%s", (activo, usuario_id))
        if not activo:
            conn.execute("""
                UPDATE sesiones_activas
                SET estado='cerrada', updated_at=NOW()
                WHERE usuario_id=%s AND estado='activa'
            """, (usuario_id,))
        _registrar_evento_licencia(
            conn,
            row["cliente_id"],
            auth["usuario_id"],
            auth.get("device_id_hash"),
            "ACTIVAR_USUARIO_CLIENTE" if activo else "DESACTIVAR_USUARIO_CLIENTE",
            f"usuario_id={usuario_id} usuario={row['usuario']}",
        )
    return jsonify({"ok": True, "activo": bool(activo)})


@app.route("/api/admin/usuarios/<int:usuario_id>/activar", methods=["POST"])
def api_admin_usuario_activar(usuario_id):
    return _admin_set_activo_usuario(usuario_id, True)


@app.route("/api/admin/usuarios/<int:usuario_id>/desactivar", methods=["POST"])
def api_admin_usuario_desactivar(usuario_id):
    return _admin_set_activo_usuario(usuario_id, False)


def _admin_set_estado_cliente(cliente_id, estado):
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    with get_conn() as conn:
        conn.execute("UPDATE clientes_sistema SET estado=%s, updated_at=NOW() WHERE id=%s", (estado, cliente_id))
        if estado != "activo":
            conn.execute("""
                UPDATE sesiones_activas
                SET estado='bloqueada', updated_at=NOW()
                WHERE cliente_id=%s AND estado='activa'
            """, (cliente_id,))
    return jsonify({"ok": True, "estado": estado})


@app.route("/api/admin/clientes/<int:cliente_id>/suspender", methods=["POST"])
def api_admin_cliente_suspender(cliente_id):
    return _admin_set_estado_cliente(cliente_id, "suspendido")


@app.route("/api/admin/clientes/<int:cliente_id>/bloquear", methods=["POST"])
def api_admin_cliente_bloquear(cliente_id):
    return _admin_set_estado_cliente(cliente_id, "bloqueado")


@app.route("/api/admin/clientes/<int:cliente_id>/reactivar", methods=["POST"])
def api_admin_cliente_reactivar(cliente_id):
    return _admin_set_estado_cliente(cliente_id, "activo")


@app.route("/api/admin/sesiones-activas", methods=["GET"])
def api_admin_sesiones_activas():
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.id, c.nombre_negocio, u.usuario, u.nombre, s.modulo_actual,
                   s.app_version, s.ip, s.ultimo_heartbeat, s.estado
            FROM sesiones_activas s
            JOIN clientes_sistema c ON c.id=s.cliente_id
            JOIN usuarios_sistema u ON u.id=s.usuario_id
            WHERE s.estado='activa'
            ORDER BY s.ultimo_heartbeat DESC
        """).fetchall()
    return jsonify(rows)


@app.route("/api/admin/auditoria", methods=["GET"])
def api_admin_auditoria():
    auth = _require_super_admin()
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT e.id, c.nombre_negocio, u.usuario, e.device_id_hash,
                   e.evento, e.detalle, e.ip, e.created_at
            FROM licencias_eventos e
            LEFT JOIN clientes_sistema c ON c.id=e.cliente_id
            LEFT JOIN usuarios_sistema u ON u.id=e.usuario_id
            ORDER BY e.created_at DESC
            LIMIT 200
        """).fetchall()
    return jsonify(rows)


def _pedido_payload_numero(data):
    numero = (
        data.get("numero")
        or data.get("pedido_id")
        or data.get("pedido")
        or data.get("nombre")
    )
    numero = str(numero or "").strip()
    if not numero:
        raise ValueError("Falta numero de pedido.")
    return numero


def _pedido_fecha_api(valor):
    if valor in (None, ""):
        return None
    if hasattr(valor, "isoformat"):
        return valor
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except Exception:
            pass
    raise ValueError("Fecha de pedido invalida. Use DD/MM/AAAA o YYYY-MM-DD.")


def _pedido_select_sql(cols):
    if "numero" not in cols:
        raise ValueError("La tabla pedidos no tiene columna numero.")
    campos = [
        "numero AS numero",
        "desde AS desde" if "desde" in cols else "NULL AS desde",
        "hasta AS hasta" if "hasta" in cols else "NULL AS hasta",
        "activo AS activo" if "activo" in cols else "FALSE AS activo",
    ]
    if "nombre" in cols:
        campos.append("nombre AS nombre")
    return ", ".join(campos)


def _normalizar_pedido_api(row):
    data = _row_dict(row)
    if not data:
        return None
    data["activo"] = bool(data.get("activo"))
    data["fecha_inicio"] = data.get("desde")
    data["fecha_fin"] = data.get("hasta")
    return data


def _obtener_pedido_api(conn, numero):
    cols = _columnas_tabla_api(conn, "pedidos")
    if not cols:
        raise LookupError("No existe la tabla pedidos.")
    row = conn.execute(
        f"SELECT {_pedido_select_sql(cols)} FROM pedidos WHERE CAST(numero AS TEXT)=%s LIMIT 1",
        (str(numero),),
    ).fetchone()
    return _normalizar_pedido_api(row)


def _crear_pedido_api(conn, data):
    cols = _columnas_tabla_api(conn, "pedidos")
    if not cols:
        raise LookupError("No existe la tabla pedidos.")
    if "numero" not in cols:
        raise ValueError("La tabla pedidos no tiene columna numero.")

    numero = _pedido_payload_numero(data)
    existente = conn.execute(
        "SELECT numero FROM pedidos WHERE CAST(numero AS TEXT)=%s LIMIT 1",
        (numero,),
    ).fetchone()
    if existente:
        raise KeyError("Pedido duplicado")

    valores = {"numero": numero}
    if "desde" in cols:
        valores["desde"] = _pedido_fecha_api(data.get("desde") or data.get("fecha_inicio"))
    if "hasta" in cols:
        valores["hasta"] = _pedido_fecha_api(data.get("hasta") or data.get("fecha_fin"))
    if "activo" in cols:
        valores["activo"] = bool(data.get("activo", False))
    if "nombre" in cols and data.get("nombre"):
        valores["nombre"] = str(data.get("nombre")).strip()

    campos = list(valores)
    placeholders = ",".join(["%s"] * len(campos))
    conn.execute(
        f"INSERT INTO pedidos({','.join(campos)}) VALUES ({placeholders})",
        tuple(valores[campo] for campo in campos),
    )
    return _obtener_pedido_api(conn, numero)


def _activar_pedido_api(conn, numero):
    cols = _columnas_tabla_api(conn, "pedidos")
    if not cols:
        raise LookupError("No existe la tabla pedidos.")
    pedido = _obtener_pedido_api(conn, numero)
    if not pedido:
        raise LookupError("Pedido no encontrado.")

    if "activo" in cols:
        conn.execute("UPDATE pedidos SET activo=FALSE")
        conn.execute("UPDATE pedidos SET activo=TRUE WHERE CAST(numero AS TEXT)=%s", (str(numero),))
        return _obtener_pedido_api(conn, numero)

    estado_cols = _columnas_tabla_api(conn, "pedido_estado")
    if estado_cols and "numero" in estado_cols:
        conn.execute("DELETE FROM pedido_estado")
        valores = {"numero": numero}
        if "id" in estado_cols:
            valores["id"] = 1
        if "desde" in estado_cols:
            valores["desde"] = pedido.get("desde")
        if "hasta" in estado_cols:
            valores["hasta"] = pedido.get("hasta")
        campos = list(valores)
        placeholders = ",".join(["%s"] * len(campos))
        conn.execute(
            f"INSERT INTO pedido_estado({','.join(campos)}) VALUES ({placeholders})",
            tuple(valores[campo] for campo in campos),
        )
        pedido["activo"] = True
        return pedido

    raise ValueError("No hay columna activo ni tabla pedido_estado para guardar pedido activo.")


@app.route("/api/pedidos", methods=["GET"])
def api_pedidos_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            cols = _columnas_tabla_api(conn, "pedidos")
            if not cols:
                return jsonify({"ok": True, "pedidos": [], "total": 0})
            q = str(request.args.get("q") or "").strip()
            limit = _api_limite(request.args.get("limit"), default=100, maximo=500)
            offset = _api_offset(request.args.get("offset"))
            where = []
            valores = []
            if q:
                where.append("CAST(numero AS TEXT) ILIKE %s")
                valores.append(f"%{q}%")
            estado = str(request.args.get("estado") or "").strip().lower()
            if estado == "activo" and "activo" in cols:
                where.append("activo=TRUE")
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            order_col = "desde" if "desde" in cols else "numero"
            total = conn.execute(
                f"SELECT COUNT(*) AS total FROM pedidos {where_sql}",
                tuple(valores),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT {_pedido_select_sql(cols)}
                FROM pedidos
                {where_sql}
                ORDER BY {order_col} DESC NULLS LAST, numero DESC
                LIMIT %s OFFSET %s
                """,
                tuple(valores + [limit, offset]),
            ).fetchall()
        pedidos = [_normalizar_pedido_api(row) for row in rows]
        return jsonify({"ok": True, "pedidos": pedidos, "total": int((total or {}).get("total") or 0)})
    except Exception:
        app.logger.exception("Error al consultar pedidos")
        return jsonify({"ok": False, "error": "No se pudieron consultar los pedidos."}), 500


@app.route("/api/pedidos", methods=["POST"])
def api_pedidos_crear():
    _, error = _require_license_api()
    if error:
        return error
    data = _body_json()
    try:
        with get_conn() as conn:
            pedido = _crear_pedido_api(conn, data)
        return jsonify({"ok": True, "pedido": pedido}), 201
    except KeyError:
        return jsonify({"ok": False, "error": "Pedido duplicado"}), 409
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al crear pedido")
        return jsonify({"ok": False, "error": "No se pudo crear el pedido."}), 500


@app.route("/api/pedidos/activo", methods=["GET"])
def api_pedidos_activo():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            cols = _columnas_tabla_api(conn, "pedidos")
            pedido = None
            if cols and "activo" in cols:
                row = conn.execute(
                    f"SELECT {_pedido_select_sql(cols)} FROM pedidos WHERE activo=TRUE LIMIT 1"
                ).fetchone()
                pedido = _normalizar_pedido_api(row)
            if not pedido:
                estado_cols = _columnas_tabla_api(conn, "pedido_estado")
                if estado_cols and "numero" in estado_cols:
                    row = conn.execute(
                        "SELECT numero, desde, hasta FROM pedido_estado LIMIT 1"
                    ).fetchone()
                    if row:
                        pedido = _normalizar_pedido_api(row)
                        pedido["activo"] = True
        return jsonify({"ok": True, "pedido": pedido})
    except Exception:
        app.logger.exception("Error al consultar pedido activo")
        return jsonify({"ok": False, "error": "No se pudo consultar el pedido activo."}), 500


@app.route("/api/pedidos/activo", methods=["POST", "PATCH"])
def api_pedidos_activar():
    _, error = _require_license_api()
    if error:
        return error
    data = _body_json()
    try:
        numero = _pedido_payload_numero(data)
        with get_conn() as conn:
            pedido = _activar_pedido_api(conn, numero)
        return jsonify({"ok": True, "pedido": pedido})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al activar pedido")
        return jsonify({"ok": False, "error": "No se pudo activar el pedido."}), 500


@app.route("/api/pedidos/activo", methods=["DELETE"])
def api_pedidos_limpiar_activo():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            cols = _columnas_tabla_api(conn, "pedidos")
            if cols and "activo" in cols:
                conn.execute("UPDATE pedidos SET activo=FALSE")
            estado_cols = _columnas_tabla_api(conn, "pedido_estado")
            if estado_cols:
                conn.execute("DELETE FROM pedido_estado")
        return jsonify({"ok": True})
    except Exception:
        app.logger.exception("Error al limpiar pedido activo")
        return jsonify({"ok": False, "error": "No se pudo limpiar el pedido activo."}), 500


@app.route("/api/empacadores", methods=["GET"])
def api_empacadores_listar():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            cols = _columnas_tabla_api(conn, "empacadores")
            if not cols:
                return jsonify({"ok": True, "empacadores": [], "total": 0})
            campos = [
                "id AS id" if "id" in cols else "NULL AS id",
                "nombre AS nombre" if "nombre" in cols else "'' AS nombre",
                "usuario AS usuario" if "usuario" in cols else "NULL AS usuario",
                "rol AS rol" if "rol" in cols else "NULL AS rol",
                "activo AS activo" if "activo" in cols else "TRUE AS activo",
            ]
            solo_activos = str(request.args.get("activo", "true")).strip().lower() not in {"0", "false", "no"}
            where = "WHERE activo=TRUE" if solo_activos and "activo" in cols else ""
            rows = conn.execute(
                f"SELECT {', '.join(campos)} FROM empacadores {where} ORDER BY nombre"
            ).fetchall()
        empacadores = [_row_dict(row) for row in rows]
        return jsonify({"ok": True, "empacadores": empacadores, "total": len(empacadores)})
    except Exception:
        app.logger.exception("Error al consultar empacadores")
        return jsonify({"ok": False, "error": "No se pudieron consultar los empacadores."}), 500


def _notas_asignacion_empacador_api(conn):
    notas_cols = _columnas_tabla_api(conn, "notas")
    if not notas_cols or "id" not in notas_cols:
        raise LookupError("No existe la tabla notas o falta id.")
    emp_cols = _columnas_tabla_api(conn, "empacadores")
    cli_cols = _columnas_tabla_api(conn, "clientes")
    items_cols = _columnas_tabla_api(conn, "items")

    selects = [
        "n.id AS id",
        "n.cliente_nombre AS cliente_nombre" if "cliente_nombre" in notas_cols else "'' AS cliente_nombre",
        "n.pedido AS pedido" if "pedido" in notas_cols else "NULL AS pedido",
        "n.fecha AS fecha" if "fecha" in notas_cols else "NULL AS fecha",
        "n.fecha_asignacion AS fecha_asignacion" if "fecha_asignacion" in notas_cols else "NULL AS fecha_asignacion",
        "n.estado AS estado" if "estado" in notas_cols else "NULL AS estado",
        "e.nombre AS empacador_actual" if {"empacador_id"}.issubset(notas_cols) and {"id", "nombre"}.issubset(emp_cols) else "NULL AS empacador_actual",
        "c.telefono AS telefono" if {"cliente_id"}.issubset(notas_cols) and {"id", "telefono"}.issubset(cli_cols) else "NULL AS telefono",
        "COALESCE(it.empacadas, 0) AS empacadas",
        "COALESCE(it.requeridas, 0) AS requeridas",
    ]
    joins = []
    if {"empacador_id"}.issubset(notas_cols) and {"id", "nombre"}.issubset(emp_cols):
        joins.append("LEFT JOIN empacadores e ON e.id = n.empacador_id")
    if {"cliente_id"}.issubset(notas_cols) and {"id", "telefono"}.issubset(cli_cols):
        joins.append("LEFT JOIN clientes c ON c.id = n.cliente_id")
    if {"nota_id", "cantidad"}.issubset(items_cols):
        empacadas_expr = "COALESCE(empacadas, 0)" if "empacadas" in items_cols else "0"
        joins.append(f"""
            LEFT JOIN (
                SELECT
                    nota_id,
                    COALESCE(SUM({empacadas_expr}), 0) AS empacadas,
                    COALESCE(SUM(COALESCE(cantidad, 0)), 0) AS requeridas
                FROM items
                GROUP BY nota_id
            ) it ON it.nota_id = n.id
        """)
    else:
        joins.append("LEFT JOIN (SELECT NULL::text AS nota_id, 0 AS empacadas, 0 AS requeridas) it ON FALSE")

    where = []
    if "estado" in notas_cols:
        if "fecha_asignacion" in notas_cols:
            where.append("""
                n.estado != 'ARCHIVADA'
                AND (
                    n.estado NOT IN ('COMPLETA')
                    OR n.fecha_asignacion >= NOW() - INTERVAL '24 HOURS'
                )
            """)
        else:
            where.append("n.estado != 'ARCHIVADA'")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = "ORDER BY n.fecha_asignacion DESC NULLS LAST, n.id DESC" if "fecha_asignacion" in notas_cols else "ORDER BY n.id DESC"
    return conn.execute(
        f"""
        SELECT {', '.join(selects)}
        FROM notas n
        {' '.join(joins)}
        {where_sql}
        {order_sql}
        """
    ).fetchall()


@app.route("/api/notas/asignacion-empacador", methods=["GET"])
def api_notas_asignacion_empacador():
    _, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            rows = _notas_asignacion_empacador_api(conn)
        notas = [_row_dict(row) for row in rows]
        return jsonify({"ok": True, "notas": notas, "total": len(notas)})
    except Exception:
        app.logger.exception("Error al consultar notas para asignacion")
        return jsonify({"ok": False, "error": "No se pudieron consultar las notas para asignacion."}), 500


def _nota_ids_payload_api(data):
    ids = data.get("nota_ids")
    if ids is None:
        ids = [data.get("nota_id")]
    if not isinstance(ids, list):
        ids = [ids]
    ids = [str(x).strip() for x in ids if str(x or "").strip()]
    if not ids:
        raise ValueError("Seleccione al menos una nota.")
    return ids


@app.route("/api/notas/asignar-empacador", methods=["POST"])
def api_notas_asignar_empacador():
    auth, error = _require_license_api()
    if error:
        return error
    data = _body_json()
    try:
        nota_ids = _nota_ids_payload_api(data)
        empacador_id = int(data.get("empacador_id") or 0)
        if empacador_id <= 0:
            raise ValueError("Empacador invalido.")
        with get_conn() as conn:
            notas_cols = _columnas_tabla_api(conn, "notas")
            if "empacador_id" not in notas_cols:
                raise ValueError("La tabla notas no permite asignar empacador.")
            emp_cols = _columnas_tabla_api(conn, "empacadores")
            if "id" not in emp_cols:
                raise ValueError("La tabla empacadores no tiene id.")
            filtro_activo = " AND activo=TRUE" if "activo" in emp_cols else ""
            emp = conn.execute(
                f"SELECT id FROM empacadores WHERE id=%s{filtro_activo} LIMIT 1",
                (empacador_id,),
            ).fetchone()
            if not emp:
                raise LookupError("Empacador no encontrado o inactivo.")
            campos = ["empacador_id=%s"]
            valores_base = [empacador_id]
            if "fecha_asignacion" in notas_cols:
                campos.append("fecha_asignacion=NOW()")
            if "estado" in notas_cols:
                campos.append("estado='EN_PROCESO'")
            if "fecha_finalizacion" in notas_cols:
                campos.append("fecha_finalizacion=NULL")
            for nota_id in nota_ids:
                conn.execute(
                    f"UPDATE notas SET {', '.join(campos)} WHERE id=%s",
                    tuple(valores_base + [nota_id]),
                )
        return jsonify({"ok": True, "asignadas": len(nota_ids), "usuario": _usuario_auth_api(auth)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al asignar empacador")
        return jsonify({"ok": False, "error": "No se pudo asignar empacador."}), 500


@app.route("/api/notas/desasignar-empacador", methods=["POST"])
def api_notas_desasignar_empacador():
    _, error = _require_license_api()
    if error:
        return error
    data = _body_json()
    try:
        nota_ids = _nota_ids_payload_api(data)
        with get_conn() as conn:
            notas_cols = _columnas_tabla_api(conn, "notas")
            if "empacador_id" not in notas_cols:
                raise ValueError("La tabla notas no permite desasignar empacador.")
            for nota_id in nota_ids:
                conn.execute("UPDATE notas SET empacador_id=NULL WHERE id=%s", (nota_id,))
        return jsonify({"ok": True, "desasignadas": len(nota_ids)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Error al desasignar empacador")
        return jsonify({"ok": False, "error": "No se pudo desasignar empacador."}), 500


# =========================
# NOTAS PAGADAS (EMPACADOR)
# =========================
@app.route("/notas-pagadas", methods=["GET"])
def notas_pagadas():

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    with get_conn() as conn:

        notas = conn.execute("""
            SELECT id, cliente_nombre, estado, paqueteria
            FROM notas
            WHERE empacador_id=%s
            AND estado != 'ARCHIVADA'
            AND (
                estado IN ('PAGADA','EN_PROCESO','INCOMPLETA','ENVIADO')
                OR
                (
                    estado='COMPLETA'
                    AND fecha_finalizacion > NOW() - INTERVAL '24 hours'
                )
            )
            ORDER BY fecha_asignacion DESC
        """,(auth["empacador_id"],)).fetchall()

        resultado = []

        for n in notas:
            productos = conn.execute("""
                SELECT id, hilo, color, codigo,
                       cantidad as pz_requeridas,
                       empacadas as pz_empacadas
                FROM items
                WHERE nota_id=%s
            """,(n["id"],)).fetchall()

            resultado.append({
                "id": n["id"],
                "cliente": n["cliente_nombre"],
                "estado": n["estado"],
                "paqueteria": n["paqueteria"] or "",
                "productos": productos
            })

    print("Notas enviadas:", resultado)
    return jsonify(resultado)




@app.route("/asignar-nota", methods=["POST"])
def asignar_nota():

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    # 🔒 Solo admin puede asignar
    if auth["rol"] != "ADMIN":
        return jsonify({"error": "Solo admin puede asignar"}), 403

    data = request.json
    nota_id = data["nota_id"]
    empacador_id = data["empacador_id"]

    with get_conn() as conn:
        conn.execute("""
            UPDATE notas
            SET empacador_id=%s,
                fecha_asignacion=NOW(),
                estado='EN_PROCESO',
                fecha_finalizacion=NULL
            WHERE id=%s
        """,(empacador_id, nota_id))


    return jsonify({"ok": True})


# =========================
# CAMBIAR ESTADO DE NOTA
# =========================
@app.route("/notas/<nota_id>/estado", methods=["POST"])
def cambiar_estado(nota_id):
    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    nuevo_estado = request.json.get("estado")

    ESTADOS_VALIDOS = [
    "PAGADA",
    "EN_PROCESO",
    "INCOMPLETA",
    "COMPLETA",
    "ENVIADO",
    "ARCHIVADA"
    ]

    if nuevo_estado not in ESTADOS_VALIDOS:
        return jsonify({"error": "Estado inválido"}), 400

    with get_conn() as conn:

        nota = conn.execute("""
            SELECT estado, empacador_id
            FROM notas
            WHERE id=%s
            AND estado!='ARCHIVADA'
        """,(nota_id,)).fetchone()

        if not nota:
            return jsonify({"error": "Nota no encontrada"}), 404

        if nota["empacador_id"] != auth["empacador_id"] and auth["rol"] != "ADMIN":
            return jsonify({"error": "No es tu nota"}), 403

        estado_actual = nota["estado"]

        transicion_valida = False

        if estado_actual == "PAGADA" and nuevo_estado == "EN_PROCESO":
            transicion_valida = True

        elif estado_actual == "EN_PROCESO" and nuevo_estado in ["COMPLETA", "INCOMPLETA"]:
            transicion_valida = True

        elif estado_actual == "INCOMPLETA" and nuevo_estado == "EN_PROCESO":
            transicion_valida = True


        if not transicion_valida:
            return jsonify({"error": "Transición no permitida"}), 400

        conn.execute("""
            UPDATE notas
            SET estado=%s
            WHERE id=%s
        """,(nuevo_estado, nota_id))

    return jsonify({
        "ok": True,
        "nuevo_estado": nuevo_estado
    })


@app.route("/notas/<nota_id>/reset", methods=["POST"])
def resetear_nota(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    with get_conn() as conn:

        nota = conn.execute("""
            SELECT id
            FROM notas
            WHERE id=%s
            AND empacador_id=%s
            AND estado!='ARCHIVADA'
        """,(nota_id, auth["empacador_id"])).fetchone()

        if not nota:
            return jsonify({"error": "Nota no encontrada o no autorizada"}), 403

        conn.execute("""
            UPDATE items
            SET empacadas = 0
            WHERE nota_id=%s
        """,(nota_id,))

        conn.execute("""
            UPDATE notas
            SET estado='EN_PROCESO'
            WHERE id=%s
        """,(nota_id,))

        productos = conn.execute("""
            SELECT id, marca, hilo, color, codigo,
                   cantidad as pz_requeridas,
                   empacadas as pz_empacadas
            FROM items
            WHERE nota_id=%s
        """,(nota_id,)).fetchall()
        
    return jsonify({
        "id": nota_id,
        "estado": "EN_PROCESO",
        "productos": productos
    })




@app.route("/notas/<nota_id>/scan", methods=["POST"])
def escanear_producto(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    codigo_barras = request.json.get("codigo")

    if not codigo_barras:
        return jsonify({"error": "Código requerido"}), 400

    producto = obtener_producto_por_codigo_barras(codigo_barras)
    if not producto:
        return jsonify({"error": "No existe en almacén"}), 404

    with get_conn() as conn:

        nota = conn.execute("""
            SELECT empacador_id
            FROM notas
            WHERE id=%s
            AND estado!='ARCHIVADA'
        """,(nota_id,)).fetchone()

        if not nota or (
            nota["empacador_id"] != auth["empacador_id"]
            and auth["rol"] != "ADMIN"
        ):
            return jsonify({"error": "No autorizado para esta nota"}), 403

        item = conn.execute("""
            SELECT id, cantidad, empacadas
            FROM items
            WHERE nota_id=%s
            AND codigo=%s
        """,(
            nota_id,
            producto["codigo"]
        )).fetchone()

        if not item:
            return jsonify({"error": "No pertenece a la nota"}), 404

        if item["empacadas"] >= item["cantidad"]:
            return jsonify({"error": "Piezas completas"}), 409

        conn.execute("""
            UPDATE items
            SET empacadas = empacadas + 1
            WHERE id=%s
        """,(item["id"],))

        totales = conn.execute("""
            SELECT SUM(cantidad) total,
                   SUM(empacadas) emp
            FROM items
            WHERE nota_id=%s
        """,(nota_id,)).fetchone()

        if totales["emp"] == totales["total"]:
            nuevo_estado = "COMPLETA"
            conn.execute("""
                UPDATE notas
                SET estado=%s,
                    fecha_finalizacion=NOW()
                WHERE id=%s
            """,(nuevo_estado, nota_id))
        elif totales["emp"] == 0:
            nuevo_estado = "EN_PROCESO"
            conn.execute("""
                UPDATE notas
                SET estado=%s
                WHERE id=%s
            """,(nuevo_estado, nota_id))
        else:
            nuevo_estado = "INCOMPLETA"
            conn.execute("""
                UPDATE notas
                SET estado=%s
                WHERE id=%s
            """,(nuevo_estado, nota_id))

        producto_actualizado = conn.execute("""
            SELECT id, marca, hilo, codigo,
                   cantidad as pz_requeridas,
                   empacadas as pz_empacadas
            FROM items
            WHERE id=%s
        """,(item["id"],)).fetchone()

    return jsonify({
        "ok": True,
        "estado_nota": nuevo_estado,
        "producto": producto_actualizado
    })






@app.route("/notas/<nota_id>/producto/ajustar", methods=["POST"])
def ajustar_producto(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    print("Headers:", request.headers)
    print("Raw data:", request.data)
    print("JSON recibido:", request.get_json(silent=True))
    data = request.get_json()

    item_id = data.get("id")
    cantidad = data.get("cantidad")

    if item_id is None or cantidad is None:
        return jsonify({"error": "Datos incompletos"}), 400

    with get_conn() as conn:

        nota = conn.execute("""
            SELECT empacador_id
            FROM notas
            WHERE id=%s
            AND estado!='ARCHIVADA'
        """,(nota_id,)).fetchone()

        if not nota or (
            nota["empacador_id"] != auth["empacador_id"]
            and auth["rol"] != "ADMIN"
        ):
            return jsonify({"error": "No autorizado para esta nota"}), 403


        item = conn.execute("""
            SELECT id, cantidad, empacadas
            FROM items
            WHERE nota_id=%s
            AND id=%s
        """,(nota_id, item_id)).fetchone()

        if not item:
            return jsonify({"error": "No pertenece a la nota"}), 404


        nuevo_total = item["empacadas"] + cantidad

        if nuevo_total < 0 or nuevo_total > item["cantidad"]:
            return jsonify({"error": "Cantidad inválida"}), 409


        conn.execute("""
            UPDATE items
            SET empacadas=%s
            WHERE id=%s
        """,(nuevo_total, item_id))


        totales = conn.execute("""
            SELECT SUM(cantidad) total,
                   SUM(empacadas) emp
            FROM items
            WHERE nota_id=%s
        """,(nota_id,)).fetchone()


        if totales["emp"] == totales["total"]:
            nuevo_estado = "COMPLETA"
            conn.execute("""
                UPDATE notas
                SET estado=%s,
                    fecha_finalizacion=NOW()
                WHERE id=%s
            """,(nuevo_estado, nota_id))

        elif totales["emp"] == 0:
            nuevo_estado = "EN_PROCESO"
            conn.execute("""
                UPDATE notas
                SET estado=%s
                WHERE id=%s
            """,(nuevo_estado, nota_id))

        else:
            nuevo_estado = "INCOMPLETA"
            conn.execute("""
                UPDATE notas
                SET estado=%s
                WHERE id=%s
            """,(nuevo_estado, nota_id))


        producto_actualizado = conn.execute("""
            SELECT id, marca, hilo, color, codigo,
                   cantidad as pz_requeridas,
                   empacadas as pz_empacadas
            FROM items
            WHERE id=%s
        """,(item_id,)).fetchone()


    return jsonify({
        "ok": True,
        "estado_nota": nuevo_estado,
        "producto": producto_actualizado
    })



@app.route("/errores-scan", methods=["GET"])
def ver_errores_scan():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT e.id,
                   e.nota_id,
                   e.codigo,
                   e.motivo,
                   e.fecha,
                   em.nombre as empacador
            FROM errores_scan e
            JOIN empacadores em
                ON em.id = e.empacador_id
            ORDER BY e.fecha DESC
        """).fetchall()

    return jsonify(rows)


@app.route("/notas/<nota_id>/progreso", methods=["GET"])
def progreso_nota(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    with get_conn() as conn:
        datos = conn.execute("""
            SELECT SUM(cantidad) total,
                   SUM(empacadas) emp
            FROM items
            WHERE nota_id=%s
        """,(nota_id,)).fetchone()

    total = datos["total"] or 0
    emp = datos["emp"] or 0

    porcentaje = round((emp/total)*100,2) if total else 0

    return jsonify({
        "total": total,
        "empacadas": emp,
        "porcentaje": porcentaje
    })


@app.route("/notas/<nota_id>/archivar", methods=["POST"])
def archivar_nota(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    if auth["rol"] != "ADMIN":
        return jsonify({"error": "Solo admin puede archivar"}), 403

    with get_conn() as conn:
        conn.execute("""
            UPDATE notas
            SET estado='ARCHIVADA'
            WHERE id=%s
        """,(nota_id,))

    return jsonify({"ok": True})


@app.route("/mantenimiento/archivar-expiradas", methods=["POST"])
def archivar_expiradas():

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    if auth["rol"] != "ADMIN":
        return jsonify({"error": "Solo admin"}), 403

    with get_conn() as conn:
        conn.execute("""
            UPDATE notas
            SET estado = 'ARCHIVADA'
            WHERE estado='COMPLETA'
            AND fecha_finalizacion < NOW() - INTERVAL '24 hours'
        """)

    return jsonify({"ok": True})


def generar_link_paqueteria(paqueteria, guia):

    if not paqueteria or not guia:
        return "#"

    paqueteria = paqueteria.upper()

    if paqueteria == "DHL":
        return f"https://www.dhl.com/mx-es/home/tracking.html?tracking-id={guia}"

    if paqueteria == "FEDEX":
        return f"https://www.fedex.com/apps/fedextrack/?tracknumbers={guia}"

    if paqueteria == "ESTAFETA":
        return f"https://www.estafeta.com/Herramientas/Rastreo?trackingNumber={guia}"

    return "#"

@app.route("/seguimiento/<nota_id>")
def seguimiento(nota_id):

    with get_conn() as conn:
        row = conn.execute("""
            SELECT id, cliente_nombre, estado, paqueteria, guia
            FROM notas
            WHERE id = %s
        """, (nota_id,)).fetchone()

    if not row:
        return "Nota no encontrada", 404

    nota = {
        "id": row["id"],
        "cliente_nombre": row["cliente_nombre"],
        "estado": row["estado"],
        "paqueteria": row["paqueteria"],
        "guia": row["guia"],
    }

    progreso_map = {
       "PAGADA": 15,
       "EN_PROCESO": 25,
       "INCOMPLETA": 50,
       "COMPLETA": 75,
       "ENVIADO": 100,
       
    }

    estado = nota["estado"]

    # 🔥 REGLA CORRECTA
    if nota["guia"] and estado == "COMPLETA":
        estado_visual = "ENVIADO"
    else:
        estado_visual = estado

    progreso = progreso_map.get(estado_visual, 10)

    return render_template(
        "seguimiento.html",
        nota=nota,
        estado_visual=estado_visual,
        progreso=progreso
    )
@app.route("/notas/<nota_id>/guia", methods=["POST"])
def agregar_guia(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    data = request.json
    guia = data.get("guia")
    paqueteria = data.get("paqueteria")

    if not guia:
        return jsonify({"error": "Guía requerida"}), 400

    with get_conn() as conn:

        nota = conn.execute("""
            SELECT estado
            FROM notas
            WHERE id=%s
        """,(nota_id,)).fetchone()

        if not nota:
            return jsonify({"error": "Nota no encontrada"}), 404

        # 🔥 VALIDACIÓN CLAVE
        if nota["estado"] != "COMPLETA":
            return jsonify({"error": "Solo notas COMPLETAS pueden enviarse"}), 400

        conn.execute("""
            UPDATE notas
            SET guia=%s,
                paqueteria=%s,
                estado='ENVIADO'
            WHERE id=%s
        """,(guia, paqueteria, nota_id))
    return jsonify({"ok": True, "estado": "ENVIADO"})


# ==============================
# IMPRIMIR DESTINATARIO
# ==============================

@app.route("/notas/<nota_id>/imprimir/<tipo>", methods=["POST"])
def solicitar_impresion(nota_id, tipo):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    if tipo not in ["destinatario", "remitente", "ambas"]:
        return jsonify({"error": "Tipo inválido"}), 400

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO cola_impresion (nota_id, tipo)
            VALUES (%s,%s)
        """,(nota_id, tipo))

    return jsonify({"ok": True, "mensaje": "Enviado a cola de impresión"})


# ==============================
# IMPRIMIR AMBAS
# ==============================
@app.route("/notas/<nota_id>/datos-impresion", methods=["GET"])
def datos_impresion(nota_id):

    if request.headers.get("X-PRINT-KEY") != "MI_CLAVE_DE_IMPRESION_LOCAL":
        return jsonify({"error": "No autorizado"}), 401

    with get_conn() as conn:
        nota = conn.execute("""
            SELECT n.id,
                   n.cliente_nombre,
                   n.paqueteria,
                   c.telefono,
                   c.direccion
            FROM notas n
            JOIN clientes c ON c.nombre = n.cliente_nombre
            WHERE n.id=%s
        """,(nota_id,)).fetchone()

    if not nota:
        return jsonify({"error": "Nota no encontrada"}), 404

    import json

    direccion = nota["direccion"]

    # Si está guardado como texto JSON
    if isinstance(direccion, str):
        try:
            direccion = json.loads(direccion)
        except:
            direccion = {}

    cliente = {
        "nombre": nota["cliente_nombre"],
        "telefono": nota["telefono"],
        "direccion": direccion or {}
    }

    remitente = {
        "nombre": "Jorge Angel Ortiz Anguiano",
        "telefono": "5545414186",
        "direccion": {
            "calle": "Cocula",
            "numero_ext": "246",
            "numero_int": "",
            "colonia": "Benito Juarez",
            "municipio": "Nezahualcoyotl",
            "estado": "Estado de Mexico",
            "codigo_postal": "57000",
            "referencia": "Lona rosa"
        }
    }

    return jsonify({
        "cliente": cliente,
        "envio": {"tipo": nota["paqueteria"]},
        "remitente": remitente
    })

@app.route("/cola-impresion", methods=["GET"])
def obtener_cola():

    clave = request.headers.get("X-PRINT-KEY")
    if clave != "MI_CLAVE_DE_IMPRESION_LOCAL":
        return jsonify({"error": "No autorizado"}), 401

    with get_conn() as conn:
        tareas = conn.execute("""
            SELECT id, nota_id, tipo
            FROM cola_impresion
            WHERE estado='PENDIENTE'
            ORDER BY creado_en ASC
            LIMIT 5
        """).fetchall()

    return jsonify(tareas)

@app.route("/cola-impresion/<int:id>/completar", methods=["POST"])
def completar_impresion(id):

    clave = request.headers.get("X-PRINT-KEY")
    if clave != "MI_CLAVE_DE_IMPRESION_LOCAL":
        return jsonify({"error": "No autorizado"}), 401

    with get_conn() as conn:
        conn.execute("""
            UPDATE cola_impresion
            SET estado='IMPRESO',
                impreso_en=NOW()
            WHERE id=%s
        """,(id,))

    return jsonify({"ok": True})

@app.route("/health")
def health():
    return {"status": "ok"}, 200

# =========================
# MAIN
# =========================
app.jinja_env.globals.update(
    generar_link_paqueteria=generar_link_paqueteria
)




import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

