import pytesseract
import os
from PIL import Image, ImageOps, ImageFilter


# ================= CONFIG TESSERACT =================

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR\tessdata"


# ================= PREPROCESADO =================

def _mejorar_imagen(img):
    """
    Mejora contraste y nitidez para OCR más preciso
    """
    img = img.convert("L")           # gris
    img = ImageOps.autocontrast(img) # contraste automático
    img = img.filter(ImageFilter.SHARPEN)
    return img


# ================= API =================

def leer_pedido_desde_imagen(ruta):
    img = Image.open(ruta)

    img = _mejorar_imagen(img)

    texto = pytesseract.image_to_string(
        img,
        lang="spa",
        config="--oem 3 --psm 6"
    )

    return texto.strip()

