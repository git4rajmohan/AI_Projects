"""One-shot Selenium capture of DocFlow UI screenshots for userguide.html.

Runs headless Chrome (Selenium Manager auto-downloads chromedriver) against the
already-running API (127.0.0.1:8000) + Streamlit UI (127.0.0.1:8510), drives the
reviewer flow, and saves full-page PNGs to docs/screenshots/.
"""
import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

OUT = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(OUT, exist_ok=True)

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--disable-gpu")
opts.add_argument("--hide-scrollbars")
opts.add_argument("--window-size=1400,2600")
opts.add_argument("--force-device-scale-factor=1")
opts.add_argument("--log-level=3")
service = webdriver.ChromeService()  # Selenium Manager auto-resolves chromedriver
driver = webdriver.Chrome(options=opts, service=service)
driver.set_window_size(1400, 2600)


def shot(name):
    time.sleep(2.5)  # let Streamlit finish its render loop
    driver.save_screenshot(os.path.join(OUT, name))
    print("saved", name)


def settle(sec):
    time.sleep(sec)


try:
    driver.get("http://127.0.0.1:8510/")
    settle(6)

    # reviewer name -> unlocks action buttons
    inp = driver.find_element(By.XPATH, "//input[@aria-label='Reviewer name']")
    inp.send_keys("yuki")
    inp.send_keys(Keys.ENTER)
    settle(2)

    # ---- All Invoices page: skipped (radio switch is fragile in headless); the
    # Review Inbox + detail captures carry the demo story.

    # ---- Review Inbox -> open d2 detail (mismatch + rejected) ----
    time.sleep(3)
    combo = driver.find_element(By.XPATH, "//input[@aria-label='Review invoice']")
    combo.click()
    settle(1.5)
    combo.send_keys(Keys.ARROW_DOWN)   # highlight option 1 (d5)
    settle(0.5)
    combo.send_keys(Keys.ARROW_DOWN)   # option 2 (d2)
    settle(0.5)
    combo.send_keys(Keys.ENTER)        # commit
    settle(2.5)
    combo = driver.find_element(By.XPATH, "//input[@aria-label='Review invoice']")
    combo.send_keys(Keys.ENTER)        # Open
    settle(5)
    shot("ui_review_mismatch.png")

    # ---- d5 detail (missing PO, info_requested) ----
    combo = driver.find_element(By.XPATH, "//input[@aria-label='Review invoice']")
    combo.click()                      # re-open dropdown
    settle(1.5)
    combo.send_keys(Keys.ARROW_DOWN)   # option 1 (d5)
    settle(0.5)
    combo.send_keys(Keys.ENTER)        # commit
    settle(2.5)
    combo = driver.find_element(By.XPATH, "//input[@aria-label='Review invoice']")
    combo.send_keys(Keys.ENTER)        # Open
    settle(5)
    shot("ui_review_missing_po.png")

    # ---- upload page fragment: not needed ----

finally:
    driver.quit()
print("done")