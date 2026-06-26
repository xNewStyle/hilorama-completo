import socket
import textwrap
import unicodedata
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
from auditoria import registrar_evento
import qrcode

PRINTER_IP = "192.168.100.6"
PRINTER_PORT = 9100

# ==================================================
# TAMAÑO HORIZONTAL REAL (150mm ancho x 100mm alto)
# ==================================================
ANCHO = 1200
ALTO = 800


def enviar_a_impresora(data):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((PRINTER_IP, PRINTER_PORT))
    s.send(data)
    s.close()


# ==================================================
# UTILIDADES DE TEXTO / ETIQUETA
# ==================================================
def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _txt(valor):
    return str(valor or "").strip()


def _sin_acentos(valor):
    valor = _txt(valor).upper()
    return "".join(
        c for c in unicodedata.normalize("NFD", valor)
        if unicodedata.category(c) != "Mn"
    )


def _text_width(draw, texto, font):
    bbox = draw.textbbox((0, 0), texto, font=font)
    return bbox[2] - bbox[0]


def _line_height(draw, font, extra=8):
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return (bbox[3] - bbox[1]) + extra


def _wrap_pixels(draw, texto, font, max_width):
    """Envuelve texto por ancho real en pixeles, no por cantidad fija de letras."""
    texto = _txt(texto)
    if not texto:
        return []

    palabras = texto.split()
    lineas = []
    actual = ""

    for palabra in palabras:
        prueba = palabra if not actual else f"{actual} {palabra}"
        if _text_width(draw, prueba, font) <= max_width:
            actual = prueba
            continue

        if actual:
            lineas.append(actual)
            actual = ""

        # Si una sola palabra es larguísima, partirla para que no se salga.
        if _text_width(draw, palabra, font) <= max_width:
            actual = palabra
        else:
            pedazo = ""
            for ch in palabra:
                prueba_ch = pedazo + ch
                if _text_width(draw, prueba_ch, font) <= max_width:
                    pedazo = prueba_ch
                else:
                    if pedazo:
                        lineas.append(pedazo)
                    pedazo = ch
            actual = pedazo

    if actual:
        lineas.append(actual)

    return lineas


def _dibujar_wrap(draw, texto, x, y, font, max_width, fill="black", max_lines=None, extra=8):
    lineas = _wrap_pixels(draw, texto, font, max_width)

    if max_lines is not None and len(lineas) > max_lines:
        lineas = lineas[:max_lines]
        if lineas:
            ultima = lineas[-1]
            while _text_width(draw, ultima + "...", font) > max_width and len(ultima) > 1:
                ultima = ultima[:-1]
            lineas[-1] = ultima + "..."

    alto = _line_height(draw, font, extra)
    for linea in lineas:
        draw.text((x, y), linea, fill=fill, font=font)
        y += alto
    return y


def _normalizar_envio(envio):
    if not envio:
        return ""
    if isinstance(envio, dict):
        return _txt(envio.get("tipo") or envio.get("paqueteria") or envio.get("empresa") or envio.get("nombre"))
    return _txt(envio)


# ==================================================
# GENERAR ETIQUETA
# ==================================================
def generar_etiqueta(cliente, nota_id, tipo="DESTINATARIO", envio=None):
    img = Image.new("RGB", (ANCHO, ALTO), "white")
    draw = ImageDraw.Draw(img)

    # ================= TIPOGRAFÍAS =================
    font_logo = _font("C:/Windows/Fonts/segoeuib.ttf", 70)
    font_titulo = _font("C:/Windows/Fonts/segoeuib.ttf", 45)
    font_nombre = _font("C:/Windows/Fonts/segoeuib.ttf", 54)
    font_texto = _font("C:/Windows/Fonts/segoeui.ttf", 38)
    font_small = _font("C:/Windows/Fonts/segoeui.ttf", 28)
    font_badge = _font("C:/Windows/Fonts/segoeuib.ttf", 28)

    # ================= MARCO =================
    draw.rectangle((20, 20, ANCHO - 20, ALTO - 20), outline="black", width=3)

    # ================= LOGO =================
    draw.text((60, 50), "HILORAMA", fill="black", font=font_logo)

    # ================= NOTA SUPERIOR DERECHA =================
    nota_txt = f"Nota #{nota_id}"
    bbox = draw.textbbox((0, 0), nota_txt, font=font_small)
    ancho_txt = bbox[2] - bbox[0]
    draw.text((ANCHO - ancho_txt - 60, 60), nota_txt, fill="black", font=font_small)

    draw.line((50, 150, ANCHO - 50, 150), fill="black", width=2)

    # ================= TÍTULO =================
    draw.text((60, 180), tipo, fill="black", font=font_titulo)

    # ================= PAQUETERÍA DINÁMICA =================
    paq_original = _normalizar_envio(envio)
    paq = _sin_acentos(paq_original)

    if paq:
        color_map = {
            "ESTAFETA": (255, 140, 0),
            "FEDEX": (102, 0, 153),
            "DHL": (255, 204, 0),
            "CORREOS DE MEXICO": (0, 102, 204),
            "SEPOMEX": (0, 102, 204),
            "ENTREGA PERSONAL": (0, 153, 0),
            "EN TIENDA": (120, 120, 120),
        }

        color = (0, 0, 0)
        for clave, c in color_map.items():
            if clave in paq:
                color = c
                break

        box_x1 = ANCHO - 450
        box_y1 = 180
        box_x2 = ANCHO - 50
        box_y2 = 240
        draw.rectangle((box_x1, box_y1, box_x2, box_y2), fill=color)

        etiqueta_paq = paq_original.upper()
        if len(etiqueta_paq) > 24:
            etiqueta_paq = etiqueta_paq[:24] + "..."

        bbox = draw.textbbox((0, 0), etiqueta_paq, font=font_badge)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = box_x1 + ((box_x2 - box_x1) - text_width) // 2
        text_y = box_y1 + ((box_y2 - box_y1) - text_height) // 2
        draw.text((text_x, text_y), etiqueta_paq, fill="white", font=font_badge)

    # ==================================================
    # DATOS DEL CLIENTE
    # ==================================================
    y = 255
    x = 60
    max_ancho_texto = ANCHO - 120

    nombre = _txt(cliente.get("nombre"))
    if nombre:
        # Antes el nombre podía empujar/encimar direcciones largas.
        # Ahora se envuelve por ancho real.
        y = _dibujar_wrap(draw, nombre, x, y, font_nombre, max_ancho_texto, max_lines=2, extra=6)
        y += 8

    direccion = cliente.get("direccion", {}) or {}

    # Aceptar nombres alternos por si algún cliente fue guardado distinto.
    calle = _txt(direccion.get("calle") or direccion.get("direccion") or direccion.get("domicilio"))
    numero_ext = _txt(direccion.get("numero_ext") or direccion.get("num_ext") or direccion.get("exterior"))
    numero_int = _txt(direccion.get("numero_int") or direccion.get("num_int") or direccion.get("interior"))
    colonia = _txt(direccion.get("colonia") or direccion.get("col"))
    municipio = _txt(direccion.get("municipio") or direccion.get("alcaldia") or direccion.get("delegacion") or direccion.get("ciudad"))
    estado = _txt(direccion.get("estado"))
    cp = _txt(direccion.get("codigo_postal") or direccion.get("cp") or direccion.get("c_p"))
    referencia = _txt(direccion.get("referencia") or direccion.get("referencias"))

    partes = []
    if calle:
        partes.append(calle)
    if numero_ext:
        partes.append(f"No. {numero_ext}")
    if numero_int:
        partes.append(f"Int. {numero_int}")

    if partes:
        y = _dibujar_wrap(draw, " ".join(partes), x, y, font_texto, max_ancho_texto, max_lines=2, extra=5)
        y += 2

    if colonia:
        y = _dibujar_wrap(draw, f"Col. {colonia}", x, y, font_texto, max_ancho_texto, max_lines=2, extra=5)
        y += 2

    ubicacion = []
    if municipio:
        ubicacion.append(municipio)
    if estado:
        ubicacion.append(estado)
    if cp:
        ubicacion.append(f"C.P. {cp}")

    if ubicacion:
        y = _dibujar_wrap(draw, " • ".join(ubicacion), x, y, font_texto, max_ancho_texto, max_lines=2, extra=5)
        y += 4

    telefono = _txt(cliente.get("telefono") or cliente.get("celular"))
    if telefono:
        y = _dibujar_wrap(draw, f"Tel: {telefono}", x, y, font_texto, max_ancho_texto, max_lines=1, extra=5)
        y += 8

    # Línea separadora dinámica, sin encimar texto.
    linea_y = min(y + 5, ALTO - 270)
    draw.line((50, linea_y, ANCHO - 50, linea_y), fill="black", width=2)

    # ==================================================
    # REFERENCIA EN RECUADRO CONTROLADO
    # ==================================================
    caja_y = linea_y + 22
    qr_x = ANCHO - 300
    qr_y = ALTO - 250

    if referencia:
        caja_x1 = 60
        caja_x2 = qr_x - 45
        caja_alto = min(125, ALTO - caja_y - 55)
        draw.rectangle((caja_x1, caja_y, caja_x2, caja_y + caja_alto), outline="black", width=2)

        y_ref = caja_y + 12
        _dibujar_wrap(
            draw,
            f"Ref: {referencia}",
            caja_x1 + 15,
            y_ref,
            font_small,
            caja_x2 - caja_x1 - 30,
            max_lines=3,
            extra=4,
        )

    # ==================================================
    # CÓDIGO QR DISCRETO (ESQUINA INFERIOR DERECHA)
    # ==================================================
    qr = qrcode.QRCode(
        version=2,
        box_size=4,
        border=2
    )
    qr.add_data(str(nota_id))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img.paste(qr_img, (qr_x, qr_y))

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

    tspl = (
        "SIZE 100 mm,150 mm\n"
        "GAP 3 mm,0\n"
        "DENSITY 8\n"
        "DIRECTION 0\n"
        "REFERENCE 0,0\n"
        "CLS\n"
        f"BITMAP 0,0,{bytes_per_row},{height},0,"
    ).encode()

    return tspl + bitmap_data + b"\nPRINT 1,1\n"


# ==================================================
# FUNCIONES PÚBLICAS
# ==================================================
def etiqueta_destinatario(cliente, nota_id, envio=None):
    img = generar_etiqueta(cliente, nota_id, "DESTINATARIO", envio)
    return convertir_a_tspl(img)


def etiqueta_remitente(nota_id, mis_datos):
    cliente = {
        "nombre": mis_datos["nombre"],
        "telefono": mis_datos.get("telefono", ""),
        "direccion": mis_datos["direccion"]
    }

    img = generar_etiqueta(cliente, nota_id, "REMITENTE")
    return convertir_a_tspl(img)
