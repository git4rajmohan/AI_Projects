"""Final combined verification: per-question judging + progress + Stop.

RUN A: full suite, ragas ON (faithfulness), watch per-question progress.
RUN B: start a suite, stop it during judging (async step), assert cancel.
"""
import json
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


def start_run(label, metrics="faithfulness"):
    cfg = json.load(open("ui/ui_config.json", encoding="utf-8"))["suite"]
    cfg["setup"]["label"] = label
    cfg["ragas"]["metrics"] = metrics
    return api("/api/suite/start", {"config": cfg})["run_id"]


def poll_progress(rid, seconds=600):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            p = api("/api/suite/progress?run_id=" + rid, timeout=10)
            prog = p.get("progress")
            if prog and prog.get("phase") == "ragas-judging":
                print("  PROGRESS %d/%d phase=%s" % (
                    prog.get("question_index", 0),
                    prog.get("question_total", 0),
                    prog.get("phase")), flush=True)
                return
        except Exception:
            pass
        time.sleep(3)


print("=== RUN A: full suite, per-question progress check ===", flush=True)
ridA = start_run("ragas-perq-check")
print("RUN A:", ridA, flush=True)
t = threading.Thread(target=poll_progress, args=(ridA,), daemon=True)
t.start()

for i in range(4):
    t0 = time.time()
    res = api("/api/suite/step", {"run_id": ridA, "step_index": i})
    print("STEP %d %s: %s (%.0fs)" % (i, res["step"]["key"], res["status"],
                                      time.time() - t0), flush=True)
    if res["status"] == "error":
        print("  ERR:", json.dumps(res.get("result"))[:300], flush=True)
        break
    if res["step"]["key"] == "run_questions":
        rag = res["result"].get("ragas") or {}
        print("RUN A ragas agg:", json.dumps(rag.get("aggregate")),
              "| judge:", rag.get("judge_model"), "| scored:", rag.get("n_scored"),
              flush=True)
        print("RUN A ragas errors:", rag.get("errors"), flush=True)
        perq = rag.get("per_question") or []
        n_ok = sum(1 for q in perq if not q.get("failed"))
        print("RUN A per-question OK: %d/%d" % (n_ok, len(perq)), flush=True)

print("=== RUN B: stop during judging ===", flush=True)
ridB = start_run("ragas-stop-check")
print("RUN B:", ridB, flush=True)
status = {}


def step_async():
    try:
        status["res"] = api("/api/suite/step", {"run_id": ridB, "step_index": 2},
                            timeout=1700)
    except Exception as exc:
        status["err"] = exc


th = threading.Thread(target=step_async, daemon=True)
th.start()
# wait until judging phase begins, then request stop
seen_judging = False
t_stop = None
while th.is_alive():
    try:
        p = api("/api/suite/progress?run_id=" + ridB, timeout=10)
        prog = p.get("progress") or {}
        if prog.get("phase") == "ragas-judging":
            if not seen_judging:
                seen_judging = True
                print("  judging started — requesting STOP", flush=True)
                t_stop = time.time()
                api("/api/suite/stop", {"run_id": ridB}, timeout=30)
                break
    except Exception:
        pass
    time.sleep(2)
th.join(timeout=1700)
res = status.get("res") or {}
st = (res.get("status") or "error")
print("step2 status after stop: %s (stop->ack %.1fs)" % (
    st, (time.time() - t_stop) if t_stop else -1), flush=True)
print("VERDICT:", "PASS" if st == "cancelled" else "FAIL", flush=True)