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
from datetime import date, datetime, timedelta, timezone
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

try:
    from hilorama_backend.services.auditoria_service import (
        diferencias_relevantes as _diferencias_auditoria,
        limpiar_datos_sensibles as _limpiar_datos_auditoria,
        registrar_auditoria as _registrar_auditoria_db,
    )
    from hilorama_backend.services.movimientos_almacen_service import (
        agrupar_lineas_producto as _agrupar_lineas_movimiento,
        cantidad_reintegrable as _cantidad_reintegrable_movimiento,
        clave_producto_movimiento as _clave_producto_movimiento,
        registrar_movimiento_almacen as _registrar_movimiento_db,
    )
except ImportError:
    from services.auditoria_service import (
        diferencias_relevantes as _diferencias_auditoria,
        limpiar_datos_sensibles as _limpiar_datos_auditoria,
        registrar_auditoria as _registrar_auditoria_db,
    )
    from services.movimientos_almacen_service import (
        agrupar_lineas_producto as _agrupar_lineas_movimiento,
        cantidad_reintegrable as _cantidad_reintegrable_movimiento,
        clave_producto_movimiento as _clave_producto_movimiento,
        registrar_movimiento_almacen as _registrar_movimiento_db,
    )

try:
    from hilorama_backend.services.clientes_analytics_service import (
        construir_analitica_clientas,
        es_venta_comercial as _es_venta_comercial_crm,
        normalizar_estado as _normalizar_estado_crm,
        parsear_fecha as _parsear_fecha_crm,
    )
except ImportError:
    from services.clientes_analytics_service import (
        construir_analitica_clientas,
        es_venta_comercial as _es_venta_comercial_crm,
        normalizar_estado as _normalizar_estado_crm,
        parsear_fecha as _parsear_fecha_crm,
    )

try:
    from hilorama_backend.services.notificaciones_service import (
        construir_notificaciones_operacion,
        construir_oportunidades_venta,
        construir_resumen_notificaciones,
        guia_nota as _guia_nota_notificaciones,
        requiere_guia as _requiere_guia_notificaciones,
    )
except ImportError:
    from services.notificaciones_service import (
        construir_notificaciones_operacion,
        construir_oportunidades_venta,
        construir_resumen_notificaciones,
        guia_nota as _guia_nota_notificaciones,
        requiere_guia as _requiere_guia_notificaciones,
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
    acciones = {
        "login_ok": ("INICIO_SESION_CORRECTO", "OK", "seguridad"),
        "login_bloqueado": ("ACCESO_DENEGADO", "DENEGADO", "seguridad"),
        "logout": ("CIERRE_SESION", "OK", "seguridad"),
        "dispositivo_bloqueado": ("DISPOSITIVO_BLOQUEADO", "OK", "seguridad"),
        "sesion_cerrada_remota": ("SESION_CERRADA_REMOTAMENTE", "OK", "seguridad"),
        "CREAR_USUARIO_CLIENTE": ("USUARIO_CREADO", "OK", "administracion"),
        "RESET_PASSWORD_USUARIO": ("PASSWORD_RESTABLECIDO", "OK", "administracion"),
        "ACTIVAR_USUARIO_CLIENTE": ("USUARIO_ACTIVADO", "OK", "administracion"),
        "DESACTIVAR_USUARIO_CLIENTE": ("USUARIO_DESACTIVADO", "OK", "administracion"),
    }
    accion, resultado, modulo = acciones.get(
        evento,
        (str(evento or "EVENTO_LICENCIA").upper(), "OK", "seguridad"),
    )
    try:
        _registrar_auditoria_general_api(
            conn,
            {
                "cliente_id": cliente_id,
                "usuario_id": usuario_id,
                "device_id_hash": device_id_hash,
            },
            accion,
            modulo,
            entidad_tipo="usuario_sistema",
            entidad_id=usuario_id,
            descripcion=detalle or str(evento or "").replace("_", " "),
            resultado=resultado,
        )
    except Exception:
        # La auditoria no debe impedir cerrar una sesion si falta la migracion durante la transicion.
        app.logger.warning("No se pudo registrar auditoria general de seguridad", exc_info=True)


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
            _registrar_auditoria_general_api(
                conn,
                {
                    "cliente_id": (row or {}).get("cliente_id"),
                    "usuario_id": (row or {}).get("usuario_id"),
                    "device_id_hash": device_id_hash,
                },
                "INICIO_SESION_FALLIDO",
                "seguridad",
                entidad_tipo="usuario_sistema",
                entidad_id=(row or {}).get("usuario_id"),
                descripcion="Credenciales rechazadas.",
                datos_nuevos={"usuario": usuario},
                resultado="DENEGADO",
            )
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
    antes, despues = _diferencias_auditoria(anterior, {campo: valor_nuevo}, campos=(campo,))
    return _registrar_auditoria_general_api(
        conn,
        auth,
        "PRODUCTO_EDITADO",
        "almacen",
        entidad_tipo="producto",
        entidad_id=(anterior or {}).get("id"),
        descripcion=motivo or "Edición manual de producto desde Almacén",
        datos_anteriores=antes,
        datos_nuevos=despues,
    )


def _registrar_movimiento_producto_alta_api(conn, producto, motivo, auth):
    stock = int((producto or {}).get("stock") or 0)
    if stock <= 0 or not _es_inventariable_tipo_api(producto.get("tipo_producto")):
        return None
    producto_id = (producto or {}).get("id")
    return _registrar_movimiento_inventario_api(
        conn,
        auth,
        producto=producto,
        tipo="STOCK_INICIAL",
        cantidad=stock,
        stock_anterior=0,
        stock_nuevo=stock,
        motivo=motivo or "Stock inicial al crear producto",
        referencia_tipo="PRODUCTO",
        referencia_id=producto_id,
        idempotency_key=f"STOCK_INICIAL:{producto_id}" if producto_id is not None else None,
        metadata={"origen": "alta_producto"},
    )


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
            _registrar_auditoria_general_api(
                conn,
                auth,
                "PRODUCTO_CREADO",
                "almacen",
                entidad_tipo="producto",
                entidad_id=producto_creado.get("id"),
                descripcion=motivo,
                datos_nuevos={
                    campo: producto_creado.get(campo)
                    for campo in ("marca", "hilo", "color", "codigo", "stock", "tipo_producto", "estado")
                },
            )

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
            movimiento = _cambiar_stock_con_movimiento_api(
                conn,
                auth,
                producto,
                stock_nuevo,
                tipo="AJUSTE_POSITIVO" if diferencia >= 0 else "AJUSTE_NEGATIVO",
                motivo=motivo,
                referencia_tipo="PRODUCTO",
                referencia_id=producto_id,
                idempotency_key=data.get("idempotency_key"),
                metadata={"origen": "ajuste_manual_almacen"},
                estado_nuevo=estado_nuevo,
            )
            _registrar_auditoria_general_api(
                conn,
                auth,
                "AJUSTE_STOCK_MANUAL",
                "almacen",
                entidad_tipo="producto",
                entidad_id=producto_id,
                descripcion=motivo,
                datos_anteriores={"stock": stock_anterior, "estado": producto.get("estado")},
                datos_nuevos={"stock": stock_nuevo, "estado": estado_nuevo},
            )

        producto_respuesta = obtener_producto_por_id(producto_id)
        return jsonify({"ok": True, "producto": producto_respuesta, "movimiento": movimiento})
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
    stock_anterior = int((anterior or {}).get("stock") or 0)
    tipo_anterior = (anterior or {}).get("tipo_producto") or (anterior or {}).get("tipo") or "INVENTARIO"
    inventariable_anterior = _producto_inventariable_api(anterior)
    stock_nuevo = int(stock_nuevo or 0)
    diferencia = stock_nuevo - stock_anterior
    if diferencia:
        if not inventariable_anterior and inventariable_nuevo:
            tipo_movimiento = "STOCK_INICIAL"
        elif inventariable_anterior and not inventariable_nuevo:
            tipo_movimiento = "CORRECCION"
        else:
            tipo_movimiento = "AJUSTE_POSITIVO" if diferencia > 0 else "AJUSTE_NEGATIVO"
        _registrar_movimiento_inventario_api(
            conn,
            auth,
            producto=anterior,
            tipo=tipo_movimiento,
            cantidad=diferencia,
            stock_anterior=stock_anterior,
            stock_nuevo=stock_nuevo,
            motivo=motivo,
            referencia_tipo="PRODUCTO",
            referencia_id=(anterior or {}).get("id"),
            metadata={"operacion": "cambio_tipo_producto", "tipo_anterior": tipo_anterior, "tipo_nuevo": tipo_nuevo},
        )
    _registrar_auditoria_general_api(
        conn,
        auth,
        "TIPO_PRODUCTO_ACTUALIZADO",
        "almacen",
        entidad_tipo="producto",
        entidad_id=(anterior or {}).get("id"),
        descripcion=motivo,
        datos_anteriores={"tipo_producto": tipo_anterior, "es_inventariable": inventariable_anterior, "stock": stock_anterior},
        datos_nuevos={"tipo_producto": tipo_nuevo, "es_inventariable": inventariable_nuevo, "stock": stock_nuevo},
    )


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
    tipo_anterior = producto.get("tipo_producto") or producto.get("tipo") or "INVENTARIO"
    motivo_final = motivo
    if advertencias:
        motivo_final = f"{motivo} | Advertencias: {'; '.join(advertencias)}"
    stock_anterior = int(stock_anterior or 0)
    if stock_anterior:
        _registrar_movimiento_inventario_api(
            conn,
            auth,
            producto=producto,
            tipo="CORRECCION",
            cantidad=-stock_anterior,
            stock_anterior=stock_anterior,
            stock_nuevo=0,
            motivo=motivo_final,
            referencia_tipo="PRODUCTO",
            referencia_id=producto.get("id"),
            idempotency_key=f"ANULACION_PRODUCTO:{producto.get('id')}" if producto.get("id") is not None else None,
            metadata={"operacion": "anulacion_producto", "advertencias": list(advertencias or [])},
        )
    _registrar_auditoria_general_api(
        conn,
        auth,
        "PRODUCTO_ANULADO",
        "almacen",
        entidad_tipo="producto",
        entidad_id=producto.get("id"),
        descripcion=motivo_final,
        datos_anteriores={"estado": producto.get("estado"), "tipo_producto": tipo_anterior, "stock": stock_anterior},
        datos_nuevos={"estado": "ANULADO", "tipo_producto": "ANULADO", "es_inventariable": False, "stock": 0},
    )


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
        "cliente_sistema_id",
        "producto_id",
        "referencia_tipo",
        "referencia_id",
        "usuario_id",
        "device_id",
        "idempotency_key",
        "metadata_json",
        "fecha_creacion",
    ):
        if columna in columnas:
            campos.append(f"{columna} AS {columna}")
        else:
            campos.append(f"NULL AS {columna}")
    return ", ".join(campos)


def _movimiento_row_api(row):
    data = _row_dict(row) or {}
    fecha = data.get("fecha_creacion") or data.get("fecha")
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
        "cliente_sistema_id": data.get("cliente_sistema_id"),
        "producto_id": data.get("producto_id"),
        "referencia_tipo": data.get("referencia_tipo") or "",
        "referencia_id": data.get("referencia_id") or "",
        "usuario_id": data.get("usuario_id"),
        "device_id": data.get("device_id") or "",
        "idempotency_key": data.get("idempotency_key") or "",
        "metadata_json": _limpiar_datos_auditoria(_json_field(data.get("metadata_json"), {})),
    }


def _restriccion_cliente_movimientos_api(columnas, auth):
    """Limita movimientos al cliente autenticado salvo para super_admin."""
    if (auth or {}).get("rol") == "super_admin":
        return "", ()
    cliente_id = (auth or {}).get("cliente_id")
    if cliente_id in (None, "") or "cliente_sistema_id" not in columnas:
        raise PermissionError("No se puede consultar movimientos sin aislamiento por cliente.")
    return "cliente_sistema_id=%s", (cliente_id,)


def _filtros_movimientos_almacen_api(conn, columnas, args, auth=None):
    filtros = []
    valores = []

    def filtro_texto(param, columna):
        valor = str(args.get(param) or "").strip()
        if valor and columna in columnas:
            filtros.append(f"{columna} ILIKE %s")
            valores.append(f"%{valor}%")

    producto_id = str(args.get("producto_id") or args.get("producto") or "").strip()
    if producto_id:
        productos_cols = _columnas_tabla_api(conn, "productos")
        condiciones_busqueda = ["CAST(id AS TEXT)=%s"] if "id" in productos_cols else []
        valores_busqueda = [producto_id] if condiciones_busqueda else []
        if "codigo" in productos_cols:
            condiciones_busqueda.append("CAST(codigo AS TEXT) ILIKE %s")
            valores_busqueda.append(f"%{producto_id}%")
        if not condiciones_busqueda:
            raise LookupError("No se puede resolver el producto solicitado.")
        producto = conn.execute(
            f"SELECT * FROM productos WHERE {' OR '.join(condiciones_busqueda)} ORDER BY id LIMIT 1",
            tuple(valores_busqueda),
        ).fetchone()
        producto = _row_dict(producto)
        if not producto:
            raise LookupError("Producto no encontrado.")
        coincidencias_producto = []
        if "producto_id" in columnas:
            coincidencias_producto.append(("producto_id=%s", [producto_id]))
        coincidencias_legacy = []
        valores_legacy = []
        if "codigo" in columnas and producto.get("codigo"):
            coincidencias_legacy.append("codigo=%s")
            valores_legacy.append(producto.get("codigo"))
        for campo in ("marca", "hilo", "color"):
            if campo in columnas and producto.get(campo):
                coincidencias_legacy.append(f"UPPER({campo})=UPPER(%s)")
                valores_legacy.append(producto.get(campo))
        if coincidencias_legacy:
            coincidencias_producto.append(("(" + " AND ".join(coincidencias_legacy) + ")", valores_legacy))
        if coincidencias_producto:
            filtros.append("(" + " OR ".join(condicion for condicion, _ in coincidencias_producto) + ")")
            for _, valores_coincidencia in coincidencias_producto:
                valores.extend(valores_coincidencia)

    for param in ("codigo", "marca", "hilo", "color", "tipo", "usuario"):
        filtro_texto(param, param)

    referencia = str(args.get("referencia") or "").strip()
    if referencia:
        campos_referencia = [campo for campo in ("referencia_tipo", "referencia_id") if campo in columnas]
        if campos_referencia:
            filtros.append("(" + " OR ".join(f"{campo} ILIKE %s" for campo in campos_referencia) + ")")
            valores.extend([f"%{referencia}%"] * len(campos_referencia))

    q = str(args.get("q") or "").strip()
    if q:
        campos_q = [campo for campo in ("marca", "hilo", "color", "codigo", "tipo", "campo", "motivo", "usuario", "referencia_tipo", "referencia_id") if campo in columnas]
        if campos_q:
            like = f"%{q}%"
            filtros.append("(" + " OR ".join(f"{campo} ILIKE %s" for campo in campos_q) + ")")
            valores.extend([like] * len(campos_q))

    fecha_columna = (
        "COALESCE(fecha_creacion, fecha)"
        if "fecha_creacion" in columnas and "fecha" in columnas
        else ("fecha_creacion" if "fecha_creacion" in columnas else ("fecha" if "fecha" in columnas else None))
    )
    desde = str(args.get("desde") or args.get("fecha_inicial") or "").strip()
    if desde and fecha_columna:
        filtros.append(f"{fecha_columna} >= %s")
        valores.append(desde)
    hasta = str(args.get("hasta") or args.get("fecha_final") or "").strip()
    if hasta and fecha_columna:
        filtros.append(f"{fecha_columna} < (%s::date + INTERVAL '1 day')")
        valores.append(hasta)

    restriccion_cliente, valores_cliente = _restriccion_cliente_movimientos_api(columnas, auth)
    if restriccion_cliente:
        filtros.append(restriccion_cliente)
        valores.extend(valores_cliente)
    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, tuple(valores)


def _puede_consultar_movimientos_api(auth):
    return (auth or {}).get("rol") in {"super_admin", "admin_cliente", "almacen"}


def _respuesta_movimientos_paginada_api(conn, columnas, args, auth=None):
    per_page = _api_limite(args.get("per_page") or args.get("limit"), default=50, maximo=500)
    page_raw = str(args.get("page") or "").strip()
    if page_raw:
        try:
            page = max(1, int(page_raw))
        except ValueError:
            raise ValueError("page debe ser un numero entero positivo.")
        offset = (page - 1) * per_page
    else:
        offset = _api_offset(args.get("offset"))
        page = (offset // per_page) + 1
    where, valores = _filtros_movimientos_almacen_api(conn, columnas, args, auth=auth)
    total_row = conn.execute(
        f"SELECT COUNT(*) AS total FROM movimientos_almacen {where}",
        valores,
    ).fetchone()
    total = int((total_row or {}).get("total") or 0)
    if "fecha_creacion" in columnas and "fecha" in columnas:
        fecha_order = "fecha_creacion DESC NULLS LAST, fecha DESC"
    elif "fecha_creacion" in columnas:
        fecha_order = "fecha_creacion DESC"
    else:
        fecha_order = "fecha DESC" if "fecha" in columnas else "id DESC"
    rows = conn.execute(
        f"""
        SELECT {_select_movimiento_almacen_api(columnas)}
        FROM movimientos_almacen
        {where}
        ORDER BY {fecha_order}
        LIMIT %s OFFSET %s
        """,
        valores + (per_page, offset),
    ).fetchall()
    items = [_movimiento_row_api(row) for row in rows]
    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if total else 0,
    }
    return {
        "ok": True,
        "items": items,
        "pagination": pagination,
        # Compatibilidad con la vista de Almacen existente.
        "movimientos": items,
        "total": total,
        "limit": per_page,
        "offset": offset,
    }


@app.route("/api/almacen/movimientos", methods=["GET"])
def api_almacen_movimientos():
    auth, error = _require_license_api()
    if error:
        return error
    if not _puede_consultar_movimientos_api(auth):
        return jsonify({"ok": False, "error": "Permiso denegado para consultar movimientos."}), 403
    try:
        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "movimientos_almacen")
            if not columnas:
                return jsonify({"ok": True, "items": [], "movimientos": [], "pagination": {"page": 1, "per_page": 50, "total": 0, "pages": 0}, "total": 0, "limit": 50, "offset": 0})
            respuesta = _respuesta_movimientos_paginada_api(conn, columnas, request.args, auth=auth)
        return jsonify(respuesta)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al consultar movimientos de almacen")
        return jsonify({"ok": False, "error": "No se pudieron consultar los movimientos de almacen."}), 500


@app.route("/api/almacen/productos/<int:producto_id>/movimientos", methods=["GET"])
def api_almacen_producto_movimientos(producto_id):
    auth, error = _require_license_api()
    if error:
        return error
    if not _puede_consultar_movimientos_api(auth):
        return jsonify({"ok": False, "error": "Permiso denegado para consultar movimientos."}), 403
    try:
        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "movimientos_almacen")
            if not columnas:
                return jsonify({"ok": True, "items": [], "pagination": {"page": 1, "per_page": 50, "total": 0, "pages": 0}})
            args = request.args.to_dict(flat=True)
            args["producto_id"] = str(producto_id)
            respuesta = _respuesta_movimientos_paginada_api(conn, columnas, args, auth=auth)
        return jsonify(respuesta)
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al consultar historial de movimiento por producto")
        return jsonify({"ok": False, "error": "No se pudo consultar el historial del producto."}), 500


@app.route("/api/almacen/movimientos/<int:movimiento_id>", methods=["GET"])
def api_almacen_movimiento_detalle(movimiento_id):
    auth, error = _require_license_api()
    if error:
        return error
    if not _puede_consultar_movimientos_api(auth):
        return jsonify({"ok": False, "error": "Permiso denegado para consultar movimientos."}), 403
    try:
        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "movimientos_almacen")
            if not columnas:
                raise LookupError("No hay movimientos registrados.")
            where_cliente, valores_cliente = _restriccion_cliente_movimientos_api(columnas, auth)
            condicion_cliente = f" AND {where_cliente}" if where_cliente else ""
            row = conn.execute(
                f"SELECT {_select_movimiento_almacen_api(columnas)} FROM movimientos_almacen WHERE id=%s{condicion_cliente} LIMIT 1",
                (movimiento_id,) + valores_cliente,
            ).fetchone()
        if not row:
            raise LookupError("Movimiento no encontrado.")
        return jsonify({"ok": True, "movimiento": _movimiento_row_api(row)})
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except Exception:
        app.logger.exception("Error al consultar detalle de movimiento")
        return jsonify({"ok": False, "error": "No se pudo consultar el movimiento."}), 500


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
    antes, despues = _diferencias_auditoria(producto, {campo: valor_nuevo}, campos=(campo,))
    return _registrar_auditoria_general_api(
        conn,
        auth,
        "PRODUCTO_ACTUALIZADO_MASIVO",
        "almacen",
        entidad_tipo="producto",
        entidad_id=producto.get("id"),
        descripcion=f"{motivo} ({tipo})",
        datos_anteriores=antes,
        datos_nuevos=despues,
    )


def _registrar_movimiento_precio_marca_api(conn, marca, anterior, distribuidor, venta, cantidad, motivo, auth):
    antes, despues = _diferencias_auditoria(
        anterior or {},
        {"distribuidor": distribuidor, "venta": venta},
        campos=("distribuidor", "venta"),
    )
    return _registrar_auditoria_general_api(
        conn,
        auth,
        "PRECIO_MARCA_ACTUALIZADO",
        "almacen",
        entidad_tipo="marca",
        entidad_id=marca,
        descripcion=f"{motivo}. Productos afectados: {cantidad}.",
        datos_anteriores=antes,
        datos_nuevos=despues,
    )


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
    cache = None
    try:
        cache = getattr(conn, "_hilorama_columnas_cache", None)
        if cache is None:
            cache = {}
            setattr(conn, "_hilorama_columnas_cache", cache)
        if tabla in cache:
            return set(cache[tabla])
    except Exception:
        cache = None
    rows = conn.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name=%s
    """, (tabla,)).fetchall()
    columnas = {row["column_name"] for row in rows}
    if cache is not None:
        cache[tabla] = frozenset(columnas)
    return columnas


def _contexto_request_auditoria_api():
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        return {
            "ip": str(ip or "").split(",")[0].strip() or None,
            "user_agent": request.headers.get("User-Agent"),
            "request_id": request.headers.get("X-Request-ID") or request.headers.get("X-Request-Id"),
        }
    except RuntimeError:
        return {"ip": None, "user_agent": None, "request_id": None}


def _registrar_auditoria_general_api(
    conn,
    auth,
    accion,
    modulo,
    *,
    entidad_tipo=None,
    entidad_id=None,
    descripcion=None,
    datos_anteriores=None,
    datos_nuevos=None,
    resultado="OK",
    codigo_error=None,
):
    columnas = _columnas_tabla_api(conn, "auditoria_general")
    if not columnas:
        app.logger.warning("No se registro auditoria general porque falta la migracion FASE 9B")
        return None
    contexto = _contexto_request_auditoria_api()
    return _registrar_auditoria_db(
        conn,
        columnas,
        accion=accion,
        modulo=modulo,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        descripcion=descripcion,
        datos_anteriores=datos_anteriores,
        datos_nuevos=datos_nuevos,
        resultado=resultado,
        codigo_error=codigo_error,
        usuario_id=(auth or {}).get("usuario_id"),
        cliente_sistema_id=(auth or {}).get("cliente_id"),
        device_id=(auth or {}).get("device_id_hash"),
        **contexto,
    )


def _movimiento_idempotente_existente_api(conn, idempotency_key, cliente_sistema_id=None):
    clave = str(idempotency_key or "").strip()
    if not clave:
        return None
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if "idempotency_key" not in columnas:
        return None
    if "cliente_sistema_id" in columnas:
        return conn.execute(
            """
            SELECT id, producto_id, tipo, cantidad, stock_anterior, stock_nuevo
            FROM movimientos_almacen
            WHERE idempotency_key=%s
              AND COALESCE(cliente_sistema_id, 0)=COALESCE(%s, 0)
            LIMIT 1
            """,
            (clave, cliente_sistema_id),
        ).fetchone()
    return conn.execute(
        "SELECT id, producto_id, tipo, cantidad, stock_anterior, stock_nuevo FROM movimientos_almacen WHERE idempotency_key=%s LIMIT 1",
        (clave,),
    ).fetchone()


def _registrar_movimiento_inventario_api(
    conn,
    auth,
    *,
    producto,
    tipo,
    cantidad,
    stock_anterior,
    stock_nuevo,
    motivo=None,
    referencia_tipo=None,
    referencia_id=None,
    idempotency_key=None,
    metadata=None,
):
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    if idempotency_key and not {"idempotency_key", "cliente_sistema_id"}.issubset(columnas):
        raise RuntimeError("Falta aplicar la migracion FASE 9B para registrar movimientos idempotentes.")
    usuario = (auth or {}).get("usuario") or (auth or {}).get("usuario_nombre") or "usuario_desconocido"
    return _registrar_movimiento_db(
        conn,
        columnas,
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo,
        motivo=motivo,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        usuario_id=(auth or {}).get("usuario_id"),
        cliente_sistema_id=(auth or {}).get("cliente_id"),
        usuario=usuario,
        device_id=(auth or {}).get("device_id_hash"),
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


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
ESTADOS_NOTA_PAGADA_API = {
    "PAGADA", "EN_PROCESO", "INCOMPLETA", "COMPLETA", "ENVIADO", "VENTA_PAGADA"
}
ESTADOS_NOTA_ANULADA_API = {"ANULADA", "CANCELADA", "ELIMINADA"}
ESTADOS_EMPAQUE_ASIGNABLES = {"PAGADA", "EN_PROCESO", "INCOMPLETA"}
ESTADOS_EMPAQUE_EDITABLES = ESTADOS_EMPAQUE_ASIGNABLES | {"COMPLETA"}
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


def _estado_empaque_por_totales(total, empacadas):
    total = max(int(total or 0), 0)
    empacadas = max(int(empacadas or 0), 0)
    if total > 0 and empacadas >= total:
        return "COMPLETA"
    if empacadas > 0:
        return "INCOMPLETA"
    return "EN_PROCESO"


def _actualizar_estado_empaque_nota_api(conn, nota_id, total, empacadas):
    nuevo_estado = _estado_empaque_por_totales(total, empacadas)
    notas_cols = _columnas_tabla_api(conn, "notas")
    campos = ["estado=%s"]
    valores = [nuevo_estado]
    if "fecha_finalizacion" in notas_cols:
        if nuevo_estado == "COMPLETA":
            campos.append("fecha_finalizacion=COALESCE(fecha_finalizacion, NOW())")
        else:
            campos.append("fecha_finalizacion=NULL")
    conn.execute(
        f"UPDATE notas SET {', '.join(campos)} WHERE id=%s",
        tuple(valores + [nota_id]),
    )
    return nuevo_estado


def _rechazar_pago_nota_anulada_api(nota):
    estado = _normalizar_estado_pago_api((nota or {}).get("estado"))
    if estado in ESTADOS_NOTA_ANULADA_API | {"ARCHIVADA"}:
        mensaje = "No se puede registrar un pago en una nota anulada, cancelada o archivada."
        raise NotaPagoNoPermitido(mensaje, 409)


def _nota_tiene_pagos_api(conn, nota_id):
    try:
        pagos_cols = _columnas_tabla_api(conn, "pagos")
        if "nota_id" not in pagos_cols:
            return False
        row = conn.execute("SELECT 1 FROM pagos WHERE nota_id=%s LIMIT 1", (nota_id,)).fetchone()
        return bool(row)
    except Exception:
        return False


def _nota_pago_ya_aplicado_api(conn, nota):
    if not nota:
        return False
    estado = _normalizar_estado_pago_api(nota.get("estado"))
    if estado in ESTADOS_NOTA_PAGADA_API:
        return True
    if nota.get("fecha_pago"):
        return True
    return _nota_tiene_pagos_api(conn, nota.get("id"))


def _cantidades_movimiento_nota_api(conn, nota_id, auth, tipos, *, solo_positivos=False, solo_negativos=False):
    """Resume movimientos reales de una nota, siempre aislados por cliente."""
    columnas = _columnas_tabla_api(conn, "movimientos_almacen")
    requeridas = {"referencia_tipo", "referencia_id", "tipo", "cantidad"}
    if not requeridas.issubset(columnas):
        return {}

    filtros = ["UPPER(COALESCE(referencia_tipo, ''))='NOTA'", "referencia_id=%s"]
    valores = [str(nota_id)]
    tipos_normalizados = tuple(str(tipo).strip().upper() for tipo in tipos)
    filtros.append("UPPER(COALESCE(tipo, '')) IN (" + ",".join(["%s"] * len(tipos_normalizados)) + ")")
    valores.extend(tipos_normalizados)
    if "cliente_sistema_id" in columnas:
        cliente_id = (auth or {}).get("cliente_id")
        if cliente_id in (None, "") and (auth or {}).get("rol") != "super_admin":
            raise PermissionError("No se puede consultar movimientos de otra empresa.")
        if cliente_id not in (None, ""):
            filtros.append("cliente_sistema_id=%s")
            valores.append(cliente_id)

    campos = [
        "producto_id" if "producto_id" in columnas else "NULL AS producto_id",
        "marca" if "marca" in columnas else "NULL AS marca",
        "hilo" if "hilo" in columnas else "NULL AS hilo",
        "codigo" if "codigo" in columnas else "NULL AS codigo",
        "cantidad",
    ]
    rows = conn.execute(
        f"SELECT {', '.join(campos)} FROM movimientos_almacen WHERE {' AND '.join(filtros)}",
        tuple(valores),
    ).fetchall()
    cantidades = {}
    for row in rows:
        movimiento = _row_dict(row) or {}
        try:
            cantidad = int(movimiento.get("cantidad") or 0)
        except (TypeError, ValueError):
            continue
        if solo_positivos and cantidad <= 0:
            continue
        if solo_negativos and cantidad >= 0:
            continue
        clave = _clave_producto_movimiento(movimiento, movimiento)
        cantidades[clave] = cantidades.get(clave, 0) + abs(cantidad)
    return cantidades


def _cantidades_salida_nota_api(conn, nota_id, auth):
    return _cantidades_movimiento_nota_api(
        conn,
        nota_id,
        auth,
        {"VENTA", "SALIDA_STOCK", "SALIDA_STOCK_API"},
        solo_negativos=True,
    )


def _cantidades_reintegradas_nota_api(conn, nota_id, auth):
    return _cantidades_movimiento_nota_api(
        conn,
        nota_id,
        auth,
        {"CANCELACION_VENTA", "DEVOLUCION", "DEVOLUCION_POR_ANULACION", "STOCK_RESTABLECIDO_NOTA_PAGADA"},
        solo_positivos=True,
    )


def _cantidades_pendientes_devolucion_nota_api(conn, nota_id, auth):
    salidas = _cantidades_salida_nota_api(conn, nota_id, auth)
    reintegradas = _cantidades_reintegradas_nota_api(conn, nota_id, auth)
    pendientes = {}
    for clave, cantidad_salida in salidas.items():
        pendiente = _cantidad_reintegrable_movimiento(
            cantidad_salida,
            reintegradas.get(clave, 0),
        )
        if pendiente > 0:
            pendientes[clave] = pendiente
    return pendientes


def _nota_requiere_devolucion_stock_api(conn, nota, auth):
    if not nota or nota.get("id") in (None, ""):
        return False
    # El estado PAGADA por si solo no prueba que esta nota desconto inventario.
    return bool(_cantidades_pendientes_devolucion_nota_api(conn, nota.get("id"), auth))


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
    lineas_sin_agrupar = []
    # Primero se resuelven y agrupan las lineas; despues se bloquean los
    # productos en un orden estable para que dos ventas no dupliquen descuentos.
    for row in rows:
        item = _row_dict(row) or {}
        producto = _buscar_producto_item_api(conn, item, bloquear=False)
        lineas_sin_agrupar.append((item, _row_dict(producto) or {}, None))

    lineas = _agrupar_lineas_movimiento(lineas_sin_agrupar)
    if bloquear:
        lineas_bloqueadas = []
        for item, producto, afectado in lineas:
            if producto:
                producto_bloqueado = _buscar_producto_item_api(conn, item, bloquear=True)
                producto = _row_dict(producto_bloqueado) or {}
            lineas_bloqueadas.append((item, producto, afectado))
        lineas = lineas_bloqueadas

    afectados = []
    lineas_validadas = []
    for item, producto_data, _ in lineas:
        cantidad = _cantidad_item_stock_api(item)

        if producto_data and not _producto_inventariable_api(producto_data):
            lineas_validadas.append((item, producto_data, None))
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
        lineas_validadas.append((item, producto_data, afectado))
    return lineas_validadas, afectados


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
        _registrar_auditoria_general_api(
            conn,
            auth,
            "AUTORIZACION_STOCK_ESPECIAL",
            "ventas",
            entidad_tipo="producto",
            entidad_id=producto.get("id") or producto.get("codigo"),
            descripcion=motivo,
            datos_anteriores={"stock_actual": producto.get("stock_actual")},
            datos_nuevos={"cantidad_solicitada": producto.get("cantidad_solicitada")},
            resultado="AUTORIZADO",
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
    movimientos = []
    for item, producto, _ in lineas:
        if not producto or not _producto_inventariable_api(producto):
            continue
        cantidad = _cantidad_item_stock_api(item)
        stock_anterior = int(producto.get("stock") or 0)
        stock_nuevo = stock_anterior - cantidad
        estado_nuevo = "OK" if stock_nuevo >= STOCK_MINIMO_API else "RESURTIR"
        identificador_producto = producto.get("id") or item.get("codigo") or "sin_producto"
        idempotency_key = f"VENTA:PAGO:{nota_id}:{identificador_producto}"
        movimiento = _cambiar_stock_con_movimiento_api(
            conn,
            auth,
            producto,
            stock_nuevo,
            tipo="VENTA",
            motivo=f"Descuento por pago de nota {nota_id}",
            referencia_tipo="NOTA",
            referencia_id=nota_id,
            idempotency_key=idempotency_key,
            metadata={"operacion": "pago", "nota_id": str(nota_id), "cantidad_item": cantidad},
            estado_nuevo=estado_nuevo,
        )
        movimientos.append(movimiento)
    return movimientos


def _devolucion_stock_existente_api(conn, nota_id, auth):
    """Una devolucion previa de esta empresa bloquea una segunda anulacion."""
    return bool(_cantidades_reintegradas_nota_api(conn, nota_id, auth))


def _producto_por_clave_movimiento_api(conn, clave_producto, bloquear=False):
    """Resuelve un producto desde la llave estable de un movimiento ya registrado."""
    productos_cols = _columnas_tabla_api(conn, "productos")
    bloqueo = " FOR UPDATE" if bloquear else ""
    if not clave_producto:
        return None

    if clave_producto[0] == "producto_id":
        if "id" not in productos_cols:
            return None
        return conn.execute(
            f"SELECT * FROM productos WHERE id=%s LIMIT 1{bloqueo}",
            (clave_producto[1],),
        ).fetchone()

    if len(clave_producto) != 4 or not {"marca", "hilo", "codigo"}.issubset(productos_cols):
        return None
    _, marca, hilo, codigo = clave_producto
    return conn.execute(
        f"""
        SELECT *
        FROM productos
        WHERE UPPER(COALESCE(CAST(marca AS TEXT), ''))=%s
          AND UPPER(COALESCE(CAST(hilo AS TEXT), ''))=%s
          AND UPPER(COALESCE(CAST(codigo AS TEXT), ''))=%s
        LIMIT 1{bloqueo}
        """,
        (str(marca).upper(), str(hilo).upper(), str(codigo).upper()),
    ).fetchone()


def _devolver_stock_nota_api(conn, nota_id, auth):
    cantidades_salida = _cantidades_salida_nota_api(conn, nota_id, auth)
    cantidades_reintegradas = _cantidades_reintegradas_nota_api(conn, nota_id, auth)
    pendientes = _cantidades_pendientes_devolucion_nota_api(conn, nota_id, auth)
    productos_devueltos = []
    for clave_producto in sorted(pendientes, key=lambda clave: tuple(str(valor) for valor in clave)):
        cantidad_salida = int(cantidades_salida.get(clave_producto, 0) or 0)
        cantidad_reintegrada = int(cantidades_reintegradas.get(clave_producto, 0) or 0)
        cantidad = int(pendientes[clave_producto])
        producto = _row_dict(_producto_por_clave_movimiento_api(conn, clave_producto, bloquear=True)) or {}
        if not producto:
            raise ValueError(f"No se pudo resolver el producto del movimiento {clave_producto!r} para regresar stock.")
        if not _producto_inventariable_api(producto):
            continue
        stock_anterior = int(producto.get("stock") or 0)
        stock_nuevo = stock_anterior + cantidad
        estado_nuevo = "OK" if stock_nuevo >= STOCK_MINIMO_API else "RESURTIR"
        identificador_producto = producto.get("id") or producto.get("codigo") or "sin_producto"
        resultado_movimiento = _cambiar_stock_con_movimiento_api(
            conn,
            auth,
            producto,
            stock_nuevo,
            tipo="CANCELACION_VENTA",
            motivo=f"Stock regresado por anulacion de nota pagada autorizada. nota={nota_id}",
            referencia_tipo="NOTA",
            referencia_id=nota_id,
            idempotency_key=(
                f"CANCELACION:NOTA:{nota_id}:{identificador_producto}:"
                f"SALIDA:{cantidad_salida}:REINTEGRADA:{cantidad_reintegrada}"
            ),
            metadata={
                "operacion": "anulacion",
                "nota_id": str(nota_id),
                "cantidad_reintegrada": cantidad,
                "cantidad_salida_registrada": cantidad_salida,
                "cantidad_reintegrada_previa": cantidad_reintegrada,
            },
            estado_nuevo=estado_nuevo,
        )
        if resultado_movimiento.get("idempotente"):
            raise RuntimeError("La reposicion pendiente colisiono con una llave idempotente existente.")
        productos_devueltos.append({
            "producto_id": producto.get("id"),
            "codigo": producto.get("codigo") or "",
            "marca": producto.get("marca") or "",
            "hilo": producto.get("hilo") or "",
            "color": producto.get("color") or "",
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


def _actualizar_stock_producto_api(conn, producto, stock_nuevo, estado_nuevo=None):
    productos_cols = _columnas_tabla_api(conn, "productos")
    if estado_nuevo is None:
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


def _cambiar_stock_con_movimiento_api(
    conn,
    auth,
    producto,
    stock_nuevo,
    *,
    tipo,
    motivo,
    referencia_tipo,
    referencia_id,
    idempotency_key=None,
    metadata=None,
    estado_nuevo=None,
):
    """Actualiza stock y persiste su movimiento en la misma transaccion."""
    stock_anterior = int((producto or {}).get("stock") or 0)
    stock_nuevo = int(stock_nuevo)
    cantidad = stock_nuevo - stock_anterior
    if cantidad == 0:
        return {"creado": False, "sin_cambio": True, "movimiento": None}

    existente = _movimiento_idempotente_existente_api(
        conn,
        idempotency_key,
        (auth or {}).get("cliente_id"),
    )
    if existente:
        return {"creado": False, "idempotente": True, "movimiento": _row_dict(existente)}

    _actualizar_stock_producto_api(conn, producto, stock_nuevo, estado_nuevo=estado_nuevo)
    return _registrar_movimiento_inventario_api(
        conn,
        auth,
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo,
        motivo=motivo,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        idempotency_key=idempotency_key,
        metadata=metadata,
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

        detalle = (
            f"{motivo}. nota={nota_id}; cantidad_anterior={cantidad_anterior}; "
            f"cantidad_nueva={cantidad_nueva}; diferencia={diferencia}"
        )
        identificador_producto = producto.get("id") or item_base.get("codigo") or "sin_producto"
        _cambiar_stock_con_movimiento_api(
            conn,
            auth,
            producto,
            stock_nuevo,
            tipo="CORRECCION",
            motivo=detalle,
            referencia_tipo="NOTA",
            referencia_id=nota_id,
            idempotency_key=f"CORRECCION:NOTA:{nota_id}:{identificador_producto}:{cantidad_anterior}:{cantidad_nueva}",
            metadata={"operacion": "ajuste_admin_nota_pagada", "cantidad_anterior": cantidad_anterior, "cantidad_nueva": cantidad_nueva},
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
            "tipo": "CORRECCION",
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


# ================= CRM COMERCIAL DE CLIENTAS =================
# Solo se cuentan estados que el backend ya trata como ventas finales. No se
# incluyen COTIZACION, VENTA ni VENTA_PENDIENTE, porque aun no son ventas reales.
ESTADOS_VENTA_COMERCIAL_ANALYTICS = frozenset(
    set(ESTADOS_NOTA_PAGADA_API) | {"ENVIADO", "ARCHIVADA"}
)
ORDENES_RANKING_CLIENTAS = {
    "total_comprado",
    "numero_compras",
    "ticket_promedio",
    "ultima_compra",
}


def _filtros_analytics_clientas_api(args):
    return {
        "desde": (args.get("desde") or "").strip(),
        "hasta": (args.get("hasta") or "").strip(),
        "q": (args.get("q") or "").strip(),
        "segmento": (args.get("segmento") or "").strip(),
    }


def _where_estados_ventas_finales_api(alias="n"):
    estados = tuple(sorted(ESTADOS_VENTA_COMERCIAL_ANALYTICS))
    placeholders = ", ".join(["%s"] * len(estados))
    return (
        f"UPPER(COALESCE(CAST({alias}.estado AS TEXT), '')) IN ({placeholders})",
        estados,
    )


def _consultar_clientes_crm_api(conn, cliente_id=None):
    if not _tabla_existe_api(conn, "clientes"):
        return []
    columnas = _columnas_tabla_api(conn, "clientes")
    if "id" not in columnas:
        return []
    orden = "LOWER(nombre), id" if "nombre" in columnas else "id"
    where = ""
    valores = ()
    if cliente_id is not None:
        where = " WHERE id = %s"
        valores = (cliente_id,)
    rows = conn.execute(f"SELECT * FROM clientes{where} ORDER BY {orden}", valores).fetchall()
    return [_normalizar_cliente_api(row) for row in rows if row]


def _consultar_ventas_crm_api(conn, cliente_id=None):
    if not _tabla_existe_api(conn, "notas"):
        return []
    columnas = _columnas_tabla_api(conn, "notas")
    if not {"id", "cliente_id", "estado"}.issubset(columnas):
        return []
    where_estados, valores = _where_estados_ventas_finales_api("n")
    cliente_where = ""
    if cliente_id is not None:
        cliente_where = "\n          AND n.cliente_id = %s"
        valores = tuple(valores) + (cliente_id,)
    pagos_cols = (
        _columnas_tabla_api(conn, "pagos")
        if _tabla_existe_api(conn, "pagos")
        else set()
    )
    evidencia_pago = "FALSE"
    if "nota_id" in pagos_cols:
        evidencia_pago = "EXISTS (SELECT 1 FROM pagos pg WHERE pg.nota_id = n.id)"
    rows = conn.execute(f"""
        SELECT n.*, it.subtotal_productos, {evidencia_pago} AS pagado
        FROM notas n
        {_join_subtotal_items_nota_api()}
        WHERE n.cliente_id IS NOT NULL
          AND {where_estados}
          {cliente_where}
        ORDER BY n.fecha ASC NULLS LAST, n.id ASC
    """, valores).fetchall()
    ventas = []
    for row in rows:
        nota = _normalizar_nota_api(row)
        if not nota:
            continue
        if not _es_venta_comercial_crm(nota, ESTADOS_VENTA_COMERCIAL_ANALYTICS):
            continue
        nota["fecha_comercial"] = nota.get("fecha_pago") or nota.get("fecha")
        if _parsear_fecha_crm(nota.get("fecha_comercial")):
            ventas.append(nota)
    return ventas


def _consultar_items_ventas_crm_api(conn, cliente_id=None):
    if not _tabla_existe_api(conn, "items") or not _tabla_existe_api(conn, "notas"):
        return []
    items_cols = _columnas_tabla_api(conn, "items")
    notas_cols = _columnas_tabla_api(conn, "notas")
    productos_cols = _columnas_tabla_api(conn, "productos")
    if "nota_id" not in items_cols or not {"id", "estado"}.issubset(notas_cols):
        return []

    join_productos, tiene_join_producto = _join_producto_para_item(items_cols, productos_cols)
    codigo_expr = "COALESCE({})".format(
        ", ".join([
            _sql_text_col("i", "codigo", items_cols),
            _sql_text_col("i", "codigo_barras", items_cols),
            _sql_text_col("p", "codigo", productos_cols) if tiene_join_producto else "NULL",
            "''",
        ])
    )
    marca_expr = "COALESCE({})".format(
        ", ".join([
            _sql_text_col("i", "marca", items_cols),
            _sql_text_col("p", "marca", productos_cols) if tiene_join_producto else "NULL",
            "''",
        ])
    )
    hilo_expr = "COALESCE({})".format(
        ", ".join([
            _sql_text_col("i", "hilo", items_cols),
            _sql_text_col("p", "hilo", productos_cols) if tiene_join_producto else "NULL",
            "''",
        ])
    )
    color_expr = "COALESCE({})".format(
        ", ".join([
            _sql_text_col("i", "color", items_cols),
            _sql_text_col("p", "color", productos_cols) if tiene_join_producto else "NULL",
            "''",
        ])
    )
    cantidad_expr = _sql_num_col("i", "cantidad", items_cols)
    precio_expr = _sql_num_col("i", "precio", items_cols)
    where_estados, valores = _where_estados_ventas_finales_api("n")
    cliente_where = ""
    if cliente_id is not None:
        cliente_where = "\n          AND n.cliente_id = %s"
        valores = tuple(valores) + (cliente_id,)

    rows = conn.execute(f"""
        SELECT
            i.nota_id AS nota_id,
            {codigo_expr} AS codigo,
            {marca_expr} AS marca,
            {hilo_expr} AS hilo,
            {color_expr} AS color,
            {cantidad_expr} AS cantidad,
            {precio_expr} AS precio,
            ({cantidad_expr} * {precio_expr}) AS subtotal
        FROM items i
        JOIN notas n ON n.id = i.nota_id
        {join_productos}
        WHERE {where_estados}
          {cliente_where}
    """, valores).fetchall()
    return [_normalizar_item_nota_api(row) for row in rows]


def _analitica_clientas_conn_api(
    conn,
    filtros=None,
    cliente_id=None,
    incluir_historial=False,
    incluir_favoritos=False,
    incluir_graficas=False,
):
    clientes = _consultar_clientes_crm_api(conn, cliente_id=cliente_id)
    ventas = _consultar_ventas_crm_api(conn, cliente_id=cliente_id)
    items = (
        _consultar_items_ventas_crm_api(conn, cliente_id=cliente_id)
        if incluir_historial or incluir_favoritos
        else []
    )
    return construir_analitica_clientas(
        clientes,
        ventas,
        items,
        filtros=filtros,
        incluir_historial=incluir_historial,
        incluir_favoritos=incluir_favoritos,
        incluir_graficas=incluir_graficas,
        estados_finales=ESTADOS_VENTA_COMERCIAL_ANALYTICS,
    )


def _analitica_clientas_api(
    filtros=None,
    cliente_id=None,
    incluir_historial=False,
    incluir_favoritos=False,
    incluir_graficas=False,
):
    with get_conn() as conn:
        return _analitica_clientas_conn_api(
            conn,
            filtros=filtros,
            cliente_id=cliente_id,
            incluir_historial=incluir_historial,
            incluir_favoritos=incluir_favoritos,
            incluir_graficas=incluir_graficas,
        )


def _ranking_clientas_api(metricas, orden):
    orden = orden if orden in ORDENES_RANKING_CLIENTAS else "total_comprado"
    if orden == "ultima_compra":
        return sorted(
            metricas,
            key=lambda fila: (fila.get("ultima_compra") is not None, fila.get("ultima_compra") or ""),
            reverse=True,
        )
    return sorted(
        metricas,
        key=lambda fila: (fila.get(orden) or 0, fila.get("total_comprado") or 0, fila.get("nombre") or ""),
        reverse=True,
    )


def _fila_ranking_clienta_api(fila):
    return {
        clave: fila.get(clave)
        for clave in (
            "cliente_id",
            "nombre",
            "telefono",
            "total_comprado",
            "numero_compras",
            "ticket_promedio",
            "ultima_compra",
            "dias_desde_ultima_compra",
            "frecuencia_promedio_dias",
            "indice_compra",
            "segmento",
        )
    }


def _buscar_metricas_clienta_api(cliente_id, incluir_historial=False, incluir_favoritos=False):
    data = _analitica_clientas_api(
        cliente_id=cliente_id,
        incluir_historial=incluir_historial,
        incluir_favoritos=incluir_favoritos,
    )
    cliente_id = str(cliente_id)
    for fila in data.get("clientes", []):
        if str(fila.get("cliente_id")) == cliente_id:
            return fila
    raise LookupError("Cliente no encontrado.")


def _respuesta_error_analytics_clientas_api(exc, accion="consultar la analitica de clientas"):
    if isinstance(exc, ValueError):
        return jsonify({"ok": False, "error": str(exc)}), 400
    if isinstance(exc, LookupError):
        return jsonify({"ok": False, "error": str(exc)}), 404
    app.logger.exception("Error al %s", accion)
    return jsonify({"ok": False, "error": "No se pudo consultar el CRM de clientas."}), 500


@app.route("/api/clientes/analytics/resumen", methods=["GET"])
def api_clientes_analytics_resumen():
    _, error = _require_license_api()
    if error:
        return error
    try:
        filtros = _filtros_analytics_clientas_api(request.args)
        data = _analitica_clientas_api(
            filtros=filtros,
            incluir_favoritos=False,
            incluir_graficas=False,
        )
        return jsonify({"ok": True, "resumen": data["resumen"], "filtros": data["filtros"]})
    except Exception as exc:
        return _respuesta_error_analytics_clientas_api(exc, "consultar el resumen de clientas")


@app.route("/api/clientes/analytics/ranking", methods=["GET"])
def api_clientes_analytics_ranking():
    _, error = _require_license_api()
    if error:
        return error
    try:
        filtros = _filtros_analytics_clientas_api(request.args)
        orden = (request.args.get("orden") or "total_comprado").strip()
        if orden not in ORDENES_RANKING_CLIENTAS:
            raise ValueError("Orden de ranking no valido.")
        limit = _api_limite(request.args.get("limit"), default=100, maximo=500)
        data = _analitica_clientas_api(
            filtros=filtros,
            incluir_favoritos=False,
            incluir_graficas=False,
        )
        ranking = _ranking_clientas_api(data["clientes"], orden)
        return jsonify({
            "ok": True,
            "resumen": data["resumen"],
            "ranking": [_fila_ranking_clienta_api(fila) for fila in ranking[:limit]],
            "total": len(ranking),
            "limit": limit,
            "orden": orden,
            "filtros": data["filtros"],
        })
    except Exception as exc:
        return _respuesta_error_analytics_clientas_api(exc, "consultar el ranking de clientas")


@app.route("/api/clientes/analytics/graficas", methods=["GET"])
def api_clientes_analytics_graficas():
    _, error = _require_license_api()
    if error:
        return error
    try:
        filtros = _filtros_analytics_clientas_api(request.args)
        data = _analitica_clientas_api(
            filtros=filtros,
            incluir_favoritos=False,
            incluir_graficas=True,
        )
        return jsonify({"ok": True, "graficas": data["graficas"], "filtros": data["filtros"]})
    except Exception as exc:
        return _respuesta_error_analytics_clientas_api(exc, "consultar las graficas de clientas")


@app.route("/api/clientes/<int:cliente_id>/analytics", methods=["GET"])
def api_cliente_analytics(cliente_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        fila = _buscar_metricas_clienta_api(cliente_id, incluir_favoritos=True)
        fila["clienta"] = {
            "id": fila.get("cliente_id"),
            "nombre": fila.get("nombre"),
            "telefono": fila.get("telefono"),
            "direccion": fila.get("direccion") or {},
        }
        return jsonify({"ok": True, "analitica": fila})
    except Exception as exc:
        return _respuesta_error_analytics_clientas_api(exc, "consultar la ficha de clienta")


@app.route("/api/clientes/<int:cliente_id>/historial-compras", methods=["GET"])
def api_cliente_historial_compras(cliente_id):
    _, error = _require_license_api()
    if error:
        return error
    try:
        fila = _buscar_metricas_clienta_api(cliente_id, incluir_historial=True)
        historial = fila.get("historial_resumido", [])
        return jsonify({
            "ok": True,
            "cliente_id": fila.get("cliente_id"),
            "historial": historial,
            "total": len(historial),
        })
    except Exception as exc:
        return _respuesta_error_analytics_clientas_api(exc, "consultar el historial de compras")


# ================= CAMPANA DE NOTIFICACIONES =================
ESTADOS_NOTIFICACIONES_NOTAS = (
    "COTIZACION",
    "COTIZACION_PENDIENTE",
    "VENTA",
    "VENTA_PENDIENTE",
    "PAGADA",
    "EN_PROCESO",
    "INCOMPLETA",
    "COMPLETA",
    "ENVIADO",
    "ANULADA",
    "CANCELADA",
    "ELIMINADA",
    "ARCHIVADA",
)
CATEGORIAS_OPORTUNIDAD_NOTIFICACION = {
    "PROXIMA_COMPRA",
    "ATRASADA",
    "DORMIDA",
    "VIP_RECUPERAR",
    "RECURRENTE_ATRASADA",
}
ACCIONES_CONTROL_OPORTUNIDAD = {
    "RECORDAR_3": (3, False),
    "RECORDAR_7": (7, False),
    "OCULTAR_30": (30, True),
}


def _columna_select_notificaciones(alias, columna, columnas, nombre=None, default="NULL"):
    nombre = nombre or columna
    if columna not in columnas:
        return f"{default} AS {nombre}"
    return f"{alias}.{columna} AS {nombre}"


def _consultar_notas_notificaciones_api(conn):
    if not _tabla_existe_api(conn, "notas"):
        return []
    notas_cols = _columnas_tabla_api(conn, "notas")
    if not {"id", "estado"}.issubset(notas_cols):
        return []

    joins = []
    selects = ["n.*"]
    items_cols = _columnas_tabla_api(conn, "items") if _tabla_existe_api(conn, "items") else set()
    if {"nota_id", "cantidad"}.issubset(items_cols):
        empacadas_expr = "COALESCE(empacadas, 0)" if "empacadas" in items_cols else "0"
        joins.append(f"""
            LEFT JOIN (
                SELECT
                    nota_id,
                    COALESCE(SUM(COALESCE(cantidad, 0)), 0) AS piezas_totales,
                    COALESCE(SUM({empacadas_expr}), 0) AS piezas_empacadas
                FROM items
                GROUP BY nota_id
            ) ni ON ni.nota_id = n.id
        """)
        selects.extend((
            "COALESCE(ni.piezas_totales, 0) AS piezas_totales",
            "COALESCE(ni.piezas_empacadas, 0) AS piezas_empacadas",
        ))
    else:
        selects.extend(("0 AS piezas_totales", "0 AS piezas_empacadas"))

    empacadores_cols = (
        _columnas_tabla_api(conn, "empacadores")
        if _tabla_existe_api(conn, "empacadores")
        else set()
    )
    if "empacador_id" in notas_cols and {"id", "nombre"}.issubset(empacadores_cols):
        joins.append("LEFT JOIN empacadores ne ON ne.id = n.empacador_id")
        selects.append("ne.nombre AS empacador_nombre")
    else:
        selects.append("NULL AS empacador_nombre")

    clientes_cols = (
        _columnas_tabla_api(conn, "clientes")
        if _tabla_existe_api(conn, "clientes")
        else set()
    )
    if "cliente_id" in notas_cols and {"id", "nombre"}.issubset(clientes_cols):
        joins.append("LEFT JOIN clientes nc ON nc.id = n.cliente_id")
        selects.append("nc.nombre AS cliente_tabla_nombre")
        selects.append(_columna_select_notificaciones("nc", "telefono", clientes_cols, "telefono_cliente"))
    else:
        selects.extend(("NULL AS cliente_tabla_nombre", "NULL AS telefono_cliente"))

    placeholders = ", ".join(["%s"] * len(ESTADOS_NOTIFICACIONES_NOTAS))
    orden = "n.fecha DESC NULLS LAST, n.id DESC" if "fecha" in notas_cols else "n.id DESC"
    rows = conn.execute(
        f"""
        SELECT {', '.join(selects)}
        FROM notas n
        {' '.join(joins)}
        WHERE UPPER(COALESCE(CAST(n.estado AS TEXT), '')) IN ({placeholders})
        ORDER BY {orden}
        """,
        ESTADOS_NOTIFICACIONES_NOTAS,
    ).fetchall()
    notas = []
    for row in rows:
        nota = _normalizar_nota_api(row)
        if not nota:
            continue
        if not nota.get("cliente_nombre"):
            nota["cliente_nombre"] = nota.get("cliente_tabla_nombre") or nota.get("cliente")
        notas.append(nota)
    return notas


def _consultar_impresiones_notificaciones_api(conn):
    if not _tabla_existe_api(conn, "cola_impresion") or not _tabla_existe_api(conn, "notas"):
        return []
    cola_cols = _columnas_tabla_api(conn, "cola_impresion")
    notas_cols = _columnas_tabla_api(conn, "notas")
    if not {"nota_id", "estado"}.issubset(cola_cols) or "id" not in notas_cols:
        return []

    selects = [
        "ci.*",
        _columna_select_notificaciones("n", "estado", notas_cols, "estado_nota"),
        _columna_select_notificaciones("n", "cliente_id", notas_cols, "cliente_id"),
        _columna_select_notificaciones("n", "cliente_nombre", notas_cols, "cliente_nombre"),
    ]
    rows = conn.execute(f"""
        SELECT {', '.join(selects)}
        FROM cola_impresion ci
        LEFT JOIN notas n ON n.id = ci.nota_id
        WHERE UPPER(COALESCE(CAST(ci.estado AS TEXT), '')) IN ('PENDIENTE', 'FALLIDA')
        ORDER BY {_columna_orden_notificaciones(cola_cols, ('actualizado_en', 'creado_en', 'fecha', 'id'), 'ci')} DESC NULLS LAST
        LIMIT 200
    """).fetchall()
    return [_row_dict(row) for row in rows]


def _columna_orden_notificaciones(columnas, candidatas, alias):
    for columna in candidatas:
        if columna in columnas:
            return f"{alias}.{columna}"
    return "1"


def _consultar_errores_scan_notificaciones_api(conn):
    if not _tabla_existe_api(conn, "errores_scan"):
        return []
    errores_cols = _columnas_tabla_api(conn, "errores_scan")
    if "nota_id" not in errores_cols:
        return []
    notas_cols = _columnas_tabla_api(conn, "notas") if _tabla_existe_api(conn, "notas") else set()
    emp_cols = _columnas_tabla_api(conn, "empacadores") if _tabla_existe_api(conn, "empacadores") else set()
    joins = []
    selects = ["er.*"]
    where = []
    if "id" in notas_cols:
        joins.append("LEFT JOIN notas en ON en.id = er.nota_id")
        selects.append(_columna_select_notificaciones("en", "estado", notas_cols, "estado_nota"))
        if "estado" in notas_cols:
            where.append("UPPER(COALESCE(CAST(en.estado AS TEXT), '')) IN ('PAGADA','EN_PROCESO','INCOMPLETA')")
    else:
        selects.append("NULL AS estado_nota")
    if "empacador_id" in errores_cols and {"id", "nombre"}.issubset(emp_cols):
        joins.append("LEFT JOIN empacadores ee ON ee.id = er.empacador_id")
        selects.append("ee.nombre AS empacador")
    else:
        selects.append("NULL AS empacador")
    if "resuelto" in errores_cols:
        where.append("COALESCE(er.resuelto, FALSE)=FALSE")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    orden = _columna_orden_notificaciones(errores_cols, ("fecha", "id"), "er")
    rows = conn.execute(f"""
        SELECT {', '.join(selects)}
        FROM errores_scan er
        {' '.join(joins)}
        {where_sql}
        ORDER BY {orden} DESC NULLS LAST
        LIMIT 100
    """).fetchall()
    return [_row_dict(row) for row in rows]


def _consultar_productos_notificaciones_api(conn):
    if not _tabla_existe_api(conn, "productos"):
        return []
    columnas = _columnas_tabla_api(conn, "productos")
    if not {"id", "estado"}.issubset(columnas):
        return []
    inventariable = _producto_inventariable_where_api(columnas, "p")
    rows = conn.execute(f"""
        SELECT p.*
        FROM productos p
        WHERE UPPER(COALESCE(CAST(p.estado AS TEXT), '')) IN ('RESURTIR','SIN STOCK','STOCK BAJO')
          AND {inventariable}
        ORDER BY UPPER(COALESCE(CAST(p.estado AS TEXT), '')), p.id
        LIMIT 500
    """).fetchall()
    return [_row_dict(row) for row in rows]


def _consultar_controles_notificaciones_api(conn):
    if not _tabla_existe_api(conn, "notificaciones_oportunidades_control"):
        return []
    columnas = _columnas_tabla_api(conn, "notificaciones_oportunidades_control")
    requeridas = {"cliente_id", "categoria", "pospuesto_hasta", "oculto_hasta"}
    if not requeridas.issubset(columnas):
        return []
    rows = conn.execute("""
        SELECT cliente_id, categoria, pospuesto_hasta, oculto_hasta, fecha_accion, usuario
        FROM notificaciones_oportunidades_control
        WHERE pospuesto_hasta > NOW() OR oculto_hasta > NOW()
    """).fetchall()
    return [_row_dict(row) for row in rows]


def _cliente_ids_con_pendiente_notificaciones(notas):
    estados = {"COTIZACION", "COTIZACION_PENDIENTE", "VENTA", "VENTA_PENDIENTE"}
    return {
        nota.get("cliente_id")
        for nota in notas
        if nota.get("cliente_id") is not None
        and _normalizar_estado_pago_api(nota.get("estado")) in estados
    }


def _construir_resumen_notificaciones_api(incluir_oportunidades=True):
    with get_conn() as conn:
        notas = _consultar_notas_notificaciones_api(conn)
        operacion = construir_notificaciones_operacion(
            notas,
            impresiones=_consultar_impresiones_notificaciones_api(conn),
            errores_scan=_consultar_errores_scan_notificaciones_api(conn),
            productos=_consultar_productos_notificaciones_api(conn),
        )
        oportunidades = []
        if incluir_oportunidades:
            clientes = _consultar_clientes_crm_api(conn)
            analitica = _analitica_clientas_conn_api(
                conn,
                incluir_historial=False,
                incluir_favoritos=True,
                incluir_graficas=False,
            )
            oportunidades = construir_oportunidades_venta(
                analitica.get("clientes", []),
                clientes=clientes,
                cliente_ids_con_pendiente=_cliente_ids_con_pendiente_notificaciones(notas),
                controles=_consultar_controles_notificaciones_api(conn),
            )
    return construir_resumen_notificaciones(
        operacion,
        oportunidades,
        oportunidades_actualizadas=incluir_oportunidades,
    )


def _bool_notificaciones(valor, default=True):
    if valor in (None, ""):
        return default
    return str(valor).strip().lower() not in {"0", "false", "no"}


@app.route("/api/notificaciones/resumen", methods=["GET"])
def api_notificaciones_resumen():
    _, error = _require_license_api()
    if error:
        return error
    try:
        incluir_oportunidades = _bool_notificaciones(request.args.get("incluir_oportunidades"), True)
        return jsonify(_construir_resumen_notificaciones_api(incluir_oportunidades))
    except Exception:
        app.logger.exception("Error al consultar la campana de notificaciones")
        return jsonify({
            "ok": False,
            "error": "No se pudieron actualizar las notificaciones.",
        }), 500


@app.route("/api/notificaciones/oportunidades/<int:cliente_id>/control", methods=["POST"])
def api_notificaciones_oportunidad_control(cliente_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        categoria = _normalizar_estado_pago_api(data.get("categoria"))
        accion = _normalizar_estado_pago_api(data.get("accion"))
        if categoria not in CATEGORIAS_OPORTUNIDAD_NOTIFICACION:
            raise ValueError("Tipo de oportunidad no válido.")
        if accion not in ACCIONES_CONTROL_OPORTUNIDAD:
            raise ValueError("Acción de oportunidad no válida.")
        dias, ocultar = ACCIONES_CONTROL_OPORTUNIDAD[accion]
        ahora = datetime.now(timezone.utc)
        vigencia = ahora + timedelta(days=dias)
        pospuesto_hasta = None if ocultar else vigencia
        oculto_hasta = vigencia if ocultar else None
        usuario = _usuario_auth_api(auth)

        with get_conn() as conn:
            if not _tabla_existe_api(conn, "notificaciones_oportunidades_control"):
                return jsonify({
                    "ok": False,
                    "error": "Falta aplicar la migración de control de oportunidades.",
                }), 409
            cliente = conn.execute("SELECT id FROM clientes WHERE id=%s", (cliente_id,)).fetchone()
            if not cliente:
                raise LookupError("Cliente no encontrado.")
            row = conn.execute("""
                INSERT INTO notificaciones_oportunidades_control (
                    cliente_id,
                    categoria,
                    pospuesto_hasta,
                    oculto_hasta,
                    fecha_accion,
                    usuario
                )
                VALUES (%s, %s, %s, %s, NOW(), %s)
                ON CONFLICT (cliente_id, categoria)
                DO UPDATE SET
                    pospuesto_hasta=EXCLUDED.pospuesto_hasta,
                    oculto_hasta=EXCLUDED.oculto_hasta,
                    fecha_accion=NOW(),
                    usuario=EXCLUDED.usuario
                RETURNING cliente_id, categoria, pospuesto_hasta, oculto_hasta, fecha_accion
            """, (cliente_id, categoria, pospuesto_hasta, oculto_hasta, usuario)).fetchone()
        return jsonify({"ok": True, "control": _row_dict(row)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al guardar control de oportunidad")
        return jsonify({
            "ok": False,
            "error": "No se pudo guardar el recordatorio de la oportunidad.",
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
    auth, error = _require_license_api()
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
            _registrar_auditoria_general_api(
                conn,
                auth,
                "COTIZACION_CREADA",
                "ventas",
                entidad_tipo="nota",
                entidad_id=nota_id,
                descripcion=f"Cotizacion creada con {len(items)} producto(s).",
                datos_nuevos={
                    "cliente_id": cliente_id,
                    "estado": "COTIZACION",
                    "subtotal_productos": total,
                    "items": len(items),
                },
            )

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
    auth, error = _require_license_api()
    if error:
        return error
    try:
        data = _body_json()
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id)
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
                antes, despues = _diferencias_auditoria(actual, cambios, campos=tuple(cambios))
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "COTIZACION_MODIFICADA",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Cotizacion actualizada.",
                    datos_anteriores=antes,
                    datos_nuevos=despues,
                )

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


@app.route("/api/notas/<string:nota_id>/admin", methods=["PATCH"])
def api_notas_actualizar_admin(nota_id):
    auth, error = _require_license_api()
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
                antes, despues = _diferencias_auditoria(actual, cambios, campos=tuple(cambios))
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "NOTA_EDITADA_ADMIN",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Datos administrativos de nota actualizados.",
                    datos_anteriores=antes,
                    datos_nuevos=despues,
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
            _registrar_auditoria_general_api(
                conn,
                auth,
                "NOTA_PAGADA_AJUSTADA",
                "ventas",
                entidad_tipo="nota",
                entidad_id=nota_id_real,
                descripcion=motivo,
                datos_anteriores={"subtotal": subtotal_anterior, "total_final": total_anterior_final},
                datos_nuevos={"subtotal": subtotal_nuevo, "total_final": total_nuevo_final, "movimientos": len(movimientos)},
                resultado="AUTORIZADO",
            )

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
            _registrar_auditoria_general_api(
                conn,
                auth,
                "COTIZACION_CONVERTIDA_A_VENTA",
                "ventas",
                entidad_tipo="nota",
                entidad_id=nota_id_real,
                descripcion="Cotizacion convertida a venta pendiente de pago.",
                datos_anteriores={"estado": actual.get("estado")},
                datos_nuevos={"estado": "VENTA_PENDIENTE", "subtotal_productos": total},
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
    auth, error = _require_license_api()
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
            items_anteriores = _items_actuales_nota_api(conn, nota_id_real, bloquear=False)
            notas_cols = _columnas_tabla_api(conn, "notas")
            conn.execute("DELETE FROM items WHERE nota_id=%s", (nota_id_real,))
            _insertar_items_nota_api(conn, nota_id_real, items)
            if "total" in notas_cols:
                conn.execute("UPDATE notas SET total=%s WHERE id=%s", (total, nota_id_real))
            _registrar_auditoria_general_api(
                conn,
                auth,
                "COTIZACION_ITEMS_MODIFICADOS",
                "ventas",
                entidad_tipo="nota",
                entidad_id=nota_id_real,
                descripcion="Productos de cotizacion actualizados.",
                datos_anteriores={"items": len(items_anteriores), "subtotal": actual.get("total")},
                datos_nuevos={"items": len(items), "subtotal": total},
            )

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
        pago_idempotente = False
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id, bloquear=True)
            _rechazar_pago_nota_anulada_api(actual)
            if _nota_pago_ya_aplicado_api(conn, actual):
                pago_idempotente = True
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "PAGO_REPETIDO",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Solicitud de pago repetida; no se descontó stock nuevamente.",
                    resultado="IDEMPOTENTE",
                )
            else:
                _validar_nota_pagable_api(conn, actual)
                movimientos = _descontar_stock_nota_api(
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
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "PAGO_REGISTRADO",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Venta marcada como pagada y stock descontado.",
                    datos_anteriores={"estado": actual.get("estado"), "fecha_pago": actual.get("fecha_pago")},
                    datos_nuevos={"estado": "PAGADA", "fecha_pago": fecha_pago, "movimientos": len(movimientos)},
                )

        nota = _nota_con_detalle_api(nota_id_real)
        nota["pagos"] = _pagos_nota_api(nota_id_real)
        return jsonify({"ok": True, "nota": nota, "idempotente": pago_idempotente})
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


def _cancelar_impresiones_pendientes_nota_api(conn, nota_id):
    columnas = _columnas_tabla_api(conn, "cola_impresion")
    if not {"nota_id", "estado"}.issubset(columnas):
        return 0
    filas = conn.execute(
        """
        UPDATE cola_impresion
        SET estado='CANCELADA'
        WHERE nota_id=%s AND estado='PENDIENTE'
        RETURNING nota_id
        """,
        (nota_id,),
    ).fetchall()
    return len(filas or [])


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
            if estado == "ARCHIVADA":
                raise NotaPagoNoPermitido("Una nota ARCHIVADA es terminal y no puede anularse.", 409)
            ya_anulada = estado in {"ANULADA", "CANCELADA", "ELIMINADA"}
            productos_devueltos = []
            requiere_devolver_stock = _nota_requiere_devolucion_stock_api(conn, actual, auth)
            if requiere_devolver_stock:
                if not _clave_stock_autorizada_api(data):
                    raise NotaPagoNoPermitido(
                        "Esta nota ya fue pagada. Para anularla y regresar stock se requiere autorizacion.",
                        409,
                )
                productos_devueltos = _devolver_stock_nota_api(conn, nota_id_real, auth)

            notas_cols = _columnas_tabla_api(conn, "notas")
            cambios = {}
            if not ya_anulada and "estado" in notas_cols:
                cambios["estado"] = "ANULADA"
            if cambios:
                sets = ", ".join(f"{campo}=%s" for campo in cambios)
                conn.execute(
                    f"UPDATE notas SET {sets} WHERE id=%s",
                    tuple(cambios.values()) + (nota_id_real,),
                )
            tareas_impresion_canceladas = _cancelar_impresiones_pendientes_nota_api(conn, nota_id_real)

            idempotente = ya_anulada and not productos_devueltos
            if not idempotente:
                detalle = (
                    f"Nota {'reparada' if ya_anulada else 'anulada'} por {_usuario_auth_api(auth)}. "
                    f"Stock devuelto: {len(productos_devueltos)} producto(s)."
                )
                _registrar_anulacion_nota_api(conn, nota_id_real, detalle)
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "VENTA_ANULADA",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion=detalle,
                    datos_anteriores={"estado": actual.get("estado"), "fecha_pago": actual.get("fecha_pago")},
                    datos_nuevos={
                        "estado": "ANULADA",
                        "productos_reintegrados": len(productos_devueltos),
                        "impresiones_canceladas": tareas_impresion_canceladas,
                    },
                )

        nota = _nota_con_detalle_api(nota_id_real)
        return jsonify({
            "ok": True,
            "nota": nota,
            "productos_devueltos": productos_devueltos,
            "stock_devuelto": bool(productos_devueltos),
            "impresiones_canceladas": tareas_impresion_canceladas,
            "idempotente": idempotente,
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
        pago_idempotente = False
        with get_conn() as conn:
            nota_id_real, actual = _resolver_nota_api(conn, nota_id, bloquear=True)
            _rechazar_pago_nota_anulada_api(actual)
            if _nota_pago_ya_aplicado_api(conn, actual):
                pago_idempotente = True
                pagos_existentes = _pagos_nota_api_conn(conn, nota_id_real)
                pago = pagos_existentes[-1] if pagos_existentes else None
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "PAGO_REPETIDO",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Solicitud de pago repetida; no se descontó stock nuevamente.",
                    resultado="IDEMPOTENTE",
                )
            else:
                _validar_nota_pagable_api(conn, actual)
                movimientos = _descontar_stock_nota_api(
                    conn,
                    nota_id_real,
                    auth,
                    autorizacion_stock=_clave_stock_autorizada_api(data),
                )
                notas_cols = _columnas_tabla_api(conn, "notas")
                cambios = {}
                fecha_pago = datetime.now().isoformat(timespec="seconds")
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
                pago = _insertar_pago_api(conn, nota_id_real, comprobante)
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "PAGO_REGISTRADO",
                    "ventas",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Pago registrado y stock descontado.",
                    datos_anteriores={"estado": actual.get("estado"), "fecha_pago": actual.get("fecha_pago")},
                    datos_nuevos={"estado": "PAGADA", "fecha_pago": fecha_pago, "movimientos": len(movimientos)},
                )
        return jsonify({"ok": True, "pago": _row_dict(pago) if pago else None, "idempotente": pago_idempotente})
    except Exception as exc:
        return _respuesta_error_nota_api(exc)


def _estado_envio_filtro_api(valor):
    clave = str(valor or "").strip().upper().replace(" ", "_")
    clave = clave.replace("Í", "I").replace("Á", "A")
    mapa = {
        "COMPLETAS": "COMPLETA",
        "COMPLETA": "COMPLETA",
        "EN_PROCESO": "EN_PROCESO",
        "INCOMPLETAS": "INCOMPLETA",
        "INCOMPLETA": "INCOMPLETA",
        "PAGADA": "PAGADA",
    }
    return mapa.get(clave, clave if clave else "")


def _normalizar_filtro_panel_envios_api(valor):
    clave = str(valor or "").strip().upper().replace(" ", "_")
    clave = clave.replace("Í", "I").replace("Á", "A")
    aliases = {
        "PENDIENTES_DE_GUIA": "PENDIENTES_GUIA",
        "PENDIENTES_GUIA": "PENDIENTES_GUIA",
        "LISTAS_PARA_ENVIAR": "LISTAS_ENVIAR",
        "LISTOS_PARA_ENVIAR": "LISTAS_ENVIAR",
        "LISTAS_ENVIAR": "LISTAS_ENVIAR",
        "ENVIADOS": "ENVIADAS",
        "ENVIADAS": "ENVIADAS",
        "TODAS": "TODAS",
    }
    return aliases.get(clave, clave)


def _normalizar_envio_nota_api(row):
    data = _row_dict(row) or {}
    envio = _json_field(data.get("envio"), {})
    if not isinstance(envio, dict):
        envio = {}
    paqueteria = data.get("paqueteria") or _paqueteria_envio_api(envio)
    costo_envio = data.get("costo_envio")
    if costo_envio is None:
        costo_envio = envio.get("precio")
    tipo_entrega = envio.get("tipo") or envio.get("metodo") or paqueteria or ""
    observaciones = (
        data.get("observaciones_envio")
        or data.get("observaciones")
        or data.get("notas")
        or ""
    )
    normalizada = {
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
        "fecha_guia": data.get("fecha_guia"),
        "fecha_envio": data.get("fecha_envio"),
        "observaciones_envio": data.get("observaciones_envio"),
        "observaciones": observaciones,
        "tipo_entrega": tipo_entrega,
        "empacador": data.get("empacador_nombre"),
        "articulos": int(data.get("articulos") or 0),
        "piezas": _float_api(data.get("piezas"), default=0.0),
        "fecha": data.get("fecha"),
    }
    normalizada["requiere_guia"] = bool(_requiere_guia_notificaciones(normalizada))
    return normalizada


def _envio_coincide_filtro_api(envio, filtro):
    filtro = _normalizar_filtro_panel_envios_api(filtro)
    estado = _normalizar_estado_pago_api((envio or {}).get("estado"))
    tiene_guia = bool(_guia_nota_notificaciones(envio or {}))
    requiere_guia = bool((envio or {}).get("requiere_guia", True))
    if filtro == "PENDIENTES_GUIA":
        return estado == "COMPLETA" and requiere_guia and not tiene_guia
    if filtro == "LISTAS_ENVIAR":
        return estado == "COMPLETA" and (tiene_guia or not requiere_guia)
    if filtro == "ENVIADAS":
        return estado == "ENVIADO"
    if filtro == "TODAS":
        return estado in {"COMPLETA", "ENVIADO"}
    return True


def _select_envios_notas_api(conn):
    notas_cols = _columnas_tabla_api(conn, "notas")
    clientes_cols = _columnas_tabla_api(conn, "clientes")
    if not notas_cols or "id" not in notas_cols:
        raise LookupError("No existe la tabla notas o falta id.")
    joins = []
    selects = [
        "n.id AS id",
        "n.cliente_nombre AS cliente_nombre" if "cliente_nombre" in notas_cols else "NULL AS cliente_nombre",
        "n.cliente AS cliente" if "cliente" in notas_cols else "NULL AS cliente",
        "n.pedido AS pedido" if "pedido" in notas_cols else "NULL AS pedido",
        "n.estado AS estado" if "estado" in notas_cols else "NULL AS estado",
        "n.total AS total" if "total" in notas_cols else "NULL AS total",
        "n.envio AS envio" if "envio" in notas_cols else "NULL AS envio",
        "n.paqueteria AS paqueteria" if "paqueteria" in notas_cols else "NULL AS paqueteria",
        "n.guia AS guia" if "guia" in notas_cols else "NULL AS guia",
        "n.fecha AS fecha" if "fecha" in notas_cols else "NULL AS fecha",
        "n.costo_envio AS costo_envio" if "costo_envio" in notas_cols else "NULL AS costo_envio",
        "n.estado_envio AS estado_envio" if "estado_envio" in notas_cols else "NULL AS estado_envio",
        "n.fecha_guia AS fecha_guia" if "fecha_guia" in notas_cols else "NULL AS fecha_guia",
        "n.fecha_envio AS fecha_envio" if "fecha_envio" in notas_cols else "NULL AS fecha_envio",
        "n.observaciones_envio AS observaciones_envio" if "observaciones_envio" in notas_cols else "NULL AS observaciones_envio",
        "n.observaciones AS observaciones" if "observaciones" in notas_cols else "NULL AS observaciones",
        "n.notas AS notas" if "notas" in notas_cols else "NULL AS notas",
        "c.telefono AS telefono" if {"cliente_id"}.issubset(notas_cols) and {"id", "telefono"}.issubset(clientes_cols) else "NULL AS telefono",
        "c.direccion AS direccion" if {"cliente_id"}.issubset(notas_cols) and {"id", "direccion"}.issubset(clientes_cols) else "NULL AS direccion",
    ]
    if "cliente_id" in notas_cols and "id" in clientes_cols:
        joins.append("LEFT JOIN clientes c ON c.id = n.cliente_id")

    items_cols = _columnas_tabla_api(conn, "items") if _tabla_existe_api(conn, "items") else set()
    if {"nota_id", "cantidad"}.issubset(items_cols):
        joins.append("""
            LEFT JOIN (
                SELECT nota_id, COUNT(*) AS articulos,
                       COALESCE(SUM(COALESCE(cantidad, 0)), 0) AS piezas
                FROM items
                GROUP BY nota_id
            ) ei ON ei.nota_id = n.id
        """)
        selects.extend(("COALESCE(ei.articulos, 0) AS articulos", "COALESCE(ei.piezas, 0) AS piezas"))
    else:
        selects.extend(("0 AS articulos", "0 AS piezas"))

    empacadores_cols = (
        _columnas_tabla_api(conn, "empacadores")
        if _tabla_existe_api(conn, "empacadores")
        else set()
    )
    if "empacador_id" in notas_cols and {"id", "nombre"}.issubset(empacadores_cols):
        joins.append("LEFT JOIN empacadores ee ON ee.id = n.empacador_id")
        selects.append("ee.nombre AS empacador_nombre")
    else:
        selects.append("NULL AS empacador_nombre")
    return ", ".join(selects), "\n".join(joins), notas_cols


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
            if "estado" in notas_cols:
                filtros.append("""
                    UPPER(COALESCE(n.estado, '')) NOT IN (
                        'COTIZACION','COTIZACION_PENDIENTE','VENTA','VENTA_PENDIENTE',
                        'ANULADA','CANCELADA','ELIMINADA','ARCHIVADA'
                    )
                """)
            estado_solicitado = str(request.args.get("estado") or "").strip().upper()
            filtro_panel = _normalizar_filtro_panel_envios_api(estado_solicitado)
            estado = _estado_envio_filtro_api(estado_solicitado)
            if filtro_panel in {"PENDIENTES_GUIA", "LISTAS_ENVIAR"} and "estado" in notas_cols:
                filtros.append("UPPER(COALESCE(n.estado, ''))='COMPLETA'")
            elif filtro_panel == "ENVIADAS" and "estado" in notas_cols:
                filtros.append("UPPER(COALESCE(n.estado, ''))='ENVIADO'")
            elif filtro_panel == "TODAS" and "estado" in notas_cols:
                filtros.append("UPPER(COALESCE(n.estado, '')) IN ('COMPLETA','ENVIADO')")
            elif estado_solicitado == "TODAS_PAGADAS" and "estado" in notas_cols:
                filtros.append(
                    "UPPER(COALESCE(n.estado, '')) IN "
                    "('PAGADA','EN_PROCESO','INCOMPLETA','COMPLETA')"
                )
            elif estado in {"PAGADA", "EN_PROCESO", "INCOMPLETA", "COMPLETA"} and "estado" in notas_cols:
                filtros.append("n.estado=%s")
                valores.append(estado)
            elif "estado" in notas_cols:
                filtros.append(
                    "UPPER(COALESCE(n.estado, '')) IN "
                    "('PAGADA','EN_PROCESO','INCOMPLETA','COMPLETA')"
                )
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
            order_col = "fecha" if "fecha" in notas_cols else "id"
            limite_candidatos = min(max(limit + offset, 500), 5000)
            rows = conn.execute(
                f"""
                SELECT {selects}
                FROM notas n
                {join}
                {where_sql}
                ORDER BY n.{order_col} DESC NULLS LAST
                LIMIT %s
                """,
                tuple(valores + [limite_candidatos]),
            ).fetchall()
        envios = [_normalizar_envio_nota_api(row) for row in rows]
        if filtro_panel in {"PENDIENTES_GUIA", "LISTAS_ENVIAR", "ENVIADAS", "TODAS"}:
            envios = [envio for envio in envios if _envio_coincide_filtro_api(envio, filtro_panel)]
        total = len(envios)
        envios = envios[offset:offset + limit]
        return jsonify({"ok": True, "envios": envios, "total": total, "filtro": filtro_panel})
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
            estado_actual = _normalizar_estado_pago_api(nota.get("estado"))
            if estado_actual in ESTADOS_NOTA_ANULADA_API | {"ARCHIVADA"}:
                raise NotaPagoNoPermitido("Una nota terminal no puede volver a la cola de envios.", 409)
            if "guia" in data and estado_actual != "COMPLETA":
                raise NotaPagoNoPermitido("Solo una nota COMPLETA puede recibir una guia.", 409)
            if _normalizar_estado_pago_api(data.get("estado_envio")) == "ENVIADO" or "fecha_envio" in data:
                raise NotaPagoNoPermitido(
                    "Usa la accion Marcar como enviado para confirmar la entrega a paqueteria.",
                    409,
                )
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
    except NotaPagoNoPermitido as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al actualizar envio")
        return jsonify({"ok": False, "error": "No se pudo actualizar el envio."}), 500


def _marcar_nota_enviada_api_conn(conn, nota_id):
    nota_id_real, nota = _resolver_nota_api(conn, nota_id, bloquear=True)
    estado_actual = _normalizar_estado_pago_api(nota.get("estado"))
    if estado_actual == "ENVIADO":
        return nota_id_real, nota, True, "fecha_envio" in _columnas_tabla_api(conn, "notas")
    if estado_actual != "COMPLETA":
        raise NotaPagoNoPermitido("Solo una nota COMPLETA puede marcarse como enviada.", 409)
    nota_regla = dict(nota)
    nota_regla["envio"] = _json_field(nota_regla.get("envio"), {})
    guia = str(nota.get("guia") or _guia_nota_notificaciones(nota_regla) or "").strip()
    if _requiere_guia_notificaciones(nota_regla) and not guia:
        raise NotaPagoNoPermitido("Guarda la guia antes de marcar el envio.", 409)

    notas_cols = _columnas_tabla_api(conn, "notas")
    campos = ["estado='ENVIADO'"]
    if "estado_envio" in notas_cols:
        campos.append("estado_envio='ENVIADO'")
    fecha_envio_disponible = "fecha_envio" in notas_cols
    if fecha_envio_disponible:
        campos.append("fecha_envio=COALESCE(fecha_envio, NOW())")
    conn.execute(
        f"UPDATE notas SET {', '.join(campos)} WHERE id=%s",
        (nota_id_real,),
    )
    actualizada = conn.execute("SELECT * FROM notas WHERE id=%s", (nota_id_real,)).fetchone()
    return nota_id_real, _row_dict(actualizada) or {}, False, fecha_envio_disponible


@app.route("/api/envios/notas/<string:nota_id>/marcar-enviado", methods=["POST"])
def api_envios_nota_marcar_enviado(nota_id):
    auth, error = _require_license_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            nota_id_real, nota, idempotente, fecha_disponible = _marcar_nota_enviada_api_conn(conn, nota_id)
            if not idempotente:
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "ENVIO_MARCADO_ENVIADO",
                    "envios",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Paquete marcado como entregado a paqueteria.",
                    datos_anteriores={"estado": "COMPLETA"},
                    datos_nuevos={"estado": "ENVIADO", "fecha_envio_guardada": fecha_disponible},
                )
        return jsonify({
            "ok": True,
            "nota_id": nota_id_real,
            "estado": nota.get("estado") or "ENVIADO",
            "fecha_envio": nota.get("fecha_envio"),
            "fecha_envio_guardada": fecha_disponible,
            "idempotente": idempotente,
        })
    except Exception as exc:
        return _respuesta_error_nota_api(exc, accion="marcar como enviada")


def _procesar_envios_lote_api_conn(conn, nota_ids, auth):
    resultados = []
    procesados = 0
    for indice, nota_id in enumerate(nota_ids):
        savepoint = f"envio_lote_{indice}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            nota_id_real, nota, idempotente, fecha_disponible = _marcar_nota_enviada_api_conn(
                conn,
                nota_id,
            )
            if idempotente:
                resultados.append({
                    "nota_id": nota_id_real,
                    "ok": False,
                    "estado": "ENVIADO",
                    "error": "La nota ya estaba enviada.",
                    "idempotente": True,
                })
            else:
                _registrar_auditoria_general_api(
                    conn,
                    auth,
                    "ENVIO_MARCADO_ENVIADO",
                    "envios",
                    entidad_tipo="nota",
                    entidad_id=nota_id_real,
                    descripcion="Paquete marcado como entregado a paqueteria por lote.",
                    datos_anteriores={"estado": "COMPLETA"},
                    datos_nuevos={
                        "estado": "ENVIADO",
                        "fecha_envio_guardada": fecha_disponible,
                    },
                )
                procesados += 1
                resultados.append({
                    "nota_id": nota_id_real,
                    "ok": True,
                    "estado": "ENVIADO",
                    "fecha_envio": nota.get("fecha_envio"),
                    "fecha_envio_guardada": fecha_disponible,
                    "guia": nota.get("guia"),
                    "paqueteria": nota.get("paqueteria"),
                })
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except (NotaPagoNoPermitido, LookupError, ValueError) as exc:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            resultados.append({
                "nota_id": nota_id,
                "ok": False,
                "error": str(exc),
            })
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            app.logger.exception("Error al marcar envio individual dentro de lote")
            resultados.append({
                "nota_id": nota_id,
                "ok": False,
                "error": "No se pudo actualizar esta nota.",
            })
    return {
        "ok": True,
        "procesados": procesados,
        "omitidos": len(resultados) - procesados,
        "resultados": resultados,
    }


@app.route("/api/envios/notas/marcar-enviadas", methods=["POST"])
def api_envios_notas_marcar_enviadas():
    auth, error = _require_license_api()
    if error:
        return error
    data = _body_json()
    nota_ids = data.get("nota_ids")
    if not isinstance(nota_ids, list) or not nota_ids:
        return jsonify({"ok": False, "error": "Selecciona al menos una nota."}), 400
    if len(nota_ids) > 100:
        return jsonify({"ok": False, "error": "Solo se permiten 100 notas por lote."}), 400

    ids_limpios = []
    vistos = set()
    for nota_id in nota_ids:
        if isinstance(nota_id, (dict, list)) or nota_id is None:
            return jsonify({"ok": False, "error": "La lista contiene un identificador invalido."}), 400
        clave = str(nota_id).strip()
        if not clave:
            return jsonify({"ok": False, "error": "La lista contiene un identificador vacio."}), 400
        if clave not in vistos:
            vistos.add(clave)
            ids_limpios.append(clave)

    try:
        with get_conn() as conn:
            resultado = _procesar_envios_lote_api_conn(conn, ids_limpios, auth)
        return jsonify(resultado)
    except Exception:
        app.logger.exception("Error al marcar envios por lote")
        return jsonify({"ok": False, "error": "No se pudieron procesar los envios."}), 500


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
                    COUNT(*) FILTER (
                        WHERE estado IN ('PAGADA','EN_PROCESO','INCOMPLETA','COMPLETA','ENVIADO','VENTA_PAGADA')
                    ) AS ventas_pagadas,
                    COUNT(*) FILTER (WHERE estado IN ('VENTA','VENTA_PENDIENTE')) AS ventas_pendientes
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
        _registrar_auditoria_general_api(
            conn,
            auth,
            "CLIENTE_SISTEMA_CREADO",
            "administracion",
            entidad_tipo="cliente_sistema",
            entidad_id=row["id"],
            descripcion="Cliente de sistema creado.",
            datos_nuevos={
                "nombre_negocio": data.get("nombre_negocio"),
                "estado": data.get("estado") or "activo",
                "plan": data.get("plan"),
            },
        )
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
        anterior = conn.execute(
            "SELECT * FROM clientes_sistema WHERE id=%s",
            (cliente_id,),
        ).fetchone()
        if not anterior:
            return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404
        conn.execute(f"UPDATE clientes_sistema SET {', '.join(sets)}, updated_at=NOW() WHERE id=%s", tuple(params))
        antes, despues = _diferencias_auditoria(anterior, data, campos=tuple(sets_item.split("=")[0] for sets_item in sets))
        _registrar_auditoria_general_api(
            conn,
            auth,
            "CLIENTE_SISTEMA_EDITADO",
            "administracion",
            entidad_tipo="cliente_sistema",
            entidad_id=cliente_id,
            descripcion="Datos de cliente de sistema actualizados.",
            datos_anteriores=antes,
            datos_nuevos=despues,
        )
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
        anterior = conn.execute(
            "SELECT id, nombre_negocio, estado FROM clientes_sistema WHERE id=%s",
            (cliente_id,),
        ).fetchone()
        if not anterior:
            return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404
        conn.execute("UPDATE clientes_sistema SET estado=%s, updated_at=NOW() WHERE id=%s", (estado, cliente_id))
        if estado != "activo":
            conn.execute("""
                UPDATE sesiones_activas
                SET estado='bloqueada', updated_at=NOW()
                WHERE cliente_id=%s AND estado='activa'
            """, (cliente_id,))
        accion = {
            "suspendido": "CLIENTE_SUSPENDIDO",
            "bloqueado": "CLIENTE_BLOQUEADO",
            "activo": "CLIENTE_REACTIVADO",
        }.get(estado, "CLIENTE_ESTADO_ACTUALIZADO")
        _registrar_auditoria_general_api(
            conn,
            auth,
            accion,
            "administracion",
            entidad_tipo="cliente_sistema",
            entidad_id=cliente_id,
            descripcion=f"Estado del cliente actualizado a {estado}.",
            datos_anteriores={"estado": (anterior or {}).get("estado")},
            datos_nuevos={"estado": estado},
        )
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


def _select_auditoria_general_api(columnas):
    campos = []
    for columna in (
        "id", "cliente_sistema_id", "usuario_id", "accion", "modulo",
        "entidad_tipo", "entidad_id", "descripcion", "datos_anteriores_json",
        "datos_nuevos_json", "resultado", "codigo_error", "ip", "user_agent",
        "device_id", "request_id", "fecha_creacion",
    ):
        if columna in columnas:
            campos.append(f"a.{columna} AS {columna}")
        else:
            campos.append(f"NULL AS {columna}")
    campos.extend((
        "u.usuario AS usuario",
        "u.nombre AS usuario_nombre",
        "c.nombre_negocio AS nombre_negocio",
    ))
    return ", ".join(campos)


def _filtros_auditoria_general_api(columnas, args):
    filtros, valores = [], []

    def texto(parametro, columna):
        valor = str(args.get(parametro) or "").strip()
        if valor and columna in columnas:
            filtros.append(f"a.{columna} ILIKE %s")
            valores.append(f"%{valor}%")

    for parametro, columna in (
        ("modulo", "modulo"),
        ("accion", "accion"),
        ("resultado", "resultado"),
    ):
        texto(parametro, columna)
    cliente = str(args.get("cliente") or "").strip()
    if cliente:
        if cliente.isdigit() and "cliente_sistema_id" in columnas:
            filtros.append("a.cliente_sistema_id=%s")
            valores.append(int(cliente))
        else:
            filtros.append("c.nombre_negocio ILIKE %s")
            valores.append(f"%{cliente}%")
    entidad = str(args.get("entidad") or "").strip()
    if entidad:
        campos_entidad = [campo for campo in ("entidad_tipo", "entidad_id") if campo in columnas]
        if campos_entidad:
            filtros.append("(" + " OR ".join(f"a.{campo} ILIKE %s" for campo in campos_entidad) + ")")
            valores.extend([f"%{entidad}%"] * len(campos_entidad))
    usuario = str(args.get("usuario") or "").strip()
    if usuario:
        filtros.append("(u.usuario ILIKE %s OR u.nombre ILIKE %s)")
        valores.extend([f"%{usuario}%", f"%{usuario}%"])
    texto_busqueda = str(args.get("texto") or args.get("q") or "").strip()
    if texto_busqueda:
        campos = [campo for campo in ("accion", "modulo", "entidad_tipo", "entidad_id", "descripcion", "resultado") if campo in columnas]
        if campos:
            filtros.append("(" + " OR ".join(f"a.{campo} ILIKE %s" for campo in campos) + ")")
            valores.extend([f"%{texto_busqueda}%"] * len(campos))
    desde = str(args.get("desde") or args.get("fecha_inicial") or "").strip()
    if desde and "fecha_creacion" in columnas:
        filtros.append("a.fecha_creacion >= %s")
        valores.append(desde)
    hasta = str(args.get("hasta") or args.get("fecha_final") or "").strip()
    if hasta and "fecha_creacion" in columnas:
        filtros.append("a.fecha_creacion <= %s")
        valores.append(hasta)
    return ("WHERE " + " AND ".join(filtros) if filtros else ""), tuple(valores)


def _normalizar_auditoria_general_api(row):
    data = _row_dict(row) or {}
    for campo in ("fecha_creacion",):
        valor = data.get(campo)
        if hasattr(valor, "isoformat"):
            data[campo] = valor.isoformat(timespec="seconds")
    for campo in ("datos_anteriores_json", "datos_nuevos_json"):
        data[campo] = _limpiar_datos_auditoria(_json_field(data.get(campo), {}))
    return data


def _validar_acceso_auditoria_general_api():
    auth, error = _require_license_api()
    if error:
        return None, error
    if (auth or {}).get("rol") != "super_admin":
        return None, (jsonify({"ok": False, "error": "Permiso denegado para consultar auditoría general."}), 403)
    return auth, None


@app.route("/api/admin/auditoria", methods=["GET"])
def api_admin_auditoria():
    """Contrato legacy: eventos de licencia como lista directa."""
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


@app.route("/api/admin/auditoria-general", methods=["GET"])
def api_admin_auditoria_general():
    _, error = _validar_acceso_auditoria_general_api()
    if error:
        return error
    try:
        per_page = _api_limite(request.args.get("per_page") or request.args.get("limit"), default=50, maximo=200)
        try:
            page = max(1, int(request.args.get("page") or 1))
        except ValueError:
            raise ValueError("page debe ser un numero entero positivo.")
        offset = (page - 1) * per_page
        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "auditoria_general")
            if not columnas:
                return jsonify({"ok": True, "items": [], "auditoria": [], "pagination": {"page": page, "per_page": per_page, "total": 0, "pages": 0}})
            where, valores = _filtros_auditoria_general_api(columnas, request.args)
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM auditoria_general a
                LEFT JOIN usuarios_sistema u ON u.id=a.usuario_id
                LEFT JOIN clientes_sistema c ON c.id=a.cliente_sistema_id
                {where}
                """,
                valores,
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT {_select_auditoria_general_api(columnas)}
                FROM auditoria_general a
                LEFT JOIN usuarios_sistema u ON u.id=a.usuario_id
                LEFT JOIN clientes_sistema c ON c.id=a.cliente_sistema_id
                {where}
                ORDER BY a.fecha_creacion DESC, a.id DESC
                LIMIT %s OFFSET %s
                """,
                valores + (per_page, offset),
            ).fetchall()
        total = int((total_row or {}).get("total") or 0)
        items = [_normalizar_auditoria_general_api(row) for row in rows]
        pagination = {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page if total else 0}
        return jsonify({"ok": True, "items": items, "auditoria": items, "pagination": pagination})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Error al consultar auditoria general")
        return jsonify({"ok": False, "error": "No se pudo consultar la auditoría general."}), 500


@app.route("/api/admin/auditoria/<int:auditoria_id>", methods=["GET"])
def api_admin_auditoria_detalle(auditoria_id):
    _, error = _validar_acceso_auditoria_general_api()
    if error:
        return error
    try:
        with get_conn() as conn:
            columnas = _columnas_tabla_api(conn, "auditoria_general")
            if not columnas:
                raise LookupError("No hay auditoría general disponible.")
            row = conn.execute(
                f"""
                SELECT {_select_auditoria_general_api(columnas)}
                FROM auditoria_general a
                LEFT JOIN usuarios_sistema u ON u.id=a.usuario_id
                LEFT JOIN clientes_sistema c ON c.id=a.cliente_sistema_id
                WHERE a.id=%s
                LIMIT 1
                """,
                (auditoria_id,),
            ).fetchone()
        if not row:
            raise LookupError("Registro de auditoría no encontrado.")
        return jsonify({"ok": True, "auditoria": _normalizar_auditoria_general_api(row)})
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception:
        app.logger.exception("Error al consultar detalle de auditoria")
        return jsonify({"ok": False, "error": "No se pudo consultar el detalle de auditoría."}), 500


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
        where.append("UPPER(COALESCE(n.estado, '')) IN ('PAGADA','EN_PROCESO','INCOMPLETA')")
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
            notas_validas = []
            for nota_id in nota_ids:
                nota = conn.execute(
                    "SELECT id, estado FROM notas WHERE id=%s FOR UPDATE",
                    (nota_id,),
                ).fetchone()
                if not nota:
                    raise LookupError(f"Nota {nota_id} no encontrada.")
                estado = _normalizar_estado_pago_api(nota.get("estado"))
                if estado not in ESTADOS_EMPAQUE_ASIGNABLES:
                    raise NotaPagoNoPermitido(
                        f"La nota {nota_id} no puede asignarse a empaque desde el estado {estado or 'SIN ESTADO'}.",
                        409,
                    )
                notas_validas.append(nota_id)
            campos = ["empacador_id=%s"]
            valores_base = [empacador_id]
            if "fecha_asignacion" in notas_cols:
                campos.append("fecha_asignacion=NOW()")
            if "estado" in notas_cols:
                campos.append(
                    "estado=CASE "
                    "WHEN UPPER(COALESCE(estado, ''))='PAGADA' THEN 'EN_PROCESO' "
                    "ELSE estado END"
                )
            if "fecha_finalizacion" in notas_cols:
                campos.append("fecha_finalizacion=NULL")
            for nota_id in notas_validas:
                conn.execute(
                    f"UPDATE notas SET {', '.join(campos)} WHERE id=%s",
                    tuple(valores_base + [nota_id]),
                )
        return jsonify({"ok": True, "asignadas": len(notas_validas), "usuario": _usuario_auth_api(auth)})
    except NotaPagoNoPermitido as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
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
            AND (
                estado IN ('PAGADA','EN_PROCESO','INCOMPLETA')
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
        nota = conn.execute(
            "SELECT id, estado FROM notas WHERE id=%s FOR UPDATE",
            (nota_id,),
        ).fetchone()
        if not nota:
            return jsonify({"error": "Nota no encontrada"}), 404
        estado = _normalizar_estado_pago_api(nota.get("estado"))
        if estado not in ESTADOS_EMPAQUE_ASIGNABLES:
            return jsonify({
                "error": f"La nota no puede asignarse a empaque desde el estado {estado or 'SIN ESTADO'}"
            }), 409
        conn.execute("""
            UPDATE notas
            SET empacador_id=%s,
                fecha_asignacion=NOW(),
                estado=CASE
                    WHEN UPPER(COALESCE(estado, ''))='PAGADA' THEN 'EN_PROCESO'
                    ELSE estado
                END,
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
            SELECT id, estado
            FROM notas
            WHERE id=%s
            AND empacador_id=%s
        """,(nota_id, auth["empacador_id"])).fetchone()

        if not nota:
            return jsonify({"error": "Nota no encontrada o no autorizada"}), 403
        estado = _normalizar_estado_pago_api(nota.get("estado"))
        if estado not in ESTADOS_EMPAQUE_ASIGNABLES:
            return jsonify({
                "error": f"La nota no puede reiniciarse desde el estado {estado or 'SIN ESTADO'}"
            }), 409

        conn.execute("""
            UPDATE items
            SET empacadas = 0
            WHERE nota_id=%s
        """,(nota_id,))

        conn.execute("""
            UPDATE notas
            SET estado='EN_PROCESO',
                fecha_finalizacion=NULL
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
            SELECT empacador_id, estado
            FROM notas
            WHERE id=%s
        """,(nota_id,)).fetchone()

        if not nota or (
            nota["empacador_id"] != auth["empacador_id"]
            and auth["rol"] != "ADMIN"
        ):
            return jsonify({"error": "No autorizado para esta nota"}), 403
        estado = _normalizar_estado_pago_api(nota.get("estado"))
        if estado not in ESTADOS_EMPAQUE_ASIGNABLES:
            return jsonify({
                "error": f"La nota no puede escanearse desde el estado {estado or 'SIN ESTADO'}"
            }), 409

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

        nuevo_estado = _actualizar_estado_empaque_nota_api(
            conn, nota_id, totales["total"], totales["emp"]
        )

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
            SELECT empacador_id, estado
            FROM notas
            WHERE id=%s
        """,(nota_id,)).fetchone()

        if not nota or (
            nota["empacador_id"] != auth["empacador_id"]
            and auth["rol"] != "ADMIN"
        ):
            return jsonify({"error": "No autorizado para esta nota"}), 403
        estado = _normalizar_estado_pago_api(nota.get("estado"))
        if estado not in ESTADOS_EMPAQUE_EDITABLES:
            return jsonify({
                "error": f"La nota no puede corregirse desde el estado {estado or 'SIN ESTADO'}"
            }), 409


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


        nuevo_estado = _actualizar_estado_empaque_nota_api(
            conn, nota_id, totales["total"], totales["emp"]
        )


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

        if nota["estado"] != "COMPLETA":
            return jsonify({"error": "Solo notas COMPLETAS pueden recibir una guia"}), 409

        conn.execute("""
            UPDATE notas
            SET guia=%s,
                paqueteria=%s
            WHERE id=%s
        """,(guia, paqueteria, nota_id))
    return jsonify({"ok": True, "estado": "COMPLETA", "guia": guia})


@app.route("/notas/<nota_id>/enviar", methods=["POST"])
def marcar_nota_enviada_legacy(nota_id):
    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401
    try:
        with get_conn() as conn:
            nota_id_real, nota, idempotente, fecha_disponible = _marcar_nota_enviada_api_conn(conn, nota_id)
        return jsonify({
            "ok": True,
            "nota_id": nota_id_real,
            "estado": nota.get("estado") or "ENVIADO",
            "fecha_envio": nota.get("fecha_envio"),
            "fecha_envio_guardada": fecha_disponible,
            "idempotente": idempotente,
        })
    except NotaPagoNoPermitido as exc:
        return jsonify({"error": str(exc)}), exc.status
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404


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
        nota = conn.execute("SELECT id, estado FROM notas WHERE id=%s", (nota_id,)).fetchone()
        if not nota:
            return jsonify({"error": "Nota no encontrada"}), 404
        estado = _normalizar_estado_pago_api(nota.get("estado"))
        if estado in ESTADOS_NOTA_ANULADA_API | {"ARCHIVADA"}:
            return jsonify({"error": "Una nota terminal no puede enviarse a impresion"}), 409
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
                   n.estado,
                   c.telefono,
                   c.direccion
            FROM notas n
            JOIN clientes c ON c.nombre = n.cliente_nombre
            WHERE n.id=%s
        """,(nota_id,)).fetchone()

    if not nota:
        return jsonify({"error": "Nota no encontrada"}), 404
    estado = _normalizar_estado_pago_api(nota.get("estado"))
    if estado in ESTADOS_NOTA_ANULADA_API | {"ARCHIVADA"}:
        return jsonify({"error": "La tarea de impresion ya no es valida"}), 409

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
            SELECT ci.id, ci.nota_id, ci.tipo
            FROM cola_impresion ci
            JOIN notas n ON n.id=ci.nota_id
            WHERE ci.estado='PENDIENTE'
              AND UPPER(COALESCE(n.estado, '')) NOT IN ('ANULADA','CANCELADA','ELIMINADA','ARCHIVADA')
            ORDER BY ci.creado_en ASC
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

