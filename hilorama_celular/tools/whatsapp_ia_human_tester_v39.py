#!/usr/bin/env python3
"""
Tester conversacional humano V39 para WhatsApp IA Hilorama.

Este tester NO reemplaza al tester masivo V35. Lo complementa.
V35 prueba muchas preguntas/pedidos rápidos.
V39 prueba conversaciones más reales, raras y largas:
- mensajes cortados como WhatsApp
- faltas de ortografía
- cambios de producto a mitad de conversación
- preguntas de catálogo: qué más manejan, marcas, hilos, accesorios, ganchos/agujas
- pedidos mixtos con hilos + accesorios
- envío, pago, descuento, correcciones y dudas humanas

Uso recomendado:
  python tools/whatsapp_ia_human_tester_v39.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50
  python tools/whatsapp_ia_human_tester_v39.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 200 --sleep 0.2

IMPORTANTE:
- Usa tester_mode=true y dry_run=true.
- No debe guardar conversaciones reales.
- No debe crear notas reales.
- No debe crear decisiones pendientes reales.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FORBIDDEN_PUBLIC_PHRASES = [
    "confianza baja", "confianza media", "parser", "no ubiqué", "no ubique",
    "revisar códigos", "revisar codigos", "código aparece en varios hilos",
    "codigo aparece en varios hilos", "advertencias", "errores", "interno",
    "apartado", "apartar", "aparto", "aparta", "le aparto",
    # V39: señales de productos inventados por abrir conversación o corregir contexto.
    "Pregunta x1", "Pedio Kotton Milk x1", "Velluto Perdon Todo Eso Seria x1",
]

DEFAULT_PRODUCTS = [
    {"marca": "ALIZE", "hilo": "VELLUTO", "codigo": "55", "color": "BLANCO", "stock": 1, "precio_venta": 59.99},
    {"marca": "ALIZE", "hilo": "VELLUTO", "codigo": "60", "color": "NEGRO", "stock": 1, "precio_venta": 59.99},
    {"marca": "ALIZE", "hilo": "VELLUTO", "codigo": "429", "color": "CAMEL", "stock": 1, "precio_venta": 59.99},
    {"marca": "KARINA", "hilo": "KOMFY MINI", "codigo": "01", "color": "BLANCO", "stock": 1, "precio_venta": 52.0},
    {"marca": "KARINA", "hilo": "KOMFY MINI", "codigo": "99", "color": "NEGRO", "stock": 1, "precio_venta": 52.0},
    {"marca": "HILORAMA", "hilo": "GANCHO ALUMINIO", "codigo": "4", "color": "4 MM", "stock": 1, "precio_venta": 0},
    {"marca": "HILORAMA", "hilo": "OJO SEGURIDAD", "codigo": "8", "color": "8 MM", "stock": 1, "precio_venta": 0},
    {"marca": "HILORAMA", "hilo": "RELLENO", "codigo": "500", "color": "MEDIO KILO", "stock": 1, "precio_venta": 0},
    {"marca": "HILORAMA", "hilo": "GANCHO ALUMINIO", "codigo": "5", "color": "5 MM", "stock": 1, "precio_venta": 0},
]

YARN_HINTS = ["HILO", "ESTAMBRE", "VELLUTO", "KOMFY", "KURUMI", "TRAPILLO", "KRAFT", "ALIZE", "KARINA"]
ACCESSORY_HINTS = [
    "GANCHO", "AGUJA", "CROCHET", "GANCHILLO", "OJO", "SEGURIDAD",
    "MARCADOR", "TIJERA", "RELLENO", "SILICON", "FIELTRO", "ALUMINIO",
    "ESTUCHE", "CINTA", "TELA", "CIERRE", "BOTON", "BOTÓN",
]

TYPO_MAP = {
    "Velluto": ["Velluto", "Veluto", "Belluto", "Beyuto", "Vellluto"],
    "Komfy Mini": ["Komfy Mini", "Konfy Mini", "Comfy Mini", "Komfi Mini", "Confi Mini"],
    "pedido": ["pedido", "pwdido", "pedidio", "pedio"],
    "cotizar": ["cotizar", "cotisar", "cotiizar", "cotiiza"],
    "buenas tardes": ["buenas tardes", "buenas trades", "buenas tarde", "buenaz tardes"],
}

@dataclass
class Turn:
    text: str
    marca: str = ""
    hilo: str = ""

@dataclass
class Case:
    case_id: str
    category: str
    turns: List[Turn]
    expect: Dict[str, Any] = field(default_factory=dict)


def norm(s: str) -> str:
    s = (s or "").lower()
    repl = str.maketrans("áéíóúüñ", "aeiouun")
    return s.translate(repl)


def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()[:70]


def get_json(url: str, pin: str = "", timeout: float = 30.0) -> Any:
    req = urllib.request.Request(url, method="GET")
    if pin:
        req.add_header("X-Mobile-Pin", pin)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def post_json(url: str, payload: Dict[str, Any], pin: str, timeout: float = 60.0) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if pin:
        req.add_header("X-Mobile-Pin", pin)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def safe_str(v: Any) -> str:
    return str(v or "").strip()


def product_text(p: Dict[str, Any]) -> str:
    return " ".join(safe_str(p.get(k)) for k in ("marca", "hilo", "codigo", "color"))


def load_inventory(base_url: str, pin: str, limit: int, timeout: float) -> Dict[str, Any]:
    """Carga un resumen del almacén desde el sitio real. Si falla, usa respaldo mínimo."""
    base = base_url.rstrip("/")
    products: List[Dict[str, Any]] = []
    marcas: List[str] = []
    hilos: List[str] = []
    errors: List[str] = []
    try:
        marcas = get_json(base + "/api/catalogo/marcas", pin=pin, timeout=timeout) or []
    except Exception as exc:
        errors.append(f"No pude leer marcas: {exc}")
    try:
        hilos = get_json(base + "/api/catalogo/hilos", pin=pin, timeout=timeout) or []
    except Exception as exc:
        errors.append(f"No pude leer hilos: {exc}")
    try:
        qs = urllib.parse.urlencode({"limit": min(max(limit, 50), 300)})
        products = get_json(base + "/api/productos?" + qs, pin=pin, timeout=timeout) or []
    except Exception as exc:
        errors.append(f"No pude leer productos: {exc}")

    if not products:
        products = list(DEFAULT_PRODUCTS)
    if not marcas:
        marcas = sorted({safe_str(p.get("marca")) for p in products if safe_str(p.get("marca"))})
    if not hilos:
        hilos = sorted({safe_str(p.get("hilo")) for p in products if safe_str(p.get("hilo"))})

    # Normalizar formato básico
    clean_products: List[Dict[str, Any]] = []
    for p in products:
        pp = dict(p)
        pp["marca"] = safe_str(pp.get("marca"))
        pp["hilo"] = safe_str(pp.get("hilo"))
        pp["codigo"] = safe_str(pp.get("codigo"))
        pp["color"] = safe_str(pp.get("color"))
        try:
            pp["stock"] = int(float(pp.get("stock") or 0))
        except Exception:
            pp["stock"] = 0
        clean_products.append(pp)

    available = [p for p in clean_products if int(p.get("stock") or 0) > 0]
    yarns = [p for p in clean_products if any(h in norm(product_text(p)).upper() for h in YARN_HINTS)]
    accessories = [p for p in clean_products if any(h in norm(product_text(p)).upper() for h in ACCESSORY_HINTS)]
    return {
        "products": clean_products,
        "available": available or clean_products,
        "marcas": [safe_str(x) for x in marcas if safe_str(x)],
        "hilos": [safe_str(x) for x in hilos if safe_str(x)],
        "yarns": yarns or clean_products,
        "accessories": accessories,
        "errors": errors,
    }


def choose(rng: random.Random, seq: List[Any], fallback: Any = None) -> Any:
    return rng.choice(seq) if seq else fallback


def maybe_typo(rng: random.Random, phrase: str) -> str:
    out = phrase
    for good, variants in TYPO_MAP.items():
        if good.lower() in out.lower() and rng.random() < 0.55:
            out = re.sub(re.escape(good), rng.choice(variants), out, flags=re.I)
    return out


def contains_any(text: str, parts: List[str]) -> bool:
    tn = norm(text)
    return any(norm(str(p)) in tn for p in parts if str(p).strip())


def generate_cases(limit: int, inventory: Dict[str, Any], seed: int = 3636) -> List[Case]:
    rng = random.Random(seed)
    cases: List[Case] = []
    available = inventory.get("available") or DEFAULT_PRODUCTS
    products = inventory.get("products") or DEFAULT_PRODUCTS
    accessories = inventory.get("accessories") or []
    marcas = inventory.get("marcas") or sorted({p["marca"] for p in DEFAULT_PRODUCTS})
    hilos = inventory.get("hilos") or sorted({p["hilo"] for p in DEFAULT_PRODUCTS})

    # Palabras esperadas para preguntas de catálogo, basadas en lo que existe en almacén.
    catalog_terms = []
    for x in list(marcas)[:8] + list(hilos)[:12]:
        if x:
            catalog_terms.append(x)
    # Reforzar términos que el negocio suele manejar.
    catalog_terms += ["Velluto", "Komfy", "Kurumi", "Alize", "Karina", "gancho", "aguja", "ojos", "seguridad"]

    def add(category: str, turns: List[str], expect: Optional[Dict[str, Any]] = None):
        idx = len(cases) + 1
        t_objs = [Turn(t) for t in turns]
        cases.append(Case(f"{idx:05d}_{category}_{slug(t_objs[-1].text)}", category, t_objs, expect or {}))

    # V39: casos complejos externos listos para copiar/pegar y estresar la IA.
    # Están en tools/casos_tester_v39_complejos_hilorama.json. Si no existe el archivo, el tester sigue con los casos internos.
    extra_cases_path = Path(__file__).with_name("casos_tester_v39_complejos_hilorama.json")
    if extra_cases_path.exists():
        try:
            extra_data = json.loads(extra_cases_path.read_text(encoding="utf-8"))
            for obj in extra_data:
                turns = obj.get("turns") or []
                if turns:
                    add(obj.get("category") or "v39_extra", turns, obj.get("expect") or {})
        except Exception as exc:
            print(f"Aviso: no pude cargar casos V39 externos: {exc}", file=sys.stderr)

    # Conversaciones humanas fijas: estas valen más que muchas preguntas simples.
    add("humano_catalogo_general", [
        "Hola buenas tardes",
        "disculpa que más manejan aparte de velluto?",
        "también manejan agujas o ganchos?",
    ], {
        "scope": "all",
        "must_contain_any": catalog_terms,
        "must_not_only_ask_hilo_codigo": True,
    })

    add("humano_marcas_hilos", [
        "Hola",
        "que marcas de hilos maneja?",
        "y de karina que tiene?",
    ], {
        "scope": "all",
        "must_contain_any": ["karina", "komfy", "kurumi", "marca", "hilo", "manej"],
        "must_not_only_ask_hilo_codigo": True,
    })

    add("humano_amigurumi_recomendacion", [
        "holaa",
        "quiero hacer amigurumis pero no se que hilo me conviene",
        "algo suave y que no salga tan caro",
    ], {
        "scope": "all",
        "must_contain_any": ["amigurumi", "kurumi", "komfy", "hilo", "opci", "recom"],
        "must_not_contain_any": ["no sé", "no se"],
    })

    add("humano_pedido_envio_descuento", [
        "buenas trades",
        "quiero cotisar velluto",
        "5 del 55 y 10 del 60",
        "y cuanto sale envio al 97000",
        "si llevo 15 me mejoras precio?",
    ], {
        "scope": "all",
        "expected_items": [{"codigo": "55", "cantidad": 5}, {"codigo": "60", "cantidad": 10}],
        "must_contain_any": ["97000", "envio", "envío", "revis", "confirm"],
        "must_not_contain_any": ["se lo dejo", "descuento aprobado", "$55"],
    })

    add("humano_lista_rara_confirmacion", [
        "buenas tardes le paso listita",
        "60\n310\n107\n329\n466\n26\n87",
        "perdon todo eso seria de belluto",
        "y agregue 2 del 429",
    ], {
        "scope": "all",
        "expected_items_any": ["60", "310", "429"],
        "must_contain_any": ["velluto", "belluto", "cotiz", "agrego"],
    })

    add("humano_correccion_larga", [
        "me puede poner 6 del 14 y 3 del 06 de komfi mini",
        "perdon mejor quite el 14",
        "del 06 dejeme solo 2",
        "y agregue negro si tiene",
    ], {
        "scope": "all",
        "must_contain_any": ["komfy", "06", "negro", "actualiz", "quito", "corrijo", "cotiz"],
    })

    add("humano_pago_comprobante", [
        "ya quedo el pago",
        "ahorita le mando comprobante",
        "me confirma si le llego?",
    ], {
        "scope": "all",
        "must_contain_any": ["comprobante", "revis", "confirm"],
        "must_not_contain_any": ["pagado", "marcado como pagado"],
    })

    add("humano_producto_no_manejado", [
        "manejas estambre la abuelita?",
        "si no tiene cual me recomienda parecido?",
    ], {
        "scope": "all",
        "must_contain_any": ["por el momento", "no", "parecid", "opci", "kurumi", "komfy"],
    })

    if accessories:
        acc = choose(rng, accessories)
        acc_name = " ".join([safe_str(acc.get("hilo")), safe_str(acc.get("color"))]).strip() or product_text(acc)
        add("humano_accesorio_real_almacen", [
            "hola una pregunta",
            f"maneja {acc_name}?",
            "y me lo puede agregar con mis hilos?",
        ], {
            "scope": "all",
            "must_contain_any": [acc.get("hilo", ""), acc.get("color", ""), "tenemos", "manej", "agrego", "cotiz", "revis"],
            "must_not_only_ask_hilo_codigo": True,
        })
    else:
        add("humano_accesorios_generico", [
            "hola una pregunta",
            "maneja agujas o ganchos para crochet?",
            "y ojos de seguridad?",
        ], {
            "scope": "all",
            "must_contain_any": ["aguja", "gancho", "crochet", "ojo", "seguridad", "manej", "tenemos", "revis"],
            "must_not_only_ask_hilo_codigo": True,
        })

    # Casos generados dinámicamente con inventario real.
    human_openers = [
        "Hola", "Holaa", "Buenas tardes", "buenas trades", "Disculpa", "Oye una pregunta", "Buen día",
    ]
    ask_catalog = [
        "qué más manejan aparte de velluto?",
        "manejan otras marcas de hilos?",
        "qué hilos tienes?",
        "tienen agujas o ganchos?",
        "manejan accesorios para tejer?",
        "que me recomiendas para amigurumi?",
    ]
    pedido_words = ["me puede poner", "me cotiza", "quiero", "agregame", "me puede agregar"]

    while len(cases) < limit:
        kind = rng.choices(
            ["catalogo", "producto", "conversacion_pedido", "accesorio", "recomendacion", "mixto"],
            weights=[18, 22, 28, 12, 10, 10],
            k=1,
        )[0]
        p = choose(rng, products, DEFAULT_PRODUCTS[0])
        p2 = choose(rng, products, DEFAULT_PRODUCTS[1])
        marca = safe_str(p.get("marca")) or "ALIZE"
        hilo = safe_str(p.get("hilo")) or "VELLUTO"
        codigo = safe_str(p.get("codigo")) or "55"
        color = safe_str(p.get("color")) or "BLANCO"
        qty = rng.randint(1, 8)

        if kind == "catalogo":
            q = rng.choice(ask_catalog)
            add("generado_humano_catalogo", [
                rng.choice(human_openers),
                maybe_typo(rng, q),
            ], {
                "scope": "all",
                "must_contain_any": catalog_terms,
                "must_not_only_ask_hilo_codigo": True,
            })
        elif kind == "producto":
            query = rng.choice([
                f"tiene {hilo} {color}?",
                f"maneja {marca}?",
                f"tiene el codigo {codigo} de {hilo}?",
                f"cuanto cuesta {hilo}?",
            ])
            add("generado_humano_producto", [
                rng.choice(human_openers),
                maybe_typo(rng, query),
            ], {
                "scope": "all",
                "must_contain_any": [hilo, color, codigo, marca, "manej", "tenemos", "revis", "precio"],
            })
        elif kind == "conversacion_pedido":
            hilo_alias = hilo
            if "VELLUTO" in norm(hilo).upper():
                hilo_alias = rng.choice(TYPO_MAP["Velluto"])
            if "KOMFY" in norm(hilo).upper():
                hilo_alias = rng.choice(TYPO_MAP["Komfy Mini"])
            p2_codigo = safe_str(p2.get("codigo")) or "60"
            turns = [
                rng.choice(human_openers),
                maybe_typo(rng, f"quiero hacer un pedido de {hilo_alias}"),
                f"{qty} del {codigo}",
            ]
            if rng.random() < 0.55:
                turns.append(f"y {rng.randint(1, 5)} del {p2_codigo}")
            if rng.random() < 0.35:
                turns.append("cuanto seria con envio al 97000?")
            add("generado_humano_pedido_seguimiento", turns, {
                "scope": "all",
                "expected_items_any": [codigo],
                "must_contain_any": ["cotiz", "agrego", "pedido", hilo.split()[0], codigo],
            })
        elif kind == "accesorio":
            acc = choose(rng, accessories, None)
            if acc:
                acc_text = " ".join([safe_str(acc.get("hilo")), safe_str(acc.get("color"))]).strip()
                expected = [acc.get("hilo", ""), acc.get("color", ""), "tenemos", "manej", "revis", "agrego"]
            else:
                acc_text = rng.choice(["gancho de aluminio", "aguja de crochet", "ojos de seguridad", "marcadores de punto"])
                expected = ["gancho", "aguja", "crochet", "ojos", "seguridad", "manej", "revis"]
            add("generado_humano_accesorio", [
                rng.choice(human_openers),
                f"maneja {acc_text}?",
                "me puede decir precio o si hay?",
            ], {
                "scope": "all",
                "must_contain_any": expected,
                "must_not_only_ask_hilo_codigo": True,
            })
        elif kind == "recomendacion":
            add("generado_humano_recomendacion", [
                rng.choice(human_openers),
                rng.choice([
                    "busco hilo para bebé, algo suave",
                    "quiero hacer una cobijita, que hilo me recomienda?",
                    "quiero hacer muñecos amigurumi, que me recomienda?",
                    "ocupo algo tipo chenille pero barato",
                ]),
            ], {
                "scope": "all",
                "must_contain_any": ["recom", "opci", "hilo", "komfy", "kurumi", "velluto", "suave", "beb"],
                "must_not_only_ask_hilo_codigo": True,
            })
        else:  # mixto
            add("generado_humano_mixto", [
                rng.choice(human_openers),
                f"me puedes cotizar {qty} del {codigo} de {hilo}",
                rng.choice(["tambien maneja agujas?", "y que otras marcas tiene?", "tambien tiene ojos de seguridad?", "me enseña la gama?"]),
                rng.choice(["mejora precio si llevo más?", "y envio al cp 78174?", "si ya pago como le hago?", "me puede quitar uno?"]),
            ], {
                "scope": "all",
                "must_contain_any": [codigo, hilo.split()[0], "cotiz", "agrego", "revis", "envio", "envío", "comprobante", "marca", "aguja", "ojo"],
                "must_not_contain_any": ["descuento aprobado", "se lo dejo"],
            })

    return cases[:limit]


def collect_items(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if isinstance(resp.get("pedidos"), list):
        items.extend(x for x in resp["pedidos"] if isinstance(x, dict))
    parser = resp.get("parser") or {}
    if isinstance(parser, dict):
        for key in ("pedidos", "items_lista_v27", "items_lista_v17"):
            val = parser.get(key) or []
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
    v30 = resp.get("v30") or {}
    if isinstance(v30, dict):
        resol = v30.get("resolucion") or {}
        if isinstance(resol.get("pedidos"), list):
            items.extend(x for x in resol["pedidos"] if isinstance(x, dict))
    return items


def item_matches(items: List[Dict[str, Any]], codigo: str, cantidad: Optional[int] = None) -> bool:
    codigo_norm = str(codigo).lstrip("0") or str(codigo)
    for it in items:
        code = str(it.get("codigo") or it.get("codigo_raw") or "")
        code_norm = code.lstrip("0") or code
        qty_raw = it.get("cantidad")
        try:
            qty = int(float(qty_raw)) if qty_raw is not None and str(qty_raw) else None
        except Exception:
            qty = None
        if code_norm == codigo_norm and (cantidad is None or qty == int(cantidad)):
            return True
    return False


def response_text(resp: Dict[str, Any]) -> str:
    return safe_str(resp.get("respuesta_sugerida") or resp.get("respuesta_diferida") or resp.get("respuesta") or "")


def grade_case(case: Case, responses: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    final = responses[-1] if responses else {}
    scope = case.expect.get("scope", "final")
    texts = [response_text(r) for r in responses]
    text = "\n".join(texts) if scope == "all" else (texts[-1] if texts else "")
    tn = norm(text)

    if not final.get("ok"):
        reasons.append("respuesta final ok=false")
    if not final.get("tester_mode"):
        reasons.append("NO está en tester_mode; se debe desplegar V30+ para no ensuciar datos")

    for bad in FORBIDDEN_PUBLIC_PHRASES:
        if norm(bad) in tn:
            reasons.append(f"respuesta contiene frase interna/prohibida: {bad}")

    if len(response_text(final).strip()) < 8:
        reasons.append("respuesta final demasiado corta o vacía")

    must_any = case.expect.get("must_contain_any") or []
    flat = []
    for phrase in must_any:
        if isinstance(phrase, (list, tuple, set)):
            flat.extend(str(x) for x in phrase)
        else:
            flat.append(str(phrase))
    flat = [x for x in flat if x and str(x).strip()]
    if flat and not contains_any(text, flat):
        reasons.append("no contiene ninguno de los esperados: " + ", ".join(flat[:12]))

    # V39: algunos casos deben contener varias piezas a la vez (ej. ojo + seguridad),
    # no solo una palabra suelta que permita falsos positivos.
    for phrase in case.expect.get("must_contain_all") or []:
        if norm(str(phrase)) not in tn:
            reasons.append(f"no contiene requerido: {phrase}")

    for phrase in case.expect.get("must_not_contain_any") or []:
        if norm(str(phrase)) in tn:
            reasons.append(f"contiene algo que no debía: {phrase}")

    if case.expect.get("must_not_only_ask_hilo_codigo"):
        # Si ante una pregunta de catálogo/accesorio responde con una pregunta genérica sin dar nada útil.
        bad_generic = [
            "que hilo color o codigo busca",
            "que hilo, color o codigo busca",
            "me indica que hilo",
            "me indica que producto",
            "para revisarlo bien",
        ]
        if any(bg in tn for bg in bad_generic) and not any(x in tn for x in ["manej", "tenemos", "alize", "karina", "velluto", "komfy", "gancho", "aguja", "ojo"]):
            reasons.append("respondió genérico; debía mencionar catálogo/productos/accesorios")

    all_items: List[Dict[str, Any]] = []
    for r in responses:
        all_items.extend(collect_items(r))
    for exp_item in case.expect.get("expected_items") or []:
        if not item_matches(all_items, exp_item["codigo"], exp_item.get("cantidad")):
            reasons.append(f"no detectó item esperado: {exp_item}")
    for code in case.expect.get("expected_items_any") or []:
        if not item_matches(all_items, str(code), None) and norm(str(code)) not in tn:
            reasons.append(f"no detectó/mencionó código esperado: {code}")

    return len(reasons) == 0, reasons


def run_case(case: Case, base_url: str, pin: str, timeout: float, sleep_s: float, abort_if_not_tester: bool) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/api/whatsapp-ia/simular"
    memoria: Dict[str, Any] = {}
    conversacion_id = f"TEST-V39-{case.case_id}"
    responses: List[Dict[str, Any]] = []
    message_rows: List[Dict[str, Any]] = []

    for idx, turn in enumerate(case.turns):
        payload = {
            "texto": turn.text,
            "marca": turn.marca,
            "hilo": turn.hilo,
            "cliente_nombre": "Tester Humano Hilorama",
            "telefono": f"TEST-V39-{case.case_id}",
            "conversacion_id": conversacion_id,
            "nueva_conversacion": idx == 0,
            "tester_mode": True,
            "dry_run": True,
            "memoria": memoria,
        }
        resp = post_json(url, payload, pin, timeout=timeout)
        if abort_if_not_tester and not resp.get("tester_mode"):
            raise RuntimeError("El servidor no regresó tester_mode=true. Deteniendo para no guardar datos falsos.")
        responses.append(resp)
        message_rows.append({
            "turn_no": idx + 1,
            "cliente": turn.text,
            "respuesta": response_text(resp),
            "intencion": resp.get("intencion"),
            "confianza": resp.get("confianza"),
            "accion": resp.get("accion_recomendada"),
        })
        memoria = resp.get("memoria_actual") or memoria
        if sleep_s:
            time.sleep(sleep_s)

    passed, reasons = grade_case(case, responses)
    final = responses[-1] if responses else {}
    return {
        "case_id": case.case_id,
        "category": case.category,
        "passed": passed,
        "reasons": reasons,
        "turns": [t.text for t in case.turns],
        "messages": message_rows,
        "final_response": response_text(final),
        "intencion": final.get("intencion"),
        "confianza": final.get("confianza"),
        "accion": final.get("accion_recomendada"),
        "pedidos": collect_items(final),
        "raw_final": final,
    }


def write_reports(results: List[Dict[str, Any]], out_dir: Path, inventory: Dict[str, Any]):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"wa_human_test_results_v39_{stamp}.json"
    fail_csv_path = out_dir / f"wa_human_test_failures_v39_{stamp}.csv"
    conv_csv_path = out_dir / f"wa_human_test_conversaciones_v39_{stamp}.csv"
    html_path = out_dir / f"wa_human_test_report_v39_{stamp}.html"

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    with fail_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "reasons", "turns", "final_response", "intencion", "confianza", "accion"])
        for r in results:
            if not r["passed"]:
                w.writerow([r["case_id"], r["category"], " | ".join(r["reasons"]), " || ".join(r["turns"]), r["final_response"], r.get("intencion"), r.get("confianza"), r.get("accion")])

    with conv_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "passed", "turn_no", "cliente", "respuesta", "intencion", "confianza", "accion", "reasons"])
        for r in results:
            for m in r.get("messages") or []:
                w.writerow([r["case_id"], r["category"], r["passed"], m["turn_no"], m["cliente"], m["respuesta"], m.get("intencion"), m.get("confianza"), m.get("accion"), " | ".join(r.get("reasons") or [])])

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    cats: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r)
    rows = []
    for cat, arr in sorted(cats.items()):
        p = sum(1 for r in arr if r["passed"])
        rows.append(f"<tr><td>{html.escape(cat)}</td><td>{p}/{len(arr)}</td><td>{(p/len(arr)*100):.1f}%</td></tr>")

    failures = []
    for r in results:
        if not r["passed"]:
            convo = "".join(
                f"<p><b>Cliente {m['turn_no']}:</b> {html.escape(m['cliente'])}<br><b>IA:</b> {html.escape(m['respuesta'])}</p>"
                for m in r.get("messages") or []
            )
            failures.append(
                f"<details><summary><b>{html.escape(r['case_id'])}</b> - {html.escape(r['category'])}</summary>"
                f"<p><b>Razones:</b> {html.escape(' | '.join(r['reasons']))}</p>{convo}"
                f"<pre>{html.escape(json.dumps(r.get('pedidos') or [], ensure_ascii=False, indent=2))}</pre></details>"
            )

    inv_summary = f"Productos leídos: {len(inventory.get('products') or [])} | Marcas: {len(inventory.get('marcas') or [])} | Hilos: {len(inventory.get('hilos') or [])} | Accesorios detectados: {len(inventory.get('accessories') or [])}"
    if inventory.get("errors"):
        inv_summary += " | Avisos: " + "; ".join(inventory.get("errors") or [])

    html_doc = f"""<!doctype html><meta charset='utf-8'><title>WA IA Tester Humano V39</title>
    <style>body{{font-family:Arial,sans-serif;margin:24px}} table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px 10px}} details{{margin:12px 0;padding:10px;border:1px solid #ddd;border-radius:8px}} .bad{{color:#b00020}} .ok{{color:#067d2f}} p{{line-height:1.35}}</style>
    <h1>Reporte tester conversacional humano WhatsApp IA Hilorama V39</h1>
    <p>Total: <b>{total}</b> | Pasaron: <b class='ok'>{passed}</b> | Fallaron: <b class='bad'>{failed}</b> | Efectividad: <b>{(passed/total*100 if total else 0):.1f}%</b></p>
    <p><b>Inventario:</b> {html.escape(inv_summary)}</p>
    <h2>Por categoría</h2><table><tr><th>Categoría</th><th>Pasaron</th><th>%</th></tr>{''.join(rows)}</table>
    <h2>Fallos</h2>{''.join(failures[:500])}<p>Mostrando máximo 500 fallos en HTML. Ver CSV/JSON para todo.</p>
    <h2>Archivo para ver todas las conversaciones</h2><p>Abre en Excel: <b>{html.escape(conv_csv_path.name)}</b></p>
    """
    html_path.write_text(html_doc, encoding="utf-8")
    return json_path, fail_csv_path, conv_csv_path, html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="Ej: https://hilorama-celular.onrender.com")
    ap.add_argument("--pin", default="", help="MOBILE_PIN. Mejor no compartirlo en chats.")
    ap.add_argument("--limit", type=int, default=100, help="Número de conversaciones humanas a generar/probar")
    ap.add_argument("--seed", type=int, default=3636)
    ap.add_argument("--sleep", type=float, default=0.2, help="Pausa entre requests para no saturar Render/OpenAI")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default="wa_tester_reports")
    ap.add_argument("--inventory-limit", type=int, default=300, help="Máximo de productos a leer de /api/productos")
    ap.add_argument("--allow-real-write", action="store_true", help="No recomendado: permite seguir aunque el servidor no tenga tester_mode")
    args = ap.parse_args()

    print("Cargando resumen de almacén para generar preguntas basadas en tus productos...")
    inventory = load_inventory(args.base_url, args.pin, args.inventory_limit, args.timeout)
    print(f"Productos leídos: {len(inventory.get('products') or [])} | Marcas: {len(inventory.get('marcas') or [])} | Hilos: {len(inventory.get('hilos') or [])} | Accesorios detectados: {len(inventory.get('accessories') or [])}")
    if inventory.get("errors"):
        print("Avisos de inventario:")
        for e in inventory["errors"]:
            print(" -", e)

    cases = generate_cases(args.limit, inventory, args.seed)
    results: List[Dict[str, Any]] = []
    print(f"Ejecutando {len(cases)} conversaciones humanas contra {args.base_url}...")
    print("Recomendación: primero 30-50. Luego 100-200. Este tester es más pesado porque cada caso tiene varios mensajes.")

    for i, case in enumerate(cases, 1):
        try:
            res = run_case(case, args.base_url, args.pin, args.timeout, args.sleep, abort_if_not_tester=not args.allow_real_write)
        except Exception as exc:
            res = {
                "case_id": case.case_id,
                "category": case.category,
                "passed": False,
                "reasons": [f"EXCEPTION: {exc}"],
                "turns": [t.text for t in case.turns],
                "messages": [],
                "final_response": "",
                "traceback": traceback.format_exc(),
            }
            if "tester_mode" in str(exc):
                print("\nERROR: el sitio no regresó tester_mode=true. Deteniendo para no crear datos falsos.")
                results.append(res)
                break
        results.append(res)
        status = "OK" if res["passed"] else "FAIL"
        if i % 10 == 0 or not res["passed"]:
            print(f"[{i}/{len(cases)}] {status} {case.case_id} {(res.get('reasons') or [''])[:1]}")

    json_path, fail_csv_path, conv_csv_path, html_path = write_reports(results, Path(args.out), inventory)
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print("\nListo.")
    print(f"Pasaron: {passed}/{total} ({(passed/total*100 if total else 0):.1f}%)")
    print(f"Reporte HTML: {html_path}")
    print(f"Fallos CSV: {fail_csv_path}")
    print(f"Conversaciones CSV: {conv_csv_path}")
    print(f"JSON completo: {json_path}")


if __name__ == "__main__":
    main()
