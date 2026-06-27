
import re
import unicodedata
from difflib import SequenceMatcher

# ======================================================
# NÚMEROS Y CANTIDADES COLOQUIALES
# ======================================================
NUM_PALABRA = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3,
    "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9,
    "diez": 10,
    "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "dieciséis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21, "veintiuna": 21,
    "veintidos": 22, "veintidós": 22,
    "veintitres": 23, "veintitrés": 23,
    "veinticuatro": 24, "veinticinco": 25,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
}

CANTIDAD_ALIAS = {
    "par": 2,
    "pareja": 2,
    "media docena": 6,
    "docena": 12,
    "docenita": 12,
}

UNIDADES = (
    r"pz|pza|pzas|pieza|piezas|pzs|pzas\.|pieza\.|piezas\.|"
    r"madeja|madejas|madejita|madejitas|rollo|rollos|bolsa|bolsas|"
    r"unidad|unidades|estambre|estambres|hilo|hilos|lana|lanas|"
    r"velluto|vellutos|veluto|velutos|vello|vellos|komfy|komfis|komfy mini|"
    r"trapillo|trapillos|kraft|chenille|chenil|algodon|algodón"
)

INTRO_PALABRAS = (
    "quiero", "quisiera", "ocupo", "necesito", "dame", "demen", "deme", "dem", "da", "mandame", "mándame",
    "ponme", "agrega", "agregame", "agrégame", "me das", "me puedes dar",
    "te encargo", "encargame", "encárgame", "pasame", "pásame", "echame",
    "échame", "apartame", "apártame", "anotame", "anótame", "meteme",
    "méteme", "me llevas", "llevo", "voy a querer", "va a ser", "serian",
    "serían", "seria", "sería", "me interesan", "me apartas", "se me antojan", "pasame", "pasame porfa", "regalame"
)


def _txt(v):
    return str(v or "").strip()


def _sin_acentos(v):
    v = _txt(v).lower()
    return "".join(c for c in unicodedata.normalize("NFD", v) if unicodedata.category(c) != "Mn")


def norm_codigo(v):
    return _txt(v).lstrip("0") or "0"


def limpiar_texto(texto):
    texto = _sin_acentos(texto)
    # Normaliza errores comunes de escritura de WhatsApp: "de del 55", "de de 55".
    texto = re.sub(r"\bde\s+del\b", "del", texto)
    texto = re.sub(r"\bde\s+de\b", "de", texto)
    texto = re.sub(r"\bdel\s+del\b", "del", texto)
    texto = re.sub(r"\b(?:tambien|también|aparte|ademas|además|mas|más)\b", ",", texto)
    texto = re.sub(r"\[.*?\]", " ", texto)
    texto = re.sub(r"\+?\d{9,}", " ", texto)  # teléfonos
    texto = texto.replace("—>", "->").replace("–>", "->").replace("→", "->")
    texto = texto.replace("×", "x")
    texto = texto.replace(";", "\n")
    texto = re.sub(r"[{}\[\]|]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _ratio(a, b):
    return SequenceMatcher(None, _sin_acentos(a), _sin_acentos(b)).ratio()


def sugerir_codigo(codigo_erroneo, codigos_validos):
    codigo_erroneo = norm_codigo(codigo_erroneo)
    sugerencias = []
    for c in codigos_validos:
        if abs(len(c) - len(codigo_erroneo)) > 1:
            continue
        dif = sum(a != b for a, b in zip(c, codigo_erroneo)) + abs(len(c) - len(codigo_erroneo))
        if dif == 1:
            sugerencias.append(c)
    return sugerencias[:5]


def _producto_map(productos):
    codigos = set()
    for p in productos:
        c = norm_codigo(p.get("codigo"))
        if c != "0":
            codigos.add(c)
        cb = norm_codigo(p.get("codigo_barras"))
        if cb != "0":
            codigos.add(cb)
    return codigos


def _add(pedidos, codigo, cantidad):
    codigo = norm_codigo(codigo)
    try:
        cantidad = int(float(cantidad))
    except Exception:
        cantidad = 0
    if not codigo or codigo == "0" or cantidad <= 0:
        return
    pedidos[codigo] = pedidos.get(codigo, 0) + cantidad


def _numeros(texto):
    return [norm_codigo(n) for n in re.findall(r"\d+", texto)]


def _cantidad_texto(valor):
    valor = _sin_acentos(valor)
    if not valor:
        return None
    if valor.isdigit():
        return int(valor)
    if valor in NUM_PALABRA:
        return NUM_PALABRA[valor]
    if valor in CANTIDAD_ALIAS:
        return CANTIDAD_ALIAS[valor]
    # "media docena", "un par"
    for frase, cant in CANTIDAD_ALIAS.items():
        if frase in valor:
            return cant
    return None


# ======================================================
# COLORES / ALIAS MEXICANOS
# ======================================================
COLOR_ALIAS = {
    "negro": [
        "negro", "negra", "negrito", "negrita", "black", "blac", "blak", "blk",
        "azabache", "obscuro", "oscuro", "charol"
    ],
    "blanco": [
        "blanco", "blanca", "blanquito", "blanquita", "white", "withe", "whit",
        "crudo", "cruda", "hueso", "marfil", "ivory"
    ],
    "rojo": [
        "rojo", "roja", "rojito", "rojita", "red", "reed", "rd", "cereza",
        "escarlata", "navidad"
    ],
    "vino": [
        "vino", "vinotinto", "guinda", "borgona", "burgundy", "tinto"
    ],
    "azul": [
        "azul", "blue", "blu", "azulito", "rey", "azul rey", "marino",
        "azul marino", "cielo", "azul cielo", "celeste", "turquesa"
    ],
    "verde": [
        "verde", "green", "gren", "verdecito", "menta", "limon", "limón",
        "bandera", "militar", "olivo", "pistache"
    ],
    "amarillo": [
        "amarillo", "amarilla", "yellow", "yelow", "mostaza", "canario", "oro"
    ],
    "rosa": [
        "rosa", "rosita", "pink", "rose", "rosa mexicano", "mexicano",
        "fucsia", "fiusha", "fiusha", "fiuscha", "fiusha", "fiucha"
    ],
    "morado": [
        "morado", "morada", "purple", "violeta", "violet", "lila",
        "lavanda", "uva"
    ],
    "gris": [
        "gris", "gray", "grey", "plata", "plateado", "plateada", "silver"
    ],
    "cafe": [
        "cafe", "café", "cafecito", "brown", "marron", "marrón",
        "chocolate", "capuchino", "camel"
    ],
    "naranja": [
        "naranja", "orange", "mandarina", "salmon", "salmón", "coral"
    ],
    "beige": [
        "beige", "crema", "cream", "nude", "arena", "champagne", "champaña", "piel", "perla"
    ],
    "dorado": [
        "dorado", "dorada", "gold", "oro"
    ],
}

ALIAS_A_COLOR = {}
for canon, aliases in COLOR_ALIAS.items():
    for a in aliases:
        ALIAS_A_COLOR[_sin_acentos(a)] = canon
        # Plurales comunes de WhatsApp: negros, negras, blancos, blancas, etc.
        aa = _sin_acentos(a)
        if aa and aa.isalpha() and len(aa) >= 4:
            ALIAS_A_COLOR.setdefault(aa + "s", canon)
            if aa.endswith("o"):
                ALIAS_A_COLOR.setdefault(aa[:-1] + "os", canon)
                ALIAS_A_COLOR.setdefault(aa[:-1] + "as", canon)
            if aa.endswith("a"):
                ALIAS_A_COLOR.setdefault(aa[:-1] + "as", canon)
    ALIAS_A_COLOR[_sin_acentos(canon)] = canon
    ALIAS_A_COLOR.setdefault(_sin_acentos(canon) + "s", canon)


def _normalizar_color(valor):
    v = _sin_acentos(valor)
    if not v:
        return ""
    return ALIAS_A_COLOR.get(v, v)


def _indice_colores(productos):
    """
    Índice de colores del contexto.
    Ejemplo: si en KARINA/TRAPILLO KRAFT existe color NEGRO, entonces
    "black", "blac", "negrito" pueden resolver a ese código.
    """
    color_a_codigos = {}
    nombres_color_reales = {}

    for p in productos:
        codigo = norm_codigo(p.get("codigo"))
        if codigo == "0":
            continue
        color_raw = _txt(p.get("color"))
        if not color_raw:
            continue

        color_norm = _sin_acentos(color_raw)
        color_canon = _normalizar_color(color_raw)

        for clave in {color_norm, color_canon}:
            color_a_codigos.setdefault(clave, [])
            if codigo not in color_a_codigos[clave]:
                color_a_codigos[clave].append(codigo)
            nombres_color_reales[clave] = color_raw

    presentes = set(color_a_codigos.keys())

    for alias, canon in ALIAS_A_COLOR.items():
        if canon in presentes:
            color_a_codigos.setdefault(alias, list(color_a_codigos[canon]))

    # Match aproximado con colores reales, para errores tipo "negr", "blnco", "azl".
    reales = list(nombres_color_reales.keys())
    for real in reales:
        for palabra in real.split():
            if len(palabra) >= 4:
                color_a_codigos.setdefault(palabra, list(color_a_codigos[real]))

    alias_ordenados = sorted(color_a_codigos.keys(), key=len, reverse=True)
    return color_a_codigos, alias_ordenados


def _detectar_colores_en_linea(linea, color_a_codigos, alias_ordenados):
    encontrados = []
    vistos = set()

    for alias in alias_ordenados:
        if not alias:
            continue
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", linea):
            canon = _normalizar_color(alias)
            clave = canon if canon in color_a_codigos else alias
            if clave not in vistos:
                encontrados.append(clave)
                vistos.add(clave)

    # fuzzy simple para palabras sueltas de color
    palabras = [p for p in re.findall(r"[a-zñ]+", linea) if len(p) >= 4]
    for p in palabras:
        if p in ("quiero", "quisiera", "necesito", "ocupo", "pieza", "piezas", "madeja", "madejas"):
            continue
        for alias in alias_ordenados:
            if len(alias) >= 4 and _ratio(p, alias) >= 0.86:
                clave = _normalizar_color(alias)
                if clave not in color_a_codigos:
                    clave = alias
                if clave not in vistos:
                    encontrados.append(clave)
                    vistos.add(clave)
                break

    return encontrados


# ======================================================
# PATRONES DE INTERPRETACIÓN
# ======================================================
def _quitar_intro_cantidad(linea):
    """
    Detecta:
    - quiero 6 de:
    - ocupo 6 de los siguientes
    - 6 piezas de estos
    """
    l = linea.strip()
    # No tomar "dame 2 del 55" como cantidad global; eso es cantidad + código.
    if re.search(rf"\b(?:dame|quiero|quisiera|ocupo|necesito|ponme|agrega|agregame|mandame|pasame|echame|apartame|anotame)?\s*\d+\s*(?:{UNIDADES})?\s*(?:del|de|d|tono|codigo|cod)\s*#?\s*\d+\b", l):
        return None, linea
    intro = "|".join(re.escape(_sin_acentos(x)) for x in INTRO_PALABRAS)

    patrones = [
        rf"^(?:.*?\b)?(?:{intro})?\s*(\d+)\s*(?:{UNIDADES})?\s*(?:del|de\s+los|de\s+las|de\s+estos|de\s+estas|de)\s*[:\-]*\s*(.*)$",
        r"^(?:de|para)\s+estos\s*(\d+)\s*[:\-]*\s*(.*)$",
        r"^(?:cada\s+uno|c/u|cada)\s*(\d+)\s*[:\-]*\s*(.*)$",
    ]
    for pat in patrones:
        m = re.match(pat, l, re.I)
        if m:
            return int(m.group(1)), (m.group(2) or "").strip()
    return None, linea


def _extraer_lista_codigos(texto, codigos_validos):
    cods = []
    for n in _numeros(texto):
        if n in codigos_validos:
            cods.append(n)
    return cods


def _tokenizar_numeros_y_cantidades(seg):
    """Devuelve números y palabras de cantidad en orden.
    Sirve para interpretar secuencias reales de WhatsApp:
    - 55 1 56 2 16  => 55x1, 56x2, 16x1
    - un 55 1 56 2 16 => 55x1, 56x1, 16x2
    - 16 550 => 16 piezas del código 550 si 550 existe
    """
    palabras = sorted(list(NUM_PALABRA.keys()) + list(CANTIDAD_ALIAS.keys()), key=len, reverse=True)
    # media docena debe detectarse como una sola cantidad
    alternos = [re.escape(x) for x in palabras] + [r"\d+"]
    pat = r"(?<!\w)(" + "|".join(alternos) + r")(?!\w)"
    out = []
    for m in re.finditer(pat, _sin_acentos(seg)):
        tok = m.group(1)
        qty = _cantidad_token(tok)
        code = norm_codigo(tok) if tok.isdigit() else None
        out.append({"tok": tok, "qty": qty, "code": code, "is_word": not tok.isdigit(), "start": m.start(), "end": m.end()})
    return out


def _try_qty_code(tokens, codigos_validos):
    if len(tokens) < 2 or len(tokens) % 2 != 0:
        return None
    pairs = []
    for i in range(0, len(tokens), 2):
        qty = tokens[i].get("qty")
        code = tokens[i+1].get("code")
        if not qty or qty <= 0 or qty > 50 or code not in codigos_validos:
            return None
        pairs.append((code, qty))
    return pairs


def _try_code_qty(tokens, codigos_validos):
    if len(tokens) < 2:
        return None
    pairs = []
    i = 0
    while i < len(tokens):
        code = tokens[i].get("code")
        if code not in codigos_validos:
            return None
        qty = 1
        if i + 1 < len(tokens):
            q = tokens[i+1].get("qty")
            # Si el siguiente token es cantidad razonable y después viene otro código
            # o termina la frase, lo tomamos como cantidad del código anterior.
            if q and 1 <= q <= 50:
                if i + 2 >= len(tokens) or tokens[i+2].get("code") in codigos_validos:
                    qty = q
                    i += 2
                    pairs.append((code, qty))
                    continue
        pairs.append((code, qty))
        i += 1
    return pairs


def _parsear_secuencia_numerica_contextual(seg, codigos_validos):
    """Interpreta secuencias compactas sin palabras claras.
    Da preferencia a códigos existentes y evita cantidades absurdas como 550 piezas.
    Cuando realmente puede significar dos cosas (ej. "2 4" y ambos códigos existen),
    no inventa: pide confirmación.
    """
    seg_norm = _sin_acentos(seg)
    tokens = _tokenizar_numeros_y_cantidades(seg_norm)
    if len(tokens) < 2:
        return [], []

    # No intervenir si hay símbolos explícitos; esos los resuelven reglas concretas.
    if re.search(r"\b(?:del|de|d|tono|codigo|cod)\b|[:=x\*\-\>]", seg_norm):
        return [], []

    nums = [t for t in tokens if t.get("code") is not None]
    preguntas = []

    # Caso corto más problemático: "dame 2 4".
    if len(tokens) == 2 and all(t.get("code") is not None for t in tokens):
        a, b = tokens[0]["code"], tokens[1]["code"]
        ia, ib = int(a), int(b)
        a_es, b_es = a in codigos_validos, b in codigos_validos

        # 16 550 => 16 piezas del 550 si el 550 existe.
        if b_es and 1 <= ia <= 50 and (len(b) >= 3 or not a_es):
            return [(b, ia)], []

        # 55 2 => código 55 cantidad 2 si 2 no parece código o el 55 es claramente código largo.
        if a_es and 1 <= ib <= 50 and (len(a) >= 3 or not b_es):
            return [(a, ib)], []

        # 55 56 => dos códigos, 1 de cada uno.
        if a_es and b_es and (len(a) >= 2 and len(b) >= 2):
            return [(a, 1), (b, 1)], []

        # 2 4 => ambiguo: puede ser código 2 y código 4, o 2 piezas del 4.
        if a_es and b_es:
            preguntas.append(f"Confirma '{a} {b}': ¿son códigos {a} y {b}, o {a} piezas del código {b}?")
            return [], preguntas

        return [], []

    # Si son varios códigos largos: 55 56 57 => 1 de cada uno.
    if len(tokens) >= 3 and all(t.get("code") in codigos_validos for t in tokens) and all(len(t.get("code") or "") >= 2 for t in tokens):
        # Pero primero intenta modo código-cantidad por si viene: 55 1 56 2 16.
        cq = _try_code_qty(tokens, codigos_validos)
        if cq and len(cq) < len(tokens):
            return cq, []
        return [(t["code"], 1) for t in tokens], []

    # Modo cantidad-código: "un 55 1 56 2 16" o "1 55 2 16".
    qc = _try_qty_code(tokens, codigos_validos)
    # Modo código-cantidad: "55 1 56 2 16".
    cq = _try_code_qty(tokens, codigos_validos)

    if qc and not cq:
        return qc, []
    if cq and not qc:
        return cq, []
    if qc and cq:
        # Si empieza con palabra de cantidad, se entiende cantidad-código.
        if tokens[0].get("is_word"):
            return qc, []
        # Si empieza con código claramente largo, se entiende código-cantidad.
        if tokens[0].get("code") in codigos_validos and len(tokens[0].get("code") or "") >= 2:
            return cq, []
        preguntas.append("Confirma la secuencia numérica: puede leerse como cantidad-código o código-cantidad.")
        return [], preguntas

    # Si hay muchos números y alguno no existe como código, avisa de forma útil.
    if len(nums) >= 2:
        desconocidos = [t["code"] for t in nums if t.get("code") not in codigos_validos and int(t["code"]) > 50]
        if desconocidos:
            preguntas.append("Revisa estos números; parecen códigos pero no están en el catálogo: " + ", ".join(desconocidos))
    return [], preguntas


def _cantidad_en_linea(linea):
    # 2 pz / 2 madejas / 2 rollos
    m = re.search(rf"\b(\d+)\s*(?:{UNIDADES})\b", linea)
    if m:
        return int(m.group(1))

    # pz 2
    m = re.search(rf"\b(?:{UNIDADES})\s*(\d+)\b", linea)
    if m:
        return int(m.group(1))

    # "un par", "media docena", "docena"
    for frase, cant in CANTIDAD_ALIAS.items():
        if re.search(rf"\b(?:un|una)?\s*{re.escape(frase)}\b", linea):
            return cant

    # palabras
    for palabra, cant in NUM_PALABRA.items():
        if re.search(rf"\b{palabra}\s*(?:{UNIDADES})?\b", linea):
            return cant

    nums = _numeros(linea)
    if len(nums) == 1:
        n = int(nums[0])
        if 1 <= n <= 50:
            return n
    return None


def _extraer_pares_color_cantidad(linea, color_a_codigos, alias_ordenados):
    """
    Soporta varios colores en una línea:
    - 2 negro y 3 blanco
    - negro 2, blanco 1
    - mandame 2 black y 1 white
    - un par de negro
    """
    resultados = []
    partes = re.split(r"\s*(?:,|\by\b|\be\b|\+|/)\s*", linea)

    for parte in partes:
        parte = parte.strip()
        if not parte:
            continue

        colores = _detectar_colores_en_linea(parte, color_a_codigos, alias_ordenados)
        if not colores:
            continue

        cantidad = _cantidad_en_linea(parte)

        # cantidad antes del color: "2 negro", "2 de negro"
        if cantidad is None:
            m = re.search(r"\b(\d+)\s+(?:de\s+)?[a-zñ]+", parte)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 50:
                    cantidad = n

        # color antes de cantidad: "negro 2"
        if cantidad is None:
            m = re.search(r"[a-zñ]+\s+(\d+)\b", parte)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 50:
                    cantidad = n

        if cantidad is None:
            cantidad = 1

        for color in colores:
            resultados.append((color, cantidad))

    # Si no se pudo por partes, intentar línea completa.
    if not resultados:
        colores = _detectar_colores_en_linea(linea, color_a_codigos, alias_ordenados)
        cantidad = _cantidad_en_linea(linea)
        if colores and cantidad:
            for color in colores:
                resultados.append((color, cantidad))

    return resultados



def _extraer_pares_color_cantidad_avanzado(linea, color_a_codigos, alias_ordenados):
    """
    Parser de colores más tolerante para mensajes reales de WhatsApp.
    Entiende cosas como:
    - dem 3 vellutos blanco, tres negros
    - 3 blancos 2 negros
    - blanco 3 negro 2
    - dame tres negros y un blanco
    - 2 de cada blanco negro
    - blanco y negro 3 cada uno
    """
    linea = _sin_acentos(linea)
    resultados = []
    vistos = set()

    # Normaliza errores/coloquialismos comunes.
    linea = re.sub(r"\b(dem|deme|demen)\b", "dame", linea)
    linea = re.sub(r"\bvelutos?\b", "velluto", linea)
    linea = re.sub(r"\b(?:tambien|aparte|ademas|mas)\b", ",", linea)

    # Caso: "2 de cada blanco negro", "3 c/u blanco y negro",
    # o "blanco y negro 3 cada uno".
    cant_pat = _cantidad_pat()

    # Primero revisa cantidad al final, para no leer solo el último color:
    # "blanco y negro 3 cada uno" => blanco=3, negro=3.
    m_each_end = re.search(rf"^(.*?)\b({cant_pat})\s*(?:cada\s*uno|c/u|c/u\.|por\s+color|por\s+tono)\b", linea)
    if m_each_end:
        zona_colores = m_each_end.group(1)
        cantidad = _cantidad_token(m_each_end.group(2))
        colores = _detectar_colores_en_linea(zona_colores, color_a_codigos, alias_ordenados)
        if cantidad and colores:
            for color in colores:
                key = (color, cantidad)
                if key not in vistos:
                    resultados.append((color, cantidad)); vistos.add(key)
            return resultados

    # Luego cantidad al inicio:
    # "2 de cada blanco negro" => blanco=2, negro=2.
    m_each_start = re.match(rf"^.*?\b({cant_pat})\s*(?:de\s*)?(?:cada|c/u|c/u\.|por\s+color|por\s+tono)\b(.*)$", linea)
    if m_each_start:
        cantidad = _cantidad_token(m_each_start.group(1))
        zona_colores = m_each_start.group(2)
        colores = _detectar_colores_en_linea(zona_colores, color_a_codigos, alias_ordenados)
        if cantidad and colores:
            for color in colores:
                key = (color, cantidad)
                if key not in vistos:
                    resultados.append((color, cantidad)); vistos.add(key)
            return resultados

    # Cadenas sin comas: "3 blancos 2 negros" o "blanco 3 negro 2".
    color_alt_chain = "|".join(re.escape(a) for a in alias_ordenados if a and len(a) >= 3)
    producto_ruido_chain = r"(?:velluto|veluto|komfy\s+mini|komfy|estambre|hilo|madejas?|piezas?|pzas?|pz|rollos?|trapillos?|kraft|chenille|chenil|karina|alize|hilorama)"
    cant_chain = _cantidad_pat()
    qty_color_pat = rf"\b({cant_chain})\b\s*(?:{producto_ruido_chain}\s*)?(?:de\s+|del\s+|color\s+|tono\s+)?({color_alt_chain})(?=\b|s\b)"
    color_qty_pat = rf"\b(?:color\s+|tono\s+)?({color_alt_chain})(?=\b|s\b)\s*(?:de\s*)?(?:{producto_ruido_chain}\s*)?({cant_chain})\b"
    qty_matches = list(re.finditer(qty_color_pat, linea))
    cq_matches = list(re.finditer(color_qty_pat, linea))
    stripped = linea.strip()
    starts_qty = bool(re.match(rf"^({cant_chain})\b", stripped))
    starts_color = bool(color_alt_chain and re.match(rf"^(?:color\s+|tono\s+)?({color_alt_chain})(?=\b|s\b)", stripped))
    preferred = qty_matches if (starts_qty or len(qty_matches) >= len(cq_matches)) else cq_matches
    if preferred:
        for m in preferred:
            if m.re.pattern == qty_color_pat:
                cantidad = _cantidad_token(m.group(1)) or 1
                color_raw = m.group(2)
            else:
                color_raw = m.group(1)
                cantidad = _cantidad_token(m.group(2)) or 1
            color = _normalizar_color(color_raw)
            if color not in color_a_codigos:
                color = _sin_acentos(color_raw)
            if color in color_a_codigos:
                key = (color, cantidad)
                if key not in vistos:
                    resultados.append((color, cantidad)); vistos.add(key)
        if resultados:
            return resultados

    # Patrones de cantidad + producto opcional + color.
    color_alt = "|".join(re.escape(a) for a in alias_ordenados if a and len(a) >= 3)
    producto_ruido = r"(?:velluto|veluto|komfy\s+mini|komfy|estambre|hilo|madejas?|piezas?|pzas?|pz|rollos?|trapillos?|kraft|chenille|chenil|karina|alize|hilorama)"
    cant = _cantidad_pat()
    patrones = [
        # "3 vellutos blanco", "tres negros", "2 pzas color blanco"
        rf"\b({cant})\b\s*(?:{producto_ruido}\s*)?(?:de\s+|del\s+|color\s+|tono\s+)?({color_alt})(?=\b|s\b)",
        # "blanco 3", "negro dos", "color blanco 2 pz"
        rf"\b(?:color\s+|tono\s+)?({color_alt})(?=\b|s\b)\s*(?:de\s*)?(?:{producto_ruido}\s*)?({cant})\b",
        # "3 de color blanco"
        rf"\b({cant})\b\s*(?:{producto_ruido}\s*)?(?:de\s+)?(?:color|tono)\s+({color_alt})(?=\b|s\b)",
    ]
    for pat in patrones:
        for m in re.finditer(pat, linea):
            g1, g2 = m.group(1), m.group(2)
            if _cantidad_token(g1):
                cantidad = _cantidad_token(g1)
                color_raw = g2
            else:
                color_raw = g1
                cantidad = _cantidad_token(g2)
            if not cantidad:
                cantidad = 1
            color = _normalizar_color(color_raw)
            if color not in color_a_codigos:
                color = _sin_acentos(color_raw)
            if color in color_a_codigos:
                key = (color, cantidad, m.start(), m.end())
                if key not in vistos:
                    resultados.append((color, cantidad)); vistos.add(key)

    # Si los patrones directos no encontraron nada, usa el parser base por pedazos.
    # Evitamos correrlo siempre porque duplicaba casos como "tres negros" o "3 vellutos blanco".
    if not resultados:
        for parte in re.split(r"\s*(?:,|\by\b|\be\b|\+|/|;|\n)\s*", linea):
            parte = parte.strip()
            if not parte:
                continue
            for color, cantidad in _extraer_pares_color_cantidad(parte, color_a_codigos, alias_ordenados):
                key = (color, cantidad, parte)
                if key not in vistos:
                    resultados.append((color, cantidad)); vistos.add(key)

    # Último recurso: colores sueltos con una cantidad global de la frase.
    if not resultados:
        colores = _detectar_colores_en_linea(linea, color_a_codigos, alias_ordenados)
        cantidad = _cantidad_en_linea(linea) or 1
        for color in colores:
            resultados.append((color, cantidad))

    return resultados


def _parsear_linea_mixta_codigos_y_colores(linea, codigos_validos, color_a_codigos, alias_ordenados):
    """Procesa una frase mezclada con códigos y colores sin cancelar los colores.
    Además detecta ambigüedades reales para pedir confirmación en vez de inventar.
    """
    pares_codigo = []
    pares_color = []
    preguntas = []
    bloquear_colores_por_partes = False

    # Primero, una lectura contextual de secuencias compactas sin separadores:
    # "55 1 56 2 16", "un 55 1 56 2 16", "16 550", "2 4".
    seq_pares, seq_preg = _parsear_secuencia_numerica_contextual(linea, codigos_validos)
    if seq_preg:
        preguntas.extend(seq_preg)
        # Si hay ambigüedad fuerte, no seguimos con reglas genéricas que podrían inventar.
        return [], [], preguntas
    if seq_pares:
        colores_linea = _detectar_colores_en_linea(linea, color_a_codigos, alias_ordenados)
        for codigo, _cant in seq_pares:
            for color in colores_linea:
                posibles = color_a_codigos.get(color) or []
                if posibles and codigo not in posibles:
                    preguntas.append(
                        f"Confirma código {codigo}: en el contexto no parece color '{color}'. "
                        f"Para '{color}' encontré código(s): {', '.join(posibles[:5])}."
                    )
        return seq_pares, [], preguntas

    # En frases tipo "blanco y negro 3 cada uno" no conviene partir por "y",
    # porque la cantidad final aplica a todos los colores mencionados.
    if re.search(r"\b(cada\s+uno|c/u|c/u\.|por\s+color|por\s+tono)\b", _sin_acentos(linea)):
        pares_color = _extraer_pares_color_cantidad_avanzado(linea, color_a_codigos, alias_ordenados)
        bloquear_colores_por_partes = bool(pares_color)

    for parte in _split_partes_pedido(linea):
        parte = parte.strip()
        if not parte:
            continue

        seq_cods, seq_q = _parsear_secuencia_numerica_contextual(parte, codigos_validos)
        if seq_q:
            preguntas.extend(seq_q)
            continue
        colores_en_parte = _detectar_colores_en_linea(parte, color_a_codigos, alias_ordenados)
        if seq_cods:
            cods = seq_cods
        else:
            cods = _parsear_segmento_codigo_cantidad(parte, codigos_validos)

        # Si hay color y un solo número pequeño, puede ser cantidad-color aunque ese número
        # también exista como código. Ej: "3 blancos" debe ser 3 piezas del blanco.
        # Pero si el código coincide con ese color, respetamos el código. Ej: "16 azul".
        if cods and colores_en_parte:
            nums_parte = _numeros(parte)
            codigo_unico = cods[0][0] if len(cods) == 1 else None
            color_coincide_codigo = any(codigo_unico in (color_a_codigos.get(c) or []) for c in colores_en_parte) if codigo_unico else False
            sin_marcador_codigo = not re.search(r"\b(?:del|de|d|tono|codigo|cod|num|numero)\b|#", _sin_acentos(parte))
            if (len(nums_parte) == 1 and int(nums_parte[0]) <= 50 and sin_marcador_codigo and not color_coincide_codigo):
                n_unico = norm_codigo(nums_parte[0])
                # 3 blancos => cantidad-color.
                # 16 blanco, si 16 existe como código, ya es dudoso: mejor preguntar.
                if n_unico in codigos_validos and int(n_unico) > 10:
                    posibles_txt = []
                    for c in colores_en_parte:
                        posibles_txt.extend(color_a_codigos.get(c) or [])
                    preguntas.append(
                        f"Confirma '{nums_parte[0]} {colores_en_parte[0]}': ¿quieres el código {n_unico}, "
                        f"o {nums_parte[0]} pieza(s) del color {colores_en_parte[0]}"
                        + (f" (código {posibles_txt[0]})?" if posibles_txt else "?")
                    )
                    continue
                cods = []

        if cods:
            pares_codigo.extend(cods)
            # Si el cliente escribió código + color, mandan los códigos, pero se valida color.
            for codigo, _cant in cods:
                for color in colores_en_parte:
                    posibles = color_a_codigos.get(color) or []
                    if posibles and codigo not in posibles:
                        preguntas.append(
                            f"Confirma código {codigo}: en el contexto no parece color '{color}'. "
                            f"Para '{color}' encontré código(s): {', '.join(posibles[:5])}."
                        )
            # Código gana sobre color para evitar duplicar: "55 blanco" no son 55 blancos.
            continue

        if not bloquear_colores_por_partes:
            cols = _extraer_pares_color_cantidad_avanzado(parte, color_a_codigos, alias_ordenados)
            if cols:
                pares_color.extend(cols)

    # Si no hubo separadores claros, intenta toda la línea, pero sin duplicar:
    # si ya se entendió por código, no vuelvas a leer el número como cantidad-color;
    # si ya se entendió por color, no vuelvas a leer la cantidad como código.
    if not pares_color and not pares_codigo:
        pares_color = _extraer_pares_color_cantidad_avanzado(linea, color_a_codigos, alias_ordenados)
    if not pares_codigo and not pares_color:
        pares_codigo = _parsear_linea_mixta(linea, codigos_validos)
    return pares_codigo, pares_color, preguntas



# ======================================================
# PARSER NUMÉRICO INTELIGENTE
# ======================================================
def _cantidad_token(tok):
    tok = _sin_acentos(tok)
    if tok.isdigit():
        return int(tok)
    return NUM_PALABRA.get(tok) or CANTIDAD_ALIAS.get(tok)


def _cantidad_pat():
    palabras = sorted(list(NUM_PALABRA.keys()) + list(CANTIDAD_ALIAS.keys()), key=len, reverse=True)
    return r"(?:\d+|" + "|".join(re.escape(p) for p in palabras) + r")"


def _split_partes_pedido(linea):
    # Divide pedidos mixtos: "del 55 dame 2, 3 56 y un 310"
    # pero evita romper frases con "de arriba y derecha" porque esas son visuales.
    partes = re.split(r"\s*(?:,|\+|/|\by\b|\be\b|\bluego\b|\botro\b|\botra\b)\s*", linea)
    return [p.strip() for p in partes if p and p.strip()]


def _parsear_segmento_codigo_cantidad(seg, codigos_validos):
    seg = seg.strip().lower()
    if not seg:
        return []
    cant = _cantidad_pat()
    verbos = r"(?:dame|dames|quiero|quisiera|ocupo|necesito|ponme|agrega|agregame|mandame|pasame|echame|apartame|anotame)?"

    # "del 55 dame 2", "de 55 ponme dos", "tono 310 uno"
    m = re.search(rf"\b(?:del|de|d|tono|codigo|cod)\s*#?\s*(\d+)\b\s*(?:{verbos})\s*(?:de\s*)?({cant})\b", seg)
    if m:
        codigo = norm_codigo(m.group(1))
        cantidad = _cantidad_token(m.group(2))
        if codigo in codigos_validos and cantidad:
            return [(codigo, cantidad)]

    # "55 dame 2", "55 ponme dos", "55 de 2"
    # OJO: no debe convertir "3 56" en código 3 cantidad 56.
    m = re.search(rf"^\s*(\d+)\b\s+(?:dame|quiero|quisiera|ocupo|necesito|ponme|agrega|agregame|mandame|pasame|echame|apartame|anotame|de)\s+({cant})\b", seg)
    if m:
        codigo = norm_codigo(m.group(1))
        cantidad = _cantidad_token(m.group(2))
        if codigo in codigos_validos and cantidad:
            return [(codigo, cantidad)]

    # "dame 2 del 55", "2 pz tono 310", "un 310", "3 56"
    m = re.search(rf"\b({cant})\b\s*(?:{UNIDADES})?\s*(?:del|de|d|tono|codigo|cod)?\s*#?\s*(\d+)\b", seg)
    if m:
        cantidad = _cantidad_token(m.group(1))
        codigo = norm_codigo(m.group(2))
        # Evita leer "55 2" como 55 piezas del código 2.
        # Si la cantidad parece demasiado grande, dejamos que la regla de dos números decida.
        if codigo in codigos_validos and cantidad and 1 <= cantidad <= 50:
            return [(codigo, cantidad)]

    # "55 x 2", "55:2", "55=2"
    m = re.search(r"^\s*(\d+)\s*(?:x|\*|:|=|->)\s*(\d+)\s*$", seg)
    if m:
        codigo = norm_codigo(m.group(1))
        cantidad = int(m.group(2))
        if codigo in codigos_validos:
            return [(codigo, cantidad)]

    nums = _numeros(seg)
    if len(nums) == 2:
        a, b = nums
        a_es = a in codigos_validos
        b_es = b in codigos_validos
        ia = int(a)
        ib = int(b)
        # "3 56" = 3 piezas del 56, aunque el 3 exista como código.
        if 1 <= ia <= 50 and b_es and len(b) >= 2 and not seg.strip().startswith(("tono", "codigo", "cod", "del", "de ")):
            return [(b, ia)]
        # "55 2" = código 55 cantidad 2.
        if a_es and 1 <= ib <= 50:
            return [(a, ib)]
        if a_es and b_es:
            return [(a, 1), (b, 1)]

    # Frases muy humanas: "el 55 dos piezas", "55 me das dos", "55 van 2"
    m = re.search(rf"\b(?:el|tono|codigo|cod)?\s*#?(\d+)\b.*?\b(?:me\s+das|dame|van|serian|serían|son|quiero|ponme)?\s*({cant})\b", seg)
    if m:
        codigo = norm_codigo(m.group(1))
        cantidad = _cantidad_token(m.group(2))
        if codigo in codigos_validos and cantidad and 1 <= cantidad <= 50:
            return [(codigo, cantidad)]

    if len(nums) == 1:
        c = nums[0]
        if c in codigos_validos:
            return [(c, 1)]

    return []


def _parsear_linea_mixta(linea, codigos_validos):
    resultados = []
    for seg in _split_partes_pedido(linea):
        resultados.extend(_parsear_segmento_codigo_cantidad(seg, codigos_validos))
    # Si partir no funcionó, intenta toda la línea.
    if not resultados:
        resultados.extend(_parsear_segmento_codigo_cantidad(linea, codigos_validos))
    return resultados


def extraer_pedidos(texto, productos):
    texto = limpiar_texto(texto)
    codigos_validos = _producto_map(productos)
    color_a_codigos, alias_ordenados = _indice_colores(productos)

    pedidos = {}
    errores = []
    sugerencias = {}
    advertencias = []
    preguntas = []

    texto_limpio = texto.lower()

    # ================= GAMA =================
    excluidos = set()
    m = re.search(r"\b(?:excepto|menos|sin|quita|no\s+pongas|no\s+incluyas)\s+(?:el|los|este|estos)?\s*([\d,\sy]+)", texto_limpio)
    if m:
        for n in _numeros(m.group(1)):
            excluidos.add(n)

    hay_colores_mencionados = bool(_detectar_colores_en_linea(texto_limpio, color_a_codigos, alias_ordenados))
    modo_gama = bool(re.search(
        r"\b(dame|de|quiero|ocupo)?\s*(toda|todos|una)\s+(?:la\s+)?gama\b|"
        r"\bde\s+todos\s+uno\b|\buno\s+de\s+cada\b|\buna\s+de\s+cada\b|"
        r"\b1\s+de\s+cada\s+(?:uno|color|tono)?\b|\bdame\s+1\s+de\s+cada\s+(?:uno|color|tono)?\b|"
        r"\bquiero\s+1\s+de\s+cada\s+(?:uno|color|tono)?\b|\bc/u\b",
        texto_limpio
    ) or (re.search(r"\bcada\s+uno\b", texto_limpio) and not hay_colores_mencionados))
    if modo_gama:
        for c in codigos_validos:
            if c not in excluidos:
                pedidos[c] = 1
        return {
            "pedidos": [{"codigo": c, "cantidad": q} for c, q in pedidos.items()],
            "errores": [],
            "sugerencias": {},
            "advertencias": [],
            "preguntas": [],
            "modo": "gama"
        }

    cantidad_bloque = None
    lineas = []
    for raw in re.split(r"\n+", texto.replace(";", "\n")):
        raw = raw.strip()
        if raw:
            lineas.append(raw)

    for linea in lineas:
        linea = linea.strip().lower()
        if not linea:
            continue

        cantidad_intro, resto = _quitar_intro_cantidad(linea)
        if cantidad_intro:
            cantidad_bloque = cantidad_intro
            linea = resto
            if not linea:
                continue

        # ================= parser mixto avanzado =================
        # Ejemplos:
        # - "del 55 dame 2, 3 56 y un 310"
        # - "dem 3 vellutos blanco, tres negros, tambien agregame un velluto 429 y un 56"
        # Importante: si encuentra códigos, NO debe saltarse los colores de la misma frase.
        pares_mixtos, pares_color_mixtos, preguntas_mixtas = _parsear_linea_mixta_codigos_y_colores(
            linea, codigos_validos, color_a_codigos, alias_ordenados
        )
        if preguntas_mixtas:
            preguntas.extend(preguntas_mixtas)
            continue
        if pares_mixtos or pares_color_mixtos:
            usar_bloque = bool(cantidad_bloque and pares_mixtos and all(int(cant or 0) == 1 for _, cant in pares_mixtos))
            for codigo, cantidad in pares_mixtos:
                _add(pedidos, codigo, cantidad_bloque if usar_bloque else cantidad)
            for color, cantidad in pares_color_mixtos:
                cods = color_a_codigos.get(color) or []
                if len(cods) == 1:
                    _add(pedidos, cods[0], cantidad_bloque or cantidad)
                elif len(cods) > 1:
                    _add(pedidos, cods[0], cantidad_bloque or cantidad)
                    preguntas.append(
                        f"Confirma el color '{color}': coincide con varios códigos ({', '.join(cods[:8])}). Se usó {cods[0]} provisionalmente."
                    )
            continue


        # ================= frases compuestas muy humanas =================
        # Ej: "del 55 dame 2, 3 56 y un 310"
        patrones_frase_compuesta = [
            r"(?:del|de|d)\s*#?(\d+)\s*(?:dame|quiero|ponme|agrega|pasame|pásame)?\s*(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)",
            r"\b(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+(?:del|de|d)?\s*#?(\d+)\b",
        ]
        found_comp = False
        for patc in patrones_frase_compuesta:
            for mc in re.finditer(patc, linea, re.I):
                a = str(mc.group(1)).lower()
                b = str(mc.group(2)).lower()
                # Si empieza con "del 55 dame 2", a=codigo, b=cantidad.
                if a.isdigit() and norm_codigo(a) in codigos_validos:
                    codigo = norm_codigo(a)
                    cantidad = _cantidad_texto(b) or (int(b) if b.isdigit() else 1)
                else:
                    cantidad = _cantidad_texto(a) or (int(a) if a.isdigit() else 1)
                    codigo = norm_codigo(b)
                if codigo in codigos_validos:
                    _add(pedidos, codigo, cantidad)
                    found_comp = True
        if found_comp:
            continue

        # ================= formatos explícitos por código =================
        patrones = [
            (rf"\b(\d+)\s*[\.\-]?\s*\(\s*(?:x|\*)?\s*(\d+)\s*(?:{UNIDADES})?\s*\)", "codigo_cantidad"),
            (rf"\b(\d+)\s*(?:{UNIDADES})\s*(?:tono|del|de|codigo|cod)?\s*#?\s*(\d+)\b", "cantidad_codigo"),
            (rf"\b(?:tono|codigo|cod)\s*#?\s*(\d+)\b[^\d]{{0,25}}\b(\d+)\s*(?:{UNIDADES})\b", "codigo_cantidad"),
            (r"\b(\d+)\s+(?:del|de|d)\s*#?\s*(\d+)\b", "cantidad_codigo"),
            (r"\b(?:del|de|d)\s*#?\s*(\d+)\s+(\d+|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|veinte)\b", "codigo_cantidad_pal"),
            (r"\b#?\s*(\d+)\s*(?:->|:|=)\s*(\d+)\b", "codigo_cantidad"),
            (r"\b(\d+)\s*[x\*]\s*(\d+)\b", "multiplica"),
        ]

        found = False
        for pat, modo in patrones:
            for m in re.finditer(pat, linea, re.I):
                a = norm_codigo(m.group(1))
                b_raw = m.group(2)
                b = norm_codigo(b_raw) if str(b_raw).isdigit() else b_raw.lower()

                codigo = None
                cantidad = None

                if modo == "codigo_cantidad":
                    codigo, cantidad = a, b
                elif modo == "cantidad_codigo":
                    cantidad, codigo = a, norm_codigo(b_raw)
                elif modo == "codigo_cantidad_pal":
                    codigo = a
                    cantidad = _cantidad_texto(str(b)) or 1
                elif modo == "multiplica":
                    a_es = a in codigos_validos
                    b_norm = norm_codigo(b_raw)
                    b_es = b_norm in codigos_validos
                    if a_es and not b_es:
                        codigo, cantidad = a, b_norm
                    elif b_es and not a_es:
                        codigo, cantidad = b_norm, a
                    elif a_es and b_es:
                        # 55x60 probablemente son códigos, no multiplicación.
                        continue
                    else:
                        continue

                if codigo and norm_codigo(codigo) in codigos_validos:
                    _add(pedidos, codigo, cantidad)
                    found = True

        if found:
            continue

        # ================= línea con exactamente 2 números =================
        nums = _numeros(linea)
        if len(nums) == 2:
            a, b = nums
            a_es = a in codigos_validos
            b_es = b in codigos_validos

            if cantidad_bloque and (a_es or b_es):
                for c in nums:
                    if c in codigos_validos:
                        _add(pedidos, c, cantidad_bloque)
                continue

            # 6 55 => cantidad código, si el primero es cantidad razonable y el segundo código.
            if b_es and (not a_es or int(a) <= 20):
                _add(pedidos, b, int(a))
                continue

            # 55 2 => código cantidad, solo si el segundo NO es código.
            if a_es and not b_es:
                _add(pedidos, a, int(b))
                continue

            # 55 60, ambos códigos y no hay cantidad clara: ambos x1.
            if a_es and b_es:
                _add(pedidos, a, 1)
                _add(pedidos, b, 1)
                continue

        # ================= lista de códigos =================
        codigos = _extraer_lista_codigos(linea, codigos_validos)
        if codigos:
            cantidad = cantidad_bloque or 1
            if cantidad_bloque:
                codigos = [c for c in codigos if c != norm_codigo(cantidad_bloque)]
            for c in codigos:
                _add(pedidos, c, cantidad)
            continue

        # ================= palabras de cantidad + códigos =================
        found = False
        for palabra, cant in NUM_PALABRA.items():
            m = re.search(rf"\b{palabra}\b\s+(?:del|de|tono|codigo|cod)?\s*#?\s*(\d+)\b", linea)
            if m:
                c = norm_codigo(m.group(1))
                if c in codigos_validos:
                    _add(pedidos, c, cant)
                    found = True
        if found:
            continue

        # ================= colores con cantidad =================
        pares_color = _extraer_pares_color_cantidad_avanzado(linea, color_a_codigos, alias_ordenados)
        if pares_color:
            for color, cantidad in pares_color:
                cods = color_a_codigos.get(color) or []
                if len(cods) == 1:
                    _add(pedidos, cods[0], cantidad)
                elif len(cods) > 1:
                    _add(pedidos, cods[0], cantidad)
                    preguntas.append(
                        f"Confirma el color '{color}': coincide con varios códigos ({', '.join(cods[:8])}). Se usó {cods[0]} provisionalmente."
                    )
            continue

        # Ignorar referencias visuales comunes como "de ese 2", "el segundo", etc.
        if any(x in linea for x in ["de ese", "de la foto", "de la imagen", "arriba", "abajo", "izquierda", "derecha", "segundo", "tercero", "primero"]):
            continue

        # Si hay números no usados que parecen códigos inválidos, avisar.
        for n in nums:
            if n not in codigos_validos and int(n) > 20:
                errores.append(n)
                sug = sugerir_codigo(n, codigos_validos)
                if sug:
                    sugerencias[n] = sug

    return {
        "pedidos": [{"codigo": c, "cantidad": q} for c, q in pedidos.items()],
        "errores": sorted(set(errores)),
        "sugerencias": sugerencias,
        "advertencias": sorted(set(advertencias)),
        "preguntas": sorted(set(preguntas)),
        "modo": "normal",
    }
