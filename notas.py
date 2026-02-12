# notas.py (SQLite version)

import json
from datetime import datetime
from database.connection import get_conn
from clientes import obtener_cliente_por_id
from tkinter import messagebox


# ================= ID =================

def generar_id():
    conn = get_conn()

    row = conn.execute(
        "SELECT COUNT(*) c FROM notas"
    ).fetchone()

    conn.close()

    return f"COT-{row['c']+1:05d}"


# ================= CREAR =================

def crear_cotizacion(cliente, carrito, envio=None, pedido=None):
    conn = get_conn()

    nota_id = generar_id()
    fecha = datetime.now().strftime("%d-%m-%Y %H:%M")
    total = sum(p["cantidad"] * p["precio"] for p in carrito)

    conn.execute("""
        INSERT INTO notas
        (id, cliente_id, cliente_nombre, fecha, estado, total, envio, pedido)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        nota_id,
        cliente["id"],
        cliente["nombre"],
        fecha,
        "COTIZACION",
        total,
        json.dumps(envio) if envio else None,
        pedido
    ))

    for p in carrito:
        conn.execute("""
            INSERT INTO items
            (nota_id, codigo, cantidad, precio)
            VALUES (%s,%s,%s,%s)
        """, (
            nota_id,
            p["codigo"],
            p["cantidad"],
            p["precio"]
        ))

    conn.commit()
    conn.close()

    return obtener_cotizacion(nota_id)


# ================= LISTAR =================

def listar_cotizaciones():
    conn = get_conn()

    rows = conn.execute("""
        SELECT * FROM notas
        ORDER BY fecha DESC
    """).fetchall()

    notas = [dict(r) for r in rows]

    conn.close()

    return notas


# ================= OBTENER =================

def obtener_cotizacion(id_nota):
    conn = get_conn()

    nota = conn.execute(
        "SELECT * FROM notas WHERE id=%s",
        (id_nota,)
    ).fetchone()

    if not nota:
        conn.close()
        return None

    items = conn.execute("""
        SELECT codigo, cantidad, precio
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

    conn.execute("""
        UPDATE notas
        SET estado='VENTA_PENDIENTE',
            cliente_id=%s,
            cliente_nombre=%s,
            envio=%s,
            total=%s
        WHERE id=%s
    """, (
        cliente["id"],
        cliente["nombre"],
        json.dumps(envio) if envio else None,
        total,
        id_nota
    ))

    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))

    for p in items_finales:
        conn.execute("""
            INSERT INTO items(nota_id,codigo,cantidad,precio)
            VALUES (%s,%s,%s,%s)
        """,(id_nota,p["codigo"],p["cantidad"],p["precio"]))

    conn.commit()
    conn.close()

    return True



def actualizar_cotizacion(id_nota, nuevos_items):
    conn = get_conn()

    total = sum(p["cantidad"] * p["precio"] for p in nuevos_items)

    conn.execute("DELETE FROM items WHERE nota_id=%s", (id_nota,))

    for p in nuevos_items:
        conn.execute("""
            INSERT INTO items(nota_id,codigo,cantidad,precio)
            VALUES (%s,%s,%s,%s)
        """,(id_nota,p["codigo"],p["cantidad"],p["precio"]))

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
    conn = get_conn()

    conn.execute("""
        UPDATE notas
        SET cliente_id=%s,
            cliente_nombre=%s,
            estado=%s,
            total=%s,
            envio=%s,
            comprobante=%s
        WHERE id=%s
    """, (
        nota_actualizada["cliente_id"],
        nota_actualizada["cliente_nombre"],
        nota_actualizada["estado"],
        nota_actualizada["total"],
        json.dumps(nota_actualizada.get("envio", {})),
        nota_actualizada.get("comprobante"),
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

