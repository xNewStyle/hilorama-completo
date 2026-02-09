import customtkinter as ctk
from tkinter import messagebox, filedialog
from tkinterdnd2 import DND_FILES
from PIL import ImageGrab
import tempfile

from ocr import leer_pedido_desde_imagen
from core.almacen_api import obtener_productos
from parser_whatsapp import extraer_pedidos


def crear_area_imagen(root, marca_var, hilo_var, agregar_al_carrito, refrescar_carrito):

    # =====================================================
    # 🔵 LÓGICA ORIGINAL (MISMA QUE YA TENÍAS)
    # =====================================================

    def procesar_imagen(ruta):
        try:
            texto = leer_pedido_desde_imagen(ruta)
            texto = texto.replace("O", "0").replace("l", "1").replace("I", "1")

            productos = obtener_productos(
                marca_var.get(),
                hilo_var.get()
            )

            resultado = extraer_pedidos(texto, productos)

            if not resultado["pedidos"]:
                messagebox.showinfo(
                    "Sin coincidencias",
                    "No se detectaron códigos válidos"
                )
                return

            for pedido in resultado["pedidos"]:
                agregar_al_carrito(pedido)

            refrescar_carrito()

        except Exception as e:
            messagebox.showerror("OCR Error", str(e))


    def drop(event):
        ruta = event.data.strip("{}")
        procesar_imagen(ruta)


    def pegar(event=None):
        img = ImageGrab.grabclipboard()
        if not img:
            return

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(tmp.name)
        tmp.close()

        procesar_imagen(tmp.name)


    def abrir_archivo():
        ruta = filedialog.askopenfilename(
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp")]
        )
        if ruta:
            procesar_imagen(ruta)


    # =====================================================
    # 🔵 NUEVA UI MODERNA (CUSTOMTKINTER)
    # =====================================================

    card = ctk.CTkFrame(
        root,
        corner_radius=18,
        fg_color="#F8FAFC"
    )
    card.pack(fill="both", expand=True, padx=15, pady=12)


    # ---------- título ----------
    ctk.CTkLabel(
        card,
        text="📷 Imagen de pedido",
        font=("Segoe UI", 16, "bold")
    ).pack(anchor="w", padx=18, pady=(14, 6))


    # ---------- drop zone ----------
    drop_zone = ctk.CTkFrame(
        card,
        corner_radius=14,
        fg_color="#FFFFFF",
        border_width=2,
        border_color="#D0D7DE"
    )
    drop_zone.pack(fill="both", expand=True, padx=18, pady=(0, 15))


    drop_zone.grid_rowconfigure(0, weight=1)
    drop_zone.grid_columnconfigure(0, weight=1)


    lbl = ctk.CTkLabel(
        drop_zone,
        text="📸 Arrastra imagen aquí\nCtrl+V para pegar\nClick para seleccionar",
        justify="center",
        font=("Segoe UI", 14),
        text_color="#555"
    )
    lbl.grid(row=0, column=0)


    # =====================================================
    # 🔵 EVENTOS (MISMAS FUNCIONES QUE PEDISTE)
    # =====================================================

    drop_zone.drop_target_register(DND_FILES)
    drop_zone.dnd_bind("<<Drop>>", drop)

    drop_zone.bind("<Control-v>", pegar)
    drop_zone.bind("<Button-1>", lambda e: abrir_archivo())

    drop_zone.focus_set()
