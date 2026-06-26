# notas.py (SQLite version)

import json
from datetime import datetime
from database.connection import get_conn
from clientes import obtener_cliente_por_id
from tkinter import messagebox


def ensure_notas_extra_schema():
    """Agrega columnas nuevas de forma segura, sin borrar datos."""
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
    ensure_notas_extra_schema()
    conn = get_conn()

    # Importante: NO ordenar aquí con COALESCE(fecha_pago, fecha),
    # porque en algunas bases fecha es TEXT y fecha_pago es TIMESTAMP.
    # Eso rompe Postgres. Ordenamos en Python para que funcione con ambos tipos.
    rows = conn.execute("SELECT * FROM notas").fetchall()

    notas = [dict(r) for r in rows]
    notas.sort(key=_clave_orden_nota, reverse=True)

    conn.close()

    return notas


# ================= OBTENER =================

def obtener_cotizacion(id_nota):
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

    return nota




# ================= ELIMINAR =================

def eliminar_cotizacion(id_nota):
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

    tk.Label(
        det,
        text=f"TOTAL: ${nota['total']:.2f}",
        font=("Segoe UI", 14, "bold")
    ).pack(pady=10)


# ================= VISOR =================
def abrir_visor(root):
    win = tk.Toplevel(root)
    win.title("Cotizaciones")
    win.geometry("600x400")

    tree = ttk.Treeview(
        win,
        columns=("ID", "Cliente", "Fecha", "Estado", "Total"),
        show="headings"
    )
    tree.pack(fill="both", expand=True, padx=10, pady=5)

    for c in ("ID", "Cliente", "Fecha", "Estado", "Total"):
        tree.heading(c, text=c)

    for n in listar_cotizaciones():
        tree.insert(
            "",
            "end",
            values=(
                n["id"],
                n["cliente_nombre"],
                n["fecha"],
                n["estado"],
                n["total"]
            )
        )

    ttk.Button(
        win,
        text="Ver detalle",
        command=lambda: ver_detalles(tree, win)
    ).pack(pady=5)

def convertir_cotizacion_a_venta(id_nota, items_finales, cliente, envio=None):
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

def eliminar_nota(id_nota):
    conn = get_conn()

    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))
    conn.execute("DELETE FROM notas WHERE id=%s", (id_nota,))

    conn.commit()
    conn.close()

    return True


def guardar_nota_actualizada(nota_actualizada):
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




def buscar_nota_por_texto(texto):
    conn = get_conn()

    texto = texto.strip().lower()

    row = conn.execute("""
        SELECT * FROM notas
        WHERE LOWER(id)=%s
    """,(texto,)).fetchone()

    conn.close()

    return dict(row) if row else None

def cambiar_cliente_nota(id_nota, cliente):
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