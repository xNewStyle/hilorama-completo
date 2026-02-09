# ventas/ventas_logic.py
from tkinter import messagebox, simpledialog
from core.almacen_api import (
    obtener_stock,
    descontar_stock,
    obtener_precio_venta,
    es_stock_bajo,
    obtener_producto_por_codigo
)

PASSWORD_OVERRIDE = "12587987521"

def validar_stock(marca, hilo, color, cantidad):
    stock = obtener_stock(marca, hilo, color)

    if cantidad <= stock:
        return True

    faltante = cantidad - stock
    resp = messagebox.askyesno(
        "Stock insuficiente",
        f"Stock disponible: {stock}\n"
        f"Intentas vender: {cantidad}\n"
        f"Faltan: {faltante}\n\n¿Deseas continuar?"
    )

    if not resp:
        return False

    pwd = simpledialog.askstring("Autorización", "Contraseña:", show="*")
    return pwd == PASSWORD_OVERRIDE


def aplicar_venta(marca, hilo, color, cantidad):
    descontar_stock(
        marca,
        hilo,
        color,
        cantidad,
        override=True
    )

def calcular_volumetrico_total(items):
    total = 0.0
    for i in items:
        prod = obtener_producto_por_codigo(i["codigo"])
        if not prod:
            continue

        vol = prod.get("volumetrico", 0)
        total += vol * i["cantidad"]

    return round(total, 2)
