#!/usr/bin/env python3
"""Tester V63: conversaciones humanas dificiles para WhatsApp IA Hilorama.

Genera casos cada vez mas complejos y, si se proporciona --base-url, los ejecuta
contra /api/whatsapp-ia/simular usando siempre tester_mode=true y dry_run=true.
No crea notas, no descuenta stock, no registra pagos y no genera guias.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import whatsapp_ia_cotizacion_real_tester_v61 as v61  # noqa: E402


DEFAULT_OUT = ROOT / "wa_tester_reports"
ALNUM_FALLBACK = {
    "producto_id": 900172,
    "codigo": "172AT",
    "marca": "KARINA",
    "hilo": "FIORENTINO MAXI",
    "color": "FUCSIA",
    "stock": 50,
    "precio_venta": 52.0,
    "volumetrico": 1.0,
}


def safe(v: Any) -> str:
    return str(v or "").strip()


def qty(v: Any, default: int = 1) -> int:
    try:
        return int(float(v or default))
    except Exception:
        return default


def _pool(inv: Dict[str, Any]) -> List[Dict[str, Any]]:
    pool = []
    for key in ("hilos", "available", "velluto", "komfy", "accesorios"):
        for item in inv.get(key) or []:
            if isinstance(item, dict):
                pool.append(dict(item))
    if not pool:
        pool = [dict(x) for x in v61.DEFAULT_PRODUCTS]
    if not any(safe(x.get("codigo")).lower() == "172at" for x in pool):
        pool.append(dict(ALNUM_FALLBACK))
    seen = set()
    out = []
    for p in pool:
        k = (safe(p.get("producto_id") or p.get("id")), safe(p.get("codigo")), safe(p.get("hilo")), safe(p.get("color")))
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _line_for_item(rng: random.Random, item: Dict[str, Any], cycle: int) -> str:
    code = safe(item.get("codigo"))
    hilo = safe(item.get("hilo")) or "HILO"
    color = safe(item.get("color"))
    q = qty(item.get("cantidad"), 1)
    variants = [
        f"{code} x{q}",
        f"{code} {q}",
        f"{q} del {code}",
        f"{q} piezas {code}",
        f"{hilo} {code} x{q}",
    ]
    if cycle >= 3 and color:
        variants.extend([
            f"{q} {color} codigo {code}",
            f"{color} {code} - {q}",
        ])
    if cycle >= 4:
        variants.extend([
            f"{code} x {q}",
            f"{q} pzas {code}",
            f"{hilo.lower()} {code} x{q}",
        ])
    if cycle >= 5:
        variants.extend([
            f"#{code} * {q}",
            f"mejor {q} del {code}",
        ])
    return rng.choice(variants)


def _chunk_lines(lines: List[str], rng: random.Random, cycle: int) -> List[str]:
    chunks = []
    pos = 0
    min_chunk = 6 if cycle <= 2 else 4
    max_chunk = 18 if cycle <= 3 else 14
    while pos < len(lines):
        n = rng.randint(min_chunk, max_chunk)
        chunks.append("\n".join(lines[pos:pos + n]))
        pos += n
    labels = ["tambien:", "va otra parte:", "y estos tambien:", "me faltaron estos:"]
    return [f"{rng.choice(labels)}\n{chunk}" for chunk in chunks]


def _build_items(rng: random.Random, inv: Dict[str, Any], cycle: int, count: int) -> List[Dict[str, Any]]:
    pool = _pool(inv)
    qmax = 3 if cycle <= 2 else 5 if cycle <= 4 else 8
    items = v61.build_items_from_pool(rng, pool, count, 1, qmax)
    if cycle >= 5:
        items.append(dict(ALNUM_FALLBACK, cantidad=rng.randint(1, 3)))
    return v61.compact_expected(items)


def _case_meta(items: List[Dict[str, Any]]) -> Tuple[int | None, bool]:
    try:
        return v61.expected_tramo_for_items_volume(items)
    except Exception:
        return None, False


def generate_cases(limit: int, inv: Dict[str, Any], cycle: int, seed: int) -> List[v61.Case]:
    rng = random.Random(seed + cycle * 1009)
    cases: List[v61.Case] = []
    min_lines = {1: 20, 2: 25, 3: 35, 4: 45, 5: 80}.get(cycle, 30)
    max_lines = {1: 45, 2: 70, 3: 90, 4: 110, 5: 150}.get(cycle, 80)
    openers = v61.OPENERS + ["holaa me apoyas", "buenas, traigo una listita", "oye disculpa"]
    starts = v61.START_ORDER + [
        "me armas una cotizacion porfa",
        "te mando lista larga",
        "ocupo varios estambres",
        "quiero cotizar y luego vemos envio",
    ]
    consults = [
        "me muestras el 429 antes de pedir",
        "foto del 429 porfa",
        "que color es el 429",
        "quiero ver el 429",
        "me recomiendas algo para amigurumi",
    ]
    corrections = [
        "quita el {code}",
        "cambia el {old} por el {new}",
        "mejor que sean 5 del {code}",
    ]
    complaints = [
        "oye no me han contestado y me urge",
        "ese envio se me hace caro, hay otra opcion?",
        "ya te pague pero no tengo comprobante aqui",
    ]
    for idx in range(1, limit + 1):
        count = rng.randint(min_lines, max_lines)
        items = _build_items(rng, inv, cycle, count)
        lines = [_line_for_item(rng, it, cycle) for it in items]
        chunks = _chunk_lines(lines, rng, cycle)
        turns = [v61.Turn(rng.choice(openers)), v61.Turn(rng.choice(starts))]
        if cycle >= 3 and rng.random() < 0.45:
            turns.append(v61.Turn(rng.choice(consults)))
        turns.extend(v61.Turn(x) for x in chunks)
        final_items = list(items)
        if cycle >= 4 and final_items and rng.random() < 0.45:
            old = rng.choice(final_items)
            new = rng.choice(_pool(inv))
            code = safe(old.get("codigo"))
            text = rng.choice(corrections).format(code=code, old=code, new=safe(new.get("codigo")))
            turns.append(v61.Turn(text))
            if "quita" in text:
                final_items = [x for x in final_items if v61.item_key(x) != v61.item_key(old)]
            elif "cambia" in text:
                q = qty(old.get("cantidad"), 1)
                final_items = [x for x in final_items if v61.item_key(x) != v61.item_key(old)]
                final_items.append(dict(new, cantidad=q))
        if cycle >= 4 and rng.random() < 0.25:
            turns.append(v61.Turn(rng.choice(complaints)))
        if rng.random() < 0.35:
            turns.append(v61.Turn(rng.choice(v61.TOTAL_ASKS)))
        cp = rng.choice(v61.CP_POOL)
        turns.append(v61.Turn(rng.choice(v61.SHIP_ASKS).format(cp=cp)))
        tramo, manual = _case_meta(final_items)
        cases.append(v61.Case(
            case_id=f"v63_c{cycle}_{idx:05d}_{v61.slug(turns[-1].text)}",
            category=f"v63_ciclo_{cycle}_humano_dificil",
            turns=turns,
            expected_items=v61.compact_expected(final_items),
            cp=cp,
            expected_tramo_kg=tramo,
            expected_manual=manual,
            min_unique_ratio=0.72 if len(final_items) >= 50 else 0.80,
            min_qty_ratio=0.70 if len(final_items) >= 50 else 0.78,
            notes=f"V63 ciclo {cycle}: caso generado con listas partidas y lenguaje humano dificil.",
        ))
    return cases


def write_cases(cases: Iterable[v61.Case], out_dir: Path, cycle: int) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"wa_human_hard_cases_v63_c{cycle}_{stamp}.json"
    csv_path = out_dir / f"wa_human_hard_cases_v63_c{cycle}_{stamp}.csv"
    rows = []
    for c in cases:
        rows.append({
            "case_id": c.case_id,
            "category": c.category,
            "turns": [t.text for t in c.turns],
            "expected_items": c.expected_items,
            "cp": c.cp,
            "expected_tramo_kg": c.expected_tramo_kg,
            "expected_manual": c.expected_manual,
            "min_unique_ratio": c.min_unique_ratio,
            "min_qty_ratio": c.min_qty_ratio,
            "notes": c.notes,
        })
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "turns", "expected_items", "cp", "expected_tramo_kg", "expected_manual"])
        for row in rows:
            w.writerow([
                row["case_id"], row["category"], json.dumps(row["turns"], ensure_ascii=False),
                json.dumps(row["expected_items"], ensure_ascii=False), row["cp"],
                row["expected_tramo_kg"], row["expected_manual"],
            ])
    return json_path, csv_path


def run_cases(cases: List[v61.Case], base_url: str, pin: str, timeout: float, sleep_s: float, out_dir: Path, inv: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    for i, case in enumerate(cases, 1):
        try:
            res = v61.run_case(case, base_url, pin, timeout, sleep_s, abort_if_not_tester=True, run_debug=True)
        except Exception as exc:
            res = {
                "case_id": case.case_id,
                "category": case.category,
                "passed": False,
                "reasons": [f"EXCEPTION: {exc}"],
                "turns": [t.text for t in case.turns],
                "expected_items": case.expected_items,
                "traceback": traceback.format_exc(),
            }
        results.append(res)
        status = "OK" if res.get("passed") else "FAIL"
        print(f"[{i}/{len(cases)}] {status} {case.case_id}")
        if sleep_s:
            time.sleep(sleep_s)
    v61.write_reports(results, out_dir, inv)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="", help="Render/base URL. Si se omite, solo genera casos.")
    ap.add_argument("--pin", default="")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--cycle", type=int, default=1)
    ap.add_argument("--seed", type=int, default=6363)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--inventory-limit", type=int, default=900)
    args = ap.parse_args()

    out_dir = Path(args.out)
    if args.base_url:
        inv = v61.load_inventory(args.base_url, args.pin, args.timeout, args.inventory_limit)
    else:
        inv = {"available": v61.DEFAULT_PRODUCTS, "hilos": v61.DEFAULT_PRODUCTS, "errors": ["sin_base_url"]}
    cases = generate_cases(args.limit, inv, args.cycle, args.seed)
    json_path, csv_path = write_cases(cases, out_dir, args.cycle)
    print(f"Casos V63 generados: {len(cases)}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    if args.base_url:
        results = run_cases(cases, args.base_url, args.pin, args.timeout, args.sleep, out_dir, inv)
        passed = sum(1 for r in results if r.get("passed"))
        print(f"Resultado V63: {passed}/{len(results)} ({(passed/len(results)*100 if results else 0):.1f}%)")


if __name__ == "__main__":
    main()
