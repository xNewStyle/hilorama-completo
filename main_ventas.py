import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from tkinterdnd2 import TkinterDnD, DND_FILES
# ================= IMPORTS DEL SISTEMA =================
from core.almacen_api import (
  
    obtener_marcas,
    obtener_hilos,
    obtener_productos,
    obtener_precio_venta,
    es_stock_bajo
)

from parser_whatsapp import extraer_pedidos
from notas import crear_cotizacion, listar_cotizaciones, obtener_cotizacion, eliminar_cotizacion
from clientes import obtener_o_crear_cliente
from ver_cotizaciones import abrir_visor, ver_detalles
from ver_clientes import abrir_clientes, editar_cliente_por_id
from ver_notas_completo import abrir_visor_notas
from ver_cotizaciones import calcular_volumetrico_total, seleccionar_envio
from ocr import leer_pedido_desde_imagen
from ui_imagen import crear_area_imagen
import customtkinter as ctk
from PIL import Image
import os
from pedidos import crear_pedido, listar_pedidos
import calendar
from datetime import datetime
from pedido_estado import guardar_pedido
from pedido_estado import pedido_por_vencer, pedido_vencido, cargar_pedido

# ================= CONFIG =================
PASSWORD = "12587987521"

# ================= CARRITO =================
carrito = []
envio_actual = None
lbl_envio = None
cliente_actual = None
pedido_actual = None
fecha_desde = None
fecha_hasta = None
# ================= TK ROOT =================
root = TkinterDnD.Tk()
# ===== CONTENEDOR PRINCIPAL 2 COLUMNAS =====
frame_main = tk.Frame(root, bg="#EFEFEF")
frame_main.pack(fill="both", expand=True, padx=15, pady=15)

# columnas → izquierda grande | derecha panel
frame_main.columnconfigure(0, weight=4)
frame_main.columnconfigure(1, weight=1)

# filas → contexto | carrito | imagen
frame_main.rowconfigure(0, weight=0)
frame_main.rowconfigure(1, weight=1)
frame_main.rowconfigure(2, weight=4)
frame_main.rowconfigure(3, weight=1)


card_contexto = tk.Frame(frame_main, bg="white")
card_contexto.grid(row=0, column=0, sticky="ew", pady=(0,10))

card_whatsapp = tk.Frame(frame_main, bg="white")
card_whatsapp.grid(row=1, column=0, sticky="ew", pady=(0,10))

card_carrito = tk.Frame(frame_main, bg="white")
card_carrito.grid(row=2, column=0, sticky="nsew", pady=(0,10))

card_imagen = tk.Frame(frame_main, bg="white")
card_imagen.grid(row=3, column=0, sticky="nsew")


card_total = tk.Frame(frame_main, bg="white")
card_total.grid(row=0, column=1, rowspan=4, sticky="nsew", padx=(10,0))



# ================= ANALIZAR WHATSAPP =================
def analizar_whatsapp():
    texto = txt_whatsapp.get("1.0", tk.END).strip()
    if not texto:
        return

    productos = obtener_productos(
        marca_var.get(),
        hilo_var.get()
    )

    if not productos:
        messagebox.showwarning(
            "Contexto",
            "No hay productos para la marca e hilo seleccionados"
        )
        return

    resultado = extraer_pedidos(texto, productos)

    # 🔴 AQUÍ ESTABA EL ERROR ANTES
    lista_pedidos = resultado.get("pedidos", [])

    if not lista_pedidos:
        messagebox.showinfo(
            "Sin coincidencias",
            "No se detectaron códigos válidos"
        )
        return

    for pedido in lista_pedidos:
        agregar_al_carrito(pedido)

    refrescar_carrito()
    print(lista_pedidos)

def actualizar_hilos(event=None):
    marca = marca_var.get()
    hilos = obtener_hilos(marca)

    combo_hilo.configure(values=hilos)

    if hilos:
        hilo_var.set(hilos[0])


def cargar_contexto():
    marcas = obtener_marcas()

    combo_marca.configure(values=marcas)

    if marcas:
        marca_var.set(marcas[0])
        actualizar_hilos()

from clientes import listar_clientes

def abrir_panel_asignacion():

    if not pedir_password():
        return

    from database.connection import get_conn
    from empacadores import listar_empacadores_activos

    conn = get_conn()

    notas = conn.execute("""
        SELECT 
            n.id,
            n.cliente_nombre,
            n.pedido,
            n.fecha_asignacion,
            n.estado,
            e.nombre AS empacador_actual,
            c.telefono,

            COALESCE(SUM(i.empacadas),0) AS empacadas,
            COALESCE(SUM(i.cantidad),0) AS requeridas

        FROM notas n
        LEFT JOIN empacadores e ON e.id = n.empacador_id
        LEFT JOIN clientes c ON c.id = n.cliente_id
        LEFT JOIN items i ON i.nota_id = n.id

        WHERE n.estado != 'ARCHIVADA'
        AND (
            n.estado NOT IN ('COMPLETA')
            OR n.fecha_asignacion >= NOW() - INTERVAL '24 HOURS'
        )

        GROUP BY n.id, e.nombre, c.telefono
        ORDER BY n.fecha_asignacion DESC NULLS LAST




   
    """).fetchall()

    conn.close()

    win = ctk.CTkToplevel(root)
    win.title("Asignar notas a empacador")
    win.geometry("1200x800")
    win.grab_set()

    # ================= FILTRO AVANZADO =================
    frame_filtro = ctk.CTkFrame(win, fg_color="transparent")
    frame_filtro.pack(fill="x", padx=15, pady=10)
    frame_stats = ctk.CTkFrame(win)
    frame_stats.pack(fill="x", padx=20, pady=10)

    total = len(notas)
    sin_asignar = len([n for n in notas if not n["empacador_actual"]])
    asignadas = total - sin_asignar

    lbl_total = ctk.CTkLabel(frame_stats, font=("Segoe UI", 13, "bold"))
    lbl_total.pack(side="left", padx=10)

    lbl_sin_asignar = ctk.CTkLabel(frame_stats, font=("Segoe UI", 13, "bold"))
    lbl_sin_asignar.pack(side="left", padx=10)

    lbl_asignadas = ctk.CTkLabel(frame_stats, font=("Segoe UI", 13, "bold"))
    lbl_asignadas.pack(side="left", padx=10)

    def actualizar_stats(data):
        total = len(data)
        sin_asignar = len([n for n in data if not n["empacador_actual"]])
        asignadas = total - sin_asignar

        lbl_total.configure(text=f"📦 Total: {total}")
        lbl_sin_asignar.configure(text=f"🟡 Sin asignar: {sin_asignar}")
        lbl_asignadas.configure(text=f"🟢 Asignadas: {asignadas}")  
    
    def auto_refresh():
        if not win.winfo_exists():
            return

        nuevas_notas = recargar_datos()

        conn = get_conn()

        for n in nuevas_notas:
            if n["requeridas"] > 0:

                if n["empacadas"] >= n["requeridas"]:
                    conn.execute("""
                        UPDATE notas
                        SET estado='COMPLETA'
                        WHERE id=%s AND estado!='COMPLETA'
                    """, (n["id"],))

                elif n["empacadas"] > 0:
                    conn.execute("""
                        UPDATE notas
                        SET estado='EN_PROCESO'
                        WHERE id=%s AND estado!='EN_PROCESO'
                    """, (n["id"],))


        conn.commit()
        conn.close()

        notas.clear()
        notas.extend(nuevas_notas)

        aplicar_filtros()
        actualizar_stats(notas)

        win.after(5000, auto_refresh)


    actualizar_stats(notas)

    solo_sin_asignar_var = tk.BooleanVar()

    def aplicar_filtros(*args):
        texto = filtro_texto.get().lower()
        tipo = filtro_tipo.get()
        solo_libres = solo_sin_asignar_var.get()

        resultado = notas

        # 🔎 FILTRO POR TEXTO
        if texto:
            if tipo == "cliente":
                resultado = [
                    n for n in resultado
                    if texto in (n["cliente_nombre"] or "").lower()
                ]

            elif tipo == "pedido":
                resultado = [
                    n for n in resultado
                    if texto in str(n["pedido"]).lower()
                ]

            elif tipo == "nota_id":
                resultado = [
                    n for n in resultado
                    if texto in str(n["id"]).lower()
                ]

            elif tipo == "telefono":
                resultado = [
                    n for n in resultado
                   if texto in str(n.get("telefono", "")).lower()
                ]

        # 📦 FILTRO SOLO SIN ASIGNAR
        if solo_libres:
            resultado = [
                n for n in resultado
                if not n["empacador_actual"]
            ]

        cargar_tabla(resultado)

    chk_sin_asignar = ctk.CTkCheckBox(
        win,
        text="Mostrar solo notas sin empacador",
        variable=solo_sin_asignar_var,
        command=lambda: aplicar_filtros()
    )
    chk_sin_asignar.pack(anchor="w", padx=20, pady=(0, 5))


    filtro_tipo = tk.StringVar(value="cliente")
    
    combo_filtro = ctk.CTkComboBox(
        frame_filtro,
        values=["cliente", "telefono", "pedido", "nota_id"],
        variable=filtro_tipo,
        width=150
    )
    combo_filtro.pack(side="left", padx=5)

    filtro_texto = tk.StringVar()

    entry = ctk.CTkEntry(
        frame_filtro,
        placeholder_text="Buscar...",
        textvariable=filtro_texto
    )
    entry.pack(side="left", fill="x", expand=True, padx=5)

    filtro_texto.trace_add("write", aplicar_filtros)
    combo_filtro.configure(command=lambda _: aplicar_filtros())
 

    # ================= TABLA =================
    cols = ("ID", "Cliente", "Pedido", "Progreso", "Estado", "Empacador")



    tabla = ttk.Treeview(
        win,
        columns=cols,
        show="headings",
        selectmode="extended"
    )

    for c in cols:
        tabla.heading(c, text=c)
        tabla.column(c, anchor="center")
    # ================= CONTADOR SELECCIÓN =================
    lbl_contador = ctk.CTkLabel(
        win,
        text="📦 0 notas seleccionadas",
        font=("Segoe UI", 13, "bold")
    )
    lbl_contador.pack(pady=(0, 5))

    tabla.pack(fill="both", expand=True, padx=15, pady=10)

    # 🎨 COLORES
    tabla.tag_configure("PAGADA", background="#FEF3C7")
    tabla.tag_configure("EN_PROCESO", background="#DBEAFE")
    tabla.tag_configure("INCOMPLETA", background="#FEE2E2")
    tabla.tag_configure("COMPLETA", background="#DCFCE7")
    tabla.tag_configure("SIN_ASIGNAR", background="#F3F4F6")

   
    def cargar_tabla(data):
        tabla.delete(*tabla.get_children())

        for n in data:

            # calcular progreso
            empacadas = n["empacadas"]
            requeridas = n["requeridas"]


            if requeridas > 0:
                porcentaje = int((empacadas / requeridas) * 100)
            else:
                porcentaje = 0

            progreso = f"{empacadas} / {requeridas} ({porcentaje}%)"

            if porcentaje == 100:
                tag_estado = "COMPLETA"
            elif porcentaje > 0:
                tag_estado = "EN_PROCESO"
            elif not n["empacador_actual"]:
                tag_estado = "SIN_ASIGNAR"            
            else:
                tag_estado = n["estado"]

            tabla.insert(
                "",
                "end",
                values=(
                    n["id"],
                    n["cliente_nombre"],
                    n["pedido"],
                    progreso,
                    "COMPLETA" if porcentaje == 100 else
                    "EN_PROCESO" if porcentaje > 0 else
                    n["estado"],

                    n["empacador_actual"] if n["empacador_actual"] else "Sin asignar"
                ),
                tags=(tag_estado,)
            )

    cargar_tabla(notas)
   
    def recargar_datos():
        conn = get_conn()
       
        nuevas_notas = conn.execute("""
            SELECT 
                n.id,
                n.cliente_nombre,
                n.pedido,
                n.fecha_asignacion,
                n.estado,
                e.nombre AS empacador_actual,
                c.telefono,

                COALESCE(SUM(i.empacadas),0) AS empacadas,
                COALESCE(SUM(i.cantidad),0) AS requeridas

            FROM notas n
            LEFT JOIN empacadores e ON e.id = n.empacador_id
            LEFT JOIN clientes c ON c.id = n.cliente_id
            LEFT JOIN items i ON i.nota_id = n.id

            WHERE n.estado != 'ARCHIVADA'
            AND (
                n.estado NOT IN ('COMPLETA')
                OR n.fecha_asignacion >= NOW() - INTERVAL '24 HOURS'
            )

            GROUP BY n.id, e.nombre, c.telefono
            ORDER BY n.fecha_asignacion DESC NULLS LAST


        """).fetchall()

        conn.close()

        return nuevas_notas

        
    def actualizar_contador(event=None):
        seleccionadas = tabla.selection()
        cantidad = len(seleccionadas)

        if cantidad == 0:
            texto = "📦 0 notas seleccionadas"
        elif cantidad == 1:
            texto = "📦 1 nota seleccionada"
        else:
            texto = f"📦 {cantidad} notas seleccionadas"

        lbl_contador.configure(text=texto)

    tabla.bind("<<TreeviewSelect>>", actualizar_contador)

    # ================= FILTRO DINÁMICO =================



    # ================= EMPACADORES =================
    empacadores = listar_empacadores_activos()
    nombres_emp = [e["nombre"] for e in empacadores]

    combo = ctk.CTkComboBox(
        win,
        values=nombres_emp
    )
    combo.pack(pady=10)

    if nombres_emp:
        combo.set(nombres_emp[0])

    # ================= ASIGNAR =================
    def asignar():
        seleccion = tabla.selection()
        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona al menos una nota")
            return

        nombre_emp = combo.get()

        emp = next(
            (e for e in empacadores if e["nombre"] == nombre_emp),
            None
        )

        if not emp:
            messagebox.showerror("Error", "Empacador inválido")
            return

        conn = get_conn()

        for item in seleccion:
            valores = tabla.item(item)["values"]
            nota_id = valores[0]

            conn.execute("""
                UPDATE notas
                SET empacador_id=%s,
                    fecha_asignacion=NOW(),
                    estado='EN_PROCESO'
                WHERE id=%s
            """, (emp["id"], nota_id))

        conn.commit()
        conn.close()

        # 🔄 RECARGAR
        nuevas_notas = recargar_datos()
        notas.clear()
        notas.extend(nuevas_notas)

        aplicar_filtros()
        actualizar_stats(notas)

        tabla.selection_remove(*tabla.selection())
        actualizar_contador()

        mostrar_toast("✅ Notas asignadas correctamente")
        
    def mostrar_toast(mensaje, color="#16A34A"):

        toast = ctk.CTkToplevel(root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)

        ancho = 320
        alto = 60

        x = root.winfo_x() + root.winfo_width() - ancho - 20
        y = root.winfo_y() + 40

        toast.geometry(f"{ancho}x{alto}+{x}+{y}")

        frame = ctk.CTkFrame(
            toast,
            fg_color=color,
            corner_radius=15
        )
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text=mensaje,
            font=("Segoe UI", 13, "bold"),
            text_color="white"
        ).pack(expand=True)

        toast.after(2500, toast.destroy)

        


    def desasignar():
        seleccion = tabla.selection()
        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona al menos una nota")
            return

        if not messagebox.askyesno(
            "Confirmar",
            "¿Desasignar empacador de las notas seleccionadas?"
        ):
            return

        conn = get_conn()

        for item in seleccion:
            valores = tabla.item(item)["values"]
            nota_id = valores[0]

            conn.execute("""
                UPDATE notas
                SET empacador_id = NULL
                WHERE id = %s
            """,(nota_id,))

        conn.commit()
        conn.close()

        # 🔄 RECARGAR
        nuevas_notas = recargar_datos()
        notas.clear()
        notas.extend(nuevas_notas)

        aplicar_filtros()
        actualizar_stats(notas)

        tabla.selection_remove(*tabla.selection())
        actualizar_contador()
    
        mostrar_toast("🔄 Notas desasignadas", "#DC2626")

    
    # ================= BOTONES ACCIÓN =================
    frame_botones = ctk.CTkFrame(win, fg_color="transparent")
    frame_botones.pack(fill="x", padx=20, pady=15)

    frame_botones.grid_columnconfigure((0,1,2,3), weight=1)
    btn_asignar = ctk.CTkButton(
        frame_botones,
        text="🚀 Asignar",
        height=45,
        corner_radius=12,
        fg_color="#16A34A",
        hover_color="#15803D",
        font=("Segoe UI", 14, "bold"),
        command=asignar
    )
    btn_asignar.grid(row=0, column=0, padx=10, sticky="ew")
    btn_desasignar = ctk.CTkButton(
        frame_botones,
        text="🔄 Desasignar",
        height=45,
        corner_radius=12,
        fg_color="#DC2626",
        hover_color="#B91C1C",
        font=("Segoe UI", 14, "bold"),
        command=desasignar
    )
    btn_desasignar.grid(row=0, column=1, padx=10, sticky="ew")

    def recargar_manual():
        nuevas_notas = recargar_datos()
        notas.clear()
        notas.extend(nuevas_notas)
        aplicar_filtros()
        actualizar_stats(notas)

    btn_recargar = ctk.CTkButton(
        frame_botones,
        text="🔄 Actualizar",
        height=45,
        corner_radius=12,
        fg_color="#2563EB",
        hover_color="#1D4ED8",
        font=("Segoe UI", 14, "bold"),
        command=recargar_manual
    )
    btn_recargar.grid(row=0, column=2, padx=10, sticky="ew")
    btn_cerrar = ctk.CTkButton(
        frame_botones,
        text="✖ Cerrar",
        height=45,
        corner_radius=12,
        fg_color="#6B7280",
        hover_color="#4B5563",
        font=("Segoe UI", 14, "bold"),
        command=win.destroy
    )
    btn_cerrar.grid(row=0, column=3, padx=10, sticky="ew")

    auto_refresh()

  
def abrir_panel_envios():

    if not pedir_password():
        return

    from database.connection import get_conn

    conn = get_conn()
    estado_filtro = tk.StringVar(value="COMPLETAS")



    conn.close()

    win = ctk.CTkToplevel(root)
    win.title("Gestión de Envíos")
    win.geometry("1200x750")
    win.grab_set()


    def cargar_datos():
        conn = get_conn()

        estado = estado_filtro.get()

        where_extra = ""

        if estado == "COMPLETAS":
            where_extra = "WHERE n.estado = 'COMPLETA'"
        elif estado == "EN_PROCESO":
            where_extra = "WHERE n.estado = 'EN_PROCESO'"
        elif estado == "INCOMPLETAS":
            where_extra = "WHERE n.estado = 'INCOMPLETA'"
        elif estado == "TODAS_PAGADAS":
            where_extra = "WHERE n.estado = 'PAGADA'"
        else:
            where_extra = ""

        notas_db = conn.execute(f"""
            SELECT 
                n.id,
                n.cliente_nombre,
                n.pedido,
                n.estado,
                n.paqueteria,
                n.guia,
                n.fecha,
                c.telefono
            FROM notas n
            LEFT JOIN clientes c ON c.id = n.cliente_id
            {where_extra}
            ORDER BY n.fecha DESC
        """).fetchall()

        conn.close()

        return notas_db

    # ================= FILTROS =================
    frame_filtro = ctk.CTkFrame(win)
    frame_filtro.pack(fill="x", padx=20, pady=15)

    filtro_tipo = tk.StringVar(value="nota")

    combo_filtro = ctk.CTkComboBox(
        frame_filtro,
        values=["nota", "cliente", "telefono", "pedido"],
        variable=filtro_tipo,
        width=150
    )
    combo_filtro.pack(side="left", padx=5)
    combo_estado = ctk.CTkComboBox(
        win,
        values=["COMPLETAS"],
        variable=estado_filtro,
        width=180
    )
    combo_estado.pack(pady=5)
    def desbloquear_avanzado():
        if not pedir_password():
            return
    
        combo_estado.configure(
            values=["COMPLETAS", "EN_PROCESO", "INCOMPLETAS", "TODAS_PAGADAS"]
        )

    ctk.CTkButton(
        win,
        text="🔐 Ver estados avanzados",
        command=desbloquear_avanzado
    ).pack(pady=5)
    def cambiar_estado(_=None):
        nuevas = cargar_datos()
        cargar_tabla(nuevas)

    combo_estado.configure(command=cambiar_estado)


    filtro_texto = tk.StringVar()

    entry_buscar = ctk.CTkEntry(
        frame_filtro,
        textvariable=filtro_texto,
        placeholder_text="Buscar..."
    )
    entry_buscar.pack(side="left", fill="x", expand=True, padx=5)

    # ================= TABLA =================
    cols = (
        "ID",
        "Cliente",
        "Pedido",
        "Teléfono",
        "Paquetería",
        "Guía"
    )

    tabla = ttk.Treeview(
        win,
        columns=cols,
        show="headings",
        selectmode="extended"
    )

    for c in cols:
        tabla.heading(c, text=c)
        tabla.column(c, anchor="center")

    tabla.pack(fill="both", expand=True, padx=20, pady=15)

    tabla.tag_configure("SIN_GUIA", background="#F3F4F6")
    tabla.tag_configure("CON_GUIA", background="#DBEAFE")

    def cargar_tabla(data):
        tabla.delete(*tabla.get_children())

        for n in data:
            tag = "CON_GUIA" if n["guia"] else "SIN_GUIA"

            tabla.insert(
                "",
                "end",
                values=(
                    n["id"],
                    n["cliente_nombre"],
                    n["pedido"],
                    n["telefono"],
                    n["paqueteria"] or "No definida",
                    n["guia"] or "Sin guía"
                ),
                tags=(tag,)
            )


    notas = cargar_datos()
    cargar_tabla(notas)
     # ================= FILTRO DINÁMICO =================
    def aplicar_filtro(*args):
        texto = filtro_texto.get().lower()
        tipo = filtro_tipo.get()

        datos_actuales = cargar_datos()
        resultado = datos_actuales

        if texto:
            if tipo == "cliente":
                resultado = [n for n in resultado if texto in (n["cliente_nombre"] or "").lower()]
            elif tipo == "nota":
                resultado = [n for n in resultado if texto in str(n["id"]).lower()]
            elif tipo == "pedido":
                resultado = [n for n in resultado if texto in str(n["pedido"]).lower()]
            elif tipo == "telefono":
                resultado = [n for n in resultado if texto in str(n["telefono"] or "").lower()]

        cargar_tabla(resultado)

    filtro_texto.trace_add("write", aplicar_filtro)
    combo_filtro.configure(command=lambda _: aplicar_filtro())


    # ================= ASIGNAR GUÍA =================
    def asignar_guia():
        seleccion = tabla.selection()

        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona una nota")
            return

        item = tabla.item(seleccion[0])["values"]
        nota_id = item[0]

        guia = simpledialog.askstring(
            "Asignar guía",
            "Número de guía:"
        )

        if not guia:
            return

        conn = get_conn()

        conn.execute("""
            UPDATE notas
            SET guia=%s
            WHERE id=%s
        """, (guia, nota_id))

        conn.commit()
        conn.close()

        messagebox.showinfo("OK", "Guía asignada")

        win.destroy()
        abrir_panel_envios()

    ctk.CTkButton(
        win,
        text="➕ Asignar guía",
        height=45,
        fg_color="#16A34A",
        hover_color="#15803D",
        font=("Segoe UI", 14, "bold"),
        command=asignar_guia
    ).pack(pady=15)


# =====================================================
# 🔵 FILTRAR SOLO CLIENTES COMPLETOS
# =====================================================



def clientes_completos(clientes):
    def valido(c):
        return (
            c.get("nombre") and
            c.get("telefono") and
            c.get("direccion") and
            c["direccion"].get("calle") and
            c["direccion"].get("codigo_postal")
        )

    return [c for c in clientes if valido(c)]




def elegir_pedido():

    from database.connection import get_conn

    win = ctk.CTkToplevel(root)
    win.title("Seleccionar pedido")
    win.geometry("800x500")
    win.grab_set()

    # ================= FILTROS =================
    frame_filtros = ctk.CTkFrame(win)
    frame_filtros.pack(fill="x", padx=20, pady=15)

    filtro_numero = tk.StringVar()
    filtro_fecha = tk.StringVar()

    entry_num = ctk.CTkEntry(
        frame_filtros,
        textvariable=filtro_numero,
        placeholder_text="Número de pedido..."
    )
    entry_num.pack(side="left", fill="x", expand=True, padx=5)

    entry_fecha = ctk.CTkEntry(
        frame_filtros,
        textvariable=filtro_fecha,
        placeholder_text="Fecha (YYYY-MM-DD)..."
    )
    entry_fecha.pack(side="left", fill="x", expand=True, padx=5)

    # ================= TABLA =================
    cols = ("Pedido", "Desde", "Hasta")


    tabla = ttk.Treeview(win, columns=cols, show="headings")

    for c in cols:
        tabla.heading(c, text=c)
        tabla.column(c, anchor="center")

    tabla.pack(fill="both", expand=True, padx=20, pady=10)

    def cargar_datos():
        conn = get_conn()

        pedidos = conn.execute("""
            SELECT numero, desde, hasta
            FROM pedidos
            ORDER BY desde DESC
        """).fetchall()


        conn.close()
        return pedidos

    pedidos_db = cargar_datos()

    def cargar_tabla(data):
        tabla.delete(*tabla.get_children())

        for p in data:
            tabla.insert(
                "",
                "end",
                values=(
                    p["numero"],
                    p["desde"],
                    p["hasta"]
                )
            )



    cargar_tabla(pedidos_db)

    # ================= FILTRO DINÁMICO =================
    def aplicar_filtro(*args):

        num = filtro_numero.get().lower()
        fecha = filtro_fecha.get().lower()

        resultado = pedidos_db

        if num:
            resultado = [
                p for p in resultado
                if num in str(p["numero"]).lower()
            ]

        if fecha:
            resultado = [
                p for p in resultado
                if fecha in str(p["desde"]).lower()
                or fecha in str(p["hasta"]).lower()
            ]

        cargar_tabla(resultado)


    filtro_numero.trace_add("write", aplicar_filtro)
    filtro_fecha.trace_add("write", aplicar_filtro)

    # ================= SELECCIONAR =================
    def confirmar():
        sel = tabla.focus()
        if not sel:
            return

        valores = tabla.item(sel)["values"]

        numero_pedido = valores[0]

        # 👉 aquí actualizas tu variable global o label
        pedido_actual.set(numero_pedido)

        win.destroy()

    ctk.CTkButton(
        win,
        text="Seleccionar pedido",
        height=40,
        fg_color="#1976D2",
        command=confirmar
    ).pack(pady=10)







def seleccionar_cliente():
    global cliente_actual

    clientes = clientes_completos(listar_clientes())


    win = tk.Toplevel(root)
    win.title("Seleccionar cliente")
    win.geometry("420x520")
    win.grab_set()

    cliente_actual = None

    # ================= BUSCADOR =================
    tk.Label(
        win,
        text="Buscar (nombre o teléfono)",
        font=("Segoe UI", 11, "bold")
    ).pack(pady=(10, 0))

    buscar_var = tk.StringVar()

    entry_buscar = tk.Entry(
        win,
        textvariable=buscar_var,
        font=("Segoe UI", 12)
    )
    entry_buscar.pack(fill="x", padx=12, pady=8)


    # ================= LISTA =================
    lista = tk.Listbox(
        win,
        font=("Segoe UI", 12),
        height=15
    )
    lista.pack(fill="both", expand=True, padx=12, pady=8)


    # ================= FUNCIONES =================

    def refrescar_lista(filtro=""):
        lista.delete(0, "end")

        # 🔥 opción ninguno siempre arriba
        lista.insert("end", "➕ Ninguno (cliente nuevo)")

        filtro = filtro.lower()

        for c in clientes:
            nombre = c.get("nombre", "")
            tel = c.get("telefono", "")

            if filtro in nombre.lower() or filtro in tel:
                texto = f"{nombre}   |   {tel}"
                lista.insert("end", texto)


    def al_escribir(*args):
        refrescar_lista(buscar_var.get())


    buscar_var.trace_add("write", al_escribir)


    def elegir(event=None):
        global cliente_actual

        if not lista.curselection():
            return

        texto = lista.get(lista.curselection())

        # 🔥 ninguno
        if texto.startswith("➕"):
            cliente_actual = None
            lbl_cliente_valor.configure(text="Cliente nuevo")
            btn_editar_cliente.pack_forget()

            win.destroy()
            return

        nombre = texto.split("|")[0].strip()

        for c in clientes:
            if c["nombre"] == nombre:
                cliente_actual = c
                break

        lbl_cliente_valor.configure(text=cliente_actual["nombre"])
        btn_editar_cliente.pack(side="right", padx=(6,0))

        win.destroy()


    lista.bind("<Double-1>", elegir)


    # ================= BOTÓN =================
    tk.Button(
        win,
        text="Seleccionar",
        command=elegir
    ).pack(pady=10)


    # primera carga
    refrescar_lista()

def configurar_pedido():
    global pedido_actual, fecha_desde, fecha_hasta

    from pedido_estado import cargar_pedido

    # =================================================
    # 🔵 VALIDAR PEDIDO ACTIVO (ANTES DE ABRIR VENTANA)
    # =================================================
    pedido_existente = cargar_pedido()

    if pedido_existente:
        if not pedir_password():
            return

        if not messagebox.askyesno(
            "Pedido activo",
            "⚠️ Ya existe un pedido en curso.\n\n¿Deseas crear uno nuevo?"
        ):
            return

    # =================================================
    # 🔵 AHORA SÍ → CREAR VENTANA
    # =================================================
    hoy = datetime.now()
    anio_actual = hoy.year

    win = ctk.CTkToplevel(root)
    win.title("Configurar pedido")
    win.geometry("340x330")
    win.grab_set()

    frame = ctk.CTkFrame(win, corner_radius=15)
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    # ================= PEDIDO =================
    ctk.CTkLabel(
        frame,
        text="Pedido #",
        font=("Segoe UI", 14, "bold")
    ).pack(pady=(10, 0))

    pedido_var = tk.StringVar(value=str(pedido_actual or ""))

    ctk.CTkEntry(
        frame,
        textvariable=pedido_var,
        width=120
    ).pack(pady=6)

    # ================= FECHAS =================
    def crear_selector_fecha(titulo):

        cont = ctk.CTkFrame(frame, fg_color="transparent")
        cont.pack(pady=8)

        ctk.CTkLabel(cont, text=titulo).pack()

        dias = ctk.CTkComboBox(cont, width=60)
        meses = ctk.CTkComboBox(cont, width=100)
        anios = ctk.CTkComboBox(cont, width=80)

        dias.pack(side="left", padx=4)
        meses.pack(side="left", padx=4)
        anios.pack(side="left", padx=4)

        meses.configure(values=[
            "Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
        ])

        anios.configure(values=[str(a) for a in range(anio_actual, anio_actual+4)])

        meses.set("Enero")
        anios.set(str(anio_actual))

        def actualizar_dias(*args):
            mes = meses.get()
            anio = int(anios.get())

            mes_num = [
                "Enero","Febrero","Marzo","Abril","Mayo","Junio",
                "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
            ].index(mes) + 1

            max_dia = calendar.monthrange(anio, mes_num)[1]

            dias.configure(values=[str(i) for i in range(1, max_dia+1)])
            dias.set("1")

        meses.configure(command=actualizar_dias)
        anios.configure(command=actualizar_dias)

        actualizar_dias()

        return dias, meses, anios


    d1, m1, a1 = crear_selector_fecha("Desde")
    d2, m2, a2 = crear_selector_fecha("Hasta")

    # ================= GUARDAR =================
    def guardar():
        global pedido_actual, fecha_desde, fecha_hasta

        pedido_actual = int(pedido_var.get())

        meses_lista = [
            "Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
        ]

        mes1 = meses_lista.index(m1.get()) + 1
        mes2 = meses_lista.index(m2.get()) + 1

        fecha_desde = f"{int(d1.get()):02d}/{mes1:02d}/{a1.get()}"
        fecha_hasta = f"{int(d2.get()):02d}/{mes2:02d}/{a2.get()}"


        try:
              pedido_data = {
                "numero": pedido_actual,
                "desde": fecha_desde,
                "hasta": fecha_hasta
            }

              # pedido activo
              guardar_pedido(pedido_data)

              # historial
              from pedidos import crear_pedido
              crear_pedido(pedido_actual, fecha_desde, fecha_hasta)

        except ValueError:
            messagebox.showerror(
                "Duplicado",
                "❌ Ese número de pedido ya existe.\nUsa otro número."
            )
            return


        lbl_pedido_valor.configure(
            text=f"Pedido #{pedido_actual}\n{fecha_desde} → {fecha_hasta}"
        )

        win.destroy()

    ctk.CTkButton(
        frame,
        text="Guardar",
        height=40,
        command=guardar
    ).pack(pady=15)

# ================= CONTEXTO MODERNO =================
frame_ctx = ctk.CTkFrame(
    card_contexto,
    corner_radius=15,
    fg_color="white"
)
frame_ctx.pack(fill="x", padx=15, pady=12)

# layout horizontal elegante
frame_ctx.grid_columnconfigure((0,1,2,3), weight=1)


marca_var = tk.StringVar()
hilo_var = tk.StringVar()

# ----- Marca -----
combo_marca = ctk.CTkComboBox(
    frame_ctx,
    variable=marca_var,
    width=180,
    height=40,
    command=actualizar_hilos,
    corner_radius=10,
    font=("Segoe UI", 13)
)
combo_marca.grid(row=0, column=0, padx=10, pady=12, sticky="ew")


# ----- Hilo -----
combo_hilo = ctk.CTkComboBox(
    frame_ctx,
    variable=hilo_var,
    width=180,
    height=40,
    
    corner_radius=10,
    font=("Segoe UI", 13)
)
combo_hilo.grid(row=0, column=1, padx=10, pady=12, sticky="ew")


# ----- Buscador visual (solo diseño) -----
buscar_producto_var = tk.StringVar(value="Código / Buscar producto")

entry_buscar = ctk.CTkEntry(
    frame_ctx,
    textvariable=buscar_producto_var,
    height=40,
    corner_radius=10,
    font=("Segoe UI", 13),
    text_color="#888"  # gris tipo placeholder
)
entry_buscar.grid(row=0, column=2, padx=10, pady=12, sticky="ew")

def limpiar_placeholder(event):
    if buscar_producto_var.get() == "Código / Buscar producto":
        buscar_producto_var.set("")
        entry_buscar.configure(text_color="black")


entry_buscar.bind("<FocusIn>", limpiar_placeholder)
def restaurar_placeholder(event):
    if not buscar_producto_var.get():
        buscar_producto_var.set("Código / Buscar producto")
        entry_buscar.configure(text_color="#888")


entry_buscar.bind("<FocusOut>", restaurar_placeholder)


# ================= DROPDOWN BUSCADOR =================
lista_sugerencias = tk.Listbox(
    frame_ctx,
    height=6,
    font=("Segoe UI", 12)
)

lista_sugerencias = tk.Listbox(
    root,   # 🔥 NO frame_ctx
    height=6,
    font=("Segoe UI", 12),
    bd=1,
    relief="solid"
)

lista_sugerencias.place_forget()  # oculto


def actualizar_sugerencias(*args):

    texto = buscar_producto_var.get().lower().strip()

    if not texto:
        lista_sugerencias.place_forget()
        return

    productos = obtener_productos(
        marca_var.get(),
        hilo_var.get()
    )

    encontrados = []

    for p in productos:
        if (texto in str(p["codigo"]).lower()
            or texto in p["marca"].lower()
            or texto in p["hilo"].lower()):
            encontrados.append(p)

    if not encontrados:
        lista_sugerencias.place_forget()
        return

    lista_sugerencias.delete(0, "end")

    for p in encontrados[:10]:
        lista_sugerencias.insert(
            "end",
            f"{p['marca']} | {p['hilo']} | {p['codigo']}"
        )

    # 🔥 POSICIÓN EXACTA debajo del entry
    x = entry_buscar.winfo_rootx() - root.winfo_rootx()
    y = entry_buscar.winfo_rooty() - root.winfo_rooty() + entry_buscar.winfo_height()

    lista_sugerencias.place(
        x=x,
        y=y,
        width=entry_buscar.winfo_width()
    )


def seleccionar_producto(event=None):

    if not lista_sugerencias.curselection():
        return

    texto = lista_sugerencias.get(lista_sugerencias.curselection())
    codigo = texto.split("|")[-1].strip()

    agregar_al_carrito({
        "codigo": codigo,
        "cantidad": 1
    })

    refrescar_carrito()

    buscar_producto_var.set("")
    lista_sugerencias.place_forget()


buscar_producto_var.trace_add("write", actualizar_sugerencias)

lista_sugerencias.bind("<Double-1>", seleccionar_producto)
lista_sugerencias.bind("<Return>", seleccionar_producto)



# ----- Botón verde moderno -----
btn_whatsapp = ctk.CTkButton(
    frame_ctx,
    text="📥 Analizar WhatsApp",
    height=40,
    corner_radius=12,
    fg_color="#2E7D32",
    hover_color="#1B5E20",
    font=("Segoe UI", 13, "bold"),
    command=analizar_whatsapp
)
btn_whatsapp.grid(row=0, column=3, padx=10, pady=12, sticky="ew")


def procesar_imagen(ruta_imagen):
    try:
        texto = leer_pedido_desde_imagen(ruta_imagen)

        texto = texto.replace("O", "0").replace("l", "1").replace("I", "1")

        productos = obtener_productos(
            marca_var.get(),
            hilo_var.get()
        )

        if not productos:
            messagebox.showwarning(
                "Contexto",
                "No hay productos para la marca e hilo seleccionados"
            )
            return

        resultado = extraer_pedidos(texto, productos)

        for pedido in resultado.get("pedidos", []):
            agregar_al_carrito(pedido)

        refrescar_carrito()

    except Exception as e:
        messagebox.showerror("Error", str(e))


def cargar_imagen():
    ruta = filedialog.askopenfilename(
        title="Seleccionar imagen",
        filetypes=[
            ("Imágenes", "*.png *.jpg *.jpeg *.bmp")
        ]
    )

    if ruta:
        procesar_imagen(ruta)

def drop_imagen(event):
    ruta = event.data.strip("{}")
    procesar_imagen(ruta)



def mostrar_resultado(texto, resultado):
    print("TEXTO OCR:")
    print(texto)

    print("\nPEDIDOS:")
    for p in resultado["pedidos"]:
        print(f"{p['codigo']} → {p['cantidad']}")

root.drop_target_register(DND_FILES)
root.dnd_bind("<<Drop>>", drop_imagen)


def cargar_contexto():
    marcas = obtener_marcas()

    combo_marca.configure(values=marcas)

    if marcas:
        marca_var.set(marcas[0])
        actualizar_hilos()




def guardar_cotizacion():
    global cliente_actual

    if not carrito:
        messagebox.showwarning("Vacío", "El carrito está vacío")
        return

    # ================= USAR CLIENTE SELECCIONADO =================
    if cliente_actual:
        cliente = cliente_actual

    else:
        # crear nuevo solo si no hay seleccionado
        nombre = simpledialog.askstring(
            "Cliente nuevo",
            "Nombre del cliente:"
        )

        if not nombre:
            return

        cliente = obtener_o_crear_cliente(nombre)

    # ================= GUARDAR NOTA =================
    crear_cotizacion(
        cliente,
        carrito,
        envio=envio_actual,
        pedido=pedido_actual   # 🔥 importante para tu sistema nuevo
    )

    messagebox.showinfo(
        "Guardado",
        f"Nota creada para {cliente['nombre']}"
    )
    


    carrito.clear()
    refrescar_carrito()


def actualizar_total_con_envio():
    total_productos = sum(p["cantidad"] * p["precio"] for p in carrito)
    envio_precio = envio_actual["precio"] if envio_actual else 0

    total = total_productos + envio_precio

    lbl_total.configure(text=f"${total:.2f}")


    
    
def configurar_envio_carrito():
    global envio_actual

    if not carrito:
        messagebox.showwarning(
            "Carrito vacío",
            "Agrega productos antes de configurar el envío"
        )
        return

    vol_total = calcular_volumetrico_total(carrito)

    envio = seleccionar_envio(root, vol_total)
    if not envio:
        return

    envio_actual = envio

    lbl_envio.configure(
        text=f"Envío: ${envio['precio']:.2f}"
    )

    actualizar_total_con_envio()

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


def eliminar_producto_carrito():
    seleccion = tabla_carrito.selection()

    if not seleccion:
        messagebox.showinfo("Selecciona", "Selecciona productos primero")
        return

    if not pedir_password():
        return

    # 🔥 obtener códigos como STRING
    codigos = []
    for item in seleccion:
        valores = tabla_carrito.item(item)["values"]
        codigos.append(str(valores[2]))

    global carrito

    carrito = [
        p for p in carrito
        if str(p["codigo"]) not in codigos
    ]

    refrescar_carrito()


    

def editar_cantidad_multiple():
    seleccion = tabla_carrito.selection()

    if not seleccion:
        messagebox.showinfo("Selecciona", "Selecciona productos primero")
        return

    nueva = simpledialog.askinteger(
        "Cantidad",
        "Nueva cantidad para todos:",
        minvalue=1
    )

    if nueva is None:
        return

    # 🔥 FORZAR STRING
    codigos = []
    for item in seleccion:
        valores = tabla_carrito.item(item)["values"]
        codigos.append(str(valores[2]))

    for p in carrito:
        if str(p["codigo"]) in codigos:
            p["cantidad"] = nueva

    refrescar_carrito()




def editar_precio_multiple():
    seleccion = tabla_carrito.selection()

    if not seleccion:
        messagebox.showinfo("Selecciona", "Selecciona productos primero")
        return

    if not pedir_password():
        return

    nuevo = simpledialog.askfloat(
        "Precio",
        "Nuevo precio para todos:"
    )

    if nuevo is None:
        return

    codigos = []
    for item in seleccion:
        valores = tabla_carrito.item(item)["values"]
        codigos.append(str(valores[2]))

    for p in carrito:
        if str(p["codigo"]) in codigos:
            p["precio"] = nuevo

    refrescar_carrito()

def nuevo_pedido():
    global pedido_actual

    win = tk.Toplevel(root)
    win.title("Nuevo pedido")
    win.geometry("300x220")
    win.grab_set()

    tk.Label(win, text="Número pedido").pack()
    num_var = tk.IntVar()
    tk.Entry(win, textvariable=num_var).pack()

    tk.Label(win, text="Fecha inicio (DD/MM/AAAA)").pack()
    ini_var = tk.StringVar()
    tk.Entry(win, textvariable=ini_var).pack()

    tk.Label(win, text="Fecha fin (DD/MM/AAAA)").pack()
    fin_var = tk.StringVar()
    tk.Entry(win, textvariable=fin_var).pack()

    def guardar():
        pedido_actual = crear_pedido(
            num_var.get(),
            ini_var.get(),
            fin_var.get()
        )

        lbl_pedido_valor.configure(
            text=f"Pedido #{pedido_actual['numero']}  |  {pedido_actual['fecha_inicio']} - {pedido_actual['fecha_fin']}"
        )

        win.destroy()

    tk.Button(win, text="Guardar", command=guardar).pack(pady=10)

def abrir_dashboard():

    from admin_metricas import obtener_metricas_empacadores

    datos = obtener_metricas_empacadores()

    win = ctk.CTkToplevel(root)
    win.title("Dashboard de Empacadores")
    win.geometry("900x500")

    cols = (
        "Empacador",
        "Total",
        "Completas",
        "Incompletas",
        "Errores",
        "Tiempo Prom (min)"
    )

    tabla = ttk.Treeview(
        win,
        columns=cols,
        show="headings"
    )

    for c in cols:
        tabla.heading(c, text=c)
        tabla.column(c, anchor="center")

    tabla.pack(fill="both", expand=True, padx=20, pady=20)

    for row in datos:
        tabla.insert(
            "",
            "end",
            values=(
                row["nombre"],
                row["total_notas"],
                row["completas"],
                row["incompletas"],
                row["errores"],
                round(row["tiempo_promedio_min"] or 0, 1)
            )
        )

def abrir_panel_errores():

    from admin_errores import obtener_errores

    datos = obtener_errores()

    win = ctk.CTkToplevel(root)
    win.title("Errores de Escaneo")
    win.geometry("1000x500")

    cols = ("Fecha", "Empacador", "Nota", "Código", "Motivo")

    tabla = ttk.Treeview(
        win,
        columns=cols,
        show="headings"
    )

    for c in cols:
        tabla.heading(c, text=c)
        tabla.column(c, anchor="center")

    tabla.pack(fill="both", expand=True, padx=20, pady=20)

    for row in datos:
        tabla.insert(
            "",
            "end",
            values=(
                row["fecha"],
                row["nombre"],
                row["nota_id"],
                row["codigo"],
                row["motivo"]
            )
        )
        
def obtener_ranking():

    from database.connection import get_conn

    conn = get_conn()

    rows = conn.execute("""
        SELECT 
            e.nombre,
            COUNT(n.id) AS completadas
        FROM empacadores e
        JOIN notas n 
            ON n.empacador_id = e.id
        WHERE n.estado = 'COMPLETA'
        GROUP BY e.nombre
        ORDER BY completadas DESC
        LIMIT 3
    """).fetchall()

    conn.close()

    return rows



# ================= WHATSAPP =================
frame_wa = tk.LabelFrame(card_whatsapp, text="WhatsApp")
frame_wa.pack(fill="both", expand=True)

txt_whatsapp = tk.Text(frame_wa, height=10)
txt_whatsapp.pack(fill="both", expand=True)

# ================= CARRITO =================
# ================= CARRITO MODERNO =================

# ---- tarjeta principal ----
frame_carrito = ctk.CTkFrame(
    card_carrito,
    corner_radius=18,
    fg_color="white"
)
frame_carrito.pack(fill="both", expand=True, padx=15, pady=12)


# ================= HEADER =================
header = ctk.CTkLabel(
    frame_carrito,
    text="Carrito",
    font=("Segoe UI", 18, "bold"),
    anchor="w"
)
header.pack(fill="x", padx=20, pady=(15, 5))


# ================= TABLA =================
frame_tabla = tk.Frame(frame_carrito, bg="white")
frame_tabla.pack(fill="both", expand=True, padx=15, pady=10)


style = ttk.Style()
style.theme_use("default")

style.configure(
    "Treeview",
    background="white",
    foreground="black",
    rowheight=38,
    fieldbackground="white",
    borderwidth=0,
    font=("Segoe UI", 12)
)

style.configure(
    "Treeview.Heading",
    font=("Segoe UI", 12, "bold"),
    background="#F3F4F6",
    foreground="#333"
)

style.map("Treeview", background=[("selected", "#DCEBFF")])


cols = ("Marca", "Hilo", "Código", "Cantidad", "Precio", "Subtotal")

tabla_carrito = ttk.Treeview(
    frame_tabla,
    columns=cols,
    show="headings",
    selectmode="extended"
)

for c in cols:
    tabla_carrito.heading(c, text=c)
    tabla_carrito.column(c, anchor="center")

tabla_carrito.pack(fill="both", expand=True)


# zebra rows
tabla_carrito.tag_configure("odd", background="#FAFAFA")
tabla_carrito.tag_configure("even", background="white")
tabla_carrito.tag_configure("bajo", background="#FFE5E5")


tabla_carrito.bind("<Double-1>", lambda e: editar_cantidad_multiple())


# ================= FOOTER =================
footer = tk.Frame(frame_carrito, bg="white")
footer.pack(fill="x", padx=15, pady=(5, 15))


menu = tk.Menu(root, tearoff=0)

menu.add_command(label="Cantidad múltiple", command=editar_cantidad_multiple)
menu.add_command(label="Precio múltiple", command=editar_precio_multiple)
menu.add_separator()
menu.add_command(label="Adjuntar imagen", command=cargar_imagen)
menu.add_command(label="Eliminar producto", command=eliminar_producto_carrito)


def mostrar_menu(event):
    menu.tk_popup(event.x_root, event.y_root)


btn_menu = ctk.CTkButton(
    footer,
    text="⋯  Otros",
    width=120,
    height=36,
    corner_radius=12,
    fg_color="#F2F2F2",
    text_color="black"
)

btn_menu.pack(side="left")
btn_menu.bind("<Button-1>", mostrar_menu)


BASE_DIR = os.path.dirname(__file__)
icon_path = os.path.join(BASE_DIR, "trash.png.png")
icon_trash = ctk.CTkImage(
    Image.open(icon_path),
    size=(60, 60)
)
btn_limpiar = ctk.CTkButton(
    footer,
    text="",
    image=icon_trash,
    width=38,
    height=38,
    corner_radius=18,
    fg_color="transparent",
    hover_color="#FFE5E5",
    command=lambda: [carrito.clear(), refrescar_carrito()]
)

btn_limpiar.pack(side="right")

# ================= HEADER SUPERIOR DERECHO =================
frame_top = tk.Frame(root)
frame_top.pack(fill="x", padx=10, pady=(5, 0))

frame_top.columnconfigure(0, weight=1)  # empuja botones a la derecha

frame_top_btns = tk.Frame(frame_top)
frame_top_btns.grid(row=0, column=1, sticky="e")
btn_clientes = ctk.CTkButton(
    frame_top_btns,
    text="👤 Clientes",
    corner_radius=18,
    fg_color="#FB8C00",      # naranja moderno
    hover_color="#EF6C00",
    height=36,
    width=130,
    font=("Segoe UI", 13, "bold"),
    command=lambda: abrir_clientes(root)
)
btn_clientes.pack(side="left", padx=5)

# ================= PANEL TOTAL MODERNO (VERTICAL) =================

frame_total = ctk.CTkFrame(
    card_total,
    corner_radius=18,
    fg_color="white"
)
frame_total.pack(fill="both", expand=True, padx=20, pady=20)


# ===== TOTAL =====
lbl_total_title = ctk.CTkLabel(
    frame_total,
    text="TOTAL",
    font=("Segoe UI", 14)
)
lbl_total_title.pack(anchor="w", padx=20, pady=(20, 0))


lbl_total = ctk.CTkLabel(
    frame_total,
    text="$0.00",
    font=("Segoe UI", 36, "bold")
)
lbl_total.pack(anchor="w", padx=20, pady=(0, 15))


ctk.CTkFrame(frame_total, height=2, fg_color="#EEEEEE").pack(fill="x", padx=15, pady=5)


# ===== ENVÍO + BOTÓN (MISMA FILA) =====
frame_envio = ctk.CTkFrame(frame_total, fg_color="transparent")
frame_envio.pack(fill="x", padx=20, pady=10)

frame_envio.columnconfigure(0, weight=1)  # texto ocupa todo
frame_envio.columnconfigure(1, weight=0)  # botón tamaño fijo

BASE_DIR = os.path.dirname(__file__)

icon_ship_path  = os.path.join(BASE_DIR, "shipping.png")
icon_ship  = ctk.CTkImage(Image.open(icon_ship_path),  size=(120, 120))

lbl_envio = ctk.CTkLabel(
    frame_envio,
    text="Envío: No configurado",
    font=("Segoe UI", 13)
)
lbl_envio.grid(row=0, column=0, sticky="w")


btn_envio = ctk.CTkButton(
    frame_envio,
    text="",
    image=icon_ship,
    width=36,
    height=36,
    fg_color="transparent",
    hover_color="#E3F2FD",
    corner_radius=18,
    command=configurar_envio_carrito
)
btn_envio.grid(row=0, column=1, padx=(5, 0))




# ===== BLOQUE CLIENTE + PEDIDO (compacto) =====
frame_cliente_pedido = ctk.CTkFrame(
    frame_total,
    fg_color="transparent"
)
frame_cliente_pedido.pack(fill="x", padx=20, pady=(10, 5))


# ---- cliente ----
# ==================================================
# 🔵 CLIENTE CON ICONO EDITAR
# ==================================================

frame_cliente_btns = ctk.CTkFrame(
    frame_cliente_pedido,
    fg_color="transparent"
)
frame_cliente_btns.pack(fill="x", padx=40, pady=(0, 6))


# ---- botón principal seleccionar ----
lbl_cliente_valor = ctk.CTkButton(
    frame_cliente_btns,
    text="👤 Seleccionar cliente...",
    fg_color="#F3F4F6",
    text_color="black",
    corner_radius=12,
    height=40,
    command=seleccionar_cliente
)
lbl_cliente_valor.pack(side="left", fill="x", expand=True)


# ---- icono editar ----
icon_edit_path = os.path.join(BASE_DIR, "edit.png")

icon_edit = ctk.CTkImage(
    Image.open(icon_edit_path),
    size=(20, 20)
)

btn_editar_cliente = ctk.CTkButton(
    frame_cliente_btns,
    text="",
    image=icon_edit,
    width=40,
    height=40,
    fg_color="#E3F2FD",
    hover_color="#BBDEFB",
    corner_radius=12,
    command=lambda: (
        editar_cliente_por_id(cliente_actual["id"], root)
        if cliente_actual else abrir_clientes(root)
    )

  # 🔥 abre tu editor real
)


# 🔥 oculto al inicio
btn_editar_cliente.pack_forget()



# ---- pedido ----
# =========================================
# 🎯 CARD PEDIDO MODERNO
# =========================================

card_pedido = ctk.CTkFrame(
    frame_cliente_pedido,
    corner_radius=18,
    fg_color="#FFFFFF"
)
card_pedido.pack(fill="x", pady=(0, 5))


# ---- título pedido grande ----
lbl_pedido_valor = ctk.CTkLabel(
    card_pedido,
    text="📦 Configurar pedido",
    font=("Segoe UI", 18, "bold"),
    anchor="w"
)
lbl_pedido_valor.pack(fill="x", padx=18, pady=(14, 0))


# ---- fecha ----
lbl_pedido_fecha = ctk.CTkLabel(
    card_pedido,
    text="",
    font=("Segoe UI", 13),
    text_color="#555",
    anchor="w"
)
lbl_pedido_fecha.pack(fill="x", padx=18, pady=(0, 10))


# ---- botón pequeño dentro (encimado) ----
ctk.CTkButton(
    card_pedido,
    text="🔁 Cambiar pedido",
    height=30,
    fg_color="#F2F6FF",
    text_color="#1976D2",
    hover_color="#E3F2FD",
    corner_radius=10,
    command=elegir_pedido
).pack(anchor="w", padx=18, pady=(0,14))


# ---- click en la tarjeta = configurar ----
card_pedido.bind("<Button-1>", lambda e: configurar_pedido())
lbl_pedido_valor.bind("<Button-1>", lambda e: configurar_pedido())


frame_admin = ctk.CTkFrame(
    frame_top_btns,
    fg_color="transparent"
)
frame_admin.pack(side="left", padx=10)





# ===== BOTONES GRANDES =====
btn_guardar = ctk.CTkButton(
    frame_total,
    text="💾  Guardar nota",
    fg_color="#1976D2",
    hover_color="#1565C0",
    height=55,
    corner_radius=14,
    font=("Segoe UI", 16, "bold"),
    command=guardar_cotizacion
)
btn_guardar.pack(fill="x", padx=20, pady=(20, 10))


btn_ver = ctk.CTkButton(
    frame_total,
    text="👀  Ver notas",
    fg_color="#D8C140",
    hover_color="#EBE828",
    text_color="black",
    height=55,
    corner_radius=14,
    font=("Segoe UI", 16, "bold"),
    command=lambda: abrir_visor(root)
)
btn_ver.pack(fill="x", padx=20, pady=(0, 20))


icon_asignar_path = os.path.join(BASE_DIR, "asignar.png")

icon_asignar = ctk.CTkImage(
    Image.open(icon_asignar_path),
    size=(36, 36)
)

ctk.CTkButton(
    frame_total,
    text="",
    image=icon_asignar,
    width=55,
    height=55,
    fg_color="#F3F4F6",
    hover_color="#E5E7EB",
    corner_radius=15,
    command=abrir_panel_asignacion
).pack(pady=(0, 20))
ctk.CTkButton(
    frame_total,
    text="🚚 Gestión de Envíos",
    fg_color="#0EA5E9",
    hover_color="#0284C7",
    height=50,
    corner_radius=14,
    font=("Segoe UI", 15, "bold"),
    command=abrir_panel_envios
).pack(fill="x", padx=20, pady=(0, 20))

ctk.CTkButton(
    frame_admin,
    text="📊 Dashboard",
    height=36,
    corner_radius=12,
    fg_color="#7C3AED",
    hover_color="#6D28D9",
    command=abrir_dashboard
).pack(side="left", padx=5)

ctk.CTkButton(
    frame_admin,
    text="⚠ Errores",
    height=36,
    corner_radius=12,
    fg_color="#EF4444",
    hover_color="#DC2626",
    command=abrir_panel_errores
).pack(side="left", padx=5)



def agregar_al_carrito(pedido):
    codigo = pedido["codigo"]
    cantidad = pedido["cantidad"]

    productos = obtener_productos(
        marca_var.get(),
        hilo_var.get()
    )

    for p in productos:
        if p["codigo"] == codigo:
            precio = obtener_precio_venta(p["marca"])

            for c in carrito:
                if c["codigo"] == codigo:
                    c["cantidad"] += cantidad
                    return

            carrito.append({
                "marca": p["marca"],
                "hilo": p["hilo"],
                "codigo": codigo,
                "cantidad": cantidad,
                "precio": precio,
                "stock": p["stock"]
            })
            return

def refrescar_carrito():
    tabla_carrito.delete(*tabla_carrito.get_children())

    for i, p in enumerate(carrito):
        subtotal = p["cantidad"] * p["precio"]

        tag = "even" if i % 2 == 0 else "odd"

        if p["cantidad"] > p["stock"]:
            tag = "bajo"

        tabla_carrito.insert(
            "",
            "end",
            values=(
                p["marca"],
                p["hilo"],
                p["codigo"],
                p["cantidad"],
                f"${p['precio']:.2f}",
                f"${subtotal:.2f}"
            ),
            tags=(tag,)
        )

    actualizar_total_con_envio()

# ================= INICIO =================


def main():
    global pedido_actual, fecha_desde, fecha_hasta

    
    cargar_contexto()

    # =========================================
    # 🔵 PASO 2 → CARGAR PEDIDO GUARDADO
    # =========================================
    pedido_guardado = cargar_pedido()

    if pedido_guardado:
        pedido_actual = pedido_guardado["numero"]
        fecha_desde = pedido_guardado["desde"]
        fecha_hasta = pedido_guardado["hasta"]

        lbl_pedido_valor.configure(
            text=f"Pedido #{pedido_actual}\n{fecha_desde} → {fecha_hasta}"
        )

        # =====================================
        # 🔵 PASO 4 → AVISOS AUTOMÁTICOS
        # =====================================
        if pedido_por_vencer(pedido_guardado):
            messagebox.showwarning(
                "Pedido por vencer",
                "⚠️ Este pedido termina mañana.\nConsidera crear uno nuevo."
            )

        if pedido_vencido(pedido_guardado):
            messagebox.showinfo(
                "Pedido vencido",
                "Este pedido ya terminó.\nDebes crear uno nuevo."
            )

    crear_area_imagen(
        card_imagen,
        marca_var,
        hilo_var,
        agregar_al_carrito,
        refrescar_carrito
    )



    root.mainloop()

if __name__ == "__main__":
    main()
crear_cotizacion
