"""Live evaluation of the document check against the running backend (real container, real reasoning model).

    python scripts/eval_documents.py                 # the whole corpus
    python scripts/eval_documents.py forged_invoice_pdf genuine_invoice_png   # just these

Prints, per document: the expected verdict, the actual one, how long it took, what the reading model returned, and
which warnings fired. Results are also written to eval_results/documents.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.corpus import CORPUS  # noqa: E402

API = "http://127.0.0.1:8001"
OUT = Path(__file__).resolve().parent.parent / "eval_results"


def run_one(d: dict) -> dict:
    data = d["build"]()
    t = time.time()
    res = requests.post(f"{API}/analyze-document", files={"file": (d["id"], data, "application/octet-stream")},
                        data={"vendor": d["vendor"]} if d["vendor"] else None, timeout=600)
    secs = round(time.time() - t, 1)
    if res.status_code != 200:
        return {"id": d["id"], "expected": d["band"], "actual": f"HTTP {res.status_code}", "seconds": secs}
    body = res.json()
    c = body.get("content") or {}
    reading = c.get("reading") or {}
    facts = c.get("facts") or {}
    sus = sorted(s["id"] for s in body["signals"] if s["direction"] == "suspicious" and s["confidence"] >= 0.6 and s["strength"] >= 0.3)
    weak = sorted(s["id"] for s in body["signals"] if s["direction"] == "suspicious" and not (s["confidence"] >= 0.6 and s["strength"] >= 0.3))
    return {
        "id": d["id"], "format": body["format"], "expected": d["band"], "actual": body.get("band"), "seconds": secs,
        "match": d["band"] == body.get("band"), "isolation": body.get("isolation"),
        "reading": reading.get("status"), "concern": reading.get("concern"), "doc_type": facts.get("document_type"),
        "issuer": facts.get("issuer"), "account_holder": facts.get("account_holder"), "amount": facts.get("total_amount"),
        "dropped_note": "not found in the document" in (reading.get("note") or ""),
        "counted_warnings": sus, "weak_warnings": weak,
        "identifiers": [(i["kind"], i["valid"]) for i in c.get("identifiers", [])],
        "summary_from_model": reading.get("summary"), "inconsistencies": reading.get("inconsistencies", []),
    }


def main(argv: list[str]) -> None:
    wanted = set(argv)
    docs = [d for d in CORPUS if not wanted or d["id"] in wanted]
    results = []
    print(f"{'document':26} {'expected':9} {'actual':9} {'ok':3} {'secs':>6}  reading   details")
    for d in docs:
        r = run_one(d)
        results.append(r)
        print(f"{r['id']:26} {r['expected']:9} {str(r['actual']):9} {'yes' if r.get('match') else 'NO':3} {r['seconds']:>6}  "
              f"{str(r.get('reading')):9} counted={r.get('counted_warnings')}", flush=True)
        if r.get("issuer") or r.get("account_holder") or r.get("amount"):
            print(f"{'':26} model read -> type={r.get('doc_type')} issuer={r.get('issuer')!r} pay-to={r.get('account_holder')!r} amount={r.get('amount')!r}", flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "documents.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    ok = sum(1 for r in results if r.get("match"))
    print(f"\n{ok}/{len(results)} documents reached the expected verdict")


if __name__ == "__main__":
    main(sys.argv[1:])
