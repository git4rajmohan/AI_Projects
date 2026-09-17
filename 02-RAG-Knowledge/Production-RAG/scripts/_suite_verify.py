"""Full suite run with ragas (sequential) — final verification helper."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def api(path, payload=None, method=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    cfg = json.load(open("ui/ui_config.json", encoding="utf-8"))["suite"]
    cfg["setup"]["label"] = "ragas-sequential-check"
    cfg["ragas"]["metrics"] = "faithfulness"
    start = api("/api/suite/start", {"config": cfg})
    rid = start["run_id"]
    print("RUN:", rid, flush=True)
    for i in range(4):
        t0 = time.time()
        res = api("/api/suite/step", {"run_id": rid, "step_index": i})
        print("STEP %d %s: %s (%.0fs)" % (i, res["step"]["key"], res["status"],
                                          time.time() - t0), flush=True)
        if res["status"] == "error":
            print("ERR:", json.dumps(res.get("result"))[:200], flush=True)
            break
        if res["step"]["key"] == "run_questions":
            rag = res["result"].get("ragas") or {}
            print("  ragas agg:", json.dumps(rag.get("aggregate")),
                  "| judge:", rag.get("judge_model"),
                  "| scored:", rag.get("n_scored"), flush=True)
            print("  ragas errors:", rag.get("errors"), flush=True)


if __name__ == "__main__":
    main()