import tkinter as tk
import os
import shutil
import json
import urllib.request
import urllib.error
from pathlib import Path
from tkinter import ttk, simpledialog, messagebox, filedialog
from notas import listar_cotizaciones, obtener_cotizacion, cambiar_cliente_nota, calcular_totales_nota
from notas import ajustar_items_nota_pagada_admin, actualizar_cotizacion, actualizar_nota_admin, convertir_cotizacion_a_venta, eliminar_cotizacion, eliminar_nota, guardar_nota_actualizada
from core.almacen_api import STOCK_MINIMO, descontar_stock, obtener_producto_por_codigo
from clientes import cliente_completo, obtener_cliente_por_id, listar_clientes
from PIL import Image, ImageTk   
from visor_imagen import visor_imagen
from ver_clientes import editar_cliente_por_id
from notas import buscar_nota_por_texto
import platform
import datetime
from pdf_cotizacion import generar_pdf_cotizacion
import subprocess
from envios_config import calcular_envio, cargar_envios
from ventas_logic import calcular_volumetrico_total
from generar_pdf_venta_premium import generar_pdf_venta_premium
import customtkinter as ctk
from parser_whatsapp import extraer_pedidos
from core.almacen_api import obtener_todos_los_productos, obtener_producto_por_codigo, obtener_precio_venta
from auditoria import registrar_cambio
from hilorama_desktop.security.authorization import (
    get_admin_override_key,
    is_admin_override_key,
    is_legacy_sales_override_key,
)

BASE_DIR = Path(__file__).resolve().parent
COMPROBANTES_DIR = BASE_DIR / "comprobantes"
EXTENSIONES_COMPROBANTE = (".png", ".jpg", ".jpeg", ".webp", ".pdf")

try:
    from hilorama_desktop.ui.dialogs import (
        alerta_moderna,
        confirmar_moderno,
        pedir_clave_autorizacion,
        pedir_autorizacion_anulacion,
        pedir_autorizacion_stock,
    )
except Exception:
    alerta_moderna = None
    confirmar_moderno = None
    pedir_clave_autorizacion = None
    pedir_autorizacion_anulacion = None
    pedir_autorizacion_stock = None

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE
except Exception:
    HILORAMA_DATA_MODE = "local"


ACCION_NO_DISPONIBLE_API = "Esta acción todavía no está disponible en modo API."


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _bloquear_accion_api(parent=None):
    if not _modo_api():
        return
    messagebox.showwarning("Modo API", ACCION_NO_DISPONIBLE_API, parent=parent)
    raise RuntimeError(ACCION_NO_DISPONIBLE_API)


MENSAJE_COTIZACION_NO_PAGABLE = (
    "No puedes marcar como pagada una cotización. Primero conviértela a venta "
    "y completa los datos de envío."
)
ESTADOS_COTIZACION_NO_PAGABLE = {"COTIZACION", "COTIZACION_PENDIENTE"}
ESTADOS_VENTA_PAGABLE = {"VENTA", "VENTA_PENDIENTE", "EN_PROCESO", "COMPLETA"}
ESTADOS_NOTA_PAGADA_UI = {
    "PAGADA", "EN_PROCESO", "INCOMPLETA", "COMPLETA", "ENVIADO", "VENTA_PAGADA"
}


def _normalizar_estado_pago(estado):
    return str(estado or "").strip().upper().replace("Ó", "O")


def _nota_requiere_stock_pagado_ui(nota):
    if not nota:
        return False
    estado = _normalizar_estado_pago(nota.get("estado"))
    if estado in ESTADOS_NOTA_PAGADA_UI:
        return True
    if nota.get("fecha_pago"):
        return True
    pagos = nota.get("pagos")
    return bool(pagos)


def _validar_nota_pagable_ui(nota, parent=None):
    if not nota:
        messagebox.showwarning("Aviso", "No se encontró la nota seleccionada.", parent=parent)
        return False

    estado = _normalizar_estado_pago(nota.get("estado"))
    if _nota_requiere_stock_pagado_ui(nota):
        messagebox.showwarning("Aviso", "Esta nota ya tiene un pago registrado.", parent=parent)
        return False
    if estado in ESTADOS_COTIZACION_NO_PAGABLE:
        messagebox.showwarning("Aviso", MENSAJE_COTIZACION_NO_PAGABLE, parent=parent)
        return False
    if not _modo_api():
        if estado != "VENTA_PENDIENTE":
            messagebox.showwarning("Aviso", "La venta no está pendiente de pago", parent=parent)
            return False
        return True
    if estado not in ESTADOS_VENTA_PAGABLE:
        messagebox.showwarning("Aviso", "Solo una venta puede marcarse como pagada.", parent=parent)
        return False

    envio = nota.get("envio") or {}
    if isinstance(envio, str):
        try:
            envio = json.loads(envio)
        except Exception:
            envio = {}
    if not isinstance(envio, dict) or not envio:
        messagebox.showwarning(
            "Aviso",
            "Primero completa los datos de envío antes de marcar la venta como pagada.",
            parent=parent
        )
        return False

    cliente = obtener_cliente_por_id(nota.get("cliente_id"))
    if not cliente_completo(cliente):
        messagebox.showwarning(
            "Aviso",
            "Primero completa los datos del cliente y su dirección de envío.",
            parent=parent
        )
        return False

    return True


def _stock_afectado_items_ui(items):
    afectados = []
    for item in items or []:
        codigo = str(item.get("codigo") or "").strip()
        producto = obtener_producto_por_codigo(codigo) if codigo else None
        if producto and producto.get("es_item_cotizacion"):
            continue
        cantidad = int(float(item.get("cantidad") or 0))
        stock_actual = int((producto or {}).get("stock_real", (producto or {}).get("stock", 0)) or 0)
        faltante = max(cantidad - stock_actual, 0)
        estado = None
        if not producto or stock_actual <= 0:
            estado = "STOCK NULO"
            faltante = cantidad
        elif stock_actual < cantidad:
            estado = "STOCK INSUFICIENTE"
        elif stock_actual < STOCK_MINIMO:
            estado = "STOCK BAJO"
            faltante = 0

        if estado:
            afectados.append({
                "codigo": codigo,
                "marca": item.get("marca") or (producto or {}).get("marca") or "",
                "hilo": item.get("hilo") or (producto or {}).get("hilo") or "",
                "color": item.get("color") or (producto or {}).get("color") or "",
                "cantidad_solicitada": cantidad,
                "stock_actual": stock_actual,
                "faltante": faltante,
                "estado": estado,
            })
    return afectados


def _texto_alerta_stock(afectados):
    partes = ["Hay productos con stock bajo o insuficiente:\n"]
    for p in afectados:
        partes.append(
            f"Código {p.get('codigo')} - {p.get('marca')} - {p.get('hilo')} - {p.get('color')}\n"
            f"Solicitado: {p.get('cantidad_solicitada')}\n"
            f"Stock actual: {p.get('stock_actual')}\n"
            f"Faltante: {p.get('faltante')}\n"
            f"Estado: {p.get('estado')}\n"
        )
    partes.append("Para continuar, ingresa clave de autorización.")
    return "\n".join(partes)


def _pedir_autorizacion_stock_si_necesaria(parent, items):
    afectados = _stock_afectado_items_ui(items)
    if not afectados:
        return True, None, []

    if pedir_autorizacion_stock:
        if pedir_autorizacion_stock(parent, afectados):
            return True, get_admin_override_key(), afectados
        return False, None, afectados

    clave = simpledialog.askstring(
        "Autorización por stock",
        _texto_alerta_stock(afectados),
        parent=parent,
        show="*"
    )
    if not is_admin_override_key(clave):
        messagebox.showwarning(
            "Operación cancelada",
            "Clave incorrecta. No se convirtió, no se marcó pagada y no se descontó stock.",
            parent=parent
        )
        return False, None, afectados
    return True, get_admin_override_key(), afectados


def _pagos_detalle_nota(nota):
    pagos = nota.get("pagos")
    if pagos is not None:
        return pagos
    try:
        from pagos import listar_pagos
        return listar_pagos(nota.get("id"))
    except Exception:
        return []


def _agregar_pagos_ctk(parent, nota):
    pagos_card = ctk.CTkFrame(parent, fg_color="#F8FAFC", corner_radius=10)
    pagos_card.pack(fill="x", padx=12, pady=(8, 10))

    ctk.CTkLabel(
        pagos_card,
        text="Pagos registrados",
        font=("Segoe UI", 12, "bold")
    ).pack(anchor="w", padx=10, pady=(8, 3))

    pagos = _pagos_detalle_nota(nota)
    if not pagos:
        ctk.CTkLabel(
            pagos_card,
            text="Sin pagos registrados",
            text_color="#6B7280"
        ).pack(anchor="w", padx=10, pady=(0, 8))
        return

    for pago in pagos:
        fecha = pago.get("fecha") or pago.get("created_at") or ""
        comprobante = pago.get("comprobante") or ""
        texto = f"{fecha} - {comprobante}" if fecha else comprobante or "Pago registrado"
        ctk.CTkLabel(
            pagos_card,
            text=texto,
            justify="left",
            wraplength=310,
            text_color="#374151"
        ).pack(anchor="w", padx=10, pady=2)


def _agregar_pagos_ttk(parent, nota):
    frame = ttk.LabelFrame(parent, text="Pagos registrados")
    frame.pack(fill="x", padx=10, pady=(0, 10))

    pagos = _pagos_detalle_nota(nota)
    if not pagos:
        ttk.Label(frame, text="Sin pagos registrados").pack(anchor="w", padx=8, pady=6)
        return

    for pago in pagos:
        fecha = pago.get("fecha") or pago.get("created_at") or ""
        comprobante = pago.get("comprobante") or ""
        texto = f"{fecha} - {comprobante}" if fecha else comprobante or "Pago registrado"
        ttk.Label(frame, text=texto).pack(anchor="w", padx=8, pady=2)


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
        candidatos.extend([
            f"{stem}{suffix}",
            f"{stem.lower()}{suffix}",
        ])

    for ext in EXTENSIONES_COMPROBANTE:
        candidatos.extend([
            f"{stem}{ext}",
            f"{stem.lower()}{ext}",
        ])

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


def obtener_ruta_destino_comprobante(id_nota, extension=".png"):
    COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)

    ext = str(extension or ".png").lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    return COMPROBANTES_DIR / f"{id_nota}{ext}"


def _ruta_relativa_comprobante(id_nota, extension=".png"):
    ext = str(extension or ".png").lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    return Path("comprobantes") / f"{id_nota}{ext}"


def guardar_comprobante_en_proyecto(id_nota, ruta_origen):
    ext = Path(str(ruta_origen)).suffix.lower() or ".png"
    destino = obtener_ruta_destino_comprobante(id_nota, ext)
    origen = Path(str(ruta_origen)).resolve()
    if origen != destino.resolve():
        shutil.copy(str(origen), str(destino))
    return _ruta_relativa_comprobante(id_nota, ext).as_posix()


def guardar_comprobante_legacy_en_proyecto(nota, ruta_origen):
    nombre_original = _nombre_archivo_comprobante(nota.get("comprobante"))
    stem = Path(nombre_original).stem or str(nota.get("id") or "comprobante")
    ext = Path(str(ruta_origen)).suffix.lower() or Path(nombre_original).suffix.lower() or ".png"

    COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)
    destino = COMPROBANTES_DIR / f"{stem}{ext}"

    origen = Path(str(ruta_origen)).resolve()
    if origen != destino.resolve():
        shutil.copy(str(origen), str(destino))

    return (Path("comprobantes") / destino.name).as_posix()


def _ruta_comprobante_existente(ruta):
    ruta_resuelta = resolver_ruta_comprobante(ruta)
    if ruta_resuelta and ruta_resuelta.exists():
        return str(ruta_resuelta)
    return None


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
        if is_legacy_sales_override_key(
            pwd_var.get(),
            {"accion": "ver_cotizaciones_autorizacion"},
        ):
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
    estado_nota = _normalizar_estado_pago(nota.get("estado"))
    nota_con_stock_pagado = _nota_requiere_stock_pagado_ui(nota)
    estados_anulables = {"COTIZACION", "COTIZACION_PENDIENTE", "VENTA", "VENTA_PENDIENTE", "EN_PROCESO"}
    if estado_nota not in estados_anulables and not nota_con_stock_pagado:
        messagebox.showwarning(
            "Aviso",
            "Solo cotizaciones o ventas se pueden anular",
            parent=win
        )
        return

    if _modo_api():
        autorizacion_stock = None
        if nota_con_stock_pagado:
            autorizado = pedir_autorizacion_anulacion(win, nota, nota.get("items", [])) if pedir_autorizacion_anulacion else pedir_password(win)
            if not autorizado:
                return
            autorizacion_stock = "1"
        else:
            mensaje = f"¿Anular la venta {id_nota}?\n\nNo se tocará stock porque todavía no está pagada."
            confirmado = confirmar_moderno(win, "Anular venta", mensaje, "Anular") if confirmar_moderno else messagebox.askyesno(
                "Confirmar",
                mensaje,
                parent=win
            )
            if not confirmado:
                return

        try:
            eliminar_nota(id_nota, autorizacion_stock=autorizacion_stock)
        except Exception as exc:
            if alerta_moderna:
                alerta_moderna(win, "No se pudo anular", str(exc))
            else:
                messagebox.showerror("Error", f"No se pudo anular la nota.\n\n{exc}", parent=win)
            return

        if alerta_moderna:
            alerta_moderna(win, "Nota anulada", "La nota fue anulada correctamente.")
        else:
            messagebox.showinfo("Anulada", "La nota fue anulada correctamente.", parent=win)
        win.destroy()
        abrir_visor(win.master)
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

    mensaje = f"¿Eliminar la cotización {id_nota}?\n\nEsta acción no se puede deshacer."
    confirmado = confirmar_moderno(win, "Eliminar cotización", mensaje, "Eliminar") if confirmar_moderno else messagebox.askyesno(
        "Confirmar",
        mensaje,
        parent=win
    )
    if not confirmado:
        return

    try:
        ok = eliminar_cotizacion(id_nota)
    except Exception as exc:
        messagebox.showerror("Error", f"No se pudo eliminar/anular la cotización.\n\n{exc}", parent=win)
        return

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
    frame.pack(fill="both", expand=True, padx=(8, 15), pady=10)

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
            f"${calcular_totales_nota(nota)['envio_precio']:.2f} | "
            f"{envio.get('volumetrico','-')} kg\n"
            f"📅 Fecha salida: {nota.get('fecha_envio','-')}"
        )
    ).pack(anchor="w", padx=10, pady=6)

    # ================= TOTALES =================
    totales_nota = calcular_totales_nota(nota)

    totales = ctk.CTkFrame(frame_tabla)
    totales.pack(fill="x", padx=10, pady=5)

    ctk.CTkLabel(
        totales,
        text=(
            f"Subtotal productos: ${totales_nota['subtotal_productos']:.2f}\n"
            f"Envío: ${totales_nota['envio_precio']:.2f}\n"
            f"Total final: ${totales_nota['total_final']:.2f}"
        ),
        font=("Segoe UI", 16, "bold"),
        text_color="#1976D2",
        justify="right"
    ).pack(anchor="e", padx=10, pady=8)

    # ================= COMPROBANTE =================
    comprobante_card = ctk.CTkFrame(content)
    comprobante_card.pack(side="right", fill="both", padx=(5, 10), pady=10)
    comprobante_card.configure(width=360)
    comprobante_card.pack_propagate(False)

    ctk.CTkLabel(
        comprobante_card,
        text="Comprobante de pago",
        font=("Segoe UI", 14, "bold")
    ).pack(anchor="w", padx=12, pady=(10, 4))

    _agregar_pagos_ctk(comprobante_card, nota)

    ruta_original = nota.get("comprobante")
    ruta_resuelta = resolver_ruta_comprobante(ruta_original)
    nombre_buscado = _nombre_archivo_comprobante(ruta_original)
    ruta_esperada = (
        (COMPROBANTES_DIR / nombre_buscado).resolve()
        if nombre_buscado else ruta_resuelta
    )

    def buscar_comprobante_legacy():
        ruta_seleccionada = filedialog.askopenfilename(
            parent=win,
            title="Buscar comprobante",
            filetypes=[
                ("Comprobantes", "*.png *.jpg *.jpeg *.webp *.pdf"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not ruta_seleccionada:
            return

        nota_actualizada = obtener_cotizacion(nota["id"]) or nota
        nota_actualizada["comprobante"] = guardar_comprobante_legacy_en_proyecto(
            nota_actualizada,
            ruta_seleccionada
        )
        guardar_nota_actualizada(nota_actualizada)

        messagebox.showinfo(
            "Comprobante vinculado",
            "El comprobante se copió a la carpeta del programa y la nota quedó actualizada.",
            parent=win
        )
        win.destroy()
        ver_detalles(tree, parent)

    def copiar_ruta_esperada():
        win.clipboard_clear()
        win.clipboard_append(str(ruta_esperada or ""))
        messagebox.showinfo(
            "Ruta copiada",
            "La ruta esperada se copió al portapapeles.",
            parent=win
        )

    if ruta_resuelta and ruta_resuelta.exists():
        if ruta_resuelta.suffix.lower() == ".pdf":
            ctk.CTkLabel(
                comprobante_card,
                text=f"Comprobante PDF registrado:\n{ruta_resuelta}",
                justify="left",
                wraplength=320,
                text_color="#374151"
            ).pack(anchor="w", padx=12, pady=10)
        else:
            crear_visor_imagen(comprobante_card, str(ruta_resuelta))
    elif ruta_original:
        ctk.CTkLabel(
            comprobante_card,
            text=(
                "Esta nota tiene un comprobante registrado, pero el archivo no se encontró. "
                "Puede ser una nota antigua o el archivo no fue copiado al programa nuevo.\n\n"
                f"Ruta guardada original:\n{ruta_original}\n\n"
                f"Ruta esperada actual:\n{ruta_esperada}\n\n"
                f"Nombre buscado:\n{nombre_buscado or '-'}"
            ),
            justify="left",
            wraplength=320,
            text_color="#B45309"
        ).pack(anchor="w", padx=12, pady=10)

        acciones_comprobante = ctk.CTkFrame(comprobante_card, fg_color="transparent")
        acciones_comprobante.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(
            acciones_comprobante,
            text="Buscar comprobante",
            command=buscar_comprobante_legacy
        ).pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            acciones_comprobante,
            text="Copiar ruta esperada",
            fg_color="#6B7280",
            hover_color="#4B5563",
            command=copiar_ruta_esperada
        ).pack(fill="x")
    else:
        ctk.CTkLabel(
            comprobante_card,
            text="Sin comprobante registrado",
            justify="left",
            text_color="#6B7280"
        ).pack(anchor="w", padx=12, pady=10)


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

    if (
        _normalizar_estado_pago(nota.get("estado")) != "VENTA_PENDIENTE"
        and not _nota_requiere_stock_pagado_ui(nota)
    ):
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

    if (
        _normalizar_estado_pago(nota.get("estado")) != "VENTA_PENDIENTE"
        and not _nota_requiere_stock_pagado_ui(nota)
    ):
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
            try:
                destino_relativo = guardar_comprobante_en_proyecto(nota["id"], ruta)
                nota["comprobante"] = destino_relativo
                guardar_nota_actualizada(nota)
                messagebox.showinfo(
                    "Comprobante guardado",
                    "El comprobante se guardó correctamente.",
                    parent=ed
                )
            except Exception as exc:
                messagebox.showerror(
                    "Error",
                    f"No se pudo guardar el comprobante.\n\n{exc}",
                    parent=ed
                )
                raise

        visor_imagen(
            parent=ed,
            ruta_inicial=_ruta_comprobante_existente(nota.get("comprobante")),
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
        "Subtotal",
        "Envio",
        "Total final"
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
        notas_lista = listar_cotizaciones()

        # 🔥 ORDEN GENERAL:
        # - PAGADAS: primero por fecha_pago, si no existe usa fecha.
        # - COTIZACIONES / PENDIENTES: por fecha de creación.
        # Así lo más reciente siempre sale arriba y lo más antiguo abajo,
        # no solo cuando filtras PAGADA.
        def fecha_orden(n):
            if _nota_requiere_stock_pagado_ui(n):
                return str(n.get("fecha_pago") or n.get("fecha") or "")
            return str(n.get("fecha") or "")

        notas_lista = sorted(
            notas_lista,
            key=fecha_orden,
            reverse=True
        )

        for n in notas_lista:

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

            fecha = (
                str(n.get("fecha_pago") or n.get("fecha", ""))
                if _nota_requiere_stock_pagado_ui(n)
                else str(n.get("fecha", ""))
            )

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

            totales_nota = calcular_totales_nota(n)

            envio_txt = (
                f"{envio.get('paqueteria','-')} ${totales_nota['envio_precio']:.2f}"
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
                    f"${totales_nota['subtotal_productos']:.2f}",
                    envio_txt,
                    f"${totales_nota['total_final']:.2f}"
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

    ctk.CTkButton(
        side,
        text="🔄 Sincronizar ingresos",
        fg_color="#1976D2",
        command=lambda: sincronizar_pendientes_contabilidad(win, silencioso=False)
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
    win.after(1200, lambda: sincronizar_pendientes_contabilidad(win, silencioso=True))
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

        autorizacion_stock = None
        if _modo_api():
            ok_stock, autorizacion_stock, _ = _pedir_autorizacion_stock_si_necesaria(win, nota["items"])
            if not ok_stock:
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

            if _modo_api():
                continue

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
            envio,
            autorizacion_stock=autorizacion_stock
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

        sel = tree.focus()
        if not sel:
            return

        id_nota = tree.item(sel, "values")[0]
        nota = obtener_cotizacion(id_nota)

        if not nota:
            return

        nota_pagada = _nota_requiere_stock_pagado_ui(nota)
        clave_admin_pagada = None

        if nota_pagada:
            mensaje_autorizacion = (
                "Esta nota ya está pagada. Los cambios de productos, cantidades "
                "o precios ajustarán stock y totales. Ingresa clave de autorización."
            )
            autorizado = pedir_clave_autorizacion(
                win,
                "Editor admin de nota pagada",
                mensaje_autorizacion,
                get_admin_override_key(),
            ) if pedir_clave_autorizacion else simpledialog.askstring(
                "Autorizacion",
                f"{mensaje_autorizacion}\n\nClave temporal:",
                show="*",
                parent=win,
            ) == get_admin_override_key()
            if not autorizado:
                return
            clave_admin_pagada = get_admin_override_key()
        elif not pedir_password(win):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=win)
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
            if bloquear_edicion_productos_pagada():
                return

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
                *_, sub = tree_ed.item(i, "values")

                total += float(sub)

            envio = nota.get("envio", {}).get("precio", 0)
            total += envio

            lbl_total.configure(text=f"TOTAL: ${total:.2f}")


        recalcular()

        MENSAJE_ITEMS_PAGADA = (
            "Esta nota ya está pagada. Los cambios de productos o cantidades "
            "se guardan con ajuste administrativo de stock."
        )

        def bloquear_edicion_productos_pagada():
            return False

        def snapshot_items(items):
            normalizados = []
            for item in items or []:
                normalizados.append((
                    str(item.get("codigo") or ""),
                    str(item.get("marca") or ""),
                    str(item.get("hilo") or ""),
                    str(item.get("color") or ""),
                    int(float(item.get("cantidad") or 0)),
                    round(float(item.get("precio") or 0), 2),
                ))
            return sorted(normalizados)

        snapshot_original_pagada = snapshot_items(nota.get("items", []))


        # =====================================================
        # 🔵 ACCIONES PRODUCTOS
        # =====================================================
        def editar_celda_cantidad(event):
            if bloquear_edicion_productos_pagada():
                return

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
            if bloquear_edicion_productos_pagada():
                return

            item = tree_ed.identify_row(event.y)
            col = tree_ed.identify_column(event.x)

            # Columna Precio (#6)
            if not item or col != "#6":
                return

            if not nota_pagada and not pedir_password(ed):
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
            if bloquear_edicion_productos_pagada():
                return

            items = tree_ed.selection()
            if not items:
                return

            if not nota_pagada and not pedir_password(ed):
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
                vals[6] = round(float(vals[4]) * nuevo, 2)
                tree_ed.item(item, values=vals)

            recalcular()
        def cambiar_precio_por_contexto():
            if bloquear_edicion_productos_pagada():
                return

            marca_ctx = combo_marca_contexto.get().strip().upper()
            hilo_ctx = combo_hilo_contexto.get().strip().upper()

            if not marca_ctx or not hilo_ctx:
                return

            if not nota_pagada and not pedir_password(ed):
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

                if str(vals[1]).upper() == marca_ctx and str(vals[2]).upper() == hilo_ctx:
                    vals[5] = round(nuevo, 2)
                    vals[6] = round(float(vals[4]) * nuevo, 2)
                    tree_ed.item(item, values=vals)

            recalcular()
        def eliminar_item():
            if bloquear_edicion_productos_pagada():
                return
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
            nota["paqueteria"] = envio.get("paqueteria") or envio.get("tipo")
            recalcular()

            try:
                registrar_cambio(
                    nota["id"],
                    "Cambio de envío",
                    f"{envio['paqueteria']} - ${envio['precio']}"
                )
            except Exception:
                pass

       # =====================================================
       # 🔵 CAMBIAR COMPROBANTE
       # =====================================================
        def cambiar_comprobante():
            if not pedir_password(ed):
                return

            from visor_imagen import visor_imagen

            def guardar_imagen(ruta):
                try:
                    nota["comprobante"] = guardar_comprobante_en_proyecto(nota["id"], ruta)
                    if nota_pagada:
                        nota["admin_edicion_pagada"] = True
                        nota["clave_autorizacion"] = clave_admin_pagada
                    guardar_nota_actualizada(nota)
                    messagebox.showinfo(
                        "Comprobante guardado",
                        "El comprobante se guardó correctamente.",
                        parent=ed
                    )
                except Exception as exc:
                    messagebox.showerror(
                        "Error",
                        f"No se pudo guardar el comprobante.\n\n{exc}",
                        parent=ed
                    )
                    raise

            visor_imagen(
                parent=ed,
                ruta_inicial=_ruta_comprobante_existente(nota.get("comprobante")),
                on_save=guardar_imagen
            )
            try:
                registrar_cambio(
                    nota["id"],
                    "Cambio de comprobante",
                    "Se actualizó imagen de comprobante"
                )
            except Exception:
                pass

        # =====================================================
        # 🔵 ELIMINAR VENTA
        # =====================================================
        def eliminar_venta():
            if _modo_api():
                eliminar_venta_desde_lista(tree, win)
                return

            if not pedir_password(ed):
                return

            if not messagebox.askyesno("Confirmar", "Eliminar venta y devolver stock?", parent=ed):
                return

            eliminar_venta_desde_lista(tree, win)


        # =====================================================
        # 🔵 GUARDAR CAMBIOS
        # =====================================================
        def _clave_item_admin(item):
            return (
                str(item.get("marca") or "").strip().upper(),
                str(item.get("hilo") or "").strip().upper(),
                str(item.get("codigo") or "").strip().upper(),
            )

        def _agrupar_items_admin(items):
            grupos = {}
            for item in items or []:
                clave = _clave_item_admin(item)
                if clave not in grupos:
                    grupos[clave] = {
                        "cantidad": 0,
                        "precio": float(item.get("precio") or 0),
                        "item": dict(item),
                    }
                grupos[clave]["cantidad"] += int(float(item.get("cantidad") or 0))
                grupos[clave]["precio"] = float(item.get("precio") or 0)
            return grupos

        def _total_final_admin(items):
            subtotal = sum(float(item.get("cantidad") or 0) * float(item.get("precio") or 0) for item in items or [])
            envio = nota.get("envio") or {}
            envio_precio = float((envio or {}).get("precio") or 0) if isinstance(envio, dict) else 0
            return subtotal + envio_precio

        def _resumen_ajuste_admin(nuevos):
            originales_grupo = _agrupar_items_admin(nota.get("items", []))
            nuevos_grupo = _agrupar_items_admin(nuevos)
            lineas = []
            afectados = []

            for clave in sorted(set(originales_grupo) | set(nuevos_grupo)):
                anterior = originales_grupo.get(clave, {})
                nuevo = nuevos_grupo.get(clave, {})
                item = nuevo.get("item") or anterior.get("item") or {}
                cantidad_anterior = int(anterior.get("cantidad") or 0)
                cantidad_nueva = int(nuevo.get("cantidad") or 0)
                diferencia = cantidad_nueva - cantidad_anterior
                etiqueta = f"{item.get('marca','')} {item.get('hilo','')} {item.get('codigo','')}".strip()

                if cantidad_anterior == 0 and cantidad_nueva > 0:
                    lineas.append(f"Agregado: {etiqueta} x{cantidad_nueva}")
                elif cantidad_nueva == 0 and cantidad_anterior > 0:
                    lineas.append(f"Eliminado: {etiqueta} x{cantidad_anterior} (regresa stock)")
                elif diferencia > 0:
                    lineas.append(f"Aumenta: {etiqueta} {cantidad_anterior} -> {cantidad_nueva} (descuenta {diferencia})")
                elif diferencia < 0:
                    lineas.append(f"Reduce: {etiqueta} {cantidad_anterior} -> {cantidad_nueva} (regresa {abs(diferencia)})")

                precio_anterior = float(anterior.get("precio") or 0)
                precio_nuevo = float(nuevo.get("precio") or 0)
                if cantidad_anterior and cantidad_nueva and round(precio_anterior, 2) != round(precio_nuevo, 2):
                    lineas.append(f"Precio: {etiqueta} ${precio_anterior:.2f} -> ${precio_nuevo:.2f}")

                if diferencia > 0:
                    try:
                        producto = obtener_producto_por_codigo(item.get("codigo"))
                    except Exception:
                        producto = None
                    stock_actual = int((producto or {}).get("stock") or 0)
                    faltante = max(diferencia - stock_actual, 0)
                    if faltante or stock_actual - diferencia < STOCK_MINIMO:
                        afectados.append({
                            "codigo": item.get("codigo", ""),
                            "marca": item.get("marca", ""),
                            "hilo": item.get("hilo", ""),
                            "color": item.get("color", ""),
                            "cantidad_solicitada": diferencia,
                            "stock_actual": stock_actual,
                            "faltante": faltante,
                            "estado": "STOCK INSUFICIENTE" if faltante else "STOCK BAJO",
                        })

            total_anterior = calcular_totales_nota(nota).get("total_final", 0)
            total_nuevo = _total_final_admin(nuevos)
            lineas.append(f"Total anterior: ${float(total_anterior):.2f}")
            lineas.append(f"Total nuevo: ${float(total_nuevo):.2f}")
            return "\n".join(lineas), afectados, total_anterior, total_nuevo

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

            if nota_pagada and _modo_api():
                resumen, afectados_ui, total_anterior, total_nuevo = _resumen_ajuste_admin(nuevos)
                mensaje = (
                    "Esta nota ya está pagada. Los cambios ajustarán stock y totales.\n\n"
                    f"{resumen}\n\n¿Deseas continuar?"
                )
                confirmado = confirmar_moderno(
                    ed,
                    "Ajuste administrativo",
                    mensaje,
                    "Guardar ajuste",
                    "Cancelar",
                ) if confirmar_moderno else messagebox.askyesno("Ajuste administrativo", mensaje, parent=ed)
                if not confirmado:
                    return

                if afectados_ui:
                    autorizado_stock = pedir_autorizacion_stock(
                        ed,
                        afectados_ui,
                        titulo="Autorización por stock",
                        descripcion="El ajuste necesita descontar stock bajo o insuficiente.",
                    ) if pedir_autorizacion_stock else simpledialog.askstring(
                        "Autorización por stock",
                        "Clave temporal:",
                        show="*",
                        parent=ed,
                    ) == "1"
                    if not autorizado_stock:
                        return

                nota["items"] = nuevos
                try:
                    respuesta = ajustar_items_nota_pagada_admin(
                        nota,
                        nuevos,
                        clave_autorizacion=clave_admin_pagada,
                        motivo="Edición administrativa de nota pagada autorizada",
                    )
                except Exception as exc:
                    messagebox.showerror(
                        "Guardar cambios",
                        f"No se pudo guardar el ajuste administrativo.\n\n{exc}",
                        parent=ed
                    )
                    return

                if isinstance(respuesta, dict) and respuesta.get("aviso_total_pago"):
                    aviso = "El total cambió. Revisa si hay diferencia entre total y pago registrado."
                    if alerta_moderna:
                        alerta_moderna(ed, "Revisar diferencia", aviso)
                    else:
                        messagebox.showwarning("Revisar diferencia", aviso, parent=ed)

                ed.destroy()
                cargar_notas()
                return

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
            *_, sub = tree_ed.item(i, "values")
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
     if not is_legacy_sales_override_key(
        pwd,
        {"accion": "ver_cotizaciones_cambiar_precio_item"},
     ):
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

            nota["envio"] = envio

            autorizacion_stock = None
            if _modo_api():
                ok_stock, autorizacion_stock, _ = _pedir_autorizacion_stock_si_necesaria(ed, items_finales)
                if not ok_stock:
                    return

            # 4️⃣ Descontar stock
            for item in items_finales:
                
                if not item:
                    messagebox.showerror(
                        "Error",
                        f"No existe el producto {item['codigo']}",
                        parent=ed
                    )
                    return

                if _modo_api():
                    continue

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
                envio,
                autorizacion_stock=autorizacion_stock
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

        if _modo_api() and _normalizar_estado_pago(nota.get("estado")) in ESTADOS_COTIZACION_NO_PAGABLE:
            cliente = obtener_cliente_por_id(nota["cliente_id"])
            if not cliente or not cliente_completo(cliente):
                messagebox.showinfo(
                    "Datos incompletos",
                    "Completa los datos del cliente para continuar",
                    parent=ed
                )
                editar_cliente_por_id(
                    nota["cliente_id"],
                    ed,
                    on_guardar=lambda _cliente: configurar_envio_cotizacion()
                )
                return

            ok_stock, autorizacion_stock, _ = _pedir_autorizacion_stock_si_necesaria(ed, items)
            if not ok_stock:
                return

            convertir_cotizacion_a_venta(
                nota["id"],
                items,
                cliente,
                envio,
                autorizacion_stock=autorizacion_stock
            )
            cargar_envios()
            messagebox.showinfo(
                "Venta creada",
                f"Envío guardado y venta pendiente: {envio['paqueteria']} • ${envio['precio']:.2f}",
                parent=ed
            )
            ed.destroy()
            win.destroy()
            abrir_visor(win.master)
            return

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

        if _modo_api() and _normalizar_estado_pago(nota.get("estado")) in ESTADOS_COTIZACION_NO_PAGABLE:
            items = []
            for i in tree_ed.get_children():
                codigo, marca, hilo, color, cantidad, precio_item, _ = tree_ed.item(i, "values")
                items.append({
                    "codigo": codigo,
                    "marca": marca,
                    "hilo": hilo,
                    "color": color,
                    "cantidad": int(cantidad),
                    "precio": float(precio_item)
                })

            cliente = obtener_cliente_por_id(nota["cliente_id"])
            if not cliente or not cliente_completo(cliente):
                messagebox.showinfo(
                    "Datos incompletos",
                    "Completa los datos del cliente para continuar",
                    parent=ed
                )
                editar_cliente_por_id(
                    nota["cliente_id"],
                    ed,
                    on_guardar=lambda _cliente: aplicar_envio_manual()
                )
                return

            ok_stock, autorizacion_stock, _ = _pedir_autorizacion_stock_si_necesaria(ed, items)
            if not ok_stock:
                return

            convertir_cotizacion_a_venta(
                nota["id"],
                items,
                cliente,
                nota["envio"],
                autorizacion_stock=autorizacion_stock
            )
            messagebox.showinfo(
                "Venta creada",
                f"Envío manual aplicado y venta pendiente: ${precio:.2f}",
                parent=ed
            )
            ed.destroy()
            win.destroy()
            abrir_visor(win.master)
            return

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

   

    


CONTABILIDAD_API_URL = os.environ.get(
    "CONTABILIDAD_API_URL",
    "https://contabilidad-api-oxdb.onrender.com"
)

PENDIENTES_CONTABILIDAD_FILE = "contabilidad_pendientes.json"


# Costos reales de envío que quieres descontar para calcular dinero neto.
# Puedes cambiar estos números después si suben tus costos.
COSTOS_ENVIO_REALES = {
    "CORREOS": 30,
    "CORREOS DE MEXICO": 30,
    "CORREOS DE MÉXICO": 30,
    "SEPOMEX": 30,
    "FEDEX": 200,
    "ESTAFETA": 150,
}


def _numero(valor, default=0):
    try:
        if valor is None or valor == "":
            return default
        return float(valor)
    except Exception:
        return default


def _texto_normalizado(valor):
    return str(valor or "").strip().upper()


def obtener_costo_envio_real_neto(nota):
    """Devuelve el costo real de envío que se resta a la venta."""
    envio = nota.get("envio") or {}

    if isinstance(envio, str):
        try:
            envio = json.loads(envio)
        except Exception:
            envio = {}

    paqueteria = _texto_normalizado(
        envio.get("paqueteria")
        or envio.get("empresa")
        or envio.get("nombre")
        or ""
    )

    if "CORREOS" in paqueteria or "SEPOMEX" in paqueteria:
        return COSTOS_ENVIO_REALES["CORREOS"], paqueteria or "CORREOS"
    if "FEDEX" in paqueteria:
        return COSTOS_ENVIO_REALES["FEDEX"], paqueteria or "FEDEX"
    if "ESTAFETA" in paqueteria:
        return COSTOS_ENVIO_REALES["ESTAFETA"], paqueteria or "ESTAFETA"

    # Si no reconoce la paquetería, no descuenta envío para evitar inventar costo.
    return 0, paqueteria or "SIN PAQUETERIA"


def obtener_costo_proveedor_item_neto(item):
    """
    Busca el costo proveedor unitario del producto.
    Primero intenta en el item de la nota; si no viene ahí, lo busca en almacén por código.
    """
    posibles_campos = (
        "costo_neto",
        "costo_proveedor",
        "precio_proveedor",
        "precio_compra",
        "costo_compra",
        "costo",
        "precio_costo",
    )

    for campo in posibles_campos:
        if campo in item and item.get(campo) not in (None, ""):
            return _numero(item.get(campo)), campo

    codigo = item.get("codigo") or item.get("Código")
    if codigo:
        try:
            producto = obtener_producto_por_codigo(codigo)
        except Exception:
            producto = None

        if producto:
            for campo in posibles_campos:
                if campo in producto and producto.get(campo) not in (None, ""):
                    return _numero(producto.get(campo)), campo

    return 0, "SIN_COSTO"


def calcular_dinero_neto_nota(nota):
    """
    Fórmula:
    dinero_neto = total_nota - costo_proveedor_total

    IMPORTANTE:
    Aquí NO se descuenta el costo real del envío.
    Si pagaste envío a Correos, FedEx, Estafeta, etc., regístralo aparte
    como gasto manual desde la app de dinero.
    """
    total_nota = _numero(nota.get("total"))

    costo_proveedor_total = 0
    productos_sin_costo = []

    for item in nota.get("items", []) or []:
        cantidad = _numero(item.get("cantidad"))
        costo_unitario, campo = obtener_costo_proveedor_item_neto(item)
        costo_proveedor_total += cantidad * costo_unitario

        if costo_unitario <= 0:
            productos_sin_costo.append(str(item.get("codigo") or "SIN_CODIGO"))

    dinero_neto = total_nota - costo_proveedor_total

    return {
        "total_nota": round(total_nota, 2),
        "costo_proveedor": round(costo_proveedor_total, 2),
        "costo_envio_real": 0,
        "paqueteria": "NO_DESCONTADO",
        "dinero_neto": round(dinero_neto, 2),
        "productos_sin_costo": productos_sin_costo,
    }


def construir_payload_ingreso_contabilidad(nota, comprobante=None):
    """Construye el ingreso NETO que se enviará a Mi Control de Dinero."""
    nota_id = str(nota.get("id") or "").strip()
    if not nota_id:
        return None, "La nota no tiene ID"

    calculo = calcular_dinero_neto_nota(nota)
    monto_neto = calculo["dinero_neto"]

    if calculo["total_nota"] <= 0:
        return None, "La nota no tiene total válido"

    if monto_neto <= 0:
        return None, (
            "El dinero neto salió en cero o negativo. "
            f"Total: ${calculo['total_nota']:.2f}, "
            f"proveedor: ${calculo['costo_proveedor']:.2f}"
        )

    cliente_nombre = nota.get("cliente_nombre") or ""
    if not cliente_nombre:
        try:
            cliente = obtener_cliente_por_id(nota.get("cliente_id"))
            if cliente:
                cliente_nombre = cliente.get("nombre", "")
        except Exception:
            cliente_nombre = ""

    # La API actual usa el campo cliente para armar la descripción.
    # Por eso aquí dejamos un resumen corto del cálculo.
    detalle = (
        f"{cliente_nombre} | NETO ${monto_neto:.2f} "
        f"= Total ${calculo['total_nota']:.2f} "
        f"- proveedor ${calculo['costo_proveedor']:.2f} "
        f"| envío real NO descontado, se registra como gasto manual"
    )

    if calculo["productos_sin_costo"]:
        detalle += f" | Sin costo proveedor: {', '.join(calculo['productos_sin_costo'][:8])}"

    return {
        "nota_id": nota_id,
        "cliente": detalle,
        "monto": monto_neto,
        "comprobante": comprobante or nota.get("comprobante", ""),
        "tipo_calculo": "neto",
        "total_nota": calculo["total_nota"],
        "costo_proveedor": calculo["costo_proveedor"],
        "costo_envio_real": calculo["costo_envio_real"],
        "paqueteria": calculo["paqueteria"],
        "productos_sin_costo": calculo["productos_sin_costo"],
    }, None


def cargar_pendientes_contabilidad():
    if not os.path.exists(PENDIENTES_CONTABILIDAD_FILE):
        return []

    try:
        with open(PENDIENTES_CONTABILIDAD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def guardar_pendientes_contabilidad(pendientes):
    with open(PENDIENTES_CONTABILIDAD_FILE, "w", encoding="utf-8") as f:
        json.dump(pendientes, f, ensure_ascii=False, indent=2)


def encolar_ingreso_contabilidad(payload, motivo=""):
    """Guarda un ingreso pendiente localmente para enviarlo cuando vuelva internet."""
    if not payload or not payload.get("nota_id"):
        return False

    pendientes = cargar_pendientes_contabilidad()
    nota_id = str(payload.get("nota_id"))

    # Evitar duplicar la misma nota en pendientes.
    for p in pendientes:
        if str(p.get("nota_id")) == nota_id:
            p.update(payload)
            p["ultimo_motivo"] = motivo
            guardar_pendientes_contabilidad(pendientes)
            return True

    payload = dict(payload)
    payload["ultimo_motivo"] = motivo
    pendientes.append(payload)
    guardar_pendientes_contabilidad(pendientes)
    return True


def enviar_payload_ingreso_contabilidad(payload):
    """Envía un payload ya construido a la API de contabilidad."""
    url = CONTABILIDAD_API_URL.rstrip("/") + "/api/ingreso-nota"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")

    respuesta = json.loads(raw)

    if respuesta.get("ok"):
        if respuesta.get("duplicado"):
            return True, "La nota ya tenía ingreso registrado"

        try:
            monto = float(payload.get("monto") or 0)
            total = float(payload.get("total_nota") or 0)
            proveedor = float(payload.get("costo_proveedor") or 0)
            envio = float(payload.get("costo_envio_real") or 0)
            paqueteria = payload.get("paqueteria") or ""
            return True, (
                "Ingreso NETO registrado en Mi Control de Dinero: "
                f"${monto:.2f} = total ${total:.2f} "
                f"- proveedor ${proveedor:.2f} "
                "(envío real se registra manual)"
            )
        except Exception:
            return True, "Ingreso NETO registrado automáticamente en Mi Control de Dinero"

    return False, respuesta.get("error") or "La API no aceptó el ingreso"


def sincronizar_pendientes_contabilidad(parent=None, silencioso=True):
    """Intenta enviar todos los ingresos pendientes guardados localmente."""
    pendientes = cargar_pendientes_contabilidad()

    if not pendientes:
        if not silencioso:
            messagebox.showinfo(
                "Sin pendientes",
                "No hay ingresos pendientes por sincronizar.",
                parent=parent
            )
        return True, "No hay pendientes"

    restantes = []
    enviados = 0
    errores = []

    for payload in pendientes:
        try:
            ok, msg = enviar_payload_ingreso_contabilidad(payload)
            if ok:
                enviados += 1
            else:
                payload["ultimo_motivo"] = msg
                restantes.append(payload)
                errores.append(msg)
        except Exception as e:
            payload["ultimo_motivo"] = str(e)
            restantes.append(payload)
            errores.append(str(e))

    guardar_pendientes_contabilidad(restantes)

    if not silencioso:
        if restantes:
            messagebox.showwarning(
                "Sincronización parcial",
                f"Se enviaron {enviados} ingreso(s).\n"
                f"Quedan {len(restantes)} pendiente(s).\n\n"
                f"Último error: {errores[-1] if errores else 'No disponible'}",
                parent=parent
            )
        else:
            messagebox.showinfo(
                "Sincronizado",
                f"Se enviaron {enviados} ingreso(s) pendiente(s).",
                parent=parent
            )

    return len(restantes) == 0, f"Enviados: {enviados}, pendientes: {len(restantes)}"


def enviar_ingreso_contabilidad_por_nota(nota, comprobante=None):
    """
    Envía el ingreso automático al sistema Mi Control de Dinero.
    Si no hay internet/API, guarda el ingreso como pendiente local.
    La API evita duplicados usando nota_id.
    """
    payload, error = construir_payload_ingreso_contabilidad(nota, comprobante)
    if error:
        return False, error

    # Antes de enviar el actual, intenta vaciar pendientes anteriores.
    sincronizar_pendientes_contabilidad(silencioso=True)

    try:
        ok, msg = enviar_payload_ingreso_contabilidad(payload)
        if ok:
            return True, msg

        encolar_ingreso_contabilidad(payload, msg)
        return False, f"{msg}. El ingreso quedó guardado como pendiente y se enviará cuando vuelva la conexión"

    except urllib.error.URLError as e:
        encolar_ingreso_contabilidad(payload, str(e))
        return False, "No hay conexión con la API. El ingreso quedó guardado como pendiente y se enviará cuando vuelva la conexión"
    except Exception as e:
        encolar_ingreso_contabilidad(payload, str(e))
        return False, f"Error temporal: {e}. El ingreso quedó guardado como pendiente y se intentará reenviar después"


def marcar_como_pagada(tree, win):
    sel = tree.focus()
    if not sel:
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)

    if not _validar_nota_pagable_ui(nota, win):
        return

    # ✅ ESTA FUNCIÓN DEBE IR ANTES
    def guardar_imagen(ruta_imagen):
        autorizacion_stock = None
        if _modo_api():
            ok_stock, autorizacion_stock, _ = _pedir_autorizacion_stock_si_necesaria(win, nota.get("items", []))
            if not ok_stock:
                return

        destino = guardar_comprobante_en_proyecto(id_nota, ruta_imagen)

        nota["estado"] = "PAGADA"
        nota["comprobante"] = destino
        nota["fecha_pago"] = datetime.datetime.now().isoformat(timespec="seconds")
        if autorizacion_stock:
            nota["autorizacion_stock"] = autorizacion_stock
        try:
            guardar_nota_actualizada(nota)
        except Exception as exc:
            messagebox.showerror(
                "Pago no confirmado",
                f"No se pudo marcar como pagada.\n\n{exc}",
                parent=win
            )
            return

        registrar_cambio(
            id_nota,
            "Cambio de estado",
            "VENTA_PENDIENTE → PAGADA"
        )

        ok_contabilidad, msg_contabilidad = enviar_ingreso_contabilidad_por_nota(
            nota,
            comprobante=destino
        )

        if ok_contabilidad:
            messagebox.showinfo(
                "Pago confirmado",
                "La venta fue marcada como PAGADA.\n\n"
                f"{msg_contabilidad}.",
                parent=win
            )
        else:
            messagebox.showwarning(
                "Pago confirmado con aviso",
                "La venta fue marcada como PAGADA, pero no se pudo enviar "
                "el ingreso automático a Mi Control de Dinero en este momento.\n\n"
                f"Motivo: {msg_contabilidad}\n\n"
                "No lo registres manualmente todavía: quedó como pendiente y se intentará enviar automáticamente cuando vuelva la conexión.",
                parent=win
            )

        win.destroy()
        abrir_visor(win.master)

    # 🔍 ABRIR VISOR CON DRAG & DROP
    visor_imagen(
    parent=win,
    ruta_inicial=_ruta_comprobante_existente(nota.get("comprobante")),
    on_save=guardar_imagen
)



def ver_comprobante(tree, win):
    sel = tree.focus()
    if not sel:
        return

    id_nota = tree.item(sel, "values")[0]
    nota = obtener_cotizacion(id_nota)

    ruta_comprobante = nota.get("comprobante")

    if not _nota_requiere_stock_pagado_ui(nota) or not ruta_comprobante:
        messagebox.showwarning("Aviso", "No hay comprobante", parent=win)
        return

    ruta_resuelta = resolver_ruta_comprobante(ruta_comprobante)

    if not ruta_resuelta or not ruta_resuelta.exists():
        nombre_buscado = _nombre_archivo_comprobante(ruta_comprobante)
        ruta_esperada = (
            (COMPROBANTES_DIR / nombre_buscado).resolve()
            if nombre_buscado else ruta_resuelta
        )
        messagebox.showwarning(
            "Aviso",
            "Comprobante registrado, pero archivo no encontrado.\n\n"
            f"Ruta guardada original:\n{ruta_comprobante}\n\n"
            f"Ruta esperada actual:\n{ruta_esperada}\n\n"
            f"Nombre buscado:\n{nombre_buscado or '-'}",
            parent=win
        )
        return

    if ruta_resuelta.suffix.lower() == ".pdf":
        messagebox.showinfo(
            "Comprobante PDF",
            f"Comprobante PDF registrado:\n{ruta_resuelta}",
            parent=win
        )
        return

    visor_imagen(win, ruta_inicial=str(ruta_resuelta))


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

    totales_nota = calcular_totales_nota(nota)
    frame_totales = ttk.Frame(det)
    frame_totales.pack(fill="x", padx=10, pady=10)

    ttk.Label(
        frame_totales,
        text=f"Subtotal productos: ${totales_nota['subtotal_productos']:.2f}"
    ).pack(anchor="e")
    ttk.Label(
        frame_totales,
        text=f"Envío: ${totales_nota['envio_precio']:.2f}"
    ).pack(anchor="e")
    ttk.Label(
        frame_totales,
        text=f"Total final: ${totales_nota['total_final']:.2f}",
        font=("Segoe UI", 14, "bold")
    ).pack(anchor="e")

    comprobante_frame = ttk.LabelFrame(det, text="Comprobante de pago")
    comprobante_frame.pack(fill="x", padx=10, pady=(0, 10))

    ruta_comprobante = nota.get("comprobante")
    ruta_resuelta = resolver_ruta_comprobante(ruta_comprobante)

    if ruta_resuelta and ruta_resuelta.exists():
        ttk.Label(
            comprobante_frame,
            text=f"Comprobante registrado: {ruta_resuelta.name}"
        ).pack(anchor="w", padx=8, pady=(6, 3))

        if ruta_resuelta.suffix.lower() == ".pdf":
            ttk.Label(
                comprobante_frame,
                text=f"PDF: {ruta_resuelta}"
            ).pack(anchor="w", padx=8, pady=(0, 6))
        else:
            ttk.Button(
                comprobante_frame,
                text="Ver comprobante",
                command=lambda: visor_imagen(det, ruta_inicial=str(ruta_resuelta))
            ).pack(anchor="w", padx=8, pady=(0, 6))
    elif ruta_comprobante:
        nombre_buscado = _nombre_archivo_comprobante(ruta_comprobante)
        ruta_esperada = (
            (COMPROBANTES_DIR / nombre_buscado).resolve()
            if nombre_buscado else ruta_resuelta
        )
        ttk.Label(
            comprobante_frame,
            text=(
                "Comprobante registrado, pero archivo no encontrado.\n"
                f"Ruta guardada original: {ruta_comprobante}\n"
                f"Ruta esperada actual: {ruta_esperada}"
            )
        ).pack(anchor="w", padx=8, pady=6)
    else:
        ttk.Label(
            comprobante_frame,
            text="Sin comprobante registrado"
        ).pack(anchor="w", padx=8, pady=6)

    _agregar_pagos_ttk(det, nota)

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





    

    


    
