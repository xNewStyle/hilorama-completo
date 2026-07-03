#!/usr/bin/env python3
"""Auto-loop controlado V63 para WhatsApp IA Hilorama.

Este script no edita codigo por si solo. Orquesta ciclos seguros:
- compila,
- corre regresion local,
- ejecuta testers remotos en tester_mode/dry_run,
- agrega fallos a regresion/historial,
- genera reportes y resumen,
- se detiene si baja la regresion o no cumple la meta.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "hilorama_celular" / "tools"
REPORT_DIR = ROOT / "wa_tester_reports"
REGRESSION_PATH = ROOT / "hilorama_celular" / "data" / "test_cases" / "regresion_hilorama_v63.jsonl"
HISTORY_PATH = ROOT / "hilorama_celular" / "data" / "test_cases" / "fallos_historicos_hilorama_v63.jsonl"
SUMMARY_PATH = REPORT_DIR / "ultimo_resumen_auto_loop.txt"
NOTIFY_PATH = REPORT_DIR / "notificacion_auto_loop.txt"

V61_TESTER = TOOLS / "whatsapp_ia_cotizacion_real_tester_v61.py"
HARD_TESTER = TOOLS / "whatsapp_ia_human_hard_tester_v63.py"

GOALS = {1: 97.0, 2: 98.0, 3: 98.5, 4: 99.0, 5: 99.0}
SUCCESS_STREAK_REQUIRED = 3


def now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def run_cmd(args: List[str], timeout: int = 1800) -> Tuple[int, str]:
    proc = subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout


def latest_result_json() -> Path | None:
    files = sorted(REPORT_DIR.glob("wa_quote_real_test_results_v61_*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load_results(path: Path | None) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("results") or []
    return [x for x in data if isinstance(x, dict)]


def stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    categories: Dict[str, int] = {}
    for r in results:
        if not r.get("passed"):
            cat = r.get("category") or "sin_categoria"
            categories[cat] = categories.get(cat, 0) + 1
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "effectiveness": (passed / total * 100.0) if total else 0.0,
        "failed_categories": categories,
    }


def failure_keys(results: List[Dict[str, Any]]) -> set[str]:
    keys = set()
    for r in results:
        if r.get("passed"):
            continue
        case_id = str(r.get("case_id") or "").strip()
        category = str(r.get("category") or "sin_categoria").strip()
        reasons = "|".join(str(x).strip() for x in (r.get("reasons") or [])[:3])
        keys.add(case_id or f"{category}:{reasons}")
    return keys


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def existing_regression_ids() -> set[str]:
    if not REGRESSION_PATH.exists():
        return set()
    ids = set()
    for line in REGRESSION_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("case_id"):
            ids.add(str(obj["case_id"]))
    return ids


def append_failures(results: List[Dict[str, Any]], cycle: int, source: str) -> int:
    failures = [r for r in results if not r.get("passed")]
    known = existing_regression_ids()
    added = 0
    for r in failures:
        row = {
            "case_id": r.get("case_id"),
            "source": source,
            "cycle": cycle,
            "category": r.get("category"),
            "status": "fallo_real_pendiente",
            "fecha": now(),
            "reasons": r.get("reasons") or [],
            "turns": r.get("turns") or [],
            "expected_items": r.get("expected_items") or [],
            "cp": r.get("cp") or "",
            "expected_tramo_kg": r.get("expected_tramo_kg"),
            "expected_manual": r.get("expected_manual"),
        }
        append_jsonl(HISTORY_PATH, row)
        cid = str(row.get("case_id") or "")
        if cid and cid not in known:
            append_jsonl(REGRESSION_PATH, row)
            known.add(cid)
            added += 1
    return added


def compile_check() -> Tuple[bool, str]:
    files = [
        "hilorama_celular/whatsapp_ia_v27.py",
        "hilorama_celular/app.py",
        "hilorama_celular/tools/whatsapp_ia_auto_loop_v63.py",
        "hilorama_celular/tools/whatsapp_ia_human_hard_tester_v63.py",
        "hilorama_celular/tools/whatsapp_ia_feedback_research_v63.py",
    ]
    code, out = run_cmd([sys.executable, "-m", "py_compile", *files], timeout=300)
    return code == 0, out


def regression_check() -> Tuple[bool, str]:
    code, out = run_cmd([
        sys.executable,
        "-m",
        "unittest",
        "hilorama_celular.test_whatsapp_ia_v61_real_failures",
        "hilorama_celular.test_whatsapp_ia_v63_regression",
        "-v",
    ], timeout=900)
    return code == 0, out


def cycle_limit(cycle: int, start_limit: int, max_limit: int) -> int:
    if cycle <= 1:
        return start_limit
    if cycle == 2:
        return min(max_limit, max(300, start_limit))
    return max_limit


def run_cycle_tester(args: argparse.Namespace, cycle: int, limit: int) -> Tuple[int, str, Path | None]:
    before = latest_result_json()
    if cycle == 1:
        cmd = [
            sys.executable, str(V61_TESTER),
            "--base-url", args.base_url,
            "--pin", args.pin,
            "--limit", str(limit),
            "--sleep", str(args.sleep),
            "--timeout", str(args.timeout),
            "--out", str(REPORT_DIR),
        ]
    else:
        cmd = [
            sys.executable, str(HARD_TESTER),
            "--base-url", args.base_url,
            "--pin", args.pin,
            "--limit", str(limit),
            "--cycle", str(cycle),
            "--sleep", str(args.sleep),
            "--timeout", str(args.timeout),
            "--out", str(REPORT_DIR),
        ]
    code, out = run_cmd(cmd, timeout=max(1200, int(args.timeout * max(limit, 1) + 600)))
    after = latest_result_json()
    if after == before:
        # El tester V63 tambien usa write_reports de V61, asi que debe crear wa_quote_real...
        after = latest_result_json()
    return code, out, after


def has_safety_failure(results: List[Dict[str, Any]], output: str) -> str:
    text = (output or "").lower()
    if "tester_mode" in text and ("deteniendo" in text or "no regreso" in text or "no regres" in text):
        return "Render no regreso tester_mode=true o parece version vieja."
    for r in results:
        for reason in r.get("reasons") or []:
            rn = str(reason).lower()
            if "tester_mode" in rn or "ok=false" in rn or "exception" in rn:
                return "Hay error de servidor, tester_mode o excepcion en resultados."
    return ""


def write_cycle_summary(cycle: int, limit: int, goal: float, result_path: Path | None, results: List[Dict[str, Any]], added: int, status: str, modified_files: List[str], output_tail: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    st = stats(results)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = REPORT_DIR / f"auto_loop_v63_ciclo_{cycle}_{stamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    html_path = base.with_suffix(".html")
    txt_path = base.with_suffix(".txt")
    payload = {
        "cycle": cycle,
        "limit": limit,
        "goal": goal,
        "status": status,
        "result_path": str(result_path or ""),
        "stats": st,
        "failures_added_to_regression": added,
        "modified_files": modified_files,
        "output_tail": output_tail[-6000:],
        "fecha": now(),
        "safety": {
            "tester_mode": True,
            "dry_run": True,
            "no_notas_reales": True,
            "no_stock_real": True,
            "no_pagos": True,
            "no_guias": True,
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "passed", "reasons"])
        for r in results:
            if not r.get("passed"):
                w.writerow([r.get("case_id"), r.get("category"), r.get("passed"), " | ".join(r.get("reasons") or [])])
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(st["failed_categories"].items()))
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'>"
        f"<h1>Auto-loop V63 ciclo {cycle}</h1>"
        f"<p>Status: <b>{status}</b></p>"
        f"<p>Total: {st['total']} | Pasaron: {st['passed']} | Fallaron: {st['failed']} | Efectividad: {st['effectiveness']:.1f}% | Meta: {goal:.1f}%</p>"
        f"<p>Agregados a regresion: {added}</p>"
        f"<h2>Categorias fallidas</h2><table border='1'><tr><th>Categoria</th><th>Fallos</th></tr>{rows}</table>"
        f"<h2>Salida</h2><pre>{output_tail[-6000:]}</pre>",
        encoding="utf-8",
    )
    summary = (
        f"Auto-loop V63 ciclo {cycle}\n"
        f"Estado: {status}\n"
        f"Conversaciones: {st['total']}\n"
        f"Pasaron: {st['passed']}\n"
        f"Fallaron: {st['failed']}\n"
        f"Efectividad: {st['effectiveness']:.1f}%\n"
        f"Meta: {goal:.1f}%\n"
        f"Categorias fallidas: {json.dumps(st['failed_categories'], ensure_ascii=False)}\n"
        f"Archivos modificados: {', '.join(modified_files) if modified_files else 'sin cambios detectados por el loop'}\n"
        f"Casos agregados a regresion: {added}\n"
        f"Recomendacion: {'seguir' if status == 'ok' else 'detenerse y corregir fallos antes de continuar'}\n"
        f"Resultado JSON tester: {result_path or ''}\n"
        f"Reporte ciclo: {json_path}\n"
    )
    txt_path.write_text(summary, encoding="utf-8")
    SUMMARY_PATH.write_text(summary, encoding="utf-8")
    return txt_path


def git_modified_files() -> List[str]:
    code, out = run_cmd(["git", "status", "--short"], timeout=60)
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--pin", default="")
    ap.add_argument("--cycles", type=int, default=5)
    ap.add_argument("--start-limit", type=int, default=100)
    ap.add_argument("--max-limit", type=int, default=1000)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--notify-file", action="store_true")
    ap.add_argument("--ingest-existing", action="store_true", help="Agregar fallos del ultimo reporte local antes de correr.")
    args = ap.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if args.ingest_existing:
        existing = latest_result_json()
        existing_results = load_results(existing)
        if existing_results:
            added = append_failures(existing_results, 0, str(existing))
            print(f"Fallos existentes agregados a regresion: {added}")

    final_status = "no_ejecutado"
    previous_failures: set[str] = set()
    success_streak_1000 = 0
    for cycle in range(1, min(args.cycles, 5) + 1):
        print(f"\n=== Auto-loop V63 ciclo {cycle} ===")
        ok, out = compile_check()
        if not ok:
            write_cycle_summary(cycle, 0, GOALS.get(cycle, 99.0), None, [], 0, "detenido_compilacion", git_modified_files(), out)
            final_status = "detenido_compilacion"
            break
        ok, reg_out = regression_check()
        if not ok:
            write_cycle_summary(cycle, 0, GOALS.get(cycle, 99.0), None, [], 0, "detenido_regresion", git_modified_files(), reg_out)
            final_status = "detenido_regresion"
            break
        limit = cycle_limit(cycle, args.start_limit, args.max_limit)
        goal = GOALS.get(cycle, 99.0)
        code, tester_out, result_path = run_cycle_tester(args, cycle, limit)
        results = load_results(result_path)
        added = append_failures(results, cycle, str(result_path or ""))
        st = stats(results)
        current_failures = failure_keys(results)
        repeated_failures = sorted(previous_failures & current_failures)
        safety = has_safety_failure(results, tester_out)
        if code != 0:
            status = "detenido_error_tester"
        elif safety:
            status = "detenido_seguridad"
            tester_out += "\nSAFETY: " + safety
        elif repeated_failures:
            status = "detenido_fallo_repetido"
            tester_out += "\nFALLO_REPETIDO: " + ", ".join(repeated_failures[:10])
        elif st["effectiveness"] + 1e-9 < goal:
            status = "detenido_meta_no_cumplida"
        else:
            status = "ok"
            if limit >= 1000 and st["effectiveness"] >= 99.0:
                success_streak_1000 += 1
            else:
                success_streak_1000 = 0
            if success_streak_1000 >= SUCCESS_STREAK_REQUIRED:
                status = "completado_3_tandas_1000_con_99"
        write_cycle_summary(cycle, limit, goal, result_path, results, added, status, git_modified_files(), tester_out)
        print(SUMMARY_PATH.read_text(encoding="utf-8"))
        final_status = status
        previous_failures = current_failures
        if status not in {"ok"}:
            break
    if args.notify_file:
        NOTIFY_PATH.write_text(SUMMARY_PATH.read_text(encoding="utf-8") if SUMMARY_PATH.exists() else final_status, encoding="utf-8")
        print(f"Notificacion escrita en {NOTIFY_PATH}")


if __name__ == "__main__":
    main()
