import json
import os
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_ENVIOS = os.path.join(BASE_DIR, "envios_config.json")


def cargar_envios():
    if not os.path.exists(ARCHIVO_ENVIOS):
        raise FileNotFoundError("No existe envios_config.json")

    with open(ARCHIVO_ENVIOS, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalizar_envio(envio):
    if isinstance(envio, dict):
        return envio
    if isinstance(envio, str):
        try:
            valor = json.loads(envio)
            return valor if isinstance(valor, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _numero(valor, default=0.0):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def requiere_precio_manual(paqueteria):
    data = cargar_envios().get(str(paqueteria or "").strip()) or {}
    return bool(data.get("precio_manual"))


def es_envio_gratis(envio):
    envio = _normalizar_envio(envio)
    valor = envio.get("gratis", envio.get("envio_gratis", False))
    if isinstance(valor, str):
        valor = valor.strip().lower() in {"1", "true", "si", "sí", "yes"}
    if valor:
        return True

    tipo = str(envio.get("tipo") or envio.get("paqueteria") or "").strip().upper()
    return tipo in {"ENVIO GRATIS", "ENVÍO GRATIS"}


def formatear_costo_envio(envio, con_etiqueta=False):
    envio = _normalizar_envio(envio)
    if es_envio_gratis(envio):
        return "Envío gratis"
    precio = _numero(envio.get("precio"))
    texto = f"${precio:.2f}"
    return f"Envío: {texto}" if con_etiqueta else texto


def formatear_resumen_envio(envio, predeterminado="-"):
    envio = _normalizar_envio(envio)
    if not envio:
        return predeterminado
    paqueteria = str(envio.get("paqueteria") or envio.get("tipo") or "").strip()
    costo = formatear_costo_envio(envio)
    return f"{paqueteria} | {costo}" if paqueteria else costo


def _fecha_calendario(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor or "").strip()
    if not texto:
        return None

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def formatear_rango_fecha_envio(fecha_desde, fecha_hasta=None):
    """Presenta las fechas reales del pedido para cotizaciones y ventas."""
    desde = _fecha_calendario(fecha_desde)
    if desde is None:
        return "Por confirmar"

    if fecha_hasta not in (None, ""):
        hasta = _fecha_calendario(fecha_hasta)
        if hasta is None or hasta < desde:
            return "Por confirmar"
    else:
        # Compatibilidad con notas historicas sin pedido asociado.
        hasta = desde + timedelta(days=2)

    return f"{desde.strftime('%d/%m/%Y')} - {hasta.strftime('%d/%m/%Y')}"


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
