#!/usr/bin/env python3
"""
Tester masivo V34 para el agente WhatsApp IA de Hilorama.

Uso recomendado:
  python tools/whatsapp_ia_mass_tester_v34.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100
  python tools/whatsapp_ia_mass_tester_v34.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.2

Para 10,000 pruebas:
  python tools/whatsapp_ia_mass_tester_v34.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 10000 --sleep 0.1

IMPORTANTE: requiere V34/V33/V31/V30 en el servidor porque usa tester_mode/dry_run para NO guardar conversaciones reales.
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
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

FORBIDDEN_PUBLIC_PHRASES = [
    "confianza baja",
    "confianza media",
    "parser",
    "no ubiqué",
    "no ubique",
    "revisar códigos",
    "revisar codigos",
    "código aparece en varios hilos",
    "codigo aparece en varios hilos",
    "advertencias",
    "errores",
    "interno",
    "apartado",
    "apartar",
    "aparto",
    "aparta",
    "le aparto",
]

PRODUCTS = [
    {"marca": "ALIZE", "hilo": "VELLUTO", "aliases": ["Velluto", "Veluto", "Belluto", "Alize Velluto"], "price_q": ["cuánto cuesta", "precio", "en cuanto esta"], "codes": [("55", "BLANCO"), ("56", "ROJO"), ("60", "NEGRO"), ("429", "CAMEL"), ("532", "ARENA"), ("216", "CANARIO"), ("493", "CAFE OSCURO"), ("550", "MANDARINA")], "colors": ["blanco", "rojo", "negro", "camel", "arena", "canario"]},
    {"marca": "KARINA", "hilo": "KOMFY MINI", "aliases": ["Komfy Mini", "Konfy Mini", "Comfy Mini", "Komfi Mini"], "price_q": ["cuánto cuesta", "precio"], "codes": [("01", "BLANCO"), ("06", "CIELO"), ("08", "TURQUESA"), ("14", "ROSA BEBE"), ("20", "LILA"), ("99", "NEGRO")], "colors": ["blanco", "cielo", "turquesa", "rosa bebe", "lila", "negro"]},
]

TYPO_PHRASES = [
    "buenas trades",
    "me gustaria hacer un pwdido",
    "me cotiiza",
    "me manda las ganas de colores",
    "aun vigenete",
    "porfavro",
    "me puede cotisar",
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
    expect: Dict[str, Any] = field(default_factory=dict)


def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()[:80]


def generate_cases(limit: int, seed: int = 1234) -> List[Case]:
    rng = random.Random(seed)
    cases: List[Case] = []

    def add(category: str, turns: List[str] | List[Turn], expect: Dict[str, Any]):
        idx = len(cases) + 1
        t_objs = [t if isinstance(t, Turn) else Turn(t) for t in turns]
        cases.append(Case(f"{idx:05d}_{category}_{slug(t_objs[-1].text)}", category, t_objs, expect))

    # Casos fijos importantes
    add("manejan_producto", ["¿Manejan Komfy Mini?"], {"must_contain_any": ["komfy"], "should_answer_yes": True, "must_not_ask_code": True})
    add("stock_color", ["¿Tienen Velluto blanco?"], {"must_contain_any": ["velluto", "blanco", "55"], "should_answer_yes": True, "no_similar_for_exact": True})
    add("pedido_cantidad_codigo", ["hola buenas tardes quiero cotizar un pedido de velluto son 15 madejas", "5 del 55 y 10 del 60"], {"expected_items": [{"codigo": "55", "cantidad": 5}, {"codigo": "60", "cantidad": 10}], "must_contain_any": ["15", "cotiz"]})
    add("pedido_lista", ["me puede poner esta lista\n550 x2\n493\n216 canario - 4\nBlanco 01- 2\nRojo escolar- 2\nHueso 26- 1", "todo sería velluto"], {"expected_items_any": ["550", "493", "216"], "must_contain_any": ["velluto", "cotiz"]})
    add("lista_codigos", ["quiero hacer pedido de Velluto", "60\n310\n107\n329\n466\n26\n87\n428\n13\n31"], {"expected_items_any": ["60", "310", "107"], "must_contain_any": ["cotiz", "agrego", "lista"]})
    add("envio_sin_cp", ["¿cuánto sale el envío?"], {"must_contain_any": ["código postal", "cp"]})
    add("envio_con_cp", ["quiero cotizar envío", "mi cp es 97000"], {"must_contain_any": ["97000", "envío", "revis"]})
    add("pago", ["ya quedó el pago"], {"must_contain_any": ["comprobante", "revis"]})
    add("descuento_humano", ["si compro 5 madejas me mejora el precio?"], {"must_contain_any": ["revis", "confirm"], "must_not_contain_any": ["se lo dejo", "$55", "$54", "descuento aprobado"]})
    add("producto_no_manejado", ["¿Manejan La Abuelita?"], {"must_contain_any": ["por el momento", "manej", "opci", "kurumi", "komfy"]})
    add("typo", ["buenas trades, me gustaria hacer un pwdido de belluto", "5 del 55 y 10 del 60"], {"expected_items": [{"codigo": "55", "cantidad": 5}, {"codigo": "60", "cantidad": 10}], "must_contain_any": ["velluto", "cotiz"]})
    add("tono_foto", ["me muestra el tono 429 de velluto"], {"must_contain_any": ["429"], "photo_intent": True})
    add("gama", ["me manda la gama de colores de velluto"], {"must_contain_any": ["gama", "velluto"]})
    add("correccion", ["quiero 5 del 55 y 10 del 60", "perdón, mejor solo 3 del 55", "quite el 60"], {"must_contain_any": ["55", "60", "quito", "corrijo", "actualiz"]})

    templates = [
        "Hola, ¿{precio} el {hilo}?",
        "¿Manejan {hilo}?",
        "¿Me manda la gama de {hilo}?",
        "¿Tiene {hilo} {color}?",
        "Me puede poner {cant} del {codigo}",
        "Quiero {cant} {color} de {hilo}",
        "Me cotiza {cant1} del {codigo1} y {cant2} del {codigo2}",
        "Buenas tardes le paso la lista de colores porfavor\n{codigo1}\n{codigo2}\n{codigo3}",
        "{typo} de {hilo}\n{cant1} del {codigo1} y {cant2} del {codigo2}",
    ]
    while len(cases) < limit:
        prod = rng.choice(PRODUCTS)
        c1, c2, c3 = rng.sample(prod["codes"], 3)
        cant = rng.randint(1, 12)
        cant1 = rng.randint(1, 8)
        cant2 = rng.randint(1, 8)
        template = rng.choice(templates)
        hilo_alias = rng.choice(prod["aliases"])
        color = rng.choice(prod["colors"])
        text = template.format(
            precio=rng.choice(prod["price_q"]), hilo=hilo_alias, color=color,
            cant=cant, cant1=cant1, cant2=cant2,
            codigo=c1[0], codigo1=c1[0], codigo2=c2[0], codigo3=c3[0],
            typo=rng.choice(TYPO_PHRASES),
        )
        expect: Dict[str, Any] = {"must_not_crash": True}
        if "Manejan" in text:
            expect.update({"must_contain_any": [prod["hilo"].lower().split()[0]], "should_answer_yes": True})
            category = "generado_manejan"
        elif "gama" in text:
            expect.update({"must_contain_any": ["gama", prod["hilo"].lower().split()[0]]})
            category = "generado_gama"
        elif "cotiza" in text or "poner" in text or "lista" in text or "pwdido" in text:
            expect.update({"must_contain_any": ["cotiz", "agrego", "lista", "pedido"], "no_technical": True})
            category = "generado_pedido"
        elif "Tiene" in text:
            expect.update({"must_contain_any": [color.split()[0]], "no_similar_for_exact": True})
            category = "generado_stock"
        else:
            expect.update({"must_contain_any": [prod["hilo"].lower().split()[0]]})
            category = "generado_general"
        add(category, [text], expect)
    return cases[:limit]


def post_json(url: str, payload: Dict[str, Any], pin: str, timeout: float = 45.0) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if pin:
        req.add_header("X-Mobile-Pin", pin)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    return json.loads(data)


def text_norm(s: str) -> str:
    return (s or "").lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


def collect_items(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for key in ("pedidos",):
        val = resp.get(key) or []
        if isinstance(val, list):
            items.extend(x for x in val if isinstance(x, dict))
    parser = resp.get("parser") or {}
    for key in ("pedidos", "items_lista_v27", "items_lista_v17"):
        val = parser.get(key) or []
        if isinstance(val, list):
            items.extend(x for x in val if isinstance(x, dict))
    return items


def item_matches(items: List[Dict[str, Any]], codigo: str, cantidad: Optional[int] = None) -> bool:
    for it in items:
        code = str(it.get("codigo") or it.get("code") or it.get("sku") or it.get("tono") or "")
        qty_raw = it.get("cantidad") if "cantidad" in it else it.get("qty")
        try:
            qty = int(float(qty_raw)) if qty_raw is not None and str(qty_raw) else None
        except Exception:
            qty = None
        if code == str(codigo) and (cantidad is None or qty == int(cantidad)):
            return True
    return False


def grade_case(case: Case, final_resp: Dict[str, Any], all_resps: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    text = final_resp.get("respuesta_sugerida") or final_resp.get("respuesta_diferida") or ""
    tn = text_norm(text)
    if not final_resp.get("ok"):
        reasons.append("respuesta ok=false")
    if not final_resp.get("tester_mode"):
        reasons.append("NO está en tester_mode; se debe desplegar V30 o abortar para no ensuciar datos")
    for bad in FORBIDDEN_PUBLIC_PHRASES:
        if text_norm(bad) in tn:
            reasons.append(f"respuesta contiene frase interna/prohibida: {bad}")
    exp = case.expect or {}
    if exp.get("should_answer_yes"):
        if not any(w in tn for w in ["si", "sí", "manejamos", "tenemos", "claro"]):
            reasons.append("debería responder afirmativamente")
    if exp.get("must_not_ask_code"):
        if "codigo" in tn or "código" in tn or "tono" in tn:
            if not any(w in tn for w in ["gama", "color", "especial"]):
                reasons.append("preguntó código/tono donde debía contestar si maneja el producto")
    if exp.get("no_similar_for_exact"):
        if "opciones parecidas" in tn or "parecid" in tn:
            reasons.append("ofreció parecidos aunque la consulta era de color exacto")
    # must_contain_any significa que basta con UNO de los textos esperados.
    # En versiones anteriores se evaluaba como si todos fueran obligatorios y generaba falsos fallos.
    must_any = exp.get("must_contain_any", []) or []
    if must_any:
        flat = []
        for phrase in must_any:
            if isinstance(phrase, (list, tuple, set)):
                flat.extend(str(x) for x in phrase)
            else:
                flat.append(str(phrase))
        if not any(text_norm(part) in tn for part in flat):
            reasons.append("no contiene ninguno de los esperados: " + ", ".join(flat[:8]))
    for phrase in exp.get("must_not_contain_any", []) or []:
        if text_norm(phrase) in tn:
            reasons.append(f"contiene algo que no debía: {phrase}")
    items = collect_items(final_resp)
    for exp_item in exp.get("expected_items", []) or []:
        if not item_matches(items, exp_item["codigo"], exp_item.get("cantidad")):
            reasons.append(f"no detectó item esperado: {exp_item}")
    for code in exp.get("expected_items_any", []) or []:
        if not item_matches(items, str(code), None) and str(code) not in tn:
            reasons.append(f"no detectó/mencionó código esperado: {code}")
    # Coherencia mínima: respuesta vacía o demasiado corta, excepto cierres diferidos.
    if len(text.strip()) < 8 and not final_resp.get("respuesta_diferida"):
        reasons.append("respuesta demasiado corta o vacía")
    return (len(reasons) == 0), reasons


def run_case(case: Case, base_url: str, pin: str, timeout: float, sleep_s: float, abort_if_not_tester: bool) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/api/whatsapp-ia/simular"
    memoria: Dict[str, Any] = {}
    conversacion_id = f"TEST-{case.case_id}"
    responses: List[Dict[str, Any]] = []
    for idx, turn in enumerate(case.turns):
        payload = {
            "texto": turn.text,
            "marca": turn.marca,
            "hilo": turn.hilo,
            "cliente_nombre": "Tester Hilorama",
            "telefono": f"TEST-{case.case_id}",
            "conversacion_id": conversacion_id,
            "nueva_conversacion": idx == 0,
            "tester_mode": True,
            "dry_run": True,
            "memoria": memoria,
        }
        resp = post_json(url, payload, pin, timeout=timeout)
        if abort_if_not_tester and not resp.get("tester_mode"):
            raise RuntimeError("El servidor no regresó tester_mode=true. Sube V30 antes de correr pruebas masivas para no guardar datos falsos.")
        responses.append(resp)
        memoria = resp.get("memoria_actual") or memoria
        if sleep_s:
            time.sleep(sleep_s)
    final = responses[-1] if responses else {}
    passed, reasons = grade_case(case, final, responses)
    return {
        "case_id": case.case_id,
        "category": case.category,
        "passed": passed,
        "reasons": reasons,
        "turns": [t.text for t in case.turns],
        "final_response": final.get("respuesta_sugerida") or final.get("respuesta_diferida") or "",
        "intencion": final.get("intencion"),
        "confianza": final.get("confianza"),
        "accion": final.get("accion_recomendada"),
        "pedidos": collect_items(final),
        "raw_final": final,
    }


def write_reports(results: List[Dict[str, Any]], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"wa_test_results_{stamp}.json"
    csv_path = out_dir / f"wa_test_failures_{stamp}.csv"
    html_path = out_dir / f"wa_test_report_{stamp}.html"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "reasons", "turns", "response", "intencion", "confianza", "accion"])
        for r in results:
            if not r["passed"]:
                w.writerow([r["case_id"], r["category"], " | ".join(r["reasons"]), " || ".join(r["turns"]), r["final_response"], r.get("intencion"), r.get("confianza"), r.get("accion")])
    total = len(results); passed = sum(1 for r in results if r["passed"]); failed = total - passed
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
            failures.append(f"<details><summary><b>{html.escape(r['case_id'])}</b> - {html.escape(r['category'])}</summary><p><b>Razones:</b> {html.escape(' | '.join(r['reasons']))}</p><p><b>Turnos:</b><br>{'<br>'.join(html.escape(t) for t in r['turns'])}</p><p><b>Respuesta:</b><br>{html.escape(r['final_response'])}</p><pre>{html.escape(json.dumps(r.get('pedidos') or [], ensure_ascii=False, indent=2))}</pre></details>")
    html_doc = f"""<!doctype html><meta charset='utf-8'><title>WA IA Tester Hilorama</title>
    <style>body{{font-family:Arial,sans-serif;margin:24px}} table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px 10px}} details{{margin:12px 0;padding:10px;border:1px solid #ddd;border-radius:8px}} .bad{{color:#b00020}} .ok{{color:#067d2f}}</style>
    <h1>Reporte tester WhatsApp IA Hilorama V34</h1>
    <p>Total: <b>{total}</b> | Pasaron: <b class='ok'>{passed}</b> | Fallaron: <b class='bad'>{failed}</b> | Efectividad: <b>{(passed/total*100 if total else 0):.1f}%</b></p>
    <h2>Por categoría</h2><table><tr><th>Categoría</th><th>Pasaron</th><th>%</th></tr>{''.join(rows)}</table>
    <h2>Fallos</h2>{''.join(failures[:500])}<p>Mostrando máximo 500 fallos en HTML. Ver CSV/JSON para todo.</p>"""
    html_path.write_text(html_doc, encoding="utf-8")
    return json_path, csv_path, html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="Ej: https://hilorama-celular.onrender.com")
    ap.add_argument("--pin", default="", help="MOBILE_PIN. Mejor usar variable env o pegarlo aquí solo localmente.")
    ap.add_argument("--limit", type=int, default=100, help="Número de casos a generar/probar")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--sleep", type=float, default=0.15, help="Pausa entre requests para no saturar Render/OpenAI")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default="wa_tester_reports")
    ap.add_argument("--allow-real-write", action="store_true", help="No recomendado: permite seguir aunque el servidor no tenga tester_mode")
    args = ap.parse_args()

    cases = generate_cases(args.limit, args.seed)
    results: List[Dict[str, Any]] = []
    print(f"Ejecutando {len(cases)} casos contra {args.base_url}...")
    print("Recomendación: primero 50-100. Para 10,000 puede gastar OpenAI y tardar bastante.")
    for i, case in enumerate(cases, 1):
        try:
            res = run_case(case, args.base_url, args.pin, args.timeout, args.sleep, abort_if_not_tester=not args.allow_real_write)
        except Exception as exc:
            res = {"case_id": case.case_id, "category": case.category, "passed": False, "reasons": [f"EXCEPTION: {exc}"], "turns": [t.text for t in case.turns], "final_response": "", "traceback": traceback.format_exc()}
            if "tester_mode" in str(exc):
                print("\nERROR: el sitio no tiene V30 tester_mode. Deteniendo para no crear datos falsos.")
                results.append(res)
                break
        results.append(res)
        status = "OK" if res["passed"] else "FAIL"
        if i % 10 == 0 or not res["passed"]:
            print(f"[{i}/{len(cases)}] {status} {case.case_id} {res.get('reasons','')[:1]}")
    json_path, csv_path, html_path = write_reports(results, Path(args.out))
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print("\nListo.")
    print(f"Pasaron: {passed}/{total} ({(passed/total*100 if total else 0):.1f}%)")
    print(f"Reporte HTML: {html_path}")
    print(f"Fallos CSV: {csv_path}")
    print(f"JSON completo: {json_path}")

if __name__ == "__main__":
    main()
