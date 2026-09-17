"""
Verify Stop works: start a suite WITH ragas, let judging start, stop it,
and confirm the step returns 'cancelled' quickly.
"""
import json
import sys
import threading
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


def main() -> int:
    # read saved suite config (has glm-5.3-flash judge, ragas on)
    cfg = json.load(open("ui/ui_config.json", encoding="utf-8"))["suite"]
    cfg["ragas"]["include_ragas"] = "yes"
    cfg["setup"]["label"] = "stop-test"

    start = api("/api/suite/start", {"config": cfg})
    rid = start["run_id"]
    print("RUN:", rid, flush=True)

    # steps 0,1 are fast — run them
    for i in range(2):
        res = api("/api/suite/step", {"run_id": rid, "step_index": i})
        print("STEP", i, res["step"]["key"], res["status"], flush=True)

    # step 2 (run_questions) in background; stop it once judging begins
    step_result = {}

    def run_step():
        step_result["res"] = api("/api/suite/step", {"run_id": rid, "step_index": 2})

    t = threading.Thread(target=run_step, daemon=True)
    t.start()

    # wait for the ragas-judging phase (or give generation up to 3 min)
    t0 = time.time()
    saw_judging = False
    while time.time() - t0 < 240:
        time.sleep(2)
        p = api(f"/api/suite/progress?run_id={rid}", timeout=10).get("progress")
        if p and p.get("phase") == "ragas-judging":
            saw_judging = True
            print(f"judging started at {time.time()-t0:.0f}s — requesting STOP", flush=True)
            break
    if not saw_judging:
        print("judging never started within 180s; stopping anyway", flush=True)
    api("/api/suite/stop", {"run_id": rid})

    t_stop = time.time()
    t.join(timeout=240)
    took = time.time() - t_stop
    res = step_result.get("res") or {}
    print(f"step2 status after stop: {res.get('status')} (stop→ack {took:.1f}s)")
    print("result:", json.dumps(res.get("result", {}))[:200])
    ok = res.get("status") == "cancelled" and took < 30
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())