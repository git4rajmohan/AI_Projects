# -*- coding: utf-8 -*-
"""Run the suite with the semantic retriever, then diff vs baseline via /api/eval/diff."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(path, payload=None, method=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method=method or ("POST" if payload is not None else "GET"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # semantic retriever config, temperature 0 for reproducibility
    config = {"setup": {"mode": "single", "label": "semantic-retriever-check"},
              "retrieve": {"retriever": "semantic", "top_k": 5},
              "generate": {"chat_model": "gpt-oss:120b",
                           "chat_base_url": "https://ollama.com/v1",
                           "max_tokens": 2048, "temperature": 0.0}}
    start = call("/api/suite/start", {"config": config})
    run_id = start["run_id"]
    for i, k in enumerate(s["key"] for s in start["steps"]):
        res = call("/api/suite/step", {"run_id": run_id, "step_index": i})
        r = res.get("result", {})
        if res["status"] == "error":
            print("ERROR at", k, ":", json.dumps(r, ensure_ascii=False))
            sys.exit(1)
        if k == "run_questions":
            snap_id = r["snapshot_id"]
            print("snapshot:", snap_id, "aggregate:", json.dumps(r["aggregate"], indent=1))
    diff = call(f"/api/eval/diff?id={snap_id}")
    print(f"GATE vs baseline {diff['baseline_id']}: {diff['icon']} {diff['verdict']}")
    for m in diff["metrics"]:
        if m["delta"] is not None:
            print(f"  {m['metric']:24s} {m['baseline']} -> {m['current']}  delta={m['delta']}  {m['verdict']}")
    print("regressed:", [q["id"] for q in diff["regressed_ids"]])


if __name__ == "__main__":
    main()