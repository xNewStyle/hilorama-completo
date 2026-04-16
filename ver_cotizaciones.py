import tkinter as tk
import os
import shutil
from tkinter import ttk, simpledialog, messagebox
from notas import listar_cotizaciones, obtener_cotizacion, cambiar_cliente_nota
from notas import actualizar_cotizacion, convertir_cotizacion_a_venta, eliminar_cotizacion, eliminar_nota, guardar_nota_actualizada
from core.almacen_api import descontar_stock, obtener_producto_por_codigo
from clientes import cliente_completo, obtener_cliente_por_id, listar_clientes
from PIL import Image, ImageTk   
from visor_imagen import visor_imagen
from ver_clientes import editar_cliente_por_id
from notas import buscar_nota_por_texto
import platform
from pdf_cotizacion import generar_pdf_cotizacion
import subprocess
from envios_config import calcular_envio, cargar_envios
from ventas_logic import calcular_volumetrico_total
from generar_pdf_venta_premium import generar_pdf_venta_premium
import customtkinter as ctk
from parser_whatsapp import extraer_pedidos
from core.almacen_api import obtener_todos_los_productos, obtener_producto_por_codigo, obtener_precio_venta
from auditoria import registrar_cambio

def seleccionar_o_crear_cliente(parent):

    win = ctk.CTkToplevel(parent)
    win.title("Seleccionar cliente")
    win.geometry("600x600")
    win.grab_set()

    resultado = {"cliente": None}

    buscar_var = tk.StringVar()

    entry = ctk.CTkEntry(
        win,
        textvariable=buscar_var,
        placeholder_text="Buscar cliente o escribir nuevo..."
    )
    entry.pack(fill="x", padx=10, pady=10)

    tree = ttk.Treeview(
        win,
        columns=("ID", "Nombre"),
        show="headings"
    )

    tree.heading("ID", text="ID")
    tree.heading("Nombre", text="Nombre")

    tree.pack(fill="both", expand=True, padx=10, pady=5)

    clientes = listar_clientes()

    def cargar():
        tree.delete(*tree.get_children())

        texto = buscar_var.get().lower()

        for c in clientes:
            if texto in c["nombre"].lower():
                tree.insert(
                    "",
                    "end",
                    values=(c["id"], c["nombre"])
                )

    cargar()

    buscar_var.trace_add("write", lambda *a: cargar())

    def seleccionar():
        sel = tree.focus()

        if sel:
            vals = tree.item(sel)["values"]
            resultado["cliente"] = obtener_cliente_por_id(vals[0])
            win.destroy()
            return

        nombre = buscar_var.get().strip()

        if not nombre:
            return

        from clientes import obtener_o_crear_cliente
        resultado["cliente"] = obtener_o_crear_cliente(nombre)

        win.destroy()

    ctk.CTkButton(
        win,
        text="Seleccionar / Crear",
        command=seleccionar
    ).pack(pady=10)

    win.wait_window()

    return resultado["cliente"]

PASSWORD = "12587987521"
def pedir_password(parent=None):
    if parent is None:
        parent = root
    resultado = {"ok": False}

    modal = ctk.CTkToplevel(parent)
    modal.title("Autorización")
    modal.geometry("350x200")
    modal.grab_set()
    modal.resizable(False, False)

    modal.configure(fg_color="#F3F4F6")

    frame = ctk.CTkFrame(modal, corner_radius=15)
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(
        frame,
        text="🔐 Autorización requerida",
        font=("Segoe UI", 15, "bold")
    ).pack(pady=(10, 5))

    pwd_var = tk.StringVar()

    entry = ctk.CTkEntry(
        frame,
        textvariable=pwd_var,
        show="•",
        placeholder_text="Ingresa contraseña",
        height=35
    )
    entry.pack(fill="x", padx=10, pady=10)
    entry.focus()

    def confirmar():
        if pwd_var.get() == PASSWORD:
            resultado["ok"] = True
            modal.destroy()
        else:
            messagebox.showerror(
                "Error",
                "Contraseña incorrecta",
                parent=modal
            )

    ctk.CTkButton(
        frame,
        text="Confirmar",
        fg_color="#1976D2",
        hover_color="#1565C0",
        command=confirmar
    ).pack(pady=10)

    modal.wait_window()

    return resultado["ok"]

def eliminar_venta_desde_lista(tree, win):

    sel = tree.focus()
    if not sel:
        return

    valores = tree.item(sel, "values")
    id_nota = valores[0]

    nota = obtener_cotizacion(id_nota)
    if not nota:
        return

    # ✅ AHORA PERMITE AMBOS
    if nota["estado"] not in ("VENTA_PENDIENTE", "PAGADA"):
        messagebox.showwarning(
            "Aviso",
            "Solo ventas se pueden eliminar",
            parent=win
        )
        return

    if not pedir_password(win):
        return

    if not messagebox.askyesno(
        "Confirmar",
        "Eliminar venta y devolver stock?",
        parent=win
    ):
        return

    # 🔁 devolver stock
    for item in nota["items"]:
        descontar_stock(
            item["marca"],
            item["hilo"],
            item["codigo"],
           -item["cantidad"]
        )

    registrar_cambio(
        id_nota,
        "Venta eliminada",
        "Se eliminó la venta y se devolvió stock"
    )
    eliminar_nota(id_nota)

    messagebox.showinfo(
        "Eliminado",
        "Venta eliminada correctamente",
        parent=win
    )

    win.destroy()
    abrir_visor(win.master)



def eliminar_cotizacion_desde_lista(tree, win):
    seleccionado = tree.focus()
    if not seleccionado:
        messagebox.showwarning(
            "Selecciona",
            "Selecciona una cotización primero",
            parent=win
        )
        return

    valores = tree.item(seleccionado, "values")
    id_nota = valores[0]

    nota = obtener_cotizacion(id_nota)
    if not nota:
        return

    if nota["estado"] != "COTIZACION":
        messagebox.showerror(
            "No permitido",
            "Solo se pueden eliminar cotizaciones, no ventas",
            parent=win
        )
        return

    if not messagebox.askyesno(
        "Confirmar",
        f"¿Eliminar la cotización {id_nota}?\n\nEsta acción no se puede deshacer.",
        parent=win
    ):
        return

    ok = eliminar_cotizacion(id_nota)

    if ok:
        messagebox.showinfo(
            "Eliminado",
            "Cotización eliminada correctamente",
            parent=win
        )
        win.destroy()   # 👈 cierra visor para evitar inconsistencias
    else:
        messagebox.showerror(
            "Error",
            "No se pudo eliminar la cotización",
            parent=win
        )


# ======================================================
# 🔵 VISOR ZOOM + DRAG
# ======================================================
def crear_visor_imagen(parent, ruta_img):

    import math

    # ===== contenedor moderno =====
    frame = ctk.CTkFrame(
        parent,
        corner_radius=15,
        fg_color="#F8FAFC"   # 🔵 fondo suave moderno
    )
    frame.pack(side="right", fill="both", expand=True, padx=(8, 15), pady=10)

    canvas = tk.Canvas(
        frame,
        bg="#F8FAFC",        # mismo color que card
        highlightthickness=0
    )
    canvas.pack(fill="both", expand=True)

    img_original = Image.open(ruta_img).convert("RGB")

    zoom = 1.0
    canvas.img_ref = None

    offset_x = 0
    offset_y = 0


    # ======================================================
    # 🔵 RENDER CENTRADO
    # ======================================================
    def render():
        nonlocal zoom, offset_x, offset_y

        cw = canvas.winfo_width()
        ch = canvas.winfo_height()

        if cw < 20 or ch < 20:
            frame.after(50, render)
            return

        w = int(img_original.width * zoom)
        h = int(img_original.height * zoom)

        img = img_original.resize((w, h), Image.LANCZOS)
        img_tk = ImageTk.PhotoImage(img)

        canvas.img_ref = img_tk
        canvas.delete("all")

        # 🔥 CENTRAR AUTOMÁTICAMENTE
        x = (cw - w) // 2 + offset_x
        y = (ch - h) // 2 + offset_y

        canvas.create_image(x, y, anchor="nw", image=img_tk)


    # ======================================================
    # 🔵 ZOOM
    # ======================================================
    def zoom_mouse(e):
        nonlocal zoom

        old_zoom = zoom
        zoom *= 1.1 if e.delta > 0 else 0.9
        zoom = max(0.2, min(zoom, 5))

        render()


    # ======================================================
    # 🔵 DRAG LIBRE
    # ======================================================
    def start_drag(e):
        canvas.scan_mark(e.x, e.y)

    def drag(e):
        nonlocal offset_x, offset_y
        offset_x += e.x - canvas._drag_start_x
        offset_y += e.y - canvas._drag_start_y
        canvas._drag_start_x = e.x
        canvas._drag_start_y = e.y
        render()

    def start_drag_mark(e):
        canvas._drag_start_x = e.x
        canvas._drag_start_y = e.y


    canvas.bind("<MouseWheel>", zoom_mouse)
    canvas.bind("<ButtonPress-1>", start_drag_mark)
    canvas.bind("<B1-Motion>", drag)

    frame.after(80, render)





# ======================================================
# 🔵 DETALLE MODERNO
# ======================================================
def ver_detalles(tree, parent):

    sel = tree.focus()
    if not sel:
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)
    cliente = obtener_cliente_por_id(nota["cliente_id"])

    win = ctk.CTkToplevel(parent)
    win.title(f"Detalle {id_nota}")
    win.geometry("1100x720")
    win.configure(fg_color="#F3F4F6")
    win.grab_set()

    # ================= HEADER =================
    header = ctk.CTkFrame(win, corner_radius=12)
    header.pack(fill="x", padx=15, pady=10)

    colores = {
        "COTIZACION": "#6B7280",
        "VENTA_PENDIENTE": "#F59E0B",
        "PAGADA": "#16A34A"
    }

    ctk.CTkLabel(
        header,
        text=nota["estado"],
        fg_color=colores.get(nota["estado"], "#333"),
        text_color="white",
        corner_radius=8,
        padx=12,
        pady=6
    ).pack(side="left", padx=10)

    ctk.CTkLabel(
        header,
        text=f"Pedido #{nota.get('pedido','-')}",
        font=("Segoe UI", 14, "bold")
    ).pack(side="left", padx=15)

    # ================= CLIENTE =================
    direccion = cliente.get("direccion", {})

    direccion_txt = (
        f"{direccion.get('calle','')} {direccion.get('numero_ext','')} "
        f"{direccion.get('colonia','')}, {direccion.get('municipio','')}, "
        f"{direccion.get('estado','')} CP {direccion.get('codigo_postal','')}"
    )

    card_cliente = ctk.CTkFrame(win, corner_radius=12)
    card_cliente.pack(fill="x", padx=15, pady=8)

    ctk.CTkLabel(
        card_cliente,
        text=(
            f"👤 {cliente.get('nombre','')}\n"
            f"📞 {cliente.get('telefono','')}\n"
            f"📍 {direccion_txt}\n"
            f"📝 {direccion.get('referencia','')}"
        ),
        justify="left"
    ).pack(anchor="w", padx=15, pady=10)

    # ================= CONTENIDO =================
    content = ctk.CTkFrame(win, corner_radius=12)
    content.pack(fill="both", expand=True, padx=15, pady=10)

    frame_tabla = ctk.CTkFrame(content)
    frame_tabla.pack(side="left", fill="both", expand=True, padx=(10, 5))

    # ================= PRODUCTOS =================
    cols = ("Código", "Marca", "Hilo", "Color", "Cantidad", "Precio", "Subtotal")


    tree_det = ttk.Treeview(frame_tabla, columns=cols, show="headings")

    for c in cols:
        tree_det.heading(c, text=c)
        tree_det.column(c, anchor="center")

    tree_det.pack(fill="both", expand=True, padx=10, pady=10)

    total_productos = 0

    for p in nota["items"]:
        sub = p["cantidad"] * p["precio"]
        total_productos += sub

        tree_det.insert("", "end", values=(
            p["codigo"],
            p["marca"],
            p["hilo"],
            p.get("color",""),
            p["cantidad"],
            f"${p['precio']:.2f}",
            f"${sub:.2f}"
        ))


    # ================= ENVÍO =================
    import json

    envio = nota.get("envio") or {}

    if isinstance(envio, str):
        try:
           envio = json.loads(envio)
        except:
            envio = {}


    envio_card = ctk.CTkFrame(frame_tabla)
    envio_card.pack(fill="x", padx=10, pady=5)

    ctk.CTkLabel(
        envio_card,
        text=(
            f"🚚 {envio.get('paqueteria','-')} | "
            f"${envio.get('precio',0):.2f} | "
            f"{envio.get('volumetrico','-')} kg\n"
            f"📅 Fecha salida: {nota.get('fecha_envio','-')}"
        )
    ).pack(anchor="w", padx=10, pady=6)

    # ================= TOTALES =================
    total_final = total_productos + envio.get("precio", 0)

    totales = ctk.CTkFrame(frame_tabla)
    totales.pack(fill="x", padx=10, pady=5)

    ctk.CTkLabel(
        totales,
        text=f"TOTAL: ${total_final:.2f}",
        font=("Segoe UI", 16, "bold"),
        text_color="#1976D2"
    ).pack(anchor="e", padx=10, pady=8)

    # ================= COMPROBANTE =================
    ruta = nota.get("comprobante")
    if ruta and os.path.exists(ruta):
        crear_visor_imagen(content, ruta)


    # ================= BOTONES =================

def cambiar_cliente_nota_desde_lista(tree, win):

    sel = tree.focus()
    if not sel:
        return

    id_nota = tree.item(sel, "values")[0]

    cliente = seleccionar_o_crear_cliente(win)

    if not cliente:
        return

    cambiar_cliente_nota(id_nota, cliente)

    registrar_cambio(
        id_nota,
        "Cambio de cliente",
        f"Cliente cambiado a {cliente['nombre']}"
    )

    messagebox.showinfo(
        "Actualizado",
        f"Cliente cambiado a {cliente['nombre']}",
        parent=win
    )

    win.destroy()
    abrir_visor(win.master)

def exportar_pdf_venta_premium(tree, win):
    sel = tree.focus()
    if not sel:
        messagebox.showwarning(
            "Selecciona",
            "Selecciona una venta primero",
            parent=win
        )
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)

    if nota["estado"] not in ("VENTA_PENDIENTE", "PAGADA"):
        messagebox.showwarning(
            "No permitido",
            "Solo se puede exportar PDF premium después de convertir a venta",
            parent=win
        )
        return

    carpeta = "ventas_pdf"
    os.makedirs(carpeta, exist_ok=True)

    ruta_pdf = os.path.join(carpeta, f"{id_nota}_premium.pdf")

    generar_pdf_venta_premium(
        nota,
        ruta_pdf,
        ruta_logo="logo_hilorama.png"
    )

    os.startfile(ruta_pdf)

def exportar_pdf_venta_premium_desde_lista(tree, win):
    sel = tree.focus()
    if not sel:
        messagebox.showwarning(
            "Selecciona",
            "Selecciona una venta primero",
            parent=win
        )
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)
    cliente = obtener_cliente_por_id(nota["cliente_id"])

    if cliente:
        nota["telefono"] = cliente.get("telefono", "")
        nota["direccion"] = cliente.get("direccion", {})

    if not nota:
        messagebox.showerror(
            "Error",
            "No se encontró la nota",
            parent=win
        )
        return

    if nota["estado"] not in ("VENTA_PENDIENTE", "PAGADA"):
        messagebox.showwarning(
            "No permitido",
            "Solo se puede exportar la versión premium después de convertir a venta",
            parent=win
        )
        return

    # 📂 carpeta de ventas premium
    carpeta = "ventas_pdf"
    os.makedirs(carpeta, exist_ok=True)

    ruta_pdf = os.path.join(
        carpeta,
        f"{nota['id']}_premium.pdf"
    )

    generar_pdf_venta_premium(
        nota,
        ruta_pdf,
        ruta_logo="logo_hilorama.png"
    )

    os.startfile(ruta_pdf)

def exportar_imagen_cotizacion_desde_lista(tree, win):
    sel = tree.focus()
    if not sel:
        messagebox.showwarning(
            "Selecciona",
            "Selecciona una cotización",
            parent=win
        )
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)

    if not nota:
        messagebox.showerror(
            "Error",
            "No se encontró la cotización",
            parent=win
        )
        return

    if nota["estado"] != "COTIZACION":
        messagebox.showwarning(
            "No permitido",
            "La imagen solo se puede exportar desde cotizaciones",
            parent=win
        )
        return

    # 📂 carpeta
    carpeta = "cotizaciones_pdf"
    os.makedirs(carpeta, exist_ok=True)

    ruta_pdf = os.path.join(
        carpeta,
        f"{id_nota}.pdf"
    )

    # 🔴 SIEMPRE generar antes de abrir
    generar_pdf_cotizacion(
        nota,
        ruta_pdf,
        ruta_logo="logo_hilorama.png"
    )

    # 🔎 Verificar que sí exista
    if not os.path.exists(ruta_pdf):
        messagebox.showerror(
            "Error",
            "No se pudo generar la cotización",
            parent=win
        )
        return

    os.startfile(ruta_pdf)


def exportar_pdf_cotizacion(id_nota):
    nota = obtener_cotizacion(id_nota)
    if not nota:
        messagebox.showerror("Error", "No se encontró la cotización")
        return

    carpeta = "cotizaciones_pdf"
    os.makedirs(carpeta, exist_ok=True)

    ruta_pdf = os.path.join(carpeta, f"{id_nota}.pdf")

    generar_pdf_cotizacion(
        nota,
        ruta_pdf,
        ruta_logo="logo_hilorama.png"  # si tienes logo
    )

    if not os.path.exists(ruta_pdf):
        messagebox.showerror(
            "Error",
            "El PDF no se pudo generar"
        )
        return

    os.startfile(ruta_pdf)
def exportar_pdf_seleccionada(tree):
    sel = tree.focus()
    if not sel:
        messagebox.showwarning("Selecciona", "Selecciona una cotización")
        return

    id_nota = tree.item(sel, "values")[0]
    exportar_pdf_cotizacion(id_nota)

def abrir_editor_venta(parent, nota):

    ed = ctk.CTkToplevel(parent)
    ed.title(f"Editar venta {nota['id']}")
    ed.geometry("900x600")
    ed.grab_set()
    ed.attributes("-topmost", True)

    frame = ctk.CTkFrame(ed)
    frame.pack(fill="both", expand=True, padx=20, pady=20)
    # ================= CONTEXTO =================
    frame_contexto = ctk.CTkFrame(frame)
    frame_contexto.pack(fill="x", pady=(0,10))

    from core.almacen_api import obtener_marcas, obtener_hilos

    ctk.CTkLabel(frame_contexto, text="Marca").pack(side="left", padx=(0,5))

    combo_marca_contexto = ctk.CTkComboBox(
        frame_contexto,
        values=obtener_marcas(),
        width=150,
        command=lambda value: actualizar_hilos()
    )
    combo_marca_contexto.pack(side="left", padx=(0,10))

    ctk.CTkLabel(frame_contexto, text="Hilo").pack(side="left", padx=(0,5))

    combo_hilo_contexto = ctk.CTkComboBox(
        frame_contexto,
        values=[],
        width=150
    )
    combo_hilo_contexto.pack(side="left")


    def actualizar_hilos(event=None):

        marca = combo_marca_contexto.get()

        if not marca:
            combo_hilo_contexto.configure(values=[])
            combo_hilo_contexto.set("")
            return

        hilos = obtener_hilos(marca)

        combo_hilo_contexto.configure(values=hilos)

        if hilos:
            combo_hilo_contexto.set(hilos[0])
        else:
            combo_hilo_contexto.set("")
    # 🔥 FORZAR CARGA INICIAL
    if combo_marca_contexto.get():
        actualizar_hilos()
    # ================= PRODUCTOS =================
    cols = ("Código", "Cantidad", "Precio", "Subtotal")
    tree_ed = ttk.Treeview(frame, columns=cols, show="headings")

    for c in cols:
        tree_ed.heading(c, text=c)

    tree_ed.pack(fill="both", expand=True, pady=10)


    def cargar_items():
        tree_ed.delete(*tree_ed.get_children())
        for p in nota["items"]:
            tree_ed.insert(
                "",
                "end",
                values=(
                    p["codigo"],
                    p["cantidad"],
                    p["precio"],
                    p["cantidad"] * p["precio"]
                )
            )

    cargar_items()


    # ================= CAMBIAR COMPROBANTE =================
    def cambiar_comprobante():

        if not pedir_password(ed):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=ed)
            return

        def guardar_imagen(ruta):
            os.makedirs("comprobantes", exist_ok=True)

            destino = f"comprobantes/{nota['id']}.png"
            shutil.copy(ruta, destino)

            nota["comprobante"] = destino
            guardar_nota_actualizada(nota)

        visor_imagen(
            parent=ed,
            ruta_inicial=nota.get("comprobante"),
            on_save=guardar_imagen
        )


    # ================= GUARDAR PRODUCTOS =================
    def guardar():

        nuevos = []

        for i in tree_ed.get_children():
            c, q, p, _ = tree_ed.item(i, "values")

            nuevos.append({
                "codigo": c,
                "cantidad": int(q),
                "precio": float(p)
            })

        nota["items"] = nuevos
        guardar_nota_actualizada(nota)

        messagebox.showinfo("Listo", "Venta actualizada", parent=ed)
        ed.destroy()


    # ================= BOTONES =================
    btns = ctk.CTkFrame(ed)
    btns.pack(pady=10)

    ctk.CTkButton(
        btns,
        text="🖼 Cambiar comprobante 🔒",
        fg_color="#5C6BC0",
        command=cambiar_comprobante
    ).pack(side="left", padx=10)

    ctk.CTkButton(
        btns,
        text="💾 Guardar",
        fg_color="#1976D2",
        command=guardar
    ).pack(side="left", padx=10)






# ================= VISOR =================
def abrir_visor(root):

    import datetime
    import customtkinter as ctk

    win = ctk.CTkToplevel(root)
    win.title("Notas / Cotizaciones")
    win.geometry("1500x900")
    win.configure(fg_color="#F5F6FA")
    win.grab_set()
    top = ctk.CTkFrame(win, corner_radius=12)
    top.pack(fill="x", padx=15, pady=10)

    def filtro_input(parent, label, var, width=160, icon=""):
        cont = ctk.CTkFrame(parent, fg_color="transparent")

        ctk.CTkLabel(
            cont,
            text=label,
            font=("Segoe UI", 11)
        ).pack(anchor="w", padx=4)

        ctk.CTkEntry(
            cont,
            textvariable=var,
            width=width,
            height=36,
            placeholder_text=icon,
            corner_radius=10
        ).pack()

        cont.pack(side="left", padx=8, pady=4)


    buscar_var = tk.StringVar()
    pedido_var = tk.StringVar()
    cliente_id_var = tk.StringVar()
    estado_var = tk.StringVar(value="TODOS")


    filtro_input(top, "Cliente o teléfono", buscar_var, 260, "🔎")
    filtro_input(top, "Pedido #", pedido_var, 120, "📦")
    filtro_input(top, "ID cliente", cliente_id_var, 120, "🆔")

    # ================= ESTADO =================
    estado_cont = ctk.CTkFrame(top, fg_color="transparent")

    ctk.CTkLabel(
        estado_cont,
        text="Estado",
        font=("Segoe UI", 11)
    ).pack(anchor="w", padx=4)

    combo_estado = ctk.CTkComboBox(
        estado_cont,
        variable=estado_var,
        values=["TODOS", "HOY", "COTIZACION", "VENTA_PENDIENTE", "PAGADA"],
        width=160,
        height=36,
        corner_radius=10
    )
    combo_estado.pack()

    estado_cont.pack(side="left", padx=8, pady=4)


   
    
    
    # 🔵 TABLA MODERNA
    # ======================================================
    frame_tabla = ctk.CTkFrame(win, corner_radius=12)
    frame_tabla.pack(fill="both", expand=True, padx=15, pady=10)

    style = ttk.Style()
    style.theme_use("default")

    style.configure(
        "Treeview",
        font=("Segoe UI", 12),
        rowheight=36
    )

    cols = (
        "ID",
        "Pedido",
        "Cliente",
        "Teléfono",
        "Fecha",
        "Estado",
        "Total",
        "Envío"
    )

    tree = ttk.Treeview(
        frame_tabla,
        columns=cols,
        show="headings",
        selectmode="browse"
    )

    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, anchor="center")

    tree.pack(fill="both", expand=True)

    # ======================================================
    # 🔵 CARGAR NOTAS
    # ======================================================

    def cargar_notas():
        tree.delete(*tree.get_children())

        texto = buscar_var.get().lower()
        pedido_txt = pedido_var.get().strip()
        estado = estado_var.get()
        cliente_id_txt = cliente_id_var.get().strip()

        hoy = datetime.date.today().isoformat()

        clientes = listar_clientes()

        for n in listar_cotizaciones():

            cliente = next(
                (c for c in clientes if c["id"] == n["cliente_id"]),
                {}
            )
            # 🔹 FILTRO ID CLIENTE ⭐
            if cliente_id_txt and str(cliente.get("id")) != cliente_id_txt:
                continue

            nombre = n.get("cliente_nombre", "").lower()
            tel = cliente.get("telefono", "")

            pedido = str(n.get("pedido", ""))

            fecha = str(n.get("fecha", ""))

            # 🔹 FILTRO CLIENTE/TEL
            if texto and texto not in nombre and texto not in tel:
                continue

            # 🔹 FILTRO PEDIDO
            if pedido_txt and pedido_txt != pedido:
                continue

            # 🔹 FILTRO ESTADO
            if estado == "HOY":
                if len(fecha) >= 10 and not fecha.startswith(hoy):
                    continue
            elif estado != "TODOS" and n["estado"] != estado:
                continue

            import json  # arriba del archivo si no está

            envio = n.get("envio") or {}

            # 🔥 NORMALIZAR (string → dict)
            if isinstance(envio, str):
                try:
                   envio = json.loads(envio)
                except:
                    envio = {}

            envio_txt = (
                f"{envio.get('paqueteria','-')} ${envio.get('precio',0):.2f}"
                if envio else "-"
            )


            tree.insert(
                "",
                "end",
                values=(
                    n["id"],
                    pedido,
                    n["cliente_nombre"],
                    tel,
                    fecha,
                    n["estado"],
                    f"${n['total']:.2f}",
                    envio_txt
                )
            )
    ctk.CTkButton(
        top,
        text="🔎 Filtrar",
        width=140,
        height=36,
        corner_radius=10,
        fg_color="#1976D2",
        hover_color="#1565C0",
        font=("Segoe UI", 12, "bold"),
        command=cargar_notas
    ).pack(side="left", padx=12, pady=(22, 0))
    
    
    buscar_var.trace_add("write", lambda *a: cargar_notas())
    pedido_var.trace_add("write", lambda *a: cargar_notas())
    combo_estado.bind("<<ComboboxSelected>>", lambda e: cargar_notas())

    # ======================================================
    # 🔵 BOTONES LATERALES (FLUJO CORRECTO)
    # ======================================================

    side = ctk.CTkFrame(win, width=220)
    side.pack(fill="y", side="right", padx=10, pady=10)

    def selected_id():
        sel = tree.focus()
        return tree.item(sel, "values")[0] if sel else None

    ctk.CTkButton(
        side,
        text="👁 Ver detalle",
        command=lambda: ver_detalles(tree, win)
    ).pack(fill="x", pady=5)

    ctk.CTkButton(
        side,
        text="✏ Editar",
        command=lambda: editar_cotizacion(win, tree)
    ).pack(fill="x", pady=5)

    ctk.CTkButton(
        side,
        text="👤 Cambiar cliente",
        command=lambda: cambiar_cliente_nota_desde_lista(tree, win)
    ).pack(fill="x", pady=5)

    ctk.CTkButton(
        side,
        text="💰 Marcar pagada",
        fg_color="#2E7D32",
        command=lambda: marcar_como_pagada(tree, win)
    ).pack(fill="x", pady=5)

    btn_exportar = ctk.CTkButton(side, text="📄 Exportar")
    btn_exportar.pack(fill="x", pady=5)

    ctk.CTkButton(
        side,
        text="🗑 Eliminar",
        fg_color="#E53935",
        command=lambda: eliminar_cotizacion_desde_lista(tree, win)
    ).pack(fill="x", pady=5)

    # ======================================================
    # 🔵 EXPORTAR DINÁMICO
    # ======================================================

    def actualizar_exportar(event=None):
        sel = tree.focus()
        if not sel:
            return

        estado = tree.item(sel, "values")[5]

        if estado == "COTIZACION":
            btn_exportar.configure(
                text="📄 Exportar cotización",
                command=lambda: exportar_imagen_cotizacion_desde_lista(tree, win)
            )
        else:
            btn_exportar.configure(
                text="🧾 Exportar venta",
                command=lambda: exportar_pdf_venta_premium_desde_lista(tree, win)
            )

    tree.bind("<<TreeviewSelect>>", actualizar_exportar)

    cargar_notas()
    # ===# ======================================================
# 🔵 BOTÓN CONVERTIR FLOTANTE MODERNO (IZQ-CENTRO)
# ======================================================

    BASE_DIR = os.path.dirname(__file__)

    icon_convert = ctk.CTkImage(
        Image.open(os.path.join(BASE_DIR, "convert.png")),
        size=(150, 150)   # 🔥 más grande
    )

    def convertir_directo_desde_lista():

        sel = tree.focus()
        if not sel:
            messagebox.showwarning("Selecciona", "Selecciona una cotización", parent=win)
            return

        id_nota = tree.item(sel, "values")[0]
        nota = obtener_cotizacion(id_nota)

        if not nota or nota["estado"] != "COTIZACION":
            return


        cliente = obtener_cliente_por_id(nota["cliente_id"])

        if not cliente or not cliente_completo(cliente):

            messagebox.showinfo(
                "Datos incompletos",
                "Completa los datos del cliente para continuar",
                parent=win
            )

            def continuar(cliente_actualizado):
                convertir_directo_desde_lista()   # 🔥 vuelve a intentar automáticamente

            editar_cliente_por_id(
                cliente["id"],
                win,
                on_guardar=continuar
            )

            return

 

        if not nota["items"]:
            messagebox.showwarning("Sin productos", parent=win)
            return


    # =========================
    # ENVÍO
    # =========================
        vol_total = calcular_volumetrico_total(nota["items"])

        envio = seleccionar_envio(win, vol_total)
        if not envio:
            return


    # =========================
    # DESCONTAR STOCK
    # =========================
        for item in nota["items"]:

            if not item:
                messagebox.showerror(
                    "Error crítico",
                    f"El producto {item['codigo']} no existe en almacén.",
                    parent=win
                )
                return

            descontar_stock(
                item["marca"],
                item["hilo"],
                item["codigo"],
                item["cantidad"]
            )




    # =========================
    # CONVERTIR
    # =========================
        ok = convertir_cotizacion_a_venta(
            id_nota,
            nota["items"],
            cliente,
            envio
        )

        if ok:
            messagebox.showinfo("Venta creada", "Convertida correctamente", parent=win)
            cargar_notas()





    btn_convertir = ctk.CTkButton(
        win,
        text="",
        image=icon_convert,
        width=95,
        height=95,

        fg_color="transparent",      # ✅ mismo fondo (fake transparente)
        hover_color="#E8F5E9",  # ✅ color sólido válido

        corner_radius=50,
        border_width=0,

        command=convertir_directo_desde_lista

    )

    btn_convertir.place(
        relx=0.20,   # 👉 más derecha
        rely=0.88,   # 👉 más abajo (centrado visual)
        anchor="center"
    )
     
      
    # =====================================================
    # 🔵 ICONO EDITAR VENTA 🔒
    # =====================================================

    icon_editar = ctk.CTkImage(
       Image.open(os.path.join(BASE_DIR, "edit_sale.png")),
       size=(150, 150)
    )


    def editar_venta_desde_lista(tree, win):

        if not pedir_password(win):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=win)
            return

        sel = tree.focus()
        if not sel:
            return

        id_nota = tree.item(sel, "values")[0]
        nota = obtener_cotizacion(id_nota)

        if not nota:
            return


        # =====================================================
        # 🔵 VENTANA MODERNA
        # =====================================================
        ed = ctk.CTkToplevel(win)
        ed.title(f"Editar venta {id_nota}")
        ed.geometry("1100x650")
        ed.grab_set()
        ed.lift()
        ed.attributes("-topmost", True)
        ed.after(200, lambda: ed.attributes("-topmost", False))

 
        # =====================================================
        # 🔵 TABLA PRODUCTOS
        # =====================================================
        frame = ctk.CTkFrame(ed)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        # ================= CONTEXTO =================
        frame_contexto = ctk.CTkFrame(frame)
        frame_contexto.pack(fill="x", pady=(0,10))

        from core.almacen_api import obtener_marcas, obtener_hilos

        ctk.CTkLabel(frame_contexto, text="Marca").pack(side="left", padx=(0,5))

        combo_marca_contexto = ctk.CTkComboBox(
            frame_contexto,
            values=obtener_marcas(),
            width=150,
            command=lambda value: actualizar_hilos()
        )
        combo_marca_contexto.pack(side="left", padx=(0,10))

        ctk.CTkLabel(frame_contexto, text="Hilo").pack(side="left", padx=(0,5))

        combo_hilo_contexto = ctk.CTkComboBox(
            frame_contexto,
            values=[],
            width=150
        )
        combo_hilo_contexto.pack(side="left")


        def actualizar_hilos(event=None):

            marca = combo_marca_contexto.get()

            if not marca:
                combo_hilo_contexto.configure(values=[])
                combo_hilo_contexto.set("")
                return

            hilos = obtener_hilos(marca)

            combo_hilo_contexto.configure(values=hilos)

            if hilos:
                combo_hilo_contexto.set(hilos[0])
            else:
                combo_hilo_contexto.set("")
        # 🔥 FORZAR CARGA INICIAL
        if combo_marca_contexto.get():
            actualizar_hilos()        
        # ==========================
        # 🔵 PARSER WHATSAPP
        # ==========================

        frame_parser = ctk.CTkFrame(frame)
        frame_parser.pack(fill="x", pady=(0,10))

        texto_parser = tk.StringVar()

        entry_parser = ctk.CTkEntry(
            frame_parser,
            textvariable=texto_parser,
            placeholder_text="Pegar pedido aquí...",
            height=40
        ) 
        entry_parser.pack(side="left", fill="x", expand=True, padx=(0,8))

        def agregar_producto():
            texto = texto_parser.get().strip()
            if not texto:
                return

            productos = obtener_todos_los_productos()

            marca_ctx = combo_marca_contexto.get().strip().upper()
            hilo_ctx = combo_hilo_contexto.get().strip().upper()

            if marca_ctx:
                productos = [
                    p for p in productos
                    if p["marca"].upper() == marca_ctx
                ]

            if hilo_ctx:
                productos = [
                    p for p in productos
                    if p["hilo"].upper() == hilo_ctx
                ]
            resultado = extraer_pedidos(texto, productos)

            if resultado["errores"]:
                messagebox.showerror(
                    "Error",
                    f"No existen: {', '.join(resultado['errores'])}",
                    parent=ed
                )
                return

            for p in resultado["pedidos"]:

                prod = obtener_producto_por_codigo(p["codigo"])
                if not prod:
                    messagebox.showerror(
                        "Error",
                        f"No existe el producto {p['codigo']}",
                        parent=ed
                    )
                    continue

                precio = obtener_precio_venta(prod["marca"])
                if not precio:
                    messagebox.showerror(
                        "Error",
                        f"No hay precio configurado para la marca {prod['marca']}",
                        parent=ed
                    )
                    continue

                cantidad = p["cantidad"]
                subtotal = cantidad * precio
 
                # 🔥 Si ya existe en tabla → sumar cantidad
                existe = None
                for item in tree_ed.get_children():
                    vals = tree_ed.item(item)["values"]
                    if (
                       str(vals[0]) == str(p["codigo"]) and
                       str(vals[1]) == str(prod["marca"]) and
                       str(vals[2]) == str(prod["hilo"])
                    ):

                        existe = item
                        break

                if existe:
                    vals = list(tree_ed.item(existe)["values"])
                    nueva_cantidad = int(vals[4]) + cantidad
                    nuevo_subtotal = nueva_cantidad * float(vals[5])

                    tree_ed.item(existe, values=(
                        vals[0],
                        vals[1],
                        vals[2],
                        vals[3],
                        nueva_cantidad,
                        vals[5],
                        nuevo_subtotal
                    ))
                else:
                    color = prod.get("color", "")
                    tree_ed.insert("", "end", values=(
                        p["codigo"],
                        prod["marca"],
                        prod["hilo"],
                        color,
                        cantidad,
                        precio,
                        subtotal
                    ))


            texto_parser.set("")
            recalcular()


        ctk.CTkButton(
            frame_parser,
            text="+ Agregar",
            width=110,
           command=agregar_producto
        ).pack(side="right")

        cols = ("Código", "Marca", "Hilo", "Color", "Cantidad", "Precio", "Subtotal")


        tree_ed = ttk.Treeview(
            frame,
            columns=cols,
            show="headings",
            selectmode="extended"   # 🔥 clave
        )

        for c in cols:
            tree_ed.heading(c, text=c)
            tree_ed.column(c, anchor="center")

        tree_ed.pack(fill="both", expand=True)


        for p in nota["items"]:
            tree_ed.insert("", "end", values=(
                p["codigo"],
                p["marca"],
                p["hilo"],
                p.get("color",""),
                p["cantidad"],
                p["precio"],
                p["cantidad"] * p["precio"]
            ))



        # =====================================================
        # 🔵 TOTAL
        # =====================================================
        lbl_total = ctk.CTkLabel(ed, font=("Segoe UI", 26, "bold"))
        lbl_total.pack(pady=8)


        def recalcular():
            total = 0
            for i in tree_ed.get_children():
                _, _, _, _, _, sub = tree_ed.item(i, "values")

                total += float(sub)

            envio = nota.get("envio", {}).get("precio", 0)
            total += envio

            lbl_total.configure(text=f"TOTAL: ${total:.2f}")


        recalcular()


        # =====================================================
        # 🔵 ACCIONES PRODUCTOS
        # =====================================================
        def editar_celda_cantidad(event):

            item = tree_ed.identify_row(event.y)
            col = tree_ed.identify_column(event.x)

            # Columna Cantidad (#5)
            if not item or col != "#5":
                return

            x, y, width, height = tree_ed.bbox(item, col)

            valores = list(tree_ed.item(item, "values"))
            valor_actual = valores[4]

            spin = tk.Spinbox(
                tree_ed,
                from_=1,
                to=9999,
                justify="center",
                font=("Segoe UI", 11)
            )

            spin.place(x=x, y=y, width=width, height=height)
            spin.delete(0, "end")
            spin.insert(0, valor_actual)
            spin.focus()
            spin.selection_range(0, "end")

            def guardar(event=None):
                try:
                    nueva = int(spin.get())
                    if nueva <= 0:
                        raise ValueError
                except:
                    spin.destroy()
                    return

                valores[4] = nueva
                valores[6] = round(nueva * float(valores[5]), 2)

                tree_ed.item(item, values=valores)
 
                spin.destroy()
                recalcular()

            spin.bind("<Return>", guardar)
            spin.bind("<FocusOut>", guardar)


        def editar_celda_precio(event):

            item = tree_ed.identify_row(event.y)
            col = tree_ed.identify_column(event.x)

            # Columna Precio (#6)
            if not item or col != "#6":
                return

            if not pedir_password(ed):
                return

            x, y, width, height = tree_ed.bbox(item, col)

            valores = list(tree_ed.item(item, "values"))
            valor_actual = valores[5]

            spin = tk.Spinbox(
                tree_ed,
                from_=0.01,
                to=9999,
                increment=0.50,
                format="%.2f",
                justify="center",
                font=("Segoe UI", 11)
            )

            spin.place(x=x, y=y, width=width, height=height)
            spin.delete(0, "end")
            spin.insert(0, valor_actual)
            spin.focus()
            spin.selection_range(0, "end")

            def guardar(event=None):
                try:
                    nuevo = float(spin.get())
                    if nuevo <= 0:
                        raise ValueError
                except:
                    spin.destroy()
                    return

                valores[5] = round(nuevo, 2)
                valores[6] = round(float(valores[4]) * nuevo, 2)

                tree_ed.item(item, values=valores)

                spin.destroy()
                recalcular()

            spin.bind("<Return>", guardar)
            spin.bind("<FocusOut>", guardar)

        def editar_celda(event):
            col = tree_ed.identify_column(event.x)

            if col == "#5":
                editar_celda_cantidad(event)
            elif col == "#6":
                editar_celda_precio(event)

        tree_ed.bind("<Double-1>", editar_celda)
        def cambiar_precio_seleccion():

            items = tree_ed.selection()
            if not items:
                return

            if not pedir_password(ed):
                return

            nuevo = simpledialog.askfloat(
                "Precio múltiple",
                "Nuevo precio para productos seleccionados:",
                parent=ed,
                minvalue=0.01
            )

            if nuevo is None:
                return

            for item in items:
                vals = list(tree_ed.item(item, "values"))
                vals[5] = round(nuevo, 2)
                vals[6] = round(vals[4] * nuevo, 2)
                tree_ed.item(item, values=vals)

            recalcular()
        def cambiar_precio_por_contexto():

            marca_ctx = combo_marca_contexto.get().strip().upper()
            hilo_ctx = combo_hilo_contexto.get().strip().upper()

            if not marca_ctx or not hilo_ctx:
                return

            if not pedir_password(ed):
                return

            nuevo = simpledialog.askfloat(
                "Precio por grupo",
                f"Nuevo precio para {marca_ctx} / {hilo_ctx}:",
                parent=ed,
                minvalue=0.01
            )

            if nuevo is None:
                return

            for item in tree_ed.get_children():
                vals = list(tree_ed.item(item, "values"))

                if vals[1].upper() == marca_ctx and vals[2].upper() == hilo_ctx:
                    vals[5] = round(nuevo, 2)
                    vals[6] = round(vals[4] * nuevo, 2)
                    tree_ed.item(item, values=vals)

            recalcular()
        def eliminar_item():
            tree_ed.delete(tree_ed.focus())
            recalcular()


        # =====================================================
        # 🔵 ENVÍO
        # =====================================================
        def editar_envio():
            vol = calcular_volumetrico_total(nota["items"])
            envio = seleccionar_envio(ed, vol)

            if not envio:
                return

            nota["envio"] = envio
            recalcular()

            registrar_cambio(
                nota["id"],
                "Cambio de envío",
                f"{envio['paqueteria']} - ${envio['precio']}"
            )

       # =====================================================
       # 🔵 CAMBIAR COMPROBANTE
       # =====================================================
        def cambiar_comprobante():
            if not pedir_password(ed):
                return

            from visor_imagen import visor_imagen

            visor_imagen(
                parent=ed,
                ruta_inicial=nota.get("comprobante"),
                on_save=lambda r: nota.update({"comprobante": r})
            )
            registrar_cambio(
                nota["id"],
                "Cambio de comprobante",
                "Se actualizó imagen de comprobante"
            )

        # =====================================================
        # 🔵 ELIMINAR VENTA
        # =====================================================
        def eliminar_venta():
            if not pedir_password(ed):
                return

            if not messagebox.askyesno("Confirmar", "Eliminar venta y devolver stock?", parent=ed):
                return

            eliminar_venta_desde_lista(tree, win)


        # =====================================================
        # 🔵 GUARDAR CAMBIOS
        # =====================================================
        def guardar():

            # 🔵 1. Guardar estado original
            originales = {
                (item["codigo"], item["marca"], item["hilo"]): item["cantidad"]
                for item in nota["items"]
            }


            # 🔵 2. Construir nuevos items
            nuevos = []
            actuales = {}

            for i in tree_ed.get_children():
                codigo, marca, hilo, color, cantidad, precio, _ = tree_ed.item(i, "values")


                cantidad = int(cantidad)

                nuevos.append({
                    "codigo": codigo,
                    "marca": marca,
                    "hilo": hilo,
                    "color": color,
                    "cantidad": int(cantidad),
                    "precio": float(precio)
                })

                actuales[(codigo, marca, hilo)] = int(cantidad)

            # 🔵 3. Ajustar stock SOLO si NO es cotización
            if nota["estado"] != "COTIZACION":

                todas_claves = set(originales.keys()) | set(actuales.keys())

                for clave in todas_claves:

                    cantidad_original = originales.get(clave, 0)
                    cantidad_nueva = actuales.get(clave, 0)

                    diferencia = cantidad_nueva - cantidad_original

                    if diferencia != 0:

                        codigo, marca, hilo = clave

                        # Ajustar stock
                        descontar_stock(
                            marca,
                            hilo,
                            codigo,
                            diferencia
                        )

                        # Registrar cambio
                        registrar_cambio(
                            nota["id"],
                            "Cambio de cantidad",
                            f"{marca} {hilo} {codigo} | {cantidad_original} → {cantidad_nueva}"
                        )
                            
            
            # 🔵 4. Recalcular total real
            total = 0
            for item in nuevos:
                total += item["cantidad"] * item["precio"]

            envio_precio = nota.get("envio", {}).get("precio", 0)
            total += envio_precio

            nota["total"] = round(total, 2)

            # 🔥 1. Actualizar items en tabla items
            actualizar_cotizacion(nota["id"], nuevos)

            # 🔥 2. Actualizar datos generales (total, envio, comprobante, etc)
            guardar_nota_actualizada(nota)



            ed.destroy()
            cargar_notas()



        # =====================================================
        # 🔵 BOTONES
        # =====================================================
        btn_frame = ctk.CTkFrame(ed)
        btn_frame.pack(pady=10)

        def b(t, c, f):
            return ctk.CTkButton(btn_frame, text=t, fg_color=c, command=f)
        b("💲 Precio por hilo 🔒", "#5C6BC0", cambiar_precio_por_contexto).pack(side="left", padx=5)
        b("💲 Precio selección 🔒", "#7986CB", cambiar_precio_seleccion).pack(side="left", padx=5)
        b("Eliminar item", "#E57373", eliminar_item).pack(side="left", padx=5)
        b("Envío", "#64B5F6", editar_envio).pack(side="left", padx=5)
        b("Comprobante 🔒", "#9575CD", cambiar_comprobante).pack(side="left", padx=5)
        b("Eliminar venta 🔒", "#D32F2F", eliminar_venta).pack(side="left", padx=5)
        b("Guardar", "#2E7D32", guardar).pack(side="left", padx=5)



    btn_editar = ctk.CTkButton(
        win,
        text="",
        image=icon_editar,
        fg_color="transparent",
        hover_color="#E3F2FD",
        width=95,
        height=95,
        corner_radius=50,
        border_width=0,
        command=lambda: editar_venta_desde_lista(tree, win)

    )

    btn_editar.place(
        relx=0.40,   # 👉 al lado del convertir
        rely=0.88,
        anchor="center"
    )

    
    
       
    
       
         
           
                                   
def editar_cotizacion(win, tree):

    seleccionado = tree.focus()
    if not seleccionado:
        return

    id_nota = tree.item(seleccionado, "values")[0]

    nota = obtener_cotizacion(id_nota)
    if not nota or nota["estado"] != "COTIZACION":
        return


    # ======================================================
    # 🔵 VENTANA MODERNA
    # ======================================================
    ed = ctk.CTkToplevel(win)
    ed.title(f"Editar {id_nota}")
    ed.geometry("1500x650")
    ed.configure(fg_color="#F3F4F6")
    ed.grab_set()


    # ======================================================
    # 🔵 LAYOUT 2 COLUMNAS
    # ======================================================
    main = ctk.CTkFrame(ed, fg_color="transparent")
    main.pack(fill="both", expand=True, padx=20, pady=20)

    main.grid_columnconfigure(0, weight=4)
    main.grid_columnconfigure(1, weight=1)
    main.grid_rowconfigure(0, weight=1)


    # ======================================================
    # 🔵 CARD TABLA
    # ======================================================
    card_tabla = ctk.CTkFrame(main, corner_radius=18)
    card_tabla.grid(row=0, column=0, sticky="nsew", padx=(0, 10))


    ctk.CTkLabel(
        card_tabla,
        text="Productos",
        font=("Segoe UI", 18, "bold")
    ).pack(anchor="w", padx=20, pady=(15, 5))
    # ================= BUSCADOR PRODUCTOS =================
    frame_buscar = ctk.CTkFrame(card_tabla, fg_color="transparent")
    frame_buscar.pack(fill="x", padx=20, pady=(0, 10))

    buscar_codigo_var = tk.StringVar()

    entry_buscar = ctk.CTkEntry(
        frame_buscar,
        textvariable=buscar_codigo_var,
        placeholder_text="Código producto...",
        height=36
    )
    entry_buscar.pack(side="left", fill="x", expand=True, padx=(0, 8))
    # ================= CONTEXTO =================
    frame_contexto = ctk.CTkFrame(card_tabla, fg_color="transparent")
    frame_contexto.pack(fill="x", padx=20, pady=(0, 10))

    ctk.CTkLabel(frame_contexto, text="Marca").pack(side="left", padx=(0,5))

    from core.almacen_api import obtener_marcas, obtener_hilos
    
    combo_marca_contexto = ctk.CTkComboBox(
        frame_contexto,
        values=obtener_marcas(),
        width=150,
        command=lambda value: actualizar_hilos()
    )
    combo_marca_contexto.pack(side="left", padx=(0,10))

    ctk.CTkLabel(frame_contexto, text="Hilo").pack(side="left", padx=(0,5))

    combo_hilo_contexto = ctk.CTkComboBox(
        frame_contexto,
        values=[],
        width=150
    )
    combo_hilo_contexto.pack(side="left")

    def actualizar_hilos(event=None):
        marca = combo_marca_contexto.get()

        if not marca:
            combo_hilo_contexto.configure(values=[])
            combo_hilo_contexto.set("")
            return

        hilos = obtener_hilos(marca)

        combo_hilo_contexto.configure(values=hilos)

        if hilos:
            combo_hilo_contexto.set(hilos[0])
        else:
            combo_hilo_contexto.set("")
    

    if combo_marca_contexto.get():
        actualizar_hilos()

    def agregar_producto():
        texto = buscar_codigo_var.get().strip()

        if not texto:
            return

        # 🔥 obtener todos los productos del sistema
        from core.almacen_api import obtener_todos_los_productos
        productos = obtener_todos_los_productos()

        marca_ctx = combo_marca_contexto.get().strip().upper()
        hilo_ctx = combo_hilo_contexto.get().strip().upper()

        if marca_ctx:
           productos = [p for p in productos if p["marca"].upper() == marca_ctx]

        if hilo_ctx:
           productos = [p for p in productos if p["hilo"].upper() == hilo_ctx]

        resultado = extraer_pedidos(texto, productos)
 
        if resultado["errores"]:
            messagebox.showerror(
                "Error",
                f"No existe el producto {resultado['errores'][0]}",
                parent=ed
            )
            return

        for item in resultado["pedidos"]:
            codigo = item["codigo"]
            cantidad = item["cantidad"]

            codigo = str(codigo).strip()

            prod = next((p for p in productos if str(p["codigo"]) == codigo), None)

            if not prod:
                messagebox.showerror(
                    "Error",
                    f"No existe el producto {codigo}",
                    parent=ed
                )
                continue

            color = prod.get("color")

            if not color:
                color = prod.get("COLOR", "")

            # verificar si ya existe en tabla
            existe = False

            for i in tree_ed.get_children():
                vals = tree_ed.item(i, "values")

                if (
                    str(vals[0]) == codigo and
                    str(vals[1]) == prod["marca"] and
                    str(vals[2]) == prod["hilo"]
                ):

                    nueva_cant = int(vals[4]) + cantidad
                    precio = float(vals[5])
                    color = prod.get("color", "")
                    tree_ed.item(i, values=(
                        codigo,
                        prod["marca"],
                        prod["hilo"],
                        color,
                        nueva_cant,
                        precio,
                        nueva_cant * precio
                    ))

                    existe = True
                    break

            if not existe:
                precio = obtener_precio_venta(prod["marca"]) or 0
                color = prod.get("color", "")
                tree_ed.insert(
                    "",
                    "end",
                    values=(
                        codigo,
                        prod["marca"],
                        prod["hilo"],
                        color,
                        cantidad,
                        precio,
                        cantidad * precio
                    )
                )


        recalcular_total()
        buscar_codigo_var.set("")



    ctk.CTkButton(
        frame_buscar,
        text="➕ Agregar",
        width=120,
        command=agregar_producto
    ).pack(side="right")

    entry_buscar.bind("<Return>", lambda e: agregar_producto())



    frame_tabla = tk.Frame(card_tabla)
    frame_tabla.pack(fill="both", expand=True, padx=15, pady=10)


    cols = ("Código", "Marca", "Hilo", "Color", "Cantidad", "Precio", "Subtotal")


    tree_ed = ttk.Treeview(
        frame_tabla,
        columns=cols,
        show="headings",
        selectmode="extended"   # 🔥 permite selección múltiple
    )

    for c in cols:
        tree_ed.heading(c, text=c)
        tree_ed.column(c, anchor="center")

    tree_ed.pack(fill="both", expand=True)


    # ======================================================
    # 🔵 CARD RESUMEN DERECHO
    # ======================================================
    card_resumen = ctk.CTkFrame(main, corner_radius=18)
    card_resumen.grid(row=0, column=1, sticky="nsew")


    lbl_total = ctk.CTkLabel(
        card_resumen,
        text="$0.00",
        font=("Segoe UI", 34, "bold"),
        text_color="#1976D2"
    )
    lbl_total.pack(pady=(25, 15))
    

    # ======================================================
    # 🔵 FUNCIONES AUX
    # ======================================================
    def recalcular_total():
        total = 0
        for i in tree_ed.get_children():
            _, _, _, _, _, _, sub = tree_ed.item(i, "values")
            total += float(sub)
        lbl_total.configure(text=f"${total:.2f}")


    # ======================================================
    # 🔵 CARGAR ITEMS
    # ======================================================
    for p in nota["items"]:
        tree_ed.insert("", "end", values=(
            p["codigo"],
            p["marca"],
            p["hilo"],
            p.get("color", ""),
            p["cantidad"],
            p["precio"],
            p["cantidad"] * p["precio"]
        ))


    recalcular_total()


    # ======================================================
    # 🔵 ACCIONES
    # ======================================================
    def cambiar_cantidad():
        item = tree_ed.focus()
        if not item:
            return

        nueva = simpledialog.askinteger("Cantidad", "Nueva cantidad:", parent=ed)
        if nueva is None:
            return

        vals = list(tree_ed.item(item, "values"))
        vals[4] = nueva
        vals[6] = nueva * float(vals[5])

        tree_ed.item(item, values=vals)
        recalcular_total()


    def eliminar_item():
        item = tree_ed.focus()
        if item:
            tree_ed.delete(item)
            recalcular_total()


    def cambiar_precio():
     item = tree_ed.focus()
     if not item:
        return

    # 🔒 contraseña SOLO aquí
     pwd = simpledialog.askstring(
        "Autorización",
        "Ingresa la contraseña:",
        parent=ed,
        show="*"
    )
     if pwd != PASSWORD:
        messagebox.showerror(
            "Error",
            "Contraseña incorrecta",
            parent=ed
        )
        return

     nuevo = simpledialog.askfloat(
        "Precio",
        "Nuevo precio unitario:",
        parent=ed,
        minvalue=0.01
    )
     if nuevo is None:
        return

     vals = list(tree_ed.item(item, "values"))

     vals[5] = round(float(nuevo), 2)
     vals[6] = round(float(vals[4]) * float(nuevo), 2)

     tree_ed.item(item, values=vals)

    def cambiar_precio_seleccion():

        items = tree_ed.selection()
        if not items:
            return

        if not pedir_password(ed):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=ed)
            return

        nuevo = simpledialog.askfloat(
            "Precio múltiple",
            "Nuevo precio para productos seleccionados:",
            parent=ed,
            minvalue=0.01
        )

        if nuevo is None:
            return

        for item in items:
            vals = list(tree_ed.item(item, "values"))

            vals[5] = round(float(nuevo), 2)
            vals[6] = round(int(vals[4]) * float(nuevo), 2)

            tree_ed.item(item, values=vals)

        recalcular_total()
    def cambiar_precio_por_contexto():

        marca_ctx = combo_marca_contexto.get().strip().upper()
        hilo_ctx = combo_hilo_contexto.get().strip().upper()
 
        if not marca_ctx or not hilo_ctx:
            messagebox.showwarning(
                "Contexto incompleto",
                "Selecciona marca e hilo",
                parent=ed
            )
            return

        if not pedir_password(ed):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=ed)
            return

        nuevo = simpledialog.askfloat(
            "Precio por grupo",
            f"Nuevo precio para {marca_ctx} / {hilo_ctx}:",
            parent=ed,
            minvalue=0.01
        ) 

        if nuevo is None:
            return

        cambios = 0

        for item in tree_ed.get_children():

            vals = list(tree_ed.item(item, "values"))

            if (
                vals[1].upper() == marca_ctx and
                vals[2].upper() == hilo_ctx
            ):
                vals[5] = round(float(nuevo), 2)
                vals[6] = round(int(vals[4]) * float(nuevo), 2)

                tree_ed.item(item, values=vals)
                cambios += 1

        recalcular_total()

        messagebox.showinfo(
            "Actualizado",
            f"Precio aplicado a {cambios} productos",
            parent=ed
        )
    def editar_celda_cantidad(event):

        item = tree_ed.identify_row(event.y)
        col = tree_ed.identify_column(event.x)

        # Solo columna Cantidad (#5)
        if not item or col != "#5":
            return

        x, y, width, height = tree_ed.bbox(item, col)

        valores = list(tree_ed.item(item, "values"))
        valor_actual = valores[4]

        # 🔥 Spinbox con flechas
        spin = tk.Spinbox(
            tree_ed,
            from_=1,
            to=9999,
            width=5,
            justify="center",
            font=("Segoe UI", 11)
        )

        spin.place(x=x, y=y, width=width, height=height)
        spin.delete(0, "end")
        spin.insert(0, valor_actual)
        spin.focus()
        spin.selection_range(0, "end")

        def guardar(event=None):
            try:
                nueva = int(spin.get())
                if nueva <= 0:
                    raise ValueError
            except:
                spin.destroy()
                return

            valores[4] = nueva                         # cantidad
            valores[6] = round(nueva * float(valores[5]), 2)  # subtotal

            tree_ed.item(item, values=valores)

            spin.destroy()
            recalcular_total()

        spin.bind("<Return>", guardar)
        spin.bind("<FocusOut>", guardar)   

    def editar_celda(event):

        col = tree_ed.identify_column(event.x)

        if col == "#5":        # Cantidad
            editar_celda_cantidad(event)

        elif col == "#6":      # Precio
            cambiar_precio()

    def guardar():
        nuevos = []
        for i in tree_ed.get_children():
            c, marca, hilo, color, q, p, _ = tree_ed.item(i, "values")

            nuevos.append({
                "codigo": c,
                "marca": marca,
                "hilo": hilo,
                "color": color,
                "cantidad": int(q),
                "precio": float(p)
            })


        actualizar_cotizacion(id_nota, nuevos)

        ed.destroy()
        win.destroy()
        abrir_visor(win.master)


    # doble click = cantidad
    tree_ed.bind("<Double-1>", editar_celda)


    # ======================================================
    # 🔵 BOTONES MODERNOS (VERTICALES)
    # ======================================================
    def btn(texto, color, cmd):
        return ctk.CTkButton(
            card_resumen,
            text=texto,
            height=42,
            corner_radius=14,
            fg_color=color,
            command=cmd
        )
    

    def convertir_a_venta():
        cliente = obtener_cliente_por_id(nota["cliente_id"])
        if not cliente:
            messagebox.showerror("Error", "Cliente no encontrado", parent=ed)
            return

        envio = None  # ← siempre existe

        def continuar_conversion(cliente_actualizado):
            nonlocal envio

            # 1️⃣ Recolectar items
            items_finales = []
            for i in tree_ed.get_children():
                codigo, marca, hilo, color, cantidad, precio, _ = tree_ed.item(i, "values")

                items_finales.append({
                    "codigo": codigo,
                    "marca": marca,
                    "hilo": hilo,
                    "color": color,
                    "cantidad": int(cantidad),
                    "precio": float(precio)
                })


            if not items_finales:
                messagebox.showwarning(
                    "Vacío",
                    "La cotización no tiene productos",
                    parent=ed
                )
                return

            # 2️⃣ Calcular volumétrico y seleccionar envío
            if envio is None:
                vol_total = calcular_volumetrico_total(items_finales)
                envio_sel = seleccionar_envio(ed, vol_total)
                if not envio_sel:
                    return
                envio = envio_sel

            # 3️⃣ Guardar envío en la nota
            nota["envio"] = envio

            # 4️⃣ Descontar stock
            for item in items_finales:
                
                if not item:
                    messagebox.showerror(
                        "Error",
                        f"No existe el producto {item['codigo']}",
                        parent=ed
                    )
                    return

                descontar_stock(
                    item["marca"],
                    item["hilo"],
                    item["codigo"],
                    item["cantidad"]
                )


            # 5️⃣ Convertir cotización → venta (GUARDA TODO)
            ok = convertir_cotizacion_a_venta(
                id_nota,
                items_finales,
                cliente_actualizado,
                envio
            )

            if not ok:
                messagebox.showerror(
                    "Error",
                    "No se pudo convertir la nota",
                    parent=ed
                )
                return

            messagebox.showinfo(
                "Venta creada",
                "Venta registrada como PENDIENTE DE PAGO",
                parent=ed
            )
            if ok:
                registrar_cambio(
                    id_nota,
                    "Cambio de estado",
                    "COTIZACION → VENTA_PENDIENTE"
                )
            ed.destroy()
            win.destroy()
            abrir_visor(win.master)

    # 🔁 Si cliente incompleto → editar y continuar
        if not cliente_completo(cliente):
            messagebox.showinfo(
                "Datos incompletos",
                "Completa los datos del cliente para continuar",
                parent=ed
            )

            editar_cliente_por_id(
            cliente["id"],
            ed,
            on_guardar=continuar_conversion
            )
            return

        # ✅ Cliente completo
        continuar_conversion(cliente)  

    

    def configurar_envio_cotizacion():
        items = []

        for i in tree_ed.get_children():
            codigo, marca, hilo, color, cantidad, precio, _ = tree_ed.item(i, "values")

            items.append({
                "codigo": codigo,
                "marca": marca,
                "hilo": hilo,
                "color": color,
                "cantidad": cantidad,
                "precio": precio
            })

        if not items:
            messagebox.showwarning(
                "Sin productos",
                "Agrega productos primero",
                parent=ed
            )
            return

        vol_total = calcular_volumetrico_total(items)

        envio = seleccionar_envio(ed, vol_total)
        if not envio:
            return

        nota["envio"] = envio

        # 🔥 recalcular total
        total_productos = 0
        for item in items:
            total_productos += float(item["cantidad"]) * float(item["precio"])

        nota["total"] = round(total_productos + envio["precio"], 2)

        guardar_nota_actualizada(nota)

        cargar_envios()
        messagebox.showinfo(
            "Envío guardado",
            f"{envio['paqueteria']} • ${envio['precio']:.2f} • {vol_total:.2f} kg",
            parent=ed
        )


    btn("✏️ Cantidad", "#A0A8CC", cambiar_cantidad).pack(fill="x", padx=20, pady=4)
    btn("💲 Precio 🔒", "#90A2C5", cambiar_precio).pack(fill="x", padx=20, pady=4)
    btn("🗑 Eliminar", "#DF959D", eliminar_item).pack(fill="x", padx=20, pady=4)
    btn("💲 Precio selección 🔒", "#7986CB", cambiar_precio_seleccion)\
        .pack(fill="x", padx=20, pady=4)

    btn("💲 Precio por hilo 🔒", "#5C6BC0", cambiar_precio_por_contexto)\
        .pack(fill="x", padx=20, pady=4)

    ctk.CTkFrame(card_resumen, height=2, fg_color="#E5E7EB").pack(fill="x", padx=20, pady=10)

    btn("🚚 Envío", "#A2C3DB", configurar_envio_cotizacion).pack(fill="x", padx=20, pady=4)
    btn("💾 Guardar", "#1976D2", guardar).pack(fill="x", padx=20, pady=4)
    btn("🧾 Convertir 🔒", "#43A047", convertir_a_venta).pack(fill="x", padx=20, pady=4)
    # ======================================================
    # 🔵 ENVÍO MANUAL INTEGRADO (DEBAJO DE BOTONES)
    # ======================================================

    ctk.CTkFrame(card_resumen, height=2, fg_color="#E5E7EB").pack(fill="x", padx=20, pady=12)

    ctk.CTkLabel(
        card_resumen,
        text="🚚 Envío manual",
        font=("Segoe UI", 13, "bold")
    ).pack(anchor="w", padx=22, pady=(4, 6))


    frame_manual = ctk.CTkFrame(card_resumen)
    frame_manual.pack(fill="x", padx=20, pady=(0, 12))


    precio_manual_var = tk.StringVar()


    entry_manual = ctk.CTkEntry(
        frame_manual,
        textvariable=precio_manual_var,
        placeholder_text="Precio $",
        width=120
    )
    entry_manual.pack(side="left", fill="x", expand=True, padx=(0, 8))


    def aplicar_envio_manual():

        if not pedir_password(ed):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=ed)
            return

        try:
            precio = float(precio_manual_var.get())
        except:
            messagebox.showwarning("Valor inválido", "Ingresa un número válido", parent=ed)
            return

        nota["envio"] = {
            "paqueteria": "MANUAL",
            "precio": round(precio, 2),
            "volumetrico": 0,
            "manual": True
        }

        guardar_nota_actualizada(nota)

        messagebox.showinfo(
            "Actualizado",
            f"Envío manual aplicado: ${precio:.2f}",
            parent=ed
        )


    ctk.CTkButton(
        frame_manual,
        text="🔒 Aplicar",
        width=90,
        fg_color="#EF5350",
        hover_color="#D32F2F",
        command=aplicar_envio_manual
    ).pack(side="right")

   

    

from tkinter import filedialog
import shutil

def marcar_como_pagada(tree, win):
    sel = tree.focus()
    if not sel:
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)

    if nota["estado"] != "VENTA_PENDIENTE":
        messagebox.showwarning(
            "Aviso",
            "La venta no está pendiente de pago",
            parent=win
        )
        return

    # ✅ ESTA FUNCIÓN DEBE IR ANTES
    def guardar_imagen(ruta_imagen):
        os.makedirs("comprobantes", exist_ok=True)

        ext = os.path.splitext(ruta_imagen)[1].lower()
        destino = f"comprobantes/{id_nota}{ext}"

        shutil.copy(ruta_imagen, destino)

        nota["estado"] = "PAGADA"
        nota["comprobante"] = destino
        guardar_nota_actualizada(nota)

        messagebox.showinfo(
            "Pago confirmado",
            "La venta fue marcada como PAGADA",
            parent=win
        )
        registrar_cambio(
            id_nota,
            "Cambio de estado",
            "VENTA_PENDIENTE → PAGADA"
        )
        win.destroy()
        abrir_visor(win.master)

    # 🔍 ABRIR VISOR CON DRAG & DROP
    visor_imagen(
    parent=win,
    ruta_inicial=nota.get("comprobante"),
    on_save=guardar_imagen
)



def ver_comprobante(tree, win):
    sel = tree.focus()
    if not sel:
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)

    if nota["estado"] != "PAGADA" or "comprobante" not in nota:
        messagebox.showwarning("Aviso", "No hay comprobante", parent=win)
        return

    visor_imagen(win, ruta_inicial=nota["comprobante"])
def mostrar_detalle_nota(nota, parent):
    det = tk.Toplevel(parent)
    det.title(f"Nota {nota['id']}")
    det.geometry("600x500")

    ttk.Label(
        det,
        text=f"Cliente: {nota['cliente_nombre']}",
        font=("Segoe UI", 11, "bold")
    ).pack(anchor="w", padx=10)

    ttk.Label(det, text=f"Fecha: {nota['fecha']}").pack(anchor="w", padx=10)
    ttk.Label(det, text=f"Estado: {nota['estado']}").pack(anchor="w", padx=10)

    cols = ("Código", "Marca", "Hilo", "Color", "Cantidad", "Precio", "Subtotal")

    tree = ttk.Treeview(det, columns=cols, show="headings")

    for c in cols:
        tree.heading(c, text=c)

    tree.pack(fill="both", expand=True, padx=10, pady=10)

    for p in nota["items"]:
        tree.insert(
            "",
            "end",
            values=(
                p["codigo"],
                p["marca"],
                p["hilo"],
                p.get("color"),
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

import customtkinter as ctk

def seleccionar_envio(root, volumetrico):

    win = ctk.CTkToplevel(root)
    win.title("Configurar envío")
    win.geometry("340x370")
    win.grab_set()

    win.configure(fg_color="white")

    resultado = {}

    frame = ctk.CTkFrame(win, corner_radius=15, fg_color="white")
    frame.pack(fill="both", expand=True, padx=20, pady=20)


    # ===== TÍTULO =====
    ctk.CTkLabel(
        frame,
        text="Paquetería",
        font=("Segoe UI", 14, "bold")
    ).pack(pady=(10, 5))


    # 🔥 cargar opciones dinámicas desde envios_config.json
    envios = cargar_envios()
    opciones = list(envios.keys())

    paq_var = tk.StringVar(value=opciones[0])

    combo = ctk.CTkComboBox(
        frame,
        variable=paq_var,
        values=opciones,
        height=35,
        corner_radius=10
    )

    combo.pack(fill="x", padx=20, pady=5)


    # ===== PRECIO =====
    precio_var = tk.StringVar(value="$0.00")

    lbl_precio = ctk.CTkLabel(
        frame,
        textvariable=precio_var,
        font=("Segoe UI", 16, "bold")
    )
    lbl_precio.pack(pady=10)


    # ===== CHECK GRATIS =====
    gratis_var = tk.BooleanVar()
    manual_var = tk.BooleanVar()

    check = ctk.CTkCheckBox(
        frame,
        text="Envío gratis",
        variable=gratis_var
    )
    check.pack(pady=5)

    manual_check = ctk.CTkCheckBox(
        frame,
        text="Precio manual",
        variable=manual_var
    )
    manual_check.pack(pady=5)

    # ===== CALCULAR =====

    def recalcular(*args):

        if gratis_var.get():
            precio_var.set("$0.00")
            return

        if manual_var.get():
           return

        precio = calcular_envio(
            paq_var.get(),
            volumetrico
        ) 

        precio_var.set(f"${precio:.2f}")

    # ======================================================
    #  🔴 ENVÍO MANUAL INTEGRADO (NUEVO)
    # ======================================================

    ctk.CTkFrame(frame, height=2, fg_color="#E5E7EB").pack(fill="x", padx=20, pady=10)

    ctk.CTkLabel(
        frame,
        text="Precio manual",
        font=("Segoe UI", 12, "bold")
    ).pack(pady=(0, 5))


    manual_frame = ctk.CTkFrame(frame, fg_color="transparent")
    manual_frame.pack(fill="x", padx=20, pady=(0, 8))


    precio_manual_var = tk.StringVar()

    entry_manual = ctk.CTkEntry(
        manual_frame,
        textvariable=precio_manual_var,
        placeholder_text="Precio $",
        width=120
    )
    entry_manual.pack(side="left", fill="x", expand=True, padx=(0, 6))


    def aplicar_manual():

        if not pedir_password(win):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=win)
            return

        try:
            precio = float(manual_var.get())
        except:
            messagebox.showwarning("Valor inválido", "Número incorrecto", parent=win)
            return

        resultado.update({
            "paqueteria": paq_var.get(),   # ✅ mantener paquetería elegida
            "precio": round(precio, 2),    # ✅ solo cambiar precio
            "volumetrico": volumetrico,
            "manual": True                 # opcional para control interno
        })

        win.destroy()



    ctk.CTkButton(
        manual_frame,
        text="🔒",
        width=40,
        fg_color="#EF5350",
        hover_color="#D32F2F",
        command=aplicar_manual
    ).pack(side="right")


    # ===== BOTÓN CONFIRMAR =====
    def confirmar():

        if gratis_var.get():
            precio = 0
 
        elif manual_var.get():

            try:
                precio = float(precio_manual_var.get())
            except:
                messagebox.showwarning(
                    "Error",
                    "Precio manual inválido",
                    parent=win
                )
                return

        else:

            precio = calcular_envio(
                paq_var.get(),
                volumetrico
            )

        resultado.update({
            "paqueteria": paq_var.get(),
            "precio": precio,
            "volumetrico": volumetrico
        })

        win.destroy()
  
    ctk.CTkButton(
        frame,
        text="Confirmar",
        fg_color="#1976D2",
        hover_color="#1565C0",
        height=40,
        corner_radius=12,
        command=confirmar
    ).pack(fill="x", padx=20, pady=(20, 10))

    # 🔥 ESTO ES LO QUE FALTA
    paq_var.trace_add("write", recalcular)
    gratis_var.trace_add("write", recalcular)

    recalcular()

    win.wait_window()   # ← 🔴 CLAVE ABSOLUTA

    return resultado if resultado else None





    

    


    





