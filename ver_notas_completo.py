import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

from notas import listar_cotizaciones, obtener_cotizacion
from clientes import listar_clientes

# ================= RUTAS =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_PAGOS = os.path.join(BASE_DIR, "data", "pagos.json")


# ================= UTIL =================

def cargar_pagos():
    if not os.path.exists(ARCHIVO_PAGOS):
        return []
    with open(ARCHIVO_PAGOS, "r", encoding="utf-8") as f:
        return json.load(f)


def indice_clientes():
    """
    Devuelve dict {cliente_id: cliente}
    """
    return {c["id"]: c for c in listar_clientes()}


def tiene_pago(id_nota, pagos):
    for p in pagos:
        if p.get("nota") == id_nota:
            return True
    return False


def normalizar(texto):
    return texto.lower().strip()


# ================= VISOR PRINCIPAL =================

def abrir_visor_notas(root):
    win = tk.Toplevel(root)
    win.title("Notas / Ventas")
    win.geometry("1000x500")

    # ================= BUSCADOR =================
    frm_buscar = ttk.Frame(win)
    frm_buscar.pack(fill="x", padx=10, pady=5)

    buscar_var = tk.StringVar()

    ttk.Label(frm_buscar, text="Buscar:").pack(side="left")
    entry_buscar = ttk.Combobox(
    frm_buscar,
    textvariable=buscar_var,
    width=40
)

    entry_buscar.pack(side="left", padx=5)

    # ================= TABLA =================
    cols = (
        "Nota",
        "Cliente",
        "Teléfono",
        "Estado",
        "Total",
        "Pago"
    )

    tree = ttk.Treeview(
        win,
        columns=cols,
        show="headings"
    )
    tree.pack(fill="both", expand=True, padx=10, pady=10)

    for c in cols:
        tree.heading(c, text=c)

    tree.column("Nota", width=100)
    tree.column("Cliente", width=200)
    tree.column("Teléfono", width=120)
    tree.column("Estado", width=150)
    tree.column("Total", width=100)
    tree.column("Pago", width=80, anchor="center")

    # ================= DATOS =================
    clientes_idx = indice_clientes()
    pagos = cargar_pagos()
    notas = listar_cotizaciones()
    # ===== AUTOCOMPLETE CLIENTES =====
    nombres_clientes = sorted({
        c.get("nombre", "")
        for c in clientes_idx.values()
        if c.get("nombre")
    })

    entry_buscar["values"] = nombres_clientes


    def refrescar(filtro=""):
        tree.delete(*tree.get_children())
        f = normalizar(filtro)

        for n in notas:
            id_nota = n["id"]
            cliente = clientes_idx.get(n["cliente_id"], {})
            nombre = cliente.get("nombre", "")
            tel = cliente.get("telefono", "")
            estado = n.get("estado", "")
            total = f"${n.get('total', 0):.2f}"
            pago = "✅" if tiene_pago(id_nota, pagos) else "❌"

            # ===== FILTRO =====
            texto_total = " ".join([
                id_nota,
                nombre,
                tel
            ]).lower()

            # Buscar por número simple: 1 → COT-00001
            if f.isdigit():
                f_id = f"COT-{int(f):05d}"
                if f_id != id_nota:
                    continue
            elif f and f not in texto_total:
                continue

            tree.insert(
                "",
                "end",
                values=(
                    id_nota,
                    nombre,
                    tel,
                    estado,
                    total,
                    pago
                )
            )
    
    refrescar()
        # ================= BUSCAR EN TIEMPO REAL =================
    def on_buscar(event=None):
        refrescar(buscar_var.get())

    entry_buscar.bind("<KeyRelease>", on_buscar)
    entry_buscar.bind("<<ComboboxSelected>>", on_buscar)

    def buscar():
        refrescar(buscar_var.get())

    ttk.Button(frm_buscar, text="Buscar", command=buscar).pack(side="left", padx=5)

    # ================= ACCIONES =================

    def ver_detalle():
        sel = tree.focus()
        if not sel:
            return

        id_nota = tree.item(sel, "values")[0]
        nota = obtener_cotizacion(id_nota)
        if not nota:
            return

        det = tk.Toplevel(win)
        det.title(f"Detalle {id_nota}")
        det.geometry("600x500")

        cliente = clientes_idx.get(nota["cliente_id"], {})

        ttk.Label(
            det,
            text=f"Cliente: {cliente.get('nombre','')}",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", padx=10, pady=2)

        ttk.Label(det, text=f"Teléfono: {cliente.get('telefono','')}")\
            .pack(anchor="w", padx=10)

        ttk.Label(det, text=f"Estado: {nota['estado']}")\
            .pack(anchor="w", padx=10)

        cols2 = ("Código", "Cantidad", "Precio", "Subtotal")
        tree_det = ttk.Treeview(det, columns=cols2, show="headings")
        for c in cols2:
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

        ttk.Label(
            det,
            text=f"TOTAL: ${nota['total']:.2f}",
            font=("Segoe UI", 14, "bold")
        ).pack(pady=10)

    def ver_comprobante():
        sel = tree.focus()
        if not sel:
            return

        id_nota = tree.item(sel, "values")[0]

        for p in pagos:
            if p.get("nota") == id_nota:
                messagebox.showinfo(
                    "Comprobante",
                    f"Archivo:\n{p.get('comprobante')}",
                    parent=win
                )
                return

        messagebox.showinfo(
            "Sin pago",
            "Esta nota no tiene comprobante",
            parent=win
        )

    frm_btn = ttk.Frame(win)
    frm_btn.pack(pady=5)

    ttk.Button(frm_btn, text="Ver detalle", command=ver_detalle)\
        .pack(side="left", padx=5)

    ttk.Button(frm_btn, text="Ver comprobante", command=ver_comprobante)\
        .pack(side="left", padx=5)

    ttk.Button(frm_btn, text="Cerrar", command=win.destroy)\
        .pack(side="left", padx=5)
