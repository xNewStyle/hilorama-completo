import socket
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter

PRINTER_IP = "192.168.100.71"
PRINTER_PORT = 9100

# 100mm ancho x 150mm alto (VERTICAL REAL)
ANCHO = 800
ALTO = 1200


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
def generar_etiqueta(cliente, nota_id, tipo="DESTINATARIO"):

    img = Image.new("RGB", (ANCHO, ALTO), "white")
    draw = ImageDraw.Draw(img)

    # TIPOGRAFÍAS
    font_logo = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 60)
    font_titulo = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 45)
    font_nombre = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 55)
    font_texto = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 40)
    font_small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 32)

    # Marco exterior
    draw.rectangle((15, 15, ANCHO - 15, ALTO - 15), outline="black", width=3)

    # LOGO
    draw.text((40, 40), "HILORAMA", fill="black", font=font_logo)

    # NOTA esquina superior derecha
    nota_txt = f"Nota #{nota_id}"
    bbox = draw.textbbox((0, 0), nota_txt, font=font_small)
    ancho_txt = bbox[2] - bbox[0]
    draw.text((ANCHO - ancho_txt - 40, 50), nota_txt, fill="black", font=font_small)

    # Línea separadora
    draw.line((30, 130, ANCHO - 30, 130), fill="black", width=2)

    # Título
    draw.text((40, 160), tipo, fill="black", font=font_titulo)

    y = 230

    # ==================================================
    # NOMBRE
    # ==================================================
    if cliente.get("nombre"):
        draw.text((40, y), cliente["nombre"], fill="black", font=font_nombre)
        y += 80

    direccion = cliente.get("direccion", {})

    # ==================================================
    # CALLE + NÚMEROS
    # ==================================================
    calle = direccion.get("calle", "")
    ext = direccion.get("numero_ext", "")
    interior = direccion.get("numero_int", "")

    linea_calle = calle
    if ext:
        linea_calle += f" No. {ext}"
    if interior:
        linea_calle += f" Int. {interior}"

    if linea_calle.strip():
        draw.text((40, y), linea_calle, fill="black", font=font_texto)
        y += 55

    # ==================================================
    # COLONIA
    # ==================================================
    colonia = direccion.get("colonia", "")
    if colonia:
        draw.text((40, y), f"Col. {colonia}", fill="black", font=font_texto)
        y += 55

    # ==================================================
    # CP + MUNICIPIO + ESTADO
    # ==================================================
    cp = direccion.get("codigo_postal", "")
    municipio = direccion.get("municipio", "")
    estado = direccion.get("estado", "")

    ubicacion = []
    if cp:
        ubicacion.append(f"C.P. {cp}")
    if municipio:
        ubicacion.append(municipio)
    if estado:
        ubicacion.append(estado)

    if ubicacion:
        draw.text((40, y), ", ".join(ubicacion), fill="black", font=font_texto)
        y += 55

    # ==================================================
    # TELÉFONO
    # ==================================================
    if cliente.get("telefono"):
        draw.text((40, y), f"Tel: {cliente['telefono']}", fill="black", font=font_texto)
        y += 60

    # Línea separadora
    draw.line((30, y + 10, ANCHO - 30, y + 10), fill="black", width=2)

    # ==================================================
    # REFERENCIA EN RECUADRO
    # ==================================================
    referencia = direccion.get("referencia", "")
    if referencia:
        caja_y = y + 30
        draw.rectangle((40, caja_y, ANCHO - 40, caja_y + 90), outline="black", width=2)
        draw.text((60, caja_y + 25), f"Referencia: {referencia}", fill="black", font=font_small)

    # ==================================================
    # CÓDIGO DE BARRAS DISCRETO
    # ==================================================
    codigo = barcode.get("code128", str(nota_id), writer=ImageWriter())
    codigo_img = codigo.render(writer_options={
        "module_width": 0.2,
        "module_height": 35,
        "font_size": 0,
        "quiet_zone": 1
    })

    codigo_img = codigo_img.resize((350, 120))
    img.paste(codigo_img, (ANCHO - 390, ALTO - 170))

    return img


# ==================================================
# CONVERTIR A TSPL
# ==================================================
def convertir_a_tspl(img):

    img = img.convert("1")

    width, height = img.size

    # Asegurar múltiplo de 8
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
def etiqueta_destinatario(cliente, nota_id):
    img = generar_etiqueta(cliente, nota_id, "DESTINATARIO")
    comando = convertir_a_tspl(img)
    enviar_a_impresora(comando)


def etiqueta_remitente(cliente, nota_id):
    img = generar_etiqueta(cliente, nota_id, "REMITENTE")
    comando = convertir_a_tspl(img)
    enviar_a_impresora(comando)

