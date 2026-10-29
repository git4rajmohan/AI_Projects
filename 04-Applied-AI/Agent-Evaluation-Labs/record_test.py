"""Drive the Streamlit eval app in Chromium; per-lab webm video + screenshots + results.json."""
import glob
import json
import os
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "test_videos")
os.makedirs(OUT, exist_ok=True)
APP_URL = "http://localhost:8501"
PHOENIX_URL = "http://localhost:6006"

LABS = [
    ("Lab 5 - Tracing demo", 0, 15, "trace"),
    ("Lab 7 - Router and skill evaluations", 1, 50, "scores"),
    ("Lab 9 - Convergence evaluation", 2, 75, "scores"),
    ("Lab 11 - Overall evaluation", 3, 90, "scores"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def lab_tag(label):
    return label.split(" - ")[0].lower().replace(" ", "")


def wait_run_finish(page, minutes):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        if page.get_by_text("Run finished").count():
            return True
        page.wait_for_timeout(3000)
    return False


def run_one(browser, label, index, minutes, kind):
    context = None
    tag = lab_tag(label)
    try:
        t0 = time.time()
        context = browser.new_context(
            viewport={"width": 1680, "height": 1000},
            record_video_dir=OUT,
            record_video_size={"width": 1680, "height": 1000})
        page = context.new_page()
        page.goto(APP_URL, timeout=60000)
        expect(page.get_by_text("Agent Evaluation")).to_be_visible(timeout=90000)
        page.wait_for_timeout(2000)
        sb = page.locator("[data-testid='stSelectbox']").first
        sb.click()
        page.wait_for_timeout(500)
        for _ in range(index):
            page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        if label not in (sb.text_content() or ""):
            sb.click()
            page.keyboard.type(label, delay=30)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
        assert label in (sb.text_content() or ""), f"could not select {label}"
        log(f"{tag}: selected, starting run (budget {minutes} min)")
        page.locator("button:has-text('Run evaluation')").first.click()
        if not wait_run_finish(page, minutes):
            log(f"{tag}: TIMEOUT after {minutes} min")
            page.screenshot(path=os.path.join(OUT, f"{tag}_timeout.png"), full_page=True)
            return "timeout"
        success = page.get_by_text("Run completed.").count() > 0
        if kind == "trace":
            checks = [
                f"metric={page.get_by_text('Answers returned / expected').count() > 0}",
                f"traces={page.get_by_text('Traces').count() > 0}",
            ]
        else:
            checks = [
                f"scores={page.get_by_text('Evaluation scores').count() > 0}",
                f"details={page.get_by_text('How this was tested').count() > 0}",
                f"logs={page.get_by_text('Technical logs').count() > 0}",
            ]
        page.wait_for_timeout(2000)
        page.screenshot(path=os.path.join(OUT, f"{tag}_result.png"), full_page=True)
        page.goto(PHOENIX_URL, timeout=60000)
        page.wait_for_timeout(8000)
        page.screenshot(path=os.path.join(OUT, f"{tag}_phoenix.png"), full_page=False)
        page.close()
        context.close()
        webms = glob.glob(os.path.join(OUT, "*.webm"))
        if webms:
            os.rename(max(webms, key=os.path.getmtime),
                      os.path.join(OUT, f"{tag}.webm"))
        elapsed = round((time.time() - t0) / 60, 1)
        status = "pass" if success else "no-success-text"
        log(f"{tag}: {status} in {elapsed} min :: " + " ".join(checks))
        return f"{status} ({elapsed} min)"
    except Exception as error:
        log(f"{tag}: FAILED - {error}")
        return f"failed: {error}"
    finally:
        if context:
            try:
                context.close()
                webms = glob.glob(os.path.join(OUT, "*.webm"))
                if webms:
                    os.rename(max(webms, key=os.path.getmtime),
                              os.path.join(OUT, f"{tag}.webm"))
            except Exception:
                pass


def main():
    urlopen(APP_URL, timeout=10)  # app must be up
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for label, index, minutes, kind in LABS:
            results[label] = run_one(browser, label, index, minutes, kind)
            with open(os.path.join(OUT, "results.json"), "w") as f:
                json.dump(results, f, indent=2)
        browser.close()
    log("ALL DONE: " + json.dumps(results))


if __name__ == "__main__":
    main()