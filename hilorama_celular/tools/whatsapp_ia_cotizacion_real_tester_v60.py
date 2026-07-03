#!/usr/bin/env python3
"""
Tester V60 de cotizaciones reales largas + envío volumétrico Hilorama.

Objetivo:
- Generar 1000 conversaciones distintas y pesadas.
- Pedir cotizaciones reales usando productos del almacén (/api/productos).
- Probar listas largas: 20 a 80 renglones por conversación, en varios mensajes.
- Probar pedidos Velluto grandes: 35 -> tramo 5 kg, mas de 35 -> tramo 10 kg, hasta 15 kg, mayor a 15 kg -> revisión manual.
- Probar pedidos mixtos: Velluto + Komfy + otros hilos/accesorios si existen.
- Pedir costo de envío con CP y verificar que use memoria/pedido acumulado.
- Verificar con /api/envios/debug-volumetrico que el cálculo volumétrico sea congruente.

Uso recomendado:
  python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 10 --sleep 0.3
  python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.3
  python hilorama_celular/tools/whatsapp_ia_cotizacion_real_tester_v60.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.3

IMPORTANTE:
- Usa tester_mode=true y dry_run=true.
- No debe crear notas reales.
- No debe apartar stock real.
- Si el sitio no regresa tester_mode=true, se detiene para no ensuciar datos.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import random
import re
import time
import traceback
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_PRODUCTS = [
    {"producto_id": 33, "marca": "ALIZE", "hilo": "VELLUTO", "codigo": "429", "color": "TABACO CLARO", "stock": 110, "precio_venta": 59.99, "volumetrico": 5/35},
    {"producto_id": 6, "marca": "ALIZE", "hilo": "VELLUTO", "codigo": "60", "color": "NEGRO", "stock": 74, "precio_venta": 59.99, "volumetrico": 5/35},
    {"producto_id": 7, "marca": "ALIZE", "hilo": "VELLUTO", "codigo": "56", "color": "ROJO", "stock": 135, "precio_venta": 59.99, "volumetrico": 5/35},
    {"producto_id": 10, "marca": "ALIZE", "hilo": "VELLUTO", "codigo": "55", "color": "BLANCO", "stock": 50, "precio_venta": 59.99, "volumetrico": 5/35},
    {"producto_id": 1001, "marca": "KARINA", "hilo": "KOMFY MINI", "codigo": "99", "color": "NEGRO", "stock": 50, "precio_venta": 26.99, "volumetrico": 0.07},
]

CP_POOL = [
    "97000", "64600", "78174", "03910", "57000", "64000", "44100", "72000", "50000", "77500",
    "76000", "22000", "80000", "29000", "20000", "86000", "37000", "45000", "52140", "94300",
]

OPENERS = [
    "hola buenas tardes", "holaa", "buen dia", "buenas trades", "disculpa", "oye una pregunta",
    "hola disculpa de casualidad", "que tal buen dia", "buenas, me apoyas", "hola me puedes ayudar",
]

START_ORDER = [
    "quiero hacer pedido", "me puedes cotizar una lista", "te paso mi listita", "quiero cotisar varios hilos",
    "me armas cotizacion porfa", "ocupo varios estambres", "te mando lista larga", "me apoyas con una cotizacion",
]

SHIP_ASKS = [
    "cuanto seria con envio al codigo postal {cp}",
    "ya con envio al cp {cp} cuanto queda",
    "mi cp es {cp} cuanto seria con envio",
    "me agregas envio a {cp} por favor",
    "cuanto me sale todo con envio al {cp}",
    "y envio para {cp} como quedaria",
]

TOTAL_ASKS = [
    "cuanto llevo hasta ahorita", "me dices cuanto va", "cuanto seria de puro producto", "cuanto me sale la lista",
]

FORBIDDEN_PUBLIC_PHRASES = [
    "parser", "traceback", "exception", "keyerror", "typeerror", "undefined", "none", "null",
    "advertencias", "errores internos", "confianza baja", "tester_mode", "dry_run",
    "no ubique", "no ubiqué", "productos inventados", "apartado", "apartar", "le aparto",
]

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
    expected_items: List[Dict[str, Any]] = field(default_factory=list)
    cp: str = ""
    expected_tramo_kg: Optional[int] = None
    expected_manual: bool = False
    direct_debug_only: bool = False
    min_unique_ratio: float = 0.80
    min_qty_ratio: float = 0.80
    notes: str = ""


def norm(s: Any) -> str:
    t = str(s or "").lower()
    return t.translate(str.maketrans("áéíóúüñ", "aeiouun"))


def safe(v: Any) -> str:
    return str(v or "").strip()


def slug(s: str, max_len: int = 90) -> str:
    s = norm(s)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:max_len] or "caso"


def money(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def qty_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v or 0))
    except Exception:
        return default


def post_json(url: str, payload: Dict[str, Any], pin: str = "", timeout: float = 80.0) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if pin:
        req.add_header("X-Mobile-Pin", pin)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def get_json(url: str, pin: str = "", timeout: float = 60.0) -> Any:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    if pin:
        req.add_header("X-Mobile-Pin", pin)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def response_text(resp: Dict[str, Any]) -> str:
    return safe(resp.get("respuesta_sugerida") or resp.get("respuesta_diferida") or resp.get("respuesta") or "")


def load_inventory(base_url: str, pin: str, timeout: float, inventory_limit: int = 500) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    errors: List[str] = []
    products: List[Dict[str, Any]] = []
    try:
        qs = urllib.parse.urlencode({"limit": min(max(inventory_limit, 50), 1000)})
        obj = get_json(base + "/api/productos?" + qs, pin=pin, timeout=timeout)
        if isinstance(obj, list):
            products = obj
        elif isinstance(obj, dict):
            for key in ("productos", "items", "data", "rows"):
                if isinstance(obj.get(key), list):
                    products = obj[key]
                    break
    except Exception as exc:
        errors.append(f"No pude leer /api/productos: {exc}")

    if not products:
        products = list(DEFAULT_PRODUCTS)

    clean: List[Dict[str, Any]] = []
    for p in products:
        d = dict(p or {})
        # Normaliza aliases comunes.
        if "producto_id" not in d and "id" in d:
            d["producto_id"] = d.get("id")
        if "precio_venta" not in d:
            d["precio_venta"] = d.get("precio") or d.get("venta") or d.get("precio_publico") or 0
        for k in ("marca", "hilo", "codigo", "color"):
            d[k] = safe(d.get(k))
        d["stock"] = qty_int(d.get("stock"), 0)
        d["precio_venta"] = money(d.get("precio_venta"))
        # conservar volumétrico si viene.
        for vk in ("volumetrico", "peso_volumetrico", "volumetrico_kg", "peso_volumetrico_kg"):
            if vk in d:
                try:
                    d[vk] = float(d.get(vk) or 0)
                except Exception:
                    d[vk] = 0
        if d.get("codigo") or d.get("hilo") or d.get("color"):
            clean.append(d)

    available = [p for p in clean if qty_int(p.get("stock"), 0) > 0]
    if not available:
        available = clean or list(DEFAULT_PRODUCTS)

    velluto = [p for p in available if "velluto" in norm(" ".join([p.get("marca",""), p.get("hilo",""), p.get("color","")]))]
    komfy = [p for p in available if "komfy" in norm(" ".join([p.get("marca",""), p.get("hilo",""), p.get("color","")])) or "komfi" in norm(p.get("hilo", ""))]
    accesorios = [p for p in available if any(x in norm(" ".join([p.get("marca",""), p.get("hilo",""), p.get("color","")])) for x in ["gancho", "aguja", "ojo", "seguridad", "relleno", "marcador"])]
    hilos = [p for p in available if p not in accesorios]

    marcas = sorted({p.get("marca", "") for p in clean if p.get("marca")})
    tipos_hilo = sorted({p.get("hilo", "") for p in clean if p.get("hilo")})
    return {
        "products": clean,
        "available": available,
        "velluto": velluto,
        "komfy": komfy,
        "hilos": hilos,
        "accesorios": accesorios,
        "marcas": marcas,
        "tipos_hilo": tipos_hilo,
        "errors": errors,
    }


def product_key(p: Dict[str, Any]) -> Tuple[str, str, str]:
    return (norm(p.get("marca")), norm(p.get("hilo")), safe(p.get("codigo")).lstrip("0") or safe(p.get("codigo")))


def item_key(it: Dict[str, Any]) -> Tuple[str, str, str]:
    return (norm(it.get("marca")), norm(it.get("hilo")), safe(it.get("codigo") or it.get("codigo_raw")).lstrip("0") or safe(it.get("codigo") or it.get("codigo_raw")))


def compact_expected(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    agg: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for it in items:
        q = qty_int(it.get("cantidad"), 1)
        k = item_key(it)
        if k not in agg:
            d = dict(it)
            d["cantidad"] = 0
            agg[k] = d
        agg[k]["cantidad"] = qty_int(agg[k].get("cantidad"), 0) + q
    return list(agg.values())


def choose(rng: random.Random, seq: List[Any], fallback: Any = None) -> Any:
    return rng.choice(seq) if seq else fallback


def public_line_for_item(rng: random.Random, item: Dict[str, Any]) -> str:
    q = qty_int(item.get("cantidad"), 1)
    codigo = safe(item.get("codigo"))
    hilo = safe(item.get("hilo"))
    color = safe(item.get("color"))
    variants = [
        f"{q} del {codigo}",
        f"{codigo} x{q}",
        f"{hilo} {codigo} x{q}",
        f"{q} piezas {codigo}",
        f"{codigo} {q}",
    ]
    if color and rng.random() < 0.18:
        variants.append(f"{q} {color} codigo {codigo}")
    return rng.choice([v for v in variants if v.strip()])


def split_chunks(lines: List[str], rng: random.Random, min_chunk: int = 8, max_chunk: int = 18) -> List[str]:
    chunks = []
    idx = 0
    while idx < len(lines):
        size = rng.randint(min_chunk, max_chunk)
        part = lines[idx:idx+size]
        sep = "\n" if rng.random() < 0.72 else ", "
        prefix = rng.choice(["", "va otra parte:\n", "tambien:\n", "y estos tambien:\n"])
        chunks.append(prefix + sep.join(part))
        idx += size
    return chunks


def build_items_from_pool(rng: random.Random, pool: List[Dict[str, Any]], line_count: int, qty_min: int = 1, qty_max: int = 3) -> List[Dict[str, Any]]:
    if not pool:
        pool = list(DEFAULT_PRODUCTS)
    out: List[Dict[str, Any]] = []
    # Control simple para no pedir cantidades absurdas por código si hay stock.
    used_by_key: Dict[Tuple[str, str, str], int] = {}
    for _ in range(line_count):
        p = choose(rng, pool, DEFAULT_PRODUCTS[0])
        k = product_key(p)
        stock = qty_int(p.get("stock"), 999)
        used = used_by_key.get(k, 0)
        max_allowed = max(1, min(qty_max, stock - used if stock > 0 else qty_max))
        if max_allowed <= 0:
            q = 1
        else:
            q = rng.randint(qty_min, max_allowed)
        used_by_key[k] = used + q
        item = {
            "producto_id": p.get("producto_id") or p.get("id"),
            "codigo": safe(p.get("codigo")),
            "marca": safe(p.get("marca")),
            "hilo": safe(p.get("hilo")),
            "color": safe(p.get("color")),
            "cantidad": q,
            "precio_venta": money(p.get("precio_venta")),
        }
        # Incluir volumétrico si el inventario lo trae para debug y comparación.
        for vk in ("volumetrico", "peso_volumetrico", "volumetrico_kg", "peso_volumetrico_kg"):
            if p.get(vk) not in (None, ""):
                item[vk] = p.get(vk)
        out.append(item)
    return compact_expected(out)


def find_velluto_code(inv: Dict[str, Any], preferred: List[str]) -> Dict[str, Any]:
    vell = inv.get("velluto") or []
    for code in preferred:
        for p in vell:
            if safe(p.get("codigo")).lstrip("0") == code.lstrip("0") and qty_int(p.get("stock"), 0) > 0:
                return p
    return choose(random.Random(1), vell, DEFAULT_PRODUCTS[0])


def find_komfy(inv: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    komfy = inv.get("komfy") or []
    return choose(random.Random(2), komfy, None)


def expected_tramo_for_velluto_count(velluto_count: int) -> Tuple[int, bool]:
    # Regla comercial indicada por Hilorama: 35 Vellutos ~= 5 kg volumétricos.
    raw = (velluto_count * 5.0) / 35.0
    tramo = int(math.ceil(max(raw, 0.0001) / 5.0) * 5)
    tramo = max(5, tramo)
    return tramo, tramo > 15


def make_case_from_items(rng: random.Random, idx: int, category: str, items: List[Dict[str, Any]], cp: str, intro_hilo: str = "", expected_tramo_kg: Optional[int] = None, expected_manual: bool = False) -> Case:
    lines = [public_line_for_item(rng, it) for it in items]
    chunks = split_chunks(lines, rng)
    turns: List[Turn] = []
    turns.append(Turn(rng.choice(OPENERS)))
    start = rng.choice(START_ORDER)
    if intro_hilo:
        start += f" de {intro_hilo}"
    turns.append(Turn(start))
    turns.extend(Turn(ch) for ch in chunks)
    if rng.random() < 0.35:
        turns.append(Turn(rng.choice(TOTAL_ASKS)))
    turns.append(Turn(rng.choice(SHIP_ASKS).format(cp=cp)))
    return Case(
        case_id=f"{idx:05d}_{category}_{slug(turns[-1].text)}",
        category=category,
        turns=turns,
        expected_items=items,
        cp=cp,
        expected_tramo_kg=expected_tramo_kg,
        expected_manual=expected_manual,
        min_unique_ratio=0.72 if len(items) >= 50 else 0.80,
        min_qty_ratio=0.70 if len(items) >= 50 else 0.78,
    )


def generate_cases(limit: int, inv: Dict[str, Any], seed: int, lineas_min: int, lineas_max: int) -> List[Case]:
    rng = random.Random(seed)
    cases: List[Case] = []
    idx = 1
    velluto_pool = inv.get("velluto") or [p for p in DEFAULT_PRODUCTS if p["hilo"] == "VELLUTO"]
    hilos_pool = inv.get("hilos") or inv.get("available") or DEFAULT_PRODUCTS
    mixed_pool = (inv.get("hilos") or []) + (inv.get("accesorios") or [])
    if not mixed_pool:
        mixed_pool = inv.get("available") or DEFAULT_PRODUCTS

    # Casos fijos críticos: estos NO deben fallar aunque el tester general pase.
    # Si 35 Velluto sale como 53 kg, este tester lo marca como falla.
    fixed_counts = [35, 40, 70, 80, 105, 106, 120]
    for count in fixed_counts:
        p = find_velluto_code(inv, ["429", "60", "56", "55", "87", "550"])
        item = {
            "producto_id": p.get("producto_id") or p.get("id"),
            "codigo": safe(p.get("codigo")),
            "marca": safe(p.get("marca")) or "ALIZE",
            "hilo": safe(p.get("hilo")) or "VELLUTO",
            "color": safe(p.get("color")),
            "cantidad": count,
            "precio_venta": money(p.get("precio_venta") or 59.99),
        }
        # NO metemos volumétrico manual aquí: queremos que el backend lo tome del almacén.
        tramo, manual = expected_tramo_for_velluto_count(count)
        cp = rng.choice(CP_POOL)
        turns = [
            Turn(rng.choice(OPENERS)),
            Turn("quiero hacer pedido de velluto"),
            Turn(f"ponme {count} del {item['codigo']}"),
            Turn(rng.choice(SHIP_ASKS).format(cp=cp)),
        ]
        cases.append(Case(
            case_id=f"{idx:05d}_v60_invariante_velluto_{count}_piezas_{tramo}kg",
            category="v60_invariante_volumetrico_velluto",
            turns=turns,
            expected_items=[item],
            cp=cp,
            expected_tramo_kg=tramo,
            expected_manual=manual,
            min_unique_ratio=1.0,
            min_qty_ratio=0.95,
            notes=f"Regla: 35 Vellutos = 5 kg volumétricos. {count} piezas => tramo {tramo} kg.",
        ))
        idx += 1

    # Caso fijo mixto 34 Velluto + 2 Komfy, debe seguir en tramo de 5 kg si Komfy está configurado razonablemente.
    komfy = find_komfy(inv)
    if komfy:
        vp = find_velluto_code(inv, ["429", "60", "56", "55"])
        items = [
            {"producto_id": vp.get("producto_id") or vp.get("id"), "codigo": safe(vp.get("codigo")), "marca": safe(vp.get("marca")), "hilo": safe(vp.get("hilo")), "color": safe(vp.get("color")), "cantidad": 34, "precio_venta": money(vp.get("precio_venta"))},
            {"producto_id": komfy.get("producto_id") or komfy.get("id"), "codigo": safe(komfy.get("codigo")), "marca": safe(komfy.get("marca")), "hilo": safe(komfy.get("hilo")), "color": safe(komfy.get("color")), "cantidad": 2, "precio_venta": money(komfy.get("precio_venta"))},
        ]
        cp = rng.choice(CP_POOL)
        cases.append(Case(
            case_id=f"{idx:05d}_v60_invariante_34_velluto_2_komfy_5kg",
            category="v60_invariante_volumetrico_mixto",
            turns=[Turn("hola"), Turn("quiero hacer pedido"), Turn(f"velluto {items[0]['codigo']} x34 y {items[1]['hilo']} {items[1]['codigo']} x2"), Turn(rng.choice(SHIP_ASKS).format(cp=cp))],
            expected_items=items,
            cp=cp,
            expected_tramo_kg=5,
            expected_manual=False,
            min_unique_ratio=1.0,
            min_qty_ratio=0.95,
            notes="Regla comercial: 34 Vellutos + 2 Komfy Mini debe seguir en tramo de 5 kg si el volumétrico está bien configurado.",
        ))
        idx += 1

    while len(cases) < limit:
        kind = rng.choices(
            ["velluto_largo", "mixto_largo", "mega_80", "correccion_larga", "solo_velluto_tramos"],
            weights=[30, 30, 18, 12, 10],
            k=1,
        )[0]
        cp = rng.choice(CP_POOL)
        line_count = rng.randint(max(4, lineas_min), max(lineas_min, lineas_max))
        if kind == "mega_80":
            line_count = max(80, lineas_max)
        if kind == "velluto_largo":
            items = build_items_from_pool(rng, velluto_pool, line_count, 1, 2)
            total_v = sum(qty_int(x.get("cantidad"), 0) for x in items)
            tramo, manual = expected_tramo_for_velluto_count(total_v)
            cases.append(make_case_from_items(rng, idx, "v60_cotizacion_larga_velluto_con_envio", items, cp, "Velluto", tramo, manual))
        elif kind == "solo_velluto_tramos":
            # cantidades diseñadas para caer en 5/10/15/manual.
            target = rng.choice([28, 35, 36, 52, 70, 71, 95, 105, 106, 120])
            p = find_velluto_code(inv, ["429", "60", "56", "55", "550", "87"])
            items = [{"producto_id": p.get("producto_id") or p.get("id"), "codigo": safe(p.get("codigo")), "marca": safe(p.get("marca")), "hilo": safe(p.get("hilo")), "color": safe(p.get("color")), "cantidad": target, "precio_venta": money(p.get("precio_venta"))}]
            tramo, manual = expected_tramo_for_velluto_count(target)
            cases.append(make_case_from_items(rng, idx, "v60_tramos_velluto_5_10_15_manual", items, cp, "Velluto", tramo, manual))
        elif kind == "mixto_largo":
            items = build_items_from_pool(rng, mixed_pool, line_count, 1, 3)
            cases.append(make_case_from_items(rng, idx, "v60_cotizacion_mixta_larga_con_envio", items, cp, "", None, False))
        elif kind == "mega_80":
            pool = velluto_pool if rng.random() < 0.65 else mixed_pool
            items = build_items_from_pool(rng, pool, line_count, 1, 2)
            if pool is velluto_pool or all("velluto" in norm(x.get("hilo")) for x in items):
                total_v = sum(qty_int(x.get("cantidad"), 0) for x in items)
                tramo, manual = expected_tramo_for_velluto_count(total_v)
            else:
                tramo, manual = None, False
            cases.append(make_case_from_items(rng, idx, "v60_lista_80_renglones_con_envio", items, cp, "", tramo, manual))
        else:  # correccion_larga
            items = build_items_from_pool(rng, velluto_pool or hilos_pool, max(12, min(line_count, 35)), 1, 2)
            # Quitamos uno y agregamos otro después, para ver si la memoria se actualiza.
            remove_item = choose(rng, items, items[0])
            add_item = build_items_from_pool(rng, velluto_pool or hilos_pool, 1, 1, 3)[0]
            final_items = [x for x in items if item_key(x) != item_key(remove_item)] + [add_item]
            total_v = sum(qty_int(x.get("cantidad"), 0) for x in final_items if "velluto" in norm(x.get("hilo")))
            tramo, manual = expected_tramo_for_velluto_count(total_v) if total_v else (None, False)
            lines = [public_line_for_item(rng, it) for it in items]
            chunks = split_chunks(lines, rng)
            turns = [Turn(rng.choice(OPENERS)), Turn("te paso una lista para cotizar")]
            turns.extend(Turn(c) for c in chunks)
            turns.append(Turn(f"perdon quitame el {safe(remove_item.get('codigo'))}"))
            turns.append(Turn(f"mejor agregame {public_line_for_item(rng, add_item)}"))
            turns.append(Turn(rng.choice(SHIP_ASKS).format(cp=cp)))
            cases.append(Case(
                case_id=f"{idx:05d}_v60_correccion_larga_con_envio_{slug(turns[-1].text)}",
                category="v60_correccion_larga_con_envio",
                turns=turns,
                expected_items=compact_expected(final_items),
                cp=cp,
                expected_tramo_kg=tramo,
                expected_manual=manual,
                min_unique_ratio=0.65,
                min_qty_ratio=0.65,
            ))
        idx += 1

    return cases[:limit]


def parse_json_maybe(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def final_memory_items(responses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not responses:
        return []
    for resp in reversed(responses):
        mem = resp.get("memoria_actual") or resp.get("memoria") or {}
        if isinstance(mem, dict):
            obj = parse_json_maybe(mem.get("pedido_en_proceso"))
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
    return []


def all_detected_items(responses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for resp in responses:
        if isinstance(resp.get("pedidos"), list):
            out.extend(x for x in resp["pedidos"] if isinstance(x, dict))
        parser = resp.get("parser") or {}
        if isinstance(parser, dict):
            for key in ("pedidos", "items_lista_v27", "items_lista_v17"):
                if isinstance(parser.get(key), list):
                    out.extend(x for x in parser[key] if isinstance(x, dict))
        v30 = resp.get("v30") or {}
        if isinstance(v30, dict):
            resol = v30.get("resolucion") or {}
            if isinstance(resol.get("pedidos"), list):
                out.extend(x for x in resol["pedidos"] if isinstance(x, dict))
    return out


def match_stats(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> Dict[str, Any]:
    exp = compact_expected(expected)
    act = compact_expected(actual)
    exp_map = {item_key(x): qty_int(x.get("cantidad"), 1) for x in exp}
    act_map = {item_key(x): qty_int(x.get("cantidad"), 1) for x in act}
    # fallback por código si marca/hilo se perdió.
    act_by_code: Dict[str, int] = {}
    for x in act:
        c = safe(x.get("codigo") or x.get("codigo_raw")).lstrip("0") or safe(x.get("codigo") or x.get("codigo_raw"))
        act_by_code[c] = act_by_code.get(c, 0) + qty_int(x.get("cantidad"), 1)
    matched_unique = 0
    matched_qty = 0
    for k, q in exp_map.items():
        aq = act_map.get(k)
        if aq is None:
            code = k[2]
            aq = act_by_code.get(code, 0)
        if aq and aq > 0:
            matched_unique += 1
            matched_qty += min(q, aq)
    exp_qty = sum(exp_map.values())
    return {
        "expected_unique": len(exp_map),
        "actual_unique": len(act_map),
        "matched_unique": matched_unique,
        "expected_qty": exp_qty,
        "matched_qty": matched_qty,
        "unique_ratio": matched_unique / len(exp_map) if exp_map else 1.0,
        "qty_ratio": matched_qty / exp_qty if exp_qty else 1.0,
    }


def debug_volumetrico(base_url: str, pin: str, items: List[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/api/envios/debug-volumetrico"
    payload = {"items": items}
    return post_json(url, payload, pin=pin, timeout=timeout)


def extract_kg_mentions(text: str) -> List[float]:
    out = []
    for m in re.finditer(r"(\d+(?:[\.,]\d+)?)\s*kg\s*vol", norm(text)):
        try:
            out.append(float(m.group(1).replace(",", ".")))
        except Exception:
            pass
    return out


def grade_response(case: Case, responses: List[Dict[str, Any]], debug_obj: Optional[Dict[str, Any]]) -> Tuple[bool, List[str], Dict[str, Any]]:
    reasons: List[str] = []
    extra: Dict[str, Any] = {}
    text_all = "\n".join(response_text(r) for r in responses)
    final_text = response_text(responses[-1]) if responses else ""
    tn_all = norm(text_all)
    tn_final = norm(final_text)

    if not responses and not case.direct_debug_only:
        reasons.append("no hubo respuestas del agente")
    for i, r in enumerate(responses, 1):
        if not r.get("ok"):
            reasons.append(f"turno {i}: ok=false")
        if not r.get("tester_mode"):
            reasons.append(f"turno {i}: no regresó tester_mode=true")
    for bad in FORBIDDEN_PUBLIC_PHRASES:
        if norm(bad) in tn_all:
            reasons.append(f"respuesta contiene frase prohibida/interna: {bad}")
    if responses and len(final_text.strip()) < 10:
        reasons.append("respuesta final demasiado corta")

    mem_items = final_memory_items(responses)
    det_items = all_detected_items(responses)
    actual_items = mem_items or det_items
    stats = match_stats(case.expected_items, actual_items) if case.expected_items else {}
    extra["match_stats"] = stats
    extra["final_memory_items_count"] = len(mem_items)
    if case.expected_items:
        if not actual_items:
            reasons.append("no hay pedido acumulado en memoria ni productos detectados")
        else:
            if stats.get("unique_ratio", 1) < case.min_unique_ratio:
                reasons.append(f"detectó pocos códigos/productos: {stats.get('matched_unique')}/{stats.get('expected_unique')} ({stats.get('unique_ratio'):.1%})")
            if stats.get("qty_ratio", 1) < case.min_qty_ratio:
                reasons.append(f"detectó poca cantidad total: {stats.get('matched_qty')}/{stats.get('expected_qty')} ({stats.get('qty_ratio'):.1%})")

    # Validación debug volumétrico.
    if debug_obj:
        plan = debug_obj.get("plan_volumetrico") or {}
        kg = plan.get("peso_volumetrico_kg")
        tramo = plan.get("tramo_kg")
        extra["debug_kg"] = kg
        extra["debug_tramo"] = tramo
        extra["debug_motivo_humano"] = plan.get("motivo_humano")
        if case.expected_tramo_kg is not None:
            try:
                tramo_i = int(float(tramo or 0))
            except Exception:
                tramo_i = 0
            if tramo_i != int(case.expected_tramo_kg):
                reasons.append(f"debug-volumétrico dio tramo {tramo_i} kg; esperado {case.expected_tramo_kg} kg")
        if case.expected_manual != bool(plan.get("requiere_humano")) and case.expected_tramo_kg is not None:
            reasons.append(f"debug-volumétrico requiere_humano={plan.get('requiere_humano')}; esperado {case.expected_manual}")
        if plan.get("motivo_humano") == "productos_sin_volumetrico_configurado":
            reasons.append("hay productos sin volumétrico configurado en almacén")

    # Validación de respuesta pública de envío.
    if case.cp:
        if case.cp not in final_text:
            reasons.append(f"respuesta final no menciona CP {case.cp}")
        if "envio" not in tn_final and "envío" not in tn_final:
            reasons.append("respuesta final no habla del envío")
        if "volum" not in tn_final:
            reasons.append("respuesta final no menciona kg/tramo volumétrico")
        if case.expected_manual:
            if not any(x in tn_final for x in ["manual", "revis", "confirm", "no cobrarle mal", "humano"]):
                reasons.append("debía mandar revisión manual por volumétrico alto y no lo hizo")
        else:
            if any(x in tn_final for x in ["pasa de 15", "manual", "necesito revisarle el envio manualmente", "mayor al limite"]):
                reasons.append("mandó a revisión manual pero el tramo esperado era automático")
            if not any(x in tn_final for x in ["correos", "estafeta", "fedex", "dhl", "paqueter"]):
                reasons.append("no muestra opciones de paquetería")
            if "$" not in final_text:
                reasons.append("no muestra precios de envío/total")
            if case.expected_tramo_kg is not None:
                kg_mentions = extract_kg_mentions(final_text)
                if kg_mentions and max(kg_mentions) > max(15, case.expected_tramo_kg + 2):
                    reasons.append(f"respuesta menciona kg volumétricos demasiado altos {kg_mentions}; esperado tramo {case.expected_tramo_kg}")
                if str(case.expected_tramo_kg) not in re.sub(r"\s+", "", tn_final) and f"{case.expected_tramo_kg} kg" not in tn_final:
                    # No todos los formatos tienen que decir exactamente el tramo, pero debe haber señal clara.
                    if case.expected_tramo_kg in (5, 10, 15):
                        reasons.append(f"no parece mencionar el tramo esperado de {case.expected_tramo_kg} kg volumétricos")
            # Si hay subtotal/cotización real, debería mencionar total con productos o subtotal.
            if not any(x in tn_final for x in ["total con productos", "subtotal", "total:", "queda en", "con productos"]):
                reasons.append("no parece dar total/subtotal real con envío")

    return len(reasons) == 0, reasons, extra


def run_case(case: Case, base_url: str, pin: str, timeout: float, sleep_s: float, abort_if_not_tester: bool, run_debug: bool) -> Dict[str, Any]:
    debug_obj: Optional[Dict[str, Any]] = None
    debug_error = ""
    if run_debug and case.expected_items:
        try:
            debug_obj = debug_volumetrico(base_url, pin, case.expected_items, timeout=timeout)
        except Exception as exc:
            debug_error = str(exc)

    responses: List[Dict[str, Any]] = []
    message_rows: List[Dict[str, Any]] = []
    if not case.direct_debug_only:
        url = base_url.rstrip("/") + "/api/whatsapp-ia/simular"
        memoria: Dict[str, Any] = {}
        conversation_id = f"TEST-V60-{case.case_id}"
        for idx, turn in enumerate(case.turns):
            payload = {
                "texto": turn.text,
                "marca": turn.marca,
                "hilo": turn.hilo,
                "cliente_nombre": "Tester Cotizacion Real Hilorama",
                "telefono": f"TEST-V60-{case.case_id}",
                "conversacion_id": conversation_id,
                "nueva_conversacion": idx == 0,
                "tester_mode": True,
                "dry_run": True,
                "memoria": memoria,
            }
            resp = post_json(url, payload, pin=pin, timeout=timeout)
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

    passed, reasons, extra = grade_response(case, responses, debug_obj)
    if debug_error:
        passed = False
        reasons.append(f"debug-volumétrico falló: {debug_error}")
    final = responses[-1] if responses else {}
    return {
        "case_id": case.case_id,
        "category": case.category,
        "passed": passed,
        "reasons": reasons,
        "notes": case.notes,
        "turns": [t.text for t in case.turns],
        "expected_items": case.expected_items,
        "expected_tramo_kg": case.expected_tramo_kg,
        "expected_manual": case.expected_manual,
        "cp": case.cp,
        "messages": message_rows,
        "final_response": response_text(final),
        "intencion": final.get("intencion"),
        "confianza": final.get("confianza"),
        "accion": final.get("accion_recomendada"),
        "memory_items": final_memory_items(responses),
        "detected_items": all_detected_items(responses),
        "debug_volumetrico": debug_obj,
        "debug_error": debug_error,
        "extra": extra,
        "raw_final": final,
    }


def write_reports(results: List[Dict[str, Any]], out_dir: Path, inv: Dict[str, Any]) -> Tuple[Path, Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"wa_quote_real_test_results_v60_{stamp}.json"
    fail_csv_path = out_dir / f"wa_quote_real_test_failures_v60_{stamp}.csv"
    conv_csv_path = out_dir / f"wa_quote_real_test_conversaciones_v60_{stamp}.csv"
    html_path = out_dir / f"wa_quote_real_test_report_v60_{stamp}.html"

    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    with fail_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "reasons", "expected_tramo_kg", "expected_manual", "cp", "final_response", "debug_kg", "debug_tramo", "match_stats"])
        for r in results:
            if not r.get("passed"):
                extra = r.get("extra") or {}
                w.writerow([
                    r.get("case_id"), r.get("category"), " | ".join(r.get("reasons") or []), r.get("expected_tramo_kg"), r.get("expected_manual"), r.get("cp"),
                    r.get("final_response"), extra.get("debug_kg"), extra.get("debug_tramo"), json.dumps(extra.get("match_stats") or {}, ensure_ascii=False),
                ])

    with conv_csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "passed", "turn_no", "cliente", "respuesta", "intencion", "confianza", "accion", "reasons"])
        for r in results:
            for m in r.get("messages") or []:
                w.writerow([r.get("case_id"), r.get("category"), r.get("passed"), m.get("turn_no"), m.get("cliente"), m.get("respuesta"), m.get("intencion"), m.get("confianza"), m.get("accion"), " | ".join(r.get("reasons") or [])])

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    cats: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        cats.setdefault(r.get("category") or "sin_categoria", []).append(r)
    rows = []
    for cat, arr in sorted(cats.items()):
        p = sum(1 for x in arr if x.get("passed"))
        rows.append(f"<tr><td>{html.escape(cat)}</td><td>{p}/{len(arr)}</td><td>{(p/len(arr)*100):.1f}%</td></tr>")

    failures = []
    for r in results:
        if not r.get("passed"):
            convo = "".join(
                f"<p><b>Cliente {m.get('turn_no')}:</b> {html.escape(str(m.get('cliente') or ''))}<br><b>IA:</b> {html.escape(str(m.get('respuesta') or ''))}</p>"
                for m in r.get("messages") or []
            )
            failures.append(
                f"<details><summary><b>{html.escape(str(r.get('case_id')))}</b> - {html.escape(str(r.get('category')))}</summary>"
                f"<p><b>Razones:</b> {html.escape(' | '.join(r.get('reasons') or []))}</p>"
                f"<p><b>Esperado:</b> CP {html.escape(str(r.get('cp') or ''))}, tramo {html.escape(str(r.get('expected_tramo_kg') or ''))}, manual {html.escape(str(r.get('expected_manual')))}</p>"
                f"{convo}"
                f"<h4>Debug volumétrico</h4><pre>{html.escape(json.dumps(r.get('debug_volumetrico') or {}, ensure_ascii=False, indent=2)[:6000])}</pre>"
                f"<h4>Memoria pedido</h4><pre>{html.escape(json.dumps(r.get('memory_items') or [], ensure_ascii=False, indent=2)[:6000])}</pre>"
                f"</details>"
            )
    inv_summary = (
        f"Productos leídos: {len(inv.get('products') or [])} | "
        f"Velluto detectados: {len(inv.get('velluto') or [])} | "
        f"Komfy detectados: {len(inv.get('komfy') or [])} | "
        f"Disponibles: {len(inv.get('available') or [])}"
    )
    if inv.get("errors"):
        inv_summary += " | Avisos: " + "; ".join(inv.get("errors") or [])
    html_doc = f"""<!doctype html><meta charset='utf-8'><title>WA Cotización Real Tester V60</title>
    <style>body{{font-family:Arial,sans-serif;margin:24px}} table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px 10px}} details{{margin:12px 0;padding:10px;border:1px solid #ddd;border-radius:8px}} .bad{{color:#b00020}} .ok{{color:#067d2f}} p{{line-height:1.35}} pre{{white-space:pre-wrap;max-height:420px;overflow:auto;background:#f7f7f7;padding:8px}}</style>
    <h1>Reporte tester V60 cotizaciones reales + envío volumétrico Hilorama</h1>
    <p>Total: <b>{total}</b> | Pasaron: <b class='ok'>{passed}</b> | Fallaron: <b class='bad'>{failed}</b> | Efectividad: <b>{(passed/total*100 if total else 0):.1f}%</b></p>
    <p><b>Inventario:</b> {html.escape(inv_summary)}</p>
    <h2>Por categoría</h2><table><tr><th>Categoría</th><th>Pasaron</th><th>%</th></tr>{''.join(rows)}</table>
    <h2>Fallos</h2>{''.join(failures[:500])}<p>Mostrando máximo 500 fallos en HTML. Ver CSV/JSON para todo.</p>
    <h2>Archivos</h2><p>Conversaciones: <b>{html.escape(conv_csv_path.name)}</b><br>Fallos: <b>{html.escape(fail_csv_path.name)}</b><br>JSON: <b>{html.escape(json_path.name)}</b></p>
    """
    html_path.write_text(html_doc, encoding="utf-8")
    return json_path, fail_csv_path, conv_csv_path, html_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="Ej: https://hilorama-celular.onrender.com")
    ap.add_argument("--pin", default="", help="MOBILE_PIN. No lo compartas en capturas.")
    ap.add_argument("--limit", type=int, default=1000, help="Número de conversaciones a probar")
    ap.add_argument("--seed", type=int, default=6060)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", default="wa_tester_reports")
    ap.add_argument("--inventory-limit", type=int, default=700)
    ap.add_argument("--lineas-min", type=int, default=20, help="Mínimo de renglones por cotización generada")
    ap.add_argument("--lineas-max", type=int, default=80, help="Máximo de renglones por cotización generada")
    ap.add_argument("--no-debug-volumetrico", action="store_true", help="No llamar /api/envios/debug-volumetrico")
    ap.add_argument("--allow-real-write", action="store_true", help="No recomendado: permite seguir aunque no regrese tester_mode")
    args = ap.parse_args()

    print("Cargando inventario real para generar cotizaciones largas...")
    inv = load_inventory(args.base_url, args.pin, args.timeout, args.inventory_limit)
    print(f"Productos leídos: {len(inv.get('products') or [])} | Disponibles: {len(inv.get('available') or [])} | Velluto: {len(inv.get('velluto') or [])} | Komfy: {len(inv.get('komfy') or [])}")
    if inv.get("errors"):
        print("Avisos:")
        for e in inv["errors"]:
            print(" -", e)

    cases = generate_cases(args.limit, inv, args.seed, args.lineas_min, args.lineas_max)
    print(f"Ejecutando {len(cases)} conversaciones V60 contra {args.base_url}...")
    print("Recomendación: primero --limit 10, luego 50/100. El de 1000 es pesado por listas largas + envío + debug volumétrico.")

    results: List[Dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        try:
            res = run_case(
                case, args.base_url, args.pin, args.timeout, args.sleep,
                abort_if_not_tester=not args.allow_real_write,
                run_debug=not args.no_debug_volumetrico,
            )
        except Exception as exc:
            res = {
                "case_id": case.case_id,
                "category": case.category,
                "passed": False,
                "reasons": [f"EXCEPTION: {exc}"],
                "turns": [t.text for t in case.turns],
                "messages": [],
                "expected_items": case.expected_items,
                "expected_tramo_kg": case.expected_tramo_kg,
                "expected_manual": case.expected_manual,
                "cp": case.cp,
                "traceback": traceback.format_exc(),
            }
            results.append(res)
            if "tester_mode" in str(exc):
                print("\nERROR: el sitio no regresó tester_mode=true. Deteniendo para no crear datos falsos.")
                break
        else:
            results.append(res)
        status = "OK" if res.get("passed") else "FAIL"
        if i % 5 == 0 or not res.get("passed"):
            print(f"[{i}/{len(cases)}] {status} {case.case_id} {(res.get('reasons') or [''])[:1]}")

    json_path, fail_csv_path, conv_csv_path, html_path = write_reports(results, Path(args.out), inv)
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    print("\nListo.")
    print(f"Pasaron: {passed}/{total} ({(passed/total*100 if total else 0):.1f}%)")
    print(f"Reporte HTML: {html_path}")
    print(f"Fallos CSV: {fail_csv_path}")
    print(f"Conversaciones CSV: {conv_csv_path}")
    print(f"JSON completo: {json_path}")


if __name__ == "__main__":
    main()
