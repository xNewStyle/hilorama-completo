import tkinter as tk
from tkinter import ttk

try:
    from ..utils.logger import log_error, log_info
except ImportError:
    from utils.logger import log_error, log_info


def crear_vista_almacen(parent):
    hijos_antes = set(parent.winfo_children())
    log_info("almacen", "Iniciando carga de vista Almacen")

    try:
        from almacen_colores import construir_interfaz

        log_info("almacen", "Modulo almacen_colores importado correctamente")
        contenedor, interior = _crear_area_scroll(parent)
        modulo = construir_interfaz(interior)
        _montar_modulo(interior, modulo)
        log_info("almacen", "Vista Almacen creada correctamente")
        return contenedor
    except Exception as exc:
        log_error("almacen", "Error al cargar o crear la vista Almacen", exc)
        for child in parent.winfo_children():
            if child not in hijos_antes:
                try:
                    child.destroy()
                except tk.TclError as destroy_exc:
                    log_error("almacen", "Error al limpiar vista Almacen fallida", destroy_exc)
        return _crear_error_view(parent, exc)


def _crear_area_scroll(parent):
    contenedor = ttk.Frame(parent)
    contenedor.columnconfigure(0, weight=1)
    contenedor.rowconfigure(0, weight=1)

    canvas = tk.Canvas(
        contenedor,
        borderwidth=0,
        highlightthickness=0,
        background="#F4F5F7",
    )
    scroll_y = ttk.Scrollbar(contenedor, orient="vertical", command=canvas.yview)
    scroll_x = ttk.Scrollbar(contenedor, orient="horizontal", command=canvas.xview)
    canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    canvas.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")
    scroll_x.grid_remove()

    interior = tk.Frame(canvas, bg="#F4F5F7")
    ventana = canvas.create_window((0, 0), window=interior, anchor="nw")

    def actualizar_scroll(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def ajustar_tamano(event):
        ancho_requerido = interior.winfo_reqwidth()
        ancho_visible = max(1, event.width)
        alto = max(event.height, interior.winfo_reqheight())
        ancho = ancho_visible if ancho_requerido <= ancho_visible else ancho_requerido

        canvas.itemconfigure(ventana, width=ancho, height=alto)
        if ancho_requerido > ancho_visible + 24:
            scroll_x.grid()
        else:
            canvas.xview_moveto(0)
            scroll_x.grid_remove()
        actualizar_scroll()

    def mover_vertical(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def mover_horizontal(event):
        canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def activar_scroll(_event):
        canvas.bind_all("<MouseWheel>", mover_vertical)
        canvas.bind_all("<Shift-MouseWheel>", mover_horizontal)

    def desactivar_scroll(_event):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Shift-MouseWheel>")

    def limpiar_scroll(_event):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Shift-MouseWheel>")

    interior.bind("<Configure>", actualizar_scroll)
    canvas.bind("<Configure>", ajustar_tamano)
    canvas.bind("<Enter>", activar_scroll)
    canvas.bind("<Leave>", desactivar_scroll)
    canvas.bind("<Destroy>", limpiar_scroll)
    return contenedor, interior


def _montar_modulo(parent, modulo):
    if modulo is None:
        return
    if getattr(modulo, "master", None) is parent and not modulo.winfo_manager():
        modulo.pack(fill="both", expand=True)


def _crear_error_view(parent, exc):
    frame = ttk.Frame(parent, padding=32)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    contenido = ttk.Frame(frame, padding=28)
    contenido.grid(row=0, column=0)

    ttk.Label(
        contenido,
        text="Almacen",
        font=("Segoe UI", 22, "bold"),
    ).pack(pady=(0, 12))
    ttk.Label(
        contenido,
        text="No se pudo abrir el modulo de almacen.",
        font=("Segoe UI", 12),
    ).pack(pady=(0, 8))
    ttk.Label(
        contenido,
        text="Revise la conexion y la configuracion local antes de intentar de nuevo.",
        font=("Segoe UI", 10),
    ).pack()
    ttk.Label(
        contenido,
        text=str(exc),
        font=("Segoe UI", 9),
        foreground="#6B7280",
    ).pack(pady=(12, 0))
    return frame
