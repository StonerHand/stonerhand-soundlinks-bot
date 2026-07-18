"""Headless smoke test for the Studio Mini App.

Loads webapp/index.html with a mocked Telegram WebApp and a mocked /api/webapp,
then drives the core flows — boot → search → result card → crate tab — asserting
each renders. Named `smoke.py` (not test_*) so unittest discovery skips it; run
directly (`python tests/e2e/smoke.py`). Exits non-zero on the first failure.
"""

from __future__ import annotations

import glob
import pathlib
import sys

from playwright.sync_api import sync_playwright

HTML = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "index.html").read_text()
COVER = "https://cover.local/a.jpg"

RELEASE = {
    "artist": "Sleep", "title": "Dopesmoker", "kind": "song", "emoji": "📻",
    "year": "1999", "genre": "Stoner Metal", "artwork": COVER,
    "page_url": "https://song.link/x", "preview": None, "preview_pending": False,
    "cta": "слушать обязательно", "cta_custom": False,
    "hashtags": "#stonerhand #doom", "auto_hashtags": "#stonerhand", "tags_custom": False,
    "platforms": [
        {"key": "spotify", "label": "Spotify", "url": "https://open.spotify.com/x", "enabled": True},
        {"key": "appleMusic", "label": "Apple", "url": "https://music.apple.com/x", "enabled": True},
    ],
}
DRAFT = {"ok": True, "draft_id": "d1", "ttl": 3600,
         "flags": {"hashtags": True, "quote": False, "large_preview": True, "as_photo": False, "has_prefix": False},
         "can_publish": False, "release": RELEASE}
RESPONSES = {
    "history": {"ok": True, "is_admin": False, "items": []},
    "resolve": DRAFT,
    "draft": DRAFT,
    "update": DRAFT,
    "preview": {"ok": True, "preview": None},
    "crate": {"ok": True, "count": 0, "max": 10, "items": []},
    "queue": {"ok": True, "items": []},
}

INIT = """window.Telegram={WebApp:{initData:"x",initDataUnsafe:{user:{language_code:"ru"}},colorScheme:"dark",
ready(){},expand(){},close(){},setHeaderColor(){},setBackgroundColor(){},BackButton:{show(){},hide(){},onClick(){}},
HapticFeedback:{impactOccurred(){},selectionChanged(){},notificationOccurred(){}},
CloudStorage:{getItem(k,cb){cb(null,null)},setItem(){}},isVersionAtLeast(){return false},switchInlineQuery(){},readTextFromClipboard(){}}};"""


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        candidates = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
        if not candidates:
            raise
        return p.chromium.launch(executable_path=candidates[0])


def _route_api(route):
    action = (route.request.post_data_json or {}).get("action")
    route.fulfill(json=RESPONSES.get(action, {"ok": True}), content_type="application/json")


def main() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": 390, "height": 800})
        page.add_init_script(INIT)
        page.route("**/telegram.org/**", lambda r: r.abort())
        page.route("**/cover.local/**", lambda r: r.fulfill(status=404))
        page.route("**/api/webapp", _route_api)
        page.route("https://studio.local/app", lambda r: r.fulfill(body=HTML, content_type="text/html"))

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto("https://studio.local/app", wait_until="load")
        page.wait_for_timeout(700)

        # 1. boots to home
        if page.eval_on_selector("#v-home", "el => el.classList.contains('hidden')"):
            failures.append("home view not shown on boot")

        # 2. a search renders the result card with the track title
        page.evaluate("document.getElementById('query').value = 'sleep dopesmoker'")
        page.eval_on_selector("#query", "el => el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        page.wait_for_timeout(900)
        if page.eval_on_selector("#v-result", "el => el.classList.contains('hidden')"):
            failures.append("result view not shown after search")
        elif "Dopesmoker" not in page.eval_on_selector("#v-result", "el => el.innerText"):
            failures.append("result card missing track title")

        # 3. crate tab opens
        page.eval_on_selector('#tabbar [data-tab="crate"]', "el => el.click()")
        page.wait_for_timeout(500)
        if page.eval_on_selector("#v-crate", "el => el.classList.contains('hidden')"):
            failures.append("crate view not shown after tab click")

        if errors:
            failures.append("uncaught page errors: " + " | ".join(errors))

        browser.close()

    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1

    print("PASS: Studio smoke test (boot → search → result → crate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
