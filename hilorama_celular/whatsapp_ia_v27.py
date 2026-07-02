import json
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher


EMOJI_OK = "\U0001f60a"
EMOJI_SAD = "\U0001f614"

INTENCIONES = {
    "saludo",
    "pregunta_precio",
    "pide_gama",
    "pide_foto_tono",
    "consulta_stock",
    "iniciar_pedido",
    "pedido_lista",
    "correccion_pedido",
    "confirmacion_contexto",
    "envio",
    "cp_envio",
    "pago",
    "comprobante",
    "datos_cliente",
    "seguimiento",
    "agradecimiento",
    "cierre",
    "duda_general",
    "producto_no_manejado",
    "pregunta_horario",
    "pregunta_promocion",
    "decision_comercial",
}

ESTADOS_PEDIDO = {
    "esperando_lista_de_colores",
    "esperando_cantidad",
    "esperando_confirmacion_hilo",
    "esperando_cp",
    "esperando_datos_envio",
    "esperando_comprobante",
    "preparando_cotizacion",
    "pedido_confirmado",
    "conversacion_cerrada",
}

HILO_ALIASES = {
    "VELLUTO": [
        "velluto", "veluto", "belluto", "vellluto", "vello", "alize velluto",
        "alize veluto", "terciopelo",
    ],
    "KOMFY MINI": [
        "komfy mini", "komfi mini", "konfy mini", "comfy mini", "komfy",
        "komfi", "konfy", "comfy",
    ],
    "KURUMI": ["kurumi"],
    "KAIRO": ["kairo"],
    "TRAPILLO": ["trapillo", "trapillo kraft", "kraft"],
}

COLOR_ALIASES = {
    # Ojo: blanco y hueso NO son lo mismo en todos los hilos.
    # Se separan para no convertir "hueso" en blanco cuando la clienta escribió hueso.
    "blanco": ["blanco", "blanca", "white"],
    "hueso": ["hueso", "marfil", "crudo", "ivory", "crema"],
    "negro": ["negro", "negra", "black"],
    "rojo": ["rojo", "roja", "rojo escolar", "escolar"],
    "rosa": ["rosa", "rosa bebe", "rosa bb", "pink"],
    "azul": ["azul", "azul cielo", "cielo", "celeste", "turquesa", "marino"],
    "verde": ["verde", "menta", "pistache", "olivo"],
    "amarillo": ["amarillo", "canario", "mostaza", "oro"],
    "cafe": ["cafe", "cafe oscuro", "cafe claro", "chocolate"],
    "gris": ["gris", "plata"],
    "morado": ["morado", "lila", "uva", "lavanda"],
    "naranja": ["naranja", "mandarina", "coral"],
    "beige": ["beige", "arena", "piel", "nude", "carne", "camel"],
}

NORMALIZACIONES = [
    (r"\bbuenas\s+trades\b", "buenas tardes"),
    (r"\bpwdido\b", "pedido"),
    (r"\bgamas\b", "gama"),
    (r"\bganas\s+de\s+colores\b", "gama de colores"),
    (r"\bvigenete\b", "vigente"),
    (r"\bcoti+iza\b", "cotiza"),
    (r"\bcotisar\b|\bcotisarme\b|\bcotizame\b|\bcot[íi]zame\b", "cotiza"),
    (r"\bporfavro\b|\bporfa\b", "por favor"),
    (r"\bkonfy\b|\bkomfi\b|\bcomfy\b", "komfy mini"),
    (r"\bbelluto\b|\bveluto\b|\bvellluto\b", "velluto"),
    (r"\bazul\s+sielo\b", "azul cielo"),
    (r"\brojo\s+escolr\b", "rojo escolar"),
    (r"\bme\s+surte\b|\bsurteme\b|\bsurteme\b", "quiero pedir"),
    (r"\bme\s+lo\s+pone\b|\bme\s+lo\s+agrega\b", "agregar al pedido"),
    (r"\bme\s+lo\s+aparta\b|\bapartame\b", "agregar al pedido"),
]

QTY_WORDS = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "quince": 15,
    "veinte": 20, "treinta": 30,
}

RESPUESTA_REVISION_HUMANA = "Claro \U0001f60a déjeme revisarlo y le confirmo para darle la mejor opción."

# V32: mapas comerciales seguros para mejorar entendimiento humano cuando el
# almacén no alcanza a resolver por alias/ortografía. Se usan para redactar
# respuestas de venta, no para generar notas sin validar en almacén.
KOMFY_MINI_CODE_COLORS = {
    "01": "Blanco", "1": "Blanco",
    "06": "Cielo", "6": "Cielo",
    "08": "Turquesa", "8": "Turquesa",
    "14": "Rosa Bebé",
    "20": "Lila",
    "99": "Negro",
}
KOMFY_MINI_COLOR_CODES = {
    "blanco": "01",
    "negro": "99",
    "cielo": "06",
    "azul cielo": "06",
    "turquesa": "08",
    "rosa bebe": "14",
    "rosa bb": "14",
    "lila": "20",
}
VELLUTO_CODE_COLORS = {
    "55": "Blanco", "56": "Rojo", "60": "Negro",
    "216": "Canario", "429": "Camel", "493": "Café Oscuro",
    "530": "Arena", "550": "Mandarina", "218": "Azul Bebé",
    "310": "Trigo", "107": "Vino", "329": "", "466": "", "26": "", "87": "", "428": "", "13": "", "31": "",
}
VELLUTO_COLOR_CODES = {
    "blanco": "55", "negro": "60", "rojo": "56",
    "camel": "429", "arena": "530", "canario": "216",
    "amarillo": "216", "mandarina": "550", "cafe oscuro": "493",
}


def _sin_acentos(texto):
    texto = "" if texto is None else str(texto)
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _norm(texto):
    texto = _sin_acentos(texto).lower()
    texto = texto.replace("\u00d7", "x")
    texto = re.sub(r"[^\w\s#,$.\-/\n]+", " ", texto, flags=re.UNICODE)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r" *\n+ *", "\n", texto)
    return texto.strip()


def _compact(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def _ratio(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def normalizar_texto_cliente(texto):
    original = "" if texto is None else str(texto)
    limpio = _norm(original)
    correcciones = []
    for patron, reemplazo in NORMALIZACIONES:
        nuevo = re.sub(patron, reemplazo, limpio, flags=re.I)
        if nuevo != limpio:
            correcciones.append({"patron": patron, "reemplazo": reemplazo})
            limpio = nuevo
    # Normaliza pequenas variantes frecuentes sin anunciarselo al cliente.
    limpio = re.sub(r"\bcodigos?\b|\bc[oó]digos?\b", "codigo", limpio)
    limpio = re.sub(r"\bpzas?\b|\bpiezas?\b|\bmadejas?\b", "piezas", limpio)
    limpio = re.sub(r"[ \t\r\f\v]+", " ", limpio)
    limpio = re.sub(r" *\n+ *", "\n", limpio).strip()
    return {
        "original": original,
        "texto": limpio,
        "lineas": [ln.strip() for ln in limpio.splitlines() if ln.strip()],
        "correcciones": correcciones,
    }


def _producto_hilos(productos):
    hilos = []
    seen = set()
    for p in productos or []:
        h = str(p.get("hilo") or "").strip()
        if h and _norm(h) not in seen:
            seen.add(_norm(h))
            hilos.append(h)
    return hilos


def _hilo_family(hilo):
    h = _norm(hilo).replace(" ", "")
    if "komfy" in h or "komfi" in h or "konfy" in h or "comfy" in h:
        return "KOMFY MINI"
    if "velluto" in h or "veluto" in h or "belluto" in h or "alize" in h:
        return "VELLUTO"
    if "kurumi" in h:
        return "KURUMI"
    if "kairo" in h:
        return "KAIRO"
    if "trapillo" in h or "kraft" in h:
        return "TRAPILLO"
    return str(hilo or "").strip().upper()


def _hilo_display(hilo):
    fam = _hilo_family(hilo)
    if fam == "VELLUTO":
        return "Velluto"
    if fam == "KOMFY MINI":
        return "Komfy Mini"
    if fam == "KURUMI":
        return "Kurumi"
    if fam == "KAIRO":
        return "Kairo"
    if fam == "TRAPILLO":
        return "Trapillo"
    return str(hilo or "").strip().title()




def _producto_preferible_para_familia(productos, familia):
    """Elige el hilo real de almacén para una familia.

    En el almacén hay productos auxiliares como paquetes o surtidos que pueden
    tener nombres parecidos (por ejemplo "KOMFY" / "20 SURTIDOS"). Para el
    agente de WhatsApp debemos preferir el hilo vendible real, no paquetes.
    """
    fam_objetivo = _hilo_family(familia)
    candidatos = [p for p in (productos or []) if _hilo_family(p.get("hilo")) == fam_objetivo and _no_combo(p)]
    if not candidatos:
        candidatos = [p for p in (productos or []) if _hilo_family(p.get("hilo")) == fam_objetivo]
    if not candidatos:
        return None

    def score(p):
        h = _norm(p.get("hilo") or "")
        m = _norm(p.get("marca") or "")
        c = _norm(p.get("color") or "")
        s = 0
        if _stock(p) > 0:
            s += 20
        if _no_combo(p):
            s += 30
        if fam_objetivo == "KOMFY MINI":
            if "komfy mini" in h:
                s += 80
            if m == "karina":
                s += 60
            if "surtido" in c or "paquete" in c or "combo" in c:
                s -= 100
        elif fam_objetivo == "VELLUTO":
            if "velluto" in h:
                s += 80
            if m == "alize":
                s += 60
        return s

    return sorted(candidatos, key=lambda p: (-score(p), str(p.get("hilo") or ""), str(p.get("marca") or "")))[0]

def detectar_hilos(texto, productos=None):
    t = _norm(texto)
    encontrados = []
    familias = []
    for fam, aliases in HILO_ALIASES.items():
        if any(re.search(rf"(?<!\w){re.escape(_norm(a))}(?!\w)", t) for a in aliases):
            familias.append(fam)
    hilos_reales = _producto_hilos(productos)
    for fam in familias:
        elegido = ""
        for h in hilos_reales:
            if _hilo_family(h) == fam:
                elegido = h
                break
        if not elegido:
            elegido = fam
        if elegido not in encontrados:
            encontrados.append(elegido)
    return encontrados


def _detectar_cp(texto, memoria=None):
    t = _norm(texto)
    m = re.search(r"\b(\d{5})\b", t)
    if not m:
        return ""
    if re.search(r"\b(cp|codigo postal|postal|envio|paqueteria)\b", t):
        return m.group(1)
    estado = str((memoria or {}).get("estado_actual") or (memoria or {}).get("ultima_intencion") or "")
    if estado in ("esperando_cp", "envio", "pregunta_envio") or (memoria or {}).get("datos_envio_pendientes"):
        return m.group(1)
    if re.fullmatch(r"(?:mi\s+)?(?:cp\s*(?:es)?\s*)?\d{5}", t):
        return m.group(1)
    return ""


def _extraer_total_esperado(texto):
    t = _norm(texto)
    patrones = [
        r"\b(?:son|serian|seria|total|en total)\s+(\d{1,3})\s*(?:piezas|madejas|pzas|pz)?\b",
        r"\b(\d{1,3})\s*(?:piezas|madejas|pzas|pz)\s+(?:en\s+)?total\b",
        r"\b(\d{1,3})\s*(?:piezas|madejas|pzas|pz)\b",
    ]
    for pat in patrones:
        m = re.search(pat, t)
        if m:
            after = t[m.end():m.end() + 24]
            if re.match(r"\s*(?:del|de|codigo|cod|tono)\b", after):
                continue
            return int(m.group(1))
    return None


def _es_consulta_manejo(texto):
    """Pregunta tipo: ¿manejan/tienen/venden Komfy Mini?"""
    t = _norm(texto)
    return bool(re.search(r"\b(manejan|maneja|tienen|tiene|hay|venden|vende|trabajan|trabaja)\b", t))


def _pide_colores_disponibles(texto):
    t = _norm(texto)
    return bool(re.search(r"\b(colores|tonos|disponibles|stock|existencia|existencias)\b", t))


def _pide_solo_existencia_hilo(texto):
    t = _norm(texto)
    return _es_consulta_manejo(t) and not _pide_colores_disponibles(t) and not re.search(r"\b(blanco|negro|rojo|rosa|azul|verde|amarillo|cafe|gris|morado|lila|naranja|beige|hueso|piel|cielo|marino|uva|canario|mandarina|turquesa|arena|camel|vino)\b", t)


def _hay_color_en_texto(texto):
    t = _norm(texto)
    colores = []
    for canon, aliases in COLOR_ALIASES.items():
        for alias in aliases:
            a = _norm(alias)
            if a and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", t):
                colores.append(canon)
                break
    return colores


def detectar_intencion(normalizado, memoria=None, productos=None):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    hilos = detectar_hilos(texto, productos)
    cp = _detectar_cp(texto, memoria)
    total = _extraer_total_esperado(texto)
    principal = "duda_general"
    secundaria = ""
    estado = ""

    if re.fullmatch(r"(gracias|muchas gracias|ok gracias|perfecto gracias|listo gracias)", texto):
        principal = "agradecimiento"
        estado = "conversacion_cerrada"
    elif re.search(r"\b(comprobante|ya pague|ya pagado|ya quedo el pago|pago|transferencia|deposito|ticket|recibo)\b", texto):
        principal = "comprobante" if re.search(r"\b(comprobante|ticket|recibo|ya pague|ya quedo)\b", texto) else "pago"
        estado = "esperando_comprobante"
    elif cp:
        principal = "cp_envio"
        estado = "esperando_datos_envio"
    elif re.search(r"\b(envio|envios|paqueteria|cuanto sale el envio|costo de envio)\b", texto):
        principal = "envio"
        estado = "esperando_cp"
    elif hilos and _es_consulta_manejo(texto) and not _pide_colores_disponibles(texto):
        principal = "consulta_stock"
        secundaria = "consulta_manejan"
    elif (
        re.search(r"\b(gama|carta|catalogo)\b", texto)
        or re.search(r"\b(colores|tonos)\s+(?:disponibles|tienen|manejan|hay)\b", texto)
        or re.search(r"\b(?:que\s+)?(?:colores|tonos)\s+(?:tiene|tienen|hay|manejan)\b", texto)
        or re.search(r"\b(?:tiene|tienen|hay|manejan)\b.*\b(?:colores|tonos)\b", texto)
    ):
        # "que colores tiene disponibles" puede ser stock; "manda la gama" es recurso.
        if re.search(r"\b(manda|mandeme|envia|pasa|pasame|comparte|gama|carta|catalogo)\b", texto):
            principal = "pide_gama"
        else:
            principal = "consulta_stock"
    elif re.search(r"\b(foto|imagen|muestra|mostrar|ver)\b", texto) and re.search(r"\b\d{1,4}\b", texto):
        principal = "pide_foto_tono"
    elif re.search(r"\b(cuanto|precio|cuesta|costo|vale|sale)\b", texto):
        principal = "pregunta_precio"
    elif re.search(r"\b(manejan|maneja|tienen|tiene)\b.*\b(abuelita|sinfonia)\b", texto):
        principal = "producto_no_manejado"
    elif re.search(r"\b(todo|todos|toda|todas)\s+(?:seria|serian|es|son)?\s*(?:de|en)?\s*(velluto|komfy|kurumi|kairo|trapillo)\b", texto):
        principal = "confirmacion_contexto"
        estado = "preparando_cotizacion"
    elif re.search(r"\b(quita|quite|quitar|quitame|quítame|corrige|corregir|me equivoque|cambia)\b", texto):
        principal = "correccion_pedido"
    elif _parece_lista_o_pedido(texto, memoria):
        principal = "pedido_lista"
        estado = "preparando_cotizacion"
    elif re.search(r"\b(pedido|cotizar|cotiza|hacer pedido|agregar al pedido|quiero pedir|lista)\b", texto):
        principal = "iniciar_pedido"
        estado = "esperando_lista_de_colores"
    elif re.search(r"\b(hola|buenas tardes|buen dia|buenos dias|buenas noches)\b", texto):
        principal = "saludo"

    if principal == "iniciar_pedido" and total:
        secundaria = "total_esperado"
    if principal in ("pide_gama", "consulta_stock") and hilos:
        secundaria = "hilo_mencionado"

    return {
        "principal": principal,
        "secundaria": secundaria,
        "hilos_mencionados": hilos,
        "cp": cp,
        "total_esperado": total,
        "estado_sugerido": estado,
    }


def _parece_lista_o_pedido(texto, memoria=None):
    t = _norm(texto)
    if re.search(r"\b\d{1,3}\s*(?:del|de|codigo|cod|tono)\s*\d{1,4}\b", t):
        return True
    if re.search(r"\b\d{1,4}\s*x\s*\d{1,3}\b", t):
        return True
    if len(re.findall(r"(?<!\d)\d{1,4}(?!\d)", t)) >= 3 and not _detectar_cp(t):
        return True
    # V32: pedidos humanos tipo "quiero 4 blanco de komfy mini" o "ocupo 2 lila".
    if re.search(r"\b(quiero|ocupo|necesito|me\s+cotiza|cotiza|me\s+puede\s+poner|poner|agregar|dame|deme)\s+\d{1,3}\s+[a-z]", t):
        return True
    if re.search(r"\b(agregar|quiero pedir|dame|deme|ponme|me puede poner|lista|cotizar|cotiza)\b", t):
        return True
    estado = str((memoria or {}).get("estado_actual") or "")
    if estado in ("esperando_lista_de_colores", "preparando_cotizacion") and re.search(r"\b\d{1,4}\b", t):
        return True
    return False


def _inferir_hilo_por_codigos_y_texto(texto, productos=None):
    """Inferencia comercial de bajo riesgo para mensajes sin hilo explícito.
    Ejemplo: "3 del 06 y 6 del 99" casi siempre es Komfy Mini.
    """
    t = _norm(texto)
    if detectar_hilos(t, productos):
        return ""
    # Preferimos los números que realmente parecen códigos, no cantidades.
    codigos = []
    codigos.extend(m.group(1) for m in re.finditer(r"\b\d{1,3}\s*(?:del|de|codigo|cod|tono)\s*#?(\d{1,4})\b", t))
    codigos.extend(m.group(1) for m in re.finditer(r"\b(\d{1,4})\s*(?:x|\*)\s*\d{1,3}\b", t))
    if not codigos:
        codigos = re.findall(r"(?<!\d)\d{1,4}(?!\d)", t)
    if not codigos:
        return ""
    cods = {c.zfill(2) if len(c) <= 2 else c for c in codigos}
    komfy = set(KOMFY_MINI_CODE_COLORS.keys())
    velluto = set(VELLUTO_CODE_COLORS.keys())
    if cods and cods.issubset(komfy):
        return _hilo_real_para_familia(productos, "KOMFY MINI") or "Komfy Mini"
    if cods and cods.issubset(velluto):
        return _hilo_real_para_familia(productos, "VELLUTO") or "Velluto"
    return ""


def _hilo_real_para_familia(productos, familia):
    elegido = _producto_preferible_para_familia(productos, familia)
    if elegido:
        return str(elegido.get("hilo") or "").strip()
    return ""


def extraer_contexto_conversacion(normalizado, intencion, memoria=None, productos=None, marca_ui="", hilo_ui=""):
    memoria = dict(memoria or {})
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    hilos = intencion.get("hilos_mencionados") or detectar_hilos(texto, productos)
    hilo = ""
    marca = ""
    origen = "sin_contexto"

    if hilo_ui and _norm(hilo_ui) not in ("todo", "todos", "toda", "todas", "all"):
        hilo = hilo_ui
        origen = "seleccion_manual"
    elif hilos:
        hilo = hilos[0]
        origen = "mensaje_actual"
    else:
        inferido = _inferir_hilo_por_codigos_y_texto(texto, productos)
        if inferido:
            hilo = inferido
            origen = "inferencia_codigos"
        elif memoria.get("hilo_actual"):
            hilo = memoria.get("hilo_actual")
            origen = "memoria"

    if marca_ui and _norm(marca_ui) not in ("todo", "todos", "toda", "todas", "all"):
        marca = marca_ui
    elif hilo:
        marca = _marca_para_hilo(productos, hilo) or memoria.get("marca_actual", "")
    else:
        marca = memoria.get("marca_actual", "")

    estado = intencion.get("estado_sugerido") or memoria.get("estado_actual") or ""
    if intencion["principal"] == "iniciar_pedido" and hilo:
        estado = "esperando_lista_de_colores"
    if intencion["principal"] == "pedido_lista" and not hilo:
        estado = "esperando_confirmacion_hilo"
    if intencion["principal"] == "envio":
        estado = "esperando_cp"
    if intencion["principal"] == "cp_envio":
        estado = "esperando_datos_envio"
    if intencion["principal"] in ("pago", "comprobante"):
        estado = "esperando_comprobante"

    total = intencion.get("total_esperado")
    if total is None:
        try:
            total = int(memoria.get("total_esperado") or 0) or None
        except Exception:
            total = None

    return {
        "hilo_actual": hilo,
        "marca_actual": marca,
        "origen_contexto": origen,
        "estado_actual": estado,
        "total_esperado": total,
        "cp_actual": intencion.get("cp") or memoria.get("cp_actual") or "",
        "memoria_previa": memoria,
    }


def _marca_para_hilo(productos, hilo):
    fam = _hilo_family(hilo)
    elegido = _producto_preferible_para_familia(productos, fam)
    if elegido:
        return str(elegido.get("marca") or "").strip()
    for p in productos or []:
        if _hilo_family(p.get("hilo")) == fam:
            return str(p.get("marca") or "").strip()
    return ""


def extraer_productos_y_cantidades(normalizado, intencion, contexto):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    texto_sin_totales = _quitar_totales_y_cp(texto)
    items = []

    # 5 del 55, 10 de 60
    for m in re.finditer(r"(?<!\d)(\d{1,3})\s*(?:piezas?\s*)?(?:del|de|codigo|cod|tono)\s*#?(\d{1,4})(?!\d)", texto_sin_totales):
        items.append(_item(codigo=m.group(2), cantidad=int(m.group(1)), raw=m.group(0), fuente="cantidad_codigo"))

    # 55 x2
    for m in re.finditer(r"(?<!\d)(\d{1,4})\s*(?:x|\*)\s*(\d{1,3})(?!\d)", texto_sin_totales):
        items.append(_item(codigo=m.group(1), cantidad=int(m.group(2)), raw=m.group(0), fuente="codigo_x_cantidad"))

    # Blanco 01 - 2 / 216 canario - 4
    for linea in normalizado.get("lineas") or [texto_sin_totales]:
        l = _quitar_intro_lista(linea)
        m = re.fullmatch(r"(\d{1,4})\s+([a-z0-9 ]{2,})\s*-\s*(\d{1,3})", l)
        if m:
            items.append(_item(codigo=m.group(1), cantidad=int(m.group(3)), desc=m.group(2), raw=linea, fuente="codigo_color_cantidad"))
            continue
        m = re.fullmatch(r"([a-z0-9 ]{2,})\s+(\d{1,4})\s*-\s*(\d{1,3})", l)
        if m:
            items.append(_item(codigo=m.group(2), cantidad=int(m.group(3)), desc=m.group(1), raw=linea, fuente="color_codigo_cantidad"))
            continue
        m = re.fullmatch(r"([a-z0-9 ]{2,})\s*-\s*(\d{1,3})", l)
        if m and not re.search(r"\d", m.group(1)):
            items.append(_item(cantidad=int(m.group(2)), desc=m.group(1), raw=linea, fuente="color_cantidad"))

    # 3 rojos y 2 negros
    for m in re.finditer(r"(?<!\d)(\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+([a-z][a-z ]{2,}?)(?=\s+y\s+\d|\s*,|$)", texto_sin_totales):
        qty = _qty(m.group(1))
        desc = _limpiar_desc_color(m.group(2))
        if qty and desc and not re.search(r"\b(pedido|lista|total|piezas)\b", desc):
            items.append(_item(cantidad=qty, desc=desc, raw=m.group(0), fuente="cantidad_color"))

    # Listas puras de codigos.
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto_sin_totales)
    if nums and _debe_tomar_codigos_sueltos(texto, intencion, contexto, len(items), len(nums)):
        explicit = {str(it.get("codigo_raw") or it.get("codigo") or "") for it in items}
        cantidad_lista = 1 if len(nums) > 1 else None
        for n in nums:
            if any(re.search(rf"(?<!\d){re.escape(n)}(?!\d)", str(it.get("raw") or "")) for it in items):
                continue
            if n not in explicit:
                items.append(_item(codigo=n, cantidad=cantidad_lista, raw=n, fuente="codigo_suelto"))

    # Color suelto como "azul cielo" o "rojo".
    if not items and intencion["principal"] in ("pedido_lista", "consulta_stock", "duda_general"):
        desc = _limpiar_desc_color(texto_sin_totales)
        if intencion["principal"] == "consulta_stock" and not _hay_color_en_texto(desc):
            desc = ""
        if desc and re.search(r"[a-z]", desc) and not detectar_hilos(desc):
            items.append(_item(desc=desc, cantidad=None, raw=desc, fuente="color_suelto"))

    return {
        "items": _dedup_items(items),
        "cp": intencion.get("cp") or "",
        "total_esperado": intencion.get("total_esperado"),
        "texto_sin_totales": texto_sin_totales,
    }


def _item(codigo="", cantidad=None, desc="", raw="", fuente=""):
    codigo_raw = str(codigo or "").strip()
    codigo_norm = codigo_raw.lstrip("0") or codigo_raw
    return {
        "codigo": codigo_norm,
        "codigo_raw": codigo_raw,
        "cantidad": cantidad,
        "desc": _compact(desc),
        "raw": _compact(raw),
        "fuente": fuente,
    }


def _qty(token):
    token = _norm(token)
    if token.isdigit():
        return int(token)
    return QTY_WORDS.get(token)


def _quitar_totales_y_cp(texto):
    t = str(texto or "")
    t = re.sub(r"\b(?:cp|codigo postal|postal)\s*(?:es)?\s*\d{5}\b", " ", t)
    t = re.sub(r"\$\s*\d+(?:\.\d+)?", " ", t)
    t = re.sub(r"\b(?:son|serian|seria|total|en total)\s+\d{1,3}\s*(?:piezas|madejas|pzas|pz)?\b", " ", t)
    t = re.sub(r"\b\d{1,3}\s*(?:piezas|madejas|pzas|pz)\s+(?:en\s+)?total\b", " ", t)
    return _compact(t)


def _quitar_intro_lista(linea):
    l = _norm(linea)
    l = re.sub(r"^.*?\b(?:lista|pedido|poner|agregar|cotizar)\b\s*", "", l)
    l = re.sub(r"^(?:quiero|dame|deme|ponme|agregame|agrega)\s+", "", l)
    return _compact(l.strip(" ,.;"))


def _limpiar_desc_color(desc):
    d = _norm(desc)
    # Si el cliente dice "blanco que no se vea tan amarillo", la intención principal es blanco,
    # no amarillo. Quitamos colores negados para no sugerir el tono contrario.
    d = re.sub(r"\bno\s+(?:se\s+)?(?:vea|sea|este)?\s*(?:tan|muy|mas)?\s*(amarillo|amarillento|rosa|rosado|oscuro|fuerte)\b", " ", d)
    # Quita verbos/frases de venta para que "¿tienen Velluto blanco?" deje solo "blanco".
    d = re.sub(r"\b(quiero|dame|deme|ponme|agregar|agregame|apartame|me|puede|podria|poner|apartar|pedido|lista|cotizar|cotiza|color|tono|de|del|el|la|los|las|por favor|favor|tiene|tienen|manejan|maneja|hay|busco|busca|necesito|ocupo|quiero|disponible|disponibles|en|un|una|unos|unas)\b", " ", d)
    d = re.sub(r"\b(velluto|komfy mini|komfy|komfi|konfy|comfy|mini|kurumi|kairo|trapillo|alize|karina|hilorama)\b", " ", d)
    d = re.sub(r"\b(que|se|vea|tan|no|muy|mas|menos|como|para)\b", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d


def _debe_tomar_codigos_sueltos(texto, intencion, contexto, items_count, nums_count):
    if intencion["principal"] == "pide_foto_tono":
        return False
    if _detectar_cp(texto):
        return False
    if nums_count >= 2:
        return True
    estado = contexto.get("estado_actual")
    if estado in ("esperando_lista_de_colores", "preparando_cotizacion") and nums_count == 1:
        return True
    if intencion["principal"] == "pedido_lista" and nums_count == 1 and items_count == 0:
        return True
    return False


def _dedup_items(items):
    out = []
    seen = set()
    for it in items:
        key = (it.get("codigo_raw") or it.get("codigo") or "", it.get("desc") or "", it.get("cantidad"), it.get("raw") or "")
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def resolver_productos_con_almacen(extraccion, productos, contexto):
    productos = list(productos or [])
    productos_ctx = _filtrar_contexto(productos, contexto)
    pedidos = []
    preguntas = []
    errores = []
    sugerencias = []
    internos = []

    for item in extraccion.get("items") or []:
        res = _resolver_item(item, productos, productos_ctx, contexto)
        if res.get("pedido"):
            pedidos.append(res["pedido"])
        preguntas.extend(res.get("preguntas") or [])
        errores.extend(res.get("errores") or [])
        sugerencias.extend(res.get("sugerencias") or [])
        internos.extend(res.get("internos") or [])

    pedidos = _merge_pedidos(pedidos)
    return {
        "pedidos": pedidos,
        "preguntas": _uniq(preguntas),
        "errores": _uniq(errores),
        "sugerencias": sugerencias,
        "internos": internos,
        "productos_contexto": len(productos_ctx),
    }


def _filtrar_contexto(productos, contexto):
    base = list(productos or [])
    out = list(base)
    marca = _norm(contexto.get("marca_actual") or "")
    hilo = contexto.get("hilo_actual") or ""
    fam = _hilo_family(hilo) if hilo else ""
    if marca:
        out = [p for p in out if _norm(p.get("marca") or "") == marca]
    if hilo:
        exact = [p for p in out if _norm(p.get("hilo") or "") == _norm(hilo)]
        fam_matches = [p for p in out if _hilo_family(p.get("hilo")) == fam]
        out = exact or fam_matches
        # Si la marca seleccionada dejó solo paquetes/surtidos o vacío, reintentamos
        # por familia en todo el almacén y preferimos productos vendibles reales.
        if not out or not any(_no_combo(p) for p in out):
            out2 = [p for p in base if _hilo_family(p.get("hilo")) == fam]
            vendibles = [p for p in out2 if _no_combo(p)]
            out = vendibles or out2 or out
    return out


def _code_map(productos):
    mp = {}
    for p in productos or []:
        for key in (p.get("codigo"), p.get("codigo_barras")):
            raw = str(key or "").strip()
            if not raw:
                continue
            keys = {raw, raw.lstrip("0") or raw}
            for k in keys:
                mp.setdefault(k, []).append(p)
    return mp


def _resolver_item(item, productos_all, productos_ctx, contexto):
    codigo = str(item.get("codigo") or "").strip()
    codigo_raw = str(item.get("codigo_raw") or codigo).strip()
    desc = str(item.get("desc") or "").strip()
    qty = item.get("cantidad")
    hilo_ctx = contexto.get("hilo_actual") or ""
    out = {"preguntas": [], "errores": [], "sugerencias": [], "internos": []}

    prod_por_desc = None
    if desc and hilo_ctx:
        prod_por_desc, opts_desc = _buscar_por_color(productos_ctx, desc)
    else:
        opts_desc = []

    matches = []
    if codigo:
        ctx_map = _code_map(productos_ctx)
        all_map = _code_map(productos_all)
        matches = ctx_map.get(codigo_raw) or ctx_map.get(codigo) or []
        # Si hay contexto de hilo pero por marca/filtro no aparecio, buscamos en todo y
        # preferimos el mismo hilo/familia antes de preguntar como ambiguo.
        if not matches:
            all_matches = all_map.get(codigo_raw) or all_map.get(codigo) or []
            if hilo_ctx and all_matches:
                fam = _hilo_family(hilo_ctx)
                fam_matches = [p for p in all_matches if _hilo_family(p.get("hilo")) == fam]
                matches = fam_matches or []
            elif not hilo_ctx:
                matches = all_matches

    prod = None
    if matches:
        normales = [p for p in matches if _no_combo(p)]
        matches = normales or matches
        fams = sorted({_hilo_family(p.get("hilo")) for p in matches})
        if not hilo_ctx and len(fams) > 1:
            # Heurística comercial: muchos códigos cortos de Komfy Mini (01,06,08,14,20,99)
            # aparecen en varios catálogos, pero si hay stock claro en Komfy Mini lo preferimos
            # para evitar mandar todo a revisión cuando la clienta sí dio una lista normal.
            komfy = [p for p in matches if _hilo_family(p.get("hilo")) == "KOMFY MINI" and _stock(p) > 0]
            velluto = [p for p in matches if _hilo_family(p.get("hilo")) == "VELLUTO" and _stock(p) > 0]
            if codigo_raw.zfill(2) in {"01", "06", "08", "14", "20", "99"} and komfy:
                matches = komfy
                fams = ["KOMFY MINI"]
            elif codigo_raw in {"55", "56", "60", "216", "310", "329", "428", "429", "466", "493", "532", "550"} and velluto:
                matches = velluto
                fams = ["VELLUTO"]
            else:
                opciones = ", ".join(_hilo_display(f) for f in fams[:4])
                out["preguntas"].append(f"El codigo {codigo_raw or codigo} aparece en varios hilos. Lo busca en {opciones}?")
                return out
        prod_codigo = sorted(matches, key=lambda p: _stock(p), reverse=True)[0]
        if desc and not _desc_compatible(prod_codigo, desc):
            if prod_por_desc:
                prod = prod_por_desc
                out["internos"].append("color_priorizado_sobre_codigo")
            else:
                out["preguntas"].append(f"Para {item.get('raw')}, confirmo el color antes de agregarlo?")
                return out
        else:
            prod = prod_codigo
    elif desc:
        if not hilo_ctx:
            out["preguntas"].append(f"Lo busca en Velluto, Komfy Mini o algun otro hilo?")
            return out
        prod, opts_desc = _buscar_por_color(productos_ctx, desc)
        if not prod and opts_desc:
            out["sugerencias"].append({"tipo": "color_parecido", "texto": desc, "opciones": opts_desc[:5]})
            out["preguntas"].append(f"Le muestro opciones parecidas para {desc}?")
            return out
        if not prod:
            # V32: si no se resolvió en almacén, no generamos error técnico.
            # Dejamos una pregunta humana que conserva hilo/color para que la respuesta sea útil.
            out["preguntas"].append(f"Me confirma si quiere {desc} en {_hilo_display(hilo_ctx)}?")
            return out
    elif codigo:
        # V32: códigos típicos pueden inferirse por familia para dar respuesta humana,
        # aunque no se pueda generar nota automática sin producto_id.
        fam_ctx = _hilo_family(hilo_ctx) if hilo_ctx else ""
        if fam_ctx == "KOMFY MINI" and (codigo_raw.zfill(2) in KOMFY_MINI_CODE_COLORS or codigo in KOMFY_MINI_CODE_COLORS):
            color = KOMFY_MINI_CODE_COLORS.get(codigo_raw.zfill(2)) or KOMFY_MINI_CODE_COLORS.get(codigo) or ""
            out["preguntas"].append(f"Me confirma Komfy Mini {codigo_raw.zfill(2)} {color}?")
            return out
        if fam_ctx == "VELLUTO" and (codigo_raw in VELLUTO_CODE_COLORS or codigo in VELLUTO_CODE_COLORS):
            color = VELLUTO_CODE_COLORS.get(codigo_raw) or VELLUTO_CODE_COLORS.get(codigo) or ""
            out["preguntas"].append(f"Me confirma Velluto {codigo_raw or codigo} {color}?")
            return out
        out["errores"].append(codigo_raw or codigo)
        out["preguntas"].append("Me confirma ese codigo para revisarlo bien?")
        return out

    if not prod:
        return out

    pedido = _producto_a_pedido(prod, qty)
    if qty is None:
        out["preguntas"].append(f"Cuantas piezas de {_linea_producto(prod)} le agrego?")
        pedido["cantidad_pendiente"] = True
    if pedido.get("es_inventariable", True) and int(pedido.get("stock") or 0) <= 0:
        out["sugerencias"].append({"tipo": "agotado", "producto": pedido})
    out["pedido"] = pedido
    return out


def _no_combo(p):
    texto = " ".join(str((p or {}).get(k) or "") for k in ("color", "nombre", "descripcion", "hilo"))
    t = _norm(texto)
    return not any(x in t for x in ("combo", "paquete", "surtido"))


def _stock(p):
    try:
        return int(p.get("stock") or 0)
    except Exception:
        return 0


def _precio(p):
    try:
        return float(p.get("precio_venta") or p.get("precio") or 0)
    except Exception:
        return 0.0


def _color_explicit_match(color, desc):
    color = _norm(color)
    desc = _norm(desc)
    if not color or not desc:
        return False
    # Si el cliente dijo un color canonico/alias, preferimos tonos que realmente contengan ese color.
    for canon, aliases in COLOR_ALIASES.items():
        alias_norm = [_norm(a) for a in aliases]
        if any(a and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", desc) for a in alias_norm):
            if canon in color or any(a and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", color) for a in alias_norm):
                return True
    return False


def _buscar_por_color(productos, desc):
    descn = _norm(desc)
    scored = []
    for p in productos or []:
        if not _no_combo(p):
            continue
        color = _norm(p.get("color") or "")
        if not color:
            continue
        score = _score_color(color, descn)
        if _color_explicit_match(color, descn):
            score = max(score, 115)
        if score > 0:
            scored.append((score + (_stock(p) > 0), p))
    scored.sort(key=lambda x: (-x[0], -_stock(x[1]), str(x[1].get("codigo") or "")))
    if not scored:
        return None, []
    opts = [p for _, p in scored[:6]]
    # Si hay un color explicito claro (blanco, rojo, hueso, etc.), no lo tratamos como ambiguedad.
    explicitos = [(score, p) for score, p in scored if _color_explicit_match(p.get("color") or "", descn)]
    if explicitos:
        explicitos.sort(key=lambda x: (-x[0], -_stock(x[1]), str(x[1].get("codigo") or "")))
        return explicitos[0][1], opts
    if len(scored) == 1 or scored[0][0] >= 90 or (len(scored) > 1 and scored[0][0] - scored[1][0] >= 35):
        return scored[0][1], opts
    return None, opts


def _score_color(color, desc):
    if desc == color:
        return 120
    if desc and desc in color:
        return 100
    words = [w for w in desc.split() if len(w) >= 3]
    if words and all(w in color for w in words):
        return 95
    score = 0
    for canon, aliases in COLOR_ALIASES.items():
        alias_norm = [_norm(a) for a in aliases]
        if any(a and a in desc for a in alias_norm):
            if any(a and a in color for a in alias_norm) or canon in color:
                score = max(score, 80)
    if words and any(_ratio(w, color) >= 0.82 for w in words):
        score = max(score, 55)
    return score


def _desc_compatible(prod, desc):
    color = _norm((prod or {}).get("color") or "")
    descn = _norm(desc)
    if not descn:
        return True
    if descn in color or color in descn:
        return True
    return _score_color(color, descn) >= 80


def _producto_a_pedido(prod, cantidad):
    return {
        "producto_id": prod.get("id"),
        "codigo": prod.get("codigo"),
        "marca": prod.get("marca") or "",
        "hilo": prod.get("hilo") or "",
        "color": prod.get("color") or "",
        "stock": _stock(prod),
        "precio_venta": _precio(prod),
        "cantidad": int(cantidad or 1),
        "es_inventariable": prod.get("es_inventariable", True),
    }


def _linea_producto(prod_or_pedido):
    hilo = _hilo_display((prod_or_pedido or {}).get("hilo") or "")
    codigo = str((prod_or_pedido or {}).get("codigo") or "").strip()
    color = str((prod_or_pedido or {}).get("color") or "").strip()
    if color and color.isupper():
        color = color.title()
    return " ".join(x for x in (hilo, codigo, color) if x).strip()


def _merge_pedidos(pedidos):
    merged = {}
    for p in pedidos or []:
        key = "|".join(str(p.get(k) or "") for k in ("producto_id", "codigo", "hilo", "color"))
        if key in merged and not p.get("cantidad_pendiente"):
            merged[key]["cantidad"] = int(merged[key].get("cantidad") or 0) + int(p.get("cantidad") or 1)
        else:
            merged[key] = dict(p)
    return list(merged.values())


def _uniq(values):
    out = []
    for v in values or []:
        s = str(v or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def calcular_confianza(intencion, contexto, extraccion, resolucion):
    pedidos = resolucion.get("pedidos") or []
    preguntas = resolucion.get("preguntas") or []
    errores = resolucion.get("errores") or []
    internos = resolucion.get("internos") or []
    nivel = "alta"
    accion = "sugerir_respuesta"

    if preguntas or errores:
        nivel = "baja"
        accion = "preguntar"
    elif any(p.get("cantidad_pendiente") for p in pedidos):
        nivel = "baja"
        accion = "preguntar_cantidad"
    elif any(p.get("es_inventariable", True) and int(p.get("stock") or 0) < int(p.get("cantidad") or 1) for p in pedidos):
        nivel = "media"
        accion = "revision_stock"
    elif internos:
        nivel = "media"
        accion = "revision_sugerida"
    elif intencion["principal"] in ("envio", "pago", "comprobante", "cp_envio"):
        nivel = "media"
        accion = "responder_revision"
    elif intencion["principal"] == "iniciar_pedido":
        nivel = "alta"
        accion = "esperar_lista"
    elif intencion["principal"] == "producto_no_manejado":
        nivel = "media"
        accion = "responder_revision"
    elif not pedidos and intencion["principal"] == "duda_general":
        nivel = "baja"
        accion = "revision_humana"

    return {"confianza": nivel, "accion_recomendada": accion, "puede_auto_enviar": False}


def detectar_decision_pendiente(normalizado, intencion, contexto, extraccion, resolucion, confianza, productos=None, envio=None):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    principal = intencion.get("principal") or ""
    pedidos = resolucion.get("pedidos") or []
    preguntas = resolucion.get("preguntas") or []
    errores = resolucion.get("errores") or []
    sugerencias = resolucion.get("sugerencias") or []
    envio = envio or {}

    def decision(tipo, resumen, opciones=None, prioridad="media", respuesta_provisional=None):
        return {
            "requiere_humano": True,
            "tipo_decision": tipo,
            "prioridad": prioridad,
            "resumen_para_admin": resumen,
            "opciones_sugeridas": opciones or [
                "Responder manualmente",
                "Mantener condiciones actuales",
                "Pedir más información a la clienta",
            ],
            # Este texto sí puede ver la clienta. Debe ser humano y específico,
            # no una frase técnica ni genérica cuando ya sabemos qué falta.
            "respuesta_provisional": respuesta_provisional or RESPUESTA_REVISION_HUMANA,
        }

    if re.search(r"\b(descuento|rebaja|mejor precio|mejora(?:r|me)? el precio|precio especial|precio final|menos precio|bajar(?:le)?|ajustar precio)\b", texto):
        return decision(
            "descuento",
            _resumen_descuento(texto, contexto, productos),
            [
                "Mantener precio actual",
                "Ofrecer descuento solo desde una cantidad autorizada",
                "Responder manualmente",
            ],
            "alta",
        )

    if re.search(r"\b(mayoreo|mayorista|precio por volumen|precio de volumen)\b", texto):
        return decision(
            "mayoreo_no_configurado",
            _resumen_descuento(texto, contexto, productos, etiqueta="La clienta pregunta por precio de mayoreo no configurado"),
            [
                "Mantener precio actual",
                "Definir regla de mayoreo",
                "Responder manualmente",
            ],
            "alta",
        )

    if re.search(r"\b(envio gratis|gratis el envio|cambiar envio|otra paqueteria|mas barato el envio|envio por cobrar|entrega especial|mandamelo por|mandemelo por)\b", texto):
        return decision(
            "condicion_envio",
            "La clienta quiere cambiar condiciones de envio o negociar el costo/paqueteria. Requiere autorizacion antes de prometerlo.",
            ["Mantener condiciones actuales", "Autorizar cambio de paqueteria", "Responder manualmente"],
            "media",
        )

    if re.search(r"\b(promo|promocion|promociones|oferta|ofertas|liquidacion|liquidaci[oó]n|2x1|gratis)\b", texto):
        return decision(
            "promocion_no_registrada",
            "La clienta pregunta por promociones u ofertas. No hay una promocion registrada para responder sin autorizacion.",
            ["Confirmar que no hay promocion activa", "Autorizar una promocion especifica", "Responder manualmente"],
            "media",
        )

    if envio.get("requiere_humano"):
        return decision(
            envio.get("tipo_decision") or "envio_sin_tarifa_segura",
            envio.get("resumen_para_admin") or "Envia.com falló o no regresó una tarifa segura. Se requiere revisar envío manualmente.",
            envio.get("opciones_sugeridas") or ["Revisar tarifa manual", "Pedir otro CP/datos de envío", "Responder manualmente"],
            "alta",
            respuesta_provisional=envio.get("respuesta") or RESPUESTA_REVISION_HUMANA,
        )

    if re.search(r"\b(reembolso|devolucion|devoluci[oó]n|cambio|cambiarlo|garantia|garant[ií]a|cancelar compra|cancelacion|cancelaci[oó]n)\b", texto):
        return decision(
            "reembolso_cambio_devolucion",
            "La clienta pide reembolso, cambio, devolucion o cancelacion. No se debe prometer nada sin aprobacion.",
            ["Revisar caso y evidencia", "Rechazar con politica vigente", "Responder manualmente"],
            "alta",
        )

    if re.search(r"\b(queja|molesta|molesto|enojada|enojado|mal servicio|profeco|denuncia|demandar|fraude|estafa|robo|me voy a quejar|amenaza)\b", texto):
        return decision(
            "queja_amenaza",
            "La clienta expresa queja, molestia fuerte o amenaza. Conviene responder con cuidado y revision humana.",
            ["Responder con disculpa y revision", "Pedir datos del caso", "Responder manualmente"],
            "alta",
        )

    if re.search(r"\b(ya pague|ya pagado|ya quedo el pago|ya transferi|ya deposite)\b", texto):
        if re.search(r"\b(no aparece|no han|no me han|por que|porque|reclamo|me cobraron|si ya pague|no reflejado|no se refleja)\b", texto):
            return decision(
                "reclamo_pago",
                "La clienta reclama un pago o dice que no se le ha reconocido. Se requiere revision humana antes de responder.",
                ["Revisar pagos y comprobante", "Pedir comprobante y datos", "Responder manualmente"],
                "alta",
            )
        if not re.search(r"\b(comprobante|foto|ticket|recibo|captura|adjunto|mando|mande|envio|envi[oó])\b", texto):
            return decision(
                "pago_sin_comprobante",
                "La clienta dice que ya pagó pero no envió comprobante en el mensaje. Se requiere revisión antes de avanzar.",
                ["Pedir comprobante", "Revisar movimientos bancarios", "Responder manualmente"],
                "alta",
                respuesta_provisional=f"Perfecto {EMOJI_OK} me puede mandar foto del comprobante para revisarlo, por favor.",
            )

    insuficientes = [
        p for p in pedidos
        if p.get("es_inventariable", True) and int(p.get("stock") or 0) < int(p.get("cantidad") or 1)
    ]
    # Si solo preguntó disponibilidad, no mandamos a decisión humana por stock 0;
    # respondemos como vendedora diciendo que no aparece disponible.
    if insuficientes and principal not in ("consulta_stock",):
        # V33: stock insuficiente ya no debe mandar una respuesta genérica al cliente.
        # El agente sí puede decir de forma segura cuántas piezas aparecen y qué tonos
        # no están disponibles, sin prometer descuento ni alterar condiciones.
        return None

    if _requiere_humano_por_ambiguedad(preguntas, errores, sugerencias):
        # V32: una duda normal de producto NO debe mandar siempre al humano.
        # Primero preguntamos de forma amable a la clienta. Solo casos comerciales
        # delicados (descuentos, pagos, reclamos, envío especial, stock insuficiente)
        # generan decisión pendiente.
        return None

    if principal == "producto_no_manejado" and not _hay_alternativas_claras(productos):
        return decision(
            "producto_no_manejado_sin_sustituto",
            "La clienta pide un producto que no esta en almacen y no hay sustituto claro con stock.",
            ["Responder que no se maneja", "Buscar sustituto manual", "Responder manualmente"],
            "media",
        )

    return None


def _resumen_descuento(texto, contexto, productos, etiqueta="La clienta pide mejor precio o descuento"):
    hilo = contexto.get("hilo_actual") or ""
    ctx = _filtrar_contexto(productos, contexto) if hilo else list(productos or [])
    precios = [_precio(p) for p in ctx if _precio(p) > 0 and _no_combo(p)]
    precio_txt = ""
    if precios:
        mn, mx = min(precios), max(precios)
        precio_txt = f" Precio actual detectado: ${mn:,.2f}" if abs(mn - mx) < 0.01 else f" Precio detectado desde ${mn:,.2f}."
    hilo_txt = f" Hilo/contexto: {_hilo_display(hilo)}." if hilo else ""
    return f"{etiqueta}.{hilo_txt}{precio_txt} Mensaje: {texto[:240]}"


def _requiere_humano_por_ambiguedad(preguntas, errores, sugerencias):
    if errores:
        return True
    if any((s or {}).get("tipo") in ("color_parecido", "agotado") for s in sugerencias or []):
        return True
    for q in preguntas or []:
        qn = _norm(q)
        if "cuantas piezas" in qn:
            continue
        if any(x in qn for x in ("varios hilos", "no ubique", "confirma codigo", "confirmo el color", "opciones parecidas")):
            return True
    return False


def _hay_alternativas_claras(productos):
    familias = set()
    for p in productos or []:
        if _stock(p) > 0 and _no_combo(p):
            familias.add(_hilo_family(p.get("hilo")))
    return bool(familias)


def _color_solicitado_desde_texto(texto):
    t = _norm(texto)
    # Primero alias específicos para no convertir lila->morado o cielo/turquesa->azul.
    for color in (
        "rosa bebe", "rosa bb", "azul cielo", "cielo", "turquesa", "lila",
        "blanco", "negro", "camel", "arena", "cafe oscuro", "cafe claro", "rojo escolar", "rojo",
    ):
        if re.search(rf"(?<!\w){re.escape(color)}(?!\w)", t):
            return color
    colores = _hay_color_en_texto(t)
    if colores:
        c = colores[0]
        if c == "azul" and "cielo" in t:
            return "cielo"
        if c == "morado" and "lila" in t:
            return "lila"
        return c
    return ""


def _fallback_codigo_color_por_familia(hilo, codigo="", color=""):
    fam = _hilo_family(hilo)
    codigo = str(codigo or "").strip()
    if fam == "KOMFY MINI":
        if codigo:
            color = KOMFY_MINI_CODE_COLORS.get(codigo.zfill(2)) or KOMFY_MINI_CODE_COLORS.get(codigo) or color
            return codigo.zfill(2) if len(codigo) <= 2 else codigo, color
        cn = _norm(color)
        cod = KOMFY_MINI_COLOR_CODES.get(cn) or KOMFY_MINI_COLOR_CODES.get(cn.replace("é", "e"))
        return cod or "", color.title() if color else ""
    if fam == "VELLUTO":
        if codigo:
            color = VELLUTO_CODE_COLORS.get(codigo) or color
            return codigo, color
        cn = _norm(color)
        cod = VELLUTO_COLOR_CODES.get(cn)
        return cod or "", color.title() if color else ""
    return codigo, color.title() if color else ""


def _respuesta_fallback_humana(normalizado, intencion, contexto, extraccion, resolucion):
    """Respuesta humana cuando el almacén no resolvió perfecto.
    Evita el genérico 'déjeme revisar' para preguntas comunes de venta.
    """
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    principal = intencion.get("principal") or ""
    hilo = contexto.get("hilo_actual") or ""
    nombre = _hilo_display(hilo) if hilo else ""
    color = _color_solicitado_desde_texto(texto)
    items = extraccion.get("items") or []

    if principal == "consulta_stock" and nombre and color:
        cod, col = _fallback_codigo_color_por_familia(hilo, color=color)
        detalle = f" {cod} {col}".strip() if cod or col else color
        return f"Claro {EMOJI_OK} le reviso {nombre} {detalle}. ¿Cuántas piezas necesita?"

    if principal == "consulta_stock" and nombre:
        return f"Sí {EMOJI_OK} manejamos {nombre}. ¿Le comparto la gama de colores o busca algún tono en especial?"

    if principal in ("pedido_lista", "duda_general") and (items or color or nombre):
        lineas = []
        total = 0
        fam_hilo = hilo or (_inferir_hilo_por_codigos_y_texto(texto) or "")
        if not nombre and fam_hilo:
            nombre = _hilo_display(fam_hilo)
        for it in items:
            qty = int(it.get("cantidad") or 1)
            cod = str(it.get("codigo_raw") or it.get("codigo") or "").strip()
            desc = str(it.get("desc") or "").strip()
            fc, fcolor = _fallback_codigo_color_por_familia(fam_hilo or nombre, codigo=cod, color=desc)
            if not fc and not fcolor and desc:
                fc, fcolor = _fallback_codigo_color_por_familia(fam_hilo or nombre, color=desc)
            etiqueta = " ".join(x for x in (nombre, fc, fcolor) if x).strip() or (desc or cod or "tono")
            lineas.append(f"- {etiqueta} x{qty}")
            total += qty
        if not lineas and color and nombre:
            qty_match = re.search(r"(?<!\d)(\d{1,3})\s+", texto)
            qty = int(qty_match.group(1)) if qty_match else 1
            fc, fcolor = _fallback_codigo_color_por_familia(hilo, color=color)
            etiqueta = " ".join(x for x in (nombre, fc, fcolor) if x).strip() or f"{nombre} {color}"
            lineas.append(f"- {etiqueta} x{qty}")
            total = qty
        if lineas:
            return f"Claro {EMOJI_OK} le cotizo:\n" + "\n".join(lineas) + f"\n\nTotal: {total} pieza" + ("s." if total != 1 else ".")

    return ""




def _pedidos_desde_memoria(memoria):
    raw = (memoria or {}).get("pedido_en_proceso")
    if not raw:
        return []
    if isinstance(raw, list):
        return [dict(x) for x in raw if isinstance(x, dict)]
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    if isinstance(obj, list):
        return [dict(x) for x in obj if isinstance(x, dict)]
    return []


def _respuesta_confirmacion_contexto_previo(contexto):
    mem = contexto.get("memoria_previa") or {}
    pedidos = _pedidos_desde_memoria(mem)
    if not pedidos:
        return ""
    hilo = _hilo_display(contexto.get("hilo_actual") or mem.get("hilo_actual") or "")
    total = sum(int(p.get("cantidad") or 1) for p in pedidos)
    lineas = [f"* {_linea_producto(p)} x{int(p.get('cantidad') or 1)}" for p in pedidos[:25]]
    intro = f"Perfecto {EMOJI_OK} entonces tomo la lista como {hilo}." if hilo else f"Perfecto {EMOJI_OK} tomo la lista anterior."
    return intro + "\n\n" + "\n".join(lineas) + f"\n\nTotal: {total} pieza" + ("s." if total != 1 else ".") + "\n\nLe preparo su cotización del pedido."


def generar_respuesta_vendedora(normalizado, intencion, contexto, extraccion, resolucion, confianza, productos=None, recursos=None, envio=None):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    principal = intencion["principal"]
    recursos = recursos or {}
    envio = envio or {}

    if principal == "confirmacion_contexto":
        resp_previa = _respuesta_confirmacion_contexto_previo(contexto)
        if resp_previa:
            return resp_previa
        hilo = _hilo_display(contexto.get("hilo_actual") or "")
        return f"Perfecto {EMOJI_OK} lo reviso como {hilo or 'ese hilo'}. Mándeme la lista o los códigos y se lo cotizo."

    if principal == "pide_gama":
        if recursos.get("respuesta"):
            resp_rec = recursos["respuesta"]
            if "gama" not in _norm(resp_rec):
                resp_rec = f"Claro {EMOJI_OK} le comparto la gama/carta de colores. " + str(resp_rec)
            return resp_rec
        hilo = _hilo_display(contexto.get("hilo_actual") or "")
        return f"Claro {EMOJI_OK} le comparto la gama de colores de {hilo or 'ese hilo'}. Si le gusta algun tono, me pasa el codigo y le reviso disponibilidad."

    if principal == "pide_foto_tono":
        if recursos.get("respuesta"):
            return recursos["respuesta"]
        codigo = _primer_codigo(texto)
        return f"Claro {EMOJI_OK} le reviso la foto del tono {codigo}."

    if principal == "pregunta_precio":
        return _respuesta_precio(contexto, productos)

    if principal == "consulta_stock":
        return _respuesta_consulta_stock_detallada(contexto, productos, texto, resolucion, extraccion)

    if principal == "envio":
        return f"Claro {EMOJI_OK} para decirle el costo exacto de envío necesito su código postal (CP), por favor."

    if principal == "cp_envio":
        if envio.get("respuesta"):
            return envio["respuesta"]
        cp = extraccion.get("cp") or contexto.get("cp_actual") or ""
        return f"Perfecto {EMOJI_OK} con el CP {cp} reviso opciones de paqueteria para su pedido."

    if principal in ("pago", "comprobante"):
        return f"Perfecto {EMOJI_OK} me puede mandar foto del comprobante para revisarlo, por favor."

    if principal == "producto_no_manejado":
        return _respuesta_producto_no_manejado(texto, productos)

    if principal == "iniciar_pedido" and not resolucion.get("pedidos"):
        hilo = _hilo_display(contexto.get("hilo_actual") or "")
        if contexto.get("total_esperado"):
            return f"Claro {EMOJI_OK} le cotizo su pedido de {hilo or 'ese hilo'}. Mándeme los códigos o colores y se lo preparo."
        if hilo:
            return f"Claro {EMOJI_OK} mándeme la lista cuando guste y se la cotizo en {hilo}."
        return f"Claro {EMOJI_OK} mándeme la lista cuando guste y con gusto se la cotizo."

    if principal == "correccion_pedido":
        nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto)
        mem = contexto.get("memoria_previa") or {}
        prev = _cargar_lista_pendiente(mem)
        # Respuesta humana: no prometemos que ya quedó aplicado si falta UI, pero sí entendemos la corrección.
        if re.search(r"\b(quita|quitame|quítame|quite|quitar)\b", texto) and nums:
            extra_prev = ""
            if prev:
                cods = ", ".join(str(x.get("codigo") or x.get("codigo_raw") or "").strip() for x in prev[:6] if (x.get("codigo") or x.get("codigo_raw")))
                if cods:
                    extra_prev = f" Tenía en la lista: {cods}."
            return f"Claro {EMOJI_OK} corrijo la cotización: quito el código {nums[-1]}.{extra_prev} Le actualizo la lista para que quede correcto."
        if nums:
            return f"Claro {EMOJI_OK} corrijo la cotización y dejo el código {nums[-1]} como me indica. Le actualizo el pedido."
        return f"Claro {EMOJI_OK} con gusto le corrijo la cotización. ¿Me confirma qué tono o cantidad cambiamos?"

    if resolucion.get("pedidos"):
        return _respuesta_pedido(resolucion, contexto)

    fallback = _respuesta_fallback_humana(normalizado, intencion, contexto, extraccion, resolucion)
    if fallback:
        return fallback

    if resolucion.get("preguntas"):
        return _respuesta_pregunta_corta(resolucion, contexto)

    if principal == "agradecimiento":
        return ""

    return f"Con gusto {EMOJI_OK} ¿me indica qué hilo, color o código busca para revisarlo bien?"


def _primer_codigo(texto):
    m = re.search(r"\b\d{1,4}\b", str(texto or ""))
    return m.group(0) if m else ""


def _respuesta_precio(contexto, productos):
    hilo = contexto.get("hilo_actual") or ""
    if not hilo:
        return f"Claro {EMOJI_OK} ¿me confirma qué hilo o código quiere revisar para darle el precio exacto?"
    ctx = _filtrar_contexto(productos, contexto)
    precios = [_precio(p) for p in ctx if _precio(p) > 0 and _no_combo(p)]
    nombre = _hilo_display(hilo)
    if not precios:
        return f"Sí manejamos {nombre} {EMOJI_OK} ¿me indica el código o color para revisarle el precio exacto?"
    mn, mx = min(precios), max(precios)
    precio = f"${mn:,.2f}" if abs(mn - mx) < 0.01 else f"desde ${mn:,.2f}"
    return f"El {nombre} está en {precio} por madeja {EMOJI_OK} ¿busca algún color o código en especial?"


def _respuesta_consulta_stock_detallada(contexto, productos, texto, resolucion, extraccion):
    hilo = contexto.get("hilo_actual") or ""
    nombre = _hilo_display(hilo) if hilo else ""
    pedidos = resolucion.get("pedidos") or []
    preguntas = resolucion.get("preguntas") or []

    # Pregunta sencilla: "¿Manejan Komfy Mini?"
    if _pide_solo_existencia_hilo(texto) and hilo:
        return f"Sí {EMOJI_OK} manejamos {nombre}. ¿Le comparto la gama de colores o busca algún tono en especial?"

    # Pregunta de disponibilidad de color: "¿Tienen Velluto blanco?"
    if pedidos:
        p = pedidos[0]
        linea = _linea_producto(p)
        stock = int(p.get("stock") or 0)
        if stock > 0:
            return f"Sí {EMOJI_OK} tengo disponible {linea}. ¿Cuántas piezas le agrego a su cotización?"
        return f"Por el momento no me aparece disponible {linea} {EMOJI_SAD} Si gusta le muestro tonos parecidos."

    if preguntas and _hay_color_en_texto(texto):
        fb = _respuesta_fallback_humana({"texto": texto}, {"principal": "consulta_stock"}, contexto, extraccion, resolucion)
        if fb:
            return fb
        # Pregunta amable, sin lenguaje tecnico.
        return _respuesta_pregunta_corta(resolucion, contexto)

    return _respuesta_stock_colores(contexto, productos, texto)


def _respuesta_stock_colores(contexto, productos, texto):
    hilo = contexto.get("hilo_actual") or ""
    if not hilo:
        return f"Claro {EMOJI_OK} ¿de qué hilo le reviso los tonos: Velluto, Komfy Mini u otro?"
    ctx = [p for p in _filtrar_contexto(productos, contexto) if _stock(p) > 0 and _no_combo(p)]
    nombre = _hilo_display(hilo)
    if not ctx:
        return f"Por el momento no me aparece stock disponible de {nombre}. Le reviso alguna alternativa?"
    lineas = []
    seen = set()
    for p in ctx:
        key = (str(p.get("codigo") or ""), _norm(p.get("color") or ""))
        if key in seen:
            continue
        seen.add(key)
        lineas.append(f"- {p.get('codigo')} {p.get('color')}".strip())
        if len(lineas) >= 24:
            break
    if len(ctx) > 24:
        muestra = ", ".join(ln.replace("- ", "") for ln in lineas[:10])
        return f"Tengo varios tonos disponibles de {nombre} {EMOJI_OK} Algunos son: {muestra}. Busca algun color en especial o le comparto la carta?"
    return f"Claro {EMOJI_OK} de {nombre} tengo disponibles estos tonos:\n" + "\n".join(lineas)


def _respuesta_producto_no_manejado(texto, productos):
    alternativas = []
    for fam in ("KURUMI", "KOMFY MINI", "VELLUTO"):
        if any(_hilo_family(p.get("hilo")) == fam and _stock(p) > 0 for p in productos or []):
            alternativas.append(_hilo_display(fam))
    extra = ", ".join(alternativas[:3]) if alternativas else "otras opciones del catalogo"
    if "abuelita" in _norm(texto):
        return f"La Abuelita por el momento no la manejamos {EMOJI_OK} pero le puedo mostrar opciones parecidas que sí tenemos, como {extra}. ¿Para qué proyecto lo ocuparía?"
    return f"Por el momento no me aparece ese producto en almacén {EMOJI_OK} pero puedo revisarle opciones que sí tenemos, como {extra}."


def _respuesta_pregunta_corta(resolucion, contexto):
    q = resolucion["preguntas"][0]
    q = _limpiar_pregunta_publica(q, contexto)
    return q


def _limpiar_pregunta_publica(q, contexto=None):
    contexto = contexto or {}
    original = str(q or "").strip()
    qn = _norm(original)
    hilo = _hilo_display(contexto.get("hilo_actual") or "")

    if "aparece en varios hilos" in qn:
        if hilo:
            return f"Solo confirmo para agregárselo bien {EMOJI_OK} ¿lo quiere en {hilo}?"
        return f"Solo para agregárselo correcto {EMOJI_OK} ¿lo busca en Velluto, Komfy Mini u otro hilo?"
    if "no ubique bien" in qn or "me confirma codigo" in qn:
        return f"Para no ponerle un tono incorrecto {EMOJI_OK} ¿me confirma el código o el color, por favor?"
    if "confirmo el color" in qn:
        return f"Solo para agregárselo correcto {EMOJI_OK} ¿me confirma ese tono, por favor?"
    if "cuantas piezas" in qn:
        return f"Claro {EMOJI_OK} ¿cuántas piezas le agrego?"
    if "lo busca en velluto" in qn:
        return f"Claro {EMOJI_OK} ¿lo busca en Velluto, Komfy Mini o algún otro hilo?"

    q = re.sub(r"\b(confianza|parser|advertencia|interno)\b.*", "", original, flags=re.I).strip()
    if not q.endswith("?"):
        q += "?"
    return f"Solo para confirmarle bien {EMOJI_OK} {q}"


def _respuesta_pedido(resolucion, contexto):
    pedidos = resolucion.get("pedidos") or []
    ok = []
    faltantes = []
    agotados = []
    insuficientes = []
    for p in pedidos:
        if p.get("cantidad_pendiente"):
            faltantes.append(p)
        elif p.get("es_inventariable", True) and int(p.get("stock") or 0) <= 0:
            agotados.append(p)
        elif p.get("es_inventariable", True) and int(p.get("stock") or 0) < int(p.get("cantidad") or 1):
            insuficientes.append(p)
        else:
            ok.append(p)

    partes = []
    if ok:
        total = sum(int(p.get("cantidad") or 1) for p in ok)
        lineas = [f"* {_linea_producto(p)} x{int(p.get('cantidad') or 1)}" for p in ok]
        partes.append(f"Claro {EMOJI_OK} le agrego a su cotización:\n\n" + "\n".join(lineas))
        partes.append(f"Total agregado: {total} pieza" + ("s." if total != 1 else "."))
        if contexto.get("total_esperado") and total != int(contexto.get("total_esperado") or 0):
            partes.append(f"Me quedan {int(contexto.get('total_esperado') or 0) - total} piezas por completar de las que me indicó.")
    for p in faltantes:
        partes.append(f"¿Cuántas piezas de {_linea_producto(p)} le agrego?")
    for p in agotados:
        partes.append(f"{_linea_producto(p)} por el momento no me aparece disponible {EMOJI_SAD} ¿Le muestro una opción parecida?")
    for p in insuficientes:
        partes.append(f"De {_linea_producto(p)} me aparecen {int(p.get('stock') or 0)} pieza(s) disponibles y usted pidió {int(p.get('cantidad') or 1)}. ¿Le agrego las disponibles o le muestro otra opción?")
    # Si hay productos correctos pero tambien dudas, no tapamos lo correcto: mostramos lo agregado y
    # pedimos confirmar solo lo que falta.
    pendientes = resolucion.get("preguntas") or []
    errores = resolucion.get("errores") or []
    if pendientes or errores:
        if errores:
            partes.append("Me faltan confirmar estos códigos para no agregarlos mal: " + ", ".join(str(e) for e in errores[:8]) + ".")
        else:
            partes.append(_limpiar_pregunta_publica(pendientes[0], contexto))
    if ok and not faltantes and not agotados and not pendientes and not errores:
        partes.append("Le preparo su cotización del pedido.")
    return "\n\n".join(partes).strip()


def guardar_memoria_conversacion(memoria, normalizado, intencion, contexto, extraccion, resolucion, respuesta):
    nueva = dict(memoria or {})
    pedidos = resolucion.get("pedidos") or []
    items = extraccion.get("items") or []
    total_esperado = contexto.get("total_esperado")
    if total_esperado is None:
        total_esperado = nueva.get("total_esperado") or ""
    nueva.update({
        "hilo_actual": contexto.get("hilo_actual") or nueva.get("hilo_actual") or "",
        "marca_actual": contexto.get("marca_actual") or nueva.get("marca_actual") or "",
        "intencion_actual": intencion.get("principal") or "",
        "estado_actual": contexto.get("estado_actual") or "",
        "ultima_respuesta_enviada": respuesta or "",
        "fecha_ultima_actividad": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "cp_actual": extraccion.get("cp") or contexto.get("cp_actual") or nueva.get("cp_actual") or "",
        "total_esperado": total_esperado,
        "pedido_en_proceso": json.dumps(pedidos[:60], ensure_ascii=False) if pedidos else nueva.get("pedido_en_proceso", "[]"),
    })
    if items and (resolucion.get("preguntas") or resolucion.get("errores") or not pedidos):
        nueva["ultima_lista_pendiente"] = json.dumps(items[:80], ensure_ascii=False)
    elif pedidos and not (resolucion.get("preguntas") or resolucion.get("errores")):
        nueva["ultima_lista_pendiente"] = ""
    if pedidos:
        nueva["ultimo_codigo"] = str(pedidos[-1].get("codigo") or "")
        nueva["ultimo_color"] = str(pedidos[-1].get("color") or "")
    if resolucion.get("preguntas"):
        nueva["ultima_pregunta_hecha"] = resolucion["preguntas"][0]
    if intencion.get("principal") in ("pago", "comprobante"):
        nueva["pago_pendiente"] = True
    if intencion.get("principal") == "envio":
        nueva["datos_envio_pendientes"] = True
    if pedidos:
        nueva["cotizacion_activa"] = True
    return nueva


def _cargar_lista_pendiente(memoria):
    for key in ("ultima_lista_pendiente", "ultima_lista_recibida"):
        raw = (memoria or {}).get(key)
        if not raw:
            continue
        if isinstance(raw, list):
            return [dict(x) for x in raw if isinstance(x, dict)]
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, list):
            out = []
            for it in obj:
                if not isinstance(it, dict):
                    continue
                out.append(_item(
                    codigo=it.get("codigo_raw") or it.get("codigo") or "",
                    cantidad=it.get("cantidad"),
                    desc=it.get("desc") or it.get("color") or "",
                    raw=it.get("raw") or "",
                    fuente=it.get("fuente") or "memoria_lista_pendiente",
                ))
            if out:
                return out
    return []


def manejar_buffer_mensajes(mensajes, ahora=None, buffer_seconds=35):
    ahora = ahora or datetime.now()
    if isinstance(mensajes, str):
        mensajes = [{"texto": mensajes, "fecha": ahora}]
    textos = [str(m.get("texto") or "").strip() for m in mensajes or [] if str(m.get("texto") or "").strip()]
    combinado = "\n".join(textos).strip()
    urgente = bool(re.search(r"\b(ya pague|ya quedo|comprobante|me equivoque|corrige|quita)\b", _norm(combinado)))
    if urgente:
        return {"accion": "procesar_rapido", "texto": combinado, "espera_segundos": 0}
    return {"accion": "procesar", "texto": combinado, "espera_segundos": int(buffer_seconds)}


def manejar_cierre_diferido(normalizado, memoria=None, minutos=5):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    if re.fullmatch(r"(gracias|muchas gracias|ok gracias|perfecto gracias|listo gracias)", texto):
        return {
            "programar": True,
            "minutos": int(minutos),
            "mensaje": f"A sus ordenes {EMOJI_OK} cualquier cosa no dude en escribirme, con gusto le atiendo.",
        }
    return {"programar": False}


def procesar_conversacion_v27(payload, productos, memoria=None, callbacks=None):
    callbacks = callbacks or {}
    texto = payload.get("texto") or ""
    marca_ui = payload.get("marca") or ""
    hilo_ui = payload.get("hilo") or ""

    buffer_info = manejar_buffer_mensajes(texto, buffer_seconds=int(payload.get("buffer_seconds") or 35))
    normalizado = normalizar_texto_cliente(buffer_info["texto"])
    cierre = manejar_cierre_diferido(normalizado, memoria)
    if cierre.get("programar"):
        return {
            "ok": True,
            "motor": "v33_motor_conversacional",
            "normalizado": normalizado,
            "intencion": {"principal": "agradecimiento"},
            "contexto": {},
            "extraccion": {"items": []},
            "resolucion": {"pedidos": [], "preguntas": [], "errores": [], "sugerencias": [], "internos": []},
            "confianza": {"confianza": "alta", "accion_recomendada": "cierre_diferido", "puede_auto_enviar": False},
            "respuesta": "",
            "cierre_diferido": cierre,
            "memoria": dict(memoria or {}),
        }

    intencion = detectar_intencion(normalizado, memoria, productos)
    contexto = extraer_contexto_conversacion(normalizado, intencion, memoria, productos, marca_ui, hilo_ui)
    extraccion = extraer_productos_y_cantidades(normalizado, intencion, contexto)
    if intencion["principal"] == "confirmacion_contexto" and not (extraccion.get("items") or []):
        pendientes = _cargar_lista_pendiente(memoria)
        if pendientes:
            extraccion["items"] = pendientes
            extraccion["reuso_lista_pendiente"] = True

    # Recurso antes de resolver carrito: gama/foto no debe agregar productos.
    recursos = {}
    if callbacks.get("buscar_recurso") and intencion["principal"] in ("pide_gama", "pide_foto_tono"):
        recursos = callbacks["buscar_recurso"](intencion, normalizado, contexto, extraccion) or {}

    resolucion = resolver_productos_con_almacen(extraccion, productos, contexto)
    confianza = calcular_confianza(intencion, contexto, extraccion, resolucion)

    envio = {}
    if callbacks.get("cotizar_envio") and intencion["principal"] == "cp_envio":
        envio = callbacks["cotizar_envio"](extraccion.get("cp") or contexto.get("cp_actual") or "", contexto) or {}

    decision = detectar_decision_pendiente(
        normalizado, intencion, contexto, extraccion, resolucion, confianza,
        productos=productos, envio=envio,
    )
    if decision:
        confianza = {"confianza": "baja", "accion_recomendada": "requiere_humano", "puede_auto_enviar": False}
        respuesta = decision.get("respuesta_provisional") or RESPUESTA_REVISION_HUMANA
    else:
        respuesta = generar_respuesta_vendedora(
            normalizado, intencion, contexto, extraccion, resolucion, confianza,
            productos=productos, recursos=recursos, envio=envio,
        )
    memoria_nueva = guardar_memoria_conversacion(memoria, normalizado, intencion, contexto, extraccion, resolucion, respuesta)

    return {
        "ok": True,
        "motor": "v33_motor_conversacional",
        "normalizado": normalizado,
        "intencion": intencion,
        "contexto": contexto,
        "extraccion": extraccion,
        "resolucion": resolucion,
        "confianza": confianza,
        "respuesta": respuesta,
        "requiere_humano": bool(decision),
        "decision_pendiente": decision or {},
        "cierre_diferido": {"programar": False},
        "buffer": buffer_info,
        "memoria": memoria_nueva,
    }
