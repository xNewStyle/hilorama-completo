import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except Exception:
    TkinterDnD = None
    DND_FILES = "DND_FILES"
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
from clientes import obtener_o_crear_cliente, listar_clientes, buscar_cliente_por_telefono, buscar_clientes
from ver_cotizaciones import abrir_visor, ver_detalles
from ver_clientes import abrir_clientes, editar_cliente_por_id
from ver_notas_completo import abrir_visor_notas
from ver_cotizaciones import calcular_volumetrico_total, seleccionar_envio
from ocr import leer_pedido_desde_imagen
try:
    from ui_imagen import crear_area_imagen
except Exception:
    crear_area_imagen = None
import customtkinter as ctk
from PIL import Image
import os
import threading
from pedidos import actualizar_pedido, crear_pedido, listar_pedidos
from envios_config import formatear_costo_envio
import calendar
from datetime import datetime
from pedido_estado import pedido_por_vencer, pedido_vencido, cargar_pedido, activar_pedido
from impresion_etiquetas import etiqueta_remitente, etiqueta_destinatario
from decimal import Decimal
from hilorama_desktop.security.authorization import get_admin_override_key
# ================= CONFIG =================
PASSWORD = get_admin_override_key()

try:
    from hilorama_desktop.config import HILORAMA_DATA_MODE, require_local_mode
except Exception:
    HILORAMA_DATA_MODE = "local"
    def require_local_mode(area=""):
        if os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api":
            detalle = f" ({area})" if area else ""
            raise RuntimeError(f"Base local bloqueada en modo API cliente{detalle}.")


def _modo_api():
    return os.environ.get("HILORAMA_DATA_MODE", HILORAMA_DATA_MODE).strip().lower() == "api"


def _get_conn_local(area="ventas"):
    require_local_mode(area)
    from database.connection import get_conn
    return get_conn()


def _validar_acceso_inicial_ventas():
    try:
        from hilorama_desktop.services.auth_service import AuthService
        from hilorama_desktop.ui.login_window import solicitar_login

        auth_service = AuthService()
        session = auth_service.require_access(modulo="ventas")
        if session:
            return auth_service

        session = solicitar_login(auth_service=auth_service, modulo="ventas")
        if session:
            return auth_service
    except SystemExit:
        raise
    except Exception as exc:
        tmp = tk.Tk()
        tmp.withdraw()
        messagebox.showerror("Acceso", f"No se pudo validar el acceso:\n{exc}", parent=tmp)
        tmp.destroy()
        raise SystemExit(1)

    tmp = tk.Tk()
    tmp.withdraw()
    messagebox.showerror("Acceso", "Acceso cancelado o no autorizado.", parent=tmp)
    tmp.destroy()
    raise SystemExit(1)


_auth_service_ventas = None
_heartbeat_service_ventas = None

# ================= CARRITO =================
carrito = []
envio_actual = None
lbl_envio = None
cliente_actual = None
pedido_actual = None
fecha_desde = None
fecha_hasta = None
productos_cache = []

# ================= TK ROOT / CONTENEDORES =================
root = None
frame_main = None
card_contexto = None
card_whatsapp = None
card_carrito = None
card_imagen = None
card_total = None

frame_ctx = None
marca_var = None
hilo_var = None
combo_marca = None
combo_hilo = None
buscar_producto_var = None
entry_buscar = None
lista_sugerencias = None
btn_whatsapp = None

txt_whatsapp = None
tabla_carrito = None
lbl_total = None
lbl_piezas = None
lbl_cliente_valor = None
lbl_estado_cliente = None
lbl_pedido_valor = None
lbl_pedido_fecha = None
btn_editar_cliente = None
telefono_buscar_var = None


def _crear_root_ventas(parent=None):
    if parent is None:
        if TkinterDnD is not None:
            ventana = TkinterDnD.Tk()
        else:
            ventana = tk.Tk()
        ventana.title("Ventas Hilorama")
        ventana.geometry("1280x780")
        ventana.minsize(1100, 680)
        ventana.configure(bg="#EFEFEF")
        return ventana
    return tk.Frame(parent, bg="#EFEFEF")


def _crear_contenedores_ventas(parent=None):
    global root, frame_main, card_contexto, card_whatsapp
    global card_carrito, card_imagen, card_total

    root = _crear_root_ventas(parent)

    # ===== CONTENEDOR PRINCIPAL 2 COLUMNAS =====
    frame_main = tk.Frame(root, bg="#EFEFEF")
    frame_main.pack(fill="both", expand=True, padx=8, pady=8)

    # columnas → izquierda grande | derecha panel
    frame_main.columnconfigure(0, weight=5)
    frame_main.columnconfigure(1, weight=0, minsize=260)

    # filas → contexto | carrito | imagen
    frame_main.rowconfigure(0, weight=0)
    frame_main.rowconfigure(1, weight=1)
    frame_main.rowconfigure(2, weight=4)
    frame_main.rowconfigure(3, weight=1)


    card_contexto = tk.Frame(frame_main, bg="white")
    card_contexto.grid(row=0, column=0, sticky="ew", pady=(0,10))

    card_whatsapp = tk.Frame(frame_main, bg="white")
    card_whatsapp.grid(row=1, column=0, sticky="nsew", pady=(0,8))

    card_carrito = tk.Frame(frame_main, bg="white")
    card_carrito.grid(row=2, column=0, sticky="nsew", pady=(0,8))

    card_imagen = tk.Frame(frame_main, bg="white")
    card_imagen.grid(row=3, column=0, sticky="nsew")


    card_total = tk.Frame(frame_main, bg="white")
    card_total.grid(row=0, column=1, rowspan=4, sticky="nsew", padx=(8,0))

    return root


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
    global productos_cache

    marca = marca_var.get()
    hilos = obtener_hilos(marca)

    combo_hilo.configure(values=hilos)

    if hilos:
        hilo_var.set(hilos[0])

    actualizar_productos_cache()   # 👈 reemplaza la carga directa


def actualizar_productos_cache(_=None):
    global productos_cache

    productos_cache = obtener_productos(
        marca_var.get(),
        hilo_var.get()
    )




def cargar_contexto():
    marcas = obtener_marcas()

    combo_marca.configure(values=marcas)

    if marcas:
        marca_var.set(marcas[0])
        actualizar_hilos()

from clientes import listar_clientes

_impresion_lock = threading.Lock()


def _enviar_etiqueta_segura(data, descripcion):
    from impresion_etiquetas import ImpresionError, enviar_a_impresora

    if not _impresion_lock.acquire(blocking=False):
        try:
            from hilorama_desktop.utils.logger import log_info
            log_info("ventas", f"Impresion duplicada bloqueada: {descripcion}")
        except Exception:
            pass
        messagebox.showwarning(
            "Impresion en proceso",
            "Ya hay una impresion en proceso. Espera a que termine antes de reintentar.",
            parent=root,
        )
        return False

    try:
        resultado = enviar_a_impresora(data)
        try:
            from hilorama_desktop.utils.logger import log_info
            log_info(
                "ventas",
                (
                    f"Impresion enviada: {descripcion} "
                    f"bytes={resultado.bytes_enviados} "
                    f"conexion_ms={resultado.tiempo_conexion_ms} "
                    f"envio_ms={resultado.tiempo_envio_ms}"
                ),
            )
        except Exception:
            pass
        return True
    except ImpresionError as exc:
        try:
            from hilorama_desktop.utils.logger import log_error
            log_error(
                "ventas",
                f"Fallo al imprimir {descripcion}: etapa={exc.etapa} tipo={exc.tipo} mensaje={exc}",
                exc,
            )
        except Exception:
            pass
        messagebox.showerror("Impresion", str(exc), parent=root)
        return False
    except Exception as exc:
        try:
            from hilorama_desktop.utils.logger import log_error
            log_error(
                "ventas",
                f"Fallo inesperado al imprimir {descripcion}: tipo={type(exc).__name__}",
                exc,
            )
        except Exception:
            pass
        messagebox.showerror(
            "Impresion",
            "No fue posible enviar la impresion. Revisa el registro de errores antes de reintentar.",
            parent=root,
        )
        return False
    finally:
        _impresion_lock.release()



def imprimir_destinatario(nota):

    from clientes import obtener_cliente_por_id

    cliente_id = nota.get("cliente_id")

    if not cliente_id:
        messagebox.showerror("Error", "La nota no tiene cliente asignado")
        return

    cliente = obtener_cliente_por_id(cliente_id)

    if not cliente:
        messagebox.showerror("Error", "No se encontró el cliente")
        return

    data = etiqueta_destinatario(
            cliente,
        nota["id"],
        envio=nota.get("envio")
    )

    return _enviar_etiqueta_segura(data, "etiqueta de destinatario")


def obtener_mis_datos():
    return {
        "nombre": "JORGE ANGEL ORTIZ ANGUIANO",
        "telefono": "55 4541 4186",
        "direccion": {
            "calle": "Cocula",
            "numero_ext": "246",
            "numero_int": "",
            "colonia": "Benito Juárez",
            "municipio": "Nezahualcóyotl",
            "estado": "Estado de México",
            "codigo_postal": "5700",
            "referencia": "Lona Rosa"
        }
    }



def imprimir_remitente(nota):

    mis_datos = obtener_mis_datos()

    data = etiqueta_remitente(
        nota["id"],
        mis_datos
    )

    return _enviar_etiqueta_segura(data, "etiqueta de remitente")

import time

def imprimir_ambas(nota):

    from clientes import obtener_cliente_por_id
    import time

    cliente_id = nota.get("cliente_id")

    if not cliente_id:
        messagebox.showerror("Error", "La nota no tiene cliente asignado")
        return

    cliente = obtener_cliente_por_id(cliente_id)

    if not cliente:
        messagebox.showerror("Error", "No se encontró el cliente")
        return

    mis_datos = obtener_mis_datos()

    data_rem = etiqueta_remitente(nota["id"], mis_datos)
    data_dest = etiqueta_destinatario(
        cliente,
        nota["id"],
        envio=nota.get("envio")
    )

    # 🔥 unir ambos trabajos en un solo envío
    data_total = data_rem + data_dest

    return _enviar_etiqueta_segura(data_total, "ambas etiquetas")


def abrir_opciones_impresion(nota):
    estado = str((nota or {}).get("estado") or "").strip().upper()
    if estado in {"ANULADA", "CANCELADA", "ELIMINADA", "ARCHIVADA"}:
        messagebox.showwarning(
            "Impresion",
            "Una nota anulada o archivada no puede volver a imprimirse.",
            parent=root,
        )
        return

    win = ctk.CTkToplevel(root)
    win.title("Imprimir etiquetas")
    win.geometry("400x300")
    win.grab_set()

    ctk.CTkLabel(
        win,
        text=f"Nota {nota['id']}",
        font=("Segoe UI", 16, "bold")
    ).pack(pady=20)

    ctk.CTkButton(
        win,
        text="📦 Solo Destinatario",
        command=lambda: imprimir_destinatario(nota)
    ).pack(fill="x", padx=40, pady=5)

    ctk.CTkButton(
        win,
        text="🏷 Solo Remitente",
        command=lambda: imprimir_remitente(nota)
    ).pack(fill="x", padx=40, pady=5)

    ctk.CTkButton(
        win,
        text="🖨 Ambas etiquetas",
        fg_color="#16A34A",
        command=lambda: imprimir_ambas(nota)
    ).pack(fill="x", padx=40, pady=10)


def abrir_panel_asignacion():

    if not pedir_password():
        return

    modo_api = _modo_api()
    if modo_api:
        from hilorama_desktop.services.pedidos_api_service import (
            asignar_notas_empacador,
            desasignar_notas_empacador,
            listar_empacadores,
            listar_notas_asignacion_empacador,
        )
    else:
        from empacadores import listar_empacadores_activos

    def _fecha_para_orden(valor):
        import datetime

        if not valor:
            return datetime.datetime.min

        if isinstance(valor, datetime.datetime):
            return valor

        if isinstance(valor, datetime.date):
            return datetime.datetime.combine(valor, datetime.time.min)

        texto = str(valor).strip()
        if not texto:
            return datetime.datetime.min

        texto = texto.replace("T", " ")

        # Quita milisegundos o zona horaria si vienen en texto
        texto_limpio = texto.split(".")[0]
        if "+" in texto_limpio:
            texto_limpio = texto_limpio.split("+")[0].strip()
        if texto_limpio.endswith("Z"):
            texto_limpio = texto_limpio[:-1].strip()

        for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                largo = 19 if "%S" in formato else 16 if "%M" in formato else 10
                return datetime.datetime.strptime(texto_limpio[:largo], formato)
            except Exception:
                pass

        return datetime.datetime.min

    def _valor_nota(nota, clave):
        try:
            return nota[clave]
        except Exception:
            return None

    def _numero_nota_para_orden(nota_id):
        # Orden más confiable para este panel: COT-00361 debe ir arriba de COT-00360.
        # Algunas notas antiguas pueden tener una fecha modificada/actualizada y por eso se subían arriba.
        import re
        texto = str(nota_id or "")
        numeros = re.findall(r"\d+", texto)
        if not numeros:
            return 0
        try:
            return int(numeros[-1])
        except Exception:
            return 0

    def ordenar_notas_empacador(lista):
        # En asignación de empacador ordenamos por número de nota descendente:
        # COT-00361, COT-00360, COT-00359...
        # La fecha queda como respaldo por si algún día una nota no trae folio numérico.
        return sorted(
            list(lista),
            key=lambda n: (
                _numero_nota_para_orden(_valor_nota(n, "id")),
                _fecha_para_orden(_valor_nota(n, "fecha_asignacion")),
                _fecha_para_orden(_valor_nota(n, "fecha"))
            ),
            reverse=True
        )

    try:
        if modo_api:
            notas = listar_notas_asignacion_empacador()
        else:
            conn = _get_conn_local("panel asignacion")
            notas = conn.execute("""
            SELECT 
                n.id,
                n.cliente_nombre,
                n.pedido,
                n.fecha,
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

            WHERE n.estado IN ('PAGADA','EN_PROCESO','INCOMPLETA')

            GROUP BY n.id, e.nombre, c.telefono
            ORDER BY n.fecha_asignacion DESC NULLS LAST
        """).fetchall()
            conn.close()
    except Exception as exc:
        messagebox.showerror("Asignacion", f"No se pudo cargar asignacion:\n{exc}")
        return

    notas = ordenar_notas_empacador(notas)

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

        if not modo_api:
            conn = _get_conn_local("panel asignacion")

            for n in nuevas_notas:
                if n["requeridas"] > 0:

                    if n["empacadas"] >= n["requeridas"]:
                        conn.execute("""
                            UPDATE notas
                            SET estado='COMPLETA',
                                fecha_finalizacion=COALESCE(fecha_finalizacion, NOW())
                            WHERE id=%s AND estado!='COMPLETA'
                        """, (n["id"],))

                    elif n["empacadas"] > 0:
                        conn.execute("""
                            UPDATE notas
                            SET estado='INCOMPLETA',
                                fecha_finalizacion=NULL
                            WHERE id=%s AND estado!='INCOMPLETA'
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
                tag_estado = "INCOMPLETA"
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
                    "INCOMPLETA" if porcentaje > 0 else
                    n["estado"],

                    n["empacador_actual"] if n["empacador_actual"] else "Sin asignar"
                ),
                tags=(tag_estado,)
            )

    cargar_tabla(notas)
   
    def recargar_datos():
        if modo_api:
            nuevas_notas = listar_notas_asignacion_empacador()
        else:
            conn = _get_conn_local("panel asignacion")
           
            nuevas_notas = conn.execute("""
                SELECT 
                    n.id,
                    n.cliente_nombre,
                    n.pedido,
                    n.fecha,
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

                WHERE n.estado IN ('PAGADA','EN_PROCESO','INCOMPLETA')

                GROUP BY n.id, e.nombre, c.telefono
                ORDER BY n.fecha_asignacion DESC NULLS LAST


            """).fetchall()

            conn.close()

        nuevas_notas = ordenar_notas_empacador(nuevas_notas)

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
    try:
        empacadores = listar_empacadores(activos=True) if modo_api else listar_empacadores_activos()
    except Exception as exc:
        messagebox.showerror("Empacadores", f"No se pudieron cargar empacadores:\n{exc}")
        win.destroy()
        return
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

        nota_ids = []

        for item in seleccion:
            valores = tabla.item(item)["values"]
            nota_id = valores[0]
            estado = str(valores[4] or "").strip().upper()
            if estado not in {"PAGADA", "EN_PROCESO", "INCOMPLETA"}:
                messagebox.showwarning(
                    "Asignacion",
                    f"La nota {nota_id} no puede asignarse desde el estado {estado or 'SIN ESTADO'}.",
                    parent=win,
                )
                return
            nota_ids.append(nota_id)

        try:
            if modo_api:
                asignar_notas_empacador(nota_ids, emp["id"])
            else:
                conn = _get_conn_local("panel asignacion")
                try:
                    for nota_id in nota_ids:
                        nota = conn.execute(
                            "SELECT estado FROM notas WHERE id=%s",
                            (nota_id,),
                        ).fetchone()
                        estado = str((nota or {}).get("estado") or "").strip().upper()
                        if estado not in {"PAGADA", "EN_PROCESO", "INCOMPLETA"}:
                            raise ValueError(
                                f"La nota {nota_id} no puede asignarse desde el estado {estado or 'SIN ESTADO'}."
                            )
                    for nota_id in nota_ids:
                        conn.execute("""
                            UPDATE notas
                            SET empacador_id=%s,
                                fecha_asignacion=NOW(),
                                estado=CASE
                                    WHEN UPPER(COALESCE(estado, ''))='PAGADA' THEN 'EN_PROCESO'
                                    ELSE estado
                                END
                            WHERE id=%s
                        """, (emp["id"], nota_id))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        except Exception as exc:
            messagebox.showerror("Asignacion", f"No se pudo asignar empacador:\n{exc}")
            return

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

        nota_ids = []

        for item in seleccion:
            valores = tabla.item(item)["values"]
            nota_id = valores[0]
            nota_ids.append(nota_id)

        try:
            if modo_api:
                desasignar_notas_empacador(nota_ids)
            else:
                conn = _get_conn_local("panel asignacion")

                for nota_id in nota_ids:
                    conn.execute("""
                        UPDATE notas
                        SET empacador_id = NULL
                        WHERE id = %s
                    """,(nota_id,))

                conn.commit()
                conn.close()
        except Exception as exc:
            messagebox.showerror("Asignacion", f"No se pudo desasignar empacador:\n{exc}")
            return

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

  
def _abrir_panel_envios_local():
    if not pedir_password():
        return

    from hilorama_desktop.services.envios_presentacion import (
        buscar_envios,
        estado_operativo_envio,
        filtrar_envios,
        formatear_fecha_envio,
        guia_envio,
        normalizar_estado_envio,
        resumir_panel_envios,
        resumir_seleccion_envios,
        texto_envio,
    )

    win = ctk.CTkToplevel(root)
    win.title("Gestión de Envíos")
    win.configure(fg_color="#F4F7FB")
    ancho = max(1080, min(1440, win.winfo_screenwidth() - 40))
    alto = max(680, min(900, win.winfo_screenheight() - 80))
    win.geometry(f"{ancho}x{alto}")
    win.minsize(min(1080, ancho), min(680, alto))
    win.grab_set()

    estado_filtro = tk.StringVar(value="TODAS")
    filtro_tipo = tk.StringVar(value="nota")
    filtro_texto = tk.StringVar()
    resultado_var = tk.StringVar(value="0 envíos visibles")
    detalle_titulo = tk.StringVar(value="Selecciona un envío")
    detalle_contenido = tk.StringVar(
        value="Consulta el estado, la guía y la paquetería sin modificar el pedido."
    )
    resumen_vars = {
        "visibles": tk.StringVar(value="0"),
        "pendientes_guia": tk.StringVar(value="0"),
        "listas_enviar": tk.StringVar(value="0"),
        "enviadas": tk.StringVar(value="0"),
    }
    datos_cargados = []
    notas_por_iid = {}

    def normalizar_fila(fila):
        nota = dict(fila)
        nota["telefono"] = nota.get("telefono") or nota.get("telefono_cliente") or ""
        nota.setdefault("requiere_guia", True)
        return nota

    def cargar_datos():
        conn = _get_conn_local("panel envios")
        try:
            filas = conn.execute("""
                SELECT
                    n.*,
                    c.telefono AS telefono_cliente
                FROM notas n
                LEFT JOIN clientes c ON c.id = n.cliente_id
                WHERE n.estado IN ('PAGADA','EN_PROCESO','INCOMPLETA','COMPLETA','ENVIADO')
                ORDER BY n.fecha DESC
            """).fetchall()
            return [normalizar_fila(fila) for fila in filas]
        finally:
            conn.close()

    encabezado = ctk.CTkFrame(win, height=86, corner_radius=0, fg_color="#17375E")
    encabezado.pack(fill="x")
    encabezado.pack_propagate(False)
    titulo_wrap = ctk.CTkFrame(encabezado, fg_color="transparent")
    titulo_wrap.pack(side="left", fill="y", padx=22, pady=13)
    ctk.CTkLabel(
        titulo_wrap,
        text="Gestión de Envíos",
        font=("Segoe UI", 25, "bold"),
        text_color="#FFFFFF",
        anchor="w",
    ).pack(anchor="w")
    ctk.CTkLabel(
        titulo_wrap,
        text="Consulta el avance, asigna guías y confirma la entrega a paquetería.",
        font=("Segoe UI", 12),
        text_color="#D7E5F5",
        anchor="w",
    ).pack(anchor="w", pady=(2, 0))
    ctk.CTkLabel(
        encabezado,
        text="Ctrl o Shift para selección múltiple",
        font=("Segoe UI", 12),
        text_color="#D7E5F5",
    ).pack(side="right", padx=22)

    resumen_frame = ctk.CTkFrame(win, fg_color="transparent")
    resumen_frame.configure(height=74)
    resumen_frame.grid_propagate(False)
    resumen_frame.grid_rowconfigure(0, weight=1)
    resumen_frame.pack(fill="x", padx=18, pady=(12, 8))
    tarjetas = (
        ("visibles", "En vista", "#2563EB"),
        ("pendientes_guia", "Pendientes de guía", "#D97706"),
        ("listas_enviar", "Listos para enviar", "#0F766E"),
        ("enviadas", "Enviados", "#16A34A"),
    )
    for indice, (clave, etiqueta, color) in enumerate(tarjetas):
        resumen_frame.grid_columnconfigure(indice, weight=1, uniform="envios-resumen")
        tarjeta = ctk.CTkFrame(
            resumen_frame,
            height=70,
            corner_radius=6,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#D8E1EC",
        )
        tarjeta.grid(row=0, column=indice, padx=4, sticky="nsew")
        tarjeta.grid_propagate(False)
        ctk.CTkFrame(tarjeta, width=5, corner_radius=0, fg_color=color).pack(
            side="left", fill="y"
        )
        contenido = ctk.CTkFrame(tarjeta, fg_color="transparent")
        contenido.pack(side="left", fill="both", expand=True, padx=12, pady=8)
        ctk.CTkLabel(
            contenido,
            text=etiqueta,
            font=("Segoe UI", 11),
            text_color="#526173",
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            contenido,
            textvariable=resumen_vars[clave],
            font=("Segoe UI", 20, "bold"),
            text_color="#102A43",
            anchor="w",
        ).pack(anchor="w", pady=(1, 0))

    frame_filtro = ctk.CTkFrame(
        win,
        corner_radius=6,
        fg_color="#FFFFFF",
        border_width=1,
        border_color="#D8E1EC",
    )
    frame_filtro.pack(fill="x", padx=22, pady=(0, 8))
    ctk.CTkLabel(
        frame_filtro,
        text="Buscar por",
        font=("Segoe UI", 11, "bold"),
        text_color="#334155",
    ).pack(side="left", padx=(12, 6), pady=9)
    combo_filtro = ctk.CTkComboBox(
        frame_filtro,
        values=["nota", "cliente", "telefono", "pedido"],
        variable=filtro_tipo,
        width=125,
        state="readonly",
    )
    combo_filtro.pack(side="left", padx=(0, 8), pady=9)
    entry_buscar = ctk.CTkEntry(
        frame_filtro,
        textvariable=filtro_texto,
        placeholder_text="Buscar folio, clienta, teléfono o pedido",
        height=34,
        border_color="#B9C8DA",
    )
    entry_buscar.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=9)
    ctk.CTkLabel(
        frame_filtro,
        text="Estado",
        font=("Segoe UI", 11, "bold"),
        text_color="#334155",
    ).pack(side="left", padx=(0, 6), pady=9)
    combo_estado = ctk.CTkComboBox(
        frame_filtro,
        values=[
            "TODAS",
            "PENDIENTES DE GUÍA",
            "LISTAS PARA ENVIAR",
            "ENVIADAS",
            "PAGADAS",
            "EN PROCESO",
            "INCOMPLETAS",
        ],
        variable=estado_filtro,
        width=205,
        state="readonly",
    )
    combo_estado.pack(side="left", padx=(0, 10), pady=9)
    ctk.CTkLabel(
        frame_filtro,
        textvariable=resultado_var,
        font=("Segoe UI", 11, "bold"),
        text_color="#2563EB",
        width=112,
    ).pack(side="right", padx=(0, 12), pady=9)

    tabla_frame = ctk.CTkFrame(
        win,
        corner_radius=6,
        fg_color="#FFFFFF",
        border_width=1,
        border_color="#D8E1EC",
    )
    tabla_frame.pack(fill="both", expand=True, padx=22, pady=(0, 8))
    tabla_frame.grid_rowconfigure(0, weight=1)
    tabla_frame.grid_columnconfigure(0, weight=1)

    estilo = ttk.Style(win)
    estilo.configure(
        "EnviosLocal.Treeview",
        rowheight=33,
        background="#FFFFFF",
        fieldbackground="#FFFFFF",
        foreground="#132238",
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    estilo.configure(
        "EnviosLocal.Treeview.Heading",
        font=("Segoe UI", 10, "bold"),
        foreground="#243B53",
        padding=(6, 8),
    )
    estilo.map(
        "EnviosLocal.Treeview",
        background=[("selected", "#1D4ED8")],
        foreground=[("selected", "#FFFFFF")],
    )

    columnas = (
        "ID",
        "Cliente",
        "Pedido",
        "Telefono",
        "Paqueteria",
        "Guia",
        "Estado",
        "Situacion",
        "FechaEnvio",
    )
    encabezados = {
        "ID": "Folio",
        "Cliente": "Cliente",
        "Pedido": "Pedido",
        "Telefono": "Teléfono",
        "Paqueteria": "Paquetería",
        "Guia": "Guía",
        "Estado": "Estado actual",
        "Situacion": "Situación de envío",
        "FechaEnvio": "Fecha de envío",
    }
    anchos = {
        "ID": 105,
        "Cliente": 205,
        "Pedido": 80,
        "Telefono": 115,
        "Paqueteria": 125,
        "Guia": 175,
        "Estado": 110,
        "Situacion": 155,
        "FechaEnvio": 140,
    }
    tabla = ttk.Treeview(
        tabla_frame,
        columns=columnas,
        show="headings",
        selectmode="extended",
        style="EnviosLocal.Treeview",
    )
    for columna in columnas:
        tabla.heading(columna, text=encabezados[columna])
        tabla.column(
            columna,
            anchor="w" if columna in {"Cliente", "Guia", "Situacion"} else "center",
            width=anchos[columna],
            minwidth=75,
            stretch=columna in {"Cliente", "Guia", "Situacion"},
        )
    scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tabla.yview)
    scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=tabla.xview)
    tabla.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
    tabla.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")

    tabla.tag_configure("PENDIENTE", background="#FFF7E6", foreground="#854D0E")
    tabla.tag_configure("LISTA", background="#EAF2FF", foreground="#1E3A8A")
    tabla.tag_configure("ENVIADO", background="#E8F7ED", foreground="#166534")
    tabla.tag_configure("OTRO", background="#F8FAFC", foreground="#475569")

    detalle_frame = ctk.CTkFrame(
        win,
        height=78,
        corner_radius=6,
        fg_color="#FFFFFF",
        border_width=1,
        border_color="#D8E1EC",
    )
    detalle_frame.pack(fill="x", padx=22, pady=(0, 8))
    detalle_frame.pack_propagate(False)
    ctk.CTkLabel(
        detalle_frame,
        textvariable=detalle_titulo,
        font=("Segoe UI", 13, "bold"),
        text_color="#102A43",
        anchor="w",
    ).pack(fill="x", padx=12, pady=(8, 1))
    ctk.CTkLabel(
        detalle_frame,
        textvariable=detalle_contenido,
        font=("Segoe UI", 11),
        text_color="#526173",
        anchor="w",
        justify="left",
        wraplength=max(800, ancho - 80),
    ).pack(fill="x", padx=12, pady=(0, 8))

    acciones = ctk.CTkFrame(win, fg_color="transparent")
    acciones.pack(fill="x", padx=22, pady=(0, 12))
    ctk.CTkLabel(
        acciones,
        text="Selecciona un registro para habilitar sus acciones.",
        font=("Segoe UI", 11),
        text_color="#64748B",
    ).pack(side="left")

    def filtrar_por_estado(notas):
        vista = estado_filtro.get().strip().upper()
        if vista == "TODAS":
            return list(notas)
        if vista in {"PENDIENTES DE GUÍA", "LISTAS PARA ENVIAR", "ENVIADAS"}:
            return filtrar_envios(notas, vista)
        estado = {
            "PAGADAS": "PAGADA",
            "EN PROCESO": "EN_PROCESO",
            "INCOMPLETAS": "INCOMPLETA",
        }.get(vista)
        return [
            nota for nota in notas
            if normalizar_estado_envio(nota.get("estado")) == estado
        ]

    def obtener_seleccion():
        return [
            notas_por_iid[iid]
            for iid in tabla.selection()
            if iid in notas_por_iid
        ]

    def cargar_tabla(data):
        tabla.delete(*tabla.get_children())
        notas_por_iid.clear()
        for indice, nota in enumerate(data):
            situacion = estado_operativo_envio(nota)
            if situacion == "ENVIADO":
                tag = "ENVIADO"
            elif situacion == "PENDIENTE DE GUÍA":
                tag = "PENDIENTE"
            elif situacion == "LISTO PARA ENVIAR":
                tag = "LISTA"
            else:
                tag = "OTRO"
            iid = f"envio-local-{indice}"
            notas_por_iid[iid] = nota
            tabla.insert(
                "",
                "end",
                iid=iid,
                values=(
                    texto_envio(nota.get("id") or nota.get("nota_id")),
                    texto_envio(nota.get("cliente_nombre") or nota.get("cliente")),
                    texto_envio(nota.get("pedido")),
                    texto_envio(nota.get("telefono")),
                    texto_envio(nota.get("paqueteria")),
                    guia_envio(nota) or "Sin guía",
                    normalizar_estado_envio(nota.get("estado")) or "SIN ESTADO",
                    situacion,
                    formatear_fecha_envio(nota.get("fecha_envio")),
                ),
                tags=(tag,),
            )
        cantidad = len(data)
        resultado_var.set(f"{cantidad} envío" if cantidad == 1 else f"{cantidad} envíos")

    def imprimir_seleccion():
        seleccion = obtener_seleccion()
        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona una nota.", parent=win)
            return
        if len(seleccion) != 1:
            messagebox.showinfo(
                "Imprimir etiquetas",
                "Selecciona una sola nota para imprimir.",
                parent=win,
            )
            return
        nota_id = seleccion[0].get("id") or seleccion[0].get("nota_id")
        from notas import obtener_cotizacion
        nota = obtener_cotizacion(nota_id)
        abrir_opciones_impresion(nota)

    def aplicar_filtro(*_args):
        resultado = filtrar_por_estado(datos_cargados)
        resultado = buscar_envios(resultado, filtro_texto.get(), filtro_tipo.get())
        cargar_tabla(resultado)
        actualizar_detalle_seleccion()

    def recargar_datos():
        try:
            nuevas = cargar_datos()
        except Exception as exc:
            messagebox.showerror(
                "Gestión de Envíos",
                f"No se pudieron cargar los envíos:\n{exc}",
                parent=win,
            )
            return False
        datos_cargados.clear()
        datos_cargados.extend(nuevas)
        resumen = resumir_panel_envios(datos_cargados)
        for clave, variable in resumen_vars.items():
            variable.set(str(resumen[clave]))
        aplicar_filtro()
        return True

    def actualizar_detalle_seleccion(_event=None):
        seleccion = obtener_seleccion()
        if not seleccion:
            detalle_titulo.set("Selecciona un envío")
            detalle_contenido.set(
                "Consulta el estado, la guía y la paquetería sin modificar el pedido."
            )
        elif len(seleccion) > 1:
            resumen = resumir_seleccion_envios(seleccion)
            detalle_titulo.set(f"{resumen['seleccionados']} envíos seleccionados")
            detalle_contenido.set(
                f"Con guía: {resumen['con_guia']}   |   "
                f"Sin guía: {resumen['sin_guia']}   |   "
                f"Listos: {resumen['listos']}   |   "
                f"Ya enviados: {resumen['ya_enviados']}"
            )
        else:
            nota = seleccion[0]
            estado = normalizar_estado_envio(nota.get("estado")) or "SIN ESTADO"
            situacion = estado_operativo_envio(nota)
            detalle_titulo.set(
                f"Envío {texto_envio(nota.get('id') or nota.get('nota_id'))} · {situacion}"
            )
            detalle_contenido.set(
                f"Cliente: {texto_envio(nota.get('cliente_nombre') or nota.get('cliente'))}   |   "
                f"Estado actual: {estado}   |   "
                f"Paquetería: {texto_envio(nota.get('paqueteria'))}   |   "
                f"Guía: {guia_envio(nota) or 'Sin guía'}   |   "
                f"Fecha de envío: {formatear_fecha_envio(nota.get('fecha_envio'))}"
            )
        actualizar_estado_botones()

    def actualizar_estado_botones():
        seleccion = obtener_seleccion()
        unica = len(seleccion) == 1
        estado = normalizar_estado_envio(seleccion[0].get("estado")) if unica else ""
        btn_asignar.configure(state="normal" if unica and estado == "COMPLETA" else "disabled")
        btn_enviar.configure(
            state=(
                "normal"
                if unica and estado_operativo_envio(seleccion[0]) == "LISTO PARA ENVIAR"
                else "disabled"
            )
        )
        btn_imprimir.configure(state="normal" if unica else "disabled")

    def asignar_guia():
        seleccion = obtener_seleccion()
        if len(seleccion) != 1:
            messagebox.showinfo("Selecciona", "Selecciona una sola nota.", parent=win)
            return
        nota_actual = seleccion[0]
        nota_id = nota_actual.get("id") or nota_actual.get("nota_id")
        guia = simpledialog.askstring(
            "Asignar guía",
            "Número de guía:",
            parent=win,
        )
        if not guia:
            return
        paqueteria = simpledialog.askstring(
            "Paquetería",
            "Paquetería (opcional):",
            initialvalue=str(nota_actual.get("paqueteria") or ""),
            parent=win,
        )
        try:
            conn = _get_conn_local("panel envios")
            nota = conn.execute(
                "SELECT estado FROM notas WHERE id=%s",
                (nota_id,),
            ).fetchone()
            estado = str((nota or {}).get("estado") or "").strip().upper()
            if estado != "COMPLETA":
                conn.close()
                raise ValueError("Solo una nota COMPLETA puede recibir una guía.")
            if paqueteria:
                conn.execute("""
                    UPDATE notas
                    SET guia=%s,
                        paqueteria=%s
                    WHERE id=%s
                """, (guia, paqueteria, nota_id))
            else:
                conn.execute("UPDATE notas SET guia=%s WHERE id=%s", (guia, nota_id))
            conn.commit()
            conn.close()
        except Exception as exc:
            messagebox.showerror(
                "Gestión de Envíos",
                f"No se pudo guardar la guía:\n{exc}",
                parent=win,
            )
            return
        recargar_datos()
        messagebox.showinfo("Guía guardada", "La guía se guardó correctamente.", parent=win)

    def marcar_como_enviado():
        seleccion = obtener_seleccion()
        if len(seleccion) != 1:
            messagebox.showinfo("Selecciona", "Selecciona una sola nota.", parent=win)
            return
        nota_id = seleccion[0].get("id") or seleccion[0].get("nota_id")
        if not messagebox.askyesno(
            "Marcar como enviado",
            "Confirma que el paquete ya fue entregado a la paquetería.",
            parent=win,
        ):
            return
        try:
            conn = _get_conn_local("panel envios")
            nota = conn.execute("SELECT * FROM notas WHERE id=%s", (nota_id,)).fetchone()
            if not nota:
                conn.close()
                raise ValueError("Nota no encontrada.")
            estado = str(nota.get("estado") or "").strip().upper()
            if estado != "COMPLETA":
                conn.close()
                raise ValueError("Solo una nota COMPLETA puede marcarse como enviada.")
            if not str(nota.get("guia") or "").strip():
                conn.close()
                raise ValueError("Guarda la guía antes de marcar el envío.")
            campos = ["estado='ENVIADO'"]
            if "estado_envio" in nota:
                campos.append("estado_envio='ENVIADO'")
            fecha_guardada = "fecha_envio" in nota
            if fecha_guardada:
                campos.append("fecha_envio=COALESCE(fecha_envio, NOW())")
            conn.execute(
                f"UPDATE notas SET {', '.join(campos)} WHERE id=%s",
                (nota_id,),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            messagebox.showerror(
                "Gestión de Envíos",
                f"No se pudo marcar el envío:\n{exc}",
                parent=win,
            )
            return
        recargar_datos()
        aviso_fecha = "" if fecha_guardada else "\n\nLa base actual no tiene fecha_envio; se guardó solo el estado."
        messagebox.showinfo(
            "Envío actualizado",
            f"La nota quedó marcada como ENVIADO.{aviso_fecha}",
            parent=win,
        )

    btn_cerrar = ctk.CTkButton(
        acciones,
        text="Cerrar",
        width=88,
        height=40,
        corner_radius=6,
        fg_color="#E8EEF5",
        hover_color="#D8E1EC",
        text_color="#243B53",
        command=win.destroy,
    )
    btn_cerrar.pack(side="right", padx=(6, 0))
    btn_actualizar = ctk.CTkButton(
        acciones,
        text="Actualizar",
        width=108,
        height=40,
        corner_radius=6,
        fg_color="#475569",
        hover_color="#334155",
        command=recargar_datos,
    )
    btn_actualizar.pack(side="right", padx=6)
    btn_imprimir = ctk.CTkButton(
        acciones,
        text="Imprimir etiqueta",
        width=136,
        height=40,
        corner_radius=6,
        fg_color="#334155",
        hover_color="#1E293B",
        command=imprimir_seleccion,
    )
    btn_imprimir.pack(side="right", padx=6)
    btn_enviar = ctk.CTkButton(
        acciones,
        text="Marcar como enviado",
        width=168,
        height=40,
        corner_radius=6,
        fg_color="#2563EB",
        hover_color="#1D4ED8",
        command=marcar_como_enviado,
    )
    btn_enviar.pack(side="right", padx=6)
    btn_asignar = ctk.CTkButton(
        acciones,
        text="Asignar guía",
        width=132,
        height=40,
        corner_radius=6,
        fg_color="#0F766E",
        hover_color="#115E59",
        command=asignar_guia,
    )
    btn_asignar.pack(side="right", padx=6)

    tabla.bind("<<TreeviewSelect>>", actualizar_detalle_seleccion)
    filtro_texto.trace_add("write", aplicar_filtro)
    combo_filtro.configure(command=lambda _valor: aplicar_filtro())
    combo_estado.configure(command=lambda _valor: aplicar_filtro())
    actualizar_detalle_seleccion()
    if not recargar_datos():
        win.destroy()


# =====================================================
# 🔵 FILTRAR SOLO CLIENTES COMPLETOS
# =====================================================



def _abrir_panel_envios_api():
    if not pedir_password():
        return

    from hilorama_desktop.services.envios_api_service import (
        actualizar_envio_nota,
        listar_envios,
        marcar_envios_lote,
    )
    from hilorama_desktop.services.envios_presentacion import (
        FILTROS_ENVIO,
        buscar_envios,
        clasificar_seleccion_envios,
        estado_operativo_envio,
        filtro_api_envios,
        formatear_fecha_envio,
        guia_envio,
        normalizar_estado_envio,
        resumir_panel_envios,
        resumir_seleccion_envios,
        texto_cantidad,
        texto_envio,
    )

    win = ctk.CTkToplevel(root)
    win.title("Gestión de Envíos")
    win.configure(fg_color="#F4F7FB")
    ancho = max(1080, min(1440, win.winfo_screenwidth() - 40))
    alto = max(680, min(900, win.winfo_screenheight() - 80))
    win.geometry(f"{ancho}x{alto}")
    win.minsize(min(1080, ancho), min(680, alto))
    win.grab_set()

    estado_filtro = tk.StringVar(value="TODAS")
    filtro_tipo = tk.StringVar(value="nota")
    filtro_texto = tk.StringVar()
    resultado_var = tk.StringVar(value="0 envíos visibles")
    detalle_titulo = tk.StringVar(value="Selecciona un pedido")
    resumen_vars = {
        "visibles": tk.StringVar(value="0"),
        "pendientes_guia": tk.StringVar(value="0"),
        "listas_enviar": tk.StringVar(value="0"),
        "enviadas": tk.StringVar(value="0"),
    }
    datos_cargados = []
    notas_por_iid = {}
    procesando = {"activo": False}

    encabezado = ctk.CTkFrame(win, height=86, corner_radius=0, fg_color="#17375E")
    encabezado.pack(fill="x")
    encabezado.pack_propagate(False)
    titulo_wrap = ctk.CTkFrame(encabezado, fg_color="transparent")
    titulo_wrap.pack(side="left", fill="y", padx=22, pady=13)
    ctk.CTkLabel(
        titulo_wrap,
        text="Gestión de Envíos",
        font=("Segoe UI", 25, "bold"),
        text_color="#FFFFFF",
        anchor="w",
    ).pack(anchor="w")
    ctk.CTkLabel(
        titulo_wrap,
        text="Consulta el avance, asigna guías y confirma la entrega a paquetería.",
        font=("Segoe UI", 12),
        text_color="#D7E5F5",
        anchor="w",
    ).pack(anchor="w", pady=(2, 0))
    ctk.CTkLabel(
        encabezado,
        text="Ctrl o Shift para selección múltiple",
        font=("Segoe UI", 12),
        text_color="#D7E5F5",
    ).pack(side="right", padx=22)

    resumen_frame = ctk.CTkFrame(win, fg_color="transparent")
    resumen_frame.configure(height=74)
    resumen_frame.grid_propagate(False)
    resumen_frame.grid_rowconfigure(0, weight=1)
    resumen_frame.pack(fill="x", padx=18, pady=(12, 8))
    tarjetas = (
        ("visibles", "En vista", "#2563EB"),
        ("pendientes_guia", "Pendientes de guía", "#D97706"),
        ("listas_enviar", "Listos para enviar", "#0F766E"),
        ("enviadas", "Enviados", "#16A34A"),
    )
    for indice, (clave, etiqueta, color) in enumerate(tarjetas):
        resumen_frame.grid_columnconfigure(indice, weight=1, uniform="envios-api-resumen")
        tarjeta = ctk.CTkFrame(
            resumen_frame,
            height=70,
            corner_radius=6,
            fg_color="#FFFFFF",
            border_width=1,
            border_color="#D8E1EC",
        )
        tarjeta.grid(row=0, column=indice, padx=4, sticky="nsew")
        tarjeta.grid_propagate(False)
        ctk.CTkFrame(tarjeta, width=5, corner_radius=0, fg_color=color).pack(
            side="left", fill="y"
        )
        contenido = ctk.CTkFrame(tarjeta, fg_color="transparent")
        contenido.pack(side="left", fill="both", expand=True, padx=12, pady=8)
        ctk.CTkLabel(
            contenido,
            text=etiqueta,
            font=("Segoe UI", 11),
            text_color="#526173",
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            contenido,
            textvariable=resumen_vars[clave],
            font=("Segoe UI", 20, "bold"),
            text_color="#102A43",
            anchor="w",
        ).pack(anchor="w", pady=(1, 0))

    filtros = ctk.CTkFrame(
        win,
        corner_radius=6,
        fg_color="#FFFFFF",
        border_width=1,
        border_color="#D8E1EC",
    )
    filtros.pack(fill="x", padx=22, pady=(0, 8))
    ctk.CTkLabel(
        filtros,
        text="Buscar por",
        font=("Segoe UI", 11, "bold"),
        text_color="#334155",
    ).pack(
        side="left", padx=(12, 6), pady=9
    )
    combo_filtro = ctk.CTkComboBox(
        filtros,
        values=["nota", "cliente", "telefono", "pedido"],
        variable=filtro_tipo,
        width=130,
        state="readonly",
    )
    combo_filtro.pack(side="left", padx=(0, 8), pady=9)
    entry_buscar = ctk.CTkEntry(
        filtros,
        textvariable=filtro_texto,
        placeholder_text="Buscar pedido, clienta o teléfono",
        width=330,
        height=34,
        border_color="#B9C8DA",
    )
    entry_buscar.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=9)
    ctk.CTkLabel(
        filtros,
        text="Estado",
        font=("Segoe UI", 11, "bold"),
        text_color="#334155",
    ).pack(
        side="left", padx=(0, 6), pady=9
    )
    combo_estado = ctk.CTkComboBox(
        filtros,
        values=list(FILTROS_ENVIO),
        variable=estado_filtro,
        width=205,
        state="readonly",
    )
    combo_estado.pack(side="left", padx=(0, 10), pady=9)
    ctk.CTkLabel(
        filtros,
        textvariable=resultado_var,
        font=("Segoe UI", 11, "bold"),
        text_color="#2563EB",
        width=112,
    ).pack(side="right", padx=(0, 12), pady=9)

    tabla_frame = ctk.CTkFrame(
        win,
        corner_radius=6,
        fg_color="#FFFFFF",
        border_width=1,
        border_color="#D8E1EC",
    )
    tabla_frame.pack(fill="both", expand=True, padx=22, pady=(0, 8))
    tabla_frame.grid_rowconfigure(0, weight=1)
    tabla_frame.grid_columnconfigure(0, weight=1)

    estilo = ttk.Style(win)
    estilo.configure(
        "Envios.Treeview",
        rowheight=33,
        background="#FFFFFF",
        fieldbackground="#FFFFFF",
        foreground="#132238",
        borderwidth=0,
        font=("Segoe UI", 10),
    )
    estilo.configure(
        "Envios.Treeview.Heading",
        font=("Segoe UI", 10, "bold"),
        foreground="#243B53",
        padding=(6, 8),
    )
    estilo.map(
        "Envios.Treeview",
        background=[("selected", "#1D4ED8")],
        foreground=[("selected", "#FFFFFF")],
    )

    columnas = (
        "ID",
        "Cliente",
        "Pedido",
        "Telefono",
        "Paqueteria",
        "Guia",
        "Estado",
        "Situacion",
        "FechaEnvio",
    )
    encabezados = {
        "ID": "ID",
        "Cliente": "Cliente",
        "Pedido": "Pedido",
        "Telefono": "Teléfono",
        "Paqueteria": "Paquetería",
        "Guia": "Guía",
        "Estado": "Estado actual",
        "Situacion": "Situación de envío",
        "FechaEnvio": "Fecha de envío",
    }
    anchos = {
        "ID": 115,
        "Cliente": 210,
        "Pedido": 100,
        "Telefono": 125,
        "Paqueteria": 130,
        "Guia": 190,
        "Estado": 105,
        "Situacion": 155,
        "FechaEnvio": 145,
    }
    tabla = ttk.Treeview(
        tabla_frame,
        columns=columnas,
        show="headings",
        selectmode="extended",
        style="Envios.Treeview",
    )
    for columna in columnas:
        tabla.heading(columna, text=encabezados[columna])
        tabla.column(
            columna,
            anchor="w" if columna in {"Cliente", "Guia", "Situacion"} else "center",
            width=anchos[columna],
            minwidth=80,
            stretch=columna in {"Cliente", "Guia", "Situacion"},
        )
    scroll_y = ttk.Scrollbar(tabla_frame, orient="vertical", command=tabla.yview)
    scroll_x = ttk.Scrollbar(tabla_frame, orient="horizontal", command=tabla.xview)
    tabla.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
    tabla.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")

    tabla.tag_configure("SIN_GUIA", background="#FFF7E6", foreground="#854D0E")
    tabla.tag_configure("LISTA", background="#EAF2FF", foreground="#1E3A8A")
    tabla.tag_configure("ENVIADO", background="#E8F7ED", foreground="#166534")

    detalle_frame = ctk.CTkFrame(
        win,
        corner_radius=6,
        fg_color="#FFFFFF",
        border_width=1,
        border_color="#D8E1EC",
    )
    detalle_frame.pack(fill="x", padx=22, pady=(0, 8))
    ctk.CTkLabel(
        detalle_frame,
        textvariable=detalle_titulo,
        font=("Segoe UI", 14, "bold"),
        anchor="w",
    ).pack(fill="x", padx=12, pady=(8, 2))
    detalle_texto = ctk.CTkTextbox(
        detalle_frame,
        height=84,
        wrap="word",
        font=("Segoe UI", 11),
        fg_color="#FFFFFF",
        text_color="#111827",
        activate_scrollbars=True,
    )
    detalle_texto.pack(fill="x", padx=12, pady=(0, 8))
    detalle_texto.configure(state="disabled")

    acciones = ctk.CTkFrame(win, fg_color="transparent")
    acciones.pack(fill="x", padx=22, pady=(0, 12))
    for columna in range(5):
        acciones.grid_columnconfigure(columna, weight=1)

    def escribir_detalle(texto):
        detalle_texto.configure(state="normal")
        detalle_texto.delete("1.0", "end")
        detalle_texto.insert("1.0", texto)
        detalle_texto.configure(state="disabled")

    def cargar_datos(etiqueta_filtro):
        return listar_envios({
            "estado": filtro_api_envios(etiqueta_filtro),
            "limit": 500,
        })

    def obtener_seleccion():
        return [
            notas_por_iid[iid]
            for iid in tabla.selection()
            if iid in notas_por_iid
        ]

    def cargar_tabla(notas):
        tabla.delete(*tabla.get_children())
        notas_por_iid.clear()
        for indice, nota in enumerate(notas):
            estado = normalizar_estado_envio(nota.get("estado"))
            situacion = estado_operativo_envio(nota)
            tiene_guia = bool(guia_envio(nota))
            requiere_guia = bool(nota.get("requiere_guia", True))
            if estado == "ENVIADO":
                tag = "ENVIADO"
            elif requiere_guia and not tiene_guia:
                tag = "SIN_GUIA"
            else:
                tag = "LISTA"
            iid = f"envio-{indice}"
            notas_por_iid[iid] = nota
            tabla.insert(
                "",
                "end",
                iid=iid,
                values=(
                    texto_envio(nota.get("id") or nota.get("nota_id")),
                    texto_envio(nota.get("cliente_nombre") or nota.get("cliente")),
                    texto_envio(nota.get("pedido")),
                    texto_envio(nota.get("telefono")),
                    texto_envio(nota.get("paqueteria")),
                    guia_envio(nota) or "Sin guía",
                    estado or "SIN ESTADO",
                    situacion,
                    formatear_fecha_envio(nota.get("fecha_envio")),
                ),
                tags=(tag,),
            )
        resumen = resumir_panel_envios(notas)
        for clave, variable in resumen_vars.items():
            variable.set(str(resumen[clave]))
        cantidad = len(notas)
        resultado_var.set(f"{cantidad} envío" if cantidad == 1 else f"{cantidad} envíos")

    def aplicar_filtro(*_args):
        visibles = buscar_envios(datos_cargados, filtro_texto.get(), filtro_tipo.get())
        cargar_tabla(visibles)
        actualizar_detalle_seleccion()

    def recargar_datos():
        try:
            nuevas = cargar_datos(estado_filtro.get())
        except Exception as exc:
            messagebox.showerror(
                "Gestión de Envíos",
                f"No se pudieron cargar los envíos:\n{exc}",
                parent=win,
            )
            return False
        datos_cargados.clear()
        datos_cargados.extend(nuevas)
        aplicar_filtro()
        return True

    def actualizar_detalle_seleccion(_event=None):
        seleccion = obtener_seleccion()
        if not seleccion:
            detalle_titulo.set("Selecciona un pedido")
            escribir_detalle("La selección no modifica estados ni datos del envío.")
        elif len(seleccion) > 1:
            resumen = resumir_seleccion_envios(seleccion)
            detalle_titulo.set(f"{resumen['seleccionados']} pedidos seleccionados")
            escribir_detalle(
                f"Con guía: {resumen['con_guia']}    "
                f"Sin guía: {resumen['sin_guia']}    "
                f"Ya enviados: {resumen['ya_enviados']}    "
                f"Listos para enviar: {resumen['listos']}"
            )
        else:
            nota = seleccion[0]
            estado = normalizar_estado_envio(nota.get("estado")) or "SIN ESTADO"
            situacion = estado_operativo_envio(nota)
            detalle_titulo.set(
                f"Envío {texto_envio(nota.get('folio') or nota.get('id') or nota.get('nota_id'))} · "
                f"{situacion}"
            )
            escribir_detalle(
                "\n".join((
                    f"Cliente: {texto_envio(nota.get('cliente_nombre') or nota.get('cliente'))}",
                    f"Estado actual: {estado}    Situación: {situacion}    "
                    f"Paquetería: {texto_envio(nota.get('paqueteria'))}    "
                    f"Guía: {guia_envio(nota) or 'Sin guía'}",
                    f"Fecha de guía: {formatear_fecha_envio(nota.get('fecha_guia'))}    "
                    f"Fecha de envío: {formatear_fecha_envio(nota.get('fecha_envio'))}",
                    f"Tipo de entrega: {texto_envio(nota.get('tipo_entrega'))}    "
                    f"Empacador: {texto_envio(nota.get('empacador'))}    "
                    f"Artículos: {texto_cantidad(nota.get('articulos'))}    "
                    f"Piezas: {texto_cantidad(nota.get('piezas'))}",
                    f"Observaciones: {texto_envio(nota.get('observaciones'))}",
                ))
            )
        actualizar_estado_botones()

    def actualizar_estado_botones():
        seleccion = obtener_seleccion()
        clasificacion = clasificar_seleccion_envios(seleccion)
        bloqueado = procesando["activo"]
        btn_asignar.configure(
            state="normal" if seleccion and not bloqueado else "disabled"
        )
        btn_enviar.configure(
            state="normal" if clasificacion["validos"] and not bloqueado else "disabled"
        )
        btn_imprimir.configure(state="normal" if seleccion and not bloqueado else "disabled")
        btn_actualizar.configure(state="disabled" if bloqueado else "normal")

    def asignar_guia():
        seleccion = obtener_seleccion()
        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona una nota.", parent=win)
            return
        if len(seleccion) != 1:
            messagebox.showinfo(
                "Asignar guía",
                "Selecciona una sola nota para asignar la guía.",
                parent=win,
            )
            return
        nota = seleccion[0]
        if normalizar_estado_envio(nota.get("estado")) != "COMPLETA":
            messagebox.showinfo(
                "Asignar guía",
                "Solo una nota COMPLETA puede recibir una guía.",
                parent=win,
            )
            return
        nota_id = nota.get("id") or nota.get("nota_id")
        guia = simpledialog.askstring("Asignar guía", "Número de guía:", parent=win)
        if not str(guia or "").strip():
            return
        paqueteria = simpledialog.askstring(
            "Paquetería",
            "Paquetería (opcional):",
            initialvalue=str(nota.get("paqueteria") or ""),
            parent=win,
        )
        datos = {"guia": str(guia).strip()}
        if str(paqueteria or "").strip():
            datos["paqueteria"] = str(paqueteria).strip()
        try:
            actualizar_envio_nota(nota_id, datos)
        except Exception as exc:
            messagebox.showerror(
                "Gestión de Envíos",
                f"No se pudo guardar la guía:\n{exc}",
                parent=win,
            )
            return
        recargar_datos()
        messagebox.showinfo("Guía guardada", "La guía se guardó correctamente.", parent=win)

    def imprimir_seleccion():
        seleccion = obtener_seleccion()
        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona una nota.", parent=win)
            return
        if len(seleccion) > 1:
            messagebox.showinfo(
                "Imprimir etiquetas",
                "El flujo actual de impresión trabaja con una nota a la vez.",
                parent=win,
            )
            return
        nota_id = seleccion[0].get("id") or seleccion[0].get("nota_id")
        nota = obtener_cotizacion(nota_id)
        abrir_opciones_impresion(nota)

    def finalizar_envio_lote(trabajo):
        procesando["activo"] = False
        if trabajo.get("error"):
            actualizar_estado_botones()
            messagebox.showerror(
                "Gestión de Envíos",
                f"No se pudieron procesar los envíos:\n{trabajo['error']}",
                parent=win,
            )
            return
        datos_cargados.clear()
        datos_cargados.extend(trabajo.get("envios") or [])
        aplicar_filtro()
        resultado = trabajo.get("resultado") or {}
        procesados = int(resultado.get("procesados") or 0)
        omitidos = int(resultado.get("omitidos") or 0)
        fallos = [item for item in resultado.get("resultados") or [] if not item.get("ok")]
        mensaje = f"{procesados} pedidos marcados como enviados."
        if omitidos:
            detalles = "\n".join(
                f"{item.get('nota_id')}: {item.get('error') or 'Omitido'}"
                for item in fallos[:8]
            )
            mensaje += f"\n\n{omitidos} pedidos fueron omitidos."
            if detalles:
                mensaje += f"\n\nDetalles:\n{detalles}"
            messagebox.showwarning("Resultado de envíos", mensaje, parent=win)
        else:
            messagebox.showinfo("Resultado de envíos", mensaje, parent=win)

    def marcar_como_enviado():
        seleccion = obtener_seleccion()
        if not seleccion:
            messagebox.showinfo("Selecciona", "Selecciona una o varias notas.", parent=win)
            return
        clasificacion = clasificar_seleccion_envios(seleccion)
        validos = clasificacion["validos"]
        if not validos:
            messagebox.showinfo(
                "Marcar como enviado",
                "No hay pedidos pendientes válidos en la selección.",
                parent=win,
            )
            return
        motivos = clasificacion["motivos"]
        lineas = [f"Se marcarán {len(validos)} pedidos como enviados."]
        if motivos.get("YA_ENVIADO"):
            lineas.append(f"{motivos['YA_ENVIADO']} ya estaban enviados.")
        if motivos.get("SIN_GUIA"):
            lineas.append(f"{motivos['SIN_GUIA']} no tienen guía y serán omitidos.")
        otros = sum(
            cantidad
            for motivo, cantidad in motivos.items()
            if motivo not in {"YA_ENVIADO", "SIN_GUIA"}
        )
        if otros:
            lineas.append(f"{otros} tienen un estado no permitido y serán omitidos.")
        lineas.append("\nSí: continuar con los válidos.  No: cancelar.")
        if not messagebox.askyesno("Confirmar envíos", "\n".join(lineas), parent=win):
            return

        ids = [nota.get("id") or nota.get("nota_id") for nota in seleccion]
        filtro_capturado = estado_filtro.get()
        trabajo = {"terminado": False}
        procesando["activo"] = True
        actualizar_estado_botones()

        def ejecutar_lote():
            try:
                trabajo["resultado"] = marcar_envios_lote(ids)
                trabajo["envios"] = cargar_datos(filtro_capturado)
            except Exception as exc:
                trabajo["error"] = str(exc)
            finally:
                trabajo["terminado"] = True

        def esperar_lote():
            if not win.winfo_exists():
                return
            if trabajo["terminado"]:
                finalizar_envio_lote(trabajo)
            else:
                win.after(80, esperar_lote)

        threading.Thread(target=ejecutar_lote, daemon=True).start()
        win.after(80, esperar_lote)

    btn_asignar = ctk.CTkButton(
        acciones,
        text="Asignar guía",
        height=42,
        corner_radius=6,
        fg_color="#0F766E",
        hover_color="#115E59",
        command=asignar_guia,
    )
    btn_asignar.grid(row=0, column=0, padx=(0, 6), sticky="ew")
    btn_enviar = ctk.CTkButton(
        acciones,
        text="Marcar como enviado",
        height=42,
        corner_radius=6,
        fg_color="#2563EB",
        hover_color="#1D4ED8",
        command=marcar_como_enviado,
    )
    btn_enviar.grid(row=0, column=1, padx=6, sticky="ew")
    btn_imprimir = ctk.CTkButton(
        acciones,
        text="Imprimir etiquetas",
        height=42,
        corner_radius=6,
        fg_color="#334155",
        hover_color="#1E293B",
        command=imprimir_seleccion,
    )
    btn_imprimir.grid(row=0, column=2, padx=6, sticky="ew")
    btn_actualizar = ctk.CTkButton(
        acciones,
        text="Actualizar",
        height=42,
        corner_radius=6,
        fg_color="#475569",
        hover_color="#334155",
        command=recargar_datos,
    )
    btn_actualizar.grid(row=0, column=3, padx=(6, 0), sticky="ew")
    ctk.CTkButton(
        acciones,
        text="Cerrar",
        height=42,
        corner_radius=6,
        fg_color="#E8EEF5",
        hover_color="#D8E1EC",
        text_color="#243B53",
        command=win.destroy,
    ).grid(row=0, column=4, padx=(6, 0), sticky="ew")

    tabla.bind("<<TreeviewSelect>>", actualizar_detalle_seleccion)
    filtro_texto.trace_add("write", aplicar_filtro)
    combo_filtro.configure(command=lambda _valor: aplicar_filtro())
    combo_estado.configure(command=lambda _valor: recargar_datos())
    actualizar_detalle_seleccion()
    if not recargar_datos():
        win.destroy()


def abrir_panel_envios():
    # Compatibilidad local: ('PAGADA','EN_PROCESO','INCOMPLETA','COMPLETA')
    if _modo_api():
        return _abrir_panel_envios_api()
    return _abrir_panel_envios_local()


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
        return listar_pedidos()

    try:
        pedidos_db = cargar_datos()
    except Exception as exc:
        messagebox.showerror("Pedidos", f"No se pudieron cargar los pedidos:\n{exc}")
        win.destroy()
        return

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
        global pedido_actual
        pedido_actual = numero_pedido
        lbl_pedido_valor.configure(text=f"Pedido #{pedido_actual}")


        win.destroy()

    ctk.CTkButton(
        win,
        text="Seleccionar pedido",
        height=40,
        fg_color="#1976D2",
        command=confirmar
    ).pack(pady=10)

def eliminar_pedido_opciones():

    global pedido_actual

    if not pedido_actual:
        messagebox.showwarning("Sin pedido", "No hay pedido activo")
        return

    if _modo_api():
        messagebox.showinfo(
            "Modo API",
            "Esta funcion de pedidos todavia no esta disponible en modo API."
        )
        return

    if not pedir_password():
        return

    win = ctk.CTkToplevel(root)
    win.title("Eliminar Pedido")
    win.geometry("420x280")
    win.grab_set()

    ctk.CTkLabel(
        win,
        text=f"Pedido #{pedido_actual}",
        font=("Segoe UI", 18, "bold")
    ).pack(pady=(20,10))

    ctk.CTkLabel(
        win,
        text="¿Qué deseas hacer?",
        font=("Segoe UI", 13)
    ).pack(pady=(0,20))

    def eliminar_total():
        global pedido_actual
        if not messagebox.askyesno(
            "Confirmar",
            "⚠️ Se eliminarán TODAS las notas del pedido.\n\n¿Continuar?"
        ):
            return

        conn = _get_conn_local("eliminar pedido")

        # borrar errores
        conn.execute("""
            DELETE FROM errores_scan
            WHERE nota_id IN (
                SELECT id FROM notas WHERE pedido=%s
            )
        """, (str(pedido_actual),))

        # borrar items
        conn.execute("""
            DELETE FROM items
            WHERE nota_id IN (
                SELECT id FROM notas WHERE pedido=%s
            )
        """, (str(pedido_actual),))

        # borrar notas
        conn.execute("""
            DELETE FROM notas WHERE pedido=%s
        """, (str(pedido_actual),))

        # borrar pedido historial
        conn.execute("""
            DELETE FROM pedidos WHERE numero=%s
        """, (str(pedido_actual),))

        conn.commit()
        conn.close()

        # limpiar pedido activo
        from pedido_estado import limpiar_pedido_activo
        limpiar_pedido_activo()


        pedido_actual = None
        lbl_pedido_valor.configure(text="📦 Configurar pedido")
        lbl_pedido_fecha.configure(text="")

        win.destroy()
        messagebox.showinfo("Eliminado", "Pedido eliminado correctamente")

    def mover_notas():
        nuevo = simpledialog.askinteger(
            "Mover notas",
            "Mover notas al pedido número:"
        )

        if not nuevo:
            return

        conn = _get_conn_local("mover notas de pedido")

        conn.execute("""
            UPDATE notas
            SET pedido=%s
            WHERE pedido=%s
        """, (nuevo, pedido_actual))

        conn.execute("""
            DELETE FROM pedidos WHERE numero=%s
        """, (pedido_actual,))

        conn.commit()
        conn.close()

        pedido_actual = nuevo
        lbl_pedido_valor.configure(text=f"Pedido #{nuevo}")

        win.destroy()
        messagebox.showinfo("Movido", "Notas movidas correctamente")

    ctk.CTkButton(
        win,
        text="🗑 Eliminar pedido con todas las notas",
        fg_color="#DC2626",
        hover_color="#B91C1C",
        height=45,
        command=eliminar_total
    ).pack(fill="x", padx=30, pady=8)

    ctk.CTkButton(
        win,
        text="🔁 Mover notas a otro pedido",
        fg_color="#2563EB",
        hover_color="#1D4ED8",
        height=45,
        command=mover_notas
    ).pack(fill="x", padx=30, pady=8)

    ctk.CTkButton(
        win,
        text="Cancelar",
        fg_color="#6B7280",
        hover_color="#4B5563",
        height=40,
        command=win.destroy
    ).pack(fill="x", padx=30, pady=(15,0))






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

    pedido_existente = cargar_pedido()
    editar_existente = False

    if pedido_existente:
        if not pedir_password():
            return

        crear_nuevo = messagebox.askyesnocancel(
            "Pedido activo",
            (
                f"Ya existe el pedido #{pedido_existente.get('numero')}.\n\n"
                "Si: crear un pedido nuevo.\n"
                "No: actualizar las fechas del pedido actual.\n"
                "Cancelar: no hacer cambios."
            ),
        )
        if crear_nuevo is None:
            return
        editar_existente = not crear_nuevo

    hoy = datetime.now()
    anio_actual = hoy.year

    def normalizar_fecha(valor, predeterminada):
        if valor is None:
            return predeterminada
        if hasattr(valor, "date") and not isinstance(valor, str):
            try:
                return valor.date()
            except Exception:
                pass
        if hasattr(valor, "year") and hasattr(valor, "month") and hasattr(valor, "day"):
            return valor
        texto = str(valor).strip()
        for formato in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(texto[:10], formato).date()
            except ValueError:
                pass
        return predeterminada

    fecha_inicial = hoy.date()
    fecha_final = hoy.date()
    if editar_existente:
        fecha_inicial = normalizar_fecha(
            pedido_existente.get("desde") or pedido_existente.get("fecha_inicio"),
            fecha_inicial,
        )
        fecha_final = normalizar_fecha(
            pedido_existente.get("hasta") or pedido_existente.get("fecha_fin"),
            fecha_final,
        )

    primer_anio = min(anio_actual, fecha_inicial.year, fecha_final.year)
    ultimo_anio = max(anio_actual + 3, fecha_inicial.year, fecha_final.year)
    valores_anios = [str(a) for a in range(primer_anio, ultimo_anio + 1)]

    win = ctk.CTkToplevel(root)
    win.title("Editar fechas del pedido" if editar_existente else "Configurar pedido")
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

    numero_existente = pedido_existente.get("numero") if editar_existente else ""
    pedido_var = tk.StringVar(value=str(numero_existente or ""))

    pedido_entry = ctk.CTkEntry(
        frame,
        textvariable=pedido_var,
        width=120
    )
    pedido_entry.pack(pady=6)
    if editar_existente:
        pedido_entry.configure(state="disabled")

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

        anios.configure(values=valores_anios)

        dias.configure(values=["1"])
        dias.set("1")
        meses.set("Enero")
        anios.set(str(anio_actual))

        def actualizar_dias(*args):
            mes = meses.get()
            anio = int(anios.get())
            try:
                dia_actual = int(dias.get())
            except (TypeError, ValueError):
                dia_actual = 1

            mes_num = [
                "Enero","Febrero","Marzo","Abril","Mayo","Junio",
                "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
            ].index(mes) + 1

            max_dia = calendar.monthrange(anio, mes_num)[1]

            dias.configure(values=[str(i) for i in range(1, max_dia+1)])
            dias.set(str(min(dia_actual, max_dia)))

        meses.configure(command=actualizar_dias)
        anios.configure(command=actualizar_dias)

        actualizar_dias()

        return dias, meses, anios, actualizar_dias


    d1, m1, a1, actualizar_dias_1 = crear_selector_fecha("Desde")
    d2, m2, a2, actualizar_dias_2 = crear_selector_fecha("Hasta")

    def establecer_fecha(dia, mes, anio, actualizar_dias, fecha):
        anio.set(str(fecha.year))
        mes.set([
            "Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
        ][fecha.month - 1])
        actualizar_dias()
        dia.set(str(fecha.day))

    establecer_fecha(d1, m1, a1, actualizar_dias_1, fecha_inicial)
    establecer_fecha(d2, m2, a2, actualizar_dias_2, fecha_final)

    # ================= GUARDAR =================
    def guardar():
        global pedido_actual, fecha_desde, fecha_hasta

        try:
            numero_pedido = int(pedido_var.get().strip())
        except (TypeError, ValueError):
            messagebox.showwarning("Pedido", "Escribe un numero de pedido valido.")
            return

        meses_lista = [
            "Enero","Febrero","Marzo","Abril","Mayo","Junio",
            "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
        ]

        mes1 = meses_lista.index(m1.get()) + 1
        mes2 = meses_lista.index(m2.get()) + 1

        try:
            desde_date = datetime(int(a1.get()), mes1, int(d1.get())).date()
            hasta_date = datetime(int(a2.get()), mes2, int(d2.get())).date()
        except (TypeError, ValueError):
            messagebox.showwarning("Pedido", "Selecciona fechas validas.")
            return

        if hasta_date < desde_date:
            messagebox.showwarning(
                "Rango de fechas",
                "La fecha Hasta no puede ser anterior a Desde.",
            )
            return

        nueva_fecha_desde = desde_date.strftime("%d/%m/%Y")
        nueva_fecha_hasta = hasta_date.strftime("%d/%m/%Y")


        try:
            if editar_existente:
                actualizar_pedido(numero_pedido, nueva_fecha_desde, nueva_fecha_hasta)
            else:
                crear_pedido(numero_pedido, nueva_fecha_desde, nueva_fecha_hasta)
                activar_pedido(numero_pedido)

        except ValueError as exc:
            mensaje = str(exc)
            if "duplicado" in mensaje.lower():
                messagebox.showerror(
                    "Duplicado",
                    "Ese numero de pedido ya existe. Usa otro numero.",
                )
            else:
                messagebox.showerror("Pedido", mensaje)
            return
        except Exception as exc:
            if editar_existente and getattr(exc, "status", None) == 404:
                messagebox.showerror(
                    "Actualizacion no disponible",
                    (
                        "El backend todavia no tiene publicada la actualizacion "
                        "de fechas de pedidos. No se guardo ningun cambio."
                    ),
                )
                return
            messagebox.showerror(
                "Pedido",
                f"No se pudieron guardar las fechas del pedido:\n{exc}"
            )
            return

        pedido_actual = numero_pedido
        fecha_desde = nueva_fecha_desde
        fecha_hasta = nueva_fecha_hasta

        lbl_pedido_valor.configure(
            text=f"Pedido #{pedido_actual}\n{fecha_desde} → {fecha_hasta}"
        )

        win.destroy()

    ctk.CTkButton(
        frame,
        text="Actualizar fechas" if editar_existente else "Crear pedido",
        height=40,
        command=guardar
    ).pack(pady=15)

def _construir_contexto_moderno():
    global frame_ctx, marca_var, hilo_var, combo_marca, combo_hilo
    global buscar_producto_var, entry_buscar, lista_sugerencias, btn_whatsapp

    # ================= CONTEXTO MODERNO =================
    frame_ctx = ctk.CTkFrame(
        card_contexto,
        corner_radius=15,
        fg_color="white"
    )
    frame_ctx.pack(fill="x", padx=8, pady=8)

    # layout horizontal flexible para modo embebido
    frame_ctx.grid_columnconfigure(0, weight=1, minsize=120)
    frame_ctx.grid_columnconfigure(1, weight=1, minsize=120)
    frame_ctx.grid_columnconfigure(2, weight=2, minsize=150)
    frame_ctx.grid_columnconfigure(3, weight=0, minsize=110)


    marca_var = tk.StringVar()
    hilo_var = tk.StringVar()

    # ----- Marca -----
    combo_marca = ctk.CTkComboBox(
        frame_ctx,
        variable=marca_var,
        width=135,
        height=36,
        command=actualizar_hilos,
        corner_radius=10,
        font=("Segoe UI", 12)
    )
    combo_marca.grid(row=0, column=0, padx=6, pady=8, sticky="ew")


    # ----- Hilo -----
    combo_hilo = ctk.CTkComboBox(
        frame_ctx,
        variable=hilo_var,
        width=135,
        height=36,
        corner_radius=10,
        font=("Segoe UI", 12),
        command=actualizar_productos_cache   # 👈 AQUÍ
    )

    combo_hilo.grid(row=0, column=1, padx=6, pady=8, sticky="ew")


    # ----- Buscador visual (solo diseño) -----
    buscar_producto_var = tk.StringVar(value="Código / Buscar producto")

    entry_buscar = ctk.CTkEntry(
        frame_ctx,
        textvariable=buscar_producto_var,
        height=36,
        corner_radius=10,
        font=("Segoe UI", 12),
        text_color="#888"  # gris tipo placeholder
    )
    entry_buscar.grid(row=0, column=2, padx=6, pady=8, sticky="ew")

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
    productos_sugeridos = []


    def actualizar_sugerencias(*args):

        texto = buscar_producto_var.get().lower().strip()

        if not texto:
            productos_sugeridos.clear()
            lista_sugerencias.place_forget()
            return

        productos = productos_cache


        encontrados = []

        for p in productos:
            if (texto in str(p["codigo"]).lower()
                or texto in p["marca"].lower()
                or texto in p["hilo"].lower()):
                encontrados.append(p)

        if not encontrados:
            productos_sugeridos.clear()
            lista_sugerencias.place_forget()
            return

        lista_sugerencias.delete(0, "end")
        productos_sugeridos[:] = encontrados[:10]

        for p in productos_sugeridos:
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

        indice = int(lista_sugerencias.curselection()[0])
        if indice >= len(productos_sugeridos):
            return

        producto = productos_sugeridos[indice]

        agregado = agregar_al_carrito({
            "producto_id": producto.get("id"),
            "codigo": producto.get("codigo"),
            "marca": producto.get("marca"),
            "hilo": producto.get("hilo"),
            "color": producto.get("color"),
            "cantidad": 1
        })

        if agregado:
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
    btn_whatsapp.grid(row=0, column=3, padx=6, pady=8, sticky="ew")

def procesar_imagen(ruta_imagen):
    try:
        texto = leer_pedido_desde_imagen(ruta_imagen)

        texto = texto.replace("O", "0").replace("l", "1").replace("I", "1")

        productos = productos_cache


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

def soporta_tkdnd(widget):
    try:
        widget.tk.call("package", "require", "tkdnd")
        return True
    except Exception:
        return False


def _registrar_drop_target(widget, callback):
    if widget is None or not soporta_tkdnd(widget):
        return False
    try:
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", callback)
        return True
    except Exception:
        return False


def _configurar_drag_and_drop():
    _registrar_drop_target(root, drop_imagen)


def cargar_contexto():
    marcas = obtener_marcas()

    combo_marca.configure(values=marcas)

    if marcas:
        marca_var.set(marcas[0])
        actualizar_hilos()


def pedir_nombre_cliente(parent):
    resultado = {"nombre": None}

    modal = ctk.CTkToplevel(parent)
    modal.title("Nuevo Cliente")
    modal.geometry("400x220")
    modal.grab_set()
    modal.resizable(False, False)

    modal.configure(fg_color="#F3F4F6")

    frame = ctk.CTkFrame(modal, corner_radius=15)
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(
        frame,
        text="👤 Nuevo Cliente",
        font=("Segoe UI", 16, "bold")
    ).pack(pady=(10,5))

    nombre_var = tk.StringVar()

    entry = ctk.CTkEntry(
        frame,
        textvariable=nombre_var,
        placeholder_text="Nombre del cliente",
        height=40
    )
    entry.pack(fill="x", padx=15, pady=10)
    entry.focus()

    def confirmar():
        nombre = nombre_var.get().strip()

        if not nombre:
            return

        resultado["nombre"] = nombre
        modal.destroy()

    ctk.CTkButton(
        frame,
        text="Guardar",
        fg_color="#1976D2",
        hover_color="#1565C0",
        height=40,
        command=confirmar
    ).pack(pady=10)

    modal.wait_window()

    return resultado["nombre"]

def guardar_cotizacion():
    global cliente_actual
    
    if not carrito:
        messagebox.showwarning("Vacío", "El carrito está vacío")
        return

    # ================= USAR CLIENTE SELECCIONADO =================
    if cliente_actual:
        from clientes import obtener_cliente_por_id

        try:
            cliente = obtener_cliente_por_id(cliente_actual["id"])
        except Exception as exc:
            messagebox.showerror(
                "Guardar nota",
                f"No se pudo cargar el cliente.\n\n{exc}"
            )
            return
        cliente_actual = cliente  # 🔥 actualizar referencia


    else:
        nombre = pedir_nombre_cliente(root)

        if not nombre:
            return

        try:
            cliente = obtener_o_crear_cliente(nombre)
        except Exception as exc:
            messagebox.showerror(
                "Guardar nota",
                f"No se pudo crear o cargar el cliente.\n\n{exc}"
            )
            return
    # ================= GUARDAR NOTA =================
    try:
        crear_cotizacion(
            cliente,
            carrito,
            envio=envio_actual,
            pedido=pedido_actual   # 🔥 importante para tu sistema nuevo
        )
    except Exception as exc:
        messagebox.showerror(
            "Guardar nota",
            f"No se pudo guardar la nota.\n\n{exc}"
        )
        return

    messagebox.showinfo(
        "Guardado",
        f"Nota creada para {cliente['nombre']}"
    )
    


    carrito.clear()
    refrescar_carrito()

    cliente_actual = None
    lbl_cliente_valor.configure(text="👤 Seleccionar cliente...")
    btn_editar_cliente.pack_forget()
    telefono_buscar_var.set("")
    lbl_estado_cliente.configure(text="")

def actualizar_total_con_envio():
    total_productos = sum(p["cantidad"] * p["precio"] for p in carrito)
    envio_precio = envio_actual["precio"] if envio_actual else 0
    total = float(total_productos) + float(envio_precio)

    lbl_total.configure(text=f"${total:.2f}")

    # 🔥 TOTAL PIEZAS
    total_general = 0
    totales_hilo = {}

    for p in carrito:
        total_general += p["cantidad"]

        if p["hilo"] not in totales_hilo:
            totales_hilo[p["hilo"]] = 0

        totales_hilo[p["hilo"]] += p["cantidad"]

    texto = ""

    for hilo, cantidad in totales_hilo.items():
        texto += f"{hilo}: {cantidad} pz   "

    texto += f"\nTOTAL PIEZAS: {total_general}"

    texto_final = ""

    for hilo, cantidad in totales_hilo.items():
        texto_final += f"• {hilo}: {cantidad} pz\n"

    texto_final += f"\n🧵 TOTAL PIEZAS: {total_general}"

    lbl_piezas.configure(text=texto_final)



    
    
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
        text=formatear_costo_envio(envio, con_etiqueta=True)
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
    global carrito
    seleccion = tabla_carrito.selection()

    if not seleccion:
        messagebox.showinfo("Selecciona", "Selecciona productos primero")
        return

    if not pedir_password():
        return

    # 🔥 obtener códigos como STRING
    items_seleccionados = []

    for item in seleccion:
        valores = tabla_carrito.item(item)["values"]
        items_seleccionados.append((
            str(valores[2]),
            str(valores[0])
        ))

    carrito = [
        p for p in carrito
        if (str(p["codigo"]), str(p["hilo"])) not in items_seleccionados
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
    items_seleccionados = []

    for item in seleccion:
        valores = tabla_carrito.item(item)["values"]
        items_seleccionados.append((
            str(valores[2]),  # codigo
            str(valores[0])   # hilo
        ))

    for p in carrito:
        if (str(p["codigo"]), str(p["hilo"])) in items_seleccionados:
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

    items_seleccionados = []

    for item in seleccion:
        valores = tabla_carrito.item(item)["values"]
        items_seleccionados.append((
            str(valores[2]),
            str(valores[0])
        ))

    for p in carrito:
        if (str(p["codigo"]), str(p["hilo"])) in items_seleccionados:
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

    try:
        if _modo_api():
            from hilorama_desktop.services.reportes_api_service import dashboard_empacadores
            datos = dashboard_empacadores()
        else:
            from admin_metricas import obtener_metricas_empacadores
            datos = obtener_metricas_empacadores()
    except Exception as exc:
        messagebox.showerror("Dashboard", f"No se pudo cargar el dashboard:\n{exc}")
        return

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

    try:
        if _modo_api():
            from hilorama_desktop.services.reportes_api_service import errores_scan
            datos = errores_scan({"limit": 500})
        else:
            from admin_errores import obtener_errores
            datos = obtener_errores()
    except Exception as exc:
        messagebox.showerror("Errores", f"No se pudieron cargar los errores:\n{exc}")
        return

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

    if _modo_api():
        from hilorama_desktop.services.reportes_api_service import ranking_empacadores
        return ranking_empacadores({"limit": 3})

    conn = _get_conn_local("ranking ventas")

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
def abrir_registro_cambios(parent):

    if _modo_api():
        messagebox.showinfo(
            "Modo API",
            "Este reporte todavía no está disponible en modo API. Se migrará en una fase posterior."
        )
        return

    import datetime
    from auditoria import obtener_registros  # asegúrate que exista

    win = ctk.CTkToplevel(parent)
    win.title("Registro de Cambios")
    win.geometry("1100x700")
    win.configure(fg_color="#F3F4F6")
    win.grab_set()

    # ================= HEADER =================
    header = ctk.CTkFrame(win, corner_radius=12)
    header.pack(fill="x", padx=15, pady=10)

    ctk.CTkLabel(
        header,
        text="📜 Registro de Cambios",
        font=("Segoe UI", 20, "bold")
    ).pack(side="left", padx=10)

    # ================= FILTROS =================
    filtros = ctk.CTkFrame(win, corner_radius=12)
    filtros.pack(fill="x", padx=15, pady=5)

    desde_var = tk.StringVar()
    hasta_var = tk.StringVar()
    nota_var = tk.StringVar()
    tipo_var = tk.StringVar(value="TODOS")

    def campo(label, var, width=140):
        cont = ctk.CTkFrame(filtros, fg_color="transparent")
        ctk.CTkLabel(cont, text=label).pack(anchor="w")
        ctk.CTkEntry(cont, textvariable=var, width=width).pack()
        cont.pack(side="left", padx=10, pady=5)

    campo("Desde (YYYY-MM-DD)", desde_var)
    campo("Hasta (YYYY-MM-DD)", hasta_var)
    campo("ID Nota", nota_var, 120)

    combo_tipo = ctk.CTkComboBox(
        filtros,
        variable=tipo_var,
        values=["TODOS", "Cambio de estado", "Cambio de cantidad", "Cambio de envío", "Venta eliminada"],
        width=180
    )
    combo_tipo.pack(side="left", padx=10, pady=20)

    # ================= TABLA =================
    frame_tabla = ctk.CTkFrame(win, corner_radius=12)
    frame_tabla.pack(fill="both", expand=True, padx=15, pady=10)

    cols = ("Fecha", "Nota", "Tipo", "Descripción")

    tree = ttk.Treeview(
        frame_tabla,
        columns=cols,
        show="headings"
    )

    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, anchor="center")

    tree.pack(fill="both", expand=True)

    # ================= CARGAR =================
    def cargar():
        tree.delete(*tree.get_children())

        registros = obtener_registros()

        for r in registros:

            if nota_var.get() and str(r["nota_id"]) != nota_var.get():
                continue

            if tipo_var.get() != "TODOS" and r["tipo"] != tipo_var.get():
                continue

            if desde_var.get() and r["fecha"][:10] < desde_var.get():
                continue

            if hasta_var.get() and r["fecha"][:10] > hasta_var.get():
                continue

            tree.insert("", "end", values=(
                r["fecha"],
                r["nota_id"],
                r["tipo"],
                r["descripcion"]
            ))

    ctk.CTkButton(
        filtros,
        text="🔎 Filtrar",
        fg_color="#1976D2",
        command=cargar
    ).pack(side="left", padx=15, pady=20)

    cargar()


def _construir_paneles_ventas():
    global txt_whatsapp, tabla_carrito, lbl_total, lbl_piezas, lbl_envio
    global lbl_cliente_valor, lbl_estado_cliente, lbl_pedido_valor, lbl_pedido_fecha
    global btn_editar_cliente, telefono_buscar_var
    global BASE_DIR, icon_trash, icon_ship, icon_edit, icon_asignar
    global frame_total, frame_top_btns

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
    frame_carrito.pack(fill="both", expand=True, padx=8, pady=8)


    # ================= HEADER =================
    header = ctk.CTkLabel(
        frame_carrito,
        text="Carrito",
        font=("Segoe UI", 18, "bold"),
        anchor="w"
    )
    header.pack(fill="x", padx=12, pady=(10, 4))


    # ================= TABLA =================
    frame_tabla = tk.Frame(frame_carrito, bg="white")
    frame_tabla.pack(fill="both", expand=True, padx=8, pady=6)


    style = ttk.Style()
    style.theme_use("default")

    style.configure(
        "Treeview",
        background="white",
        foreground="black",
        rowheight=32,
        fieldbackground="white",
        borderwidth=0,
        font=("Segoe UI", 10)
    )

    style.configure(
        "Treeview.Heading",
        font=("Segoe UI", 10, "bold"),
        background="#F3F4F6",
        foreground="#333"
    )

    style.map("Treeview", background=[("selected", "#DCEBFF")])


    cols = ("Hilo", "Color", "Código", "Cantidad", "Precio", "Subtotal")


    tabla_carrito = ttk.Treeview(
        frame_tabla,
        columns=cols,
        show="headings",
        selectmode="extended"
    )

    columnas_carrito = {
        "Hilo": 120,
        "Color": 130,
        "Código": 90,
        "Cantidad": 76,
        "Precio": 82,
        "Subtotal": 90,
    }
    for c in cols:
        tabla_carrito.heading(c, text=c)
        tabla_carrito.column(
            c,
            anchor="center",
            width=columnas_carrito[c],
            minwidth=58,
            stretch=True,
        )

    tabla_carrito.pack(fill="both", expand=True)
    def editar_celda(event):
        region = tabla_carrito.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = tabla_carrito.identify_row(event.y)
        column = tabla_carrito.identify_column(event.x)
        col_index = int(column.replace("#", "")) - 1

        # Solo permitir editar Cantidad (3) y Precio (4)
        if col_index not in [3, 4]:
            return

        x, y, width, height = tabla_carrito.bbox(row_id, column)
        valores = tabla_carrito.item(row_id)["values"]
        codigo = valores[2]
        hilo = valores[0]
        # Limpiar formato $
        valor_actual = valores[col_index]
        if col_index == 4:
            if not pedir_password():
                return
            valor_actual = str(valor_actual).replace("$", "")

        # 🔵 Contenedor elegante
        frame_editor = tk.Frame(
            tabla_carrito,
            bg="white",
            bd=1,
            relief="solid"
        )
        frame_editor.place(x=x, y=y, width=width, height=height)

        # ==========================================
        # 🔵 CANTIDAD → SPINBOX CON FLECHAS
        # ==========================================
        if col_index == 3:

            editor = tk.Spinbox(
                frame_editor,
                from_=1,
                to=9999,
                font=("Segoe UI", 12),
                justify="center",
                bd=0
            )

        # ==========================================
        # 🔵 PRECIO → ENTRY NORMAL
        # ==========================================
        else:

            editor = tk.Entry(
                frame_editor,
                font=("Segoe UI", 12),
                justify="center",
                bd=0
            )

        editor.pack(fill="both", expand=True)
        editor.insert(0, valor_actual)
        editor.focus()

        def guardar(event=None):
            nuevo_valor = editor.get()

            try:
                if col_index == 3:
                    nuevo_valor = int(nuevo_valor)
                else:
                    nuevo_valor = float(nuevo_valor)
            except:
                frame_editor.destroy()
                return

            for p in carrito:
                if (
                    str(p["codigo"]) == str(codigo)
                    and str(p["hilo"]) == str(hilo)
                ):
                    if col_index == 3:
                        p["cantidad"] = nuevo_valor
                    else:
                        p["precio"] = nuevo_valor
                    break

            frame_editor.destroy()
            refrescar_carrito()

        def cancelar(event=None):
            frame_editor.destroy()

        editor.bind("<Return>", guardar)
        editor.bind("<FocusOut>", cancelar)

    tabla_carrito.bind("<Double-1>", editar_celda)

    # zebra rows
    tabla_carrito.tag_configure("odd", background="#FAFAFA")
    tabla_carrito.tag_configure("even", background="white")
    tabla_carrito.tag_configure("bajo", background="#FFE5E5")

    # ================= FOOTER =================
    footer = tk.Frame(frame_carrito, bg="white")
    footer.pack(fill="x", padx=8, pady=(4, 8))


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
    frame_top = tk.Frame(card_total, bg="white")
    frame_top.pack(fill="x", padx=6, pady=(4, 0))

    frame_top.columnconfigure(0, weight=1)  # empuja botones a la derecha

    frame_top_btns = tk.Frame(frame_top)
    frame_top_btns.grid(row=0, column=1, sticky="e")
    btn_clientes = ctk.CTkButton(
        frame_top_btns,
        text="👤 Clientes",
        corner_radius=18,
        fg_color="#FB8C00",      # naranja moderno
        hover_color="#EF6C00",
        height=32,
        width=88,
        font=("Segoe UI", 11, "bold"),
        command=lambda: abrir_clientes(root)
    )
    btn_clientes.pack(side="left", padx=2)

    # ================= PANEL TOTAL MODERNO (VERTICAL) =================

    frame_total = ctk.CTkFrame(
        card_total,
        corner_radius=18,
        fg_color="white"
    )
    frame_total.pack(fill="both", expand=True, padx=8, pady=8)


    # ===== TOTAL =====
    lbl_total_title = ctk.CTkLabel(
        frame_total,
        text="TOTAL",
        font=("Segoe UI", 14)
    )
    lbl_total_title.pack(anchor="w", padx=12, pady=(12, 0))


    lbl_total = ctk.CTkLabel(
        frame_total,
        text="$0.00",
        font=("Segoe UI", 30, "bold")
    )
    lbl_total.pack(anchor="w", padx=12, pady=(0, 10))
    lbl_piezas = ctk.CTkLabel(
        frame_total,
        text="",
        font=("Segoe UI", 13)
    )
    lbl_piezas.pack(anchor="w", padx=12, pady=(0,8))


    ctk.CTkFrame(frame_total, height=2, fg_color="#EEEEEE").pack(fill="x", padx=15, pady=5)


    # ===== ENVÍO + BOTÓN (MISMA FILA) =====
    frame_envio = ctk.CTkFrame(frame_total, fg_color="transparent")
    frame_envio.pack(fill="x", padx=12, pady=8)

    frame_envio.columnconfigure(0, weight=1)  # texto ocupa todo
    frame_envio.columnconfigure(1, weight=0)  # botón tamaño fijo

    BASE_DIR = os.path.dirname(__file__)

    icon_ship_path  = os.path.join(BASE_DIR, "shipping.png")
    icon_ship  = ctk.CTkImage(Image.open(icon_ship_path),  size=(22, 22))

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
    frame_cliente_pedido.pack(fill="x", padx=12, pady=(8, 4))


    # ---- cliente ----
    # ==================================================
    # 🔵 CLIENTE CON ICONO EDITAR
    # ==================================================

    frame_cliente_btns = ctk.CTkFrame(
        frame_cliente_pedido,
        fg_color="transparent"
    )
    frame_cliente_btns.pack(fill="x", padx=8, pady=(0, 5))
    # =========================================
    # 🔎 BUSCADOR RÁPIDO CLIENTE
    # =========================================

    frame_busqueda_cliente = ctk.CTkFrame(
        frame_cliente_pedido,
        fg_color="transparent"
    )
    frame_busqueda_cliente.pack(fill="x", padx=8, pady=(8, 4))

    telefono_buscar_var = tk.StringVar()

    entry_buscar_tel = ctk.CTkEntry(
        frame_busqueda_cliente,
        textvariable=telefono_buscar_var,
        placeholder_text="Buscar por nombre o teléfono...",
        height=36,
        corner_radius=10
    )
    entry_buscar_tel.pack(side="left", fill="x", expand=True, padx=(0,8))

    lbl_estado_cliente = ctk.CTkLabel(
        frame_cliente_pedido,
        text="",
        font=("Segoe UI", 12)
    )
    lbl_estado_cliente.pack(anchor="w", padx=8)

    lista_sugerencias_cliente = tk.Listbox(
        frame_cliente_pedido,
        height=4,
        font=("Segoe UI", 10),
        exportselection=False
    )
    clientes_sugeridos_cliente = []
    busqueda_cliente_after = {"id": None}

    def limpiar_telefono(texto):
        return "".join(c for c in texto if c.isdigit())

    def formatear_telefono(numero):
        # Quitar lada si tiene 52
        if numero.startswith("52") and len(numero) == 12:
            numero = numero[2:]

        if len(numero) <= 2:
            return numero
        elif len(numero) <= 6:
            return f"{numero[:2]} {numero[2:]}"
        else:
            return f"{numero[:2]} {numero[2:6]} {numero[6:10]}"
    
    def buscar_cliente_automatico(*args):
        global cliente_actual

        numero_limpio = limpiar_telefono(telefono_buscar_var.get())

        # Permitir máximo 12 dígitos
        if len(numero_limpio) > 12:
            numero_limpio = numero_limpio[:12]

        # Actualizar máscara visual
        telefono_formateado = formatear_telefono(numero_limpio)
        telefono_buscar_var.set(telefono_formateado)

        # Quitar lada si viene con 52
        numero_busqueda = numero_limpio
        if numero_limpio.startswith("52") and len(numero_limpio) == 12:
            numero_busqueda = numero_limpio[2:]

        # Solo buscar cuando tenga exactamente 10 dígitos reales
        if len(numero_busqueda) == 10:

            cliente = buscar_cliente_por_telefono(numero_busqueda)

            if cliente:
                cliente_actual = cliente

                lbl_cliente_valor.configure(
                    text=f"👤 {cliente['nombre']}"
                )

                lbl_estado_cliente.configure(
                    text="✅ Cliente existente",
                    text_color="#16A34A"
                )

                entry_buscar_tel.configure(
                    border_color="#16A34A"
                )

                btn_editar_cliente.pack(side="right", padx=(6,0))

            else:
                cliente_actual = None

                lbl_estado_cliente.configure(
                    text="❌ No hay registro",
                    text_color="#DC2626"
                )

                entry_buscar_tel.configure(
                    border_color="#DC2626"
                )

        else:
            # Estado neutro mientras escribe
            lbl_estado_cliente.configure(text="")
            entry_buscar_tel.configure(
                border_color="#D1D5DB"
            )

    def on_key_release(event):
        global cliente_actual

        cursor_pos = entry_buscar_tel.index("insert")

        numero_limpio = limpiar_telefono(entry_buscar_tel.get())

        # máximo 12 dígitos
        if len(numero_limpio) > 12:
            numero_limpio = numero_limpio[:12]

        # quitar lada si viene con 52
        numero_busqueda = numero_limpio
        if numero_limpio.startswith("52") and len(numero_limpio) == 12:
            numero_busqueda = numero_limpio[2:]

        # aplicar máscara
        numero_formateado = formatear_telefono(numero_limpio)

        entry_buscar_tel.delete(0, "end")
        entry_buscar_tel.insert(0, numero_formateado)

        entry_buscar_tel.icursor(len(numero_formateado))

        # ==========================
        # BÚSQUEDA AUTOMÁTICA
        # ==========================
        if len(numero_busqueda) == 10:

            cliente = buscar_cliente_por_telefono(numero_busqueda)

            if cliente:
                cliente_actual = cliente

                lbl_cliente_valor.configure(
                    text=f"👤 {cliente['nombre']}"
                )

                lbl_estado_cliente.configure(
                    text="✅ Cliente existente",
                    text_color="#16A34A"
                )

                entry_buscar_tel.configure(
                    border_color="#16A34A"
                )

                btn_editar_cliente.pack(side="right", padx=(6,0))

            else:
                cliente_actual = None

                lbl_estado_cliente.configure(
                    text="❌ No hay registro",
                    text_color="#DC2626"
                )

                entry_buscar_tel.configure(
                    border_color="#DC2626"
                )

        else:
            lbl_estado_cliente.configure(text="")
            entry_buscar_tel.configure(
                border_color="#D1D5DB"
            )
    entry_buscar_tel.bind("<KeyRelease>", on_key_release)

    def aplicar_cliente_rapido_v2(cliente):
        global cliente_actual

        cliente_actual = cliente
        nombre = cliente.get("nombre", "")
        telefono = cliente.get("telefono", "")
        lbl_cliente_valor.configure(text=f"Cliente: {nombre}")
        lbl_estado_cliente.configure(
            text=f"Cliente existente {telefono}".strip(),
            text_color="#16A34A"
        )
        entry_buscar_tel.configure(border_color="#16A34A")
        btn_editar_cliente.pack(side="right", padx=(6,0))
        lista_sugerencias_cliente.pack_forget()

    def limpiar_sugerencias_cliente_v2():
        lista_sugerencias_cliente.delete(0, "end")
        lista_sugerencias_cliente.pack_forget()

    def mostrar_sugerencias_cliente_v2(clientes):
        clientes_sugeridos_cliente.clear()
        lista_sugerencias_cliente.delete(0, "end")

        for cliente in clientes[:6]:
            clientes_sugeridos_cliente.append(cliente)
            nombre = cliente.get("nombre", "")
            telefono = cliente.get("telefono", "")
            lista_sugerencias_cliente.insert("end", f"{nombre} | {telefono}")

        if clientes_sugeridos_cliente:
            lista_sugerencias_cliente.pack(fill="x", padx=8, pady=(0,4))
        else:
            limpiar_sugerencias_cliente_v2()

    def seleccionar_sugerencia_cliente_v2(event=None):
        if not lista_sugerencias_cliente.curselection():
            return
        indice = lista_sugerencias_cliente.curselection()[0]
        if 0 <= indice < len(clientes_sugeridos_cliente):
            aplicar_cliente_rapido_v2(clientes_sugeridos_cliente[indice])

    lista_sugerencias_cliente.bind("<ButtonRelease-1>", seleccionar_sugerencia_cliente_v2)
    lista_sugerencias_cliente.bind("<Return>", seleccionar_sugerencia_cliente_v2)
    lista_sugerencias_cliente.bind("<Double-1>", seleccionar_sugerencia_cliente_v2)

    def ejecutar_busqueda_cliente_v2(texto_original):
        global cliente_actual

        texto = str(texto_original or "").strip()
        if not texto:
            cliente_actual = None
            limpiar_sugerencias_cliente_v2()
            lbl_estado_cliente.configure(text="")
            entry_buscar_tel.configure(border_color="#D1D5DB")
            btn_editar_cliente.pack_forget()
            return

        digitos = limpiar_telefono(texto)
        solo_telefono = bool(digitos) and all(c.isdigit() or c in " +-()." for c in texto)
        termino = texto

        if solo_telefono:
            if len(digitos) > 12:
                digitos = digitos[:12]
            termino = digitos[2:] if digitos.startswith("52") and len(digitos) == 12 else digitos
            if len(termino) < 3:
                limpiar_sugerencias_cliente_v2()
                lbl_estado_cliente.configure(text="")
                entry_buscar_tel.configure(border_color="#D1D5DB")
                return
        elif len(texto) < 2:
            limpiar_sugerencias_cliente_v2()
            lbl_estado_cliente.configure(text="")
            entry_buscar_tel.configure(border_color="#D1D5DB")
            return

        try:
            resultados = buscar_clientes(termino, limit=6)
        except Exception as exc:
            cliente_actual = None
            limpiar_sugerencias_cliente_v2()
            lbl_estado_cliente.configure(
                text=f"No se pudo buscar cliente: {exc}",
                text_color="#DC2626"
            )
            entry_buscar_tel.configure(border_color="#DC2626")
            return

        if solo_telefono and len(termino) == 10:
            for cliente in resultados:
                if limpiar_telefono(cliente.get("telefono", "")) == termino:
                    aplicar_cliente_rapido_v2(cliente)
                    return

        cliente_actual = None
        mostrar_sugerencias_cliente_v2(resultados)
        if resultados:
            lbl_estado_cliente.configure(
                text="Seleccione el cliente de la lista.",
                text_color="#2563EB"
            )
            entry_buscar_tel.configure(border_color="#2563EB")
        else:
            lbl_estado_cliente.configure(
                text="No hay registro",
                text_color="#DC2626"
            )
            entry_buscar_tel.configure(border_color="#DC2626")
            btn_editar_cliente.pack_forget()

    def on_key_release_busqueda_parcial(event):
        texto = entry_buscar_tel.get()
        digitos = limpiar_telefono(texto)
        solo_telefono = bool(digitos) and all(c.isdigit() or c in " +-()." for c in texto)

        if solo_telefono and digitos:
            if len(digitos) > 12:
                digitos = digitos[:12]
            numero_formateado = formatear_telefono(digitos)
            entry_buscar_tel.delete(0, "end")
            entry_buscar_tel.insert(0, numero_formateado)
            entry_buscar_tel.icursor(len(numero_formateado))
            texto = numero_formateado

        if busqueda_cliente_after["id"]:
            entry_buscar_tel.after_cancel(busqueda_cliente_after["id"])
        busqueda_cliente_after["id"] = entry_buscar_tel.after(
            300,
            lambda: ejecutar_busqueda_cliente_v2(texto)
        )

    entry_buscar_tel.bind("<KeyRelease>", on_key_release_busqueda_parcial)

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

    def editar_y_refrescar():
        global cliente_actual

        if not cliente_actual:
            messagebox.showwarning(
                "Sin cliente",
                "Primero selecciona un cliente."
            )
            return

        # Recargar cliente desde BD antes de editar
        from clientes import obtener_cliente_por_id
        cliente_actual = obtener_cliente_por_id(cliente_actual["id"])

        editar_cliente_por_id(cliente_actual["id"], root)

    btn_editar_cliente = ctk.CTkButton(
        frame_cliente_btns,
        text="",
        image=icon_edit,
        width=40,
        height=40,
        fg_color="#E3F2FD",
        hover_color="#BBDEFB",
        corner_radius=12,
        command=editar_y_refrescar
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

    ctk.CTkButton(
        card_pedido,
        text="🗑 Eliminar pedido",
        height=30,
        fg_color="#FEE2E2",
        text_color="#B91C1C",
        hover_color="#FECACA",
        corner_radius=10,
        command=eliminar_pedido_opciones
    ).pack(anchor="w", padx=18, pady=(0,14))

    # ---- click en la tarjeta = configurar ----
    card_pedido.bind("<Button-1>", lambda e: configurar_pedido())
    lbl_pedido_valor.bind("<Button-1>", lambda e: configurar_pedido())


    frame_admin = ctk.CTkFrame(
        frame_top_btns,
        fg_color="transparent"
    )
    frame_admin.pack(side="left", padx=2)





    # ===== BOTONES GRANDES =====
    btn_guardar = ctk.CTkButton(
        frame_total,
        text="💾  Guardar nota",
        fg_color="#1976D2",
        hover_color="#1565C0",
        height=46,
        corner_radius=14,
        font=("Segoe UI", 14, "bold"),
        command=guardar_cotizacion
    )
    btn_guardar.pack(fill="x", padx=12, pady=(12, 8))


    btn_ver = ctk.CTkButton(
        frame_total,
        text="👀  Ver notas",
        fg_color="#D8C140",
        hover_color="#EBE828",
        text_color="black",
        height=46,
        corner_radius=14,
        font=("Segoe UI", 14, "bold"),
        command=lambda: abrir_visor(root)
    )
    btn_ver.pack(fill="x", padx=12, pady=(0, 12))


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
        height=44,
        fg_color="#F3F4F6",
        hover_color="#E5E7EB",
        corner_radius=15,
        command=abrir_panel_asignacion
    ).pack(pady=(0, 12))
    ctk.CTkButton(
        frame_total,
        text="🚚 Gestión de Envíos",
        fg_color="#0EA5E9",
        hover_color="#0284C7",
        height=44,
        corner_radius=14,
        font=("Segoe UI", 13, "bold"),
        command=abrir_panel_envios
    ).pack(fill="x", padx=12, pady=(0, 12))

    ctk.CTkButton(
        frame_admin,
        text="📊 Dashboard",
        height=36,
        corner_radius=12,
        fg_color="#7C3AED",
        hover_color="#6D28D9",
        command=abrir_dashboard
    ).pack(side="left", padx=2)

    ctk.CTkButton(
        frame_admin,
        text="⚠ Errores",
        width=68,
        height=32,
        corner_radius=12,
        fg_color="#EF4444",
        hover_color="#DC2626",
        command=abrir_panel_errores
    ).pack(side="left", padx=2)
    ctk.CTkButton(
        frame_total,
        text="📜 Registro de Cambios",
        fg_color="#455A64",
        hover_color="#37474F",
        height=44,
        corner_radius=14,
        font=("Segoe UI", 13, "bold"),
        command=lambda: abrir_registro_cambios(root)
    ).pack(fill="x", padx=12, pady=(0, 12))

def _buscar_producto_para_carrito(pedido, productos):
    producto_id = pedido.get("producto_id", pedido.get("id"))
    if producto_id not in (None, ""):
        for producto in productos:
            if str(producto.get("id")) == str(producto_id):
                return producto
        return None

    codigo = str(pedido.get("codigo", "")).strip()
    candidatos = [
        producto for producto in productos
        if str(producto.get("codigo", "")).strip() == codigo
    ]
    for campo in ("marca", "hilo", "color"):
        esperado = pedido.get(campo)
        if esperado not in (None, ""):
            candidatos = [
                producto for producto in candidatos
                if str(producto.get(campo, "")).strip().casefold()
                == str(esperado).strip().casefold()
            ]
    return candidatos[0] if candidatos else None


def _precio_producto_para_carrito(producto):
    for campo in ("precio", "precio_venta", "venta"):
        valor = producto.get(campo)
        if valor in (None, ""):
            continue
        try:
            return float(valor)
        except (TypeError, ValueError):
            continue
    return 0.0


def agregar_al_carrito(pedido):
    cantidad = pedido["cantidad"]
    p = _buscar_producto_para_carrito(pedido, productos_cache)
    if not p:
        messagebox.showwarning(
            "Producto no encontrado",
            "No se encontro el producto seleccionado. Actualiza la lista e intenta de nuevo.",
        )
        return False

    codigo = p.get("codigo")
    precio = _precio_producto_para_carrito(p)
    producto_id = p.get("id")

    for c in carrito:
        mismo_producto = (
            producto_id not in (None, "")
            and str(c.get("producto_id")) == str(producto_id)
        )
        compatibilidad_local = (
            producto_id in (None, "")
            and str(c.get("codigo")) == str(codigo)
            and c.get("marca") == p.get("marca")
            and c.get("hilo") == p.get("hilo")
        )
        if mismo_producto or compatibilidad_local:
            c["cantidad"] += cantidad
            return True

    carrito.append({
        "producto_id": producto_id,
        "marca": p.get("marca"),
        "hilo": p.get("hilo"),
        "color": p.get("color"),
        "codigo": codigo,
        "codigo_barras": p.get("codigo_barras"),
        "cantidad": cantidad,
        "precio": precio,
        "stock": p.get("stock", 0),
    })
    return True


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
                p["hilo"],
                p["color"],
                p["codigo"],
                p["cantidad"],
                f"${p['precio']:.2f}",
                f"${subtotal:.2f}"
            ),
            tags=(tag,)
        )

    actualizar_total_con_envio()

# ================= INICIO =================


def _reset_estado_ventas():
    global carrito, envio_actual, cliente_actual, pedido_actual
    global fecha_desde, fecha_hasta, productos_cache, _auth_service_ventas
    global _heartbeat_service_ventas

    carrito = []
    envio_actual = None
    cliente_actual = None
    pedido_actual = None
    fecha_desde = None
    fecha_hasta = None
    productos_cache = []
    if _heartbeat_service_ventas:
        _heartbeat_service_ventas.stop()
        _heartbeat_service_ventas = None


def _bloquear_por_licencia_ventas(mensaje):
    global _heartbeat_service_ventas

    if _heartbeat_service_ventas:
        _heartbeat_service_ventas.stop()
        _heartbeat_service_ventas = None

    parent = root if root is not None else None
    messagebox.showerror("Acceso bloqueado", mensaje, parent=parent)
    if root is not None:
        root.destroy()


def _iniciar_heartbeat_ventas():
    global _heartbeat_service_ventas

    if _auth_service_ventas is None or root is None:
        return

    try:
        from hilorama_desktop.services.heartbeat_service import HeartbeatService
    except Exception as exc:
        messagebox.showwarning(
            "Heartbeat",
            f"No se pudo iniciar la verificacion periodica de acceso:\n{exc}",
            parent=root,
        )
        return

    _heartbeat_service_ventas = HeartbeatService(
        root,
        _auth_service_ventas,
        modulo_actual="ventas",
        on_blocked=_bloquear_por_licencia_ventas,
        )
    _heartbeat_service_ventas.start()


def _crear_area_imagen_sin_tkdnd(parent):
    card = ctk.CTkFrame(parent, corner_radius=18, fg_color="#F8FAFC")
    card.pack(fill="both", expand=True, padx=15, pady=12)
    ctk.CTkLabel(
        card,
        text="Imagen de pedido",
        font=("Segoe UI", 16, "bold"),
    ).pack(anchor="w", padx=18, pady=(14, 6))
    ctk.CTkLabel(
        card,
        text="Drag and drop no disponible en esta ventana. Use el boton para seleccionar imagen.",
        justify="center",
        font=("Segoe UI", 13),
        text_color="#555",
        wraplength=360,
    ).pack(fill="x", padx=18, pady=(0, 10))
    ctk.CTkButton(
        card,
        text="Seleccionar imagen",
        command=cargar_imagen,
    ).pack(padx=18, pady=(0, 15))


def _construir_area_imagen_ventas():
    if crear_area_imagen is not None and soporta_tkdnd(card_imagen):
        try:
            crear_area_imagen(
                card_imagen,
                marca_var,
                hilo_var,
                agregar_al_carrito,
                refrescar_carrito,
            )
            return
        except Exception:
            pass
    for child in card_imagen.winfo_children():
        child.destroy()
    _crear_area_imagen_sin_tkdnd(card_imagen)


def _cargar_estado_inicial_ventas():
    global pedido_actual, fecha_desde, fecha_hasta

    cargar_contexto()

    pedido_guardado = cargar_pedido()

    if pedido_guardado:
        pedido_actual = pedido_guardado["numero"]
        fecha_desde = pedido_guardado["desde"]
        fecha_hasta = pedido_guardado["hasta"]

        lbl_pedido_valor.configure(
            text=f"Pedido #{pedido_actual}\n{fecha_desde} -> {fecha_hasta}"
        )

        if pedido_por_vencer(pedido_guardado):
            messagebox.showwarning(
                "Pedido por vencer",
                "Este pedido termina ma?ana.\nConsidera crear uno nuevo."
            )

        if pedido_vencido(pedido_guardado):
            messagebox.showinfo(
                "Pedido vencido",
                "Este pedido ya termin?.\nDebes crear uno nuevo."
            )

    _construir_area_imagen_ventas()


def crear_vista_ventas(parent=None):
    global _auth_service_ventas

    _reset_estado_ventas()
    if parent is None:
        _auth_service_ventas = _validar_acceso_inicial_ventas()
    else:
        _auth_service_ventas = None

    vista = _crear_contenedores_ventas(parent)
    _construir_contexto_moderno()
    _construir_paneles_ventas()
    _configurar_drag_and_drop()
    _cargar_estado_inicial_ventas()

    if parent is None:
        _iniciar_heartbeat_ventas()
        root.mainloop()

    return vista


def main():
    crear_vista_ventas()

if __name__ == "__main__":
    main()
crear_cotizacion
