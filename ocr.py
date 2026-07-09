import os
import shutil
from pathlib import Path
from PIL import Image, ImageOps, ImageFilter


# ================= CONFIG TESSERACT =================

OCR_UNAVAILABLE_MESSAGE = "OCR no disponible. Instala Tesseract o configura TESSERACT_CMD."


class OCRNoDisponibleError(RuntimeError):
    pass


def _resolver_tesseract_cmd():
    configurado = os.environ.get("TESSERACT_CMD", "").strip()
    if configurado:
        ruta_configurada = Path(configurado)
        if ruta_configurada.exists():
            return str(ruta_configurada)

        encontrado = shutil.which(configurado)
        if encontrado:
            return encontrado

        raise OCRNoDisponibleError(OCR_UNAVAILABLE_MESSAGE)

    encontrado = shutil.which("tesseract")
    if encontrado:
        return encontrado

    raise OCRNoDisponibleError(OCR_UNAVAILABLE_MESSAGE)


def _cargar_pytesseract():
    try:
        import pytesseract
    except Exception as exc:
        raise OCRNoDisponibleError(OCR_UNAVAILABLE_MESSAGE) from exc

    pytesseract.pytesseract.tesseract_cmd = _resolver_tesseract_cmd()
    return pytesseract


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
    pytesseract = _cargar_pytesseract()
    img = Image.open(ruta)

    img = _mejorar_imagen(img)

    texto = pytesseract.image_to_string(
        img,
        lang="spa",
        config="--oem 3 --psm 6"
    )

    return texto.strip()

