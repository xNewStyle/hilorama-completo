import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_ENVIOS = os.path.join(BASE_DIR, "envios_config.json")


def cargar_envios():
    if not os.path.exists(ARCHIVO_ENVIOS):
        raise FileNotFoundError("No existe envios_config.json")

    with open(ARCHIVO_ENVIOS, "r", encoding="utf-8") as f:
        return json.load(f)


def calcular_envio(paqueteria, volumetrico_total):
    envios = cargar_envios()
    data = envios.get(paqueteria)

    if not data:
        return 0.0

    # Casos simples (entrega personal / tienda)
    if "tabla" not in data:
        return float(data.get("base", 0))

    tabla = data["tabla"]
    vol = float(volumetrico_total)

    # Buscar el siguiente escalón
    for limite in sorted(map(float, tabla.keys())):
        if vol <= limite:
            return float(tabla[str(int(limite))])

    # Si excede todo
    return float(tabla[str(max(map(int, tabla.keys())))])
