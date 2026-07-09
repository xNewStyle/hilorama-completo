"""Dialogos modernos pequenos para flujos criticos de Hilorama Desktop."""

import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - fallback para entornos sin customtkinter
    ctk = None


def _centrar(win, parent, ancho=620, alto=520):
    win.update_idletasks()
    try:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + max((pw - ancho) // 2, 20)
        y = py + max((ph - alto) // 2, 20)
    except Exception:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max((sw - ancho) // 2, 20)
        y = max((sh - alto) // 2, 20)
    win.geometry(f"{ancho}x{alto}+{x}+{y}")


def _crear_modal(parent, titulo, ancho=620, alto=520):
    base = ctk.CTkToplevel(parent) if ctk else tk.Toplevel(parent)
    base.title(titulo)
    base.transient(parent)
    base.grab_set()
    base.configure(bg="#F3F4F6")
    _centrar(base, parent, ancho, alto)
    return base


def _label(parent, text, **kwargs):
    if ctk:
        return ctk.CTkLabel(parent, text=text, **kwargs)
    return tk.Label(parent, text=text, bg="#F3F4F6", **kwargs)


def _button(parent, text, command, primary=False):
    if ctk:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color="#1976D2" if primary else "#6B7280",
            hover_color="#1565C0" if primary else "#4B5563",
            height=38,
            corner_radius=10,
        )
    return tk.Button(parent, text=text, command=command)


def alerta_moderna(parent, titulo, mensaje, boton="Aceptar"):
    win = _crear_modal(parent, titulo, 520, 260)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)
    _label(cont, titulo, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
    _label(cont, mensaje, justify="left", wraplength=450).pack(anchor="w", padx=18, pady=(0, 18))
    _button(cont, boton, win.destroy, primary=True).pack(anchor="e", padx=18, pady=(0, 18))
    win.wait_window()


def confirmar_moderno(parent, titulo, mensaje, confirmar="Continuar", cancelar="Cancelar"):
    resultado = {"ok": False}
    win = _crear_modal(parent, titulo, 540, 280)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)
    _label(cont, titulo, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
    _label(cont, mensaje, justify="left", wraplength=470).pack(anchor="w", padx=18, pady=(0, 18))
    acciones = ctk.CTkFrame(cont, fg_color="transparent") if ctk else tk.Frame(cont, bg="#F3F4F6")
    acciones.pack(fill="x", padx=18, pady=(0, 18))

    def aceptar():
        resultado["ok"] = True
        win.destroy()

    _button(acciones, cancelar, win.destroy).pack(side="right", padx=(8, 0))
    _button(acciones, confirmar, aceptar, primary=True).pack(side="right")
    win.wait_window()
    return resultado["ok"]


def confirmar_cambio_masivo(
    parent,
    titulo,
    accion,
    marca=None,
    hilo=None,
    cantidad=None,
    valor_nuevo=None,
    advertencia="Este cambio afectara varios productos. Revisa antes de continuar.",
):
    detalles = []
    if accion:
        detalles.append(("Accion", accion))
    if marca:
        detalles.append(("Marca", marca))
    if hilo:
        detalles.append(("Hilo", hilo))
    if cantidad is not None:
        detalles.append(("Productos afectados", str(cantidad)))
    if valor_nuevo is not None:
        detalles.append(("Valor nuevo", str(valor_nuevo)))

    resultado = {"ok": False}
    win = _crear_modal(parent, titulo, 620, 390)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)

    _label(cont, titulo, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
    _label(cont, advertencia, justify="left", wraplength=540).pack(anchor="w", padx=18, pady=(0, 14))

    detalle_frame = ctk.CTkFrame(cont, corner_radius=12) if ctk else tk.Frame(cont, bg="white")
    detalle_frame.pack(fill="x", padx=18, pady=(0, 18))
    for etiqueta, valor in detalles:
        fila = ctk.CTkFrame(detalle_frame, fg_color="transparent") if ctk else tk.Frame(detalle_frame, bg="white")
        fila.pack(fill="x", padx=14, pady=4)
        _label(fila, f"{etiqueta}:", font=("Segoe UI", 10, "bold")).pack(side="left")
        _label(fila, valor, wraplength=360, justify="left").pack(side="left", padx=(8, 0))

    acciones = ctk.CTkFrame(cont, fg_color="transparent") if ctk else tk.Frame(cont, bg="#F3F4F6")
    acciones.pack(fill="x", padx=18, pady=(0, 18))

    def aceptar():
        resultado["ok"] = True
        win.destroy()

    _button(acciones, "Cancelar", win.destroy).pack(side="right", padx=(8, 0))
    _button(acciones, "Aplicar cambios", aceptar, primary=True).pack(side="right")
    win.wait_window()
    return resultado["ok"]


def confirmar_cambio_tipo_producto(
    parent,
    codigo=None,
    marca=None,
    hilo=None,
    color=None,
    tipo_actual=None,
    tipo_nuevo=None,
    stock_actual=None,
    stock_nuevo=None,
):
    detalles = [
        ("Codigo", codigo or ""),
        ("Marca", marca or ""),
        ("Hilo", hilo or ""),
        ("Color", color or ""),
        ("Tipo actual", tipo_actual or ""),
        ("Tipo nuevo", tipo_nuevo or ""),
        ("Stock actual", "" if stock_actual is None else str(stock_actual)),
        ("Stock nuevo", "" if stock_nuevo is None else str(stock_nuevo)),
    ]

    resultado = {"ok": False}
    win = _crear_modal(parent, "Cambiar tipo de producto", 640, 430)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)

    _label(cont, "Cambiar tipo de producto", font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
    _label(
        cont,
        "Este cambio modifica si el producto cuenta como inventario fisico.",
        justify="left",
        wraplength=560,
    ).pack(anchor="w", padx=18, pady=(0, 14))

    detalle_frame = ctk.CTkFrame(cont, corner_radius=12) if ctk else tk.Frame(cont, bg="white")
    detalle_frame.pack(fill="x", padx=18, pady=(0, 18))
    for etiqueta, valor in detalles:
        fila = ctk.CTkFrame(detalle_frame, fg_color="transparent") if ctk else tk.Frame(detalle_frame, bg="white")
        fila.pack(fill="x", padx=14, pady=4)
        _label(fila, f"{etiqueta}:", font=("Segoe UI", 10, "bold")).pack(side="left")
        _label(fila, valor, wraplength=360, justify="left").pack(side="left", padx=(8, 0))

    acciones = ctk.CTkFrame(cont, fg_color="transparent") if ctk else tk.Frame(cont, bg="#F3F4F6")
    acciones.pack(fill="x", padx=18, pady=(0, 18))

    def aceptar():
        resultado["ok"] = True
        win.destroy()

    _button(acciones, "Cancelar", win.destroy).pack(side="right", padx=(8, 0))
    _button(acciones, "Aplicar cambio", aceptar, primary=True).pack(side="right")
    win.wait_window()
    return resultado["ok"]


def confirmar_anular_tono(parent, producto):
    producto = producto or {}
    detalles = [
        ("Codigo", producto.get("codigo") or ""),
        ("Marca", producto.get("marca") or ""),
        ("Hilo", producto.get("hilo") or ""),
        ("Color", producto.get("color") or ""),
        ("Stock actual", str(producto.get("stock") or 0)),
        ("Estado actual", producto.get("estado") or ""),
    ]

    resultado = {"clave": None}
    win = _crear_modal(parent, "Anular tono", 660, 500)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)

    _label(cont, "Anular tono", font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
    _label(
        cont,
        "Este producto no se borrara fisicamente. Se marcara como anulado para conservar historial.",
        justify="left",
        wraplength=580,
    ).pack(anchor="w", padx=18, pady=(0, 14))

    detalle_frame = ctk.CTkFrame(cont, corner_radius=12) if ctk else tk.Frame(cont, bg="white")
    detalle_frame.pack(fill="x", padx=18, pady=(0, 14))
    for etiqueta, valor in detalles:
        fila = ctk.CTkFrame(detalle_frame, fg_color="transparent") if ctk else tk.Frame(detalle_frame, bg="white")
        fila.pack(fill="x", padx=14, pady=4)
        _label(fila, f"{etiqueta}:", font=("Segoe UI", 10, "bold")).pack(side="left")
        _label(fila, str(valor), wraplength=380, justify="left").pack(side="left", padx=(8, 0))

    clave_var = tk.StringVar()
    _label(cont, "Clave de autorizacion").pack(anchor="w", padx=18, pady=(4, 2))
    entry = ctk.CTkEntry(cont, textvariable=clave_var, show="*", height=36) if ctk else tk.Entry(cont, textvariable=clave_var, show="*")
    entry.pack(fill="x", padx=18, pady=(0, 6))
    error_lbl = _label(cont, "", text_color="#B91C1C" if ctk else None)
    error_lbl.pack(anchor="w", padx=18, pady=(0, 8))

    acciones = ctk.CTkFrame(cont, fg_color="transparent") if ctk else tk.Frame(cont, bg="#F3F4F6")
    acciones.pack(fill="x", padx=18, pady=(0, 18))

    def anular():
        clave = clave_var.get().strip()
        if clave != "1":
            error_lbl.configure(text="Clave incorrecta. No se anulo el producto.")
            entry.focus()
            return
        resultado["clave"] = clave
        win.destroy()

    _button(acciones, "Cancelar", win.destroy).pack(side="right", padx=(8, 0))
    _button(acciones, "Anular", anular, primary=True).pack(side="right")
    entry.focus()
    win.wait_window()
    return resultado["clave"]


def pedir_clave_autorizacion(
    parent,
    titulo="Autorizacion requerida",
    mensaje="Ingresa clave de autorizacion.",
    clave_esperada="1",
):
    resultado = {"ok": False}
    win = _crear_modal(parent, titulo, 600, 330)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)
    _label(cont, titulo, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
    _label(cont, mensaje, justify="left", wraplength=520).pack(anchor="w", padx=18, pady=(0, 14))

    clave_var = tk.StringVar()
    entry = ctk.CTkEntry(cont, textvariable=clave_var, show="*", height=36) if ctk else tk.Entry(cont, textvariable=clave_var, show="*")
    entry.pack(fill="x", padx=18, pady=(0, 6))
    error_lbl = _label(cont, "", text_color="#B91C1C" if ctk else None)
    error_lbl.pack(anchor="w", padx=18, pady=(0, 8))

    acciones = ctk.CTkFrame(cont, fg_color="transparent") if ctk else tk.Frame(cont, bg="#F3F4F6")
    acciones.pack(fill="x", padx=18, pady=(0, 18))

    def autorizar():
        if clave_var.get().strip() == str(clave_esperada):
            resultado["ok"] = True
            win.destroy()
            return
        error_lbl.configure(text="Clave incorrecta. No se realizo ningun cambio.")
        entry.focus()

    _button(acciones, "Cancelar", win.destroy).pack(side="right", padx=(8, 0))
    _button(acciones, "Autorizar", autorizar, primary=True).pack(side="right")
    entry.focus()
    win.wait_window()
    return resultado["ok"]


def _tabla_productos(parent, productos, columnas):
    frame = tk.Frame(parent, bg="white")
    frame.pack(fill="both", expand=True, padx=18, pady=(8, 10))
    tree = ttk.Treeview(frame, columns=[c[0] for c in columnas], show="headings", height=7)
    yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=yscroll.set)
    tree.pack(side="left", fill="both", expand=True)
    yscroll.pack(side="right", fill="y")
    for key, titulo, ancho in columnas:
        tree.heading(key, text=titulo)
        tree.column(key, width=ancho, stretch=True)
    for producto in productos:
        tree.insert("", "end", values=[producto.get(key, "") for key, _, _ in columnas])


def pedir_autorizacion_stock(parent, productos, titulo="Autorizacion por stock", descripcion=None):
    if not productos:
        return True

    resultado = {"ok": False}
    win = _crear_modal(parent, titulo, 780, 560)
    cont = ctk.CTkFrame(win, corner_radius=16) if ctk else tk.Frame(win, bg="#F3F4F6")
    cont.pack(fill="both", expand=True, padx=18, pady=18)

    _label(cont, titulo, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
    _label(
        cont,
        descripcion or "Algunos productos tienen stock bajo o insuficiente.",
        justify="left",
        wraplength=700,
    ).pack(anchor="w", padx=18, pady=(0, 6))

    columnas = [
        ("codigo", "Codigo", 80),
        ("marca", "Marca", 110),
        ("hilo", "Hilo", 120),
        ("color", "Color", 120),
        ("cantidad_solicitada", "Solicitado", 80),
        ("stock_actual", "Stock", 70),
        ("faltante", "Faltante", 80),
        ("estado", "Estado", 140),
    ]
    _tabla_productos(cont, productos, columnas)

    clave_var = tk.StringVar()
    _label(cont, "Clave de autorizacion").pack(anchor="w", padx=18, pady=(4, 2))
    entry = ctk.CTkEntry(cont, textvariable=clave_var, show="*", height=36) if ctk else tk.Entry(cont, textvariable=clave_var, show="*")
    entry.pack(fill="x", padx=18, pady=(0, 6))
    error_lbl = _label(cont, "", text_color="#B91C1C" if ctk else None)
    error_lbl.pack(anchor="w", padx=18, pady=(0, 8))

    acciones = ctk.CTkFrame(cont, fg_color="transparent") if ctk else tk.Frame(cont, bg="#F3F4F6")
    acciones.pack(fill="x", padx=18, pady=(0, 16))

    def autorizar():
        if clave_var.get().strip() == "1":
            resultado["ok"] = True
            win.destroy()
            return
        error_lbl.configure(text="Clave incorrecta. No se realizo ningun cambio.")
        entry.focus()

    _button(acciones, "Cancelar", win.destroy).pack(side="right", padx=(8, 0))
    _button(acciones, "Autorizar", autorizar, primary=True).pack(side="right")
    entry.focus()
    win.wait_window()
    return resultado["ok"]


def pedir_autorizacion_anulacion(parent, nota, items):
    productos = []
    for item in items or []:
        productos.append({
            "codigo": item.get("codigo", ""),
            "marca": item.get("marca", ""),
            "hilo": item.get("hilo", ""),
            "color": item.get("color", ""),
            "cantidad_solicitada": item.get("cantidad", 0),
        })
    return pedir_autorizacion_stock(
        parent,
        productos,
        titulo="Autorizacion para anular nota pagada",
        descripcion=(
            "Esta nota ya fue pagada. Si la anulas se regresara el stock al inventario."
        ),
    )
