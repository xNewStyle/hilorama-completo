import json
import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path


EMOJI_OK = "\U0001f60a"
EMOJI_SAD = "\U0001f614"

INTENCIONES = {
    "saludo",
    "pregunta_precio",
    "pide_gama",
    "pide_foto_tono",
    "consulta_tono",
    "consulta_stock",
    "iniciar_pedido",
    "pedido_lista",
    "correccion_pedido",
    "cancelacion_pedido",
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
    "queja",
    "producto_no_manejado",
    "pregunta_horario",
    "pregunta_promocion",
    "decision_comercial",
    "catalogo_general",
    "recomendacion_producto",
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
    # V38: hilos reales que antes se podían confundir con texto libre si venían con typo.
    "KOTTON MILK": ["kotton milk", "cotton milk", "koton milk", "kotton", "cotton"],
    "BABY BEST": ["baby best", "beby best", "baby", "bebe best"],
    "DIVA": ["diva"],
    "FIORentino MAXI".upper(): ["fiorentino maxi", "fiorentino", "fiorentino maxy"],
}

COLOR_ALIASES = {
    # Ojo: blanco y hueso NO son lo mismo en todos los hilos.
    # Se separan para no convertir "hueso" en blanco cuando la clienta escribió hueso.
    # V34: tonos específicos (cielo, turquesa, lila) van separados de familias amplias
    # como azul/morado para no responder cielo cuando la clienta pidió turquesa.
    "blanco": ["blanco", "blanca", "white"],
    "hueso": ["hueso", "marfil", "crudo", "ivory", "crema"],
    "negro": ["negro", "negra", "black"],
    "rojo": ["rojo", "roja", "rojo escolar", "escolar"],
    "rosa": ["rosa", "rosa bebe", "rosa bb", "pink"],
    "cielo": ["azul cielo", "cielo", "celeste"],
    "turquesa": ["turquesa"],
    "azul": ["azul", "marino"],
    "verde": ["verde", "menta", "pistache", "olivo"],
    "amarillo": ["amarillo", "canario", "mostaza", "oro"],
    "cafe": ["cafe", "cafe oscuro", "cafe claro", "chocolate"],
    "gris": ["gris", "plata"],
    "lila": ["lila", "lavanda"],
    "morado": ["morado", "uva"],
    "naranja": ["naranja", "mandarina", "coral"],
    # V35: camel debe ser tono exacto, no sinónimo genérico de arena/beige.
    # Si la clienta pide camel, no debemos contestar Arena.
    "camel": ["camel"],
    "beige": ["beige", "arena", "piel", "nude", "carne"],
}

NORMALIZACIONES = [
    (r"\bbuenas\s+trades\b", "buenas tardes"),
    (r"\bpwdido\b|\bpedio\b|\bpedidio\b|\bpeddo\b", "pedido"),
    (r"\bgamas\b", "gama"),
    (r"\bganas\s+de\s+colores\b", "gama de colores"),
    (r"\bvigenete\b", "vigente"),
    (r"\bcoti+iza\b", "cotiza"),
    (r"\bcotisar\b|\bcotisarme\b|\bcotizame\b|\bcot[íi]zame\b", "cotiza"),
    (r"\bporfavro\b|\bporfa\b", "por favor"),
    (r"\bkonfy\b|\bkomfi\b|\bcomfy\b", "komfy mini"),
    (r"\bbelluto\b|\bveluto\b|\bvellluto\b|\bvellutto\b|\bbeluto\b", "velluto"),
    (r"\bsinco\b|\bcinko\b|\bcincoo\b", "cinco"),
    (r"\btrez\b|\btresz\b", "tres"),
    (r"\bcuantro\b", "cuatro"),
    (r"\bocupo+\b", "ocupo"),
    (r"\bkiero\b|\bkiiero\b", "quiero"),
    (r"\bcotisas\b", "cotiza"),
    (r"\bazul\s+sielo\b", "azul cielo"),
    (r"\bnesecito\b|\bnececito\b", "necesito"),
    (r"\bmanejaz\b|\bmanejas\b", "manejas"),
    (r"\btendras\b|\btendrias\b", "tienes"),
    (r"\brojo\s+escolr\b", "rojo escolar"),
    (r"\bme\s+surte\b|\bsurteme\b|\bsurteme\b", "quiero pedir"),
    (r"\bme\s+lo\s+pone\b|\bme\s+lo\s+agrega\b", "agregar al pedido"),
    (r"\bme\s+lo\s+aparta\b|\bapartame\b", "agregar al pedido"),
]

QTY_WORDS = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15,
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
    if "kotton" in h or "cotton" in h:
        return "KOTTON MILK"
    if "babybest" in h or h == "baby" or "bebebest" in h:
        return "BABY BEST"
    if "diva" in h:
        return "DIVA"
    if "fiorentino" in h:
        return "FIORENTINO MAXI"
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
    # V38: además de alias fijos, reconocer nombres reales del almacén.
    # Ejemplo: "kotton milk" o "baby best" no deben convertirse en producto inventado.
    for h in hilos_reales:
        hn = _norm(h)
        if hn and re.search(rf"(?<!\w){re.escape(hn)}(?!\w)", t):
            if h not in encontrados:
                encontrados.append(h)
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
    ]
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", t)
    if len(nums) <= 1 and not re.search(r"\b(?:del|de|d|codigo|cod|tono|x)\b|\*", t):
        patrones.append(r"\b(\d{1,3})\s*(?:piezas|madejas|pzas|pz)\b")
    for pat in patrones:
        m = re.search(pat, t)
        if m:
            after = t[m.end():m.end() + 24]
            if re.match(r"\s*(?:del|de|d|codigo|cod|tono|\d{1,4}\b)", after):
                continue
            return int(m.group(1))
    return None


def _es_consulta_manejo(texto):
    """Pregunta tipo: ¿manejan/tienen/venden Komfy Mini?"""
    t = _norm(texto)
    return bool(re.search(r"\b(manejan|maneja|manejas|manejaz|tienen|tiene|tienes|hay|venden|vende|vendes|trabajan|trabaja|trabajas|tendras|tendra|tendran|tendrias)\b", t))


def _es_consulta_accesorio(texto):
    """V38: preguntas por accesorios específicos: relleno, ojos, ganchos, agujas, etc."""
    t = _norm(texto)
    return bool(
        _es_consulta_manejo(t)
        and re.search(r"\b(relleno|delcron|guata|nube|ojo|ojos|seguridad|nariz|narices|flock|gancho|ganchos|aguja|agujas|crochet|ganchillo|alfiler|marcador|marcadores|tijera|silicon|silic[oó]n|fieltro|cinta|boton|botones|cierre)\b", t)
    )


def _memoria_habla_de_accesorio(memoria=None):
    """V40: detecta si el último contexto era accesorio, aunque el mensaje actual solo diga
    'del 4.5', 'bolsa de 100' o 'cuánto'. Evita convertir medidas en códigos de hilo.
    """
    mem = memoria or {}
    campos = [
        mem.get("ultima_respuesta_enviada") or "",
        mem.get("ultima_pregunta_hecha") or "",
        mem.get("hilo_actual") or "",
        mem.get("marca_actual") or "",
    ]
    t = _norm(" ".join(str(x) for x in campos if x))
    return bool(re.search(r"\b(relleno|ojo|ojos|seguridad|nariz|narices|flock|gancho|ganchos|aguja|agujas|crochet|ganchillo|aluminio|bolsa)\b", t))


def _consulta_seguimiento_accesorio(texto, memoria=None):
    """Seguimientos como 'y bolsa de 100 cuánto' o 'ocupo del 4.5 y del 5'."""
    t = _norm(texto)
    if re.search(r"\b(ojo|ojos|seguridad|nariz|narices|flock|gancho|ganchos|aguja|agujas|relleno|bolsa|paquete|mm|aluminio)\b", t):
        return True
    if not _memoria_habla_de_accesorio(memoria):
        return False
    return bool(
        re.search(r"\b(?:del|de)\s*\d+(?:\.\d+)?\b", t)
        or re.search(r"\b\d+(?:\.\d+)?\s*(?:mm|piezas|pz|bolsa|paquete)\b", t)
        or re.search(r"\b(cuanto|precio|cuesta|sale|vale|hay|tienes|tiene|manejas|manejan|necesito|ocupo|amigurumi|amigurumis|chico|chica|pequeno|pequeño|grande|mediano)\b", t)
    )


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






def _codigo_contextual_desde_texto(texto):
    """Extrae un código/tono en preguntas humanas de seguimiento.
    Ejemplos: "429", "el 429", "color 429", "qué color es el 429",
    "stock del 429", "gracias, y el 429", "el 429 cuanto sale".
    """
    t = _norm(texto)
    if _detectar_cp(t):
        return ""
    # No tomar cantidades explícitas como código único.
    if re.search(r"\b\d{1,3}\s*(?:piezas|madejas|pz|pzas)\b", t):
        return ""
    # Quitar relleno típico de WhatsApp sin perder el código.
    t2 = re.sub(r"\b(gracias|ok|okay|va|sale|perfecto|bueno|entonces|y|tambien|también|por\s+favor|porfa)\b", " ", t)
    t2 = re.sub(r"\s+", " ", t2).strip()
    pats = [
        r"\b(?:que\s+color\s+es\s+)?(?:el\s+)?(?:color|tono|codigo|cod)\s*#?(\d{1,4})\b",
        r"\b(?:stock|existencia|disponible|hay|tienes|tiene|manejas|me\s+dices|me\s+puede\s+decir|cuanto|precio|cuesta|sale|vale)\s+(?:del|de|el)?\s*#?(\d{1,4})\b",
        r"\b(?:el|del)\s*#?(\d{1,4})\s*(?:cuanto|precio|cuesta|sale|vale|hay|tienes|color|tono)?\b",
        r"^#?(\d{1,4})$",
    ]
    for texto_busca in (t, t2):
        for pat in pats:
            m = re.search(pat, texto_busca)
            if m:
                return m.group(1).lstrip("0") or m.group(1)
    # Último recurso: si sólo queda un número y hay contexto, úsalo como código informativo.
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", t2)
    if len(nums) == 1 and re.search(r"\b(el|del|tono|color|codigo|cod|gracias|y)\b", t):
        return nums[0].lstrip("0") or nums[0]
    return ""


def _es_pregunta_info_codigo(texto):
    t = _norm(texto)
    return bool(
        re.search(r"\b(que\s+color|color\s+es|tono|codigo|cod|me\s+dices|me\s+puede\s+decir|stock|existencia|disponible|hay|tienes|cuanto|precio|cuesta|sale|vale|foto|imagen|muestra|mostrar|ver|se\s+ve|como\s+se\s+ve)\b", t)
        or re.fullmatch(r"(?:el\s+|del\s+)?#?\d{1,4}", t)
    )


def _es_solicitud_foto_tono(texto):
    t = _norm(texto)
    return bool(re.search(r"\b(foto|imagen|muestra|muestras|muestres|mostrar|ver|enseña|ensena|enseñas|ensenas|se\s+ve|como\s+se\s+ve)\b", t) and re.search(r"\b\d{1,4}\b", t))


def _es_pedido_cantidad_codigo_texto(texto):
    t = _norm(texto)
    qty_pat = r"\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|veinte|treinta"
    if re.search(rf"\b(?:ponme|agregame|agrega|dame|deme|quiero|ocupo|necesito|me\s+llevo|llevare|llevaria|pondria)\b.*\b(?:{qty_pat})\s+(?:del|de|d|codigo|cod|tono)?\s*#?\d{{1,4}}\b", t):
        return True
    if re.search(rf"\b(?:ponme|agregame|agrega|dame|deme|quiero|ocupo|necesito|me\s+llevo|llevare|llevaria)\b.*\b#?\d{{1,4}}\s+(?:{qty_pat})\b", t):
        return True
    return False

def _es_saludo_simple(texto):
    t = _norm(texto)
    # V38: saludos/frases de apertura NO son productos.
    return bool(re.fullmatch(r"(hola+|holaa+|buenas|buenas tardes|buen dia|buenos dias|buenas noches|oye|disculpa|hola una pregunta|oye una pregunta|disculpa una pregunta|buenas una pregunta)", t))


def _es_consulta_catalogo_general(texto):
    """Preguntas de catalogo: no son pedidos ni colores sueltos.
    Ejemplos: que hilos tienes, que marcas manejan, accesorios, ganchos, agujas.
    """
    t = _norm(texto)
    if _es_saludo_simple(t):
        return False
    patrones = [
        r"\bque\s+mas\s+(?:manejan|maneja|tienen|venden)\b",
        r"\bque\s+(?:hilos|estambres|productos|cosas|materiales|articulos|artículos)\s+(?:tienes|tienen|manejan|venden|hay)\b",
        r"\b(?:manejan|maneja|tienen|tiene|venden|vende)\s+(?:otras\s+)?(?:marcas|hilos|estambres|accesorios|agujas|ganchos|gancho|crochet|ganchillo)\b",
        r"\b(?:marcas\s+de\s+hilos|marcas\s+manejan|otras\s+marcas\s+de\s+hilos)\b",
        r"\b(?:accesorios\s+para\s+tejer|agujas\s+o\s+ganchos|ganchos\s+o\s+agujas)\b",
        r"\b(?:y\s+)?de\s+(?:karina|alize|hilorama)\s+(?:que\s+)?(?:tiene|tienen|maneja|manejan|hay)\b",
        r"\b(?:que\s+)?(?:tiene|tienen|manejan|hay)\s+de\s+(?:karina|alize|hilorama)\b",
    ]
    return any(re.search(p, t) for p in patrones)


def _es_consulta_recomendacion(texto):
    """Dudas donde la clienta pide consejo, no una cotizacion literal."""
    t = _norm(texto)
    if _es_saludo_simple(t):
        return False
    return bool(
        re.search(r"\b(recomienda|recomiendas|recomendacion|conviene|sirve\s+para|cual\s+me\s+sirve|que\s+hilo\s+uso|que\s+hilo\s+me\s+conviene)\b", t)
        or re.search(r"\b(amigurumi|amigurumis|muneco|munecos|muñeco|muñecos|peluche|elefante|oso|conejo)\b", t)
        or re.search(r"\b(tipo\s+chenille|chenille|suave|barato|economico|económico|no\s+salga\s+tan\s+caro|no\s+quede\s+duro|quede\s+duro|duro|esponjoso|rellenito)\b", t)
        or re.search(r"\b(busco\s+algo\s+para|algo\s+para\s+(?:peluche|amigurumi|muñeco|muneco))\b", t)
    )


# V53: conocimiento técnico de hilos (Karina/Hilorama) + modismos de venta.
_KB_HILOS_CACHE = None

def _cargar_kb_hilos():
    global _KB_HILOS_CACHE
    if _KB_HILOS_CACHE is not None:
        return _KB_HILOS_CACHE
    data = {"productos": []}
    try:
        ruta = Path(__file__).resolve().parent / "data" / "conocimiento_hilos" / "karina_productos.json"
        if ruta.exists():
            data = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        data = {"productos": []}
    _KB_HILOS_CACHE = data
    return data

def _producto_kb_por_texto(texto, contexto=None):
    t = _norm(texto)
    contexto = contexto or {}
    kb = _cargar_kb_hilos()
    productos = kb.get("productos") or []
    alias_extra = {
        "VELLUTO": ["velluto", "veluto", "belluto", "alize velluto", "terciopelo"],
        "KOMFY MINI": ["komfy mini", "komfi mini", "konfy mini", "comfy mini", "komfy", "komfi"],
        "KOMFY PLUS": ["komfy plus", "komfi plus", "konfy plus", "comfy plus"],
        "KURUMI": ["kurumi", "algodon", "algodón"],
        "KOTTON MILK": ["kotton milk", "cotton milk", "koton milk", "kotton", "algodon acrilico", "algodón acrílico"],
    }
    for prod in productos:
        clave = str(prod.get("clave") or prod.get("nombre") or "").upper()
        nombre = _norm(prod.get("nombre") or clave)
        aliases = [_norm(x) for x in alias_extra.get(clave, [])] + [nombre, _norm(clave)]
        if any(a and a in t for a in aliases):
            return prod
    hilo_ctx = _norm(contexto.get("hilo_actual") or "")
    if hilo_ctx:
        for prod in productos:
            clave = _norm(prod.get("clave") or prod.get("nombre") or "")
            nombre = _norm(prod.get("nombre") or "")
            if hilo_ctx in (clave, nombre) or clave in hilo_ctx or nombre in hilo_ctx:
                return prod
    return None

def _es_pregunta_ficha_hilo(texto):
    t = _norm(texto)
    return bool(re.search(r"\b(ficha|ficha\s+tecnica|ficha\s+técnica|composicion|composición|material|de que esta hecho|de qué está hecho|poliester|poliéster|algodon|algodón|gramos|grs|peso|metro|metros|metraje|mide|rendimiento|rinde|gancho|ganchillo|agujas|aguja|con que se teje|con qué se teje|tejer con|sirve para|recomiendas para|me sirve para|diferencia|comparacion|comparación|cual es mejor|cuál es mejor)\b", t))

def _respuesta_conocimiento_hilo(texto, contexto=None):
    t = _norm(texto)
    prod = _producto_kb_por_texto(t, contexto)
    if not prod:
        return "Con gusto 😊 ¿me indica qué hilo quiere comparar o revisar? Le puedo decir composición, metraje, gancho recomendado o para qué proyecto conviene."
    # V58: si la ficha existe pero no está confirmada, no inventar composición/metraje/gancho.
    if prod.get("datos_tecnicos_confirmados") is False:
        tiene_alguno = any(prod.get(k) not in (None, "", [], {}) and str(prod.get(k)).lower() not in ("por confirmar", "pendiente") for k in ("composicion", "peso_bola", "metraje", "gancho_recomendado", "agujas_recomendadas"))
        if not tiene_alguno:
            nombre_tmp = prod.get("nombre") or prod.get("clave") or "ese hilo"
            return f"Sí 😊 tengo ubicado {nombre_tmp} en el catálogo, pero su ficha técnica completa aún está pendiente de capturar. Para no inventarle composición, metraje o gancho, se lo reviso y le confirmo."

    nombre = prod.get("nombre") or prod.get("clave") or "ese hilo"
    desc = prod.get("descripcion") or ""
    composicion = prod.get("composicion") or "composición por confirmar"
    peso = prod.get("peso_bola") or "peso por confirmar"
    metraje = prod.get("metraje") or "metraje por confirmar"
    gancho = prod.get("gancho_recomendado") or "por confirmar"
    agujas = prod.get("agujas_recomendadas") or "por confirmar"
    usos = prod.get("usos_recomendados") or []
    cuando = prod.get("cuando_recomendar") or ""
    no_rec = prod.get("cuando_no_recomendar") or ""

    if re.search(r"\b(gancho|ganchillo|agujas|aguja|con que se teje|con qué se teje|tejer con)\b", t):
        return f"Para {nombre} se recomienda gancho {gancho} y agujas {agujas} 😊 Depende un poco de qué tan apretado teja y del proyecto."
    if re.search(r"\b(composicion|composición|material|de que esta hecho|de qué está hecho|poliester|poliéster|algodon|algodón)\b", t):
        return f"{nombre} es de {composicion} 😊"
    if re.search(r"\b(gramos|grs|peso|metro|metros|metraje|mide|rendimiento|rinde)\b", t):
        return f"{nombre} pesa {peso} y trae aprox. {metraje} por bola/madeja 😊"
    if re.search(r"\b(diferencia|comparacion|comparación|cual es mejor|cuál es mejor|mejor)\b", t):
        # Respuesta corta con base en productos comunes.
        if "kurumi" in t and ("velluto" in t or "veluto" in t or "belluto" in t):
            return "Velluto queda más suave y pachoncito tipo peluche; Kurumi es algodón y queda con más definición para amigurumi pequeño 😊"
        if "komfy" in t and ("velluto" in t or "veluto" in t or "belluto" in t):
            return "Komfy Mini es chenille más pequeño de 50 g, útil para amigurumis suaves; Velluto es chenille más grande de 100 g y queda más pachoncito 😊"
    if re.search(r"\b(sirve para|recomiendas para|me sirve para|proyecto|amigurumi|muñeco|muneco|peluche|elefante|conejo|oso|abeja|ropa|cobija)\b", t):
        uso_txt = ", ".join(usos[:4]) if usos else "varios proyectos tejidos"
        extra = f" {cuando}" if cuando else ""
        if no_rec:
            extra += f" Si busca otra textura: {no_rec}"
        return f"Sí 😊 {nombre} puede servir para {uso_txt}.{extra}"
    return f"Claro 😊 de {nombre}: {desc} Es de {composicion}, pesa {peso}, trae aprox. {metraje} y se recomienda tejer con gancho {gancho} / agujas {agujas}."


def _es_consulta_tonos_variantes(texto):
    """Seguimientos humanos sobre tonos/colores: no son pedidos aunque haya contexto de hilo."""
    t = _norm(texto)
    if _es_saludo_simple(t):
        return False
    return bool(
        re.search(r"\b(?:no\s+me\s+(?:gustan|gustaron|encantan|encantaron)|no\s+me\s+convencen|no\s+me\s+latieron)\b.*\b(?:tono|tonos|color|colores)\b", t)
        or re.search(r"\b(?:tienes|tendras|hay|manejas|muestras|muestro|me\s+muestras)\b.*\b(?:otros|otras|mas\s+claritos|claritos|claras|claros|oscuros|pastel|vivos)\b", t)
        or re.search(r"\b(?:otros|otras)\s+(?:tonos|colores)\b", t)
    )


def _es_pedido_real_por_texto(texto):
    t = _norm(texto)
    if _es_saludo_simple(t) or _es_consulta_catalogo_general(t) or _es_consulta_tonos_variantes(t) or _es_consulta_recomendacion(t):
        return False
    if re.search(r"\b(cotiza|cotizar|pedido|lista|poner|agregar|quiero|ocupo|necesito|dame|deme|ponme|me\s+llevo|llevare|llevaria)\b", t):
        # Recomendaciones tipo "quiero hacer amigurumis" no son pedido de producto.
        if _es_consulta_recomendacion(t) and not re.search(r"\b\d{1,3}\s*(?:del|de|x|\*)\b", t):
            return False
        return True
    return False


def _es_lista_larga_cruda(normalizado, texto):
    lineas = (normalizado or {}).get("lineas") if isinstance(normalizado, dict) else []
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", _norm(texto))
    if len(lineas or []) >= 4 and len(nums) >= 4:
        return True
    if len(nums) >= 8 and re.search(r"\b(?:x|del|de|d|piezas|otra parte|tambien|también)\b", _norm(texto)):
        return True
    return False


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
    elif _es_saludo_simple(texto):
        principal = "saludo"
    elif re.search(r"\b(?:te|le)?\s*pago\s+(?:en la noche|al rato|mas tarde|más tarde|manana|mañana|hoy|luego|saliendo)\b", texto):
        # V39: promesa de pago futuro no significa que ya pagó; no pedir comprobante todavía.
        principal = "decision_comercial"
        secundaria = "promesa_pago_futuro"
    elif re.search(r"\b(llego|llegó|recibiste|recibio|recibió|te llego|te llegó|me confirmas si llego|me confirmas si llegó|confirmas si llego|confirmas si llegó)\b", texto) and ((memoria or {}).get("pago_pendiente") or re.search(r"comprobante|pago", _norm((memoria or {}).get("ultima_respuesta_enviada") or ""))):
        # V39: seguimiento después de comprobante/pago: responder revisando, no pedir hilo/código.
        principal = "comprobante"
        estado = "esperando_comprobante"
    elif re.search(r"\b(comprobante|ya pague|ya pagado|ya quedo el pago|pago|transferencia|deposito|ticket|recibo)\b", texto):
        principal = "comprobante" if re.search(r"\b(comprobante|ticket|recibo|ya pague|ya quedo)\b", texto) else "pago"
        estado = "esperando_comprobante"
    elif re.search(r"\b(queja|molesta|molesto|enojada|enojado|mal servicio|profeco|denuncia|demandar|fraude|estafa|robo|me voy a quejar|amenaza)\b", texto):
        principal = "queja"
    elif re.search(r"\b(cancelar|cancela|cancelame|cancelar mi pedido|cancelacion|ya no quiero|me arrepenti)\b", texto) and re.search(r"\b(pedido|compra|nota|todo|producto|productos)\b", texto):
        principal = "cancelacion_pedido"
    elif cp:
        principal = "cp_envio"
        estado = "esperando_datos_envio"
    elif re.search(r"\b(envio|envios|paqueteria|cuanto sale el envio|costo de envio)\b", texto):
        principal = "envio"
        estado = "esperando_cp"
    elif re.search(r"\b(descuento|rebaja|mejor\s+precio|mejora(?:r|me|s)?\s+(?:el\s+)?precio|mejorarme\s+precio|mejoras\s+precio|precio\s+especial|precio\s+final|menos\s+precio|lo\s+menos|cuanto\s+es\s+lo\s+menos|minimo|mínimo|mayoreo|mayorista|por\s+mayoreo|bajar(?:le)?|ajustar\s+precio)\b", texto):
        principal = "decision_comercial"
    elif _es_pregunta_ficha_hilo(texto) and (hilos or _producto_kb_por_texto(texto, memoria or {})):
        principal = "catalogo_general"
        secundaria = "ficha_hilo"
    elif re.search(r"\b(foto|imagen|muestra|muestras|muestres|mostrar|ver|enseña|ensena|enseñas|ensenas)\b", texto) and re.search(r"\b(ojo|ojos|seguridad|nariz|narices|flock|gancho|ganchos|aguja|agujas|relleno)\b", texto):
        principal = "catalogo_general"
        secundaria = "foto_accesorio"
    elif _es_lista_larga_cruda(normalizado if isinstance(normalizado, dict) else {}, texto):
        principal = "pedido_lista"
        estado = "preparando_cotizacion"
    elif _es_pedido_cantidad_codigo_texto(texto) and (
        (memoria or {}).get("hilo_actual")
        or str((memoria or {}).get("estado_actual") or "") in ("esperando_lista_de_colores", "preparando_cotizacion")
        or re.search(r"\b(tambien|también|estos|otra parte|va otra)\b", texto)
    ):
        principal = "pedido_lista"
        estado = "preparando_cotizacion"
    elif _consulta_seguimiento_accesorio(texto, memoria):
        # V40: no tratar medidas o bolsas de accesorios como códigos de hilo.
        principal = "pregunta_precio" if re.search(r"\b(precio|cuanto|cuesta|costo|vale|sale)\b", texto) else "catalogo_general"
        secundaria = "accesorio_especifico"
    elif _es_consulta_accesorio(texto):
        principal = "catalogo_general"
        secundaria = "accesorio_especifico"
    elif _es_consulta_catalogo_general(texto):
        principal = "catalogo_general"
    elif _es_consulta_tonos_variantes(texto):
        principal = "consulta_stock"
        secundaria = "tonos_variantes"
    elif _es_pregunta_ficha_hilo(texto):
        principal = "catalogo_general"
        secundaria = "ficha_hilo"
    elif _es_consulta_recomendacion(texto):
        principal = "recomendacion_producto"
    elif _es_solicitud_foto_tono(texto):
        principal = "pide_foto_tono"
    elif _codigo_contextual_desde_texto(texto) and _es_pregunta_info_codigo(texto) and not _es_pedido_cantidad_codigo_texto(texto):
        if re.search(r"\b(cuanto|precio|cuesta|sale|vale)\b", texto):
            principal = "pregunta_precio"
            secundaria = "codigo_contextual"
        else:
            principal = "consulta_tono"
            secundaria = "codigo_informativo"
    elif (memoria or {}).get("hilo_actual") and _codigo_contextual_desde_texto(texto) and _es_pregunta_info_codigo(texto) and not _es_pedido_cantidad_codigo_texto(texto) and str((memoria or {}).get("estado_actual") or "") not in ("esperando_lista_de_colores", "preparando_cotizacion"):
        if re.search(r"\b(cuanto|precio|cuesta|sale|vale)\b", texto):
            principal = "pregunta_precio"
            secundaria = "codigo_contextual"
        else:
            principal = "consulta_stock"
            secundaria = "codigo_contextual"
    elif hilos and _es_consulta_manejo(texto) and not _pide_colores_disponibles(texto):
        principal = "consulta_stock"
        secundaria = "consulta_manejan"
    elif (
        re.search(r"\b(gama|carta|catalogo)\b", texto)
        or re.search(r"\b(colores|tonos)\s+(?:disponibles|tienen|manejan|hay)\b", texto)
        or re.search(r"\b(?:que\s+)?(?:colores|tonos)\s+(?:tiene|tienen|hay|manejan)\b", texto)
        or re.search(r"\b(?:tiene|tienen|tienes|hay|manejan|manejas)\b.*\b(?:colores|tonos)\b", texto)
    ):
        # "que colores tiene disponibles" puede ser stock; "manda la gama" es recurso.
        if re.search(r"\b(manda|mandeme|envia|pasa|pasame|comparte|gama|carta|catalogo)\b", texto):
            principal = "pide_gama"
        else:
            principal = "consulta_stock"
    elif _es_solicitud_foto_tono(texto):
        principal = "pide_foto_tono"
    elif re.search(r"\b(cuanto|precio|cuesta|costo|vale|sale)\b", texto):
        principal = "pregunta_precio"
    elif re.search(r"\b(manejan|maneja|tienen|tiene|venden|vende|consiguen)\b.*\b(abuelita|sinfonia|omega|red\s+heart|cisne|nako|estambre\s+la\s+moderna)\b", texto):
        principal = "producto_no_manejado"
    elif re.search(r"\b(?:perdon\s+)?(?:todo|todos|toda|todas)\s+(?:eso\s+)?(?:seria|serian|es|son)?\s*(?:de|en)?\s*(velluto|komfy|kurumi|kairo|trapillo|kotton milk|baby best)\b", texto) and len(re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto)) < 2:
        principal = "confirmacion_contexto"
        estado = "preparando_cotizacion"
    elif re.search(r"\b(quita|quite|quitar|quitame|quítame|corrige|corregir|me equivoque|cambia)\b", texto):
        principal = "correccion_pedido"
    elif _parece_lista_o_pedido(texto, memoria):
        principal = "pedido_lista"
        estado = "preparando_cotizacion"
    elif re.search(r"\b(pedido|cotizar|cotiza|cotizacion|cotización|hacer pedido|agregar al pedido|quiero pedir|lista)\b", texto):
        principal = "iniciar_pedido"
        estado = "esperando_lista_de_colores"
    elif re.search(r"\b(hola|buenas tardes|buen dia|buenos dias|buenas noches)\b", texto):
        principal = "saludo"

    if principal == "iniciar_pedido" and total:
        secundaria = "total_esperado"
    if principal in ("pide_gama", "consulta_stock", "consulta_tono") and hilos:
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
    if _es_saludo_simple(t) or _es_consulta_catalogo_general(t) or _es_consulta_recomendacion(t):
        return False
    # V40: si venimos hablando de accesorios, frases como
    # "ocupo del 4.5 y del 5" son medidas, no códigos de hilos.
    if _consulta_seguimiento_accesorio(t, memoria) and re.search(r"\b(?:del|de)\s*\d+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\s*mm\b", t):
        return False
    qty_pat = r"\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|veinte|treinta"
    if re.search(rf"\b(?:{qty_pat})\s*(?:del|de|d|codigo|cod|tono)\s*\d{{1,4}}\b", t):
        return True
    if re.search(rf"\b\d{{1,4}}\s*x\s*(?:{qty_pat})\b", t):
        return True
    if re.search(rf"\b(?:blanco|negro|rojo|rosa|hueso|camel|beige|arena|cielo|turquesa|lila|amarillo|canario|cafe|gris)\s+(?:{qty_pat})\b", t):
        return True
    if len(re.findall(r"(?<!\d)\d{1,4}(?!\d)", t)) >= 3 and not _detectar_cp(t):
        return True
    # V32: pedidos humanos tipo "quiero 4 blanco de komfy mini" o "ocupo 2 lila".
    if re.search(r"\b(quiero|ocupo|necesito|me\s+cotiza|cotiza|me\s+puede\s+poner|poner|agregar|dame|deme|me\s+llevo|llevare|llevaria)\s+\d{1,3}\s+[a-z]", t):
        return True
    if re.search(r"\b(agregar|quiero pedir|dame|deme|ponme|me puede poner|cotizar|cotiza|me\s+llevo|llevare|llevaria|ocupo|necesito|quiero)\b", t):
        return True
    if "lista" in t and re.search(r"\b\d{1,4}\b", t):
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
    # V39: si el número es medida de accesorio (14 mm, 4.5 mm, bolsa de 100),
    # no inferir Komfy/Velluto por códigos.
    if re.search(r"\b(ojo|ojos|seguridad|gancho|ganchos|aguja|agujas|relleno|bolsa|paquete)\b", t):
        return ""
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


def _contexto_lista_larga_mixta(texto, normalizado, intencion, memoria, hilos):
    if (intencion or {}).get("principal") != "pedido_lista":
        return {"lista_larga": False, "lista_mixta": False, "resolver_global": False}
    lineas = (normalizado or {}).get("lineas") or []
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto)
    familias = {_hilo_family(h) for h in (hilos or []) if _hilo_family(h)}
    texto_n = _norm(texto)
    continuacion = bool(re.search(r"\b(tambien|también|otra parte|va otra|sigue|continuo|continua|faltan|estos tambien)\b", texto_n))
    lista_larga = len(lineas) >= 4 or len(nums) >= 8
    lista_mixta = len(familias) >= 2
    resolver_global = lista_mixta or (continuacion and bool((memoria or {}).get("lista_mixta_activa")))
    return {
        "lista_larga": bool(lista_larga),
        "lista_mixta": bool(lista_mixta),
        "resolver_global": bool(resolver_global),
        "hilos_familia_mencionados": sorted(familias),
    }


def extraer_contexto_conversacion(normalizado, intencion, memoria=None, productos=None, marca_ui="", hilo_ui=""):
    memoria = dict(memoria or {})
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    hilos = intencion.get("hilos_mencionados") or detectar_hilos(texto, productos)
    info_lista = _contexto_lista_larga_mixta(texto, normalizado if isinstance(normalizado, dict) else {}, intencion, memoria, hilos)
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
        # V38: si ya hay pedido/contexto activo, conservar el hilo anterior para mensajes
        # como "y 4 del 99". Solo inferir por código cuando no haya memoria clara.
        if memoria.get("hilo_actual") and intencion.get("principal") in ("pedido_lista", "consulta_stock", "pregunta_precio"):
            hilo = memoria.get("hilo_actual")
            origen = "memoria"
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
        "lista_larga": info_lista.get("lista_larga"),
        "lista_mixta": info_lista.get("lista_mixta"),
        "resolver_global_en_lista": info_lista.get("resolver_global"),
        "hilos_familia_mencionados": info_lista.get("hilos_familia_mencionados") or [],
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

    # V44: mensajes de foto/ver/muestra no deben generar pedidos fantasma.
    if intencion.get("principal") in ("pide_foto_tono", "pide_gama", "consulta_tono", "cancelacion_pedido") or intencion.get("secundaria") == "foto_accesorio":
        return {
            "items": [],
            "cp": intencion.get("cp") or "",
            "total_esperado": intencion.get("total_esperado"),
            "texto_sin_totales": texto_sin_totales,
        }

    # V40: medidas de accesorios no se extraen como productos inventados/códigos.
    if intencion.get("secundaria") == "accesorio_especifico" and _consulta_seguimiento_accesorio(texto, (contexto or {}).get("memoria_previa") or {}):
        return {
            "items": [],
            "cp": intencion.get("cp") or "",
            "total_esperado": intencion.get("total_esperado"),
            "texto_sin_totales": texto_sin_totales,
        }

    # V46/V48: consultas de información sobre un código/tono no son pedidos.
    if (
        intencion.get("principal") in ("consulta_stock", "pregunta_precio", "duda_general", "recomendacion_producto")
        and (
            intencion.get("secundaria") in ("codigo_contextual", "tonos_variantes")
            or (_codigo_contextual_desde_texto(texto) and (contexto or {}).get("hilo_actual"))
            or _es_consulta_tonos_variantes(texto)
            or _es_consulta_recomendacion(texto)
        )
        and not _es_pedido_cantidad_codigo_texto(texto)
    ):
        return {
            "items": [],
            "cp": intencion.get("cp") or "",
            "total_esperado": intencion.get("total_esperado"),
            "texto_sin_totales": texto_sin_totales,
        }

    # 5 del 55, 10 de 60, dos del 55, cinco del 60.
    # V42: entiende abreviaturas y mala escritura ya normalizada:
    # "4 d 60", "sinco del 60", "55 x dos", "429 x uno".
    qty_pat = r"\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|veinte|treinta"

    # V62: listas mixtas por hilo en una sola línea.
    # Ejemplos reales: "velluto 429 x34 y komfy 99 x2",
    # "kurumi 12 x5 y velluto 429 x2".
    # Guardamos el hilo en el item para que el código se resuelva contra
    # esa familia y no contra el contexto previo de la conversación.
    hilo_pat_v62 = r"velluto|veluto|belluto|komfy mini|komfy|komfi|konfy|comfy|kurumi|kairo|trapillo(?: kraft)?|kotton milk|cotton milk|baby best|diva|fiorentino maxi"
    codigo_alpha_pat = r"\d{1,4}[a-z]{1,4}"
    for m in re.finditer(rf"\b({hilo_pat_v62})\s+#?({codigo_alpha_pat})\s*(?:x|\*)\s*({qty_pat})(?!\w)", texto_sin_totales):
        qty = _qty(m.group(3))
        fam = _hilo_family(m.group(1))
        if qty and fam:
            items.append(_item(codigo=m.group(2), cantidad=qty, raw=m.group(0), fuente="hilo_codigo_x_cantidad", hilo=fam))
    for m in re.finditer(rf"\b({hilo_pat_v62})\s+#?(\d{{1,4}})\s*(?:x|\*)\s*({qty_pat})(?!\w)", texto_sin_totales):
        qty = _qty(m.group(3))
        fam = _hilo_family(m.group(1))
        if qty and fam:
            items.append(_item(codigo=m.group(2), cantidad=qty, raw=m.group(0), fuente="hilo_codigo_x_cantidad", hilo=fam))
    for m in re.finditer(rf"\b({hilo_pat_v62})\s+({qty_pat})\s+(?:del|de|d|codigo|cod|tono)?\s*#?(\d{{1,4}})(?!\d)", texto_sin_totales):
        qty = _qty(m.group(2))
        fam = _hilo_family(m.group(1))
        if qty and fam:
            items.append(_item(codigo=m.group(3), cantidad=qty, raw=m.group(0), fuente="hilo_cantidad_codigo", hilo=fam))
    for m in re.finditer(rf"(?<!\w)({qty_pat})\s*(?:piezas?\s*)?(?:del|de|d|codigo|cod|tono)\s*#?(\d{{1,4}})(?!\d)", texto_sin_totales):
        qty = _qty(m.group(1))
        if qty:
            items.append(_item(codigo=m.group(2), cantidad=qty, raw=m.group(0), fuente="cantidad_codigo"))

    # V46: pedidos humanos sin "del": "ponme dos 429", "el 429 dos".
    if intencion.get("principal") == "pedido_lista" or _es_pedido_cantidad_codigo_texto(texto_sin_totales):
        bloques_sin_del = [texto_sin_totales]
        lineas_para_sin_del = normalizado.get("lineas") or []
        if len(lineas_para_sin_del) > 1:
            bloques_sin_del = [_quitar_intro_lista(x) for x in lineas_para_sin_del]
            bloques_sin_del = [x for x in bloques_sin_del if x]
        for bloque in bloques_sin_del:
            for m in re.finditer(rf"\b({qty_pat})\s+(?:piezas?\s*)?(?:el\s+)?#?(\d{{1,4}})(?!\d)", bloque):
                qty = _qty(m.group(1))
                verbo_cercano = bool(re.search(r"\b(ponme|agrega|agregame|dame|deme|quiero|ocupo|necesito|cotiza|cotizar|me\s+llevo)\b", bloque[:m.start()], re.I))
                tiene_piezas = bool(re.search(r"\bpiezas?\b", m.group(0)))
                parece_codigo_cantidad = (
                    str(m.group(1)).isdigit()
                    and qty
                    and (qty > 30 or (str(m.group(2)).isdigit() and int(m.group(2)) <= 30))
                    and _qty(m.group(2)) is not None
                    and not tiene_piezas
                )
                if parece_codigo_cantidad:
                    continue
                if (
                    qty and qty <= 300
                    and not tiene_piezas
                    and not verbo_cercano
                    and qty > 5
                    and len((m.group(2).lstrip("0") or m.group(2))) <= 2
                ):
                    continue
                if qty and qty <= 300 and (qty <= 30 or verbo_cercano or tiene_piezas):
                    items.append(_item(codigo=m.group(2), cantidad=qty, raw=m.group(0), fuente="cantidad_codigo_sin_del"))
            for m in re.finditer(rf"\b(?:el\s+)?#?(\d{{1,4}})\s+({qty_pat})(?!\w)", bloque):
                qty = _qty(m.group(2))
                if qty and qty <= 300:
                    items.append(_item(codigo=m.group(1), cantidad=qty, raw=m.group(0), fuente="codigo_cantidad_sin_x"))

    # el 55 son dos / 60 es cinco
    for m in re.finditer(rf"(?<!\d)(\d{{1,4}})\s*(?:son|es|serian|seria)\s*({qty_pat})(?!\w)", texto_sin_totales):
        qty = _qty(m.group(2))
        if qty:
            items.append(_item(codigo=m.group(1), cantidad=qty, raw=m.group(0), fuente="codigo_cantidad_texto"))

    # 55 x2 / 55 x dos / 55 * 3
    for m in re.finditer(rf"(?<!\w)({codigo_alpha_pat})\s*(?:x|\*)\s*({qty_pat})(?!\w)", texto_sin_totales):
        qty = _qty(m.group(2))
        if qty:
            items.append(_item(codigo=m.group(1), cantidad=qty, raw=m.group(0), fuente="codigo_x_cantidad"))
    for m in re.finditer(rf"(?<!\d)(\d{{1,4}})\s*(?:x|\*)\s*({qty_pat})(?!\w)", texto_sin_totales):
        qty = _qty(m.group(2))
        if qty:
            items.append(_item(codigo=m.group(1), cantidad=qty, raw=m.group(0), fuente="codigo_x_cantidad"))

    # blanco dos y negro cinco / blanco y negro 2 y 4
    # V43: también entiende "blanco y negro, 2 y 4, de velluto".
    # En ese caso 2 y 4 NO son códigos de Velluto, son cantidades de los colores previos.
    colores_simples = r"blanco|negro|rojo|rosa|hueso|camel|beige|arena|cielo|turquesa|lila|amarillo|canario|cafe|gris"
    # V46: "cinco del negro y dos del blanco".
    for m in re.finditer(rf"\b({qty_pat})\s+(?:del|de|d)\s+({colores_simples})(?=\s+y\s+|\s*,|\s+de\s+|$)", texto_sin_totales):
        qty = _qty(m.group(1))
        if qty and qty <= 100:
            items.append(_item(cantidad=qty, desc=m.group(2), raw=m.group(0), fuente="cantidad_color_con_del"))
    m_colores_doble = re.search(
        rf"\b({colores_simples})\s*(?:,)?\s+y\s*({colores_simples})\s*(?:,|\s)+({qty_pat})\s*(?:,)?\s*y\s*({qty_pat})(?=\b|\s*,|\s+de\b|$)",
        texto_sin_totales,
    )
    if m_colores_doble:
        q1 = _qty(m_colores_doble.group(3)); q2 = _qty(m_colores_doble.group(4))
        if q1:
            items.append(_item(cantidad=q1, desc=m_colores_doble.group(1), raw=m_colores_doble.group(0), fuente="color_color_cantidades_v43"))
        if q2:
            items.append(_item(cantidad=q2, desc=m_colores_doble.group(2), raw=m_colores_doble.group(0), fuente="color_color_cantidades_v43"))
    else:
        for m in re.finditer(rf"\b({colores_simples})\s+({qty_pat})(?=\s+y\s+|\s*,|\s+de\s+|$)", texto_sin_totales):
            qty = _qty(m.group(2))
            if qty and qty <= 100:
                items.append(_item(cantidad=qty, desc=m.group(1), raw=m.group(0), fuente="color_cantidad_texto"))

    # Pares raros de WhatsApp:
    # "55 2 60 5 429 1" = codigo/cantidad
    # "2 55 3 60 1 429" = cantidad/codigo
    if not re.search(r"\b(?:del|de|d|codigo|cod|tono|piezas)\b|(?:x|\*)", texto_sin_totales):
        nums_pair = re.findall(r"(?<!\d)(\d{1,4})(?!\d)", texto_sin_totales)
        if len(nums_pair) >= 4 and len(nums_pair) % 2 == 0:
            pairs = list(zip(nums_pair[0::2], nums_pair[1::2]))
            def _is_qty_num(x):
                try:
                    return 1 <= int(x) <= 30
                except Exception:
                    return False
            score_code_qty = sum(1 for a,b in pairs if _codigo_probable(a) and _is_qty_num(b))
            score_qty_code = sum(1 for a,b in pairs if _is_qty_num(a) and _codigo_probable(b))
            if score_code_qty >= max(2, score_qty_code + 1):
                for cod, qtys in pairs:
                    items.append(_item(codigo=cod, cantidad=int(qtys), raw=f"{cod} {qtys}", fuente="codigo_cantidad_pares"))
            elif score_qty_code >= max(2, score_code_qty + 1):
                for qtys, cod in pairs:
                    items.append(_item(codigo=cod, cantidad=int(qtys), raw=f"{qtys} {cod}", fuente="cantidad_codigo_pares"))

    # Blanco 01 - 2 / 216 canario - 4
    for linea in normalizado.get("lineas") or [texto_sin_totales]:
        l = _quitar_intro_lista(linea)
        m = re.fullmatch(rf"({qty_pat})\s+([a-z0-9 áéíóúñü]+?)\s+(?:codigo|cod|tono)\s*#?({codigo_alpha_pat}|\d{{1,4}})", l)
        if m:
            qty = _qty(m.group(1))
            if qty:
                items.append(_item(codigo=m.group(3), cantidad=qty, desc=m.group(2), raw=linea, fuente="cantidad_color_codigo"))
                continue
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

    # 3 rojos y 2 negros.
    # V38: no convertir aperturas como "una pregunta" o typos como "un pedio" en productos inventados.
    permitir_cantidad_color = (
        intencion["principal"] in ("pedido_lista", "consulta_stock")
        or bool(contexto.get("hilo_actual"))
        or _es_pedido_real_por_texto(texto_sin_totales)
    )
    if _es_saludo_simple(texto_sin_totales) or _es_consulta_catalogo_general(texto_sin_totales) or _es_consulta_recomendacion(texto_sin_totales):
        permitir_cantidad_color = False
    # Si ya detectamos cantidades por color con "del negro / del blanco", evitamos duplicar
    # el mismo bloque como un color inventado "negro y dos blanco".
    if any((it.get("fuente") or "") == "cantidad_color_con_del" for it in items):
        permitir_cantidad_color = False
    for m in re.finditer(r"(?<!\d)(\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+([a-z][a-z ]{2,}?)(?=\s+y\s+\d|\s*,|$)", texto_sin_totales):
        if not permitir_cantidad_color:
            continue
        qty = _qty(m.group(1))
        desc = _limpiar_desc_color(m.group(2))
        if qty and qty <= 100 and desc and not desc.startswith(("x ", "y ", "son ", "es ", "todo", "todos", "toda", "todas")) and not re.search(r"\b(pedido|pedio|pregunta|lista|total|piezas)\b", desc):
            items.append(_item(cantidad=qty, desc=desc, raw=m.group(0), fuente="cantidad_color"))

    for linea in normalizado.get("lineas") or [texto_sin_totales]:
        for segmento in re.split(r"[,;]+", linea):
            seg = _quitar_intro_lista(segmento)
            m = re.fullmatch(rf"({qty_pat})\s+([a-z0-9 áéíóúñü]+?)\s+(?:codigo|cod|tono)\s*#?({codigo_alpha_pat}|\d{{1,4}})", seg)
            if m:
                qty = _qty(m.group(1))
                if qty:
                    items.append(_item(codigo=m.group(3), cantidad=qty, desc=m.group(2), raw=seg, fuente="cantidad_color_codigo"))

    # V39/V42: lista de códigos con cantidad global: "55, 60, 429 todos x2".
    # También entiende "todos dos" y, si viene después de una lista, aplica a la cotización previa.
    texto_para_nums = texto_sin_totales
    m_global = re.search(rf"\b(?:todos|todas|todo|cada\s+uno|c/u|c\s+u)\s*(?:x|por|de)?\s*({qty_pat})\b", texto_sin_totales)
    if m_global:
        qty_global = _qty(m_global.group(1))
        prefijo = texto_sin_totales[:m_global.start()]
        nums_global = re.findall(r"(?<!\d)\d{1,4}(?!\d)", prefijo)
        if qty_global:
            if nums_global:
                for n in nums_global:
                    if n and not any((it.get("codigo_raw") or it.get("codigo")) == n for it in items):
                        items.append(_item(codigo=n, cantidad=qty_global, raw=f"{n} x{qty_global}", fuente="codigo_cantidad_global"))
            else:
                # Seguimiento típico:
                # Cliente: 55 / 60 / 429
                # Cliente: todos x2
                pedidos_previos = _cargar_pedido_en_proceso((contexto or {}).get("memoria_previa") or {})
                for pprev in pedidos_previos:
                    cod_prev = str(pprev.get("codigo") or "").strip()
                    if cod_prev and not any((it.get("codigo_raw") or it.get("codigo")) == cod_prev for it in items):
                        items.append(_item(codigo=cod_prev, cantidad=qty_global, raw=f"{cod_prev} x{qty_global}", fuente="memoria_todos_cantidad"))
        texto_para_nums = texto_sin_totales[:m_global.start()] + " " + texto_sin_totales[m_global.end():]

    # Listas puras de codigos.
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto_para_nums)
    if nums and _debe_tomar_codigos_sueltos(texto, intencion, contexto, len(items), len(nums)):
        explicit = {str(it.get("codigo_raw") or it.get("codigo") or "") for it in items}
        cantidad_lista = 1 if len(nums) > 1 else None
        vistos_nums = set()
        for n in nums:
            if n in vistos_nums:
                continue
            vistos_nums.add(n)
            if any(re.search(rf"(?<!\d){re.escape(n)}(?!\d)", str(it.get("raw") or "")) for it in items):
                continue
            if n not in explicit:
                repeticiones = nums.count(n)
                qty_n = repeticiones if repeticiones > 1 else cantidad_lista
                raw_n = f"{n} x{qty_n}" if repeticiones > 1 else n
                items.append(_item(codigo=n, cantidad=qty_n, raw=raw_n, fuente="codigo_suelto"))

    # Color suelto como "azul cielo" o "rojo".
    # V37: no convertir preguntas generales/recomendaciones en productos inventados
    # como "Hilos Tienes x1", "Holaa x1" o "Accesorios Tejer x1".
    if not items and intencion["principal"] in ("pedido_lista", "consulta_stock", "duda_general"):
        permitir_color_suelto = intencion["principal"] in ("pedido_lista", "consulta_stock") or bool(contexto.get("hilo_actual")) or _es_pedido_real_por_texto(texto_sin_totales)
        if not permitir_color_suelto:
            desc = ""
        else:
            desc = _limpiar_desc_color(texto_sin_totales)
        if intencion["principal"] == "consulta_stock" and not _hay_color_en_texto(desc):
            desc = ""
        if desc and re.fullmatch(r"(?:todo|todos|toda|todas)\s*(?:x|por|de)?\s*(?:\d{1,3}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)", _norm(desc)):
            desc = ""
        if desc and intencion["principal"] == "pedido_lista" and not _hay_color_en_texto(desc) and not detectar_hilos(desc) and not re.search(r"\b(relleno|gancho|ojo|ojos|aguja|trapillo|kraft)\b", _norm(desc)):
            desc = ""
        if desc and re.search(r"[a-z]", desc) and not detectar_hilos(desc) and not _es_saludo_simple(desc) and not _es_consulta_catalogo_general(desc) and not _es_consulta_recomendacion(desc):
            items.append(_item(desc=desc, cantidad=None, raw=desc, fuente="color_suelto"))

    return {
        "items": _dedup_items(items),
        "cp": intencion.get("cp") or "",
        "total_esperado": intencion.get("total_esperado"),
        "texto_sin_totales": texto_sin_totales,
    }


def _item(codigo="", cantidad=None, desc="", raw="", fuente="", hilo=""):
    codigo_raw = str(codigo or "").strip()
    codigo_norm = codigo_raw.lstrip("0") or codigo_raw
    out = {
        "codigo": codigo_norm,
        "codigo_raw": codigo_raw,
        "cantidad": cantidad,
        "desc": _compact(desc),
        "raw": _compact(raw),
        "fuente": fuente,
    }
    if hilo:
        out["hilo"] = _hilo_family(hilo) or str(hilo).strip().upper()
    return out


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
    d = re.sub(r"\b(quiero|dame|deme|ponme|agregar|agregame|apartame|me|puede|podria|poner|apartar|pedido|pedio|pregunta|lista|cotizar|cotiza|color|tono|de|del|el|la|los|las|por favor|favor|tiene|tienen|tienes|manejan|maneja|manejas|hay|busco|busca|necesito|ocupo|quiero|disponible|disponibles|en|un|una|unos|unas|buenas|tardes|buen|dia|paso|pasar)\b", " ", d)
    d = re.sub(r"\b(velluto|komfy mini|komfy|komfi|konfy|comfy|mini|kurumi|kairo|trapillo|kotton milk|kotton|cotton milk|baby best|diva|fiorentino maxi|alize|karina|hilorama)\b", " ", d)
    d = re.sub(r"\b(que|se|vea|tan|no|muy|mas|menos|como|para)\b", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d


def _debe_tomar_codigos_sueltos(texto, intencion, contexto, items_count, nums_count):
    t = _norm(texto)
    mem = (contexto or {}).get("memoria_previa") or {}
    if _consulta_seguimiento_accesorio(t, mem):
        return False
    if re.search(r"\b(ojo|ojos|seguridad|gancho|ganchos|aguja|agujas|relleno|bolsa|paquete)\b", t) and re.search(r"\b\d+(?:\.\d+)?\s*(?:mm|piezas|pz|bolsa)\b", t):
        return False
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


def _codigo_probable(codigo):
    c = str(codigo or "").strip().lstrip("0") or str(codigo or "").strip()
    if not c:
        return False
    if re.fullmatch(r"\d{1,4}[a-z]{1,4}", _norm(c)):
        return True
    if c in VELLUTO_CODE_COLORS:
        return True
    if c.zfill(2) in KOMFY_MINI_CODE_COLORS:
        return True
    # En Hilorama los códigos reales suelen ser de 2 a 4 dígitos.
    return c.isdigit() and len(c) >= 2


def _dedup_items(items):
    # V62: si una lista trae mezcla de hilos, por ejemplo
    # "velluto 429 x34 y komfy 99 x2", primero se detecta el item
    # con hilo forzado y después el regex genérico puede volver a detectar
    # "99 x2" sin hilo. En ese caso conservamos el item con hilo para que
    # no se resuelva usando el contexto anterior (Velluto).
    out = []
    seen = set()
    preferidos = {}
    for idx, it in enumerate(items or []):
        code = it.get("codigo_raw") or it.get("codigo") or ""
        key_base = (code, it.get("desc") or "", it.get("cantidad"))
        hilo = it.get("hilo") or ""
        if key_base not in preferidos or (hilo and not (preferidos[key_base].get("hilo") or "")):
            preferidos[key_base] = it
    for it in items or []:
        code = it.get("codigo_raw") or it.get("codigo") or ""
        key_base = (code, it.get("desc") or "", it.get("cantidad"))
        elegido = preferidos.get(key_base)
        if elegido is not it and (elegido or {}).get("hilo"):
            continue
        key = (code, it.get("desc") or "", it.get("cantidad"), it.get("hilo") or "")
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
    pendientes = []

    for item in extraccion.get("items") or []:
        res = _resolver_item(item, productos, productos_ctx, contexto)
        if res.get("pedido"):
            pedidos.append(res["pedido"])
        preguntas.extend(res.get("preguntas") or [])
        errores.extend(res.get("errores") or [])
        sugerencias.extend(res.get("sugerencias") or [])
        internos.extend(res.get("internos") or [])
        pendientes.extend(res.get("pendientes") or [])

    pedidos = _merge_pedidos(pedidos)
    return {
        "pedidos": pedidos,
        "preguntas": _uniq(preguntas),
        "errores": _uniq(errores),
        "sugerencias": sugerencias,
        "internos": internos,
        "pendientes_items": pendientes[:80],
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
            keys = {raw, raw.lstrip("0") or raw, raw.lower(), raw.upper()}
            keys.add((raw.lstrip("0") or raw).lower())
            keys.add((raw.lstrip("0") or raw).upper())
            for k in keys:
                mp.setdefault(k, []).append(p)
    return mp


def _pendiente_resolucion(item, motivo, contexto=None):
    return {
        "codigo": str((item or {}).get("codigo_raw") or (item or {}).get("codigo") or "").strip(),
        "desc": str((item or {}).get("desc") or "").strip(),
        "cantidad": (item or {}).get("cantidad"),
        "raw": str((item or {}).get("raw") or "").strip(),
        "fuente": str((item or {}).get("fuente") or "").strip(),
        "hilo_contexto": str((contexto or {}).get("hilo_actual") or "").strip(),
        "motivo": motivo,
    }


def _score_producto_codigo(p, contexto=None, codigo_raw=""):
    score = 0.0
    if _no_combo(p):
        score += 40
    stock = _stock(p)
    if stock > 0:
        score += 100 + min(stock, 200) / 10.0
    fam = _hilo_family((p or {}).get("hilo") or "")
    cod = str(codigo_raw or (p or {}).get("codigo") or "").strip()
    if fam == "KOMFY MINI" and (cod.zfill(2) in KOMFY_MINI_CODE_COLORS or cod in KOMFY_MINI_CODE_COLORS):
        score += 15
    if fam == "VELLUTO" and (cod in VELLUTO_CODE_COLORS or cod.lstrip("0") in VELLUTO_CODE_COLORS):
        score += 15
    if fam == _hilo_family((contexto or {}).get("hilo_actual") or "") and not (contexto or {}).get("resolver_global_en_lista"):
        score += 12
    if _precio(p) > 0:
        score += 2
    return score


def _resolver_item(item, productos_all, productos_ctx, contexto):
    codigo = str(item.get("codigo") or "").strip()
    codigo_raw = str(item.get("codigo_raw") or codigo).strip()
    desc = str(item.get("desc") or "").strip()
    qty = item.get("cantidad")
    hilo_ctx = contexto.get("hilo_actual") or ""
    resolver_global = bool((contexto or {}).get("resolver_global_en_lista"))
    fallback_global_lista = resolver_global or bool((contexto or {}).get("lista_larga"))
    out = {"preguntas": [], "errores": [], "sugerencias": [], "internos": [], "pendientes": []}

    prod_por_desc = None
    if desc and hilo_ctx:
        prod_por_desc, opts_desc = _buscar_por_color(productos_ctx, desc)
    else:
        opts_desc = []

    matches = []
    hilo_forzado = item.get("hilo") or ""
    if codigo:
        # V62: cuando el item viene con hilo explícito en la misma línea
        # ("komfy 99 x2"), se resuelve contra esa familia y no contra
        # el hilo memorizado de turnos anteriores.
        if hilo_forzado:
            productos_forzados = [p for p in productos_all if _hilo_family(p.get("hilo")) == _hilo_family(hilo_forzado)]
            force_map = _code_map(productos_forzados)
            matches = force_map.get(codigo_raw) or force_map.get(codigo) or []
        else:
            ctx_map = _code_map(productos_ctx)
            all_map = _code_map(productos_all)
            if resolver_global:
                matches = all_map.get(codigo_raw) or all_map.get(codigo) or []
            else:
                matches = ctx_map.get(codigo_raw) or ctx_map.get(codigo) or []
            # Si hay contexto de hilo pero por marca/filtro no aparecio, buscamos en todo y
            # preferimos el mismo hilo/familia antes de preguntar como ambiguo.
            if not matches:
                all_matches = all_map.get(codigo_raw) or all_map.get(codigo) or []
                if hilo_ctx and all_matches:
                    fam = _hilo_family(hilo_ctx)
                    fam_matches = [p for p in all_matches if _hilo_family(p.get("hilo")) == fam]
                    matches = fam_matches or (all_matches if fallback_global_lista else [])
                elif not hilo_ctx:
                    matches = all_matches

    prod = None
    if matches:
        normales = [p for p in matches if _no_combo(p)]
        matches = normales or matches
        fams = sorted({_hilo_family(p.get("hilo")) for p in matches})
        if not resolver_global and not hilo_ctx and len(fams) > 1:
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
                out["pendientes"].append(_pendiente_resolucion(item, "codigo_ambiguo", contexto))
                return out
        if resolver_global and len(fams) > 1:
            out["internos"].append(f"codigo_ambiguo_resuelto_lista_mixta:{codigo_raw or codigo}")
        if desc:
            compatibles = [p for p in matches if _desc_compatible(p, desc)]
            if compatibles:
                matches = compatibles
        prod_codigo = sorted(matches, key=lambda p: (_score_producto_codigo(p, contexto, codigo_raw), _stock(p)), reverse=True)[0]
        if desc and not _desc_compatible(prod_codigo, desc):
            if prod_por_desc:
                prod = prod_por_desc
                out["internos"].append("color_priorizado_sobre_codigo")
            else:
                out["preguntas"].append(f"Para {item.get('raw')}, confirmo el color antes de agregarlo?")
                out["pendientes"].append(_pendiente_resolucion(item, "color_no_compatible_con_codigo", contexto))
                return out
        else:
            prod = prod_codigo
    elif desc:
        if not hilo_ctx:
            out["preguntas"].append(f"Lo busca en Velluto, Komfy Mini o algun otro hilo?")
            out["pendientes"].append(_pendiente_resolucion(item, "falta_hilo_para_color", contexto))
            return out
        prod, opts_desc = _buscar_por_color(productos_ctx, desc)
        if not prod and opts_desc:
            out["sugerencias"].append({"tipo": "color_parecido", "texto": desc, "opciones": opts_desc[:5]})
            out["preguntas"].append(f"Le muestro opciones parecidas para {desc}?")
            out["pendientes"].append(_pendiente_resolucion(item, "color_parecido_pendiente", contexto))
            return out
        if not prod:
            # V32: si no se resolvió en almacén, no generamos error técnico.
            # Dejamos una pregunta humana que conserva hilo/color para que la respuesta sea útil.
            out["preguntas"].append(f"Me confirma si quiere {desc} en {_hilo_display(hilo_ctx)}?")
            out["pendientes"].append(_pendiente_resolucion(item, "color_no_resuelto", contexto))
            return out
    elif codigo:
        # V32: códigos típicos pueden inferirse por familia para dar respuesta humana,
        # aunque no se pueda generar nota automática sin producto_id.
        fam_ctx = _hilo_family(hilo_ctx) if hilo_ctx else ""
        if fam_ctx == "KOMFY MINI" and (codigo_raw.zfill(2) in KOMFY_MINI_CODE_COLORS or codigo in KOMFY_MINI_CODE_COLORS):
            color = KOMFY_MINI_CODE_COLORS.get(codigo_raw.zfill(2)) or KOMFY_MINI_CODE_COLORS.get(codigo) or ""
            out["preguntas"].append(f"Me confirma Komfy Mini {codigo_raw.zfill(2)} {color}?")
            out["pendientes"].append(_pendiente_resolucion(item, "codigo_inferido_sin_producto", contexto))
            return out
        if fam_ctx == "VELLUTO" and (codigo_raw in VELLUTO_CODE_COLORS or codigo in VELLUTO_CODE_COLORS):
            color = VELLUTO_CODE_COLORS.get(codigo_raw) or VELLUTO_CODE_COLORS.get(codigo) or ""
            out["preguntas"].append(f"Me confirma Velluto {codigo_raw or codigo} {color}?")
            out["pendientes"].append(_pendiente_resolucion(item, "codigo_inferido_sin_producto", contexto))
            return out
        out["errores"].append(codigo_raw or codigo)
        out["preguntas"].append("Me confirma ese codigo para revisarlo bien?")
        out["pendientes"].append(_pendiente_resolucion(item, "codigo_no_resuelto", contexto))
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


def _volumetrico(p):
    for key in ("volumetrico", "peso_volumetrico", "volumetrico_kg", "peso_volumetrico_kg"):
        try:
            val = float((p or {}).get(key) or 0)
            if val > 0:
                return val
        except Exception:
            pass
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

    # V35: primero buscamos coincidencias comerciales exactas por código/color
    # dentro del hilo filtrado. Esto evita que "camel" termine resolviendo
    # como "Arena" solo por pertenecer a la familia beige.
    fam_ctx = ""
    for _p in productos or []:
        fam_ctx = _hilo_family((_p or {}).get("hilo") or "")
        if fam_ctx:
            break
    fallback_codigo, fallback_color = _fallback_codigo_color_por_familia(fam_ctx, color=descn)
    if fallback_codigo:
        exactos = []
        for _p in productos or []:
            if not _no_combo(_p):
                continue
            cod = str((_p or {}).get("codigo") or "").strip()
            col = _norm((_p or {}).get("color") or "")
            if cod.lstrip("0") == fallback_codigo.lstrip("0") or col == _norm(fallback_color):
                exactos.append(_p)
        if exactos:
            exactos.sort(key=lambda p: (-_stock(p), str(p.get("codigo") or "")))
            return exactos[0], exactos[:6]

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
        "producto_id": prod.get("id") or prod.get("producto_id"),
        "codigo": prod.get("codigo"),
        "marca": prod.get("marca") or "",
        "hilo": prod.get("hilo") or "",
        "color": prod.get("color") or "",
        "stock": _stock(prod),
        "precio_venta": _precio(prod),
        "volumetrico": _volumetrico(prod),
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
    pendientes_items = resolucion.get("pendientes_items") or []
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

    if re.search(r"\b(descuento|rebaja|mejor\s+precio|mejora(?:r|me|s)?\s+(?:el\s+)?precio|mejorarme\s+precio|mejoras\s+precio|precio\s+especial|precio\s+final|menos\s+precio|bajar(?:le)?|ajustar\s+precio)\b", texto):
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
        lineas = [
            f"{_linea_producto(p)}: pidio {int(p.get('cantidad') or 1)}, stock {int(p.get('stock') or 0)}"
            for p in insuficientes[:8]
        ]
        return decision(
            "stock_insuficiente",
            "Stock insuficiente en el pedido. " + "; ".join(lineas),
            ["Ofrecer solo piezas disponibles", "Sugerir sustituto con stock", "Responder manualmente"],
            "alta",
        )

    if _requiere_humano_por_ambiguedad(preguntas, errores, sugerencias) or pendientes_items:
        qtxt = " ".join(preguntas or [])
        if errores or pendientes_items:
            codigos = errores or [x.get("codigo") or x.get("raw") or x.get("desc") for x in pendientes_items[:8]]
            return decision(
                "codigo_color_ambiguo",
                "La IA no pudo resolver con seguridad estos renglones del pedido: "
                + ", ".join(str(x) for x in codigos if x)[:240],
                ["Revisar codigo/color en almacen", "Pedir confirmacion a la clienta", "Responder manualmente"],
                "media",
            )
        tiene_ambiguedad_real = (
            any((s or {}).get("tipo") == "color_parecido" for s in sugerencias or [])
            or any(x in _norm(qtxt) for x in ("varios hilos", "confirmo el color", "opciones parecidas"))
        )
        if tiene_ambiguedad_real:
            return decision(
                "codigo_color_ambiguo",
                "La IA no tiene seguridad suficiente para elegir codigo/color sin riesgo. " + (qtxt[:240] or texto[:240]),
                ["Pedir confirmacion a la clienta", "Elegir opcion correcta manualmente", "Responder manualmente"],
                "media",
            )
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




def _campo_producto_texto(p):
    partes = []
    for k in ("marca", "hilo", "codigo", "color", "nombre", "producto", "descripcion", "categoria", "tipo"):
        v = p.get(k) if isinstance(p, dict) else ""
        if v:
            partes.append(str(v))
    return " ".join(partes)


def _es_accesorio_producto(p):
    t = _norm(_campo_producto_texto(p))
    return bool(re.search(r"\b(gancho|ganchos|aguja|agujas|crochet|ganchillo|ojo|ojos|seguridad|alfiler|marcador|tijera|relleno|silicon|fieltro|cinta|boton|botones|cierre|aluminio)\b", t))


def _productos_activos(productos):
    return [p for p in (productos or []) if isinstance(p, dict) and _no_combo(p)]


def _uniq_lista(vals, limite=12):
    out = []
    seen = set()
    for v in vals:
        vv = str(v or "").strip()
        if not vv:
            continue
        key = _norm(vv)
        if key in seen:
            continue
        seen.add(key)
        out.append(vv)
        if len(out) >= limite:
            break
    return out



def _tokens_accesorio_texto(texto):
    t = _norm(texto)
    base = [
        "relleno", "medio kilo", "kilo", "delcron", "guata", "nube",
        "ojo", "ojos", "seguridad", "nariz", "narices", "flock", "negro", "bolsa", "gancho", "ganchos", "aluminio",
        "aguja", "agujas", "crochet", "ganchillo", "alfiler", "marcador", "tijera",
        "silicon", "silicon", "fieltro", "cinta", "boton", "botones", "cierre",
    ]
    toks = [x for x in base if x in t]
    for m in re.finditer(r"\b\d+(?:\.\d+)?\s*(?:mm|m|kilo|kg)?\b", t):
        toks.append(m.group(0).strip())
    return _uniq(toks)


def _buscar_accesorios_texto(texto, productos, limite=5):
    activos = _productos_activos(productos)
    accesorios = [p for p in activos if _es_accesorio_producto(p)]
    toks = _tokens_accesorio_texto(texto)
    if not toks:
        return []
    scored = []
    for p in accesorios:
        pt = _norm(_campo_producto_texto(p))
        score = 0
        for tok in toks:
            tn = _norm(tok)
            if tn and tn in pt:
                score += 3 if re.search(r"\d", tn) else 1
        if score:
            scored.append((score, _stock(p), p))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [p for _, __, p in scored[:limite]]


def _respuesta_accesorio_especifico(texto, productos, incluir_precio=False):
    matches = _buscar_accesorios_texto(texto, productos)
    t = _norm(texto)
    if incluir_precio or re.search(r"\b(precio|cuanto|cuesta|sale|vale|costo)\b", t):
        incluir_precio = True
    if matches:
        lineas = []
        for p in matches[:4]:
            linea = _linea_producto(p)
            stock = _stock(p)
            precio = _precio(p)
            extra = []
            if incluir_precio and precio > 0:
                extra.append(f"${precio:,.2f}")
            if stock > 0:
                extra.append(f"stock {stock}")
            elif p.get("es_inventariable", True):
                extra.append("sin stock disponible")
            if extra:
                linea += " (" + ", ".join(extra) + ")"
            lineas.append(linea)
        if re.search(r"\b(nariz|narices|flock)\b", t) and re.search(r"\b(ojo|ojos|seguridad)\b", t):
            return f"Sí {EMOJI_OK} le reviso nariz flock y ojos de seguridad. En ojos me aparece: " + "; ".join(lineas) + ". ¿Qué medida y cuántas piezas necesita?"
        if re.search(r"\b(nariz|narices|flock)\b", t):
            return f"Sí {EMOJI_OK} le reviso nariz flock. " + ("Me aparece: " + "; ".join(lineas) + ". " if lineas else "") + "¿Qué medida y cuántas piezas necesita?"
        if re.search(r"\b(ojo|ojos|seguridad)\b", t):
            return f"Sí {EMOJI_OK} manejamos ojos de seguridad: " + "; ".join(lineas) + ". ¿Cuántas piezas necesita?"
        if re.search(r"\b(gancho|ganchos|aguja|agujas|crochet|aluminio)\b", t):
            return f"Sí {EMOJI_OK} manejamos ganchos/agujas: " + "; ".join(lineas) + ". ¿Cuántas piezas necesita?"
        return f"Sí {EMOJI_OK} manejamos " + "; ".join(lineas) + ". ¿Cuántas piezas necesita?"
    if re.search(r"\brelleno\b", t):
        return f"Sí {EMOJI_OK} manejamos relleno para amigurumi. Le reviso presentación, precio y stock disponible. ¿Lo busca por pieza o por paquete?"
    if re.search(r"\b(nariz|narices|flock)\b", t) and re.search(r"\b(ojo|ojos|seguridad)\b", t):
        return f"Sí {EMOJI_OK} le reviso nariz flock y ojos de seguridad. ¿Qué medida y cuántas piezas necesita?"
    if re.search(r"\b(nariz|narices|flock)\b", t):
        return f"Sí {EMOJI_OK} le reviso nariz flock. ¿Qué medida necesita?"
    if re.search(r"\b(ojo|ojos|seguridad)\b", t):
        return f"Sí {EMOJI_OK} manejamos ojos de seguridad. ¿Qué medida necesita?"
    if re.search(r"\b(gancho|ganchos|aguja|agujas|crochet)\b", t):
        return f"Sí {EMOJI_OK} manejamos ganchos/agujas para tejer. ¿Qué medida busca?"
    return ""


def _respuesta_catalogo_general(texto, productos):
    t = _norm(texto)
    activos = _productos_activos(productos)
    marcas = _uniq_lista([p.get("marca") for p in activos if p.get("marca")], 8)
    hilos = _uniq_lista([_hilo_display(p.get("hilo")) for p in activos if p.get("hilo") and not _es_accesorio_producto(p)], 10)
    accesorios = _uniq_lista([p.get("hilo") or p.get("color") or p.get("nombre") or p.get("producto") for p in activos if _es_accesorio_producto(p)], 8)

    if _es_consulta_accesorio(texto) or re.search(r"\b(foto|imagen|muestra|mostrar|ver)\b", t) and re.search(r"\b(ojo|ojos|seguridad|nariz|narices|flock|gancho|ganchos|aguja|agujas|relleno)\b", t):
        resp_acc = _respuesta_accesorio_especifico(texto, productos)
        if resp_acc:
            if re.search(r"\b(foto|imagen|muestra|mostrar|ver)\b", t):
                return f"Claro {EMOJI_OK} le reviso foto/imagen del accesorio. " + resp_acc
            return resp_acc

    if re.search(r"\bde\s+karina\b|\bkarina\b", t):
        karina = [p for p in activos if "karina" in _norm(p.get("marca") or "")]
        khilos = _uniq_lista([_hilo_display(p.get("hilo")) for p in karina if p.get("hilo")], 10)
        if khilos:
            return f"De Karina manejamos {', '.join(khilos[:8])} {EMOJI_OK} ¿busca algún color o tipo en especial?"
        return f"De Karina no me aparece una lista clara en este momento {EMOJI_OK}, pero puedo revisarle por nombre, hilo o código."

    if re.search(r"\b(agujas|ganchos|gancho|accesorios|crochet|ganchillo)\b", t):
        if accesorios:
            return f"Sí {EMOJI_OK} también manejamos accesorios para tejer, por ejemplo: {', '.join(accesorios[:6])}. ¿Busca ganchos/agujas de alguna medida?"
        return f"Sí {EMOJI_OK} también manejamos accesorios como ganchos, agujas y ojitos de seguridad. ¿Qué medida busca?"

    if re.search(r"\b(marcas|otras marcas)\b", t):
        if marcas:
            return f"Sí {EMOJI_OK} manejamos varias marcas/productos, entre ellas: {', '.join(marcas[:8])}. En hilos tenemos opciones como {', '.join(hilos[:6]) if hilos else 'varios hilos'}. ¿Qué proyecto va a realizar?"
        return f"Sí {EMOJI_OK} manejamos varias marcas e hilos. ¿Busca algo tipo chenille, algodón/amigurumi o trapillo?"

    if re.search(r"\b(que hilos|hilos tienes|estambres|que mas|productos|materiales)\b", t):
        if hilos:
            extra = f" También manejamos accesorios como {', '.join(accesorios[:4])}." if accesorios else ""
            return f"Claro {EMOJI_OK} manejamos hilos como {', '.join(hilos[:8])}.{extra} ¿Busca algo para amigurumi, ropa, cobija o decoración?"
        return f"Claro {EMOJI_OK} manejamos varios hilos y accesorios. ¿Busca algo para amigurumi, ropa, cobija o decoración?"

    resumen = []
    if hilos:
        resumen.append("hilos como " + ", ".join(hilos[:6]))
    if accesorios:
        resumen.append("accesorios como " + ", ".join(accesorios[:4]))
    if marcas:
        resumen.append("marcas como " + ", ".join(marcas[:5]))
    return f"Sí {EMOJI_OK} manejamos " + ("; ".join(resumen) if resumen else "hilos y accesorios para tejer") + ". ¿Qué proyecto quiere hacer?"


def _respuesta_recomendacion_producto(texto, productos):
    t = _norm(texto)
    # V53: si la recomendación pregunta por un hilo específico, usar ficha técnica primero.
    if _producto_kb_por_texto(t, {}):
        resp_kb = _respuesta_conocimiento_hilo(t, {})
        if resp_kb:
            return resp_kb
    activos = _productos_activos(productos)
    familias_stock = { _hilo_family(p.get("hilo")) for p in activos if _stock(p) > 0 and not _es_accesorio_producto(p) }

    opciones = []
    if "KOMFY MINI" in familias_stock:
        opciones.append("Komfy Mini si busca algo suave tipo chenille y rendidor")
    if "VELLUTO" in familias_stock:
        opciones.append("Velluto si quiere un acabado más pachoncito y suave")
    if "KURUMI" in familias_stock:
        opciones.append("Kurumi si lo necesita para amigurumi con más definición")
    if not opciones:
        opciones = ["Komfy Mini o Velluto para algo suave", "Kurumi para amigurumi con más detalle"]

    if re.search(r"\b(amigurumi|amigurumis|muneco|munecos|muñeco|muñecos)\b", t):
        return f"Para amigurumi le recomendaría {opciones[0]} {EMOJI_OK}. También puedo mostrarle opciones por presupuesto: económica, suave o con más definición. ¿Qué tamaño de muñeco va a hacer?"

    if re.search(r"\b(chenille|suave|barato|economico|no salga tan caro)\b", t):
        return f"Para algo suave tipo chenille y económico, le recomiendo revisar {opciones[0]} {EMOJI_OK}. Si quiere, le muestro colores disponibles y precio para comparar."

    return f"Con gusto {EMOJI_OK} le recomiendo según el proyecto: {', '.join(opciones[:3])}. ¿Qué va a tejer?"

def generar_respuesta_vendedora(normalizado, intencion, contexto, extraccion, resolucion, confianza, productos=None, recursos=None, envio=None):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    principal = intencion["principal"]
    recursos = recursos or {}
    envio = envio or {}

    # V53: ficha técnica de hilos (composición, gancho, metraje, usos) con base editable.
    if intencion.get("secundaria") == "ficha_hilo":
        if recursos.get("respuesta"):
            return recursos["respuesta"]
        return _respuesta_conocimiento_hilo(texto, contexto)

    if principal == "consulta_tono":
        resp_codigo = _respuesta_codigo_contextual(texto, contexto, productos, modo="stock")
        if resp_codigo:
            return resp_codigo

    # V39: si la clienta pregunta "serían 15 piezas, verdad?" se valida contra el pedido activo.
    resp_total = _respuesta_validacion_total(normalizado, intencion, contexto)
    if resp_total:
        return resp_total

    # V46: código/tono de seguimiento con contexto, sin inventar pedidos.
    if intencion.get("secundaria") == "codigo_contextual" or (_codigo_contextual_desde_texto(texto) and contexto.get("hilo_actual") and principal in ("consulta_stock", "pregunta_precio", "duda_general") and not resolucion.get("pedidos")):
        resp_codigo = _respuesta_codigo_contextual(texto, contexto, productos, modo=principal)
        if resp_codigo:
            return resp_codigo

    # V40: seguimiento de accesorios. Ej.: después de "ganchos de aluminio",
    # "ocupo del 4.5 y del 5" debe responder sobre ganchos, no cotizar "Si x5".
    if (
        intencion.get("secundaria") == "accesorio_especifico"
        or (
            principal not in ("pedido_lista", "cp_envio", "envio", "iniciar_pedido", "confirmacion_contexto", "correccion_pedido")
            and _consulta_seguimiento_accesorio(texto, (contexto or {}).get("memoria_previa") or {})
        )
    ):
        mem = (contexto or {}).get("memoria_previa") or {}
        texto_acc = _texto_accesorio_con_memoria(texto, mem)
        resp_acc = _respuesta_accesorio_especifico(texto_acc, productos, incluir_precio=bool(re.search(r"\b(precio|cuanto|cuesta|costo|vale|sale)\b", texto)))
        if resp_acc:
            if intencion.get("secundaria") == "foto_accesorio" or re.search(r"\b(foto|imagen|muestra|mostrar|ver)\b", texto):
                return f"Claro {EMOJI_OK} le reviso foto/imagen del accesorio. " + resp_acc
            return resp_acc
        if re.search(r"\b(gancho|ganchos|aguja|agujas|aluminio)\b", _norm(texto_acc)):
            return f"Sí {EMOJI_OK} le reviso ganchos/agujas en esas medidas y le confirmo stock disponible."
        if re.search(r"\b(nariz|narices|flock)\b", _norm(texto_acc)) and re.search(r"\b(ojo|ojos|seguridad)\b", _norm(texto_acc)):
            return f"Sí {EMOJI_OK} para amigurumi chico le reviso nariz flock y ojos de seguridad chicos, y le confirmo medidas, precio y stock."
        if re.search(r"\b(nariz|narices|flock)\b", _norm(texto_acc)):
            return f"Sí {EMOJI_OK} para amigurumi le reviso nariz flock y le confirmo medida, precio y stock."
        if re.search(r"\b(ojo|ojos|seguridad)\b", _norm(texto_acc)):
            return f"Sí {EMOJI_OK} le reviso ojos de seguridad en esa medida y le confirmo precio y stock."

    if principal == "decision_comercial" and intencion.get("secundaria") == "promesa_pago_futuro":
        return f"Claro {EMOJI_OK} lo reviso en su cotización y le confirmo disponibilidad. Cuando realice el pago me manda su comprobante, por favor."

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
        codigos = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto)
        if len(codigos) > 1:
            return f"Claro {EMOJI_OK} le reviso fotos/imágenes de los tonos " + ", ".join(codigos[:6]) + "."
        codigo = _primer_codigo(texto)
        return f"Claro {EMOJI_OK} le reviso la foto del tono {codigo}."

    if principal == "decision_comercial":
        return RESPUESTA_REVISION_HUMANA

    if principal == "catalogo_general":
        if recursos.get("respuesta") and re.search(r"\b(catalogo|carta|gama|foto|imagen|muestra|mostrar|ver|envia|manda|mandame|pasame|comparte|ficha)\b", texto):
            return recursos["respuesta"]
        return _respuesta_catalogo_general(texto, productos)

    if principal == "recomendacion_producto":
        return _respuesta_recomendacion_producto(texto, productos)

    if principal == "pregunta_precio":
        return _respuesta_precio(contexto, productos)

    if principal == "consulta_stock":
        return _respuesta_consulta_stock_detallada(contexto, productos, texto, resolucion, extraccion)

    if principal == "envio":
        if recursos.get("respuesta") and re.search(r"\b(info|informacion|costos|zonas|reexpedicion|tabla|imagen|foto)\b", texto):
            return recursos["respuesta"]
        return f"Claro {EMOJI_OK} para decirle el costo exacto de envío necesito su código postal (CP), por favor."

    if principal == "cp_envio":
        if envio.get("respuesta"):
            return envio["respuesta"]
        cp = extraccion.get("cp") or contexto.get("cp_actual") or ""
        return f"Perfecto {EMOJI_OK} con el CP {cp} reviso opciones de paqueteria para su pedido."

    if principal in ("pago", "comprobante"):
        if principal == "pago" and recursos.get("respuesta") and re.search(r"\b(datos|cuenta|clabe|transferencia|deposito|depositar|pagar)\b", texto):
            return recursos["respuesta"]
        if re.search(r"\b(llego|llegó|recibiste|confirmas|confirmar|confirmo|confirmas si)\b", texto):
            return f"Con gusto {EMOJI_OK} reviso el comprobante y le confirmo si ya aparece recibido."
        if re.search(r"\b(te mando|mando|envio|envi[oó]|ahorita|adjunto|captura)\b", texto):
            return f"Perfecto {EMOJI_OK} mándeme la foto del comprobante y lo reviso para confirmarle."
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

    if principal == "saludo":
        return f"Hola {EMOJI_OK} con gusto le atiendo. ¿Busca algún hilo, color, accesorio o quiere que le muestre lo que manejamos?"

    if principal == "correccion_pedido":
        if (resolucion.get("correccion_pedido") or {}).get("respuesta"):
            return resolucion["correccion_pedido"]["respuesta"]
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


def _texto_accesorio_con_memoria(texto, memoria=None):
    mem = memoria or {}
    prev = _norm(" ".join([str(mem.get("ultima_respuesta_enviada") or ""), str(mem.get("ultima_pregunta_hecha") or ""), str(mem.get("hilo_actual") or "")]))
    claves = []
    # No reutilizamos toda la respuesta previa porque trae precios/stock y esos números
    # pueden contaminar la búsqueda; solo conservamos el tipo de accesorio.
    if re.search(r"\b(relleno|delcron|guata)\b", prev):
        claves.append("relleno")
    if re.search(r"\b(nariz|narices|flock)\b", prev):
        claves.append("nariz flock")
    if re.search(r"\b(ojo|ojos|seguridad)\b", prev):
        claves.append("ojo seguridad")
    if re.search(r"\b(gancho|ganchos|aguja|agujas|crochet|aluminio)\b", prev):
        claves.append("gancho aluminio")
    return _compact(" ".join(claves + [str(texto or "")]))


def _respuesta_precio(contexto, productos):
    # La respuesta específica por código se maneja antes en generar_respuesta_vendedora.
    hilo = contexto.get("hilo_actual") or ""
    if not hilo:
        mem = contexto.get("memoria_previa") or {}
        prev = _norm(mem.get("ultima_respuesta_enviada") or "")
        if any(x in prev for x in ("relleno", "ojo", "ojos", "seguridad", "nariz", "narices", "flock", "gancho", "ganchos", "agujas")):
            resp_acc = _respuesta_accesorio_especifico(prev, productos, incluir_precio=True)
            if resp_acc:
                return resp_acc
        return f"Claro {EMOJI_OK} ¿me confirma qué hilo, accesorio o código quiere revisar para darle el precio exacto?"
    ctx = _filtrar_contexto(productos, contexto)
    precios = [_precio(p) for p in ctx if _precio(p) > 0 and _no_combo(p)]
    nombre = _hilo_display(hilo)
    if not precios:
        return f"Sí manejamos {nombre} {EMOJI_OK} ¿me indica el código o color para revisarle el precio exacto?"
    mn, mx = min(precios), max(precios)
    precio = f"${mn:,.2f}" if abs(mn - mx) < 0.01 else f"desde ${mn:,.2f}"
    if ctx and all(_es_accesorio_producto(p) for p in ctx):
        return f"El {nombre} está en {precio} {EMOJI_OK} ¿cuántas piezas necesita?"
    return f"El {nombre} está en {precio} por madeja {EMOJI_OK} ¿busca algún color o código en especial?"




def _producto_por_codigo_contexto(productos, contexto, codigo):
    codigo = str(codigo or "").strip().lstrip("0") or str(codigo or "").strip()
    if not codigo:
        return None
    ctx = _filtrar_contexto(productos, contexto) if (contexto or {}).get("hilo_actual") else list(productos or [])
    # Primero match exacto por contexto.
    for p in ctx:
        if str(p.get("codigo") or "").strip().lstrip("0") == codigo:
            return p
    # Luego fallback global.
    for p in productos or []:
        if str(p.get("codigo") or "").strip().lstrip("0") == codigo:
            return p
    return None


def _productos_por_codigo_contexto(productos, contexto, codigo):
    codigo = str(codigo or "").strip().lstrip("0") or str(codigo or "").strip()
    if not codigo:
        return []
    ctx = _filtrar_contexto(productos, contexto) if (contexto or {}).get("hilo_actual") else list(productos or [])
    matches = [
        p for p in ctx
        if str(p.get("codigo") or "").strip().lstrip("0") == codigo
    ]
    return [p for p in matches if _no_combo(p)] or matches


def _respuesta_codigo_contextual(texto, contexto, productos, modo="stock"):
    codigo = _codigo_contextual_desde_texto(texto)
    if not codigo:
        return ""
    hilo = contexto.get("hilo_actual") or ""
    nombre = _hilo_display(hilo) if hilo else ""
    # Si la clienta compara códigos: "4299 o será 429", no inventar.
    nums = []
    for n in re.findall(r"(?<!\d)\d{1,4}(?!\d)", _norm(texto)):
        nn = n.lstrip("0") or n
        if nn not in nums:
            nums.append(nn)
    if len(nums) >= 2 and re.search(r"\b(o|sera|seria|será|sería|mejor)\b", _norm(texto)):
        encontrados = []
        faltantes = []
        for n in nums[:4]:
            pp = _producto_por_codigo_contexto(productos, contexto, n)
            if pp:
                encontrados.append(pp)
            else:
                faltantes.append(n)
        partes = []
        if faltantes:
            partes.append("No me aparece el código " + ", ".join(faltantes) + (f" en {nombre}" if nombre else ""))
        if encontrados:
            partes.append("Sí ubico " + "; ".join(_linea_producto(pp) for pp in encontrados))
        if partes:
            return f"{EMOJI_OK} " + ". ".join(partes) + ". ¿Me confirma cuál tono desea revisar?"
    if not hilo:
        matches = _productos_por_codigo_contexto(productos, contexto, codigo)
        fams = sorted({_hilo_family(p.get("hilo")) for p in matches if p})
        if len(fams) > 1:
            opciones = ", ".join(_hilo_display(f) for f in fams[:4])
            return f"El codigo {codigo} aparece en varios hilos ({opciones}) {EMOJI_OK}. Me confirma en cual lo reviso?"
    p = _producto_por_codigo_contexto(productos, contexto, codigo)
    # Si no encontramos el código exacto, respondemos sin inventar.
    if not p:
        base = f" en {nombre}" if nombre else ""
        return f"No me aparece el código {codigo}{base} {EMOJI_OK}. ¿Me confirma si lo escribió bien o le comparto los tonos disponibles?"
    linea = _linea_producto(p)
    stock = _stock(p)
    precio = _precio(p)
    tn = _norm(texto)
    if re.search(r"\b(que\s+color|color\s+es|me\s+dices|tono)\b", tn) and not re.search(r"\b(stock|hay|tienes|cuanto|precio|sale|cuesta|foto|ver|muestra|imagen)\b", tn):
        color = str(p.get("color") or "").strip()
        return f"El tono {codigo} de {nombre or _hilo_display(p.get('hilo') or '')} es {color or 'ese tono'} {EMOJI_OK}. ¿Quiere que le mande foto o le revise disponibilidad?"
    if re.search(r"\b(cuanto|precio|cuesta|sale|vale)\b", tn):
        precio_txt = f"${precio:,.2f}" if precio > 0 else "precio por confirmar"
        return f"El {linea} está en {precio_txt} {EMOJI_OK}. ¿Cuántas piezas le agrego si le gusta?"
    if re.search(r"\b(foto|imagen|muestra|muestras|muestres|mostrar|ver|enseña|ensena|enseñas|ensenas|se\s+ve|como\s+se\s+ve)\b", tn):
        return f"Claro {EMOJI_OK} le comparto la foto del tono {linea}."
    if stock > 0:
        precio_txt = f" Está en ${precio:,.2f}." if precio > 0 else ""
        return f"Sí {EMOJI_OK} el {linea} me aparece disponible, stock {stock}.{precio_txt} ¿Le mando foto o desea que lo agregue a una cotización?"
    return f"El {linea} sí lo ubico, pero por el momento no me aparece stock disponible {EMOJI_SAD}. ¿Le muestro un tono parecido?"

def _color_compatible_con_solicitud(color_producto, color_solicitado):
    """True si el color de almacén corresponde al color exacto que pidió la clienta.

    V34: evita que una consulta exacta como "Komfy Mini turquesa" termine
    contestando "Cielo" solo porque ambos se parecían por la familia azul.
    """
    color_producto = _norm(color_producto)
    color_solicitado = _norm(color_solicitado)
    if not color_producto or not color_solicitado:
        return True
    if color_solicitado in color_producto or color_producto in color_solicitado:
        return True
    alias_req = []
    canon_req = ""
    for canon, aliases in COLOR_ALIASES.items():
        aliases_norm = [_norm(a) for a in aliases]
        if canon == color_solicitado or any(a and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", color_solicitado) for a in aliases_norm):
            canon_req = canon
            alias_req = aliases_norm
            break
    if not canon_req:
        return False
    if canon_req in color_producto:
        return True
    return any(a and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", color_producto) for a in alias_req)


def _linea_solicitada_por_color(contexto, color_solicitado, producto=None):
    """Construye una línea humana usando el color exacto solicitado.

    Si el almacén eligió un producto cercano pero no compatible, usamos el mapa
    comercial del hilo (por ejemplo Komfy Mini turquesa -> 08 Turquesa) para no
    decirle a la clienta un tono incorrecto.
    """
    hilo = contexto.get("hilo_actual") or (producto or {}).get("hilo") or ""
    nombre = _hilo_display(hilo) if hilo else ""
    cod, col = _fallback_codigo_color_por_familia(hilo, color=color_solicitado)
    if not cod and producto:
        cod = str(producto.get("codigo") or "").strip()
    if not col and producto:
        col = str(producto.get("color") or color_solicitado).strip().title()
    detalle = " ".join(x for x in [nombre, cod, col] if x).strip()
    return detalle or (color_solicitado.title() if color_solicitado else "ese tono")

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
        color_solicitado = _color_solicitado_desde_texto(texto)
        if color_solicitado and not _color_compatible_con_solicitud(p.get("color") or "", color_solicitado):
            linea = _linea_solicitada_por_color(contexto, color_solicitado, p)
        if stock > 0:
            return f"Sí {EMOJI_OK} tengo disponible {linea}. ¿Cuántas piezas le agrego a su cotización?"
        # V34: en preguntas exactas de stock no ofrecemos 'parecidos' de forma automática.
        # El tester lo marcaba como falla y además puede sonar a que cambiamos el color
        # que la clienta pidió. Si quiere alternativas, ella las puede pedir después.
        return f"Por el momento no me aparece disponible {linea} {EMOJI_SAD}."

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
        return f"Claro {EMOJI_OK} Cuantas piezas le agrego?"
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
    # V35: cuando es un pedido y todos los tonos están agotados/insuficientes,
    # no contestamos solo con líneas de stock; damos contexto humano para que
    # se entienda que sí revisamos la cotización/pedido.
    if not ok and (agotados or insuficientes):
        partes.append(f"Le revisé su pedido para cotización {EMOJI_OK}")
    if ok:
        total = sum(int(p.get("cantidad") or 1) for p in ok)
        lineas = [f"* {_linea_producto(p)} x{int(p.get('cantidad') or 1)}" for p in ok]
        partes.append(f"Claro {EMOJI_OK} le agrego a su cotización:\n\n" + "\n".join(lineas))
        partes.append(f"Total agregado: {total} pieza" + ("s." if total != 1 else "."))
        subtotal = sum(int(p.get("cantidad") or 1) * _precio(p) for p in ok)
        if subtotal > 0:
            partes.append(f"Subtotal productos: ${subtotal:,.2f} MXN")
        if contexto.get("total_esperado") and int(contexto.get("total_esperado") or 0) > total:
            partes.append(f"Me quedan {int(contexto.get('total_esperado') or 0) - total} piezas por completar de las que me indicó.")
    for p in faltantes:
        partes.append(f"Cuantas piezas de {_linea_producto(p)} le agrego?")
    for p in agotados:
        partes.append(f"{_linea_producto(p)} por el momento no me aparece disponible {EMOJI_SAD} ¿Le muestro una opción parecida?")
    for p in insuficientes:
        partes.append(f"De {_linea_producto(p)} me aparecen {int(p.get('stock') or 0)} pieza(s) disponibles y usted pidió {int(p.get('cantidad') or 1)}. ¿Le agrego las disponibles o le muestro otra opción?")
    # Si hay productos correctos pero tambien dudas, no tapamos lo correcto: mostramos lo agregado y
    # pedimos confirmar solo lo que falta.
    pendientes = resolucion.get("preguntas") or []
    errores = resolucion.get("errores") or []
    pendientes_solo_cantidad = bool(faltantes) and pendientes and all("cuantas piezas" in _norm(q) for q in pendientes)
    if (pendientes and not pendientes_solo_cantidad) or errores:
        if errores:
            partes.append("Me faltan confirmar estos códigos para no agregarlos mal: " + ", ".join(str(e) for e in errores[:8]) + ".")
        else:
            partes.append(_limpiar_pregunta_publica(pendientes[0], contexto))
    if ok and not faltantes and not agotados and not pendientes and not errores:
        partes.append("Le preparo su cotización del pedido.")
    return "\n\n".join(partes).strip()




def _wa_v52_item_key(item):
    item = item or {}
    pid = str(item.get("producto_id") or item.get("id") or "").strip()
    if pid:
        return "pid:" + pid
    codigo = str(item.get("codigo") or item.get("codigo_raw") or "").strip().upper()
    hilo = _norm(item.get("hilo") or "")
    marca = _norm(item.get("marca") or "")
    color = _norm(item.get("color") or item.get("desc") or "")
    return "|".join([marca, hilo, codigo, color])


def _wa_v52_merge_pedido_en_proceso(memoria_previa, pedidos_nuevos, intencion=None):
    """Mantiene una lista acumulada dentro del hilo de WhatsApp.

    Antes se reemplazaba el pedido_en_proceso con el último mensaje. Eso hacía que,
    si la clienta decía: "35 vellutos" y después "agrega 5 más" y luego preguntaba
    "¿cuánto sería con envío?", el envío se calculara solo con el último turno.
    """
    prev = _cargar_pedido_en_proceso(memoria_previa or {})
    nuevos = [dict(x) for x in (pedidos_nuevos or []) if isinstance(x, dict)]
    if not nuevos:
        return prev[:80]
    principal = (intencion or {}).get("principal") or ""
    if principal not in ("pedido_lista", "iniciar_pedido", "confirmacion_contexto"):
        # Para consultas de stock/foto/precio no se debe convertir en carrito.
        return prev[:80]
    merged = []
    idx = {}
    for it in prev:
        d = dict(it or {})
        k = _wa_v52_item_key(d)
        if k and k not in idx:
            idx[k] = len(merged)
            merged.append(d)
    for it in nuevos:
        d = dict(it or {})
        k = _wa_v52_item_key(d)
        try:
            q = int(float(d.get("cantidad") or 1))
        except Exception:
            q = 1
        d["cantidad"] = max(q, 1)
        if k and k in idx:
            pos = idx[k]
            try:
                q_prev = int(float(merged[pos].get("cantidad") or 1))
            except Exception:
                q_prev = 1
            merged[pos].update({kk: vv for kk, vv in d.items() if vv not in (None, "", [])})
            merged[pos]["cantidad"] = max(q_prev, 0) + max(q, 0)
        else:
            if k:
                idx[k] = len(merged)
            merged.append(d)
    return merged[:80]


def _codigo_key(codigo):
    raw = str(codigo or "").strip()
    return raw.lstrip("0") or raw


def _pedido_filtrar_codigos(pedidos, codigos):
    codigos_norm = {_codigo_key(c) for c in codigos or [] if _codigo_key(c)}
    if not codigos_norm:
        return [dict(p) for p in pedidos or []]
    return [
        dict(p) for p in pedidos or []
        if _codigo_key(p.get("codigo") or p.get("codigo_raw")) not in codigos_norm
    ]


def _resolver_codigo_para_correccion(codigo, cantidad, productos, contexto):
    item = _item(codigo=codigo, cantidad=cantidad, raw=str(codigo), fuente="correccion_sustitucion")
    res = _resolver_item(item, productos or [], _filtrar_contexto(productos or [], contexto or {}), contexto or {})
    return (res.get("pedido") or {}), res


def _aplicar_correccion_pedido(normalizado, intencion, memoria, productos, contexto):
    principal = (intencion or {}).get("principal") or ""
    if principal not in ("correccion_pedido", "cancelacion_pedido"):
        return {}
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    prev = _cargar_pedido_en_proceso(memoria or {})
    if not prev:
        return {
            "respuesta": f"Claro {EMOJI_OK} le ayudo a corregirlo. Ahorita no tengo una lista activa en memoria; me confirma que codigo o cantidad cambiamos?",
            "pedido_en_proceso_actualizado": [],
        }
    if principal == "cancelacion_pedido" or re.search(r"\b(quita|quitame|quitar|borra|elimina|cancela|cancelar)\b.*\b(todo|todos|pedido|lista)\b", texto):
        return {
            "accion": "cancelar_lista",
            "pedido_en_proceso_actualizado": [],
            "respuesta": f"Claro {EMOJI_OK} cancelo la lista de la cotizacion para no dejar nada agregado.",
        }
    nums = re.findall(r"(?<!\d)\d{1,4}(?!\d)", texto)
    m_sust = re.search(r"\b(?:cambia|cambiar|sustituye|sustituir|reemplaza|reemplazar)\b.*?#?(\d{1,4}).*?\b(?:por|a|al)\b\s*#?(\d{1,4})\b", texto)
    if m_sust:
        viejo = _codigo_key(m_sust.group(1))
        nuevo = _codigo_key(m_sust.group(2))
        quitados = [p for p in prev if _codigo_key(p.get("codigo") or p.get("codigo_raw")) == viejo]
        cantidad = sum(int(p.get("cantidad") or 1) for p in quitados) or 1
        pedido_nuevo, res_nuevo = _resolver_codigo_para_correccion(nuevo, cantidad, productos, contexto)
        if not pedido_nuevo:
            pregunta = (res_nuevo.get("preguntas") or ["me confirma el tono nuevo para cambiarlo bien?"])[0]
            return {
                "accion": "sustituir_pendiente",
                "pedido_en_proceso_actualizado": prev[:80],
                "respuesta": f"Claro {EMOJI_OK} antes de cambiarlo, {pregunta}",
            }
        base = _pedido_filtrar_codigos(prev, [viejo])
        actualizado = _merge_pedidos(base + [pedido_nuevo])[:80]
        return {
            "accion": "sustituir",
            "quitar": viejo,
            "agregar": nuevo,
            "pedido_en_proceso_actualizado": actualizado,
            "respuesta": f"Claro {EMOJI_OK} cambio el codigo {viejo} por {_linea_producto(pedido_nuevo)} en su cotizacion.",
        }
    if re.search(r"\b(quita|quitame|quitar|borra|elimina|saca)\b", texto) and nums:
        actualizado = _pedido_filtrar_codigos(prev, nums)[:80]
        quitados = len(prev) - len(actualizado)
        codigos_txt = ", ".join(_codigo_key(n) for n in nums[:6])
        if quitados <= 0:
            return {
                "accion": "quitar_no_encontrado",
                "pedido_en_proceso_actualizado": prev[:80],
                "respuesta": f"Le reviso {EMOJI_OK} no veo el codigo {codigos_txt} en la lista activa. Me confirma cual quitamos?",
            }
        total = sum(int(p.get("cantidad") or 1) for p in actualizado)
        return {
            "accion": "quitar",
            "quitar": codigos_txt,
            "pedido_en_proceso_actualizado": actualizado,
            "respuesta": f"Listo {EMOJI_OK} quito el codigo {codigos_txt} de su cotizacion. Quedan {total} pieza" + ("s." if total != 1 else "."),
        }
    return {
        "accion": "correccion_ambigua",
        "pedido_en_proceso_actualizado": prev[:80],
        "respuesta": f"Claro {EMOJI_OK} con gusto le corrijo la cotizacion. Me confirma que codigo o cantidad cambiamos?",
    }


def guardar_memoria_conversacion(memoria, normalizado, intencion, contexto, extraccion, resolucion, respuesta):
    nueva = dict(memoria or {})
    pedidos = resolucion.get("pedidos") or []
    items = extraccion.get("items") or []
    total_esperado = contexto.get("total_esperado")
    if total_esperado is None:
        total_esperado = nueva.get("total_esperado") or ""
    if "pedido_en_proceso_actualizado" in resolucion:
        pedido_en_proceso = json.dumps((resolucion.get("pedido_en_proceso_actualizado") or [])[:80], ensure_ascii=False)
    elif pedidos:
        pedido_en_proceso = json.dumps(_wa_v52_merge_pedido_en_proceso(nueva, pedidos, intencion), ensure_ascii=False)
    else:
        pedido_en_proceso = nueva.get("pedido_en_proceso", "[]")
    nueva.update({
        "hilo_actual": contexto.get("hilo_actual") or nueva.get("hilo_actual") or "",
        "marca_actual": contexto.get("marca_actual") or nueva.get("marca_actual") or "",
        "intencion_actual": intencion.get("principal") or "",
        "estado_actual": contexto.get("estado_actual") or "",
        "ultima_respuesta_enviada": respuesta or "",
        "fecha_ultima_actividad": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "cp_actual": extraccion.get("cp") or contexto.get("cp_actual") or nueva.get("cp_actual") or "",
        "total_esperado": total_esperado,
        "pedido_en_proceso": pedido_en_proceso,
        "lista_mixta_activa": bool(contexto.get("resolver_global_en_lista") or nueva.get("lista_mixta_activa")),
    })
    if resolucion.get("pendientes_items"):
        nueva["items_pendientes_resolver"] = json.dumps((resolucion.get("pendientes_items") or [])[:80], ensure_ascii=False)
    elif not (resolucion.get("preguntas") or resolucion.get("errores")):
        nueva["items_pendientes_resolver"] = ""
    inferido_sin_hilo_explicito = (
        items
        and contexto.get("origen_contexto") == "inferencia_codigos"
        and not (intencion.get("hilos_mencionados") or [])
    )
    if items and (resolucion.get("preguntas") or resolucion.get("errores") or not pedidos or inferido_sin_hilo_explicito):
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
    if "pedido_en_proceso_actualizado" in resolucion:
        nueva["cotizacion_activa"] = bool(resolucion.get("pedido_en_proceso_actualizado") or [])
    elif pedidos:
        nueva["cotizacion_activa"] = True
    return nueva




def _cargar_pedido_en_proceso(memoria):
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


def _respuesta_validacion_total(normalizado, intencion, contexto):
    texto = normalizado["texto"] if isinstance(normalizado, dict) else _norm(normalizado)
    total = intencion.get("total_esperado")
    if not total or not re.search(r"\b(verdad|correcto|cierto|serian|seria|son|total)\b", texto):
        return ""
    pedidos_previos = _cargar_pedido_en_proceso((contexto or {}).get("memoria_previa") or {})
    if not pedidos_previos:
        return ""
    total_prev = sum(int(p.get("cantidad") or 1) for p in pedidos_previos)
    if total_prev == int(total):
        return f"Sí {EMOJI_OK} correcto, serían {total_prev} piezas en su cotización. Le reviso el total con envío si me pasa su CP."
    return f"Le reviso bien {EMOJI_OK} en la cotización me aparecen {total_prev} piezas, no {int(total)}. Permítame confirmar para no dejarlo mal."

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
    tester_mode = bool(payload.get("tester_mode") or payload.get("modo_tester"))
    dry_run = bool(payload.get("dry_run") or tester_mode)

    buffer_info = manejar_buffer_mensajes(texto, buffer_seconds=int(payload.get("buffer_seconds") or 35))
    normalizado = normalizar_texto_cliente(buffer_info["texto"])
    cierre = manejar_cierre_diferido(normalizado, memoria)
    if cierre.get("programar"):
        return {
            "ok": True,
            "motor": "v62_motor_conversacional",
            "normalizado": normalizado,
            "intencion": {"principal": "agradecimiento"},
            "contexto": {},
            "extraccion": {"items": []},
            "resolucion": {"pedidos": [], "preguntas": [], "errores": [], "sugerencias": [], "internos": []},
            "confianza": {"confianza": "alta", "accion_recomendada": "cierre_diferido", "puede_auto_enviar": False},
            "respuesta": "",
            "cierre_diferido": cierre,
            "memoria": dict(memoria or {}),
            "tester_mode": tester_mode,
            "dry_run": dry_run,
        }

    intencion = detectar_intencion(normalizado, memoria, productos)
    contexto = extraer_contexto_conversacion(normalizado, intencion, memoria, productos, marca_ui, hilo_ui)
    extraccion = extraer_productos_y_cantidades(normalizado, intencion, contexto)
    if intencion["principal"] == "confirmacion_contexto" and not (extraccion.get("items") or []):
        pendientes = _cargar_lista_pendiente(memoria)
        if pendientes:
            extraccion["items"] = pendientes
            extraccion["reuso_lista_pendiente"] = True

    # Recurso antes de resolver carrito: gama/foto/ficha no debe agregar productos.
    recursos = {}
    usa_recurso = (
        intencion["principal"] in ("pide_gama", "pide_foto_tono", "catalogo_general", "envio", "pago")
        or intencion.get("secundaria") in ("ficha_hilo", "foto_accesorio", "accesorio_especifico")
    )
    if callbacks.get("buscar_recurso") and usa_recurso:
        recursos = callbacks["buscar_recurso"](intencion, normalizado, contexto, extraccion) or {}

    resolucion = resolver_productos_con_almacen(extraccion, productos, contexto)
    correccion = _aplicar_correccion_pedido(normalizado, intencion, memoria, productos, contexto)
    if correccion:
        resolucion["correccion_pedido"] = correccion
        if "pedido_en_proceso_actualizado" in correccion:
            resolucion["pedido_en_proceso_actualizado"] = correccion.get("pedido_en_proceso_actualizado") or []
    confianza = calcular_confianza(intencion, contexto, extraccion, resolucion)

    envio = {}
    if callbacks.get("cotizar_envio") and intencion["principal"] in ("cp_envio", "envio"):
        cp_para_envio = extraccion.get("cp") or contexto.get("cp_actual") or ((memoria or {}).get("cp_actual") if isinstance(memoria, dict) else "") or ""
        if cp_para_envio:
            contexto_envio = dict(contexto or {})
            memoria_envio = dict((contexto_envio.get("memoria_previa") or memoria or {}))
            if "pedido_en_proceso_actualizado" in resolucion:
                pedido_envio = (resolucion.get("pedido_en_proceso_actualizado") or [])[:80]
            elif resolucion.get("pedidos"):
                pedido_envio = _wa_v52_merge_pedido_en_proceso(memoria_envio, resolucion.get("pedidos") or [], intencion)
            else:
                pedido_envio = _cargar_pedido_en_proceso(memoria_envio)
            if pedido_envio:
                contexto_envio["pedido_en_proceso_actual"] = pedido_envio
                memoria_envio["pedido_en_proceso"] = json.dumps(pedido_envio[:80], ensure_ascii=False)
                contexto_envio["memoria_previa"] = memoria_envio
            envio = callbacks["cotizar_envio"](cp_para_envio, contexto_envio) or {}

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
        "motor": "v62_motor_conversacional",
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
        "tester_mode": tester_mode,
        "dry_run": dry_run,
    }
