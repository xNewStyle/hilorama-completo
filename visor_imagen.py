import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinterdnd2 import DND_FILES, TkinterDnD
from PIL import Image, ImageTk
from tkinter import ttk

PASSWORD = "12587987521"


def pedir_password(win):
    pwd = simpledialog.askstring(
        "Autorización",
        "Ingresa la contraseña:",
        parent=win,
        show="*"
    )
    return pwd == PASSWORD


def visor_imagen(parent, ruta_inicial=None, on_save=None):

    # =====================================================
    # 🔵 VENTANA MODERNA + SIEMPRE AL FRENTE
    # =====================================================
    win = tk.Toplevel(parent)
    win.title("Comprobante de pago")
    win.geometry("820x680")
    win.configure(bg="#EEF2F7")

    win.grab_set()          # modal
    win.lift()              # traer al frente
    win.focus_force()       # foco
    win.attributes("-topmost", True)
    win.after(200, lambda: win.attributes("-topmost", False))  # evita bug windows


    # =====================================================
    # 🔵 CARD PRINCIPAL (look moderno)
    # =====================================================
    card = tk.Frame(win, bg="white", bd=0)
    card.pack(fill="both", expand=True, padx=20, pady=20)


    # =====================================================
    # 🔵 DATA
    # =====================================================
    img_data = {
        "path": ruta_inicial,
        "img_original": None,
        "img_tk": None,
        "zoom": 1.0,
        "angle": 0,
        "offset_x": 0,
        "offset_y": 0,
        "drag_x": 0,
        "drag_y": 0
    }


    # =====================================================
    # 🔵 CANVAS
    # =====================================================
    canvas = tk.Canvas(card, bg="#F8FAFC", highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=15, pady=(15, 5))


    hint_id = canvas.create_text(
        0, 0,
        text="Haz clic o pega una imagen (Ctrl+V)",
        font=("Segoe UI", 14),
        fill="#8A8A8A"
    )


    # =====================================================
    # 🔵 RENDER
    # =====================================================
    def mostrar_imagen():

        canvas.delete("all")

        if not img_data["img_original"]:
            canvas.create_text(
                canvas.winfo_width()//2,
                canvas.winfo_height()//2,
                text="Haz clic o pega una imagen (Ctrl+V)",
                font=("Segoe UI", 14),
                fill="#8A8A8A"
            )
            return

        img = img_data["img_original"].rotate(
            img_data["angle"], expand=True
        )

        w, h = img.size
        img = img.resize(
            (int(w * img_data["zoom"]), int(h * img_data["zoom"])),
            Image.LANCZOS
        )

        img_data["img_tk"] = ImageTk.PhotoImage(img)

        cx = canvas.winfo_width()//2 + img_data["offset_x"]
        cy = canvas.winfo_height()//2 + img_data["offset_y"]

        canvas.create_image(cx, cy, image=img_data["img_tk"], anchor="center")


    # =====================================================
    # 🔵 CARGAR IMAGEN
    # =====================================================
    def cargar_imagen(ruta):
        img_data["path"] = ruta
        img_data["img_original"] = Image.open(ruta).convert("RGB")

        img_data["zoom"] = 1
        img_data["angle"] = 0
        img_data["offset_x"] = 0
        img_data["offset_y"] = 0

        mostrar_imagen()


    def seleccionar_imagen(event=None):
        ruta = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg")]
        )
        if ruta:
            cargar_imagen(ruta)


    # =====================================================
    # 🔵 CAMBIAR IMAGEN (con contraseña)
    # =====================================================
    def cambiar_imagen():
        if not pedir_password(win):
            messagebox.showerror("Error", "Contraseña incorrecta", parent=win)
            return
        seleccionar_imagen()


    # =====================================================
    # 🔵 DRAG
    # =====================================================
    def iniciar_arrastre(event):
        if not img_data["img_original"]:
            seleccionar_imagen()
            return

        img_data["drag_x"] = event.x
        img_data["drag_y"] = event.y


    def arrastrar(event):
        dx = event.x - img_data["drag_x"]
        dy = event.y - img_data["drag_y"]

        img_data["offset_x"] += dx
        img_data["offset_y"] += dy

        img_data["drag_x"] = event.x
        img_data["drag_y"] = event.y

        mostrar_imagen()


    # =====================================================
    # 🔵 ZOOM
    # =====================================================
    def zoom_rueda(event):
        if not img_data["img_original"]:
            return

        img_data["zoom"] *= 1.1 if event.delta > 0 else 0.9
        mostrar_imagen()


    def zoom_mas():
        img_data["zoom"] *= 1.15
        mostrar_imagen()


    def zoom_menos():
        img_data["zoom"] /= 1.15
        mostrar_imagen()


    # =====================================================
    # 🔵 ROTAR
    # =====================================================
    def rotar():
        img_data["angle"] = (img_data["angle"] + 90) % 360
        mostrar_imagen()


    # =====================================================
    # 🔵 COPIAR / PEGAR (NUEVO 🔥)
    # =====================================================
    from PIL import ImageGrab

    def pegar(event=None):
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            img_data["img_original"] = img
            img_data["path"] = None
            mostrar_imagen()

    win.bind("<Control-v>", pegar)


    # =====================================================
    # 🔵 GUARDAR
    # =====================================================
    def guardar():
        if not img_data["img_original"]:
            messagebox.showwarning("Aviso", "No hay imagen", parent=win)
            return

        # 🔴 guardar automático (sin explorador)
        ruta_temp = "_temp_comprobante.png"

        img_data["img_original"].save(ruta_temp)

        if on_save:
            on_save(ruta_temp)

        win.destroy()



    # =====================================================
    # 🔵 EVENTOS
    # =====================================================
    canvas.bind("<ButtonPress-1>", iniciar_arrastre)
    canvas.bind("<B1-Motion>", arrastrar)
    canvas.bind("<MouseWheel>", zoom_rueda)


    # =====================================================
    # 🔵 BOTONES MODERNOS
    # =====================================================
    toolbar = tk.Frame(card, bg="white")
    toolbar.pack(pady=10)

    def btn(t, cmd):
        return tk.Button(
            toolbar,
            text=t,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            bg="#E3E8F0",
            activebackground="#D1D9E6",
            padx=12,
            command=cmd
        )

    btn("➕ Zoom", zoom_mas).pack(side="left", padx=5)
    btn("➖ Zoom", zoom_menos).pack(side="left", padx=5)
    btn("🔄 Rotar", rotar).pack(side="left", padx=5)
    btn("📋 Pegar", pegar).pack(side="left", padx=5)
    btn("🔁 Cambiar 🔒", cambiar_imagen).pack(side="left", padx=5)
    btn("💾 Guardar", guardar).pack(side="right", padx=5)


    # =====================================================
    # 🔵 CARGA INICIAL
    # =====================================================
    if ruta_inicial and os.path.exists(ruta_inicial):
        cargar_imagen(ruta_inicial)

    win.after(80, mostrar_imagen)
