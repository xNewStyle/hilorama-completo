import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(BASE_DIR, "pedido_estado.json")



# =====================================================
# 🔵 PARSER ROBUSTO (soporta meses texto y números)
# =====================================================
def parse_fecha(texto):
    """
    Soporta:
    03/02/2026
    3/2/2026
    3/Febrero/2026
    """

    # intento normal dd/mm/yyyy
    try:
        return datetime.strptime(texto, "%d/%m/%Y").date()
    except:
        pass

    # formato con nombre de mes
    meses = {
        "Enero":1,"Febrero":2,"Marzo":3,"Abril":4,"Mayo":5,"Junio":6,
        "Julio":7,"Agosto":8,"Septiembre":9,"Octubre":10,"Noviembre":11,"Diciembre":12
    }

    d, m, y = texto.split("/")

    if m in meses:
        return datetime(int(y), meses[m], int(d)).date()

    raise ValueError("Formato de fecha inválido")


# =====================================================
# 🔵 GUARDAR / CARGAR
# =====================================================
def guardar_pedido(pedido):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(pedido, f)


def cargar_pedido():
    if not os.path.exists(ARCHIVO):
        return None

    with open(ARCHIVO, "r", encoding="utf-8") as f:
        return json.load(f)


# =====================================================
# 🔵 ESTADOS
# =====================================================
def pedido_vencido(pedido):
    if not pedido:
        return False

    hoy = datetime.now().date()
    fin = parse_fecha(pedido["hasta"])   # 🔥 CAMBIO CLAVE

    return hoy > fin


def pedido_por_vencer(pedido):
    if not pedido:
        return False

    hoy = datetime.now().date()
    fin = parse_fecha(pedido["hasta"])   # 🔥 CAMBIO CLAVE

    return (fin - hoy).days == 1
