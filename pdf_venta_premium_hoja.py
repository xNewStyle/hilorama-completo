from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Spacer, PageBreak, Table, TableStyle
)
from reportlab.lib import colors
import os

# ======================================================
# 🟣 HOJA EXTRA PREMIUM (TODO MOVIBLE)
# ======================================================

def hoja_premium_info(nota):
    elements = []

    elements.append(Spacer(1, 1*cm))

    # ---------- TÍTULO ----------
    titulo = Table(
        [["Información de Entrega y Pago"]],
        colWidths=[16*cm]
    )
    titulo.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Helvetica-Bold", 18),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.HexColor("#2E3A3F")),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
    ]))
    elements.append(titulo)

    # ---------- DATOS CLIENTE ----------
    datos_cliente = Table(
        [
            ["Cliente:", nota.get("cliente_nombre", "")],
            ["Dirección:", nota.get("direccion", "")],
            ["Teléfono:", nota.get("telefono", "")],
            ["Correo:", nota.get("correo", "")]
        ],
        colWidths=[4*cm, 12*cm]
    )
    datos_cliente.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("FONT", (0,0), (-1,-1), "Helvetica", 11),
        ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    elements.append(datos_cliente)

    elements.append(Spacer(1, 1*cm))

    # ---------- DATOS DE PAGO ----------
    pago = Table(
        [
            ["Banco:", "BBVA"],
            ["Titular:", "Jorge Ortiz A."],
            ["Cuenta:", "722969020608182169"],
            ["Referencia:", f"Nota {nota['id']}"]
        ],
        colWidths=[4*cm, 12*cm]
    )
    pago.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("FONT", (0,0), (-1,-1), "Helvetica", 11),
        ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke),
    ]))
    elements.append(pago)

    elements.append(Spacer(1, 1*cm))

    # ---------- TÉRMINOS ----------
    terminos = Table(
        [[
            "Al confirmar esta compra aceptas los términos y condiciones. "
            "El envío es responsabilidad de la paquetería seleccionada."
        ]],
        colWidths=[16*cm]
    )
    terminos.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Helvetica-Oblique", 10),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.grey),
    ]))
    elements.append(terminos)

    elements.append(Spacer(1, 1.2*cm))

    # ---------- BOTÓN (TEXTO O PNG) ----------
    boton = Table(
        [["VER ESTATUS DE MI PAQUETE"]],
        colWidths=[8*cm]
    )
    boton.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1B5E20")),
        ("TEXTCOLOR", (0,0), (-1,-1), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("FONT", (0,0), (-1,-1), "Helvetica-Bold", 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 10),
    ]))
    elements.append(boton)

    return elements


# ======================================================
# 🟣 PDF VENTA PREMIUM
# ======================================================

def generar_pdf_venta_premium(
    nota,
    ruta_pdf,
    ruta_logo=None,
    generar_pdf_cotizacion_func=None
):
    if generar_pdf_cotizacion_func is None:
        raise ValueError("Debes pasar generar_pdf_cotizacion_func")

    os.makedirs(os.path.dirname(ruta_pdf), exist_ok=True)

    width, height = LETTER

    doc = BaseDocTemplate(
        ruta_pdf,
        pagesize=LETTER,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    frame = Frame(
        2*cm, 2*cm,
        width - 4*cm,
        height - 4*cm
    )

    template = PageTemplate(id="premium", frames=[frame])
    doc.addPageTemplates([template])

    elements = []

    # 🟢 HOJA 1 → COTIZACIÓN ORIGINAL
    generar_pdf_cotizacion_func(
        nota=nota,
        ruta_pdf=None,
        ruta_logo=ruta_logo,
        elements_out=elements
    )

    # 🟣 HOJA 2 → PREMIUM
    elements.append(PageBreak())
    elements.extend(hoja_premium_info(nota))

    doc.build(elements)
