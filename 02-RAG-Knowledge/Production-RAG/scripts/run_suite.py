# -*- coding: utf-8 -*-
"""Drive a full suite run through the API (steps 0..3), print compact results."""
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
    start = call("/api/suite/start", {"config": None})
    run_id = start["run_id"]
    keys = [s["key"] for s in start["steps"]]
    print("suite run", run_id, keys)
    for i, k in enumerate(keys):
        res = call("/api/suite/step", {"run_id": run_id, "step_index": i})
        r = res.get("result", {})
        print(f"== step {k}: {res['status']} ({res['step'].get('duration_ms')} ms)")
        if res["status"] == "error":
            print("ERROR:", json.dumps(r, ensure_ascii=False))
            sys.exit(1)
        if k == "prepare":
            print(json.dumps({kk: vv for kk, vv in r.items() if kk != "strategies"},
                             ensure_ascii=False, indent=1))
        if k == "run_questions":
            print("snapshot:", r.get("snapshot_id"), "strategy:", r.get("strategy"),
                  "elapsed_s:", round(r.get("elapsed_ms", 0) / 1000))
            print("aggregate:", json.dumps(r.get("aggregate"), indent=1))
        if k == "compare":
            for d in r.get("diffs", []):
                print(f"gate {d.get('snapshot_id')} vs {d.get('baseline_id')}: "
                      f"{d.get('icon')} {d.get('verdict')} worst={d.get('worst_metric')} "
                      f"drop={d.get('worst_drop')} regressed={[q['id'] for q in d.get('regressed_ids', [])]}")
            print("has_baseline:", r.get("has_baseline"))
    print("DONE")


if __name__ == "__main__":
    main()