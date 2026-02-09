import json, os, math

ARCHIVO = "envios_data.json"

def cargar_envios():
    if not os.path.exists(ARCHIVO):
        return {}
    with open(ARCHIVO, "r", encoding="utf-8") as f:
        return json.load(f)


def calcular_envio(paqueteria, peso_volumetrico):
    envios = cargar_envios()
    tabla = envios.get(paqueteria, {}).get("volumetrico", {})

    if not tabla:
        return 0

    peso_volumetrico = math.ceil(peso_volumetrico)

    rangos = sorted(int(k) for k in tabla.keys())

    for r in rangos:
        if peso_volumetrico <= r:
            return tabla[str(r)]

    return tabla[str(rangos[-1])]  # máximo
