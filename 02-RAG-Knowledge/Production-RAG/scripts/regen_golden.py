# -*- coding: utf-8 -*-
"""Regenerate the golden set via the API and freeze it (regression for the
expected_sections freeze bug). Run with the project venv python."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(path, payload=None, method=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method=method or ("POST" if payload is not None else "GET"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    start = call("/api/eval/start", {"config": None})
    run_id = start["run_id"]
    keys = [s["key"] for s in start["steps"]]
    print("run", run_id, keys)
    for i, k in enumerate(keys):
        res = call("/api/eval/step", {"run_id": run_id, "step_index": i})
        status = res["status"]
        r = res.get("result", {})
        print(f"step {k}: {status}", {kk: vv for kk, vv in r.items()
                                      if kk in ("total_sections", "used", "generated", "kept",
                                                "closed_book_rejected", "grounding_rejected",
                                                "deduped", "awaiting", "frozen")})
        if status == "error":
            print("ERROR:", r)
            sys.exit(1)
    frozen = call("/api/eval/golden/freeze", {"approved": [], "run_id": run_id})
    print("frozen:", frozen)
    got = call("/api/eval/golden")
    items = got["frozen"]
    with_exp = sum(1 for it in items if it.get("expected_sections"))
    print(f"golden file: {len(items)} items, {with_exp} with expected_sections")
    kinds = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    print("kinds:", kinds)


if __name__ == "__main__":
    main()