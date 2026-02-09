import re

NUM_PALABRA = {
    "uno": 1, "una": 1,
    "dos": 2, "tres": 3,
    "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9,
    "diez": 10
}

def limpiar_texto(texto):
    texto = texto.lower()
    texto = re.sub(r"\[.*?\]", " ", texto)
    texto = re.sub(r"\+?\d{9,}", " ", texto)


    # 🔥 normalizar flechas unicode
    texto = texto.replace("—>", "->").replace("–>", "->").replace("→", "->")

    # ⚠️ NO quitamos (), ., #, *, x, >
    texto = re.sub(r"[^\w\s\*\-x#\.\(\)>]", " ", texto)
    return texto


def sugerir_codigo(codigo_erroneo, codigos_validos):
    sugerencias = []

    for c in codigos_validos:
        # diferencia de longitud máxima 1
        if abs(len(c) - len(codigo_erroneo)) > 1:
            continue

        # contar diferencias carácter por carácter
        dif = sum(a != b for a, b in zip(codigo_erroneo, c))
        dif += abs(len(codigo_erroneo) - len(c))

        if dif == 1:
            sugerencias.append(c)

    return sugerencias

def extraer_pedidos(texto, productos):
    
    texto = limpiar_texto(texto)
    codigos_validos = {
        str(p["codigo"]).strip().lstrip("0") or "0"
        for p in productos
    }

    pedidos = {}
    codigos_detectados = set()
    sugerencias = {}
    numeros_vistos = set()
    codigos_invalidos = set()
    codigos_con_cantidad_explicita = set()



    # ================= 🟣 MODO GAMA =================
    texto_limpio = texto.lower()
    numeros_vistos = {
    n.lstrip("0") or "0"
    for n in re.findall(r"\d+", texto_limpio)
    }

    

    modo_gama = bool(re.search(
        r"\b(dame|de)\s+(toda|todos|una)\s+(?:la\s+)?gama\b|\bde\s+todos\s+uno\b",
        texto_limpio
    ))


    excluidos = set()
    
    # ================= 🔴 EXCLUSIONES =================
    # excepto el 550,329,55
    m = re.search(
        r"\b(?:excepto|menos|sin|quita|no\s+pongas|no\s+incluyas)\s+(?:el|los|este|estos)?\s*([\d,\sy]+)",
        texto_limpio
    )

    if m:
        for n in re.findall(r"\d+", m.group(1)):
            excluidos.add(n.lstrip("0") or "0")

    # ================= 🟡 GAMA PARCIAL =================
    grupos_con_cantidad = []  # [(cantidad, [codigos])]

    # "de estos solo 2 493,550"
    for m in re.finditer(
        r"""
        (?:de|a)\s+estos\s+
        (?:solo|solamente|nada\s+mas|nada\s+m[aá]s|pon|manda|dame|quiero)?
        \s*(\d+)\s+
        ([\d,\s]+)
        |
        (?:solo|solamente|nada\s+mas|nada\s+m[aá]s)\s+
        (\d+)\s+
        (?:de|para)\s+estos\s+
        ([\d,\s]+)
        """,
        texto_limpio,
        re.VERBOSE
    ):
        cantidad = int(m.group(1) or m.group(3))
        codigos_txt = m.group(2) or m.group(4)
        codigos = [n.lstrip("0") or "0" for n in re.findall(r"\d+", codigos_txt)]
        grupos_con_cantidad.append((cantidad, codigos))

    # "de la gama de estos 310,329,60"
    for m in re.finditer(
        r"gama\s+de\s+estos\s+([\d,\s]+)",
        texto_limpio
    ):
        codigos = [n.lstrip("0") or "0" for n in re.findall(r"\d+", m.group(1))]
        grupos_con_cantidad.append((1, codigos))
    lineas = texto.splitlines()
    print("CODIGOS VALIDOS:", codigos_validos)
    print("TEXTO:", texto)


         # ================= 🟣 MODO GAMA (RETORNO INMEDIATO) =================
    if modo_gama:
        pedidos = {}

        for c in codigos_validos:
            if c not in excluidos:
                pedidos[c] = 1
                codigos_detectados.add(c)
        # aplicar grupos si existen (ej: "de estos solo 2 ...")
        for cantidad, codigos in grupos_con_cantidad:
            for c in codigos:
                if c in pedidos:
                    pedidos[c] = cantidad

        return {
            "pedidos": [{"codigo": c, "cantidad": q} for c, q in pedidos.items()],
            "errores": [],
            "sugerencias": {},
            "modo": "gama"
        }
            
    for linea in lineas:
        detecto_formato = False
        linea = linea.strip()
        if not linea:
            continue
        # ================= 🟢 FORMATO BÁSICO: "329 5" =================
        # SOLO detectar par si hay EXACTAMENTE 2 números en la línea
        nums_linea = re.findall(r"\d+", linea)

        if len(nums_linea) == 2:
           codigo = nums_linea[0].lstrip("0") or "0"
           cantidad = int(nums_linea[1])

           if codigo in codigos_validos:
              pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
              codigos_detectados.add(codigo)
              codigos_con_cantidad_explicita.add(codigo)
              detecto_formato = True

                

       
        # ================= 🔟 CANTIDAD GLOBAL: "paquete de 5 cada uno" =================
        m = re.search(
            r"(?:paquete\s+de|)\s*(\d+)\s*(?:pz|pzas|piezas)?\s*(?:cada\s+uno|c\/u|cada)",
            linea
        )

        cantidad_global = None
        if m:
            cantidad_global = int(m.group(1))
        # ================= 🔟 APLICAR CANTIDAD GLOBAL A CÓDIGOS =================
        if cantidad_global:
            codigos_en_linea = re.findall(r"\d+", linea)

            for c in codigos_en_linea:
                codigo = c.lstrip("0") or "0"
                if codigo in codigos_validos:
                   pedidos[codigo] = pedidos.get(codigo, 0) + cantidad_global  

            continue  # no seguir procesando esta línea

        # ================= 1️⃣ PARENTESIS FLEXIBLE =================
        # 55 (1 pieza) | 19. ( 1 piezas ) | 55 (* 1 pz) | 55 (x 1 pz)
        m = re.search(
            r"\b(\d+)\s*[\.\-]?\s*\(\s*(?:x|\*)?\s*(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\s*\)",
            linea,
            re.IGNORECASE
        )
        if m:
            codigo = m.group(1).lstrip("0") or "0"
            cantidad = int(m.group(2))
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
                codigos_con_cantidad_explicita.add(codigo)
                continue

        # ================= 2️⃣ FORMATO TIENDA =================
        # 1pz tono 310
        m = re.search(r"(\d+)\s*pz\s*tono\s*(\d+)", linea)
        if m:
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
        
                continue

        # ================= 3️⃣ FORMATO INVERSO =================
        # 310 Beige 3pz
        m = re.search(r"\b(\d+)\b[^\d]{0,20}(\d+)\s*pz\b", linea, re.I)
        if m:
            codigo = m.group(1).lstrip("0") or "0"
            cantidad = int(m.group(2))
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad

                continue

        # ================= 4️⃣ PALABRA + DEL =================
        # del 55 uno
        m = re.search(
            r"del\s+(\d+)\s+(uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)",
            linea
        )
        if m:
            codigo = m.group(1).lstrip("0") or "0"
            cantidad = NUM_PALABRA[m.group(2)]
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad

                continue

        # ================= 5️⃣ NUM + DEL =================
        # 8 del 55
        m = re.search(r"(\d+)\s+del\s+(\d+)", linea)
        if m:
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
                codigos_con_cantidad_explicita.add(codigo)
                continue

       
        
        # ================= 6️⃣ MULTIPLICACIÓN CORREGIDA =================
        # 2x55 | 55*2 | 5x329
        m = re.search(r"(\d+)\s*[x\*]\s*(\d+)", linea)
        if m:
            a, b = m.groups()
            a = a.lstrip("0") or "0"
            b = b.lstrip("0") or "0"

            a_es_codigo = a in codigos_validos
            b_es_codigo = b in codigos_validos

            if a_es_codigo and not b_es_codigo:
                pedidos[a] = pedidos.get(a, 0) + int(b)
                codigos_detectados.add(a)
                continue

            if b_es_codigo and not a_es_codigo:
                pedidos[b] = pedidos.get(b, 0) + int(a)
                codigos_detectados.add(b)
                continue

            # 🔥 ambos son códigos → usar el de mayor longitud (o el segundo)
            if a_es_codigo and b_es_codigo:
                codigo = b if len(b) >= len(a) else a
                cantidad = int(a) if codigo == b else int(b)
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
                codigos_detectados.add(codigo)
                codigos_con_cantidad_explicita.add(codigo)
                continue

        # ================= 🎯 TEXTO + #CODIGO + FLECHA + CANTIDAD =================
        # Ej: Rojo #56 —> 2 | Beige #310 -> 6
        m = re.search(
            r"#\s*(\d+)\s*->\s*(\d+)",
            linea
        )
        

        if m:
            codigo = m.group(1).lstrip("0") or "0"
            cantidad = int(m.group(2))

            if codigo in codigos_validos:
               pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
               codigos_detectados.add(codigo)
               detecto_formato = True
               codigos_con_cantidad_explicita.add(codigo)
               continue

        # ================= 7️⃣ WHATSAPP =================
        # 2 #493 | 1#121
        m = re.search(r"\b(\d+)\s*#\s*(\d+)\b", linea)
        if m:
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
                continue
        # ================= 4️⃣ WHATSAPP CON UNIDAD: 1pz #60 / 1 pz #43 =================
        m = re.search(
            r"\b(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\s*#\s*(\d+)\b",
            linea
        )

        if m:
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"

            if codigo in codigos_validos:
               pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
               continue

        # ================= 8️⃣ FORMATO LISTA =================
        # 1- 62 | 1 – 310 | 1 -- 55
        m = re.search(r"\b(\d+)\s*[-–—]+\s*(\d+)\b", linea)

        if m:
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"

            if codigo in codigos_validos:
               pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
               continue
        # ================= 9️⃣ FORMATO: 216 2 piezas / 429. 2 piezas =================
        m = re.search(
            r"\b(\d+)\s*\.?\s+(\d+)\s*(?:pz|pza|pzas|pieza|piezas)\b",
            linea
        )

        if m:
            codigo = m.group(1).lstrip("0") or "0"
            cantidad = int(m.group(2))

            if codigo in codigos_validos:
               pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
               continue


        # ================= 7️⃣ TEXTO + (CÓDIGO): 2 alize velluto (87) =================
        m = re.search(
            r"\b(\d+)\b.*?\(\s*(\d+)\s*\)",
            linea
        )

        if m:
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"

            if codigo in codigos_validos:
               pedidos[codigo] = pedidos.get(codigo, 0) + cantidad
               continue
        # ================= 🟢 CANTIDAD IMPLÍCITA: "un 55", "el 329" =================
        m = re.findall(
            r"\b(?:un|una|el|quiero)\s+(\d+)\b",
            linea
        )

        for c in m:
            codigo = c.lstrip("0") or "0"
            if codigo in codigos_validos and codigo not in codigos_detectados:
                pedidos[codigo] = pedidos.get(codigo, 0) + 1
                codigos_detectados.add(codigo)
                
                detecto_formato = True
                
              
        # ================= 🟢 CONECTOR: "y el 329" =================
        m = re.findall(
            r"\by\s+(?:el|un|una)?\s*(\d+)\b",
            linea
        )

        for c in m:
            codigo = c.lstrip("0") or "0"
            if (
               codigo in codigos_validos
               and codigo not in codigos_detectados
               and codigo not in codigos_con_cantidad_explicita
            ):

               pedidos[codigo] = pedidos.get(codigo, 0) + 1
               codigos_detectados.add(codigo)
               
               detecto_formato = True
               
          
        # ================= 9️⃣ SOLO CÓDIGO =================
        if linea.isdigit():
            codigo = linea.lstrip("0") or "0"
            if (
               codigo in codigos_validos
               and codigo not in codigos_detectados
               and codigo not in codigos_con_cantidad_explicita
            ):

                pedidos[codigo] = pedidos.get(codigo, 0) + 1
                codigos_detectados.add(codigo)
            
                detecto_formato = True
            continue

        # ================= 🟦 LISTA SIMPLE DE CÓDIGOS =================
        
        # 🟦 LISTA SIMPLE (solo si NO hubo formato válido en la línea)
        if not detecto_formato:
            for n in re.findall(r"\d+", linea):
                codigo = n.lstrip("0") or "0"
                if (
                    codigo in codigos_validos
                    and codigo not in codigos_detectados
                    and codigo not in codigos_con_cantidad_explicita
                ):
                    pedidos[codigo] = pedidos.get(codigo, 0) + 1
                    codigos_detectados.add(codigo)

                    
                


        # ================= 🟡 APLICAR GRUPOS =================
        for cantidad, codigos in grupos_con_cantidad:
           
            for c in codigos:
                if c in codigos_validos:
                    pedidos[c] = cantidad
                    detecto_formato = True

        # ================= 🟢 CÓDIGO SOLO EN LÍNEA =================
        m = re.fullmatch(r"\d+", linea)
        if m:
            codigo = m.group(0).lstrip("0") or "0"
            if codigo in codigos_validos:
                pedidos[codigo] = pedidos.get(codigo, 0) + 1
                codigos_detectados.add(codigo)
                codigos_con_cantidad_explicita.add(codigo)
                detecto_formato = True
        # ================= 🚨 ERRORES (solo códigos reales) =================
    for n in numeros_vistos:
        # ignorar cantidades comunes
        if n.isdigit() and int(n) <= 20:
            continue

        # si ya fue usado como código, no es error
        if n in codigos_detectados:
            continue

        # si no existe como código válido, ES error
        if n not in codigos_validos:
            codigos_invalidos.add(n)


    return {
        "pedidos": [{"codigo": c, "cantidad": q} for c, q in pedidos.items()],
        "errores": list(codigos_invalidos),
        "sugerencias": sugerencias,
        "modo": "robusto_final"
    }

  