# notas.py (SQLite version)

import json
import os
import time
from datetime import datetime
from pathlib import Path
from clientes import obtener_cliente_por_id
from tkinter import messagebox
from envios_config import formatear_costo_envio

BASE_DIR = Path(__file__).resolve().parent
COMPROBANTES_DIR = BASE_DIR / "comprobantes"
EXTENSIONES_COMPROBANTE = (".png", ".jpg", ".jpeg", ".webp", ".pdf")
ACCION_NO_DISPONIBLE_API = "Esta acción todavía no está disponible en modo API."

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE, require_local_mode
except Exception:
    HILORAMA_DATA_MODE = "local"
    def require_local_mode(area=""):
        if os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api":
            detalle = f" ({area})" if area else ""
            raise RuntimeError(f"Base local bloqueada en modo API cliente{detalle}.")

try:
    from hilorama_desktop.utils.logger import log_info
except Exception:
    def log_info(nombre_modulo, mensaje):
        return None


def get_conn():
    require_local_mode("notas")
    from database.connection import get_conn as _real_get_conn
    return _real_get_conn()


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _notas_api():
    from hilorama_desktop.services import notas_api_service
    return notas_api_service


def _bloquear_escritura_api():
    if not _modo_api():
        return
    try:
        messagebox.showwarning("Modo API", ACCION_NO_DISPONIBLE_API)
    except Exception:
        pass
    raise RuntimeError(ACCION_NO_DISPONIBLE_API)


def _numero(valor, default=0.0):
    if valor is None or valor == "":
        return default
    try:
        return float(valor)
    except Exception:
        try:
            return float(str(valor).replace("$", "").replace(",", "").strip())
        except Exception:
            return default


def _precio_envio_nota(nota):
    envio = nota.get("envio") or {}
    if isinstance(envio, str):
        try:
            envio = json.loads(envio)
        except Exception:
            envio = {}
    return _numero(envio.get("precio")) if isinstance(envio, dict) else 0.0


def _subtotal_desde_items(items):
    total = 0.0
    for item in items or []:
        total += _numero(item.get("cantidad")) * _numero(item.get("precio"))
    return total


def calcular_totales_nota(nota):
    """Devuelve subtotal, envio y total final para mostrar sin reescribir la nota."""
    envio_precio = _precio_envio_nota(nota)
    total_guardado = _numero(nota.get("total"))

    if nota.get("items"):
        subtotal_productos = _subtotal_desde_items(nota.get("items"))
        total_final = subtotal_productos + envio_precio
    elif nota.get("subtotal_productos") is not None:
        subtotal_productos = _numero(nota.get("subtotal_productos"))
        total_final = subtotal_productos + envio_precio
    elif nota.get("total_final") is not None:
        total_final = _numero(nota.get("total_final"))
        subtotal_productos = max(total_final - envio_precio, 0.0)
    else:
        subtotal_productos = total_guardado
        total_final = total_guardado

    return {
        "subtotal_productos": round(subtotal_productos, 2),
        "envio_precio": round(envio_precio, 2),
        "total_final": round(total_final, 2),
        "total_guardado": round(total_guardado, 2),
    }


def aplicar_totales_visual_nota(nota, subtotal_productos=None):
    if subtotal_productos is not None:
        nota["subtotal_productos"] = round(_numero(subtotal_productos), 2)
    nota.update(calcular_totales_nota(nota))
    return nota


def _enriquecer_totales_desde_items(conn, notas):
    try:
        rows = conn.execute("""
            SELECT
                nota_id,
                COALESCE(SUM(COALESCE(cantidad, 0) * COALESCE(precio, 0)), 0) AS subtotal_productos
            FROM items
            GROUP BY nota_id
        """).fetchall()
        subtotales = {str(r["nota_id"]): _numero(r["subtotal_productos"]) for r in rows}
    except Exception:
        subtotales = {}

    for nota in notas:
        aplicar_totales_visual_nota(nota, subtotales.get(str(nota.get("id"))))


def _nombre_archivo_comprobante(ruta):
    if not ruta:
        return ""
    ruta_txt = str(ruta).strip()
    if not ruta_txt:
        return ""
    return ruta_txt.replace("\\", "/").rstrip("/").split("/")[-1]


def _buscar_comprobante_legacy(nombre_archivo):
    if not nombre_archivo:
        return None

    nombre = _nombre_archivo_comprobante(nombre_archivo)
    base = Path(nombre)
    stem = base.stem or nombre
    suffix = base.suffix.lower()

    candidatos = []
    if suffix:
        candidatos.extend([f"{stem}{suffix}", f"{stem.lower()}{suffix}"])

    for ext in EXTENSIONES_COMPROBANTE:
        candidatos.extend([f"{stem}{ext}", f"{stem.lower()}{ext}"])

    vistos = set()
    for candidato in candidatos:
        if not candidato or candidato in vistos:
            continue
        vistos.add(candidato)
        ruta = COMPROBANTES_DIR / candidato
        if ruta.exists():
            return ruta.resolve()

    if COMPROBANTES_DIR.exists():
        objetivo = {c.lower() for c in vistos}
        for archivo in COMPROBANTES_DIR.iterdir():
            if archivo.is_file() and archivo.name.lower() in objetivo:
                return archivo.resolve()

    return None


def resolver_ruta_comprobante(ruta):
    if not ruta:
        return None

    ruta_txt = str(ruta).strip()
    if not ruta_txt:
        return None

    ruta_path = Path(ruta_txt)
    if ruta_path.is_absolute():
        if ruta_path.exists():
            return ruta_path
        nombre = _nombre_archivo_comprobante(ruta_txt)
        encontrada = _buscar_comprobante_legacy(nombre)
        if encontrada:
            return encontrada
        return (COMPROBANTES_DIR / nombre).resolve() if nombre else ruta_path

    ruta_resuelta = (BASE_DIR / ruta_path).resolve()
    if ruta_resuelta.exists():
        return ruta_resuelta

    nombre = _nombre_archivo_comprobante(ruta_txt)
    encontrada = _buscar_comprobante_legacy(nombre)
    if encontrada:
        return encontrada

    return (COMPROBANTES_DIR / nombre).resolve() if nombre else ruta_resuelta


def abrir_comprobante_seguro(parent, ruta):
    ruta_resuelta = resolver_ruta_comprobante(ruta)
    if not ruta_resuelta or not ruta_resuelta.exists():
        nombre = _nombre_archivo_comprobante(ruta)
        ruta_esperada = (COMPROBANTES_DIR / nombre).resolve() if nombre else ruta_resuelta
        messagebox.showwarning(
            "Comprobante",
            "Comprobante registrado, pero archivo no encontrado.\n\n"
            f"Ruta guardada original:\n{ruta}\n\n"
            f"Ruta esperada actual:\n{ruta_esperada}",
            parent=parent
        )
        return

    if ruta_resuelta.suffix.lower() == ".pdf":
        messagebox.showinfo(
            "Comprobante PDF",
            f"Comprobante PDF registrado:\n{ruta_resuelta}",
            parent=parent
        )
        return

    from visor_imagen import visor_imagen
    visor_imagen(parent, ruta_inicial=str(ruta_resuelta))


def agregar_seccion_comprobante_detalle(parent, nota):
    frame = ttk.LabelFrame(parent, text="Comprobante de pago")
    frame.pack(fill="x", padx=10, pady=(0, 10))

    ruta = nota.get("comprobante")
    if not ruta:
        ttk.Label(frame, text="Sin comprobante registrado").pack(anchor="w", padx=8, pady=6)
        return

    ruta_resuelta = resolver_ruta_comprobante(ruta)
    if ruta_resuelta and ruta_resuelta.exists():
        ttk.Label(frame, text=f"Comprobante registrado: {ruta_resuelta.name}").pack(
            anchor="w", padx=8, pady=(6, 3)
        )
        ttk.Button(
            frame,
            text="Ver comprobante",
            command=lambda: abrir_comprobante_seguro(parent, ruta)
        ).pack(anchor="w", padx=8, pady=(0, 6))
        return

    nombre = _nombre_archivo_comprobante(ruta)
    ruta_esperada = (COMPROBANTES_DIR / nombre).resolve() if nombre else ruta_resuelta
    ttk.Label(
        frame,
        text=(
            "Comprobante registrado, pero archivo no encontrado.\n"
            f"Ruta guardada original: {ruta}\n"
            f"Ruta esperada actual: {ruta_esperada}"
        )
    ).pack(anchor="w", padx=8, pady=6)


def agregar_seccion_pagos_detalle(parent, nota):
    frame = ttk.LabelFrame(parent, text="Pagos registrados")
    frame.pack(fill="x", padx=10, pady=(0, 10))

    pagos = nota.get("pagos")
    if pagos is None:
        try:
            from pagos import listar_pagos
            pagos = listar_pagos(nota.get("id"))
        except Exception:
            pagos = []

    if not pagos:
        ttk.Label(frame, text="Sin pagos registrados").pack(anchor="w", padx=8, pady=6)
        return

    for pago in pagos:
        fecha = pago.get("fecha") or pago.get("created_at") or ""
        comprobante = pago.get("comprobante") or ""
        texto = f"{fecha} - {comprobante}" if fecha else comprobante or "Pago registrado"
        ttk.Label(frame, text=texto).pack(anchor="w", padx=8, pady=2)


def ensure_notas_extra_schema():
    """Agrega columnas nuevas de forma segura, sin borrar datos."""
    if _modo_api():
        return
    conn = get_conn()
    try:
        conn.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS fecha_pago TEXT")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

# ================= ID =================

def generar_id():
    _bloquear_escritura_api()

    conn = get_conn()

    row = conn.execute("""
        SELECT COALESCE(MAX(id), 'COT-00000') AS ultimo
        FROM notas
    """).fetchone()

    conn.close()

    ultimo = row["ultimo"]

    numero = int(ultimo.split("-")[1])

    return f"COT-{numero + 1:05d}"




# ================= CREAR =================

def crear_cotizacion(cliente, carrito, envio=None, pedido=None):
    if _modo_api():
        nota = _notas_api().crear_cotizacion(cliente, carrito, envio=envio, pedido=pedido)
        if nota:
            aplicar_totales_visual_nota(nota, _subtotal_desde_items(nota.get("items")))
        return nota

    _bloquear_escritura_api()

    conn = get_conn()

    nota_id = generar_id()
    
    total = sum(p["cantidad"] * p["precio"] for p in carrito)
    fecha = datetime.now()

    paqueteria = None

    if envio:
        paqueteria = envio.get("tipo") or envio.get("paqueteria")

    conn.execute("""
        INSERT INTO notas
        (id, cliente_id, cliente_nombre, fecha, estado, total, envio, pedido, paqueteria)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        nota_id,
        cliente["id"],
        cliente["nombre"],
        fecha,
        "COTIZACION",
        total,
        json.dumps(envio) if envio else None,
        pedido,
        paqueteria
    ))


    for p in carrito:
        conn.execute("""
            INSERT INTO items
            (nota_id, codigo, marca, hilo, color, cantidad, precio)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,(
               nota_id,
               p["codigo"],
               p["marca"],
               p["hilo"],
               p.get("color"), 
               p["cantidad"],
               p["precio"]
            )
        )

    conn.commit()
    conn.close()

    return obtener_cotizacion(nota_id)



# ================= LISTAR =================



def _fecha_para_orden(valor):
    """Convierte fecha_pago/fecha a datetime para ordenar sin romper Postgres.
    Evita errores cuando una columna es TEXT y otra TIMESTAMP.
    """
    if not valor:
        return datetime.min

    if isinstance(valor, datetime):
        return valor

    texto = str(valor).strip()
    if not texto:
        return datetime.min

    # Quitar zona Z si llega desde algún servicio externo
    texto = texto.replace("Z", "")

    # Intento principal: fechas tipo 2026-06-15 o 2026-06-15T18:30:00
    try:
        return datetime.fromisoformat(texto)
    except Exception:
        pass

    formatos = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    )

    for fmt in formatos:
        try:
            return datetime.strptime(texto[:19], fmt)
        except Exception:
            continue

    return datetime.min


def _clave_orden_nota(nota):
    """Ordena todas las notas: pagadas por fecha_pago, las demás por fecha."""
    fecha = None

    if nota.get("estado") == "PAGADA" and nota.get("fecha_pago"):
        fecha = nota.get("fecha_pago")
    else:
        fecha = nota.get("fecha")

    return (_fecha_para_orden(fecha), str(nota.get("id", "")))

def listar_cotizaciones():
    if _modo_api():
        notas = _notas_api().listar_notas()
        for nota in notas:
            aplicar_totales_visual_nota(nota)
        notas.sort(key=_clave_orden_nota, reverse=True)
        return notas

    ensure_notas_extra_schema()
    conn = get_conn()

    # Importante: NO ordenar aquí con COALESCE(fecha_pago, fecha),
    # porque en algunas bases fecha es TEXT y fecha_pago es TIMESTAMP.
    # Eso rompe Postgres. Ordenamos en Python para que funcione con ambos tipos.
    rows = conn.execute("SELECT * FROM notas").fetchall()

    notas = [dict(r) for r in rows]
    _enriquecer_totales_desde_items(conn, notas)
    notas.sort(key=_clave_orden_nota, reverse=True)

    conn.close()

    return notas


# ================= OBTENER =================

def obtener_cotizacion(id_nota):
    if _modo_api():
        inicio = time.perf_counter()
        fuente = "detalle-completo"
        try:
            nota = _notas_api().obtener_detalle_completo_nota(id_nota)
        except Exception:
            fuente = "fallback"
            nota = _notas_api().obtener_nota(id_nota)
            if nota:
                nota["items"] = _notas_api().obtener_items_nota(id_nota)
                nota["pagos"] = _notas_api().obtener_pagos_nota(id_nota)
        if nota:
            aplicar_totales_visual_nota(nota, _subtotal_desde_items(nota["items"]))
        log_info(
            "ventas",
            f"API obtener detalle de nota {id_nota} via {fuente}: {time.perf_counter() - inicio:.2f}s",
        )
        return nota

    ensure_notas_extra_schema()
    conn = get_conn()

    nota = conn.execute(
        "SELECT * FROM notas WHERE id=%s",
        (id_nota,)
    ).fetchone()

    if not nota:
        conn.close()
        return None

    items = conn.execute("""
        SELECT codigo, marca, hilo, color, cantidad, precio
        FROM items
        WHERE nota_id=%s
    """, (id_nota,)).fetchall()

    conn.close()

    nota = dict(nota)

    # ===== ENVIO SEGURO =====
    if nota["envio"]:
        if isinstance(nota["envio"], str):
            try:
                nota["envio"] = json.loads(nota["envio"])
            except:
                nota["envio"] = {}
    else:
        nota["envio"] = {}

    # ===== ITEMS =====
    nota["items"] = [dict(i) for i in items]
    aplicar_totales_visual_nota(nota, _subtotal_desde_items(nota["items"]))

    return nota




# ================= ELIMINAR =================

def eliminar_cotizacion(id_nota, autorizacion_stock=None):
    if _modo_api():
        return _notas_api().anular_nota(id_nota, autorizacion_stock=autorizacion_stock).get("ok", True)

    conn = get_conn()

    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))
    conn.execute("DELETE FROM notas WHERE id=%s", (id_nota,))

    conn.commit()
    conn.close()

    return True


import tkinter as tk
from tkinter import ttk
from notas import listar_cotizaciones, obtener_cotizacion

# ================= VER DETALLES =================
def ver_detalles(tree, win):
    seleccionado = tree.focus()
    if not seleccionado:
        return

    valores = tree.item(seleccionado, "values")
    id_nota = valores[0]

    nota = obtener_cotizacion(id_nota)
 
    if not nota:
        messagebox.showerror(
            "Error",
            "La nota ya no existe o fue eliminada",
            parent=win
        )
        return

    cliente = obtener_cliente_por_id(nota["cliente_id"])


    det = tk.Toplevel(win)
    det.title(f"Detalle {nota['id']}")
    det.geometry("600x500")

    tk.Label(
        det,
        text=f"Cliente: {nota['cliente_nombre']}",
        font=("Segoe UI", 11, "bold")
    ).pack(anchor="w", padx=10)

    tk.Label(det, text=f"Fecha: {nota['fecha']}").pack(anchor="w", padx=10)
    tk.Label(det, text=f"Estado: {nota['estado']}").pack(anchor="w", padx=10)

    cols = ("Código", "Cantidad", "Precio", "Subtotal")
    tree_det = ttk.Treeview(det, columns=cols, show="headings")

    for c in cols:
        tree_det.heading(c, text=c)

    tree_det.pack(fill="both", expand=True, padx=10, pady=10)

    for p in nota["items"]:
        tree_det.insert(
            "",
            "end",
            values=(
                p["codigo"],
                p["cantidad"],
                f"${p['precio']:.2f}",
                f"${p['cantidad'] * p['precio']:.2f}"
            )
        )

    totales = calcular_totales_nota(nota)
    frame_totales = tk.Frame(det)
    frame_totales.pack(fill="x", padx=10, pady=10)

    tk.Label(
        frame_totales,
        text=f"Subtotal productos: ${totales['subtotal_productos']:.2f}",
        anchor="e"
    ).pack(anchor="e")
    tk.Label(
        frame_totales,
        text=formatear_costo_envio(nota.get("envio"), con_etiqueta=True),
        anchor="e"
    ).pack(anchor="e")
    tk.Label(
        frame_totales,
        text=f"Total final: ${totales['total_final']:.2f}",
        font=("Segoe UI", 14, "bold"),
        anchor="e"
    ).pack(anchor="e")

    agregar_seccion_comprobante_detalle(det, nota)
    agregar_seccion_pagos_detalle(det, nota)


# ================= VISOR =================
def abrir_visor(root):
    win = tk.Toplevel(root)
    win.title("Cotizaciones")
    win.geometry("600x400")

    tree = ttk.Treeview(
        win,
        columns=("ID", "Cliente", "Fecha", "Estado", "Total final"),
        show="headings"
    )
    tree.pack(fill="both", expand=True, padx=10, pady=5)

    for c in ("ID", "Cliente", "Fecha", "Estado", "Total final"):
        tree.heading(c, text=c)

    for n in listar_cotizaciones():
        totales = calcular_totales_nota(n)
        tree.insert(
            "",
            "end",
            values=(
                n["id"],
                n["cliente_nombre"],
                n["fecha"],
                n["estado"],
                f"${totales['total_final']:.2f}"
            )
        )

    ttk.Button(
        win,
        text="Ver detalle",
        command=lambda: ver_detalles(tree, win)
    ).pack(pady=5)

def convertir_cotizacion_a_venta(id_nota, items_finales, cliente, envio=None, autorizacion_stock=None):
    if _modo_api():
        _notas_api().convertir_a_venta(
            id_nota,
            items_finales,
            cliente,
            envio=envio,
            autorizacion_stock=autorizacion_stock,
        )
        return True

    _bloquear_escritura_api()

    conn = get_conn()

    total = sum(p["cantidad"] * p["precio"] for p in items_finales)

    paqueteria = None
    if envio:
        paqueteria = envio.get("tipo") or envio.get("paqueteria")

    conn.execute("""
        UPDATE notas
        SET estado='VENTA_PENDIENTE',
            cliente_id=%s,
            cliente_nombre=%s,
            envio=%s,
            total=%s,
            paqueteria=%s
        WHERE id=%s
    """, (
        cliente["id"],
        cliente["nombre"],
        json.dumps(envio) if envio else None,
        total,
        paqueteria,
        id_nota
    ))


    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))

    for p in items_finales:
        conn.execute("""
            INSERT INTO items(nota_id,codigo,marca,hilo,color,cantidad,precio)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            id_nota,
            p["codigo"],
            p["marca"],
            p["hilo"],
            p.get("color"),
            p["cantidad"],
            p["precio"]
        ))


    conn.commit()
    conn.close()

    return True



def actualizar_cotizacion(id_nota, nuevos_items):
    if _modo_api():
        _notas_api().actualizar_items_nota(id_nota, nuevos_items)
        return True

    _bloquear_escritura_api()

    conn = get_conn()

    total = sum(p["cantidad"] * p["precio"] for p in nuevos_items)

    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))

    for p in nuevos_items:
        conn.execute("""
            INSERT INTO items(nota_id,codigo,marca,hilo,color,cantidad,precio)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            id_nota,
            p["codigo"],
            p["marca"],
            p["hilo"],
            p.get("color"),
            p["cantidad"],
            p["precio"]
        ))


    conn.execute("""
        UPDATE notas
        SET total=%s
        WHERE id=%s
    """,(total,id_nota))

    conn.commit()
    conn.close()

    return True

def eliminar_nota(id_nota, autorizacion_stock=None):
    if _modo_api():
        return _notas_api().anular_nota(id_nota, autorizacion_stock=autorizacion_stock).get("ok", True)

    conn = get_conn()

    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))
    conn.execute("DELETE FROM notas WHERE id=%s", (id_nota,))

    conn.commit()
    conn.close()

    return True


def guardar_nota_actualizada(nota_actualizada):
    if _modo_api():
        if nota_actualizada.get("admin_edicion_pagada"):
            _notas_api().actualizar_nota_admin(
                nota_actualizada["id"],
                nota_actualizada,
                clave_autorizacion=(
                    nota_actualizada.get("clave_autorizacion")
                    or nota_actualizada.get("autorizacion_stock")
                ),
            )
            return True
        if nota_actualizada.get("estado") == "PAGADA":
            _notas_api().marcar_nota_pagada(
                nota_actualizada["id"],
                comprobante=nota_actualizada.get("comprobante"),
                fecha_pago=nota_actualizada.get("fecha_pago"),
                autorizacion_stock=nota_actualizada.get("autorizacion_stock"),
            )
            return True
        if nota_actualizada.get("comprobante"):
            _notas_api().guardar_comprobante_nota(
                nota_actualizada["id"],
                nota_actualizada.get("comprobante"),
            )
        _notas_api().actualizar_nota(nota_actualizada)
        return True

    _bloquear_escritura_api()

    ensure_notas_extra_schema()
    conn = get_conn()

    envio_data = nota_actualizada.get("envio", {})
    paqueteria = None

    if envio_data:
        paqueteria = envio_data.get("tipo") or envio_data.get("paqueteria")

    fecha_pago = nota_actualizada.get("fecha_pago")

    if nota_actualizada.get("estado") == "PAGADA" and not fecha_pago:
        actual = conn.execute(
            "SELECT fecha_pago FROM notas WHERE id=%s",
            (nota_actualizada["id"],)
        ).fetchone()
        fecha_pago = (actual or {}).get("fecha_pago") or datetime.now().isoformat(timespec="seconds")

    conn.execute("""
        UPDATE notas
        SET cliente_id=%s,
            cliente_nombre=%s,
            estado=%s,
            total=%s,
            envio=%s,
            comprobante=%s,
            paqueteria=%s,
            fecha_pago=%s
        WHERE id=%s
    """, (
        nota_actualizada["cliente_id"],
        nota_actualizada["cliente_nombre"],
        nota_actualizada["estado"],
        nota_actualizada["total"],
        json.dumps(envio_data) if envio_data else None,
        nota_actualizada.get("comprobante"),
        paqueteria,
        fecha_pago,
        nota_actualizada["id"]
    ))

    conn.commit()
    conn.close()

    return True



def actualizar_nota_admin(nota_actualizada, clave_autorizacion=None):
    if _modo_api():
        return _notas_api().actualizar_nota_admin(
            nota_actualizada["id"],
            nota_actualizada,
            clave_autorizacion=clave_autorizacion,
        )
    return guardar_nota_actualizada(nota_actualizada)


def ajustar_items_nota_pagada_admin(nota_actualizada, items, clave_autorizacion=None, motivo=None):
    if _modo_api():
        data = _notas_api().ajustar_items_nota_pagada_admin(
            nota_actualizada["id"],
            items,
            clave_autorizacion,
            envio=nota_actualizada.get("envio"),
            observaciones=nota_actualizada.get("observaciones"),
            comprobante=nota_actualizada.get("comprobante"),
            motivo=motivo,
        )
        nota = data.get("nota") if isinstance(data, dict) else None
        if nota:
            aplicar_totales_visual_nota(nota, _subtotal_desde_items(nota.get("items")))
        return data

    return guardar_nota_actualizada(nota_actualizada)



def buscar_nota_por_texto(texto):
    if _modo_api():
        return _notas_api().buscar_nota_por_texto(texto)

    conn = get_conn()

    texto = texto.strip().lower()

    row = conn.execute("""
        SELECT * FROM notas
        WHERE LOWER(id)=%s
    """,(texto,)).fetchone()

    conn.close()

    return dict(row) if row else None

def cambiar_cliente_nota(id_nota, cliente):
    if _modo_api():
        _notas_api().cambiar_cliente_nota(id_nota, cliente)
        return True

    _bloquear_escritura_api()

    conn = get_conn()

    conn.execute("""
        UPDATE notas
        SET cliente_id=%s,
            cliente_nombre=%s
        WHERE id=%s
    """, (
        cliente["id"],
        cliente["nombre"],
        id_nota
    ))

    conn.commit()
    conn.close()

    return True


def cambiar_pedido_nota(id_nota, pedido):
    try:
        pedido = int(str(pedido).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("El pedido destino no es válido.") from exc
    if pedido <= 0:
        raise ValueError("El pedido destino no es válido.")

    if _modo_api():
        return _notas_api().cambiar_pedido_nota(id_nota, pedido)

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE notas SET pedido=%s WHERE id=%s",
            (pedido, id_nota),
        )
        conn.commit()
    finally:
        conn.close()
    return True
