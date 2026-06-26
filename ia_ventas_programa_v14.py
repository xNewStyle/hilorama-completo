import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import requests

# ============================================================
# IA LOCAL HILORAMA v12 - BASADA EN TU PROGRAMA DE VENTAS
# Usa Ollama + inventario real + medios + memoria + aprendizaje local.
# ============================================================

MODELO = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

# Si este archivo está dentro de la carpeta de tu programa, no cambies nada.
# Si lo tienes en otra carpeta, puedes poner la ruta del programa aquí:
# EJEMPLO:
# PROGRAMA_DIR = r"C:\Users\jorge\OneDrive\Escritorio\Hilorama"
PROGRAMA_DIR = os.getenv("HILORAMA_PROGRAMA_DIR", "").strip()

INTENCIONES_VALIDAS = {
    "pedido",
    "pregunta_precio",
    "pregunta_stock",
    "pregunta_envio",
    "pedir_catalogo",
    "pedir_foto_tono",
    "pregunta_grosor",
    "pregunta_uso",
    "pregunta_color_luz",
    "pedir_aclaracion",
    "comprobante_pago",
    "reclamo",
    "saludo",
    "otro",
}

ACCIONES_VALIDAS = {
    "responder",
    "pedir_dato",
    "crear_cotizacion_pendiente",
    "enviar_catalogo",
    "enviar_foto",
    "enviar_archivo",
    "cotizar_envio",
    "aprender",
    "avisar_a_jorge",
    "no_responder",
}

PALABRAS_COMPROBANTE = [
    "comprobante", "ya pague", "ya pagué", "pague", "pagué", "pagado",
    "transferencia", "deposito", "depósito", "ticket de pago", "captura de pago",
    "te mande el pago", "te mandé el pago", "te envie el pago", "te envié el pago",
]

PALABRAS_RECLAMO = [
    "reclamo", "molesta", "molesto", "enojada", "enojado", "no llego", "no llegó",
    "tardaron", "me urge", "fraude", "estafa", "devolucion", "devolución", "demanda",
    "pésimo", "pesimo", "mal servicio", "no me contestan", "quiero cancelar",
]

PALABRAS_STOCK = [
    "tienes", "tiene", "hay", "disponible", "disponibles", "manejas", "vendes",
    "existencia", "stock", "te queda", "tendras", "tendrás",
]

PALABRAS_PRECIO = ["precio", "cuanto", "cuánto", "costo", "cuesta", "sale", "vale"]

PALABRAS_ENVIO = ["envio", "envío", "mandas", "mandan", "paqueteria", "paquetería", "mexico", "dhl", "estafeta"]

ALIAS_PRODUCTOS_BASE = [
    # Es común que el cliente escriba Komfy con error: komfi/comfi/comfy.
    ("komfy mini", "Komfy mini"),
    ("komfi mini", "Komfy mini"),
    ("comfi mini", "Komfy mini"),
    ("comfy mini", "Komfy mini"),
    ("komfy", "Komfy"),
    ("komfi", "Komfy"),
    ("comfi", "Komfy"),
    ("comfy", "Komfy"),
    ("velluto", "Velluto"),
    ("trapillo kraft", "Trapillo kraft"),
    ("trapillo", "Trapillo"),
    ("estambres", "Estambre"),
    ("estambre", "Estambre"),
    ("hilos", "Hilo"),
    ("hilo", "Hilo"),
    ("gancho", "Gancho"),
    ("ganchos", "Gancho"),
    ("aguja", "Aguja"),
    ("agujas", "Aguja"),
    ("accesorios", "Accesorio"),
]

# Palabras que no son color ni producto.
BASURA_COLOR = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
    "color", "tono", "tonos", "codigo", "código", "cod", "clave",
    "pieza", "piezas", "pz", "pzs", "pza", "pzas", "madeja", "madejas",
    "por", "favor", "y", "quiero", "necesito", "dame", "me", "puedes", "mandar",
    "para", "revisarlo", "porfa", "xfa", "x", "en",
}


def normalizar(texto: Any) -> str:
    texto = "" if texto is None else str(texto)
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9#\s\-\.]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto




def producto_canonico(texto: Any) -> str:
    """Normaliza nombres escritos con variantes/errores comunes."""
    t = normalizar(texto)
    if any(x in t for x in ["komfy mini", "komfi mini", "comfi mini", "comfy mini"]):
        return "komfy mini"
    if any(x in t for x in ["komfy", "komfi", "comfi", "comfy"]):
        return "komfy"
    return t


def etiqueta_producto(producto: Any) -> str:
    p = producto_canonico(producto)
    if p == "komfy mini":
        return "Komfy mini"
    if p == "komfy":
        return "Komfy"
    return str(producto or "").strip().title()


def detectar_catalogo_general(mensaje: str) -> bool:
    """Distingue 'catálogo general / todo lo que vendes' de un catálogo por línea."""
    t = normalizar(mensaje)
    frases = [
        "catalogo general", "catalogo completo", "catalogo de todo",
        "todo lo que vendes", "todo lo que manejas", "todo lo que tienes",
        "todos los productos", "lo que vendes", "lo que manejas",
        "velluto como lo demas", "velluto y lo demas", "como lo demas", "lo demas",
        "todo tu catalogo", "catalogo de la tienda",
    ]
    return any(f in t for f in frases)

def limpiar_color(texto: str) -> str:
    texto = normalizar(texto)
    texto = texto.replace("?", " ").replace(".", " ").replace(",", " ")
    palabras = [p for p in texto.split() if p not in BASURA_COLOR and not p.isdigit()]
    return " ".join(palabras[:4]).strip()


def dinero(valor: Any) -> str:
    try:
        return f"${float(valor):.2f}"
    except Exception:
        return "$0.00"


def as_bool(valor: Any, default: bool = True) -> bool:
    if valor is None:
        return default
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(valor)
    if isinstance(valor, str):
        return valor.strip().lower() not in ("false", "f", "0", "no", "n", "item")
    return default


def encontrar_dir_programa() -> Path:
    if PROGRAMA_DIR:
        return Path(PROGRAMA_DIR)

    actual = Path.cwd()
    candidatos = [actual, actual.parent, actual.parent.parent]

    for c in candidatos:
        if (c / "database").exists() or (c / "main_ventas.py").exists() or (c / "parser_whatsapp.py").exists():
            return c

    return actual


def obtener_columnas_sqlite(conn: sqlite3.Connection, tabla: str) -> List[str]:
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()]
    except Exception:
        return []


def cargar_productos_sqlite(db_path: Path) -> List[Dict[str, Any]]:
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        columnas = obtener_columnas_sqlite(conn, "productos")
        if not columnas:
            return []

        rows = conn.execute("SELECT * FROM productos").fetchall()
        productos = [dict(r) for r in rows]

        precios = {}
        try:
            for r in conn.execute("SELECT * FROM precios").fetchall():
                d = dict(r)
                precios[normalizar(d.get("marca"))] = d
        except Exception:
            pass

        for p in productos:
            marca_key = normalizar(p.get("marca"))
            precio_marca = precios.get(marca_key, {})
            if not p.get("precio"):
                p["precio"] = precio_marca.get("venta", 0) or 0
            p["origen_db"] = str(db_path)

        return productos
    finally:
        conn.close()


def cargar_productos_postgres() -> List[Dict[str, Any]]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return []

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except Exception:
        return []

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM productos ORDER BY marca, hilo, color, codigo")
            productos = [dict(r) for r in cur.fetchall()]

            precios = {}
            try:
                cur.execute("SELECT * FROM precios")
                for r in cur.fetchall():
                    d = dict(r)
                    precios[normalizar(d.get("marca"))] = d
            except Exception:
                pass

            for p in productos:
                marca_key = normalizar(p.get("marca"))
                precio_marca = precios.get(marca_key, {})
                if not p.get("precio"):
                    p["precio"] = precio_marca.get("venta", 0) or 0
                p["origen_db"] = "DATABASE_URL"

            return productos
    finally:
        conn.close()


def normalizar_producto(p: Dict[str, Any]) -> Dict[str, Any]:
    precio = p.get("precio", 0) or p.get("venta", 0) or 0
    stock = p.get("stock", 0) or 0
    try:
        stock = int(stock)
    except Exception:
        stock = 0

    es_inventariable = as_bool(p.get("es_inventariable", True), True)

    return {
        "codigo": str(p.get("codigo") or "").strip(),
        "codigo_barras": str(p.get("codigo_barras") or "").strip(),
        "marca": str(p.get("marca") or "").strip(),
        "hilo": str(p.get("hilo") or "").strip(),
        "color": str(p.get("color") or "").strip(),
        "stock": stock,
        "estado": str(p.get("estado") or "").strip(),
        "precio": float(precio or 0),
        "volumetrico": float(p.get("volumetrico") or 1),
        "es_inventariable": es_inventariable,
        "tipo_producto": str(p.get("tipo_producto") or ("INVENTARIO" if es_inventariable else "ITEM_COTIZACION")),
        "origen_db": p.get("origen_db", ""),
    }


def cargar_catalogo() -> List[Dict[str, Any]]:
    # 1) Primero intenta Render/Postgres si DATABASE_URL está configurado.
    productos = cargar_productos_postgres()

    # 2) Si no hay, intenta SQLite dentro del programa.
    if not productos:
        base_dir = encontrar_dir_programa()
        rutas = [
            base_dir / "database" / "hilorama.db",
            base_dir / "hilorama.db",
            Path.cwd() / "database" / "hilorama.db",
            Path.cwd() / "hilorama.db",
        ]
        vistos = set()
        for r in rutas:
            if str(r) in vistos:
                continue
            vistos.add(str(r))
            productos = cargar_productos_sqlite(r)
            if productos:
                break

    normalizados = [normalizar_producto(p) for p in productos]

    # Quitar vacíos.
    normalizados = [p for p in normalizados if p["codigo"] or p["marca"] or p["hilo"]]
    return normalizados


CATALOGO = cargar_catalogo()


# ============================================================
# CATÁLOGOS, FOTOS Y FICHAS DE PRODUCTO
# Busca imágenes/PDF dentro de la misma carpeta del programa.
# Ejemplos esperados:
#   Hilorama/velluto/55.webp
#   Hilorama/velluto/Imagenes para enviar/colores.jpg
#   Hilorama/catalogos/velluto.pdf
# ============================================================

EXTENSIONES_MEDIA = {".jpg", ".jpeg", ".png", ".webp", ".jfif", ".pdf"}

PALABRAS_CATALOGO = [
    "catalogo", "catálogo", "catalo", "catalog", "catalogos", "catálogos", "carta de colores", "carta colores",
    "muestrario", "colores", "tonos", "lista de colores", "gama de colores",
]

PALABRAS_FOTO_TONO = [
    "foto", "fotos", "imagen", "imagenes", "imágenes", "muestra", "muestrame", "muéstrame",
    "enseñame", "ensename", "ver el tono", "tono real", "luz natural", "a la luz", "como se ve",
]

PALABRAS_INFO_PRODUCTO = [
    "grosor", "grueso", "gruesito", "delgado", "textura", "suave", "pica", "material",
    "aguja", "gancho", "numero de gancho", "número de gancho", "sirve", "uso", "usar",
    "amigurumi", "amigurumis", "bebe", "bebé", "manta", "cobija", "rinde", "rendimiento",
]

FICHAS_DEFAULT = {
    "velluto": {
        "nombre": "Velluto",
        "descripcion": "es un hilo suave y gruesito, tipo terciopelo/chenille",
        "usos": "se usa mucho para amigurumis grandes, mantitas, cojines y proyectos esponjosos",
        "tono": "el tono puede variar un poco por iluminación o pantalla",
        "respuesta": "Velluto es suave y gruesito, tipo terciopelo/chenille 😊 Se usa mucho para amigurumis grandes, mantitas, cojines y proyectos esponjosos. El tono puede variar un poquito por la luz o la pantalla.",
    },
    "komfy": {
        "nombre": "Komfy",
        "descripcion": "es un hilo suave y esponjoso",
        "usos": "se usa para proyectos tejidos suaves, muñecos, mantitas y accesorios",
        "tono": "el tono puede variar un poco por iluminación o pantalla",
        "respuesta": "Komfy es un hilo suave y esponjoso 😊 Sirve para proyectos tejidos suaves, muñecos, mantitas y accesorios. El tono puede variar un poquito por la luz o la pantalla.",
    },
    "komfy mini": {
        "nombre": "Komfy mini",
        "descripcion": "es una versión más pequeña/delgada dentro de la línea Komfy",
        "usos": "sirve para detalles, muñecos y proyectos más pequeños",
        "tono": "el tono puede variar un poco por iluminación o pantalla",
        "respuesta": "Komfy mini es ideal para detalles y proyectos más pequeños 😊 El tono puede variar un poquito por la luz o la pantalla.",
    },
    "trapillo kraft": {
        "nombre": "Trapillo kraft",
        "descripcion": "es un material más firme para proyectos de tejido decorativo",
        "usos": "se usa para bolsas, canastas, tapetes y decoración",
        "tono": "el tono puede variar un poco por iluminación o pantalla",
        "respuesta": "Trapillo kraft es más firme y se usa mucho para bolsas, canastas, tapetes y decoración 😊",
    },
}


def cargar_fichas_externas() -> Dict[str, Any]:
    """Opcional: si existe fichas_productos.json en Hilorama, lo usa para respuestas más exactas."""
    ruta = encontrar_dir_programa() / "fichas_productos.json"
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {normalizar(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


FICHAS_EXTERNAS = cargar_fichas_externas()


def posibles_dirs_media() -> List[Path]:
    base = encontrar_dir_programa()
    candidatos = [
        base,
        base / "catalogos",
        base / "catálogos",
        base / "fotos_tonos",
        base / "fotos tonos",
        base / "imagenes",
        base / "imágenes",
        base / "images",
        base / "velluto",
        base / "Velluto",
    ]
    salida = []
    vistos = set()
    for c in candidatos:
        try:
            c = c.resolve()
        except Exception:
            pass
        if c.exists() and c.is_dir() and str(c).lower() not in vistos:
            salida.append(c)
            vistos.add(str(c).lower())
    return salida


def inferir_producto_desde_path(path: Path) -> str:
    partes = [normalizar(p) for p in path.parts]
    # Importante: muchas imágenes están dentro de /velluto/komfy o /velluto/komfy mini.
    # Por eso revisamos primero las carpetas internas/productos más específicos, y Velluto al final.
    conocidos = ["komfy mini", "komfy", "kairo", "kurumi", "trapillo kraft", "krame 3mm", "velluto"]
    texto = " ".join(partes)
    for k in conocidos:
        if k in texto:
            return k
    # Si está en /catalogos/velluto.pdf usa el nombre del archivo.
    stem = normalizar(path.stem)
    for k in conocidos:
        if k in stem:
            return k
    return ""


def clasificar_media(path: Path, root: Path) -> Dict[str, Any]:
    rel = str(path.relative_to(root)) if str(path).startswith(str(root)) else str(path)
    stem_norm = normalizar(path.stem)
    rel_norm = normalizar(rel)
    producto = inferir_producto_desde_path(path)

    tipo = "archivo"
    if any(p in rel_norm for p in ["catalogo", "catalogos", "carta", "muestrario", "colores"]):
        tipo = "catalogo"
    if "envio" in rel_norm or "envios" in rel_norm or "paqueteria" in rel_norm:
        tipo = "envios"

    codigo = ""
    # Archivos tipo 55.webp, 01-BLANCO.webp, 104_GRIS.webp
    m = re.match(r"^(\d{1,6})(?:\b|[-_\s])", stem_norm)
    if m:
        codigo = m.group(1).lstrip("0") or "0"
        if tipo == "archivo":
            tipo = "foto_tono"

    return {
        "tipo": tipo,
        "producto": producto,
        "codigo": codigo,
        "nombre": path.name,
        "ruta": str(path),
        "relativa": rel,
        "extension": path.suffix.lower(),
        "luz_natural": any(p in rel_norm for p in ["luz natural", "natural", "real"]),
    }


def construir_indice_medios(max_archivos: int = 5000) -> List[Dict[str, Any]]:
    medios = []
    vistos = set()
    for root in posibles_dirs_media():
        try:
            for path in root.rglob("*"):
                if len(medios) >= max_archivos:
                    break
                if not path.is_file() or path.suffix.lower() not in EXTENSIONES_MEDIA:
                    continue
                # Evita archivos del sistema o cotizaciones/notas PDF generadas.
                rel_norm = normalizar(str(path))
                if "__pycache__" in rel_norm:
                    continue
                nombre_norm = normalizar(path.name)
                if path.suffix.lower() == ".pdf" and (nombre_norm.startswith("cot ") or nombre_norm.startswith("cot-") or "nota" in nombre_norm or "premium" in nombre_norm):
                    continue
                key = str(path.resolve()).lower()
                if key in vistos:
                    continue
                vistos.add(key)
                medios.append(clasificar_media(path, root))
        except Exception:
            continue
    return medios


MEDIA_INDEX = construir_indice_medios()


# ============================================================
# APRENDIZAJE LOCAL SEGURO
# No entrena el modelo grande; guarda correcciones/reglas en JSON.
# Así, si Jorge corrige una frase, el programa la recuerda para la próxima.
# ============================================================

APRENDIZAJE_PATH = Path(os.getenv("HILORAMA_APRENDIZAJE_PATH", "").strip() or (encontrar_dir_programa() / "ia_hilorama_aprendizaje.json"))


def cargar_aprendizaje() -> Dict[str, Any]:
    if not APRENDIZAJE_PATH.exists():
        return {
            "alias_texto": {},
            "respuestas_fijas": [],
            "catalogos_producto": {},
            "correcciones": [],
        }
    try:
        with open(APRENDIZAJE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data.setdefault("alias_texto", {})
    data.setdefault("respuestas_fijas", [])
    data.setdefault("catalogos_producto", {})
    data.setdefault("correcciones", [])
    return data


def guardar_aprendizaje(data: Dict[str, Any]) -> None:
    try:
        APRENDIZAJE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(APRENDIZAJE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


APRENDIZAJE = cargar_aprendizaje()


def aplicar_alias_texto(mensaje: str) -> str:
    """Corrige faltas recurrentes antes de analizar: komfi -> komfy, etc."""
    salida = str(mensaje or "")
    aliases = dict(APRENDIZAJE.get("alias_texto") or {})
    # Aliases de fábrica. Los del JSON pueden agregar más.
    aliases.setdefault("comfi", "komfy")
    aliases.setdefault("komfi", "komfy")
    aliases.setdefault("comfy", "komfy")
    aliases.setdefault("catalo", "catálogo")
    aliases.setdefault("catalog", "catálogo")
    # Reemplazo por palabra, sin destruir códigos/números.
    for mal, bien in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
        if not mal or not bien:
            continue
        salida = re.sub(r"\b" + re.escape(str(mal)) + r"\b", str(bien), salida, flags=re.IGNORECASE)
    return salida


def registrar_alias_texto(mal: str, bien: str) -> str:
    data = cargar_aprendizaje()
    mal_n = normalizar(mal)
    bien = str(bien).strip()
    if not mal_n or not bien:
        return "No pude guardar el alias; usa /aprender_alias error=correcto"
    data.setdefault("alias_texto", {})[mal_n] = bien
    data.setdefault("correcciones", []).append({"tipo": "alias_texto", "mal": mal_n, "bien": bien, "fecha": ahora_iso()})
    guardar_aprendizaje(data)
    global APRENDIZAJE
    APRENDIZAJE = cargar_aprendizaje()
    return f"Aprendido: cuando escriban '{mal}', lo interpretaré como '{bien}'."


def registrar_respuesta_fija(patron: str, respuesta: str) -> str:
    data = cargar_aprendizaje()
    patron_n = normalizar(patron)
    respuesta = str(respuesta).strip()
    if not patron_n or not respuesta:
        return "No pude guardar la respuesta; usa /aprender_respuesta frase=>respuesta"
    data.setdefault("respuestas_fijas", []).append({
        "patron": patron_n,
        "respuesta_cliente": respuesta,
        "fecha": ahora_iso(),
    })
    data.setdefault("correcciones", []).append({"tipo": "respuesta_fija", "patron": patron_n, "respuesta": respuesta, "fecha": ahora_iso()})
    guardar_aprendizaje(data)
    global APRENDIZAJE
    APRENDIZAJE = cargar_aprendizaje()
    return f"Aprendido: para una frase parecida a '{patron}', responderé con esa respuesta."


def resultado_aprendido(mensaje: str) -> Optional[Dict[str, Any]]:
    t = normalizar(aplicar_alias_texto(mensaje))
    for regla in APRENDIZAJE.get("respuestas_fijas", []) or []:
        patron = normalizar(regla.get("patron"))
        if not patron:
            continue
        # Match exacto o por contenido. Esto es conservador para no disparar reglas por error.
        if t == patron or patron in t:
            return {
                "intencion": "otro",
                "productos": [],
                "datos_faltantes": [],
                "respuesta_cliente": str(regla.get("respuesta_cliente") or "").strip(),
                "accion_sugerida": "responder",
                "requiere_humano": False,
                "razon_humano": "",
                "confianza": 96,
                "resumen_para_dueno": "Respuesta tomada del aprendizaje local.",
                "puede_crear_cotizacion": False,
                "aprendido": True,
            }
    return None


def respuesta_aclaracion(mensaje: str, motivo: str = "No entendí con seguridad el pedido.", items_parciales: Optional[List[Dict[str, Any]]] = None, dudas: str = "") -> Dict[str, Any]:
    texto_items = resumen_items(items_parciales or [], para_cliente=True) if items_parciales else ""
    if texto_items and dudas:
        respuesta = f"Creo que entendí {texto_items}, pero me falta confirmar: {dudas}. ¿Me lo puedes mandar así: cantidad + tono? 😊"
    elif texto_items:
        respuesta = f"Creo que entendí {texto_items}. ¿Me confirmas si está correcto? 😊"
    else:
        respuesta = "Perdón 😊 ¿Me lo puedes mandar como cantidad + tono? Por ejemplo: 2 del #19, 4 del #466."
    return {
        "intencion": "pedir_aclaracion",
        "productos": items_parciales or [],
        "datos_faltantes": ["confirmación"],
        "respuesta_cliente": respuesta,
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 55,
        "resumen_para_dueno": motivo,
        "puede_crear_cotizacion": False,
        "texto_original": mensaje,
    }


def reindexar_medios() -> int:
    """Vuelve a leer imágenes/PDF sin reiniciar el programa."""
    global MEDIA_INDEX
    MEDIA_INDEX = construir_indice_medios()
    return len(MEDIA_INDEX)


def buscar_medios(producto: str = "", codigo: str = "", tipo: str = "", limite: int = 5) -> List[Dict[str, Any]]:
    prod_norm = normalizar(producto)
    cod_norm = normalizar(codigo).lstrip("0") if codigo else ""
    resultados = []
    exactos_codigo = []

    for m in MEDIA_INDEX:
        score = 0
        tipo_m = m.get("tipo")
        if tipo and tipo_m == tipo:
            score += 40
        elif tipo:
            # Permite usar foto_tono como apoyo cuando piden foto a luz natural y no hay exacta.
            if tipo == "foto_tono" and tipo_m in {"foto_tono", "archivo"}:
                score += 15
            else:
                continue

        if prod_norm:
            prod_m = normalizar(m.get("producto"))
            rel_m = normalizar(m.get("relativa"))
            if prod_norm and (prod_norm in prod_m or prod_norm in rel_m):
                score += 35
            else:
                score -= 10

        coincide_codigo = False
        if cod_norm:
            cod_m = normalizar(m.get("codigo", "")).lstrip("0")
            rel_m = normalizar(m.get("relativa", ""))
            coincide_codigo = cod_m == cod_norm or bool(re.search(rf"(^|[^0-9])0*{re.escape(cod_norm)}([^0-9]|$)", rel_m))
            if coincide_codigo:
                score += 80
            else:
                score -= 60

        if m.get("luz_natural"):
            score += 5

        if score > 0:
            resultados.append((score, m))
            if cod_norm and coincide_codigo:
                exactos_codigo.append((score, m))

    # Si se pidió un código y existen archivos exactos para ese código, no regresamos otros tonos.
    if exactos_codigo:
        exactos_codigo.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in exactos_codigo[:limite]]

    resultados.sort(key=lambda x: (x[0], x[1].get("tipo") == "catalogo"), reverse=True)
    return [m for _, m in resultados[:limite]]


def media_producto_coincide(m: Dict[str, Any], producto: str) -> bool:
    prod_norm = producto_canonico(producto)
    if not prod_norm:
        return True
    prod_m = normalizar(m.get("producto"))
    rel_m = normalizar(m.get("relativa"))
    texto = f"{prod_m} {rel_m}"

    if prod_norm == "komfy":
        # Evita que Komfy agarre carpeta Komfy mini.
        if "komfy mini" in texto:
            return False
        return re.search(r"(^|[^a-z0-9])komfy([^a-z0-9]|$)", texto) is not None

    if prod_norm == "komfy mini":
        return "komfy mini" in texto

    return prod_norm in texto


def buscar_medios_generales_producto(producto: str = "", limite: int = 6) -> List[Dict[str, Any]]:
    """
    Busca archivos útiles cuando el cliente pide "el de Komfy mini" o "o Komfy?"
    sin especificar tono. Prioriza catálogos o imágenes generales y evita abrir
    cotizaciones/notas generadas.
    """
    prod_norm = producto_canonico(producto)
    if not prod_norm:
        return []

    resultados = []
    for m in MEDIA_INDEX:
        rel = normalizar(m.get("relativa"))
        prod_m = normalizar(m.get("producto"))
        nombre = normalizar(m.get("nombre"))
        codigo = normalizar(m.get("codigo"))

        if not media_producto_coincide(m, prod_norm):
            continue
        if "cot" in nombre and m.get("extension") == ".pdf":
            continue
        if "nota" in nombre and m.get("extension") == ".pdf":
            continue

        score = 0
        tipo = m.get("tipo")
        if tipo == "catalogo":
            score += 120
        elif tipo == "foto_tono":
            score += 40
        else:
            score += 30

        # Si el archivo no trae código o no es un simple número, suele servir como imagen general.
        if not codigo:
            score += 40
        stem = normalizar(Path(m.get("nombre", "")).stem)
        if not re.fullmatch(r"\d{1,6}", stem or ""):
            score += 20
        if m.get("extension") in {".jpg", ".jpeg", ".png"}:
            score += 8

        resultados.append((score, m))

    resultados.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in resultados[:limite]]


def respuesta_catalogo_o_medios_producto(producto: str, etiqueta: str = "") -> Dict[str, Any]:
    """Devuelve catálogo si existe; si no, sugiere imágenes disponibles del producto."""
    producto_norm = producto_canonico(producto)
    etiqueta = etiqueta or etiqueta_producto(producto_norm)

    medios_catalogo = [m for m in MEDIA_INDEX if m.get("tipo") == "catalogo" and media_producto_coincide(m, producto_norm)][:5]
    if medios_catalogo:
        return {
            "intencion": "pedir_catalogo",
            "productos": [],
            "datos_faltantes": [],
            "respuesta_cliente": f"Claro 😊 Te comparto el catálogo/colores de {etiqueta}.",
            "accion_sugerida": "enviar_catalogo",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 94,
            "resumen_para_dueno": f"Cliente pidió catálogo de {etiqueta}. Archivos sugeridos: {', '.join(m['relativa'] for m in medios_catalogo)}",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": medios_catalogo,
        }

    medios_generales = buscar_medios_generales_producto(producto_norm, limite=6)
    if medios_generales:
        return {
            "intencion": "pedir_catalogo",
            "productos": [],
            "datos_faltantes": [],
            "respuesta_cliente": f"Claro 😊 Te comparto las imágenes/tonos que tengo de {etiqueta}. Si quieres un tono específico, dime el número.",
            "accion_sugerida": "enviar_archivo",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 88,
            "resumen_para_dueno": f"Cliente pidió archivos de {etiqueta}. Archivos sugeridos: {', '.join(m['relativa'] for m in medios_generales)}",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": medios_generales,
        }

    return {
        "intencion": "pedir_catalogo",
        "productos": [],
        "datos_faltantes": [],
        "respuesta_cliente": f"Claro 😊 Déjame revisar las imágenes de {etiqueta} y te las comparto en un momento.",
        "accion_sugerida": "avisar_a_jorge",
        "requiere_humano": True,
        "razon_humano": f"No encontré archivos para {etiqueta}.",
        "confianza": 75,
        "resumen_para_dueno": f"Cliente pidió archivos de {etiqueta}, pero no encontré medios.",
        "puede_crear_cotizacion": False,
        "archivos_sugeridos": [],
    }


def detectar_solicitud_media_producto(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """
    Entiende seguimientos naturales después de enseñar catálogo/fotos:
    - "me podrías mandar el de komfy mini también"
    - "o komfy?"
    - "ahora komfy"
    """
    t = normalizar(mensaje)
    if not t:
        return None

    # No convertir pedidos reales en archivos.
    bloqueos = ["quiero", "necesito", "deseo", "dame", "me das", "precio", "cuanto", "cuanto cuesta", "stock", "hay", "tienes", "comprar"]
    if any(b in t for b in bloqueos):
        return None

    alias_detectado = ""
    etiqueta = ""
    for alias, nombre in ALIAS_PRODUCTOS_BASE:
        a = normalizar(alias)
        if re.search(r"\b" + re.escape(a) + r"\b", t):
            alias_detectado = producto_canonico(a)
            etiqueta = nombre
            break

    if not alias_detectado:
        return None

    # Si no hay contexto de medios, solo lo tratamos como medios si el mensaje trae verbos de enviar/mostrar.
    hay_contexto_media = bool(estado and estado.get("ultima_accion_media"))
    palabras_media = ["mandar", "mandas", "mandame", "mandamelo", "enviar", "pasar", "pasame", "muestra", "muestras", "muestrame", "ver", "tambien", "también", "ahora", "otro", "otra"]
    empieza_o = t.startswith("o ") or t.startswith("u ")

    if hay_contexto_media or empieza_o or any(p in t for p in palabras_media):
        return alias_detectado, etiqueta

    return None


def detectar_intencion_catalogo(mensaje: str) -> bool:
    t = normalizar(mensaje)
    return any(normalizar(p) in t for p in PALABRAS_CATALOGO)


def detectar_intencion_foto_tono(mensaje: str) -> bool:
    t = normalizar(mensaje)
    return any(normalizar(p) in t for p in PALABRAS_FOTO_TONO)


def detectar_intencion_info_producto(mensaje: str) -> bool:
    t = normalizar(mensaje)
    return any(normalizar(p) in t for p in PALABRAS_INFO_PRODUCTO)


def extraer_codigo_mencionado(mensaje: str) -> str:
    t = normalizar(mensaje)
    # Prioridad a frases explícitas: tono 55, código 55, #55
    m = re.search(r"(?:tono|codigo|cod|#)\s*(\d{1,6})\b", t)
    if m:
        return m.group(1).lstrip("0") or "0"
    nums = re.findall(r"\b\d{1,6}\b", t)
    # Para fotos/catálogos, un número solo suele ser el tono.
    if len(nums) == 1:
        return nums[0].lstrip("0") or "0"
    return ""


def producto_alias_mencionado(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> str:
    t = normalizar(mensaje)
    for alias, _ in ALIAS_PRODUCTOS_BASE:
        if normalizar(alias) in t:
            return producto_canonico(alias)
    if estado and estado.get("ultimo_media_producto"):
        return normalizar(estado.get("ultimo_media_producto"))
    if estado and isinstance(estado.get("ultimo_producto"), dict):
        return normalizar(estado["ultimo_producto"].get("hilo") or estado["ultimo_producto"].get("marca") or "")
    if estado and estado.get("pedido_actual"):
        pedido = estado.get("pedido_actual") or []
        if pedido and isinstance(pedido[0], dict):
            return normalizar(pedido[0].get("hilo") or pedido[0].get("marca") or "")
    return ""


def producto_desde_mensaje_o_memoria(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    items = detectar_producto_sin_cantidad(mensaje)
    if items:
        return items
    if estado and isinstance(estado.get("ultimo_producto"), dict):
        return [item_desde_memoria(estado["ultimo_producto"], 0)]
    if estado and estado.get("pedido_actual"):
        pedido = estado.get("pedido_actual") or []
        if pedido and isinstance(pedido[0], dict):
            return [item_desde_memoria(pedido[0], int(pedido[0].get("cantidad") or 0))]
    return []




def respuesta_catalogo_general() -> Dict[str, Any]:
    """Responde cuando el cliente quiere 'todo lo que vendes', no una línea específica."""
    medios_generales = []
    for m in MEDIA_INDEX:
        rel = normalizar(m.get("relativa"))
        nombre = normalizar(m.get("nombre"))
        if m.get("tipo") == "catalogo" and any(p in f"{rel} {nombre}" for p in ["general", "hilorama", "todo", "productos", "tienda"]):
            medios_generales.append(m)

    if medios_generales:
        return {
            "intencion": "pedir_catalogo",
            "productos": [],
            "datos_faltantes": [],
            "respuesta_cliente": "Claro 😊 Te comparto el catálogo general de lo que manejamos.",
            "accion_sugerida": "enviar_catalogo",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 94,
            "resumen_para_dueno": f"Cliente pidió catálogo general. Archivos sugeridos: {', '.join(m['relativa'] for m in medios_generales[:5])}",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": medios_generales[:5],
        }

    # Si no existe catálogo general, no inventamos ni escogemos un tono al azar.
    productos = sorted({str(p.get("hilo") or p.get("marca") or "").strip().title() for p in CATALOGO if str(p.get("hilo") or p.get("marca") or "").strip()})
    principales = []
    for nombre in ["Velluto", "Komfy", "Komfy Mini", "Kairo", "Kurumi", "Gancho", "Accesorio"]:
        if any(nombre.lower() in p.lower() for p in productos):
            principales.append(nombre)
    if not principales:
        principales = productos[:8]

    lista = ", ".join(principales[:8]) if principales else "Velluto, Komfy, Komfy mini, hilos y accesorios"
    return {
        "intencion": "pedir_catalogo",
        "productos": [],
        "datos_faltantes": ["categoría"],
        "respuesta_cliente": f"Claro 😊 Manejo {lista}. No tengo un catálogo general único aquí, pero te puedo compartir por categoría. ¿Quieres que te mande Velluto, Komfy o Komfy mini?",
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 88,
        "resumen_para_dueno": "Cliente pidió catálogo general; no encontré archivo general, se pidió elegir categoría.",
        "puede_crear_cotizacion": False,
        "archivos_sugeridos": [],
    }

def respuesta_catalogo(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Catálogo es diferente a pedir un producto específico.
    Usa alias/carpeta de medios; si no existe catálogo general, sugiere imágenes/tonos disponibles.
    """
    t = normalizar(mensaje)
    producto = ""
    desc = "catálogo"
    items: List[Dict[str, Any]] = []

    for alias, nombre in ALIAS_PRODUCTOS_BASE:
        alias_norm = normalizar(alias)
        if alias_norm and re.search(r"\b" + re.escape(alias_norm) + r"\b", t):
            producto = producto_canonico(alias_norm)
            desc = nombre
            break

    # Si pide un catálogo general, NO usamos memoria del último producto.
    if detectar_catalogo_general(mensaje):
        return respuesta_catalogo_general()

    if not producto and estado and estado.get("ultimo_media_producto"):
        producto = producto_canonico(estado.get("ultimo_media_producto"))
        desc = etiqueta_producto(producto) if producto else "catálogo"

    if not producto and estado and isinstance(estado.get("ultimo_producto"), dict):
        producto = producto_canonico(estado["ultimo_producto"].get("hilo") or estado["ultimo_producto"].get("marca") or "")
        desc = etiqueta_producto(producto) if producto else "catálogo"

    if producto:
        r = respuesta_catalogo_o_medios_producto(producto, desc)
        r["productos"] = items
        return r

    medios = buscar_medios(producto=producto, tipo="catalogo", limite=5)
    if medios:
        return {
            "intencion": "pedir_catalogo",
            "productos": items,
            "datos_faltantes": [],
            "respuesta_cliente": "Claro 😊 Te comparto el catálogo/colores.",
            "accion_sugerida": "enviar_catalogo",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 94,
            "resumen_para_dueno": f"Cliente pidió catálogo. Archivos sugeridos: {', '.join(m['relativa'] for m in medios)}",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": medios,
        }

    return {
        "intencion": "pedir_catalogo",
        "productos": items,
        "datos_faltantes": [],
        "respuesta_cliente": "Claro 😊 Déjame revisar el catálogo y te lo comparto en un momento.",
        "accion_sugerida": "avisar_a_jorge",
        "requiere_humano": True,
        "razon_humano": "No encontré archivo de catálogo en las carpetas del programa.",
        "confianza": 80,
        "resumen_para_dueno": "Cliente pidió catálogo, pero no encontré archivo para enviar.",
        "puede_crear_cotizacion": False,
        "archivos_sugeridos": [],
    }

def respuesta_foto_tono(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    codigo_mencionado = extraer_codigo_mencionado(mensaje)
    producto_alias = producto_alias_mencionado(mensaje, estado)

    # Si el cliente pidió una foto por tono/código, NO usamos el último producto
    # de memoria como producto del análisis. En v8 pasaba esto:
    #   Cliente: "me muestras tono 56"
    #   productos: Velluto blanco 55
    # porque venía de una consulta anterior. Para fotos basta con sugerir el archivo.
    # Si no menciona código, entonces sí usamos el producto/color de memoria o mensaje.
    items = [] if codigo_mencionado else producto_desde_mensaje_o_memoria(mensaje, estado)
    pide_luz_natural = "luz natural" in normalizar(mensaje) or "natural" in normalizar(mensaje)

    # Caso común: "foto del velluto tono 55". No necesitamos que el catálogo entienda color;
    # buscamos directamente archivo por producto + código.
    if codigo_mencionado and producto_alias:
        medios_codigo = buscar_medios(producto=producto_alias, codigo=codigo_mencionado, tipo="foto_tono", limite=3)
        if medios_codigo:
            desc_codigo = f"{producto_alias.title()} tono {codigo_mencionado}"
            exacta_luz = any(m.get("luz_natural") for m in medios_codigo)
            if pide_luz_natural and not exacta_luz:
                return {
                    "intencion": "pregunta_color_luz",
                    "productos": items,
                    "datos_faltantes": [],
                    "respuesta_cliente": f"Claro 😊 Tengo imagen de {desc_codigo}, pero si la necesitas a luz natural exacta déjame revisarlo y te confirmo.",
                    "accion_sugerida": "avisar_a_jorge",
                    "requiere_humano": True,
                    "razon_humano": "Hay imagen del tono, pero no está marcada como luz natural exacta.",
                    "confianza": 90,
                    "resumen_para_dueno": f"Cliente pidió foto de {desc_codigo}. Archivos sugeridos: {', '.join(m['relativa'] for m in medios_codigo)}",
                    "puede_crear_cotizacion": False,
                    "archivos_sugeridos": medios_codigo,
                }
            return {
                "intencion": "pedir_foto_tono",
                "productos": items,
                "datos_faltantes": [],
                "respuesta_cliente": f"Claro 😊 Te comparto la imagen de {desc_codigo}.",
                "accion_sugerida": "enviar_foto",
                "requiere_humano": False,
                "razon_humano": "",
                "confianza": 92,
                "resumen_para_dueno": f"Cliente pidió foto de {desc_codigo}. Archivos sugeridos: {', '.join(m['relativa'] for m in medios_codigo)}",
                "puede_crear_cotizacion": False,
                "archivos_sugeridos": medios_codigo,
            }

    if not items:
        return {
            "intencion": "pedir_foto_tono",
            "productos": [],
            "datos_faltantes": ["producto o tono"],
            "respuesta_cliente": "Claro 😊 ¿De qué producto y tono te gustaría ver foto?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 75,
            "resumen_para_dueno": "Cliente pidió foto de tono, pero falta producto/tono.",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": [],
        }

    it = items[0]
    producto = normalizar(it.get("hilo") or it.get("marca") or it.get("descripcion"))
    codigo = str(it.get("codigo") or "")
    desc = producto_texto_cliente(it)
    medios = buscar_medios(producto=producto, codigo=codigo, tipo="foto_tono", limite=3)

    if medios:
        exacta_luz = any(m.get("luz_natural") for m in medios)
        if pide_luz_natural and not exacta_luz:
            respuesta = f"Claro 😊 Tengo imagen de {desc}, pero si la necesitas a luz natural exacta déjame revisarlo y te confirmo."
            humano = True
            accion = "avisar_a_jorge"
            razon = "Hay imagen del tono, pero no está marcada como luz natural exacta."
        else:
            respuesta = f"Claro 😊 Te comparto la imagen de {desc}."
            humano = False
            accion = "enviar_foto"
            razon = ""
        return {
            "intencion": "pedir_foto_tono" if not pide_luz_natural else "pregunta_color_luz",
            "productos": items,
            "datos_faltantes": [],
            "respuesta_cliente": respuesta,
            "accion_sugerida": accion,
            "requiere_humano": humano,
            "razon_humano": razon,
            "confianza": 90,
            "resumen_para_dueno": f"Cliente pidió foto de {desc}. Archivos sugeridos: {', '.join(m['relativa'] for m in medios)}",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": medios,
        }

    return {
        "intencion": "pedir_foto_tono" if not pide_luz_natural else "pregunta_color_luz",
        "productos": items,
        "datos_faltantes": [],
        "respuesta_cliente": f"Claro 😊 Déjame revisar si tengo foto de {desc} y te la comparto.",
        "accion_sugerida": "avisar_a_jorge",
        "requiere_humano": True,
        "razon_humano": "No encontré imagen del tono en las carpetas del programa.",
        "confianza": 82,
        "resumen_para_dueno": f"Cliente pidió foto de {desc}, pero no encontré archivo.",
        "puede_crear_cotizacion": False,
        "archivos_sugeridos": [],
    }


def ficha_para_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    claves = [
        normalizar(item.get("hilo")),
        normalizar(item.get("marca")),
        normalizar(item.get("descripcion")),
    ]
    fichas = dict(FICHAS_DEFAULT)
    fichas.update(FICHAS_EXTERNAS)
    for clave in claves:
        if not clave:
            continue
        for k, ficha in fichas.items():
            if k and (k in clave or clave in k):
                return ficha
    return None


def respuesta_info_producto(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    items = producto_desde_mensaje_o_memoria(mensaje, estado)
    if not items:
        return {
            "intencion": "pregunta_uso",
            "productos": [],
            "datos_faltantes": ["producto"],
            "respuesta_cliente": "Claro 😊 ¿De qué producto quieres saber el grosor, textura o uso?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 75,
            "resumen_para_dueno": "Cliente preguntó una duda de producto, pero falta producto.",
            "puede_crear_cotizacion": False,
        }
    it = items[0]
    ficha = ficha_para_item(it)
    desc = producto_texto_cliente(it)
    if ficha:
        respuesta = ficha.get("respuesta") or f"{desc} {ficha.get('descripcion', '')}. {ficha.get('usos', '')}."
        return {
            "intencion": "pregunta_grosor" if any(p in normalizar(mensaje) for p in ["grosor", "grueso", "delgado", "aguja", "gancho"]) else "pregunta_uso",
            "productos": items,
            "datos_faltantes": [],
            "respuesta_cliente": respuesta.strip(),
            "accion_sugerida": "responder",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 86,
            "resumen_para_dueno": f"Cliente preguntó ficha/uso de {desc}.",
            "puede_crear_cotizacion": False,
            "ficha_producto": ficha,
        }

    return {
        "intencion": "pregunta_uso",
        "productos": items,
        "datos_faltantes": [],
        "respuesta_cliente": f"Déjame revisar bien la ficha de {desc} para no darte un dato incorrecto 😊",
        "accion_sugerida": "avisar_a_jorge",
        "requiere_humano": True,
        "razon_humano": "No hay ficha de producto configurada.",
        "confianza": 75,
        "resumen_para_dueno": f"Cliente pidió información técnica de {desc}; falta ficha.",
        "puede_crear_cotizacion": False,
    }


def respuesta_media_info(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    # Foto primero, porque 'foto de colores' podría ser catálogo, pero si menciona luz/tono se trata como foto.
    if detectar_intencion_foto_tono(mensaje):
        return respuesta_foto_tono(mensaje, estado)
    if detectar_intencion_catalogo(mensaje):
        return respuesta_catalogo(mensaje, estado)

    # Seguimientos después de enviar catálogo/foto: "el de Komfy mini también", "o Komfy?"
    seguimiento_media = detectar_solicitud_media_producto(mensaje, estado)
    if seguimiento_media:
        producto, etiqueta = seguimiento_media
        codigo = extraer_codigo_mencionado(mensaje)
        if codigo:
            return respuesta_foto_tono(f"foto {producto} tono {codigo}", estado)
        return respuesta_catalogo_o_medios_producto(producto, etiqueta)

    if detectar_intencion_info_producto(mensaje):
        return respuesta_info_producto(mensaje, estado)
    return None



# ============================================================
# MEMORIA DE CONVERSACIÓN
# Guarda el último producto/pedido para entender respuestas cortas como:
# Cliente: "Hola tienes velluto blanco?" -> IA pregunta cantidad
# Cliente: "5" -> IA entiende 5 Velluto blanco tono 55
# ============================================================

MEMORIA_PATH = Path(os.getenv("HILORAMA_MEMORIA_PATH", "").strip() or (encontrar_dir_programa() / "ia_hilorama_memoria.json"))


def ahora_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cargar_memoria() -> Dict[str, Any]:
    if not MEMORIA_PATH.exists():
        return {"clientes": {}}
    try:
        with open(MEMORIA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"clientes": {}}
        data.setdefault("clientes", {})
        return data
    except Exception:
        return {"clientes": {}}


def guardar_memoria(memoria: Dict[str, Any]) -> None:
    try:
        MEMORIA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORIA_PATH, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)
    except Exception:
        # No detenemos la venta si la memoria no se puede guardar.
        pass


def obtener_memoria_cliente(memoria: Dict[str, Any], cliente_id: str) -> Dict[str, Any]:
    memoria.setdefault("clientes", {})
    if cliente_id not in memoria["clientes"]:
        memoria["clientes"][cliente_id] = {
            "esperando": "",
            "ultimo_producto": None,
            "pedido_actual": [],
            "forma_entrega": "",
            "direccion_envio": "",
            "ultimo_media_producto": "",
            "ultima_accion_media": "",
            "ultimo_codigo_media": "",
            "actualizado": ahora_iso(),
        }
    else:
        # Compatibilidad si ya existe una memoria vieja de v7/v8.
        memoria["clientes"][cliente_id].setdefault("ultimo_media_producto", "")
        memoria["clientes"][cliente_id].setdefault("ultima_accion_media", "")
        memoria["clientes"][cliente_id].setdefault("ultimo_codigo_media", "")
    return memoria["clientes"][cliente_id]


def borrar_memoria_cliente(cliente_id: str = "demo") -> None:
    memoria = cargar_memoria()
    memoria.setdefault("clientes", {})
    memoria["clientes"].pop(cliente_id, None)
    guardar_memoria(memoria)


def ver_memoria_cliente(cliente_id: str = "demo") -> Dict[str, Any]:
    memoria = cargar_memoria()
    return obtener_memoria_cliente(memoria, cliente_id)


def item_memoria(item: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda solo campos seguros/importantes."""
    campos = [
        "codigo", "codigo_barras", "marca", "hilo", "color", "stock", "estado", "precio",
        "volumetrico", "es_inventariable", "descripcion", "cantidad", "subtotal",
    ]
    return {c: item.get(c) for c in campos}


def item_desde_memoria(item: Dict[str, Any], cantidad: int) -> Dict[str, Any]:
    """Reconstruye un item usando el catálogo actual para no usar stock viejo si cambió."""
    codigo = str(item.get("codigo") or "").strip()
    codigo_barras = str(item.get("codigo_barras") or "").strip()
    por_codigo = catalogo_por_codigo()

    prod = None
    if codigo:
        prod = por_codigo.get(normalizar(codigo).lstrip("0") or "0")
    if not prod and codigo_barras:
        prod = por_codigo.get(normalizar(codigo_barras))

    if prod:
        return item_desde_producto(prod, cantidad)

    # Respaldo si no encontramos el producto en el catálogo.
    copia = dict(item)
    try:
        stock = int(copia.get("stock") or 0)
    except Exception:
        stock = 0
    try:
        precio = float(copia.get("precio") or 0)
    except Exception:
        precio = 0.0

    copia["cantidad"] = int(cantidad)
    copia["stock"] = stock
    copia["precio"] = precio
    copia["subtotal"] = round(precio * int(cantidad), 2)
    copia["disponible"] = stock >= int(cantidad)
    copia["necesita_revision"] = stock < int(cantidad)
    copia["motivo_revision"] = f"Stock insuficiente: sistema marca {stock} y pidieron {cantidad}." if stock < int(cantidad) else ""
    copia.setdefault("candidatos", [])
    copia.setdefault("descripcion", producto_texto(copia))
    return copia


def es_solo_cantidad(mensaje: str) -> Optional[int]:
    t = normalizar(mensaje)
    m = re.fullmatch(r"(?:quiero|necesito|serian|serían|dame|me das)?\s*(\d+)\s*(?:piezas|pieza|pz|pzs|madejas|madeja)?\s*", t)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def detectar_entrega(mensaje: str) -> str:
    t = normalizar(mensaje)
    if any(p in t for p in ["envio", "enviar por paqueteria", "mandamelo por paqueteria", "mandalo por paqueteria", "paqueteria", "domicilio"]):
        return "envio"
    if any(p in t for p in ["recoger", "recojo", "paso", "pasaria", "pasaría", "local", "tienda"]):
        return "recoger"
    return ""


def parece_direccion_o_cp(mensaje: str) -> bool:
    t = normalizar(mensaje)
    if re.search(r"\b\d{5}\b", t):
        return True
    palabras = ["calle", "colonia", "col", "municipio", "alcaldia", "alcaldia", "estado", "cp", "codigo postal", "numero", "num"]
    return any(p in t for p in palabras) or len(t.split()) >= 4


def extraer_codigo_seguimiento_media(mensaje: str, estado: Dict[str, Any]) -> str:
    """
    Entiende respuestas como "ahora el 216" después de que el cliente pidió
    una foto/catálogo. Sin esta regla, Ollama puede interpretar 216 como stock
    o producto distinto.
    """
    if not estado.get("ultimo_media_producto"):
        return ""

    t = normalizar(mensaje)
    nums = re.findall(r"\b\d{1,6}\b", t)
    if len(nums) != 1:
        return ""

    # No lo tratamos como foto si claramente es una compra o precio.
    bloqueos = ["quiero", "necesito", "dame", "me das", "precio", "cuanto", "cuanto cuesta", "stock", "hay", "tienes"]
    if any(b in t for b in bloqueos):
        return ""

    palabras_ok = ["ahora", "el", "la", "tono", "codigo", "cod", "#", "otro", "otra", "tambien", "también", "muestra", "muestrame", "mandame", "pasa"]
    # Si solo escribió el número, también lo aceptamos como seguimiento de foto.
    solo_numero = re.fullmatch(r"\d{1,6}", t) is not None
    if solo_numero or any(p in t for p in palabras_ok):
        return nums[0].lstrip("0") or "0"

    return ""


def respuesta_desde_cantidad_memoria(cliente_id: str, cantidad: int, memoria: Dict[str, Any], estado: Dict[str, Any]) -> Dict[str, Any]:
    ultimo = estado.get("ultimo_producto")
    if not ultimo:
        return {
            "intencion": "otro",
            "productos": [],
            "datos_faltantes": ["producto"],
            "respuesta_cliente": "Claro 😊 ¿De qué producto serían esas piezas?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 70,
            "resumen_para_dueno": "Cliente dio cantidad, pero no hay producto previo en memoria.",
            "puede_crear_cotizacion": False,
        }

    item = item_desde_memoria(ultimo, cantidad)
    resultado = respuesta_pedido([item])
    actualizar_memoria_con_resultado(cliente_id, resultado)
    return resultado


def respuesta_desde_entrega_memoria(cliente_id: str, entrega: str, memoria: Dict[str, Any], estado: Dict[str, Any]) -> Dict[str, Any]:
    pedido = estado.get("pedido_actual") or []
    if not pedido:
        return {
            "intencion": "pregunta_envio",
            "productos": [],
            "datos_faltantes": ["producto", "cantidad"],
            "respuesta_cliente": "Claro 😊 ¿Qué producto y cantidad necesitas?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 75,
            "resumen_para_dueno": "Cliente habló de entrega, pero no hay pedido previo.",
            "puede_crear_cotizacion": False,
        }

    # Reconstruir items con stock/precio actual, conservando cantidades.
    items = [item_desde_memoria(i, int(i.get("cantidad") or 0)) for i in pedido]
    texto_items_cliente = resumen_items(items, para_cliente=True)
    texto_items_dueno = resumen_items(items, para_cliente=False)
    subtotal = round(sum(float(i.get("subtotal") or 0) for i in items), 2)

    if entrega == "recoger":
        estado["forma_entrega"] = "recoger"
        estado["esperando"] = ""
        estado["actualizado"] = ahora_iso()
        memoria["clientes"][cliente_id] = estado
        guardar_memoria(memoria)
        if subtotal > 0:
            respuesta_cliente = f"Perfecto 😊 Lo dejo para recoger. {texto_items_cliente} te queda en {dinero(subtotal)}."
        else:
            respuesta_cliente = f"Perfecto 😊 Lo dejo para recoger. Te preparo la cotización de {texto_items_cliente}."

        return {
            "intencion": "pedido",
            "productos": items,
            "datos_faltantes": [],
            "respuesta_cliente": respuesta_cliente,
            "accion_sugerida": "crear_cotizacion_pendiente",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 95,
            "resumen_para_dueno": f"Pedido completo para recoger: {texto_items_dueno}.",
            "puede_crear_cotizacion": True,
            "subtotal_detectado": subtotal,
            "forma_entrega": "recoger",
            "cotizacion_sugerida": {
                "forma_entrega": "recoger",
                "subtotal": subtotal,
                "productos": [
                    {
                        "codigo": i.get("codigo", ""),
                        "codigo_barras": i.get("codigo_barras", ""),
                        "marca": i.get("marca", ""),
                        "hilo": i.get("hilo", ""),
                        "color": i.get("color", ""),
                        "cantidad": int(i.get("cantidad") or 0),
                        "precio": float(i.get("precio") or 0),
                        "subtotal": float(i.get("subtotal") or 0),
                    }
                    for i in items
                ],
            },
        }

    if entrega == "envio":
        estado["forma_entrega"] = "envio"
        estado["esperando"] = "direccion_envio"
        estado["actualizado"] = ahora_iso()
        memoria["clientes"][cliente_id] = estado
        guardar_memoria(memoria)
        return {
            "intencion": "pregunta_envio",
            "productos": items,
            "datos_faltantes": ["codigo postal o dirección"],
            "respuesta_cliente": "Claro 😊 ¿Me compartes tu código postal o dirección para cotizar el envío?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 92,
            "resumen_para_dueno": f"Cliente eligió envío para: {texto_items_dueno}.",
            "puede_crear_cotizacion": False,
            "subtotal_detectado": subtotal,
            "forma_entrega": "envio",
        }

    return {
        "intencion": "pregunta_envio",
        "productos": items,
        "datos_faltantes": ["forma de entrega"],
        "respuesta_cliente": "Claro 😊 ¿Sería envío o pasas a recoger?",
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 80,
        "resumen_para_dueno": "Falta confirmar forma de entrega.",
        "puede_crear_cotizacion": False,
    }


def respuesta_desde_direccion_memoria(cliente_id: str, mensaje: str, memoria: Dict[str, Any], estado: Dict[str, Any]) -> Dict[str, Any]:
    pedido = estado.get("pedido_actual") or []
    items = [item_desde_memoria(i, int(i.get("cantidad") or 0)) for i in pedido]
    texto_items_dueno = resumen_items(items, para_cliente=False)
    subtotal = round(sum(float(i.get("subtotal") or 0) for i in items), 2)

    estado["direccion_envio"] = mensaje.strip()
    estado["esperando"] = "cotizar_envio"
    estado["actualizado"] = ahora_iso()
    memoria["clientes"][cliente_id] = estado
    guardar_memoria(memoria)

    return {
        "intencion": "pregunta_envio",
        "productos": items,
        "datos_faltantes": ["costo de envío"],
        "respuesta_cliente": "Gracias 😊 Con ese dato reviso el envío y te confirmo el total en un momento.",
        "accion_sugerida": "avisar_a_jorge",
        "requiere_humano": True,
        "razon_humano": "Falta cotizar el costo de envío antes de confirmar total.",
        "confianza": 90,
        "resumen_para_dueno": f"Cliente dio datos de envío para: {texto_items_dueno}. Dirección/CP: {mensaje.strip()}",
        "puede_crear_cotizacion": False,
        "subtotal_detectado": subtotal,
        "forma_entrega": "envio",
        "direccion_envio": mensaje.strip(),
    }


def procesar_respuesta_con_memoria(mensaje: str, cliente_id: str, memoria: Dict[str, Any], estado: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cantidad = es_solo_cantidad(mensaje)
    if cantidad is not None and estado.get("esperando") == "cantidad":
        return respuesta_desde_cantidad_memoria(cliente_id, cantidad, memoria, estado)

    entrega = detectar_entrega(mensaje)
    if entrega and (estado.get("esperando") == "forma_entrega" or estado.get("pedido_actual")):
        return respuesta_desde_entrega_memoria(cliente_id, entrega, memoria, estado)

    if estado.get("esperando") == "direccion_envio" and parece_direccion_o_cp(mensaje):
        return respuesta_desde_direccion_memoria(cliente_id, mensaje, memoria, estado)

    codigo_media = extraer_codigo_seguimiento_media(mensaje, estado)
    if codigo_media:
        producto_media = estado.get("ultimo_media_producto") or "velluto"
        return respuesta_foto_tono(f"foto {producto_media} tono {codigo_media}", estado)

    return None


def actualizar_memoria_con_resultado(cliente_id: str, resultado: Dict[str, Any]) -> None:
    memoria = cargar_memoria()
    estado = obtener_memoria_cliente(memoria, cliente_id)

    productos = resultado.get("productos") if isinstance(resultado.get("productos"), list) else []
    productos = [p for p in productos if isinstance(p, dict)]

    archivos = resultado.get("archivos_sugeridos") if isinstance(resultado.get("archivos_sugeridos"), list) else []
    if resultado.get("intencion") in {"pedir_catalogo", "pedir_foto_tono", "pregunta_color_luz"}:
        # Guarda el contexto de imágenes/catálogos para entender: "ahora el 216".
        if archivos and isinstance(archivos[0], dict):
            estado["ultimo_media_producto"] = normalizar(archivos[0].get("producto") or estado.get("ultimo_media_producto") or "")
            estado["ultimo_codigo_media"] = str(archivos[0].get("codigo") or "")
        elif productos:
            estado["ultimo_media_producto"] = normalizar(productos[0].get("hilo") or productos[0].get("marca") or estado.get("ultimo_media_producto") or "")
            estado["ultimo_codigo_media"] = str(productos[0].get("codigo") or "")
        estado["ultima_accion_media"] = str(resultado.get("intencion") or "")

    if resultado.get("intencion") in {"pregunta_stock", "pregunta_precio"} and productos:
        estado["ultimo_producto"] = item_memoria(productos[0])
        estado["esperando"] = "cantidad"

    if resultado.get("intencion") == "pedido" and productos:
        estado["pedido_actual"] = [item_memoria(p) for p in productos]
        # Si el pedido requiere humano, no esperamos entrega; primero debe revisar Jorge.
        if resultado.get("requiere_humano"):
            estado["esperando"] = "revision_humana"
        elif "forma de entrega" in resultado.get("datos_faltantes", []):
            estado["esperando"] = "forma_entrega"
        elif resultado.get("puede_crear_cotizacion"):
            estado["esperando"] = ""

    if resultado.get("forma_entrega"):
        estado["forma_entrega"] = resultado.get("forma_entrega")
    if resultado.get("direccion_envio"):
        estado["direccion_envio"] = resultado.get("direccion_envio")

    estado["ultima_respuesta"] = resultado.get("respuesta_cliente", "")
    estado["actualizado"] = ahora_iso()
    memoria["clientes"][cliente_id] = estado
    guardar_memoria(memoria)



def producto_texto(p: Dict[str, Any]) -> str:
    """Descripción completa para análisis interno/Jorge."""
    partes = []
    if p.get("marca"):
        partes.append(p["marca"])
    if p.get("hilo") and normalizar(p.get("hilo")) not in normalizar(" ".join(partes)):
        partes.append(p["hilo"])
    if p.get("color"):
        partes.append(p["color"])
    if p.get("codigo"):
        partes.append(f"tono/código {p['codigo']}")
    return " ".join(partes).strip()


def producto_texto_cliente(p: Dict[str, Any]) -> str:
    """Descripción más natural para WhatsApp, sin sonar a sistema."""
    hilo = str(p.get("hilo") or p.get("producto") or "producto").strip().title()
    color = str(p.get("color") or "").strip().lower()
    codigo = str(p.get("codigo") or "").strip()

    partes = []
    if hilo:
        partes.append(hilo)
    if color:
        partes.append(color)
    if codigo:
        partes.append(f"tono {codigo}")

    return " ".join(partes).strip() or "ese producto"


def catalogo_por_codigo() -> Dict[str, Dict[str, Any]]:
    d = {}
    for p in CATALOGO:
        if p.get("codigo"):
            d[normalizar(p["codigo"]).lstrip("0") or "0"] = p
        if p.get("codigo_barras"):
            d[normalizar(p["codigo_barras"])] = p
    return d



def catalogo_productos_por_codigo() -> Dict[str, List[Dict[str, Any]]]:
    d: Dict[str, List[Dict[str, Any]]] = {}
    for p in CATALOGO:
        if p.get("codigo"):
            k = normalizar(p["codigo"]).lstrip("0") or "0"
            d.setdefault(k, []).append(p)
        if p.get("codigo_barras"):
            kb = normalizar(p["codigo_barras"])
            d.setdefault(kb, []).append(p)
    return d


def seleccionar_producto_por_codigo_contexto(codigo: str, estado: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    codigo_norm = normalizar(codigo).lstrip("0") or "0"
    opciones = catalogo_productos_por_codigo().get(codigo_norm, [])
    if not opciones:
        return None
    if len(opciones) == 1:
        return opciones[0]

    contexto = ""
    if estado:
        contexto = normalizar(estado.get("ultimo_media_producto") or "")
        if not contexto and isinstance(estado.get("ultimo_producto"), dict):
            contexto = normalizar(estado["ultimo_producto"].get("hilo") or estado["ultimo_producto"].get("marca") or "")

    mejores = []
    for p in opciones:
        score = 0
        texto = normalizar(f"{p.get('marca')} {p.get('hilo')} {p.get('color')}")
        if contexto and contexto in texto:
            score += 40
        # Para Velluto de carta de colores, preferimos el producto de ALIZE con color real sobre paquetes/combo de HILORAMA.
        if contexto == "velluto":
            if normalizar(p.get("marca")) == "alize":
                score += 35
            if normalizar(p.get("marca")) == "hilorama":
                score -= 25
            if any(w in normalizar(p.get("color")) for w in ["surtido", "surtidos", "combo", "paquete"]):
                score -= 40
        if int(p.get("stock") or 0) > 0:
            score += 10
        if float(p.get("precio") or 0) > 0:
            score += 5
        mejores.append((score, p))

    mejores.sort(key=lambda x: x[0], reverse=True)
    return mejores[0][1]


def detectar_items_por_codigo_contextual(texto: str, estado: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Detecta listas tipo '2 del #19, 4 #466, 2#429' usando el producto de catálogo/foto reciente como contexto."""
    texto_norm = normalizar(texto)
    if not re.search(r"\d", texto_norm):
        return []

    items: List[Dict[str, Any]] = []

    def agregar(codigo: str, cantidad: int):
        prod = seleccionar_producto_por_codigo_contexto(codigo, estado)
        if prod:
            items.append(item_desde_producto(prod, cantidad))

    # 2 del #19 / 4 #466 / 2#429 / 3 tono 26
    for m in re.finditer(r"\b(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\s*(?:de|del|tono|codigo|cod|#)\s*(\d{1,13})\b", texto_norm):
        cantidad = int(m.group(1))
        codigo = m.group(2).lstrip("0") or "0"
        agregar(codigo, cantidad)

    # #19 x 2 / tono 19 x 2
    for m in re.finditer(r"(?:tono|codigo|cod|#)\s*(\d{1,13})\s*(?:x|\*)\s*(\d+)\b", texto_norm):
        codigo = m.group(1).lstrip("0") or "0"
        cantidad = int(m.group(2))
        agregar(codigo, cantidad)

    # Quitar duplicados exactos por patrones superpuestos.
    salida = []
    vistos = set()
    for i in items:
        k = (i.get("codigo"), i.get("cantidad"))
        if k in vistos:
            continue
        vistos.add(k)
        salida.append(i)
    return salida



def detectar_items_messy_contexto(texto: str, estado: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], str]:
    """
    Intenta entender listas muy humanas/desordenadas después de ver una gama:
    - "Deseo 2 del #19, 4 #466, 2#429, 2#26"
    - "de ese dame 2 del 3 4 y de 55 20"
    Si no puede saber con seguridad, devuelve items parciales + duda para preguntar aclaración.
    """
    t = normalizar(aplicar_alias_texto(texto))
    if not estado or not estado.get("ultimo_media_producto"):
        return [], ""
    if not any(w in t for w in ["dame", "quiero", "deseo", "necesito", "del", "#", "tono", "cod", "codigo"]):
        return [], ""

    # Primero usa el parser contextual normal.
    items = detectar_items_por_codigo_contextual(t, estado)
    usados: set = set((str(i.get("codigo")), int(i.get("cantidad") or 0)) for i in items)

    def agregar(codigo: str, cantidad: int):
        codigo = str(codigo).lstrip("0") or "0"
        prod = seleccionar_producto_por_codigo_contexto(codigo, estado)
        if not prod:
            return False
        key = (str(prod.get("codigo") or codigo), int(cantidad))
        if key in usados:
            return True
        usados.add(key)
        items.append(item_desde_producto(prod, int(cantidad)))
        return True

    # Segmentos separados por coma, salto, punto y coma.
    segmentos = re.split(r"[,;\n]+", t)
    for seg in segmentos:
        seg = seg.strip()
        if not seg:
            continue
        # patrón: cantidad + varios códigos después de "del/de/#/tono"
        # Ej: "2 del 3 4" -> 2 del tono 3 y 2 del tono 4.
        m = re.search(r"\b(\d+)\s*(?:pz|pzs|pieza|piezas)?\s*(?:de|del|tono|codigo|cod|#)\s*((?:\d{1,6}\s*){1,6})\b", seg)
        if m:
            cantidad = int(m.group(1))
            codigos = re.findall(r"\d{1,6}", m.group(2))
            for c in codigos:
                agregar(c, cantidad)

    # Si quedan muchos números que no fueron parte de un patrón claro, pedir confirmación.
    nums = re.findall(r"\b\d{1,6}\b", t)
    numeros_usados = []
    for i in items:
        numeros_usados.append(str(i.get("cantidad") or ""))
        numeros_usados.append(str(i.get("codigo") or ""))
    # Si hay números sin contexto y son más de 2, es mejor no inventar.
    sueltos = [n for n in nums if n not in numeros_usados]
    duda = ""
    if sueltos and len(nums) >= 3:
        duda = "hay números sueltos que no sé si son tonos o cantidades: " + ", ".join(sueltos[:8])

    return items, duda

def alias_catalogo() -> List[Tuple[str, str]]:
    aliases = list(ALIAS_PRODUCTOS_BASE)
    vistos = {a[0] for a in aliases}

    for p in CATALOGO:
        for campo in ("marca", "hilo"):
            val = normalizar(p.get(campo))
            if val and val not in vistos and len(val) >= 3:
                aliases.append((val, str(p.get(campo)).strip()))
                vistos.add(val)

    # Ordenar largo primero para que "komfy mini" gane sobre "komfy".
    aliases.sort(key=lambda x: len(x[0]), reverse=True)
    return aliases


def producto_coincide_alias(p: Dict[str, Any], alias_norm: str) -> bool:
    alias_norm = producto_canonico(alias_norm)
    texto = normalizar(f"{p.get('marca')} {p.get('hilo')}")
    if alias_norm == "komfy mini":
        return "komfy mini" in texto
    if alias_norm == "komfy":
        return "komfy" in texto and "komfy mini" not in texto
    return alias_norm in texto


def buscar_producto_por_nombre_color(alias_norm: str, color: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    color_norm = limpiar_color(color)
    candidatos = []

    for p in CATALOGO:
        if not producto_coincide_alias(p, alias_norm):
            continue

        score = 10
        p_color = normalizar(p.get("color"))
        p_texto = normalizar(producto_texto(p))

        if color_norm:
            palabras = color_norm.split()
            encontrados = sum(1 for w in palabras if w and w in p_color)
            if color_norm == p_color:
                score += 80
            elif color_norm and color_norm in p_color:
                score += 60
            elif encontrados:
                score += 20 * encontrados
            elif color_norm in p_texto:
                score += 20
            else:
                score -= 15

        candidatos.append((score, p))

    candidatos.sort(key=lambda x: (x[0], x[1].get("stock", 0)), reverse=True)
    buenos = [p for s, p in candidatos if s >= 10]

    if color_norm:
        exactos = [p for s, p in candidatos if s >= 50]
        if exactos:
            return exactos[0], exactos

    return (buenos[0] if buenos else None), buenos


def detectar_items_por_codigo(texto: str) -> List[Dict[str, Any]]:
    por_codigo = catalogo_por_codigo()
    if not por_codigo:
        return []

    texto_norm = normalizar(texto)
    lineas = [l.strip() for l in texto_norm.splitlines() if l.strip()]
    if not lineas:
        lineas = [texto_norm]

    items = []
    usados = set()

    def agregar(codigo: str, cantidad: int):
        c = (codigo.lstrip("0") or "0")
        p = por_codigo.get(codigo) or por_codigo.get(c)
        if not p:
            return
        key = (p.get("codigo"), cantidad, len(items))
        usados.add((p.get("codigo"), cantidad))
        items.append(item_desde_producto(p, cantidad))

    for linea in lineas:
        nums = re.findall(r"\b\d+\b", linea)
        if len(nums) == 2:
            a = nums[0].lstrip("0") or "0"
            b = nums[1].lstrip("0") or "0"
            a_prod = a in por_codigo
            b_prod = b in por_codigo
            if a_prod and not b_prod:
                agregar(a, int(b))
                continue
            if b_prod and not a_prod:
                agregar(b, int(a))
                continue
            if a_prod and b_prod:
                # En tu parser original, si ambos parecen código, toma el menor como cantidad.
                if int(a) < int(b):
                    agregar(b, int(a))
                else:
                    agregar(a, int(b))
                continue

        # formatos: tono 55 x 3, 55 (3 piezas), #55 3
        for m in re.finditer(r"(?:tono|codigo|cod|#)?\s*(\d{1,13})\s*(?:\(|x|\*|-)\s*(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\)?", linea):
            codigo = m.group(1).lstrip("0") or "0"
            cantidad = int(m.group(2))
            if codigo in por_codigo:
                agregar(codigo, cantidad)

        # formatos: 3 del 55, 3 pz tono 55
        for m in re.finditer(r"\b(\d+)\s*(?:pz|pza|pzas|pieza|piezas)?\s*(?:de|del|tono|codigo|cod|#)\s*(\d{1,13})\b", linea):
            cantidad = int(m.group(1))
            codigo = m.group(2).lstrip("0") or "0"
            if codigo in por_codigo:
                agregar(codigo, cantidad)

    # Quitar duplicados exactos generados por patrones superpuestos.
    salida = []
    vistos = set()
    for i in items:
        k = (i.get("codigo"), i.get("cantidad"))
        if k in vistos:
            continue
        vistos.add(k)
        salida.append(i)
    return salida


def detectar_items_por_nombre(texto: str) -> List[Dict[str, Any]]:
    texto_norm = normalizar(texto)
    numeros = list(re.finditer(r"\b\d+\b", texto_norm))
    aliases = alias_catalogo()
    items = []
    ultimo_alias = ""

    for idx, n in enumerate(numeros):
        cantidad = int(n.group())
        inicio = n.end()
        fin = numeros[idx + 1].start() if idx + 1 < len(numeros) else len(texto_norm)
        segmento = texto_norm[inicio:fin].strip(" ,.;:-")
        segmento = re.sub(r"^(de|del|la|el|los|las|y)\s+", "", segmento).strip()

        alias_encontrado = ""
        nombre_alias = ""
        pos_final_alias = 0
        for alias_norm, alias_original in aliases:
            m = re.search(r"\b" + re.escape(alias_norm) + r"\b", segmento)
            if m:
                alias_encontrado = alias_norm
                nombre_alias = alias_original
                pos_final_alias = m.end()
                break

        if alias_encontrado:
            color = segmento[pos_final_alias:].strip()
            ultimo_alias = alias_encontrado
        else:
            alias_encontrado = ultimo_alias
            color = segmento

        if not alias_encontrado:
            continue

        prod, candidatos = buscar_producto_por_nombre_color(alias_encontrado, color)
        if prod:
            items.append(item_desde_producto(prod, cantidad, color_mencionado=limpiar_color(color), candidatos=candidatos[:5]))
        else:
            items.append({
                "codigo": "",
                "marca": nombre_alias,
                "hilo": nombre_alias,
                "color": limpiar_color(color),
                "cantidad": cantidad,
                "stock": 0,
                "precio": 0,
                "disponible": None,
                "necesita_revision": True,
                "motivo_revision": "No encontré coincidencia exacta en el catálogo.",
                "descripcion": f"{cantidad} {nombre_alias} {limpiar_color(color)}".strip(),
                "candidatos": [],
            })

    return items


def detectar_producto_sin_cantidad(texto: str) -> List[Dict[str, Any]]:
    texto_norm = normalizar(texto)
    aliases = alias_catalogo()

    for alias_norm, alias_original in aliases:
        m = re.search(r"\b" + re.escape(alias_norm) + r"\b", texto_norm)
        if not m:
            continue
        color = limpiar_color(texto_norm[m.end():])
        prod, candidatos = buscar_producto_por_nombre_color(alias_norm, color)
        if prod:
            return [item_desde_producto(prod, 0, color_mencionado=color, candidatos=candidatos[:5])]
        return [{
            "codigo": "",
            "marca": alias_original,
            "hilo": alias_original,
            "color": color,
            "cantidad": 0,
            "stock": 0,
            "precio": 0,
            "disponible": None,
            "necesita_revision": True,
            "motivo_revision": "Producto mencionado, pero no encontré coincidencia exacta en el catálogo.",
            "descripcion": f"{alias_original} {color}".strip(),
            "candidatos": [],
        }]
    return []


def item_desde_producto(p: Dict[str, Any], cantidad: int, color_mencionado: str = "", candidatos: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    stock = int(p.get("stock", 0) or 0)
    precio = float(p.get("precio", 0) or 0)
    es_inventariable = as_bool(p.get("es_inventariable", True), True)

    if cantidad <= 0:
        disponible = stock > 0 or not es_inventariable
    elif not es_inventariable:
        disponible = True
    else:
        disponible = stock >= cantidad

    necesita_revision = False
    motivo = ""
    if cantidad > 0 and es_inventariable and stock < cantidad:
        necesita_revision = True
        motivo = f"Stock insuficiente: sistema marca {stock} y pidieron {cantidad}."
    elif p.get("codigo") == "":
        necesita_revision = True
        motivo = "Falta código del producto."

    return {
        "codigo": p.get("codigo", ""),
        "codigo_barras": p.get("codigo_barras", ""),
        "marca": p.get("marca", ""),
        "hilo": p.get("hilo", ""),
        "color": p.get("color", "") or color_mencionado,
        "cantidad": int(cantidad),
        "stock": stock,
        "estado": p.get("estado", ""),
        "precio": precio,
        "subtotal": round(precio * int(cantidad), 2) if cantidad and precio else 0,
        "volumetrico": p.get("volumetrico", 1),
        "es_inventariable": es_inventariable,
        "disponible": disponible,
        "necesita_revision": necesita_revision,
        "motivo_revision": motivo,
        "descripcion": producto_texto(p),
        "candidatos": [producto_texto(c) for c in (candidatos or [])[:5]],
    }


def unir_lista(items: List[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def resumen_items(items: List[Dict[str, Any]], incluir_precio: bool = False, para_cliente: bool = False) -> str:
    partes = []
    for it in items:
        cant = it.get("cantidad", 0)
        desc = producto_texto_cliente(it) if para_cliente else (it.get("descripcion") or "producto")
        if cant:
            texto = f"{cant} {desc}"
        else:
            texto = desc
        if incluir_precio and it.get("precio"):
            texto += f" ({dinero(it['precio'])} c/u)"
        partes.append(texto)
    return unir_lista(partes)


def caso_especial(mensaje: str) -> Optional[Dict[str, Any]]:
    t = normalizar(mensaje)

    if any(normalizar(p) in t for p in PALABRAS_COMPROBANTE):
        return {
            "intencion": "comprobante_pago",
            "productos": [],
            "datos_faltantes": [],
            "respuesta_cliente": "Gracias, ya recibí tu comprobante. Permíteme revisarlo y te confirmo 😊",
            "accion_sugerida": "avisar_a_jorge",
            "requiere_humano": True,
            "razon_humano": "Se debe verificar el pago antes de confirmar.",
            "confianza": 98,
            "resumen_para_dueno": "Cliente mandó comprobante de pago. Revisar antes de confirmar.",
            "puede_crear_cotizacion": False,
        }

    if any(normalizar(p) in t for p in PALABRAS_RECLAMO):
        return {
            "intencion": "reclamo",
            "productos": [],
            "datos_faltantes": [],
            "respuesta_cliente": "Permíteme revisar tu caso con detalle y enseguida te apoyamos.",
            "accion_sugerida": "avisar_a_jorge",
            "requiere_humano": True,
            "razon_humano": "El cliente parece molesto o hay posible reclamo.",
            "confianza": 95,
            "resumen_para_dueno": "Posible reclamo. Revisar personalmente.",
            "puede_crear_cotizacion": False,
        }

    return None


def respuesta_pedido(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    hay_revision = any(i.get("necesita_revision") for i in items)
    faltan_codigo = any(not i.get("codigo") for i in items)
    todos_precio = all(float(i.get("precio") or 0) > 0 for i in items)
    subtotal = sum(float(i.get("subtotal") or 0) for i in items)
    texto_items_cliente = resumen_items(items, incluir_precio=False, para_cliente=True)
    texto_items_dueno = resumen_items(items, incluir_precio=False, para_cliente=False)

    datos_faltantes = []
    if faltan_codigo:
        datos_faltantes.append("tono o código exacto")
    datos_faltantes.append("forma de entrega")

    if hay_revision:
        motivos = [i.get("motivo_revision") for i in items if i.get("motivo_revision")]
        return {
            "intencion": "pedido",
            "productos": items,
            "datos_faltantes": [],
            "respuesta_cliente": f"Claro 😊 Déjame revisar disponibilidad de {texto_items_cliente} y te confirmo en un momento.",
            "accion_sugerida": "avisar_a_jorge",
            "requiere_humano": True,
            "razon_humano": "; ".join(motivos) or "Hay productos que requieren revisión.",
            "confianza": 90,
            "resumen_para_dueno": f"Pedido detectado con revisión: {texto_items_dueno}.",
            "puede_crear_cotizacion": False,
            "subtotal_detectado": round(subtotal, 2),
        }

    respuesta = f"Perfecto 😊 Te armo la cotización de {texto_items_cliente}. ¿Será envío o pasas a recoger?"
    if todos_precio and subtotal > 0:
        respuesta = f"Perfecto 😊 {texto_items_cliente} te queda en {dinero(subtotal)}. ¿Será envío o pasas a recoger?"

    return {
        "intencion": "pedido",
        "productos": items,
        "datos_faltantes": ["forma de entrega"],
        "respuesta_cliente": respuesta,
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 95,
        "resumen_para_dueno": f"Pedido detectado: {texto_items_dueno}. Falta confirmar forma de entrega.",
        "puede_crear_cotizacion": False,
        "puede_preparar_cotizacion": True,
        "subtotal_detectado": round(subtotal, 2),
    }


def respuesta_stock(items: List[Dict[str, Any]], mensaje: str) -> Dict[str, Any]:
    if items:
        it = items[0]
        desc_cliente = producto_texto_cliente(it)
        desc_dueno = it.get("descripcion") or desc_cliente
        if it.get("disponible") is True:
            if it.get("stock", 0) > 0:
                respuesta = f"Sí, lo tengo disponible 😊 ¿Cuántas piezas necesitas de {desc_cliente}?"
            else:
                respuesta = f"Claro 😊 ¿Cuántas piezas necesitas de {desc_cliente} para revisarlo?"
        elif it.get("disponible") is False:
            respuesta = "Ahorita me aparece sin stock suficiente. Permíteme revisarlo y te confirmo."
        else:
            respuesta = "Claro 😊 ¿Me pasas el tono o código para revisarlo?"

        return {
            "intencion": "pregunta_stock",
            "productos": items,
            "datos_faltantes": ["cantidad"],
            "respuesta_cliente": respuesta,
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False if it.get("disponible") else True,
            "razon_humano": "" if it.get("disponible") else "No hubo coincidencia clara o stock suficiente.",
            "confianza": 90,
            "resumen_para_dueno": f"Cliente preguntó existencia de {desc_dueno}.",
            "puede_crear_cotizacion": False,
        }

    return {
        "intencion": "pregunta_stock",
        "productos": [],
        "datos_faltantes": ["producto", "tono o código", "cantidad"],
        "respuesta_cliente": "Claro 😊 ¿De qué producto y tono necesitas revisar existencia?",
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 75,
        "resumen_para_dueno": "Cliente pregunta stock, pero falta producto o tono.",
        "puede_crear_cotizacion": False,
    }


def respuesta_precio(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if items:
        it = items[0]
        desc_cliente = producto_texto_cliente(it)
        desc_dueno = it.get("descripcion") or desc_cliente
        if it.get("precio"):
            respuesta = f"Claro 😊 {desc_cliente} está en {dinero(it['precio'])} por pieza. ¿Cuántas necesitas?"
            datos = ["cantidad"]
            humano = False
            razon = ""
        else:
            respuesta = f"Claro 😊 Permíteme revisar el precio de {desc_cliente} y te confirmo."
            datos = []
            humano = True
            razon = "El producto no tiene precio de venta detectado."
        return {
            "intencion": "pregunta_precio",
            "productos": items,
            "datos_faltantes": datos,
            "respuesta_cliente": respuesta,
            "accion_sugerida": "pedir_dato" if not humano else "avisar_a_jorge",
            "requiere_humano": humano,
            "razon_humano": razon,
            "confianza": 88,
            "resumen_para_dueno": f"Cliente preguntó precio de {desc_dueno}.",
            "puede_crear_cotizacion": False,
        }

    return {
        "intencion": "pregunta_precio",
        "productos": [],
        "datos_faltantes": ["producto", "tono o código"],
        "respuesta_cliente": "Claro 😊 ¿De qué producto o tono quieres saber el precio?",
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 75,
        "resumen_para_dueno": "Cliente preguntó precio, pero falta producto.",
        "puede_crear_cotizacion": False,
    }


def extraer_json(texto: str) -> Dict[str, Any]:
    texto = texto.strip()
    try:
        return json.loads(texto)
    except Exception:
        pass
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("La IA no devolvió JSON válido.")


def normalizar_salida(resultado: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(resultado, dict):
        resultado = {}
    intencion = resultado.get("intencion", "otro")
    accion = resultado.get("accion_sugerida", "responder")
    if intencion not in INTENCIONES_VALIDAS:
        intencion = "otro"
    if accion not in ACCIONES_VALIDAS:
        accion = "responder"
    try:
        confianza = int(resultado.get("confianza", 70))
    except Exception:
        confianza = 70
    confianza = max(0, min(100, confianza))
    return {
        "intencion": intencion,
        "productos": resultado.get("productos") if isinstance(resultado.get("productos"), list) else [],
        "datos_faltantes": resultado.get("datos_faltantes") if isinstance(resultado.get("datos_faltantes"), list) else [],
        "respuesta_cliente": str(resultado.get("respuesta_cliente", "")).strip(),
        "accion_sugerida": accion,
        "requiere_humano": bool(resultado.get("requiere_humano", False)),
        "razon_humano": str(resultado.get("razon_humano", "")).strip(),
        "confianza": confianza,
        "resumen_para_dueno": str(resultado.get("resumen_para_dueno", "")).strip(),
        "puede_crear_cotizacion": bool(resultado.get("puede_crear_cotizacion", False)),
    }


def consultar_ollama(mensaje: str) -> Dict[str, Any]:
    resumen_catalogo = []
    for p in CATALOGO[:80]:
        resumen_catalogo.append({
            "codigo": p.get("codigo"),
            "marca": p.get("marca"),
            "hilo": p.get("hilo"),
            "color": p.get("color"),
            "stock": p.get("stock"),
            "precio": p.get("precio"),
        })

    instrucciones = f"""
Eres una asistente de ventas de Hilorama, una mercería en línea en México.
Tu sistema de ventas usa productos con: marca, hilo, color, codigo, stock, precio y volumetrico.

Reglas:
- Responde como WhatsApp: amable, claro y corto.
- Usa máximo 1 emoji.
- No inventes precios ni stock.
- Si falta producto, color, cantidad, entrega o dirección, pide solo el dato más importante.
- Si hay comprobante, reclamo o pago, debe revisarlo Jorge.
- Nunca digas que eres IA.
- Devuelve SOLO JSON válido.

Catálogo disponible para contexto parcial:
{json.dumps(resumen_catalogo, ensure_ascii=False)}

JSON obligatorio:
{{
  "intencion": "pedido | pregunta_precio | pregunta_stock | pregunta_envio | comprobante_pago | reclamo | saludo | otro",
  "productos": [],
  "datos_faltantes": [],
  "respuesta_cliente": "",
  "accion_sugerida": "responder | pedir_dato | crear_cotizacion_pendiente | avisar_a_jorge | no_responder",
  "requiere_humano": false,
  "razon_humano": "",
  "confianza": 80,
  "resumen_para_dueno": "",
  "puede_crear_cotizacion": false
}}
"""

    payload = {
        "model": MODELO,
        "messages": [
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": f"Mensaje del cliente: {mensaje}"},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    contenido = r.json()["message"]["content"]
    return normalizar_salida(extraer_json(contenido))


def analizar_mensaje_sin_memoria(mensaje: str) -> Dict[str, Any]:
    mensaje = aplicar_alias_texto(mensaje)
    aprendido = resultado_aprendido(mensaje)
    if aprendido:
        return aprendido
    especial = caso_especial(mensaje)
    if especial:
        return especial

    media_info = respuesta_media_info(mensaje)
    if media_info:
        return media_info

    texto_norm = normalizar(mensaje)
    es_stock = any(normalizar(p) in texto_norm for p in PALABRAS_STOCK)
    es_precio = any(normalizar(p) in texto_norm for p in PALABRAS_PRECIO)
    es_envio = any(normalizar(p) in texto_norm for p in PALABRAS_ENVIO)

    # Primero detecta pedidos claros por código y por nombre.
    items = detectar_items_por_codigo(mensaje)
    if not items:
        items = detectar_items_por_nombre(mensaje)

    # Si hay cantidad clara, es pedido.
    if items and any(i.get("cantidad", 0) > 0 for i in items):
        return respuesta_pedido(items)

    # Si pregunta precio o stock sin cantidad.
    items_sin_cantidad = detectar_producto_sin_cantidad(mensaje)

    if es_precio:
        return respuesta_precio(items_sin_cantidad)

    if es_stock:
        return respuesta_stock(items_sin_cantidad, mensaje)

    if es_envio:
        return {
            "intencion": "pregunta_envio",
            "productos": [],
            "datos_faltantes": ["codigo postal", "municipio", "estado"],
            "respuesta_cliente": "Claro 😊 ¿Me compartes tu código postal, municipio y estado para revisar el envío?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 85,
            "resumen_para_dueno": "Cliente preguntó por envío.",
            "puede_crear_cotizacion": False,
        }

    # Saludo simple.
    if any(p in texto_norm for p in ["hola", "buen dia", "buenas", "info", "informes"]):
        return {
            "intencion": "saludo",
            "productos": [],
            "datos_faltantes": ["producto"],
            "respuesta_cliente": "Hola 😊 ¿Qué producto o tono estás buscando?",
            "accion_sugerida": "pedir_dato",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 80,
            "resumen_para_dueno": "Cliente saludó o pidió informes.",
            "puede_crear_cotizacion": False,
        }

    # Mensajes raros/libres: deja que Ollama ayude.
    return consultar_ollama(mensaje)



def analizar_mensaje(mensaje: str, cliente_id: str = "demo") -> Dict[str, Any]:
    mensaje_original = mensaje
    mensaje = aplicar_alias_texto(mensaje)
    aprendido = resultado_aprendido(mensaje)
    if aprendido:
        return aprendido

    memoria = cargar_memoria()
    estado = obtener_memoria_cliente(memoria, cliente_id)

    media_info = respuesta_media_info(mensaje, estado)
    if media_info:
        actualizar_memoria_con_resultado(cliente_id, media_info)
        return media_info

    # Pedido por códigos después de ver catálogo, ejemplo:
    # "Deseo 2 del #19, 4 #466, 2#429, 2#26".
    items_codigo_contexto = detectar_items_por_codigo_contextual(mensaje, estado)
    if items_codigo_contexto and any(i.get("cantidad", 0) > 0 for i in items_codigo_contexto):
        resultado = respuesta_pedido(items_codigo_contexto)
        actualizar_memoria_con_resultado(cliente_id, resultado)
        return resultado

    items_messy, duda_messy = detectar_items_messy_contexto(mensaje, estado)
    if items_messy and duda_messy:
        resultado = respuesta_aclaracion(mensaje_original, motivo="Pedido con números ambiguos.", items_parciales=items_messy, dudas=duda_messy)
        actualizar_memoria_con_resultado(cliente_id, resultado)
        return resultado
    if items_messy and any(i.get("cantidad", 0) > 0 for i in items_messy):
        resultado = respuesta_pedido(items_messy)
        actualizar_memoria_con_resultado(cliente_id, resultado)
        return resultado

    desde_memoria = procesar_respuesta_con_memoria(mensaje, cliente_id, memoria, estado)
    if desde_memoria:
        actualizar_memoria_con_resultado(cliente_id, desde_memoria)
        return desde_memoria

    resultado = analizar_mensaje_sin_memoria(mensaje)
    actualizar_memoria_con_resultado(cliente_id, resultado)
    return resultado


def imprimir_catalogo_resumen():
    print(f"Catálogo cargado: {len(CATALOGO)} productos")
    if CATALOGO:
        origen = CATALOGO[0].get("origen_db", "")
        if origen:
            print(f"Origen: {origen}")
        marcas = sorted({p.get("marca", "") for p in CATALOGO if p.get("marca")})[:15]
        print("Marcas detectadas:", ", ".join(marcas) if marcas else "sin marcas")
    else:
        print("No encontré base de datos. Aun así funciona, pero no puede revisar stock/precios reales.")

    print(f"Medios detectados: {len(MEDIA_INDEX)} archivos")
    if MEDIA_INDEX:
        tipos = {}
        for m in MEDIA_INDEX:
            tipos[m.get("tipo", "archivo")] = tipos.get(m.get("tipo", "archivo"), 0) + 1
        print("Tipos de medios:", ", ".join(f"{k}: {v}" for k, v in sorted(tipos.items())))



def abrir_archivos_sugeridos(archivos: List[Dict[str, Any]]) -> None:
    """
    En consola no se puede "mostrar" una imagen dentro de PowerShell.
    Esta función abre el archivo con el visor de Windows para probar que sí encontró la imagen.
    Más adelante WhatsApp usará esta misma ruta para enviarla.
    """
    if not archivos:
        return

    print("\nARCHIVOS SUGERIDOS PARA ENVIAR:")
    for i, archivo in enumerate(archivos, start=1):
        print(f"{i}. {archivo.get('relativa') or archivo.get('ruta')}")

    respuesta = input("\n¿Abrir archivo(s) ahora en Windows? (s/n): ").strip().lower()
    if respuesta not in {"s", "si", "sí", "y", "yes"}:
        return

    for archivo in archivos:
        ruta = archivo.get("ruta") or archivo.get("path")
        if not ruta:
            continue
        try:
            if os.name == "nt":
                os.startfile(ruta)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", ruta])
        except Exception as e:
            print(f"No pude abrir {ruta}: {e}")



# ============================================================
# OVERRIDES v13 - PARSER HUMANO + CORRECCIONES DE CATÁLOGO
# Estas funciones se declaran al final para reemplazar la lógica anterior
# sin tocar el resto del programa.
# ============================================================

# Acciones extra que puede sugerir la IA sin inventar datos.
try:
    ACCIONES_VALIDAS.add("investigar_internet")
except Exception:
    pass


def producto_canonico(texto: Any) -> str:  # override v13
    """Normaliza productos con faltas comunes y formas humanas."""
    t = normalizar(texto)
    t = t.replace("konfy", "komfy").replace("comfi", "komfy").replace("comfy", "komfy").replace("komfi", "komfy")
    t = t.replace("veluto", "velluto").replace("belluto", "velluto").replace("velutto", "velluto")
    t = re.sub(r"\s+", " ", t).strip()
    if re.search(r"\bkomfy\s*mini\b", t) or "mini komfy" in t:
        return "komfy mini"
    if re.search(r"\bkomfy\b", t):
        return "komfy"
    if re.search(r"\bvelluto\b", t):
        return "velluto"
    return t


def etiqueta_producto(producto: Any) -> str:  # override v13
    p = producto_canonico(producto)
    if p == "komfy mini":
        return "Komfy mini"
    if p == "komfy":
        return "Komfy"
    if p == "velluto":
        return "Velluto"
    return str(producto or "").strip().title()


def alias_producto_en_texto_v13(mensaje: str) -> Tuple[str, str]:
    """Regresa (producto_canonico, etiqueta) si el texto menciona un producto, incluso con error."""
    t = producto_canonico(mensaje)
    # Prioridad a Komfy mini antes que Komfy.
    if "komfy mini" in t:
        return "komfy mini", "Komfy mini"
    if re.search(r"\bkomfy\b", t):
        return "komfy", "Komfy"
    if re.search(r"\bvelluto\b", t):
        return "velluto", "Velluto"
    # Revisión extra sin convertir todo el texto.
    n = normalizar(mensaje)
    for raw in ["komfi mini", "comfi mini", "comfy mini", "konfy mini"]:
        if raw in n:
            return "komfy mini", "Komfy mini"
    for raw in ["komfi", "comfi", "comfy", "konfy"]:
        if re.search(r"\b" + re.escape(raw) + r"\b", n):
            return "komfy", "Komfy"
    for raw in ["veluto", "belluto", "velutto"]:
        if re.search(r"\b" + re.escape(raw) + r"\b", n):
            return "velluto", "Velluto"
    return "", ""


def detectar_catalogo_general(mensaje: str) -> bool:  # override v13
    t = normalizar(mensaje)
    frases = [
        "catalogo general", "catalogo completo", "catalogo de todo", "todo el catalogo",
        "todo tu catalogo", "catalogo de la tienda", "todo lo que vendes", "todo lo que manejas",
        "todo lo que tienes", "todos los productos", "lo que vendes", "lo que manejas",
        "velluto como lo demas", "velluto y lo demas", "como lo demas", "lo demas",
        "donde tienes todo", "todo lo que venden", "completo", "el completo",
    ]
    return any(f in t for f in frases)


def mensaje_es_correccion(mensaje: str) -> bool:
    t = normalizar(mensaje)
    frases = [
        "no", "no ese", "no es", "no era", "no osea", "no o sea", "me refiero",
        "esas son imagenes", "son imagenes", "no son catalogo", "no el catalogo",
        "no esta funcionando", "eso no", "asi no", "mal", "no me entendiste",
    ]
    return any(f in t for f in frases)


def mensaje_pide_catalogo(mensaje: str) -> bool:
    t = normalizar(mensaje)
    palabras = [
        "catalogo", "catalog", "catalo", "catalogos", "muestrario", "carta", "carta de colores",
        "gama", "gama de colores", "colores", "tonos", "completo", "todo lo que vendes",
        "todo lo que manejas", "todo lo que tienes", "lo que vendes", "lo demas",
    ]
    return any(p in t for p in palabras)


def mensaje_pide_foto_o_media(mensaje: str) -> bool:
    t = normalizar(mensaje)
    palabras = [
        "manda", "mandas", "mandame", "mandamelo", "enviar", "envia", "pasame", "pasar",
        "muestra", "muestras", "muestrame", "enseña", "ensena", "ver", "foto", "imagen",
        "tambien", "también", "ahora", "el de", "y de", "o ",
    ]
    return any(p in t for p in palabras)


def respuesta_catalogo_formal_no_encontrado(producto: str = "", etiqueta: str = "") -> Dict[str, Any]:
    etiqueta = etiqueta or etiqueta_producto(producto) if producto else "esa línea"
    return {
        "intencion": "pedir_catalogo",
        "productos": [],
        "datos_faltantes": ["catálogo formal"],
        "respuesta_cliente": f"Perdón, esas eran fotos sueltas. Catálogo formal de {etiqueta} no lo tengo cargado como archivo único todavía 😊 Te puedo compartir las fotos por tono o, si prefieres, lo reviso y te lo mando.",
        "accion_sugerida": "avisar_a_jorge",
        "requiere_humano": True,
        "razon_humano": f"Cliente pidió catálogo formal de {etiqueta}, pero no hay archivo único detectado.",
        "confianza": 88,
        "resumen_para_dueno": f"Hace falta cargar catálogo formal de {etiqueta} o confirmar qué archivo mandar.",
        "puede_crear_cotizacion": False,
        "archivos_sugeridos": [],
    }


def respuesta_catalogo_estricto_producto(producto: str, etiqueta: str = "") -> Dict[str, Any]:
    producto_norm = producto_canonico(producto)
    etiqueta = etiqueta or etiqueta_producto(producto_norm)
    medios_catalogo = [m for m in MEDIA_INDEX if m.get("tipo") == "catalogo" and media_producto_coincide(m, producto_norm)][:5]
    if medios_catalogo:
        return {
            "intencion": "pedir_catalogo",
            "productos": [],
            "datos_faltantes": [],
            "respuesta_cliente": f"Claro 😊 Te comparto el catálogo/colores de {etiqueta}.",
            "accion_sugerida": "enviar_catalogo",
            "requiere_humano": False,
            "razon_humano": "",
            "confianza": 95,
            "resumen_para_dueno": f"Cliente pidió catálogo formal de {etiqueta}. Archivos sugeridos: {', '.join(m['relativa'] for m in medios_catalogo)}",
            "puede_crear_cotizacion": False,
            "archivos_sugeridos": medios_catalogo,
        }
    return respuesta_catalogo_formal_no_encontrado(producto_norm, etiqueta)


def respuesta_catalogo(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:  # override v13
    """Catálogo con razonamiento contextual: general vs categoría vs fotos sueltas."""
    t = normalizar(mensaje)
    producto, etiqueta = alias_producto_en_texto_v13(mensaje)

    # Si el cliente corrige: "no, el completo", "me refiero a todo lo que vendes".
    if detectar_catalogo_general(mensaje):
        return respuesta_catalogo_general()

    # Si no menciona producto y pide "el catálogo" de forma genérica, no asumimos Velluto.
    # Mejor preguntar o mandar el general si existe.
    if not producto:
        if estado and mensaje_es_correccion(mensaje) and estado.get("ultimo_media_producto"):
            # Si el último producto fue Komfy mini y ahora insiste en catálogo, busca catálogo formal de ese producto.
            ultimo = producto_canonico(estado.get("ultimo_media_producto"))
            if ultimo and "catalogo" in t:
                return respuesta_catalogo_estricto_producto(ultimo, etiqueta_producto(ultimo))
        return respuesta_catalogo_general()

    # Si usó la palabra catálogo/muestrario/carta, no le demos fotos sueltas como si fueran catálogo.
    if any(p in t for p in ["catalogo", "catalog", "catalo", "muestrario", "carta"]):
        return respuesta_catalogo_estricto_producto(producto, etiqueta)

    # Si dijo gama/tonos/colores sí puede mandar muestrario o fotos de tonos.
    return respuesta_catalogo_o_medios_producto(producto, etiqueta)


def detectar_solicitud_media_producto(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:  # override v13
    """Entiende seguimientos: 'y de komfi', 'o comfi mini?', 'mandame el de komfy'."""
    t = normalizar(mensaje)
    if not t:
        return None
    # No convertir compras o consultas de precio/stock en archivos.
    if any(b in t for b in ["quiero", "necesito", "deseo", "dame 2", "dame 3", "precio", "cuanto", "stock", "hay", "tienes", "comprar"]):
        return None
    producto, etiqueta = alias_producto_en_texto_v13(mensaje)
    if not producto:
        return None
    hay_contexto_media = bool(estado and estado.get("ultima_accion_media"))
    empieza_o_y = t.startswith("o ") or t.startswith("y ") or t.startswith("u ")
    if hay_contexto_media or empieza_o_y or mensaje_pide_foto_o_media(mensaje) or mensaje_pide_catalogo(mensaje):
        return producto, etiqueta
    return None


def respuesta_correccion_contextual(mensaje: str, estado: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cuando el cliente dice 'no, eso no', no debe inventar tonos; debe reparar la conversación."""
    if not estado:
        return None
    t = normalizar(mensaje)
    if not mensaje_es_correccion(mensaje):
        return None

    producto, etiqueta = alias_producto_en_texto_v13(mensaje)
    if not producto and estado.get("ultimo_media_producto"):
        producto = producto_canonico(estado.get("ultimo_media_producto"))
        etiqueta = etiqueta_producto(producto)

    # Quiere catálogo general/completo.
    if detectar_catalogo_general(mensaje):
        return respuesta_catalogo_general()

    # Insiste en catálogo de la categoría anterior.
    if "catalog" in t or "catalo" in t or "muestrario" in t:
        if producto:
            return respuesta_catalogo_estricto_producto(producto, etiqueta)
        return respuesta_catalogo_general()

    # Si no queda claro, pedir aclaración humana, no inventar un producto.
    return {
        "intencion": "pedir_aclaracion",
        "productos": [],
        "datos_faltantes": ["aclaración"],
        "respuesta_cliente": "Perdón 😊 Creo que no te entendí bien. ¿Te refieres al catálogo completo, al catálogo de una línea en especial o a una foto de tono?",
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 70,
        "resumen_para_dueno": f"Cliente corrigió la respuesta anterior. Mensaje: {mensaje}",
        "puede_crear_cotizacion": False,
    }


def respuesta_media_info(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:  # override v13
    # 0) Reparación de conversación: "no, ese no", "no el catálogo".
    correccion = respuesta_correccion_contextual(mensaje, estado)
    if correccion:
        return correccion

    # 1) Catálogo / gama / colores. Primero porque "catálogo" no es compra.
    if mensaje_pide_catalogo(mensaje) or detectar_intencion_catalogo(mensaje):
        return respuesta_catalogo(mensaje, estado)

    # 2) Seguimientos después de enviar catálogo/fotos: "y de komfi", "o komfy mini".
    seguimiento_media = detectar_solicitud_media_producto(mensaje, estado)
    if seguimiento_media:
        producto, etiqueta = seguimiento_media
        codigo = extraer_codigo_mencionado(mensaje)
        if codigo:
            return respuesta_foto_tono(f"foto {producto} tono {codigo}", estado)
        # Si dice explícitamente catálogo, no mandar fotos sueltas como catálogo.
        if any(p in normalizar(mensaje) for p in ["catalogo", "catalog", "catalo", "muestrario", "carta"]):
            return respuesta_catalogo_estricto_producto(producto, etiqueta)
        return respuesta_catalogo_o_medios_producto(producto, etiqueta)

    # 3) Foto de tono.
    if detectar_intencion_foto_tono(mensaje):
        return respuesta_foto_tono(mensaje, estado)

    # 4) Dudas técnicas de producto.
    if detectar_intencion_info_producto(mensaje):
        return respuesta_info_producto(mensaje, estado)
    return None


def respuesta_aclaracion_messy(mensaje: str, motivo: str = "") -> Dict[str, Any]:
    return {
        "intencion": "pedir_aclaracion",
        "productos": [],
        "datos_faltantes": ["cantidades y tonos"],
        "respuesta_cliente": "Claro 😊 Solo para no equivocarme, ¿me lo puedes mandar así? Ejemplo: 2 piezas tono 3, 4 piezas tono 55 y 20 piezas tono 216.",
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 65,
        "resumen_para_dueno": f"Mensaje con números ambiguos. {motivo} Texto: {mensaje}",
        "puede_crear_cotizacion": False,
    }


def mensaje_numerico_ambiguo(mensaje: str, estado: Optional[Dict[str, Any]]) -> bool:
    t = normalizar(mensaje)
    if not estado or not estado.get("ultimo_media_producto"):
        return False
    nums = re.findall(r"#?\d{1,6}", t)
    if len(nums) < 3:
        return False
    # Si hay formatos claros (#19 con cantidad antes), dejamos que los parsers existentes trabajen.
    if re.search(r"\b\d+\s*(?:del|de|x)?\s*#\s*\d+", t):
        return False
    # Mensajes tipo "de ese dame 2 del 3 4 y de 55 20" son ambiguos.
    return any(p in t for p in ["de ese", "del", "y de", "dame"])


_analizar_mensaje_base_v12 = analizar_mensaje

def analizar_mensaje(mensaje: str, cliente_id: str = "demo") -> Dict[str, Any]:  # override v13
    """Router v13: reglas seguras + contexto antes de dejar que Ollama adivine."""
    mensaje_original = mensaje
    mensaje = aplicar_alias_texto(mensaje)
    aprendido = resultado_aprendido(mensaje)
    if aprendido:
        return aprendido

    memoria = cargar_memoria()
    estado = obtener_memoria_cliente(memoria, cliente_id)

    # Si detectamos números en forma muy ambigua, preguntamos antes de inventar.
    if mensaje_numerico_ambiguo(mensaje, estado):
        resultado = respuesta_aclaracion_messy(mensaje_original, "Hay varios números y no queda claro cuáles son cantidades y cuáles tonos.")
        actualizar_memoria_con_resultado(cliente_id, resultado)
        return resultado

    # Prioridad a catálogo/fotos/correcciones humanas.
    media_info = respuesta_media_info(mensaje, estado)
    if media_info:
        actualizar_memoria_con_resultado(cliente_id, media_info)
        return media_info

    # Deja el resto a la lógica ya probada de v12.
    return _analizar_mensaje_base_v12(mensaje_original, cliente_id=cliente_id)


def main():
    print("IA local Hilorama basada en tu programa.")
    print("Modelo:", MODELO)
    imprimir_catalogo_resumen()
    print("Escribe mensaje de cliente. Para salir escribe: salir")
    print("Comandos: /memoria, /reset, /medios, /reindexar, /aprendizaje, /aprender_alias error=correcto, /aprender_respuesta frase=>respuesta")
    print("-" * 70)

    while True:
        mensaje = input("\nCliente: ").strip()
        if mensaje.lower() in {"salir", "exit", "cerrar"}:
            break
        if not mensaje:
            continue
        if mensaje.strip().lower() == "/reset":
            borrar_memoria_cliente("demo")
            print("Memoria borrada para este cliente de prueba.")
            continue
        if mensaje.strip().lower() == "/memoria":
            print(json.dumps(ver_memoria_cliente("demo"), ensure_ascii=False, indent=2))
            continue
        if mensaje.strip().lower() == "/medios":
            print(json.dumps(MEDIA_INDEX[:80], ensure_ascii=False, indent=2))
            if len(MEDIA_INDEX) > 80:
                print(f"... y {len(MEDIA_INDEX) - 80} más")
            continue
        if mensaje.strip().lower() == "/reindexar":
            total = reindexar_medios()
            print(f"Medios reindexados: {total} archivos. Si reemplazaste una imagen, ya se usará la nueva ruta/archivo.")
            continue
        if mensaje.strip().lower() == "/aprendizaje":
            print(json.dumps(cargar_aprendizaje(), ensure_ascii=False, indent=2))
            continue
        if mensaje.strip().lower().startswith("/aprender_alias "):
            raw = mensaje.split(" ", 1)[1]
            if "=" in raw:
                mal, bien = raw.split("=", 1)
                print(registrar_alias_texto(mal.strip(), bien.strip()))
            else:
                print("Formato: /aprender_alias error=correcto")
            continue
        if mensaje.strip().lower().startswith("/aprender_respuesta "):
            raw = mensaje.split(" ", 1)[1]
            if "=>" in raw:
                patron, respuesta = raw.split("=>", 1)
                print(registrar_respuesta_fija(patron.strip(), respuesta.strip()))
            else:
                print("Formato: /aprender_respuesta frase del cliente=>respuesta que debe mandar")
            continue
        try:
            resultado = analizar_mensaje(mensaje, cliente_id="demo")
            print("\nRESPUESTA PARA CLIENTE:")
            print(resultado.get("respuesta_cliente", ""))
            print("\nANÁLISIS COMPLETO:")
            print(json.dumps(resultado, ensure_ascii=False, indent=2))

            archivos = resultado.get("archivos_sugeridos") or []
            if archivos:
                abrir_archivos_sugeridos(archivos)
        except Exception as e:
            print("\nERROR:")
            print(e)
            print("Revisa que Ollama esté abierto y que qwen2.5:7b esté instalado.")


# =========================
# V14 - Intérprete humano de números y contexto
# =========================
# La meta no es corregir al cliente, sino normalizar internamente su forma de escribir.
# Solo se pide aclaración cuando el riesgo de equivocarse es alto o un tono/código no existe.

PALABRAS_CANTIDAD_V14 = {
    "pz", "pza", "pzas", "pieza", "piezas", "madeja", "madejas", "bola", "bolas",
    "estambre", "estambres", "unidad", "unidades"
}

PALABRAS_CODIGO_V14 = {
    "tono", "tonos", "codigo", "cod", "clave", "color", "numero", "num", "no", "#", "del", "de"
}


def _texto_para_numeros_v14(mensaje: str) -> str:
    t = normalizar(aplicar_alias_texto(mensaje))
    # Mantener marcadores útiles y convertir separadores raros a espacios.
    t = t.replace("@", " #")
    t = t.replace("→", " ").replace("->", " ").replace("=", " ")
    t = re.sub(r"([#])", r" \1 ", t)
    t = re.sub(r"[,;\n\r\t]+", " , ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _producto_contexto_v14(mensaje: str, estado: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    producto, etiqueta = alias_producto_en_texto_v13(mensaje)
    if producto:
        return producto_canonico(producto), etiqueta
    if estado:
        for k in ("ultimo_media_producto", "producto_contexto", "ultimo_producto_hilo"):
            v = estado.get(k)
            if v:
                p = producto_canonico(str(v))
                if p:
                    return p, etiqueta_producto(p)
        ultimo = estado.get("ultimo_producto")
        if isinstance(ultimo, dict):
            h = ultimo.get("hilo") or ultimo.get("marca")
            p = producto_canonico(str(h or ""))
            if p:
                return p, etiqueta_producto(p)
    return "", ""


def _producto_por_codigo_y_contexto_v14(codigo: str, estado: Optional[Dict[str, Any]], producto_ctx: str = "") -> Optional[Dict[str, Any]]:
    codigo = str(codigo).lstrip("0") or "0"
    opciones = catalogo_productos_por_codigo().get(codigo, [])
    if not opciones:
        return None
    if not producto_ctx:
        return seleccionar_producto_por_codigo_contexto(codigo, estado)
    mejores = []
    for p in opciones:
        score = 0
        texto = normalizar(f"{p.get('marca')} {p.get('hilo')} {p.get('color')}")
        if producto_ctx and producto_ctx in texto:
            score += 80
        if producto_ctx == "velluto" and normalizar(p.get("marca")) == "alize":
            score += 25
        if any(w in normalizar(p.get("color")) for w in ["surtido", "surtidos", "combo", "paquete"]):
            score -= 35
        if int(p.get("stock") or 0) > 0:
            score += 8
        if float(p.get("precio") or 0) > 0:
            score += 5
        mejores.append((score, p))
    mejores.sort(key=lambda x: x[0], reverse=True)
    return mejores[0][1]


def _agregar_item_v14(items: List[Dict[str, Any]], codigo: str, cantidad: int, estado: Optional[Dict[str, Any]], producto_ctx: str, errores: List[str]) -> bool:
    codigo = str(codigo).strip().lstrip("0") or "0"
    try:
        cantidad = int(cantidad)
    except Exception:
        return False
    if cantidad <= 0:
        return False
    prod = _producto_por_codigo_y_contexto_v14(codigo, estado, producto_ctx)
    if not prod:
        if codigo not in errores:
            errores.append(codigo)
        return False
    items.append(item_desde_producto(prod, cantidad))
    return True


def _dedupe_items_v14(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Si el mismo tono aparece varias veces, sumamos cantidades. Esto se parece más a cómo vende una persona.
    agrupados: Dict[str, Dict[str, Any]] = {}
    for it in items:
        codigo = str(it.get("codigo") or "")
        if not codigo:
            codigo = normalizar(it.get("descripcion") or str(len(agrupados)))
        if codigo not in agrupados:
            agrupados[codigo] = dict(it)
        else:
            nueva_cantidad = int(agrupados[codigo].get("cantidad") or 0) + int(it.get("cantidad") or 0)
            base = agrupados[codigo]
            prod = {
                "codigo": base.get("codigo"),
                "codigo_barras": base.get("codigo_barras"),
                "marca": base.get("marca"),
                "hilo": base.get("hilo"),
                "color": base.get("color"),
                "stock": base.get("stock"),
                "estado": base.get("estado"),
                "precio": base.get("precio"),
                "volumetrico": base.get("volumetrico"),
                "es_inventariable": base.get("es_inventariable", True),
            }
            agrupados[codigo] = item_desde_producto(prod, nueva_cantidad)
    return list(agrupados.values())


def detectar_items_humanos_contexto_v14(mensaje: str, estado: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """
    Parser humano para mensajes desordenados.

    Entiende, según contexto:
    - "2 del #19, 4 #466, 2#429, 2#26"      => cantidad + código
    - "#19 2, #466 4"                        => código + cantidad
    - "2 del 3 4"                             => 2 piezas de tono 3 y 2 piezas de tono 4
    - "y de 55 20"                            => 20 piezas del tono 55
    - "de ese dame 2 del 3 4 y de 55 20"      => mezcla de lo anterior

    Devuelve: items, codigos_no_encontrados, dudas.
    """
    t = _texto_para_numeros_v14(mensaje)
    if not re.search(r"\d", t):
        return [], [], []

    producto_ctx, _etiqueta = _producto_contexto_v14(mensaje, estado)
    # Si no hay producto explícito ni contexto de gama/foto/producto, no arriesgar códigos.
    if not producto_ctx:
        return [], [], []

    # No meter aquí CPs/envíos/comprobantes.
    if any(w in t for w in ["cp", "codigo postal", "direccion", "calle", "col", "colonia", "municipio", "envio", "enviar"]):
        if not any(w in t for w in ["dame", "quiero", "deseo", "necesito", "tono", "#", "del"]):
            return [], [], []

    items: List[Dict[str, Any]] = []
    errores: List[str] = []
    dudas: List[str] = []
    usados_spans: List[Tuple[int, int]] = []

    def span_usado(a: int, b: int) -> bool:
        return any(not (b <= x or a >= y) for x, y in usados_spans)

    def mark(a: int, b: int):
        usados_spans.append((a, b))

    # A) cantidad + marcador + uno o varios códigos: "2 del 3 4", "2 #19", "4 tono 466"
    patron_a = re.compile(r"\b(\d{1,4})\s*(?:pz|pza|pzas|pieza|piezas|madejas?)?\s*(?:de|del|tono|tonos|codigo|cod|#)\s*((?:#?\s*\d{1,6}\s*){1,8})")
    for m in patron_a.finditer(t):
        cantidad = int(m.group(1))
        bloque = m.group(2)
        codigos = re.findall(r"\d{1,6}", bloque)
        if codigos:
            for c in codigos:
                _agregar_item_v14(items, c, cantidad, estado, producto_ctx, errores)
            mark(m.start(), m.end())

    # B) código + x/cantidad: "#19 x2", "tono 19 2 pz"
    patron_b = re.compile(r"(?:#|tono|codigo|cod)\s*(\d{1,6})\s*(?:x|por|\*)?\s*(\d{1,4})\s*(?:pz|pza|pzas|pieza|piezas|madejas?)?\b")
    for m in patron_b.finditer(t):
        if span_usado(m.start(), m.end()):
            continue
        codigo = m.group(1)
        cantidad = int(m.group(2))
        _agregar_item_v14(items, codigo, cantidad, estado, producto_ctx, errores)
        mark(m.start(), m.end())

    # C) "y de 55 20" / "del 55 20": marcador + código + cantidad.
    # Esto cubre coloquialismos donde primero dicen el tono y luego la cantidad.
    patron_c = re.compile(r"(?:^|\b(?:y|tambien|también|otro|otra)?\s*)(?:de|del|tono|#)\s*(\d{1,6})\s+(\d{1,4})(?:\b|$)")
    for m in patron_c.finditer(t):
        if span_usado(m.start(), m.end()):
            continue
        codigo = m.group(1)
        cantidad = int(m.group(2))
        # Evita tomar "2 del 3" al revés: si antes hay cantidad inmediata, ya lo tomó A.
        previo = t[max(0, m.start()-5):m.start()].strip()
        if re.search(r"\d\s*$", previo):
            continue
        _agregar_item_v14(items, codigo, cantidad, estado, producto_ctx, errores)
        mark(m.start(), m.end())

    # D) líneas o segmentos de dos números sin palabras: elegir por catálogo y probabilidad.
    # Ejemplo real de WhatsApp: "19 2" o "2 19". Si uno coincide con tono y el otro parece cantidad.
    segmentos = [s.strip() for s in re.split(r"[,;\n]+", t) if s.strip()]
    for seg in segmentos:
        nums = re.findall(r"\b\d{1,6}\b", seg)
        if len(nums) != 2:
            continue
        # Si ya hay marcadores claros en el segmento, saltamos.
        if any(w in seg for w in ["del", "tono", "codigo", "cod", "#"]):
            continue
        a, b = nums
        prod_a = _producto_por_codigo_y_contexto_v14(a, estado, producto_ctx)
        prod_b = _producto_por_codigo_y_contexto_v14(b, estado, producto_ctx)
        if prod_a and not prod_b:
            _agregar_item_v14(items, a, int(b), estado, producto_ctx, errores)
        elif prod_b and not prod_a:
            _agregar_item_v14(items, b, int(a), estado, producto_ctx, errores)
        elif prod_a and prod_b:
            # Si ambos existen como tonos, por seguridad el menor suele ser cantidad si es 1-20.
            ia, ib = int(a), int(b)
            if ia <= 20 < ib:
                _agregar_item_v14(items, b, ia, estado, producto_ctx, errores)
            elif ib <= 20 < ia:
                _agregar_item_v14(items, a, ib, estado, producto_ctx, errores)
            else:
                dudas.append(f"no sé si {a} y {b} son cantidades o tonos")

    items = _dedupe_items_v14(items)

    # Dudas por números que quedan sueltos después de entender algo.
    if items:
        nums = re.findall(r"\b\d{1,6}\b", t)
        usados_num = []
        for it in items:
            usados_num.append(str(it.get("codigo") or ""))
            usados_num.append(str(int(it.get("cantidad") or 0)))
        sueltos = [n for n in nums if n not in usados_num and n not in errores]
        # Un suelto puede ser parte de una dirección o de otra frase, no molestamos salvo que parezca pedido.
        if sueltos and any(w in t for w in ["dame", "quiero", "deseo", "necesito", "del", "#", "tono"]):
            dudas.append("me quedaron números sin interpretar: " + ", ".join(sueltos[:6]))

    return items, errores, dudas


def respuesta_aclaracion_humana_v14(mensaje: str, items: Optional[List[Dict[str, Any]]] = None, codigos_no_encontrados: Optional[List[str]] = None, dudas: Optional[List[str]] = None) -> Dict[str, Any]:
    items = items or []
    codigos_no_encontrados = codigos_no_encontrados or []
    dudas = dudas or []

    if items and not dudas and not codigos_no_encontrados:
        return respuesta_pedido(items)

    entendido = resumen_items(items, para_cliente=True) if items else ""
    partes = []
    if entendido:
        partes.append(f"entendí {entendido}")
    if codigos_no_encontrados:
        partes.append("no me aparecen estos tonos/códigos: " + ", ".join(codigos_no_encontrados[:6]))
    if dudas:
        partes.append("me falta confirmar " + "; ".join(dudas[:3]))

    detalle = ". ".join(partes)
    if detalle:
        respuesta = f"Claro 😊 {detalle}. ¿Así lo dejamos o me confirmas esa parte?"
    else:
        respuesta = "Claro 😊 para no equivocarme, ¿me confirmas cuáles números son cantidades y cuáles son tonos?"

    return {
        "intencion": "pedir_aclaracion",
        "productos": items,
        "datos_faltantes": ["confirmación de pedido"],
        "respuesta_cliente": respuesta,
        "accion_sugerida": "pedir_dato",
        "requiere_humano": False,
        "razon_humano": "",
        "confianza": 68 if items else 55,
        "resumen_para_dueno": f"Mensaje humano/desordenado. Texto: {mensaje}",
        "puede_crear_cotizacion": False,
        "codigos_no_encontrados": codigos_no_encontrados,
        "dudas_interpretacion": dudas,
    }


_analizar_mensaje_base_v13 = analizar_mensaje


def analizar_mensaje(mensaje: str, cliente_id: str = "demo") -> Dict[str, Any]:  # override v14
    """
    Router v14:
    - Normaliza coloquialismos internamente.
    - Usa contexto para decidir si un número es tono/código o cantidad.
    - No corrige al cliente; solo pide confirmación cuando hay riesgo.
    """
    mensaje_original = mensaje
    mensaje_alias = aplicar_alias_texto(mensaje)

    aprendido = resultado_aprendido(mensaje_alias)
    if aprendido:
        return aprendido

    memoria = cargar_memoria()
    estado = obtener_memoria_cliente(memoria, cliente_id)

    # Primero: medios, catálogos y correcciones de conversación.
    media_info = respuesta_media_info(mensaje_alias, estado)
    if media_info:
        actualizar_memoria_con_resultado(cliente_id, media_info)
        return media_info

    # Segundo: parser humano de pedidos raros con contexto.
    items_humanos, codigos_error, dudas = detectar_items_humanos_contexto_v14(mensaje_alias, estado)
    if items_humanos or codigos_error:
        if items_humanos and not codigos_error and not dudas:
            resultado = respuesta_pedido(items_humanos)
        else:
            resultado = respuesta_aclaracion_humana_v14(mensaje_original, items_humanos, codigos_error, dudas)
        actualizar_memoria_con_resultado(cliente_id, resultado)
        return resultado

    # Tercero: lógica ya probada de v13.
    return _analizar_mensaje_base_v13(mensaje_original, cliente_id=cliente_id)


if __name__ == "__main__":
    main()
