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
CSS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "styles.css").read_text()
JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "app.js").read_text()
API_JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "api-client.js").read_text()
CLOUD_JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "cloud-storage.js").read_text()
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
    "resolve_batch": {"ok": True, "count": 2, "max": 10, "items": [
        {"artist": "Sleep", "title": "Dopesmoker", "emoji": "📻", "artwork": None,
         "data": {"artist": "Sleep", "title": "Dopesmoker", "kind": "song",
                  "page_url": "https://song.link/a", "thumbnail_url": None}},
        {"artist": "Om", "title": "Advaitic Songs", "emoji": "📻", "artwork": None,
         "data": {"artist": "Om", "title": "Advaitic Songs", "kind": "song",
                  "page_url": "https://song.link/b", "thumbnail_url": None}},
    ]},
}
REQUEST_BODIES: list[dict] = []
ACTION_ATTEMPTS: dict[str, int] = {}

INIT = """window.Telegram={WebApp:{initData:"x",initDataUnsafe:{user:{language_code:"ru"}},colorScheme:"dark",
ready(){},expand(){},close(){},setHeaderColor(){},setBackgroundColor(){},BackButton:{show(){},hide(){},onClick(){}},
HapticFeedback:{impactOccurred(){},selectionChanged(){},notificationOccurred(){}},
CloudStorage:{getItem(k,cb){cb(null,null)},setItem(){}},isVersionAtLeast(){return false},
switchInlineQuery(q){window.__inlineQuery=q},readTextFromClipboard(cb){cb("https://open.spotify.com/track/pasted")}}};"""


def _launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        candidates = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
        if not candidates:
            raise
        return p.chromium.launch(executable_path=candidates[0])


def _route_api(route):
    body = route.request.post_data_json or {}
    REQUEST_BODIES.append(body)
    action = body.get("action")
    ACTION_ATTEMPTS[action] = ACTION_ATTEMPTS.get(action, 0) + 1
    if action == "history" and ACTION_ATTEMPTS[action] == 1:
        route.fulfill(
            status=503,
            json={"ok": False, "error": "internal", "retryable": True},
            content_type="application/json",
        )
        return
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
        page.route("https://studio.local/webapp/styles.css", lambda r: r.fulfill(body=CSS, content_type="text/css"))
        page.route("https://studio.local/webapp/app.js", lambda r: r.fulfill(body=JS, content_type="application/javascript"))
        page.route("https://studio.local/webapp/api-client.js", lambda r: r.fulfill(body=API_JS, content_type="application/javascript"))
        page.route("https://studio.local/webapp/cloud-storage.js", lambda r: r.fulfill(body=CLOUD_JS, content_type="application/javascript"))

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto("https://studio.local/app", wait_until="load")
        page.wait_for_timeout(700)

        # 1. boots to home
        if page.eval_on_selector("#v-home", "el => el.classList.contains('hidden')"):
            failures.append("home view not shown on boot")
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("home view has horizontal overflow at 390px")
        if page.eval_on_selector("#quick", "el => el.classList.contains('hidden')"):
            failures.append("quick actions are hidden for an ordinary user")
        if not page.eval_on_selector("#q-queue", "el => el.classList.contains('hidden')"):
            failures.append("admin queue shortcut is visible to an ordinary user")

        # Clipboard paste and inline mode are first-class shortcuts on home.
        page.eval_on_selector("#paste-btn", "el => el.click()")
        if "open.spotify.com" not in page.eval_on_selector("#query", "el => el.value"):
            failures.append("paste button did not fill the search input")
        page.eval_on_selector("#clear", "el => el.click()")
        page.eval_on_selector("#q-inline", "el => el.click()")
        if page.evaluate("window.__inlineQuery") != "":
            failures.append("inline shortcut did not open Telegram inline mode")

        # Popular cards must keep their title clear of the decorative music
        # icon, including the narrowest Telegram viewport we support.
        for width in (390, 320):
            page.set_viewport_size({"width": width, "height": 800})
            overlaps = page.eval_on_selector_all(
                "#suggestions .row",
                """cards => cards.some(card => {
                  const a = card.querySelector('.row-title').getBoundingClientRect();
                  const b = card.querySelector('.suggestion-note').getBoundingClientRect();
                  return a.left < b.right && a.right > b.left &&
                         a.top < b.bottom && a.bottom > b.top;
                })""",
            )
            if overlaps:
                failures.append(f"popular card title overlaps its icon at {width}px")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                failures.append(f"home view has horizontal overflow at {width}px")
        page.set_viewport_size({"width": 390, "height": 800})

        # 2. a search renders the result card with the track title
        page.evaluate("document.getElementById('query').value = 'sleep dopesmoker'")
        page.eval_on_selector("#query", "el => el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        page.wait_for_timeout(900)
        if page.eval_on_selector("#v-result", "el => el.classList.contains('hidden')"):
            failures.append("result view not shown after search")
        elif "Dopesmoker" not in page.eval_on_selector("#v-result", "el => el.innerText"):
            failures.append("result card missing track title")
        if page.locator("#result-readiness span").count() != 3:
            failures.append("result readiness summary is incomplete")
        if not page.eval_on_selector("#coach", "el => el.classList.contains('open')"):
            failures.append("first-run coach did not open")
        page.keyboard.press("Escape")
        if page.eval_on_selector("#coach", "el => el.classList.contains('open')"):
            failures.append("first-run coach cannot be dismissed with Escape")

        # 3. publication uses a destination sheet and a success state
        page.eval_on_selector("#action-main", "el => el.click()")
        page.wait_for_timeout(150)
        if not page.eval_on_selector("#publish-sheet", "el => el.classList.contains('open')"):
            failures.append("publish destination sheet did not open")
        page.eval_on_selector("#publish-self", "el => el.click()")
        page.wait_for_timeout(300)
        if not page.eval_on_selector("#success-screen", "el => el.classList.contains('open')"):
            failures.append("publication success state did not open")
        page.eval_on_selector("#success-close", "el => el.click()")

        # 4. crate tab opens
        page.eval_on_selector('#tabbar [data-tab="crate"]', "el => el.click()")
        page.wait_for_timeout(500)
        if page.eval_on_selector("#v-crate", "el => el.classList.contains('hidden')"):
            failures.append("crate view not shown after tab click")

        # 5. home shortcut cards are wired (they mirror the tab bar)
        page.eval_on_selector('#tabbar [data-tab="home"]', "el => el.click()")
        page.wait_for_timeout(300)
        page.eval_on_selector("#q-queue", "el => el.classList.remove('hidden')")
        page.eval_on_selector("#q-queue", "el => el.click()")
        page.wait_for_timeout(400)
        if page.eval_on_selector("#v-queue", "el => el.classList.contains('hidden')"):
            failures.append("home shortcut #q-queue did not open the queue")

        # 6. pasting multiple links builds a crate automatically
        page.eval_on_selector('#tabbar [data-tab="home"]', "el => el.click()")
        page.wait_for_timeout(200)
        page.evaluate(
            "document.getElementById('query').value = "
            "'https://open.spotify.com/track/a https://open.spotify.com/track/b'"
        )
        page.eval_on_selector("#query", "el => el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        page.wait_for_timeout(700)
        if page.eval_on_selector("#v-crate", "el => el.classList.contains('hidden')"):
            failures.append("batch paste did not open the crate")
        elif "Dopesmoker" not in page.eval_on_selector("#v-crate", "el => el.innerText"):
            failures.append("batch paste crate is missing items")

        if errors:
            failures.append("uncaught page errors: " + " | ".join(errors))
        if not REQUEST_BODIES or any(not body.get("request_id") for body in REQUEST_BODIES):
            failures.append("API requests are missing request_id")
        history_requests = [body for body in REQUEST_BODIES if body.get("action") == "history"]
        if len(history_requests) < 2 or history_requests[0]["request_id"] != history_requests[1]["request_id"]:
            failures.append("retry did not reuse the original request_id")

        browser.close()

    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1

    print("PASS: Studio smoke test (boot → search → result → crate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
