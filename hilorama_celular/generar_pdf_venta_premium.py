

import os
import io
import base64
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.platypus import Spacer, Table, Flowable

class FlowableVacio(Flowable):
    def draw(self):
        pass


def draw_bloque_cliente(canvas, nota, x_cm=2, y_cm=20.7, ancho_cm=9.2):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    direccion = nota.get("direccion", {})

    x = x_cm * cm
    top = y_cm * cm
    w = ancho_cm * cm

    label_style = ParagraphStyle(
        "DireccionLabel",
        fontName="Helvetica-Bold",
        fontSize=8.7,
        leading=10.2,
        textColor=colors.HexColor("#2E3A3F"),
    )
    value_style = ParagraphStyle(
        "DireccionValue",
        fontName="Helvetica",
        fontSize=8.7,
        leading=10.2,
        textColor=colors.HexColor("#2E3A3F"),
        wordWrap="CJK",
    )

    def parrafo(valor, estilo):
        texto = escape(str(valor or "")).replace("\n", "<br/>")
        return Paragraph(texto or " ", estilo)

    filas = [
        ("Calle:", direccion.get("calle", "")),
        ("No. Exterior:", direccion.get("numero_ext", "")),
        ("No. Interior:", direccion.get("numero_int", "")),
        ("Colonia:", direccion.get("colonia", "")),
        ("Municipio:", direccion.get("municipio", "")),
        ("Estado:", direccion.get("estado", "")),
        ("Código Postal:", direccion.get("codigo_postal", "")),
        ("Referencia:", direccion.get("referencia", "")),
    ]
    data = [[parrafo(label, label_style), parrafo(value, value_style)] for label, value in filas]

    label_width = 3.2 * cm
    tabla = Table(data, colWidths=[label_width, w - label_width], hAlign="LEFT")

    tabla.setStyle(TableStyle([
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#2E3A3F")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (0,-1), 8),
        ("RIGHTPADDING", (1,0), (1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1.5),
        ("TOPPADDING", (0,0), (-1,-1), 1.5),
        ("GRID", (0,0), (-1,-1), 0, colors.transparent),
    ]))

    _, table_height = tabla.wrapOn(canvas, w, 1000)
    tabla.drawOn(canvas, x, top - table_height)





from reportlab.lib import colors
from reportlab.lib.units import cm

def draw_boton_status_elegante(
    c,
    nota_id,
    texto="VER ESTATUS DE MI PAQUETE",
    x_cm=6,
    y_cm=4,
    w_cm=9,
    h_cm=1.4,
    color_fondo="#1E7F5C",
    color_texto=colors.white
):

    x = x_cm * cm
    y = y_cm * cm
    w = w_cm * cm
    h = h_cm * cm

    # ================= SOMBRA =================
    c.setFillColor(colors.HexColor("#000000"))
    c.setFillAlpha(0.15)
    c.roundRect(x + 0.1*cm, y - 0.1*cm, w, h, 10, fill=1, stroke=0)
    c.setFillAlpha(1)

    # ================= BOTÓN =================
    c.setFillColor(colors.HexColor(color_fondo))
    c.roundRect(x, y, w, h, 12, fill=1, stroke=0)

    # ================= TEXTO =================
    c.setFillColor(color_texto)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(x + w/2, y + h/2 - 4, texto)

    # ================= LINK REAL =================
    link_url = f"https://hilorama-completo.onrender.com/seguimiento/{nota_id}"

    c.linkURL(
        link_url,
        (x, y, x + w, y + h),
        relative=0
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
        leading=9.5,
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


def _abrir_imagen_comprobante(nota, rotacion=0):
    referencia = nota.get("comprobante")
    if not referencia:
        return None

    try:
        if isinstance(referencia, str) and referencia.startswith("data:image"):
            raw = referencia.split(",", 1)[1] if "," in referencia else referencia
            imagen = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            candidatos = (
                referencia,
                os.path.join(base_dir, str(referencia)),
                os.path.abspath(str(referencia)),
            )
            ruta = next((ruta for ruta in candidatos if ruta and os.path.exists(ruta)), None)
            if not ruta:
                return None
            imagen = Image.open(ruta).convert("RGB")
        imagen.load()
    except Exception:
        return None

    if rotacion:
        imagen = imagen.rotate(rotacion, expand=True)
    return imagen


def _ajustar_imagen_en_caja(image_width, image_height, box_x, box_y, box_width, box_height):
    if image_width <= 0 or image_height <= 0 or box_width <= 0 or box_height <= 0:
        return box_x, box_y, 0, 0
    scale = min(box_width / image_width, box_height / image_height)
    width = image_width * scale
    height = image_height * scale
    x = box_x + (box_width - width) / 2
    y = box_y + (box_height - height) / 2
    return x, y, width, height

def draw_comprobante_pagado(
    c,
    nota,
    x_cm=1.7,
    y_cm=7.8,
    w_cm=7.5,
    h_cm=7.6,
    rotacion=0,
    destino_zoom=None,
):
    """Dibuja una vista previa centrada que nunca sale de su caja."""
    from reportlab.lib.utils import ImageReader

    img = _abrir_imagen_comprobante(nota, rotacion=rotacion)
    if img is None:
        return False

    x = x_cm * cm
    y = y_cm * cm
    width = w_cm * cm
    height = h_cm * cm
    inner_x = x + 0.28 * cm
    inner_y = y + 0.62 * cm
    inner_width = width - 0.56 * cm
    inner_height = height - 1.55 * cm
    image_x, image_y, image_width, image_height = _ajustar_imagen_en_caja(
        img.width,
        img.height,
        inner_x,
        inner_y,
        inner_width,
        inner_height,
    )

    c.saveState()
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#D9C99F"))
    c.setLineWidth(0.8)
    c.roundRect(x, y, width, height, 7, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#2E3A3F"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x + width / 2, y + height - 0.48 * cm, "Comprobante de pago")
    c.drawImage(
        ImageReader(img),
        image_x,
        image_y,
        width=image_width,
        height=image_height,
        preserveAspectRatio=True,
        mask="auto",
    )
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#6B7280"))
    footer = "Haz clic para ampliar" if destino_zoom else "Comprobante centrado"
    c.drawCentredString(x + width / 2, y + 0.24 * cm, footer)
    if destino_zoom:
        c.linkRect(
            "Abrir comprobante ampliado",
            destino_zoom,
            Rect=(x, y, x + width, y + height),
            relative=0,
            thickness=0,
        )
    c.restoreState()
    return True


def draw_comprobante_ampliado(c, nota, destino_regreso="detalle_venta"):
    """Crea una pagina exclusiva para zoom y desplazamiento en el visor PDF."""
    from reportlab.lib.utils import ImageReader

    width, height = LETTER
    c.bookmarkPage("comprobante_full")
    c.setFillColor(colors.HexColor("#F7F4EC"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#2E3A3F"))
    c.setFont("Helvetica-Bold", 17)
    c.drawCentredString(width / 2, height - 1.35 * cm, "Comprobante de pago")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#6B7280"))
    c.drawCentredString(
        width / 2,
        height - 1.85 * cm,
        "Amplia esta pagina con el zoom del visor para revisar los detalles.",
    )

    box_x = 1.4 * cm
    box_y = 1.8 * cm
    box_width = width - 2.8 * cm
    box_height = height - 4.4 * cm
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#D9C99F"))
    c.roundRect(box_x, box_y, box_width, box_height, 9, fill=1, stroke=1)

    img = _abrir_imagen_comprobante(nota)
    if img is not None:
        image_x, image_y, image_width, image_height = _ajustar_imagen_en_caja(
            img.width,
            img.height,
            box_x + 0.4 * cm,
            box_y + 0.4 * cm,
            box_width - 0.8 * cm,
            box_height - 0.8 * cm,
        )
        c.drawImage(
            ImageReader(img),
            image_x,
            image_y,
            width=image_width,
            height=image_height,
            preserveAspectRatio=True,
            mask="auto",
        )
    else:
        c.setFillColor(colors.HexColor("#6B7280"))
        c.setFont("Helvetica", 11)
        c.drawCentredString(width / 2, height / 2, "No fue posible cargar el comprobante.")

    c.setFillColor(colors.HexColor("#1E7F5C"))
    c.setFont("Helvetica-Bold", 9)
    regreso = "Volver a informacion de entrega"
    c.drawString(1.4 * cm, 0.9 * cm, regreso)
    c.linkRect(
        regreso,
        destino_regreso,
        Rect=(1.4 * cm, 0.65 * cm, 7.2 * cm, 1.2 * cm),
        relative=0,
        thickness=0,
    )





def dibujar_premium(canvas, doc):

    nota = doc.nota

    width, height = LETTER
    canvas.bookmarkPage("detalle_venta")

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
        x_cm=11.5,
        y_cm=20.7,
        ancho_cm=9.2,
    )

    # 🔹 bloque de pago (ejemplo)
    draw_bloque_aclaraciones(
        canvas,
        x_cm=10.8,
        y_cm=6.6,
        ancho_cm=10
    )


    # 🔹 botón (puede ser texto o PNG)
    draw_boton_status_elegante(
        canvas,
        nota["id"],   # 👈 PASAMOS ID
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
        x_cm=1.7,
        y_cm=7.8,
        w_cm=7.5,
        h_cm=7.6,
        rotacion=0,
        destino_zoom="comprobante_full" if nota.get("comprobante") else None,
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

    rango = ""

    if fecha_base:
        try:
            fecha_base = str(fecha_base).split(" ")[0]

            # 🔥 Detectar formato automáticamente
            if "-" in fecha_base:
                f = datetime.strptime(fecha_base, "%Y-%m-%d")
            else:
                f = datetime.strptime(fecha_base, "%d/%m/%Y")

            entrega = f + timedelta(days=2)

            rango = f"{f.strftime('%d/%m/%Y')} - {entrega.strftime('%d/%m/%Y')}"

        except Exception as e:
            print("Error fecha:", e)
            rango = fecha_base

    x = x_cm * cm
    y = y_cm * cm
    w = ancho_cm * cm

    data = [
        ["Fecha Estimada de Envío:"],
        [rango]
    ]

    tabla = Table(data, colWidths=[w])

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
    data = [["Hilo", "Color", "Código", "Cant.", "Precio", "Subtotal"]]
    total_productos = 0

    for p in nota["items"]:
        sub = p["cantidad"] * p["precio"]
        total_productos += sub

        data.append([
            str(p.get("hilo", "")),      # 🔥 hilo
            str(p.get("color", "")),     # 🔥 color
            str(p["codigo"]),            # código
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

    def dibujar_comprobante(canvas, doc):
        draw_comprobante_ampliado(canvas, nota)
    

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

    template_comprobante = PageTemplate(
        id="comprobante",
        frames=[frame_blanco],
        onPage=dibujar_comprobante,
    )

    doc.addPageTemplates([template_cotizacion, template_blanco, template_comprobante])

    # ================= ELEMENTOS =================
    tabla = Table(
        data,
        colWidths=[3*cm, 3*cm, 2.5*cm, 2*cm, 2.5*cm, 2.5*cm],
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
    if nota.get("comprobante"):
        elements.extend([
            NextPageTemplate("comprobante"),
            PageBreak(),
            FlowableVacio(),
        ])
    

    doc.build(elements)
