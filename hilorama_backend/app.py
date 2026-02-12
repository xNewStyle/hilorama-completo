
from core.almacen_api import obtener_producto_por_codigo_barras

from flask_cors import CORS
from flask import Flask, request, jsonify, render_template



app = Flask(__name__)
CORS(app)
import hashlib
import time

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

        conn = get_conn()
        row = conn.execute("""
            SELECT id, rol
            FROM empacadores
            WHERE id=%s AND activo=TRUE
        """,(empacador_id,)).fetchone()
        conn.close()

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

def registrar_error(nota_id, codigo, empacador_id, motivo):
    conn = get_conn()

    conn.execute("""
        INSERT INTO errores_scan (
            nota_id,
            empacador_id,
            codigo,
            motivo
        )
        VALUES (%s,%s,%s,%s)
    """,(nota_id, empacador_id, codigo, motivo))

    conn.commit()
    conn.close()




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

    conn = get_conn()

    row = conn.execute("""
        SELECT id, nombre, password, rol
        FROM empacadores
        WHERE usuario=%s AND activo=TRUE
    """,(usuario,)).fetchone()

    if not row or row["password"] != password:
        conn.close()
        return jsonify({"error": "Credenciales inválidas"}), 401

    conn.close()

    token = generar_token(row["id"])



    return jsonify({
        "token": token,
        "nombre": row["nombre"],
        "empacador_id": row["id"],
        "rol": row["rol"]
    })

        

 
# =========================
# NOTAS PAGADAS (EMPACADOR)
# =========================
@app.route("/notas-pagadas", methods=["GET"])
def notas_pagadas():
    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    conn = get_conn()

    notas = conn.execute("""
        SELECT id, cliente_nombre, estado
        FROM notas
        WHERE empacador_id=%s
        AND estado != 'ARCHIVADA' 
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
            SELECT codigo, cantidad as pz_requeridas,
                   empacadas as pz_empacadas
            FROM items
            WHERE nota_id=%s
        """,(n["id"],)).fetchall()

        resultado.append({
            "id": n["id"],
            "cliente": n["cliente_nombre"],
            "estado": n["estado"],
            "productos": productos
        })

    conn.close()
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

    conn = get_conn()

    conn.execute("""
        UPDATE notas
        SET empacador_id=%s,
            fecha_asignacion=NOW(),
            estado='EN_PROCESO',
            fecha_finalizacion=NULL
        WHERE id=%s
    """,(empacador_id, nota_id))

    conn.commit()
    conn.close()

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

    ESTADOS_VALIDOS = ["PAGADA", "EN_PROCESO", "COMPLETA", "INCOMPLETA","ARCHIVADA"]

    if nuevo_estado not in ESTADOS_VALIDOS:
        return jsonify({"error": "Estado inválido"}), 400

    conn = get_conn()

    nota = conn.execute("""
        SELECT estado, empacador_id
        FROM notas
        WHERE id=%s
        AND estado!='ARCHIVADA'
    """,(nota_id,)).fetchone()

    if not nota:
        conn.close()
        return jsonify({"error": "Nota no encontrada"}), 404

    # 🔒 Validar que la nota pertenece al empacador
    if nota["empacador_id"] != auth["empacador_id"] and auth["rol"] != "ADMIN":
        conn.close()
        return jsonify({"error": "No es tu nota"}), 403

    estado_actual = nota["estado"]

    # 🔒 Reglas de transición empresariales
    transicion_valida = False

    if estado_actual == "PAGADA" and nuevo_estado == "EN_PROCESO":
        transicion_valida = True

    elif estado_actual == "EN_PROCESO" and nuevo_estado in ["COMPLETA", "INCOMPLETA"]:
        transicion_valida = True

    elif estado_actual == "INCOMPLETA" and nuevo_estado == "EN_PROCESO":
        transicion_valida = True

    if not transicion_valida:
        conn.close()
        return jsonify({"error": "Transición no permitida"}), 400

    # Actualizar estado
    conn.execute("""
        UPDATE notas
        SET estado=%s
        WHERE id=%s
    """,(nuevo_estado, nota_id))

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "nuevo_estado": nuevo_estado
    })

@app.route("/notas/<nota_id>/reset", methods=["POST"])
def resetear_nota(nota_id):
    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    conn = get_conn()

    # Verificar que la nota pertenece al empacador
    nota = conn.execute("""
        SELECT id
        FROM notas
        WHERE id=%s
        AND empacador_id=%s
        AND estado!='ARCHIVADA'
    """,(nota_id, auth["empacador_id"])).fetchone()

    if not nota:
        conn.close()
        return jsonify({"error": "Nota no encontrada o no autorizada"}), 403

    # Resetear productos
    conn.execute("""
        UPDATE items
        SET empacadas = 0
        WHERE nota_id=%s
    """,(nota_id,))

    # Cambiar estado
    conn.execute("""
        UPDATE notas
        SET estado='EN_PROCESO'
        WHERE id=%s
    """,(nota_id,))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

@app.route("/notas/<nota_id>/scan", methods=["POST"])
def escanear_producto(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    conn = get_conn()

    # 🔒 Verificar que la nota pertenece al empacador
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

        conn.close()
        return jsonify({"error": "No autorizado para esta nota"}), 403

    codigo_barras = request.json.get("codigo")

    producto = obtener_producto_por_codigo_barras(codigo_barras)
    if not producto:
        conn.close()
        return jsonify({"error": "No existe en almacén"}), 404

    item = conn.execute("""
        SELECT id, cantidad, empacadas
        FROM items
        WHERE nota_id=%s AND codigo=%s
    """,(nota_id, producto["codigo"])).fetchone()

    if not item:
        conn.close()
        return jsonify({"error": "No pertenece a la nota"}), 404

    if item["empacadas"] >= item["cantidad"]:
        conn.close()
        return jsonify({"error": "Piezas completas"}), 409

    conn.execute("""
        UPDATE items
        SET empacadas = empacadas + 1
        WHERE id=%s
    """,(item["id"],))

    # recalcular estado
    totales = conn.execute("""
        SELECT SUM(cantidad) total,
               SUM(empacadas) emp
        FROM items
        WHERE nota_id=%s
    """,(nota_id,)).fetchone()

    if totales["emp"] == totales["total"]:
        nuevo_estado = "COMPLETA"
    elif totales["emp"] == 0:
        nuevo_estado = "EN_PROCESO"
    else:
        nuevo_estado = "INCOMPLETA"

    if nuevo_estado == "COMPLETA":
        conn.execute("""
            UPDATE notas
            SET estado=%s,
                fecha_finalizacion=NOW()
            WHERE id=%s
        """,(nuevo_estado, nota_id))
    else:
        conn.execute("""
            UPDATE notas
            SET estado=%s
            WHERE id=%s
        """,(nuevo_estado, nota_id))


    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "estado_nota": nuevo_estado
    })




@app.route("/notas/<nota_id>/producto/ajustar", methods=["POST"])
def ajustar_producto(nota_id):

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    conn = get_conn()

    # 🔒 validar pertenencia
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

        conn.close()
        return jsonify({"error": "No autorizado para esta nota"}), 403

    data = request.json
    codigo = data["codigo"]
    cantidad = data["cantidad"]

    item = conn.execute("""
        SELECT id, cantidad, empacadas
        FROM items
        WHERE nota_id=%s AND codigo=%s
    """,(nota_id, codigo)).fetchone()

    if not item:
        conn.close()
        return jsonify({"error": "No pertenece a la nota"}), 404

    nuevo_total = item["empacadas"] + cantidad

    if nuevo_total < 0 or nuevo_total > item["cantidad"]:
        conn.close()
        return jsonify({"error": "Cantidad inválida"}), 409

    conn.execute("""
        UPDATE items
        SET empacadas=%s
        WHERE id=%s
    """,(nuevo_total, item["id"]))

    # recalcular estado
    totales = conn.execute("""
        SELECT SUM(cantidad) total,
               SUM(empacadas) emp
        FROM items
        WHERE nota_id=%s
    """,(nota_id,)).fetchone()

    if totales["emp"] == totales["total"]:
        nuevo_estado = "COMPLETA"
    elif totales["emp"] == 0:
        nuevo_estado = "EN_PROCESO"
    else:
        nuevo_estado = "INCOMPLETA"

    if nuevo_estado == "COMPLETA":
        conn.execute("""
            UPDATE notas
            SET estado=%s,
                fecha_finalizacion=NOW()
            WHERE id=%s
        """,(nuevo_estado, nota_id))
    else:
        conn.execute("""
            UPDATE notas
            SET estado=%s
            WHERE id=%s
        """,(nuevo_estado, nota_id))


    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "estado_nota": nuevo_estado
    })




@app.route("/errores-scan", methods=["GET"])
def ver_errores_scan():
    conn = get_conn()

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

    conn.close()

    return jsonify(rows)


@app.route("/notas/<nota_id>/progreso", methods=["GET"])
def progreso_nota(nota_id):
    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    conn = get_conn()

    datos = conn.execute("""
        SELECT SUM(cantidad) total,
               SUM(empacadas) emp
        FROM items
        WHERE nota_id=%s
    """,(nota_id,)).fetchone()

    conn.close()

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

    # 🔒 Solo admin puede archivar
    if auth["rol"] != "ADMIN":
        return jsonify({"error": "Solo admin puede archivar"}), 403

    conn = get_conn()

    conn.execute("""
        UPDATE notas
        SET estado='ARCHIVADA'
        WHERE id=%s
    """,(nota_id,))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})

@app.route("/mantenimiento/archivar-expiradas", methods=["POST"])
def archivar_expiradas():

    auth = validar_token(request)
    if not auth:
        return jsonify({"error": "No autorizado"}), 401

    if auth["rol"] != "ADMIN":
        return jsonify({"error": "Solo admin"}), 403

    conn = get_conn()

    conn.execute("""
        UPDATE notas
        SET estado = 'ARCHIVADA'
        WHERE estado='COMPLETA'
        AND fecha_finalizacion < NOW() - INTERVAL '24 hours'
    """)

    conn.commit()
    conn.close()

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

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, cliente_nombre, estado, paqueteria, guia
        FROM notas
        WHERE id = %s
    """, (nota_id,))

    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return "Nota no encontrada", 404

    nota = {
        "id": row[0],
        "cliente_nombre": row[1],
        "estado": row[2],
        "paqueteria": row[3],
        "guia": row[4],
    }

    cur.close()
    conn.close()

    progreso_map = {
        "PAGADA": 25,
        "EN_PROCESO": 50,
        "ENVIADO": 75,
        "ENTREGADO": 100
    }

    progreso = progreso_map.get(nota["estado"], 10)

    return render_template(
        "seguimiento.html",
        nota=nota,
        estado_visual=nota["estado"],
        progreso=progreso
    )


# =========================
# MAIN
# =========================
app.jinja_env.globals.update(
    generar_link_paqueteria=generar_link_paqueteria
)




if __name__ == "__main__":
    app.run()

