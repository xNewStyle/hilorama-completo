import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hilorama_celular.test_whatsapp_ia_v64_conversacional import (
    _inventory_v64,
    _pedido_memoria,
    _resource_callback,
    _shipping_callback,
)
from hilorama_celular.whatsapp_ia_v27 import procesar_conversacion_v27


def _norm(texto):
    texto = "" if texto is None else str(texto)
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto.lower()).strip()


BASE_CASES = [
    {
        "case_id": "audit01_multi_producto",
        "categoria": "multi_producto",
        "messages": ["hola buenas tardes manejas velluto y komfy mini?"],
        "expect": ["velluto", "komfy mini", "gama"],
        "not": ["le agrego"],
        "add": False,
        "debio": "Responder ambos productos y ofrecer gama o revisar tono.",
    },
    {
        "case_id": "audit02_suavecito",
        "categoria": "recomendacion",
        "messages": ["manejas algun hilo suavecito?"],
        "expect": ["velluto", "komfy mini", "proyecto"],
        "not": ["que codigo"],
        "add": False,
        "debio": "Recomendar hilos suaves y preguntar para que proyecto.",
    },
    {
        "case_id": "audit03_leoncito_cierre",
        "categoria": "cliente_indeciso",
        "messages": ["quiero hacer un leoncito que colores me recomiendas?"],
        "expect": ["leoncito", "camel", "fotos", "combinacion"],
        "not": ["que codigo"],
        "add": False,
        "debio": "Sugerir tonos y ofrecer fotos o combinacion.",
    },
    {
        "case_id": "audit04_fotos_no_agrega",
        "categoria": "foto_tono",
        "messages": ["me muestras el 429 y 550"],
        "expect": ["foto", "429", "550", "/static/tonos"],
        "not": ["total agregado", "le agrego"],
        "add": False,
        "debio": "Mostrar fotos/rutas sin agregar productos.",
    },
    {
        "case_id": "audit05_pedido_agrega",
        "categoria": "pedido",
        "messages": ["ponme 2 del 429 y 1 del 550"],
        "expect": ["le agrego", "429", "550", "total agregado"],
        "not": ["foto"],
        "add": True,
        "debio": "Agregar productos y cotizar.",
    },
    {
        "case_id": "audit06_cp_97000",
        "categoria": "cp_vs_codigo",
        "messages": ["oye me cotizas al codigo 97000"],
        "expect": ["codigo postal 97000", "productos", "envio"],
        "not": ["que hilo"],
        "add": False,
        "debio": "Detectar CP probable, no codigo de producto.",
    },
    {
        "case_id": "audit07_envio_sin_pedido",
        "categoria": "envio",
        "messages": ["cuanto sale el envio al 52140?"],
        "expect": ["productos", "volumen", "cp 52140"],
        "not": ["total con envio"],
        "add": False,
        "debio": "Pedir productos porque el envio depende del volumen.",
    },
    {
        "case_id": "audit08_uber",
        "categoria": "envio_local",
        "messages": ["manejan envios por uber?"],
        "expect": ["uber", "didi", "colonia"],
        "not": ["codigo postal (cp), por favor"],
        "add": False,
        "debio": "Pedir colonia o ubicacion aproximada.",
    },
    {
        "case_id": "audit09_borra_todo",
        "categoria": "cancelacion",
        "messages": ["ponme 2 del 429", "borra todo mejor"],
        "expect": ["cancelo", "cotizacion"],
        "not": ["que hilo"],
        "add": False,
        "debio": "Limpiar memoria/cotizacion activa.",
    },
    {
        "case_id": "audit10_parentesis",
        "categoria": "lista_parentesis",
        "initial_memory": {"hilo_actual": "Velluto", "estado_actual": "esperando_lista_de_colores"},
        "messages": ["2 Ocean (16)\n2 Cafe (493)\n2 Tabaco (329)"],
        "expect": ["velluto", "16", "493", "329"],
        "not": ["ojos", "mm"],
        "add": True,
        "debio": "Resolver tonos de Velluto, no accesorios.",
    },
    {
        "case_id": "audit11_typo_komfy",
        "categoria": "ortografia",
        "messages": ["tndrs komfi mini kolor kfe?"],
        "expect": ["komfy mini", "cafe", "disponible"],
        "not": ["que hilo"],
        "add": False,
        "debio": "Entender Komfy Mini color cafe y responder humano.",
    },
    {
        "case_id": "audit12_mayoreo",
        "categoria": "mayoreo",
        "messages": ["tienes precio de mayoreo?"],
        "expect": ["cantidad", "piezas", "reviso"],
        "not": ["te doy", "descuento del"],
        "add": False,
        "debio": "Pedir cantidad sin inventar regla de mayoreo.",
    },
    {
        "case_id": "audit13_mejor_precio_competencia",
        "categoria": "descuento",
        "messages": ["me puedes mejorar precio? en otra tienda esta mas barato"],
        "expect": ["reviso", "mejor opcion", "cuantas piezas"],
        "not": ["te igualo", "te doy"],
        "add": False,
        "debio": "Retener venta sin prometer descuento.",
    },
    {
        "case_id": "audit14_economico",
        "categoria": "recomendacion",
        "messages": ["quiero algo bonito pero economico"],
        "expect": ["economica", "proyecto"],
        "not": ["que codigo"],
        "add": False,
        "debio": "Sugerir segun uso sin inventar precio.",
    },
    {
        "case_id": "audit15_pegado_alize",
        "categoria": "mensaje_pegado",
        "messages": [
            "[10:23 a.m.] +52 1 786 123 3345: Y la dinamica\n"
            "[10:23 a.m.] +52 1 786 123 3345: Pronto me pongo en contacto para hacer pedido\n"
            "[10:23 a.m.] +52 1 786 123 3345: Gracias!\n"
            "[10:23 a.m.] +52 1 786 123 3345: Disculpe y Alize de este no maneja?"
        ],
        "expect": ["alize", "velluto", "foto", "nombre"],
        "not": ["mandeme la lista"],
        "add": False,
        "debio": "Limpiar ruido y responder la ultima intencion util.",
    },
    {
        "case_id": "audit16_bebe",
        "categoria": "bebe",
        "messages": ["quiero hacer una cobijita de bebe que hilo me recomiendas?"],
        "expect": ["bebe", "velluto", "komfy mini"],
        "not": ["que codigo"],
        "add": False,
        "debio": "Recomendar hilos suaves para bebe sin inventar ficha.",
    },
    {
        "case_id": "audit17_productono",
        "categoria": "producto_no_manejado",
        "messages": ["manejas estambre la abuelita?"],
        "expect": ["no la manejamos", "opciones parecidas"],
        "not": ["producto no encontrado"],
        "add": False,
        "debio": "Decir que no se maneja y ofrecer alternativas.",
    },
    {
        "case_id": "audit18_reclamo",
        "categoria": "reclamo",
        "messages": ["oye me llego mal un tono y estoy molesta"],
        "expect": ["revisarlo", "datos", "pedido"],
        "not": ["que hilo", "te cambio"],
        "add": False,
        "debio": "Calmar, pedir datos/evidencia y no prometer cambio.",
    },
    {
        "case_id": "audit19_gama_a_pedido",
        "categoria": "gama_a_pedido",
        "messages": ["me pasas la gama de velluto", "me gusto el 429 ponme 3"],
        "expect": ["le agrego", "429", "x3"],
        "not": ["dejeme revisarlo"],
        "add": True,
        "debio": "Convertir gusto por tono en pedido real con cantidad.",
    },
    {
        "case_id": "audit20_cierre_cp",
        "categoria": "cotizacion_envio",
        "messages": ["ponme 2 del 429", "mi cp es 52140"],
        "expect": ["subtotal", "total con productos"],
        "not": ["necesito saber que productos"],
        "add": True,
        "debio": "Cotizar envio sobre pedido acumulado.",
    },
]


EXTRA_TEMPLATES = [
    ("foto_condicional", ["me muestras el 429 y si me gusta te pido 3"], ["foto", "429"], ["le agrego"], False),
    ("precio_velluto", ["cuanto cuesta el velluto?"], ["velluto", "madeja"], ["precio por confirmar"], False),
    ("peluche", ["ocupo hilo para peluche"], ["peluche", "velluto", "komfy mini"], ["que codigo"], False),
    ("gama", ["me pasas la gama de velluto"], ["gama", "/static/gama"], ["le agrego"], False),
    ("disponibilidad", ["tienes el 429?"], ["429", "disponible"], ["total agregado"], False),
    ("pedido_simple", ["quiero 2 del 429"], ["le agrego", "429"], ["foto"], True),
    ("correccion", ["ponme 2 del 429 y 1 del 550", "mejor quita el 550 y ponme otro 429"], ["quito el codigo 550", "429"], ["quedan 0"], True),
    ("cancelar", ["ponme 2 del 429", "empecemos de nuevo borra todo"], ["cancelo", "cotizacion"], ["que hilo"], False),
    ("uber_largo", ["hola, si compro hoy pueden mandar por didi?"], ["uber", "didi", "colonia"], ["codigo postal (cp), por favor"], False),
    ("cp_sin_pedido", ["me cotizas al codigo 97000 porfa"], ["codigo postal 97000", "productos"], ["que hilo"], False),
]


def _build_cases(limit):
    cases = [dict(c) for c in BASE_CASES]
    i = 0
    while len(cases) < limit:
        cat, messages, expect, not_words, add = EXTRA_TEMPLATES[i % len(EXTRA_TEMPLATES)]
        cases.append({
            "case_id": f"auto_{len(cases)+1:04d}_{cat}_{i}",
            "categoria": cat,
            "messages": list(messages),
            "expect": list(expect),
            "not": list(not_words),
            "add": bool(add),
            "debio": "Caso automatico humano de auditoria conversacional V64.",
        })
        i += 1
    return cases[:limit]


def _run_case(case, products):
    memoria = dict(case.get("initial_memory") or {})
    turns = []
    for msg in case.get("messages") or []:
        before = dict(memoria)
        response = procesar_conversacion_v27(
            {"texto": msg, "tester_mode": True, "dry_run": True},
            products,
            memoria=memoria,
            callbacks={"buscar_recurso": _resource_callback, "cotizar_envio": _shipping_callback},
        )
        after = response.get("memoria") or {}
        turns.append({
            "mensaje_cliente": msg,
            "respuesta_agente": response.get("respuesta") or "",
            "intencion_detectada": response.get("intencion") or {},
            "productos_detectados": (response.get("resolucion") or {}).get("pedidos") or [],
            "agrego_productos": bool(_pedido_memoria(after)),
            "requiere_humano": bool(response.get("requiere_humano")),
            "decision_pendiente": response.get("decision_pendiente") or {},
            "memoria_antes": before,
            "memoria_despues": after,
        })
        memoria = after

    final = turns[-1]
    text = _norm(final["respuesta_agente"])
    fallos = []
    for expected in case.get("expect") or []:
        if _norm(expected) not in text:
            fallos.append(f"falta frase/idea: {expected}")
    for forbidden in case.get("not") or []:
        if _norm(forbidden) in text:
            fallos.append(f"contiene frase prohibida: {forbidden}")
    has_order = bool(_pedido_memoria(final["memoria_despues"]))
    if case.get("add") and not has_order:
        fallos.append("debio dejar productos en memoria")
    if not case.get("add") and has_order:
        fallos.append("no debio dejar productos en memoria")

    return {
        "case_id": case.get("case_id"),
        "categoria": case.get("categoria"),
        "turns": turns,
        "que_debio_responder": case.get("debio") or "",
        "fallo_agente": bool(fallos),
        "fallo_tester": False,
        "fallos": fallos,
        "archivo_probable": "hilorama_celular/whatsapp_ia_v27.py" if fallos else "",
        "funcion_probable": "detectar_intencion/generar_respuesta_vendedora/detectar_decision_pendiente" if fallos else "",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--cycle", type=int, default=1)
    parser.add_argument("--out-dir", default="wa_tester_reports")
    args = parser.parse_args()

    products = _inventory_v64()
    results = [_run_case(case, products) for case in _build_cases(args.limit)]
    summary = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "ciclo": args.cycle,
        "modo": "local tester_mode=true dry_run=true",
        "total": len(results),
        "pasaron": sum(1 for r in results if not r["fallo_agente"]),
        "fallaron": sum(1 for r in results if r["fallo_agente"]),
        "results": results,
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"v64_auditoria_vendedora_ciclo{args.cycle}_{args.limit}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("ciclo", "total", "pasaron", "fallaron")}, ensure_ascii=False))
    print(str(out))
    if summary["fallaron"]:
        for r in results:
            if r["fallo_agente"]:
                print("FAIL", r["case_id"], "|", "; ".join(r["fallos"]))
    raise SystemExit(1 if summary["fallaron"] else 0)


if __name__ == "__main__":
    main()
