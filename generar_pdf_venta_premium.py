

import os
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.platypus import Spacer, Table, Flowable

class FlowableVacio(Flowable):
    def draw(self):
        pass


def draw_bloque_cliente(canvas, nota, x_cm=2, y_cm=5, ancho_cm=14):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors

    direccion = nota.get("direccion", {})

    x = x_cm * cm
    y = y_cm * cm
    w = ancho_cm * cm

    data = [
        ["Calle:", direccion.get("calle", "")],
        ["No. Exterior:", direccion.get("numero_ext", "")],   # 🔥 FIX
        ["No. Interior:", direccion.get("numero_int", "")],   # 🔥 FIX
        ["Colonia:", direccion.get("colonia", "")],
        ["Municipio:", direccion.get("municipio", "")],
        ["Estado:", direccion.get("estado", "")],
        ["Código Postal:", direccion.get("codigo_postal", "")],
        ["Referencia:", direccion.get("referencia", "")]
    ]

    tabla = Table(data, colWidths=[w * 0.35, w * 0.35])

    tabla.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Helvetica", 11),
        ("FONT", (0,0), (0,-1), "Helvetica-Bold", 11),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#2E3A3F")),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("GRID", (0,0), (-1,-1), 0, colors.transparent),
    ]))

    tabla.wrapOn(canvas, w, 1000)
    tabla.drawOn(canvas, x, y)





from reportlab.lib import colors
from reportlab.lib.units import cm

def draw_boton_status_elegante(
    c,
    texto="VER ESTATUS DE MI PAQUETE",
    x_cm=6,
    y_cm=4,
    w_cm=9,
    h_cm=1.4,
    color_fondo="#1E7F5C",
    color_texto=colors.white
):
    """
    Botón elegante tipo premium
    movible y estético
    """

    x = x_cm * cm
    y = y_cm * cm
    w = w_cm * cm
    h = h_cm * cm

    # ================= SOMBRA (fake) =================
    c.setFillColor(colors.HexColor("#000000"))
    c.setFillAlpha(0.15)
    c.roundRect(
        x + 0.1*cm,
        y - 0.1*cm,
        w,
        h,
        10,
        fill=1,
        stroke=0
    )
    c.setFillAlpha(1)

    # ================= BOTÓN =================
    c.setFillColor(colors.HexColor(color_fondo))
    c.roundRect(
        x,
        y,
        w,
        h,
        12,
        fill=1,
        stroke=0
    )

    # ================= TEXTO =================
    c.setFillColor(color_texto)
    c.setFont("Helvetica-Bold", 12)

    c.drawCentredString(
        x + w/2,
        y + h/2 - 4,
        texto
    )



from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle

def draw_bloque_aclaraciones(
    c,
    x_cm=2,
    y_cm=2,
    ancho_cm=14
):
    """
    Bloque de aclaraciones legales
    letra pequeña, elegante y LEGIBLE
    TOTALMENTE MOVIBLE
    """

    x = x_cm * cm
    y = y_cm * cm
    w = ancho_cm * cm

    texto = """
    <b>1.</b> Es obligatorio grabar un video continuo desde la recepción del paquete
    hasta su apertura completa. Sin este video no habrá soluciones.<br/><br/>

    <b>2.</b> El material dañado debe reportarse dentro de las primeras 2 horas posteriores
    a la recepción del paquete, enviando evidencia en video y/o fotografías.
    Pasado este tiempo no aplica garantía.<br/><br/>

    <b>3.</b> Paquetes no recibidos por ausencia, dirección incorrecta o rechazo del cliente
    serán retornados. El cliente deberá cubrir nuevamente el costo del envío.
    El material no es reembolsable.<br/><br/>

    <b>4.</b> Una vez entregado el paquete a la paquetería, no nos hacemos responsables
    por retrasos, extravíos o mal manejo ajeno a nuestro control.
    Apoyamos en el seguimiento, pero la resolución depende de la paquetería.<br/><br/>

    <b>5.</b> Es responsabilidad del cliente proporcionar una dirección completa y correcta.
    Errores en la información pueden generar retrasos o retornos no atribuibles a la tienda.<br/><br/>

    <b>6.</b> No se aceptan cambios ni devoluciones en material usado, cortado o alterado.
    Los colores pueden variar ligeramente dependiendo del dispositivo.
    """

    estilo = ParagraphStyle(
        name="Aclaraciones",
        fontName="Helvetica",
        fontSize=5.5,
        leading=11,
        textColor=colors.HexColor("#374151"),
        alignment=4,   # 🔥 JUSTIFICADO REAL
    )

    parrafo = Paragraph(texto, estilo)

    tabla = Table(
        [[parrafo]],
        colWidths=[w]
    )

    tabla.setStyle(TableStyle([
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),

        # marco elegante
     
    ]))

    tabla.wrapOn(c, w, 200)
    tabla.drawOn(c, x, y)



def draw_bloque_cliente_compacto(
    c,
    nota,
    x_cm=2,
    y_cm=14,
    size_label=12,
    size_texto=12,
    color_label=colors.HexColor("#6B5E4B"),
    color_texto=colors.HexColor("#2E3A3F")
):
    """
    Bloque compacto:

    Cliente: Brenda
    Teléfono: 5578412147
    """

    x = x_cm * cm
    y = y_cm * cm

    cliente = nota.get("cliente_nombre", "")
    telefono = nota.get("telefono", "")

    # ===== CLIENTE =====
    c.setFont("Helvetica-Bold", size_label)
    c.setFillColor(color_label)
    c.drawString(x, y, "Cliente:")

    c.setFont("Helvetica", size_texto)
    c.setFillColor(color_texto)
    c.drawString(x + 2.2*cm, y, cliente)

    # ===== TELÉFONO =====
    c.setFont("Helvetica-Bold", size_label)
    c.setFillColor(color_label)
    c.drawString(x, y - 0.8*cm, "Teléfono:")

    c.setFont("Helvetica", size_texto)
    c.setFillColor(color_texto)
    c.drawString(x + 2.2*cm, y - 0.8*cm, telefono)

from PIL import Image
import tempfile

def draw_comprobante_pagado(
    c,
    nota,
    x_cm=2,
    y_cm=2,
    w_cm=6,
    h_cm=None,
    rotacion=0
):
    """
    Imagen del comprobante de pago
    movible, escalable y rotable
    """

    ruta = nota.get("comprobante")
    if not ruta:
        return

    if not os.path.exists(ruta):
        print("❌ No existe comprobante:", ruta)
        return

    # abrir imagen
    img = Image.open(ruta)

    # rotar si aplica
    if rotacion != 0:
        img = img.rotate(rotacion, expand=True)

    # guardar temporal
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    img.save(tmp.name, "PNG")

    # coordenadas
    x = x_cm * cm
    y = y_cm * cm
    w = w_cm * cm
    h = h_cm * cm if h_cm else None

    # dibujar
    c.drawImage(
        tmp.name,
        x,
        y,
        width=w,
        height=h,
        preserveAspectRatio=True,
        mask="auto"
    )






def dibujar_premium(canvas, doc):

    nota = doc.nota

    width, height = LETTER

    # 🔥 FONDO PREMIUM (AQUÍ)
    draw_fondo_premium(
        canvas,
        width,
        height,
        ruta_fondo="fondo_premium.png",  # ← tu imagen
        x_cm=-15.5,          # mueve izquierda / derecha
        y_cm=-9,          # mueve abajo / arriba
        w_cm=53,       # ancho hoja carta
        h_cm=46,       # alto hoja carta
        alpha=1          # transparencia
    )

    # 🔹 título
    canvas.setFont("Helvetica-Bold", 18)
    canvas.setFillColor(colors.HexColor("#2E3A3F"))
  

    # 🔹 bloque cliente (EL QUE YA HICISTE)
    draw_bloque_cliente(
        canvas,
        nota,
        x_cm=12,     # ← mueve libremente
        y_cm=15,
        ancho_cm=10
    )

    # 🔹 bloque de pago (ejemplo)
    draw_bloque_aclaraciones(
        canvas,
        x_cm=10.8,
        y_cm=7,
        ancho_cm=10
    )


    # 🔹 botón (puede ser texto o PNG)
    draw_boton_status_elegante(
        canvas,
        texto="VER ESTATUS DE MI PAQUETE",
        x_cm=6,
        y_cm=3,
        w_cm=10
    )

    draw_bloque_cliente_compacto(
        canvas,
        nota,
        x_cm=2,     # ← mueve izquierda / derecha
        y_cm=20,    # ← mueve arriba / abajo
    )
    # título, bloques, etc...

    draw_comprobante_pagado(
        canvas,
        nota,
        x_cm=3.5,     # ← mueve izquierda / derecha
        y_cm=-16,     # ← mueve arriba / abajo
        w_cm=4.3,     # ← tamaño
        rotacion=360 # 🔥 gira la imagen
    )



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

def draw_fondo_premium(
    c,
    width,
    height,
    ruta_fondo,
    x_cm=0,
    y_cm=0,
    w_cm=None,
    h_cm=None,
    alpha=1
):
    """
    Fondo premium movible y ajustable

    x_cm, y_cm → posición
    w_cm, h_cm → tamaño (None = tamaño hoja)
    alpha      → transparencia (0–1)
    """

    if not ruta_fondo:
        return

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ruta = os.path.join(BASE_DIR, ruta_fondo)

    if not os.path.exists(ruta):
        print("⚠ Fondo premium no encontrado:", ruta)
        return

    x = x_cm * cm
    y = y_cm * cm

    w = (w_cm * cm) if w_cm else width
    h = (h_cm * cm) if h_cm else height

    c.saveState()
    c.setFillAlpha(alpha)

    c.drawImage(
        ruta,
        x,
        y,
        width=w,
        height=h,
        preserveAspectRatio=False,
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

def generar_pdf_venta_premium(
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
):

    if ruta_pdf:
        os.makedirs(os.path.dirname(ruta_pdf), exist_ok=True)

    width, height = LETTER

    # ================= DATOS =================
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

    # ================= DIBUJOS =================
    def dibujar_cotizacion(canvas, doc):
        draw_fondo_papel(canvas, width, height)
        draw_marco(canvas, width, height, ruta_marco, marco_x, marco_y, marco_w, marco_h)
        draw_logo(canvas, ruta_logo, logo_x, logo_y, logo_w)

        draw_info_nota(canvas, nota["id"], nota.get("cliente_id", ""), 11, 23.8, 5.8)
        draw_info_cliente_envio(canvas, nota.get("cliente_nombre",""),
                                 nota.get("envio",{}).get("paqueteria",""), 3, 17.9, 6.5)
        draw_info_cliente_envio_fechas(canvas, nota.get("fecha",""), 13, 17.9, 16)

        draw_texto_elegante(canvas, "¡Gracias por elegirnos!", 16.4, 30)
        draw_marca_agua(canvas, width, height, "marca_agua.png", 1.1, 0, -3, 0.08)

        draw_totales_fuera_tabla(canvas, total_productos, costo_envio, total_final, 17.8, 3.8)
        draw_imagen_inferior(
            canvas,
            ruta_img="mi_imagen.png",
            x_cm=1,
            y_cm=-32,
            w_cm=10
        )
        draw_texto_inferior_izquierdo(canvas, "722969020608182169   Jorge Ortiz A.", 3, 4.8, 12)
    

    # ================= DOCUMENTO =================
    doc = BaseDocTemplate(ruta_pdf, pagesize=LETTER)

    frame_tabla = Frame(
        2*cm, 6*cm,
        width - 4*cm,
        10*cm,
        showBoundary=0
    )

    frame_blanco = Frame(
        2*cm, 2*cm,
        width - 4*cm,
        height - 4*cm,
        showBoundary=0
    )

    template_cotizacion = PageTemplate(
        id="cotizacion",
        frames=[frame_tabla],
        onPage=dibujar_cotizacion
    )

    template_blanco = PageTemplate(
        id="blanco",
        frames=[frame_blanco],
        onPage=dibujar_premium  #
    )

    doc.addPageTemplates([template_cotizacion, template_blanco])

    # ================= ELEMENTOS =================
    tabla = Table(
        data,
        colWidths=[7*cm, 2*cm, 3*cm, 3*cm],
        repeatRows=1
    )

    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2F4F4F")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONT", (0,0), (-1,0), "Helvetica-Bold", 12),
        ("FONT", (0,1), (-1,-1), "Helvetica", 10),
        ("ALIGN", (1,1), (-1,-1), "CENTER"),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#CCCCCC")),
    ]))

    from reportlab.platypus import PageBreak, NextPageTemplate
    doc.nota = nota

    elements = [
        tabla,
        NextPageTemplate("blanco"),
        PageBreak(),
        FlowableVacio(),
    ]
    

    doc.build(elements)






