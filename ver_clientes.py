import tkinter as tk
from tkinter import ttk, messagebox
from clientes import (
    listar_clientes,
    obtener_cliente_por_id, 
    guardar_cliente

)
from notas import listar_cotizaciones
from cp_api import buscar_codigo_postal
from clientes import normalizar_nombre

# ================= VISOR DE CLIENTES =================

def abrir_clientes(root, cliente=None):

    win = tk.Toplevel(root)
    win.title("Clientes")
    win.geometry("1000x400")

    tree = ttk.Treeview(
        win,
        columns=("ID", "Nombre", "Teléfono", "Notas"),
        show="headings"
    )
    tree.pack(fill="both", expand=True, padx=10, pady=10)

    for c in ("ID", "Nombre", "Teléfono", "Notas"):
        tree.heading(c, text=c)

    clientes = listar_clientes()
    notas = listar_cotizaciones()

    for c in clientes:
        if not isinstance(c, dict):
            continue

        total_notas = len([
            n for n in notas
            if n.get("cliente_id") == c.get("id")
        ])

        tree.insert(
            "",
            "end",
            values=(
                c.get("id"),
                c.get("nombre", ""),
                c.get("telefono", ""),
                total_notas
            )
        )

    ttk.Button(
        win,
        text="Editar cliente",
        command=lambda: editar_cliente(tree, win)
    ).pack(pady=5)


# ================= EDITAR CLIENTE =================

import customtkinter as ctk


def editar_cliente_directo(cliente, parent, on_guardar=None):



 

    direccion = cliente.get("direccion", {})

    # =====================================================
    # 🔵 VENTANA MODERNA
    # =====================================================
    win = ctk.CTkToplevel(parent)
    win.title("Editar cliente")
    win.geometry("560x920")
    win.grab_set()
    win.configure(fg_color="#F3F4F6")
    win.lift()
    win.focus_force()
    win.attributes("-topmost", True)
    win.after(200, lambda: win.attributes("-topmost", False))

    card = ctk.CTkFrame(win, corner_radius=18)
    card.pack(fill="both", expand=True, padx=20, pady=20)

    # =====================================================
    # 🔵 HEADER
    # =====================================================
    ctk.CTkLabel(
        card,
        text="👤 Editar cliente",
        font=("Segoe UI", 20, "bold")
    ).pack(anchor="w", padx=20, pady=(20, 10))

    # =====================================================
    # 🔵 VARIABLES
    # =====================================================
    nombre_var = ctk.StringVar(value=cliente.get("nombre", ""))
    tel_var = ctk.StringVar(value=cliente.get("telefono", ""))

    calle_var = ctk.StringVar(value=direccion.get("calle", ""))
    ext_var = ctk.StringVar(value=direccion.get("numero_ext", ""))
    int_var = ctk.StringVar(value=direccion.get("numero_int", ""))
    cp_var = ctk.StringVar(value=direccion.get("codigo_postal", ""))
    estado_var = ctk.StringVar(value=direccion.get("estado", ""))
    municipio_var = ctk.StringVar(value=direccion.get("municipio", ""))
    colonia_var = ctk.StringVar(value=direccion.get("colonia", ""))
    ref_var = ctk.StringVar(value=direccion.get("referencia", ""))

    # =====================================================
    # 🔵 HELPER INPUT MODERNO
    # =====================================================
    def input(label, var, readonly=False):

        ctk.CTkLabel(card, text=label)\
            .pack(anchor="w", padx=25, pady=(8, 0))

        ctk.CTkEntry(
            card,
            textvariable=var,
            height=40,
            corner_radius=10,
            state="readonly" if readonly else "normal"
        ).pack(fill="x", padx=20)

    # =====================================================
    # 🔵 DATOS PERSONALES
    # =====================================================
    input("Nombre completo", nombre_var)
    input("Teléfono", tel_var)

    # =====================================================
    # 🔵 SECCIÓN DIRECCIÓN
    # =====================================================
    ctk.CTkLabel(
        card,
        text="📍 Dirección",
        font=("Segoe UI", 15, "bold")
    ).pack(anchor="w", padx=20, pady=(18, 5))

    input("Calle", calle_var)

    # =============================
    # 🔵 No. Exterior / Interior
    # =============================
    fila_num = ctk.CTkFrame(card, fg_color="transparent")
    fila_num.pack(fill="x", padx=20, pady=(5, 0))

    # ---- Exterior ----
    col_ext = ctk.CTkFrame(fila_num, fg_color="transparent")
    col_ext.pack(side="left", expand=True, fill="x", padx=(0, 6))

    ctk.CTkLabel(col_ext, text="No. Exterior").pack(anchor="w")

    ctk.CTkEntry(
        col_ext,
        textvariable=ext_var,
        height=40,
        corner_radius=10
    ).pack(fill="x")


    # ---- Interior ----
    col_int = ctk.CTkFrame(fila_num, fg_color="transparent")
    col_int.pack(side="left", expand=True, fill="x", padx=(6, 0))

    ctk.CTkLabel(col_int, text="No. Interior").pack(anchor="w")

    ctk.CTkEntry(
        col_int,
        textvariable=int_var,
        height=40,
        corner_radius=10
    ).pack(fill="x")

    input("Código Postal", cp_var)
    input("Estado", estado_var, True)
    input("Municipio", municipio_var, True)
    input("Colonia", colonia_var)
    input("Referencia", ref_var)

    # =====================================================
    # 🔵 CP DINÁMICO (MISMA LÓGICA)
    # =====================================================
    def on_cp_change(*args):
        cp = cp_var.get().strip()

        if len(cp) < 5:
            estado_var.set("")
            municipio_var.set("")
            colonia_var.set("")
            return

        if not cp.isdigit():
            return

        data = buscar_codigo_postal(cp)

        if not data:
            return

        estado_var.set(data["estado"])
        municipio_var.set(data["municipio"])

        if data["colonias"]:
            colonia_var.set(data["colonias"][0])

    cp_var.trace_add("write", on_cp_change)

    # =====================================================
    # 🔵 GUARDAR (MISMA LÓGICA TUYA)
    # =====================================================
    def guardar():

        nombre_nuevo = nombre_var.get().strip()
        tel_nuevo = tel_var.get().strip()

        if not nombre_nuevo:
            messagebox.showerror("Error", "Nombre obligatorio", parent=win)
            return

        if not tel_nuevo.isdigit() or len(tel_nuevo) != 10:
            messagebox.showerror("Error", "Teléfono inválido", parent=win)
            return

        nombre_norm = normalizar_nombre(nombre_nuevo)

        for c in listar_clientes():
            if c["id"] == cliente["id"]:
                continue

            if c.get("telefono") == tel_nuevo:
                messagebox.showerror("Duplicado", "Teléfono repetido", parent=win)
                return

            if normalizar_nombre(c.get("nombre", "")) == nombre_norm:
                messagebox.showerror("Duplicado", "Nombre repetido", parent=win)
                return

        if not buscar_codigo_postal(cp_var.get()):
            messagebox.showerror("Error", "CP inválido", parent=win)
            return

        cliente["nombre"] = nombre_nuevo
        cliente["telefono"] = tel_nuevo
        cliente["completo"] = True

        cliente["direccion"] = {
            "calle": calle_var.get(),
            "numero_ext": ext_var.get(),
            "numero_int": int_var.get(),
            "colonia": colonia_var.get(),
            "codigo_postal": cp_var.get(),
            "estado": estado_var.get(),
            "municipio": municipio_var.get(),
            "referencia": ref_var.get()
        }

        guardar_cliente(cliente)

        messagebox.showinfo("Listo", "Cliente actualizado", parent=win)
        win.destroy()

        if on_guardar:
            on_guardar(cliente)

    # =====================================================
    # 🔵 BOTONES MODERNOS
    # =====================================================
    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x", padx=20, pady=20)

    ctk.CTkButton(
        btns,
        text="💾 Guardar cambios",
        fg_color="#1976D2",
        height=45,
        corner_radius=12,
        command=guardar
    ).pack(side="left", expand=True, fill="x", padx=(0, 6))

    ctk.CTkButton(
        btns,
        text="Cerrar",
        fg_color="#E0E0E0",
        text_color="black",
        height=45,
        corner_radius=12,
        command=win.destroy
    ).pack(side="left", expand=True, fill="x", padx=(6, 0))


    

def editar_cliente_por_id(id_cliente, parent, on_guardar=None):

    cliente = obtener_cliente_por_id(id_cliente)
    if not cliente:
        return

    editar_cliente_directo(cliente, parent, on_guardar)


    
def editar_cliente(tree, parent, on_guardar=None):

    sel = tree.focus()
    if not sel:
        messagebox.showwarning("Selecciona", "Selecciona un cliente", parent=parent)
        return

    id_cliente = tree.item(sel, "values")[0]

    editar_cliente_por_id(id_cliente, parent, on_guardar)

