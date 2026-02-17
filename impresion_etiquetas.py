import socket
import textwrap
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter


PRINTER_IP = "192.168.100.71"
PRINTER_PORT = 9100

# ==================================================
# TAMAÑO HORIZONTAL REAL (150mm ancho x 100mm alto)
# ==================================================
ANCHO = 1200   # más ancho
ALTO = 800     # menos alto


# ==================================================
# ENVIAR A IMPRESORA
# ==================================================
def enviar_a_impresora(data):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((PRINTER_IP, PRINTER_PORT))
    s.send(data)
    s.close()


# ==================================================
# GENERAR ETIQUETA
# ==================================================
def generar_etiqueta(cliente, nota_id, tipo="DESTINATARIO", envio=None):

    
    img = Image.new("RGB", (ANCHO, ALTO), "white")
    draw = ImageDraw.Draw(img)

    # ================= TIPOGRAFÍAS =================
    font_logo = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 70)
    font_titulo = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 45)
    font_nombre = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 60)
    font_texto = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 42)
    font_small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30)

    # ================= MARCO =================
    draw.rectangle((20, 20, ANCHO - 20, ALTO - 20), outline="black", width=3)

    # ================= LOGO =================
    draw.text((60, 50), "HILORAMA", fill="black", font=font_logo)

    # ================= NOTA SUPERIOR DERECHA =================
    nota_txt = f"Nota #{nota_id}"
    bbox = draw.textbbox((0, 0), nota_txt, font=font_small)
    ancho_txt = bbox[2] - bbox[0]
    draw.text((ANCHO - ancho_txt - 60, 60), nota_txt, fill="black", font=font_small)

    # Línea superior
    draw.line((50, 150, ANCHO - 50, 150), fill="black", width=2)

    # ================= TÍTULO =================
    draw.text((60, 180), tipo, fill="black", font=font_titulo)

    y = 250
    # ================= PAQUETERÍA DINÁMICA =================
    paq = None

    if envio:
        paq = envio.get("tipo") or envio.get("paqueteria")

    if paq:
        paq = paq.upper()


        color_map = {
            "ESTAFETA": (255, 140, 0),
            "FEDEX": (102, 0, 153),
            "DHL": (255, 204, 0),
            "CORREOS DE MEXICO": (0, 102, 204),
            "ENTREGA PERSONAL": (0, 153, 0),
            "EN TIENDA": (120, 120, 120)
        }

        color = color_map.get(paq, (0, 0, 0))

        box_x1 = ANCHO - 450
        box_y1 = 180
        box_x2 = ANCHO - 50
        box_y2 = 240

        draw.rectangle((box_x1, box_y1, box_x2, box_y2), fill=color)

        # Centrar texto
        bbox = draw.textbbox((0, 0), paq, font=font_small)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        text_x = box_x1 + ((box_x2 - box_x1) - text_width) // 2
        text_y = box_y1 + ((box_y2 - box_y1) - text_height) // 2

        draw.text(
            (text_x, text_y),
            paq,
            fill="white",
            font=font_small
        )



    # ==================================================
    # NOMBRE
    # ==================================================
    if cliente.get("nombre"):
        draw.text((60, y), cliente["nombre"], fill="black", font=font_nombre)
        y += 85

    direccion = cliente.get("direccion", {})

    # ==================================================
    # CALLE + NÚMEROS BIEN ORDENADO
    # ==================================================
    partes = []

    if direccion.get("calle"):
        partes.append(direccion.get("calle"))

    if direccion.get("numero_ext"):
        partes.append(f"No. {direccion.get('numero_ext')}")

    if direccion.get("numero_int"):
        partes.append(f"Int. {direccion.get('numero_int')}")

    if partes:
        draw.text((60, y), " ".join(partes), fill="black", font=font_texto)
        y += 55

    # ==================================================
    # COLONIA
    # ==================================================
    if direccion.get("colonia"):
        draw.text((60, y), f"Col. {direccion.get('colonia')}", fill="black", font=font_texto)
        y += 55

    # ==================================================
    # UBICACIÓN COMPLETA
    # ==================================================
    ubicacion = []

    if direccion.get("municipio"):
        ubicacion.append(direccion.get("municipio"))

    if direccion.get("estado"):
        ubicacion.append(direccion.get("estado"))

    if direccion.get("codigo_postal"):
        ubicacion.append(f"C.P. {direccion.get('codigo_postal')}")

    if ubicacion:
        draw.text((60, y), " • ".join(ubicacion), fill="black", font=font_texto)
        y += 60

    # ==================================================
    # TELÉFONO
    # ==================================================
    if cliente.get("telefono"):
        draw.text((60, y), f"Tel: {cliente['telefono']}", fill="black", font=font_texto)
        y += 70

    # Línea separadora dinámica
    draw.line((50, y + 10, ANCHO - 50, y + 10), fill="black", width=2)

    # ==================================================
    # REFERENCIA EN RECUADRO CONTROLADO
    # ==================================================
    referencia = direccion.get("referencia", "")

    if referencia:
        caja_y = y + 30
        caja_alto = 90

        draw.rectangle((60, caja_y, 760, caja_y + caja_alto), outline="black", width=2)

        texto_ref = textwrap.fill(referencia, width=40)

        draw.text(
            (75, caja_y + 20),
            texto_ref,
            fill="black",
            font=font_small
        )

    # ==================================================
    # CÓDIGO DE BARRAS DISCRETO (ESQUINA INFERIOR DERECHA)
    # ==================================================
    codigo = barcode.get("code128", str(nota_id), writer=ImageWriter())
    codigo_img = codigo.render(writer_options={
        "module_width": 0.18,
        "module_height": 30,
        "font_size": 0,
        "quiet_zone": 1
    })

    codigo_img = codigo_img.resize((320, 100))
    img.paste(codigo_img, (ANCHO - 380, ALTO - 160))

    return img
    


# ==================================================
# CONVERTIR A TSPL (HORIZONTAL REAL)
# ==================================================
def convertir_a_tspl(img):
    img = img.rotate(90, expand=True)
    img = img.convert("1")

    width, height = img.size

    if width % 8 != 0:
        new_width = width + (8 - width % 8)
        new_img = Image.new("1", (new_width, height), 1)
        new_img.paste(img, (0, 0))
        img = new_img
        width = new_width

    bytes_per_row = width // 8
    bitmap_data = img.tobytes()

    tspl = f"""
SIZE 100 mm,150 mm
GAP 3 mm,0
DENSITY 8
DIRECTION 0
REFERENCE 0,0
CLS
BITMAP 0,0,{bytes_per_row},{height},0,
""".encode()

    return tspl + bitmap_data + b"\nPRINT 1\n"


# ==================================================
# FUNCIONES PÚBLICAS
# ==================================================
def etiqueta_destinatario(cliente, nota_id, envio=None):
    img = generar_etiqueta(cliente, nota_id, "DESTINATARIO", envio)
    comando = convertir_a_tspl(img)
    enviar_a_impresora(comando)


def etiqueta_remitente(nota_id):
    mis_datos = obtener_mis_datos()

    cliente = {
        "nombre": mis_datos["nombre"],
        "direccion": {
            "calle": mis_datos["calle"],
            "colonia": mis_datos["colonia"],
            "municipio": mis_datos["ciudad"],
            "estado": "",
            "codigo_postal": mis_datos["cp"]
        },
        "telefono": ""
    }

    img = generar_etiqueta(cliente, nota_id, "REMITENTE")
    comando = convertir_a_tspl(img)
    enviar_a_impresora(comando)

