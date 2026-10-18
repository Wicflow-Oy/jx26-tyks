"""A short browser click-through of the web UI (web/), against the real app served in-process.

It starts `aei.api:app` on a free local port with a temporary state DB and cache, then drives Chromium through the
demo story: the Monday brief, the case file and an approval, My ward, the doctor's order view, the language switch
and the phone width. It skips cleanly when Playwright or its Chromium build is not installed.

    .venv/bin/python -m pytest -q tests/test_ui.py
"""

import re
import socket
import sys
import threading
import time

import pytest

sys.dont_write_bytecode = True  # read-only run: no __pycache__ next to the app's modules

sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")

AS_OF = "2026-03-29"
CHANGE_TO = re.compile(r"\bchange to\b", re.IGNORECASE)
WAIT_MS = 45_000  # a cold cache computes each week's signals on first use


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    import uvicorn

    from aei import config as C
    from aei.api import app

    tmp = tmp_path_factory.mktemp("ui")
    saved = {name: getattr(C, name) for name in ("CACHE_DIR", "STATE_DB", "RATE_LIMIT_PER_MIN")}
    C.CACHE_DIR = tmp / "cache"
    C.CACHE_DIR.mkdir()
    C.STATE_DB = tmp / "state.sqlite"
    C.RATE_LIMIT_PER_MIN = 100_000  # the click-through is one client making many requests

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 120
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            pytest.fail("the app did not start")
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=10)
    for name, value in saved.items():
        setattr(C, name, value)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except sync_api.Error as error:
            pytest.skip(f"Chromium for Playwright is not installed ({str(error).splitlines()[0]})")
        yield chromium
        chromium.close()


@pytest.fixture
def open_page(browser, base_url):
    """open_page(route, width) → a page at base_url + route; console errors are collected in page.errors."""
    pages = []

    def open_(route, width=1440, height=900):
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_default_timeout(WAIT_MS)
        page.errors = []
        page.on("console", lambda msg: msg.type == "error" and page.errors.append(msg.text))
        page.on("pageerror", lambda exc: page.errors.append(str(exc)))
        page.goto(base_url + route)
        pages.append(page)
        return page

    yield open_
    for page in pages:
        assert page.errors == [], f"console errors on {page.url}: {page.errors}"
        page.close()


def no_change_to(page):
    text = page.evaluate("document.body.innerText")
    assert not CHANGE_TO.search(text), f"a screen offers 'Change to' a drug on {page.url}"


def no_horizontal_scroll(page):
    width = page.evaluate("innerWidth")
    assert page.evaluate("document.documentElement.scrollWidth") <= width, f"horizontal scroll on {page.url}"


def test_brief_case_file_and_approval(open_page):
    page = open_page(f"#brief?as_of={AS_OF}")
    hero = page.locator("#brief-hero")
    hero.wait_for()
    assert "P1" in hero.locator(".hero-kicker").inner_text()
    assert re.search(r"ICU.*MRSA", hero.locator("h3").inner_text())

    # at 1440 the top P1's case file opens beside the brief; the hero's link opens the same one
    hero.get_by_role("button", name=re.compile("Case file")).click()
    page.locator("#pane #case-title").wait_for()
    assert "ICU" in page.locator("#pane #case-title").inner_text()

    approve = page.locator("#case-approve")
    approve.wait_for()
    if "Alert active" not in approve.inner_text():
        approve.click()
        page.locator("#toast").filter(has_text="until").wait_for()
    page.locator("#case-approve", has_text="Alert active").wait_for()
    page.locator("#sidebar").get_by_text(re.compile(r"^until ")).first.wait_for()  # the sidebar lists the alert
    no_change_to(page)


def test_my_ward_shows_meropenem_counts(open_page):
    page = open_page(f"#ward?ward=ICU&as_of={AS_OF}")
    row = page.locator("#drow-MEM")
    row.wait_for()
    assert "Meropenem" in row.inner_text()
    assert re.search(r"\d+ of \d+", row.inner_text())
    no_change_to(page)


def test_order_view_info_and_warning_at_sign(open_page):
    page = open_page("#order?patient=phc-tmp")
    card = page.locator(".sw-card")
    card.wait_for()
    assert card.locator(".sw-head .g-info").count() == 1  # a passive info card, never a warning at select
    no_change_to(page)

    page = open_page("#order?patient=uro-esbl")
    page.locator("#ord-dose").wait_for()
    page.locator(".sw-slot:not([aria-busy])").wait_for(state="attached")
    page.fill("#ord-dose", "1")
    page.select_option("#ord-route", index=1)
    page.select_option("#ord-freq", index=1)
    page.locator(".ehr-btn.sign").click()
    sheet = page.locator("#sheet.open.order-sheet")
    sheet.wait_for()
    assert sheet.locator("#sheet-title").inner_text().strip()
    no_change_to(page)
    page.keyboard.press("Escape")  # closing the check leaves the order an unsigned draft
    sheet.wait_for(state="hidden")


def test_language_switch(open_page):
    page = open_page(f"#brief?as_of={AS_OF}")
    page.locator("#brief-hero").wait_for()
    page.locator("#sidebar [role=radio]", has_text="FI").click()
    page.wait_for_url(re.compile(r"lang=fi"))
    page.locator("#brief-hero").wait_for()
    assert page.locator("h1#view-title").inner_text().strip()
    page.locator("#sidebar [role=radio]", has_text="EN").click()
    page.wait_for_function("!location.hash.includes('lang=fi')")
    page.locator("#brief-hero").wait_for()


@pytest.mark.parametrize(
    "route, ready",
    [
        (f"#brief?as_of={AS_OF}", "#brief-hero"),
        (f"#ward?ward=ICU&as_of={AS_OF}", "#drow-MEM"),
        ("#order?patient=phc-tmp", ".sw-card"),
    ],
)
def test_phone_width_has_no_horizontal_scroll(open_page, route, ready):
    page = open_page(route, width=375, height=812)
    page.locator(ready).wait_for()
    page.wait_for_timeout(300)  # charts draw at their measured width after the first frame
    no_horizontal_scroll(page)
    if route.startswith("#brief"):  # the case file as a pushed page, with its action bar
        page.locator("#brief-hero").get_by_role("button", name=re.compile("Case file")).click()
        page.locator("#pane #case-approve").wait_for()
        page.wait_for_timeout(300)
        no_horizontal_scroll(page)
