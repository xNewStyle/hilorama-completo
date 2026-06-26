import re
import unicodedata

NUM_PALABRA = {
    "uno": 1, "una": 1,
    "dos": 2, "tres": 3,
    "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9,
    "diez": 10,
    "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15,
    "veinte": 20,
}

RUIDO_CANTIDAD = re.compile(
    r"\b(?:quiero|quisiera|ocupo|necesito|dame|mandame|m[áa]ndame|ponme|agrega|agregame|serian|ser[ií]an|me\s+das|me\s+puedes\s+dar)\b",
    re.I,
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
    texto = re.sub(r"\[.*?\]", " ", texto)
    texto = re.sub(r"\+?\d{9,}", " ", texto)  # telefonos
    texto = texto.replace("—>", "->").replace("–>", "->").replace("→", "->")
    texto = texto.replace("×", "x")
    texto = texto.replace(";", "\n")
    texto = re.sub(r"[{}\[\]|]", " ", texto)
    return texto


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


def _quitar_intro_cantidad(linea):
    """
    Detecta frases como:
    - quiero 6 de:
    - quisiera 6 de estos
    - 6 piezas de los siguientes
    Devuelve (cantidad_global, resto_sin_intro).
    Así el 6 NO se interpreta como producto.
    """
    l = linea.strip()
    patrones = [
        r"^(?:.*?\b)?(?:quiero|quisiera|ocupo|necesito|dame|mandame|m[áa]ndame|ponme|agrega|agregame)?\s*(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\s*(?:de|del|de\s+los|de\s+las|de\s+estos|de\s+estas)\s*[:\-]*\s*(.*)$",
        r"^(?:de|para)\s+estos\s*(\d+)\s*[:\-]*\s*(.*)$",
        r"^(?:cada\s+uno|c/u|cada)\s*(\d+)\s*[:\-]*\s*(.*)$",
    ]
    for pat in patrones:
        m = re.match(pat, l, re.I)
        if m:
            return int(m.group(1)), (m.group(2) or "").strip()
    return None, linea


def _extraer_lista_codigos(texto, codigos_validos):
    """Extrae números que son códigos válidos; ignora conectores y palabras."""
    cods = []
    for n in _numeros(texto):
        if n in codigos_validos:
            cods.append(n)
    return cods


def extraer_pedidos(texto, productos):
    texto = limpiar_texto(texto)
    codigos_validos = _producto_map(productos)

    pedidos = {}
    errores = []
    sugerencias = {}
    usados = set()

    texto_limpio = texto.lower()

    # ================= GAMA =================
    excluidos = set()
    m = re.search(r"\b(?:excepto|menos|sin|quita|no\s+pongas|no\s+incluyas)\s+(?:el|los|este|estos)?\s*([\d,\sy]+)", texto_limpio)
    if m:
        for n in _numeros(m.group(1)):
            excluidos.add(n)

    modo_gama = bool(re.search(r"\b(dame|de|quiero|ocupo)?\s*(toda|todos|una)\s+(?:la\s+)?gama\b|\bde\s+todos\s+uno\b", texto_limpio))
    if modo_gama:
        for c in codigos_validos:
            if c not in excluidos:
                pedidos[c] = 1
        return {"pedidos": [{"codigo": c, "cantidad": q} for c, q in pedidos.items()], "errores": [], "sugerencias": {}, "modo": "gama"}

    # Cantidad global acumulada para bloques, por ejemplo:
    # "quiero 6 de:" y en las siguientes líneas una lista de códigos.
    cantidad_bloque = None

    # Separar por líneas, comas fuertes o viñetas, sin destruir pares tipo "55 2".
    lineas = []
    for raw in texto.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        # Si trae dos puntos con intro de cantidad, dejarla como una línea.
        lineas.append(raw)

    for linea in lineas:
        original = linea
        linea = linea.strip().lower()
        if not linea:
            continue

        cantidad_intro, resto = _quitar_intro_cantidad(linea)
        if cantidad_intro:
            cantidad_bloque = cantidad_intro
            linea = resto
            if not linea:
                continue

        # ================= formatos explícitos =================
        patrones = [
            # 55 (1 pieza)
            (r"\b(\d+)\s*[\.\-]?\s*\(\s*(?:x|\*)?\s*(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\s*\)", "codigo_cantidad"),
            # 1pz tono 310 / 2 piezas del 55
            (r"\b(\d+)\s*(?:pz|pza|pzas|pieza|piezas)\s*(?:tono|del|de|codigo|cod)?\s*#?\s*(\d+)\b", "cantidad_codigo"),
            # tono 310 2pz
            (r"\b(?:tono|codigo|cod)\s*#?\s*(\d+)\b[^\d]{0,25}\b(\d+)\s*(?:pz|pza|pzas|pieza|piezas)\b", "codigo_cantidad"),
            # 2 del 55
            (r"\b(\d+)\s+(?:del|de|d)\s*#?\s*(\d+)\b", "cantidad_codigo"),
            # del 55 2 / del 55 dos
            (r"\b(?:del|de|d)\s*#?\s*(\d+)\s+(\d+|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|veinte)\b", "codigo_cantidad_pal"),
            # 55 -> 2 / 55: 2
            (r"\b#?\s*(\d+)\s*(?:->|:|=)\s*(\d+)\b", "codigo_cantidad"),
            # 2x55 o 55x2
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
                    cantidad = NUM_PALABRA.get(str(b).lower(), int(b) if str(b).isdigit() else 1)
                elif modo == "multiplica":
                    a_es = a in codigos_validos
                    b_norm = norm_codigo(b_raw)
                    b_es = b_norm in codigos_validos
                    if a_es and not b_es:
                        codigo, cantidad = a, b_norm
                    elif b_es and not a_es:
                        codigo, cantidad = b_norm, a
                    elif a_es and b_es:
                        # En 55x60 probablemente son dos códigos, no multiplicación.
                        continue
                    else:
                        continue

                if codigo and norm_codigo(codigo) in codigos_validos:
                    _add(pedidos, codigo, cantidad)
                    usados.add(norm_codigo(codigo))
                    found = True
            if found:
                # Permitimos múltiples matches del mismo patrón, pero no seguimos con formatos genéricos.
                pass
        if found:
            continue

        # ================= línea con exactamente 2 números =================
        nums = _numeros(linea)
        if len(nums) == 2:
            a, b = nums
            a_es = a in codigos_validos
            b_es = b in codigos_validos
            # Si venimos de "quiero 6 de:" aplica cantidad global a ambos si ambos son códigos.
            if cantidad_bloque and (a_es or b_es):
                for c in nums:
                    if c in codigos_validos:
                        _add(pedidos, c, cantidad_bloque)
                        usados.add(c)
                continue
            # 6 55 => cantidad código, si el primero es cantidad razonable y el segundo código.
            if b_es and (not a_es or int(a) <= 20):
                _add(pedidos, b, int(a))
                usados.add(b)
                continue
            # 55 2 => código cantidad, solo si el segundo NO es código.
            if a_es and not b_es:
                _add(pedidos, a, int(b))
                usados.add(a)
                continue
            # 55 60, ambos códigos y no hay cantidad clara: ambos x1.
            if a_es and b_es:
                _add(pedidos, a, 1)
                _add(pedidos, b, 1)
                usados.update([a, b])
                continue

        # ================= lista de códigos =================
        # Aplica para "quiero 6 de: 55, 60, 70" o "55,60,70".
        codigos = _extraer_lista_codigos(linea, codigos_validos)
        if codigos:
            cantidad = cantidad_bloque or 1
            # Si la línea es "quiero 6 de 55 60" quitar el número de cantidad si fue detectado como código.
            if cantidad_bloque:
                codigos = [c for c in codigos if c != norm_codigo(cantidad_bloque)]
            for c in codigos:
                _add(pedidos, c, cantidad)
                usados.add(c)
            continue

        # ================= palabras de cantidad + números =================
        # "dos del 55"
        for palabra, cant in NUM_PALABRA.items():
            m = re.search(rf"\b{palabra}\b\s+(?:del|de|tono|codigo|cod)?\s*#?\s*(\d+)\b", linea)
            if m:
                c = norm_codigo(m.group(1))
                if c in codigos_validos:
                    _add(pedidos, c, cant)
                    usados.add(c)
                    found = True
        if found:
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
        "modo": "normal",
    }
