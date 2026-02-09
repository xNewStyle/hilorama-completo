

import os
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.platypus import Spacer, Table, Flowable

def draw_marca_agua(
    c,
    width,
    height,
    ruta_img="marca_agua.png",

    escala=0.55,     # tamaño relativo
    x_offset_cm=0,   # ← mover izquierda/derecha
    y_offset_cm=0,   # ← mover abajo/arriba
    alpha=0.10       # transparencia
):
    """
    Marca de agua PNG centrada + movible

    escala       → tamaño (0.3–0.8 típico)
    x_offset_cm  → + derecha / - izquierda
    y_offset_cm  → + arriba   / - abajo
    alpha        → transparencia (0.05–0.2 recomendado)
    """

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(BASE_DIR, ruta_img)

    if not os.path.exists(ruta):
        return

    from PIL import Image

    img = Image.open(ruta)
    iw, ih = img.size

    # tamaño proporcional
    w = width * escala
    h = w * (ih / iw)

    # centro base
    x = (width - w) / 2
    y = (height - h) / 2

    # 🔥 aplicar offsets
    x += x_offset_cm * cm
    y += y_offset_cm * cm

    c.saveState()
    c.setFillAlpha(alpha)

    c.drawImage(
        ruta,
        x,
        y,
        width=w,
        height=h,
        mask="auto"
    )

    c.restoreState()



def draw_fondo_papel(c, width, height, ruta_fondo="fondo_papel.jpg"):

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(BASE_DIR, ruta_fondo)

    if not os.path.exists(ruta):
        print("⚠ Fondo no encontrado:", ruta)  # debug
        return

    c.drawImage(
        ruta,
        0, 0,
        width=width,
        height=height,
        preserveAspectRatio=False,
        mask="auto"
    )
def draw_marco(c, width, height, ruta_marco,
               x_cm=0, y_cm=0,
               w_cm=10, h_cm=10):
    """
    Marco decorativo PNG con transparencia

    x_cm, y_cm  → posición desde esquina inferior izquierda
    w_cm, h_cm  → tamaño (si None usa tamaño hoja)
    """

    if not ruta_marco:
        return

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(BASE_DIR, ruta_marco)

    if not os.path.exists(ruta):
        print("⚠ Marco no encontrado:", ruta)
        return

    x = x_cm * cm
    y = y_cm * cm

    w = (w_cm * cm) if w_cm else width
    h = (h_cm * cm) if h_cm else height

    c.drawImage(
        ruta,
        x,
        y,
        width=w,
        height=h,
        preserveAspectRatio=False,
        mask="auto"   # 🔥 transparencia
    )



def draw_logo(c, ruta_logo, x_cm=5, y_cm=10, w_cm=12):

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(BASE_DIR, ruta_logo)

    if not os.path.exists(ruta):
        print("⚠ Logo no encontrado:", ruta)
        return

    x = x_cm * cm
    y = y_cm * cm
    w = w_cm * cm
    h = w * 2   # 🔥 proporción del logo (ajústala)

    c.drawImage(
        ruta,
        x,
        y,
        width=w,
        height=h,   # ← CLAVE
        preserveAspectRatio=True,
        mask="auto"
    )

def draw_info_nota(
    c,
    nota_id,
    cliente_id,
    x_cm=8,
    y_cm=26,
    ancho_cm=9
):
    """
    Bloque alineado profesionalmente:

    Nota de Venta No:   0012
    ID del Cliente:     3

    x_cm     = inicio izquierda
    y_cm     = altura
    ancho_cm = ancho total del bloque
    """

    from reportlab.platypus import Table, TableStyle

    x = x_cm * cm
    y = y_cm * cm
    w = ancho_cm * cm

    data = [
        ["Nota de Venta No:", str(nota_id)],
        ["ID del Cliente:", str(cliente_id)]
    ]

    tabla = Table(data, colWidths=[w*0.65, w*0.35])

    tabla.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Times-Roman", 12),

        ("ALIGN", (0,0), (0,-1), "LEFT"),   # etiquetas
        ("ALIGN", (1,0), (1,-1), "RIGHT"),  # números

        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#2E3A3F")),

        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING", (0,0), (-1,-1), 2),

        # sin bordes
        ("GRID", (0,0), (-1,-1), 0, colors.transparent),
    ]))

    tabla.wrapOn(c, w, 2*cm)
    tabla.drawOn(c, x, y)

def draw_info_cliente_envio(
    c,
    cliente,
    paqueteria,
    x_cm=2,
    y_cm=20,
    ancho_cm=9
):
    """
    Bloque:

    Cliente:     Juan Pérez
    Paquetería:  DHL

    Movible y alineado elegante
    """

    from reportlab.platypus import Table, TableStyle

    x = x_cm * cm
    y = y_cm * cm
    w = ancho_cm * cm

    data = [
        ["Cliente:", str(cliente)],
        ["Paquetería:", str(paqueteria)]
    ]

    tabla = Table(data, colWidths=[w*0.40, w*0.60])

    tabla.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Times-Roman", 14),

        ("ALIGN", (0,0), (0,-1), "LEFT"),
        ("ALIGN", (1,0), (1,-1), "LEFT"),

        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#2E3A3F")),

        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING", (0,0), (-1,-1), 2),

        ("GRID", (0,0), (-1,-1), 0, colors.transparent),
    ]))

    tabla.wrapOn(c, w, 2*cm)
    tabla.drawOn(c, x, y)

from datetime import datetime, timedelta
from reportlab.platypus import Table, TableStyle


def draw_info_cliente_envio_fechas(
    c,
   
    fecha_base,
    x_cm=3,
    y_cm=19,
    ancho_cm=14
):
    """
    Layout:

    Cliente: Patricia Lozano      Fecha Estimada de Envío:
    Paquetería: DHL               25/02/2026 - 27/02/2026
    """

    # ========= rango fechas (+2 días) =========
    rango = ""
    if fecha_base:
        try:
            fecha_base = fecha_base.split(" ")[0]
            f = datetime.strptime(fecha_base, "%d/%m/%Y")
            entrega = f + timedelta(days=2)
            rango = f"{f.strftime('%d/%m/%Y')} - {entrega.strftime('%d/%m/%Y')}"
        except:
            rango = fecha_base

    x = x_cm * cm
    y = y_cm * cm
    w = ancho_cm * cm

    data = [
        ["Fecha Estimada de Envío:"],
        [rango]
    ]

    tabla = Table(data, colWidths=[w*0.55, w*0.45])

    tabla.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Times-Roman", 14),

        ("ALIGN", (0,0), (-1,-1), "LEFT"),

        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#B49A04")),

        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 3),

        ("GRID", (0,0), (-1,-1), 0, colors.transparent),
    ]))

    tabla.wrapOn(c, w, 2*cm)
    tabla.drawOn(c, x, y)


# ================= FUENTE ELEGANTE =================
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "PlayfairDisplay-Italic.ttf")

if os.path.exists(FONT_PATH):
    pdfmetrics.registerFont(TTFont("PlayfairItalic", FONT_PATH))
    FUENTE_ELEGANTE = "PlayfairItalic"
else:
    # fallback automático si no existe
    FUENTE_ELEGANTE = "Helvetica-Oblique"



def draw_texto_elegante(
    c,
    texto="¡Gracias por elegirnos!",
    y_cm=14,
    size=30,
    color=colors.HexColor("#6B5E4B")
):
    width, height = LETTER

    c.setFont(FUENTE_ELEGANTE, size)
    c.setFillColor(color)

    text_width = c.stringWidth(texto, FUENTE_ELEGANTE, size)

    x = (width - text_width) / 2
    y = y_cm * cm

    c.drawString(x, y, texto)

def draw_totales_fuera_tabla(
    c,
    subtotal,
    envio,
    total,
    x_cm=13,
    y_cm=6
):
    """
    Totales elegantes SIN grilla
    alineados a la derecha
    """

    x = x_cm * cm
    y = y_cm * cm

    c.setFillColor(colors.HexColor("#2E3A3F"))

    # Subtotal
    c.setFont("Helvetica", 12)
    c.drawRightString(x, y + 1.2*cm, f"Subtotal:   ${subtotal:.2f}")

    # Envío
    c.drawRightString(x, y + 0.5*cm, f"Envío:      ${envio:.2f}")

    # TOTAL grande
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(colors.HexColor("#1B5E20"))
    c.drawRightString(x, y - 0.6*cm, f"Total:  ${total:.2f}")

# ================= PDF =================
def draw_imagen_inferior(
    c,
    ruta_img,
    x_cm=1,
    y_cm=2,
    w_cm=4,
    h_cm=None
):
    """
    Imagen decorativa inferior izquierda (PNG transparencia)

    x_cm  → izquierda/derecha
    y_cm  → abajo/arriba
    w_cm  → ancho
    h_cm  → alto (None = proporcional)
    """

    if not ruta_img:
        return

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(BASE_DIR, ruta_img)

    if not os.path.exists(ruta):
        print("⚠ Imagen inferior no encontrada:", ruta)
        return

    x = x_cm * cm
    y = y_cm * cm
    w = w_cm * cm
    h = (h_cm * cm) if h_cm else None

    c.drawImage(
        ruta,
        x,
        y,
        width=w,
        height=h,
        preserveAspectRatio=True,  # 🔥 mantiene proporción
        mask="auto"               # 🔥 transparencia PNG
    )
def draw_texto_inferior_izquierdo(
    c,
    texto,
    x_cm=1.5,
    y_cm=1.3,
    size=11,
    color=colors.HexColor("#2E3A3F")
):
    """
    Texto inferior izquierdo elegante y MUY legible

    x_cm → izquierda/derecha
    y_cm → abajo/arriba
    size → tamaño letra
    """

    x = x_cm * cm
    y = y_cm * cm

    # 🔥 fuente súper legible (mejor que cursiva aquí)
    c.setFont("Helvetica-Bold", size)
    c.setFillColor(color)

    c.drawString(x, y, texto)

from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Spacer,
    Flowable, Frame, PageTemplate, BaseDocTemplate,
)



def generar_pdf_cotizacion(
    nota,
    ruta_pdf,
    ruta_logo=None,
    logo_x=5,
    logo_y=12,
    logo_w=10,
    ruta_marco="marco.png",
    marco_x=-9.3,
    marco_y=-10.5,
    marco_w=38,
    marco_h=48,
    tabla_x_cm=2,
    tabla_y_cm=12,
    elements_out=None 
):

    if ruta_pdf:
        os.makedirs(os.path.dirname(ruta_pdf), exist_ok=True)

    width, height = LETTER

    # ======================================================
    # 🔵 FONDO + MARCO + HEADER EN CADA PÁGINA
    # ======================================================
    # ======================================================
    # 🔵 TABLA PRODUCTOS (AUTO PAGINACIÓN)
    # ======================================================

    data = [["Producto", "Cant.", "Precio", "Subtotal"]]

    total_productos = 0

    for p in nota["items"]:
        sub = p["cantidad"] * p["precio"]
        total_productos += sub

        data.append([
            str(p["codigo"]),
            str(p["cantidad"]),
            f"${p['precio']:.2f}",
            f"${sub:.2f}"
        ])

    envio = nota.get("envio", {})
    costo_envio = envio.get("precio", 0)
    total_final = total_productos + costo_envio

    
    
    def dibujar_fondo(canvas, doc):

        draw_fondo_papel(canvas, width, height)
        draw_marco(canvas, width, height, ruta_marco, marco_x, marco_y, marco_w, marco_h)
        draw_logo(canvas, ruta_logo, logo_x, logo_y, logo_w)
    
        draw_info_nota(
            canvas,
            nota["id"],
            nota.get("cliente_id", ""),
            x_cm=11,
            y_cm=23.8,
            ancho_cm=5.8
        )
        draw_info_cliente_envio(
            canvas,
            nota.get("cliente_nombre", ""),
            nota.get("envio", {}).get("paqueteria", ""),
            x_cm=3,     # izquierda/derecha
            y_cm=17.9,    # arriba/abajo
            ancho_cm=6.5
        )
        draw_info_cliente_envio_fechas(
            canvas,
            fecha_base=nota.get("fecha",""),
            x_cm=13,
            y_cm=17.9,
            ancho_cm=16
        )
        draw_texto_elegante(
            canvas,
            texto="¡Gracias por elegirnos!",
            y_cm=16.4,   # 🔥 mueve arriba/abajo aquí
            size=30
        )
        draw_marca_agua(
            canvas,
            width,
            height,
            ruta_img="marca_agua.png",

            escala=1.1,
            x_offset_cm=0,      # mueve horizontal
            y_offset_cm=-3,     # mueve vertical
            alpha=0.08
        )

        0
        canvas.setFont("Helvetica-Oblique", 9)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(
            width/2,
            2*cm,
            "Gracias por su preferencia • Cotización válida por 1 día"
        )
    
    def dibujar_fondo_y_footer(canvas, doc):
        dibujar_fondo(canvas, doc)
        
        draw_totales_fuera_tabla(
            canvas,
            subtotal=doc.total_productos,
            envio=doc.costo_envio,
            total=doc.total_final,
            x_cm=17.8,
            y_cm=3.8
        )

        draw_imagen_inferior(
            canvas,
            ruta_img="mi_imagen.png",
            x_cm=1,
            y_cm=-32,
            w_cm=10
        )
 
        draw_texto_inferior_izquierdo(
            canvas,
            texto="722969020608182169   Jorge Ortiz A.",
            x_cm=3,
            y_cm=4.8,
            size=12
        )


    # ======================================================
    # 🔵 DOCUMENTO CON LÍMITES DEL MARCO
    # ======================================================

    doc = BaseDocTemplate(
        ruta_pdf,
        pagesize=LETTER
    )

    # =============================
    # 🔵 FRAME = ZONA DE LA TABLA
    # =============================
    frame_tabla = Frame(
        x1 = 2*cm,        # margen izquierdo
        y1 = 6*cm,        # desde abajo
        width = width - 4*cm,
        height = 10*cm,   # 🔥 ALTURA LÍMITE DE TABLA
        showBoundary = 0  # pon 1 para debug
    )
            # =========================
        # PIE FIJO (SIEMPRE ABAJO)
        # =========================

    template_unico = PageTemplate(
        id="principal",
        frames=[frame_tabla],
        onPage=dibujar_fondo_y_footer   # ← siempre
    )

    doc.addPageTemplates([template_unico])



    tabla = Table(
        data,
        colWidths=[7*cm, 2*cm, 3*cm, 3*cm],
        repeatRows=1,
        splitByRow=1   # 🔥 permite cortes limpios
    )

    tabla.setStyle(TableStyle([

        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2F4F4F")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONT", (0,0), (-1,0), "Helvetica-Bold", 12),

        ("FONT", (0,1), (-1,-1), "Helvetica", 10),
        ("ALIGN", (1,1), (-1,-1), "CENTER"),

        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#CCCCCC")),
        
       
        ("FONT", (-2,-1), (-1,-1), "Helvetica", 10),
    ]))

    elements = []

    elements.append(tabla)

    
    # ======================================================
    # 🔵 BUILD
    # ======================================================
    doc.total_productos = total_productos
    doc.costo_envio = costo_envio
    doc.total_final = total_final
 
    # 🔥 SI SE USA DESDE PREMIUM, NO CONSTRUYE
    if elements_out is not None:
        elements_out.extend(elements)
        return
 
    # 🔥 COTIZACIÓN NORMAL
    doc.build(elements)




