#!/usr/bin/env python3
"""Investigacion y retroalimentacion controlada V63 para Hilorama.

No busca precios internos y no publica datos tecnicos sin validacion. Este modulo
administra aprendizaje_vendedor_hilorama.json y puede dejar solicitudes pendientes
para revisar en fuentes oficiales.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "hilorama_celular" / "data" / "conocimiento_hilos"
LEARNING_PATH = DATA_DIR / "aprendizaje_vendedor_hilorama.json"
HIST_PATH = ROOT / "hilorama_celular" / "data" / "test_cases" / "fallos_historicos_hilorama_v63.jsonl"


def now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def load_learning() -> Dict[str, Any]:
    if not LEARNING_PATH.exists():
        return {
            "version": "v63",
            "politica": {
                "usar_para_cliente_solo_si_validado": True,
                "no_usar_para_precios_hilorama": True,
            },
            "aprendizajes": [],
        }
    return json.loads(LEARNING_PATH.read_text(encoding="utf-8"))


def save_learning(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEARNING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def add_learning(args: argparse.Namespace) -> Dict[str, Any]:
    data = load_learning()
    aprendizajes: List[Dict[str, Any]] = data.setdefault("aprendizajes", [])
    entry = {
        "id": f"apr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(aprendizajes)+1}",
        "fecha": now(),
        "producto": args.producto or "",
        "dato_aprendido": args.dato or "",
        "fuente": args.fuente or "",
        "url": args.url or "",
        "nivel_confianza": args.confianza or "pendiente",
        "puede_usarse_en_respuesta_cliente": bool(args.validado),
        "estado": "validado" if args.validado else "pendiente de validar",
        "notas": args.notas or "",
    }
    aprendizajes.append(entry)
    save_learning(data)
    return entry


def queue_research(args: argparse.Namespace) -> Dict[str, Any]:
    data = load_learning()
    pendientes = data.setdefault("pendientes_investigacion", [])
    entry = {
        "id": f"pend_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(pendientes)+1}",
        "fecha": now(),
        "producto": args.producto or "",
        "pregunta": args.pregunta or args.dato or "",
        "fuentes_preferidas": ["Karina", "Alize", "fabricante", "proveedor oficial"],
        "estado": "pendiente de validar",
        "no_usar_para_cliente": True,
    }
    pendientes.append(entry)
    save_learning(data)
    return entry


def list_pending() -> List[Dict[str, Any]]:
    data = load_learning()
    return data.get("pendientes_investigacion") or []


def ingest_failures(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    results = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(results, dict):
        results = results.get("results") or []
    failures = [r for r in results if isinstance(r, dict) and not r.get("passed")]
    categories: Dict[str, int] = {}
    for r in failures:
        categories[r.get("category") or "sin_categoria"] = categories.get(r.get("category") or "sin_categoria", 0) + 1
        append_jsonl(HIST_PATH, {
            "case_id": r.get("case_id"),
            "source": str(path),
            "category": r.get("category"),
            "status": "fallo_real_pendiente",
            "fecha": now(),
            "reasons": r.get("reasons") or [],
            "turns": r.get("turns") or [],
            "expected_items": r.get("expected_items") or [],
            "cp": r.get("cp") or "",
        })
    return {"total_fallos": len(failures), "categorias": categories}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-learning", action="store_true", help="Agregar aprendizaje manual.")
    ap.add_argument("--queue-research", action="store_true", help="Guardar una duda pendiente de validar.")
    ap.add_argument("--list-pending", action="store_true", help="Mostrar investigaciones pendientes.")
    ap.add_argument("--ingest-failure-json", default="", help="Agregar fallos de un JSON de tester al historial.")
    ap.add_argument("--producto", default="")
    ap.add_argument("--dato", default="")
    ap.add_argument("--pregunta", default="")
    ap.add_argument("--fuente", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--confianza", default="pendiente")
    ap.add_argument("--validado", action="store_true")
    ap.add_argument("--notas", default="")
    args = ap.parse_args()

    if args.add_learning:
        print(json.dumps(add_learning(args), ensure_ascii=False, indent=2))
        return
    if args.queue_research:
        print(json.dumps(queue_research(args), ensure_ascii=False, indent=2))
        return
    if args.list_pending:
        print(json.dumps(list_pending(), ensure_ascii=False, indent=2))
        return
    if args.ingest_failure_json:
        print(json.dumps(ingest_failures(Path(args.ingest_failure_json)), ensure_ascii=False, indent=2))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
