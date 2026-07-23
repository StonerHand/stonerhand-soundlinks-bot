"""Headless smoke test for the Studio Mini App.

Loads webapp/index.html with a mocked Telegram WebApp and a mocked /api/webapp,
then drives the core flows — boot → search → result card → crate tab — asserting
each renders. Named `smoke.py` (not test_*) so unittest discovery skips it; run
directly (`python tests/e2e/smoke.py`). Exits non-zero on the first failure.
"""

from __future__ import annotations

import glob
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

HTML = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "index.html").read_text()
CSS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "styles.css").read_text()
STUDIO_SHELL_CSS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "studio-shell.css").read_text()
JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "app.js").read_text()
API_JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "api-client.js").read_text()
CLOUD_JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "cloud-storage.js").read_text()
CORE_JS = (pathlib.Path(__file__).resolve().parents[2] / "webapp" / "studio-core.js").read_text()
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
    "dashboard": {
        "ok": True, "is_admin": False, "history": [],
        "crate": {"ok": True, "count": 0, "max": 10, "items": []},
        "queue": {"count": 0, "next_at": None},
    },
    "history": {"ok": True, "is_admin": False, "items": []},
    "resolve": DRAFT,
    "draft": DRAFT,
    "update": DRAFT,
    "prepare_share": {"ok": True, "prepared_message_id": "prepared-1"},
    "prepare_crate_share": {"ok": True, "prepared_message_id": "prepared-crate-1"},
    "preview": {"ok": True, "preview": None},
    "crate": {"ok": True, "count": 0, "max": 10, "items": []},
    "queue": {"ok": True, "items": []},
    "resolve_batch": {
        "ok": True, "count": 2, "max": 10,
        "requested_count": 2, "resolved_count": 2, "failed_count": 0,
        "items": [
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
FAIL_ACTIONS: set[str] = set()
CAPTURE_DIR = os.environ.get("STUDIO_CAPTURE_DIR")

INIT = """window.Telegram={WebApp:{initData:"x",initDataUnsafe:{user:{language_code:"ru"}},colorScheme:"dark",
ready(){},expand(){},close(){},setHeaderColor(){},setBackgroundColor(){},onEvent(){},contentSafeAreaInset:{top:7,right:0,bottom:11,left:0},BackButton:{show(){},hide(){},onClick(){}},
HapticFeedback:{impactOccurred(){},selectionChanged(){},notificationOccurred(){}},
CloudStorage:{store:{},getItem(k,cb){cb(null,this.store[k]??null)},setItem(k,v,cb){this.store[k]=v;if(cb)cb(null,true)},removeItem(k,cb){delete this.store[k];if(cb)cb(null,true)}},isVersionAtLeast(){return false},
MainButton:{text:"",visible:false,handler:null,setText(t){this.text=t},show(){this.visible=true},hide(){this.visible=false},enable(){},disable(){},showProgress(){},hideProgress(){},onClick(fn){this.handler=fn},offClick(fn){if(this.handler===fn)this.handler=null}},
shareMessage(id,cb){window.__preparedMessage=id;if(cb)cb(true)},switchInlineQuery(q){window.__inlineQuery=q},readTextFromClipboard(cb){cb("https://open.spotify.com/track/pasted")}}};"""


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
    if action in FAIL_ACTIONS:
        route.fulfill(status=503, json={"ok": False, "error": "network", "retryable": False}, content_type="application/json")
        return
    if action == "resolve" and (body.get("payload") or {}).get("query") == "missing":
        route.fulfill(json={"ok": False, "error": "not_found"}, content_type="application/json")
        return
    if action == "dashboard" and ACTION_ATTEMPTS[action] == 1:
        route.fulfill(
            status=503,
            json={"ok": False, "error": "internal", "retryable": True},
            content_type="application/json",
        )
        return
    route.fulfill(json=RESPONSES.get(action, {"ok": True}), content_type="application/json")


def _theme_contrast(page) -> float:
    return page.evaluate(
        """() => {
          const root=getComputedStyle(document.documentElement), probe=document.createElement('i');
          document.body.appendChild(probe);
          const rgb=(value)=>{probe.style.color=value;const m=getComputedStyle(probe).color.match(/\\d+(?:\\.\\d+)?/g);return m.slice(0,3).map(Number)};
          const lum=(values)=>values.map(v=>v/255).map(v=>v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4)).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
          const a=lum(rgb(root.getPropertyValue('--fg'))),b=lum(rgb(root.getPropertyValue('--bg')));probe.remove();
          return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        }"""
    )


def _capture(page, name: str) -> None:
    if not CAPTURE_DIR:
        return
    target = pathlib.Path(CAPTURE_DIR)
    target.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target / f"{name}.png"), full_page=True)


def main() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": 390, "height": 800})
        page.add_init_script(INIT)
        page.route("**/telegram.org/**", lambda r: r.abort())
        page.route("**/cover.local/**", lambda r: r.fulfill(status=404))
        page.route("**/api/webapp", _route_api)
        page.route("https://studio.local/app*", lambda r: r.fulfill(body=HTML, content_type="text/html"))
        page.route("https://studio.local/webapp/styles.css", lambda r: r.fulfill(body=CSS, content_type="text/css"))
        page.route("https://studio.local/webapp/studio-shell.css", lambda r: r.fulfill(body=STUDIO_SHELL_CSS, content_type="text/css"))
        page.route("https://studio.local/webapp/app.js", lambda r: r.fulfill(body=JS, content_type="application/javascript"))
        page.route("https://studio.local/webapp/api-client.js", lambda r: r.fulfill(body=API_JS, content_type="application/javascript"))
        page.route("https://studio.local/webapp/cloud-storage.js", lambda r: r.fulfill(body=CLOUD_JS, content_type="application/javascript"))
        page.route("https://studio.local/webapp/studio-core.js", lambda r: r.fulfill(body=CORE_JS, content_type="application/javascript"))

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto("https://studio.local/app", wait_until="load")
        page.wait_for_timeout(700)

        # 1. boots to home
        if page.eval_on_selector("#v-home", "el => el.classList.contains('hidden')"):
            failures.append("home view not shown on boot")
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("home view has horizontal overflow at 390px")
        if _theme_contrast(page) < 4.5:
            failures.append("dark theme foreground contrast is below WCAG AA")
        if page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--tg-safe-bottom').trim()") != "11px":
            failures.append("Telegram content safe area was not applied")
        if page.eval_on_selector("#quick", "el => el.classList.contains('hidden')"):
            failures.append("quick actions are hidden for an ordinary user")
        if not page.eval_on_selector("#search-go", "el => el.disabled"):
            failures.append("empty search can be submitted")
        if not page.eval_on_selector("#q-queue", "el => el.classList.contains('hidden')"):
            failures.append("admin queue shortcut is visible to an ordinary user")
        _capture(page, "01-home-dark")

        # Clipboard paste and inline mode are first-class shortcuts on home.
        page.eval_on_selector("#paste-btn", "el => el.click()")
        if "open.spotify.com" not in page.eval_on_selector("#query", "el => el.value"):
            failures.append("paste button did not fill the search input")
        page.eval_on_selector("#clear", "el => el.click()")
        page.eval_on_selector("#q-inline", "el => el.click()")
        if page.evaluate("window.__inlineQuery") != "":
            failures.append("inline shortcut did not open Telegram inline mode")
        page.eval_on_selector("#q-create", "el => el.click()")
        if not page.eval_on_selector("#query", "el => document.activeElement === el"):
            failures.append("create shortcut did not focus the primary search")

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
        page.eval_on_selector(
            "#query",
            "el => {el.value='sleep dopesmoker';el.dispatchEvent(new Event('input'))}",
        )
        page.eval_on_selector("#query", "el => el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        page.wait_for_timeout(900)
        if page.eval_on_selector("#v-result", "el => el.classList.contains('hidden')"):
            failures.append("result view not shown after search")
        elif "Dopesmoker" not in page.eval_on_selector("#v-result", "el => el.innerText"):
            failures.append("result card missing track title")
        if page.locator("#result-readiness span").count() != 3:
            failures.append("result readiness summary is incomplete")
        score = int(page.eval_on_selector("#result-score-value", "el => el.textContent"))
        if score < 75:
            failures.append(f"result readiness score is unexpectedly low: {score}")
        if page.locator("#post-card .cover-fallback").count() != 1:
            failures.append("broken artwork did not switch to the compact fallback")
        if score >= 100:
            failures.append("broken artwork is incorrectly counted as fully ready")
        if not page.evaluate("Telegram.WebApp.MainButton.visible && Telegram.WebApp.MainButton.text.length > 0"):
            failures.append("native Telegram MainButton is not active on the result")
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("result view has horizontal overflow")
        if not page.eval_on_selector("#coach", "el => el.classList.contains('open')"):
            failures.append("first-run coach did not open")
        page.keyboard.press("Escape")
        if page.eval_on_selector("#coach", "el => el.classList.contains('open')"):
            failures.append("first-run coach cannot be dismissed with Escape")
        _capture(page, "02-result-dark")
        page.set_viewport_size({"width": 880, "height": 900})
        page.wait_for_timeout(150)
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("desktop result view has horizontal overflow")
        result_columns = page.eval_on_selector(
            "#post-card",
            "el => getComputedStyle(el).gridTemplateColumns",
        )
        if result_columns == "none" or len(result_columns.split()) < 2:
            failures.append("desktop result did not adopt the product-preview split card")
        _capture(page, "02b-result-desktop")
        page.set_viewport_size({"width": 390, "height": 800})

        # Formatting auto-saves and never allows a post without platforms.
        page.eval_on_selector("#open-format", "el => el.click()")
        if page.locator("#format-nav button").count() != 4:
            failures.append("format editor navigation is incomplete")
        page.eval_on_selector('#format-nav [data-target="format-copy"]', "el => el.click()")
        if not page.eval_on_selector('#format-nav [data-target="format-copy"]', "el => el.classList.contains('active')"):
            failures.append("format editor navigation does not expose its active section")
        page.wait_for_timeout(350)
        nav_bottom, input_top = page.evaluate(
            """() => [
              document.getElementById('format-nav').getBoundingClientRect().bottom,
              document.getElementById('cta-input').getBoundingClientRect().top,
            ]"""
        )
        if input_top < nav_bottom - 2:
            failures.append("format navigation scrolls the field under its sticky header")
        _capture(page, "03-format-dark")
        page.eval_on_selector("#cta-input", "el => {el.value='новый текст';el.dispatchEvent(new Event('input'))}")
        page.wait_for_timeout(650)
        if page.eval_on_selector("#fmt-sync", "el => el.textContent") != "Сохранено":
            failures.append("formatting changes do not reach the saved state")
        checks = page.locator("#pm-list .pm-check")
        checks.nth(0).click()
        checks.nth(1).click()
        if page.locator("#pm-list .pm-check.on").count() < 1:
            failures.append("formatting allowed all platforms to be disabled")
        page.eval_on_selector("#fmt-apply", "el => el.click()")
        page.wait_for_timeout(250)

        # 3. publication uses a destination sheet and a success state
        page.eval_on_selector("#action-main", "el => el.click()")
        page.wait_for_timeout(150)
        if not page.eval_on_selector("#publish-sheet", "el => el.classList.contains('open')"):
            failures.append("publish destination sheet did not open")
        if page.locator("#publish-preflight .preflight-item").count() != 4:
            failures.append("publication preflight is incomplete")
        page.eval_on_selector("#publish-self", "el => el.click()")
        page.wait_for_timeout(300)
        if not page.eval_on_selector("#success-screen", "el => el.classList.contains('open')"):
            failures.append("publication success state did not open")
        page.eval_on_selector("#success-close", "el => el.click()")

        # Native sharing sends the exact prepared post, including its keyboard.
        page.eval_on_selector("#action-share", "el => el.click()")
        page.wait_for_timeout(100)
        if not page.eval_on_selector("#share-sheet", "el => el.classList.contains('open')"):
            failures.append("share sheet did not open")
        page.eval_on_selector("#share-post", "el => el.click()")
        page.wait_for_timeout(250)
        if page.evaluate("window.__preparedMessage") != "prepared-1":
            failures.append("native Telegram share did not use prepared message")
        prepare_requests = [body for body in REQUEST_BODIES if body.get("action") == "prepare_share"]
        if not prepare_requests or (prepare_requests[-1].get("payload") or {}).get("draft_id") != "d1":
            failures.append("native share did not prepare the active draft")

        # 4. crate tab opens
        page.eval_on_selector('#tabbar [data-tab="crate"]', "el => el.click()")
        page.wait_for_timeout(500)
        if page.eval_on_selector("#v-crate", "el => el.classList.contains('hidden')"):
            failures.append("crate view not shown after tab click")
        if page.evaluate("Telegram.WebApp.MainButton.visible"):
            failures.append("native Telegram MainButton stayed visible outside the result")

        # 5. home shortcut cards are wired (they mirror the tab bar)
        page.eval_on_selector('#tabbar [data-tab="home"]', "el => el.click()")
        page.wait_for_timeout(300)
        if page.eval_on_selector("#resume-card", "el => el.classList.contains('hidden')"):
            failures.append("active draft is not offered on the home dashboard")
        elif "Dopesmoker" not in page.eval_on_selector("#resume-card", "el => el.innerText"):
            failures.append("active draft card lost release context")
        page.eval_on_selector("#q-queue", "el => el.classList.remove('hidden')")
        FAIL_ACTIONS.add("queue")
        page.eval_on_selector("#q-queue", "el => el.click()")
        page.wait_for_timeout(400)
        if page.eval_on_selector("#v-queue", "el => el.classList.contains('hidden')"):
            failures.append("home shortcut #q-queue did not open the queue")
        if page.locator("#queue-list .state-action").count() != 1:
            failures.append("queue network error has no visible retry state")
        FAIL_ACTIONS.discard("queue")
        page.eval_on_selector("#queue-list .state-action", "el => el.click()")
        page.wait_for_timeout(300)

        # 6. pasting multiple links builds a crate automatically
        page.eval_on_selector('#tabbar [data-tab="home"]', "el => el.click()")
        page.wait_for_timeout(200)
        page.eval_on_selector(
            "#query",
            """el => {
              el.value='https://open.spotify.com/track/a https://open.spotify.com/track/b';
              el.dispatchEvent(new Event('input'));
            }""",
        )
        if not page.eval_on_selector("#searchbar", "el => el.classList.contains('batch')"):
            failures.append("multiple links do not expose batch mode before submission")
        if "2" not in page.eval_on_selector("#batch-label", "el => el.textContent"):
            failures.append("batch mode does not explain how many links will be imported")
        page.eval_on_selector("#query", "el => el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        page.wait_for_timeout(700)
        if page.eval_on_selector("#v-crate", "el => el.classList.contains('hidden')"):
            failures.append("batch paste did not open the crate")
        elif "Dopesmoker" not in page.eval_on_selector("#v-crate", "el => el.innerText"):
            failures.append("batch paste crate is missing items")
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("crate view has horizontal overflow")
        page.eval_on_selector("#crate-edit", "el => el.click()")
        page.eval_on_selector("#crate-title-input", "el => el.value='Тяжёлый вечер'")
        page.eval_on_selector("#crate-intro-input", "el => el.value='Два релиза рядом'")
        page.eval_on_selector("#crate-tags-input", "el => el.value='#stonerhand #doom'")
        page.eval_on_selector("#crate-editor-save", "el => el.click()")
        page.eval_on_selector("#crate-list .edit", "el => el.click()")
        page.eval_on_selector("#crate-section-input", "el => el.value='Новинки'")
        page.eval_on_selector("#crate-note-input", "el => el.value='Начинаем здесь'")
        page.eval_on_selector("#crate-item-save", "el => el.click()")
        if "Тяжёлый вечер" not in page.eval_on_selector("#crate-cover", "el => el.innerText"):
            failures.append("collection editor did not update the crate title")
        crate_text = page.eval_on_selector("#crate-list", "el => el.innerText")
        if "новинки" not in crate_text.lower():
            failures.append("collection item grouping did not render: " + crate_text[:160])
        page.eval_on_selector("#crate-main", "el => el.click()")
        if not page.eval_on_selector("#publish-sheet", "el => el.classList.contains('open')"):
            failures.append("crate does not use the unified publish sheet")
        elif "Тяжёлый вечер" not in page.eval_on_selector("#publish-summary", "el => el.innerText"):
            failures.append("unified publish sheet lost the collection summary")
        page.eval_on_selector("#publish-close", "el => el.click()")
        if page.eval_on_selector("#crate-share", "el => el.classList.contains('hidden')"):
            failures.append("ready crate has no share action")
        else:
            page.eval_on_selector("#crate-share", "el => el.click()")
            page.wait_for_timeout(250)
            if page.evaluate("window.__preparedMessage") != "prepared-crate-1":
                failures.append("crate share did not keep the prepared collection")
            crate_share_requests = [body for body in REQUEST_BODIES if body.get("action") == "prepare_crate_share"]
            payload = (crate_share_requests[-1].get("payload") or {}) if crate_share_requests else {}
            if (payload.get("collection") or {}).get("title") != "Тяжёлый вечер":
                failures.append("crate share lost collection styling")
            if not payload.get("item_meta") or payload["item_meta"][0].get("section") != "Новинки":
                failures.append("crate share lost track grouping")

        # A failed search must lead back to an editable query, not repeat itself.
        page.eval_on_selector('#tabbar [data-tab="home"]', "el => el.click()")
        page.wait_for_timeout(200)
        page.eval_on_selector(
            "#query",
            "el => {el.value='missing';el.dispatchEvent(new Event('input'))}",
        )
        page.eval_on_selector("#query", "el => el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        page.wait_for_timeout(350)
        if page.eval_on_selector("#v-notfound", "el => el.classList.contains('hidden')"):
            failures.append("not-found state did not render")
        page.eval_on_selector("#nf-retry", "el => el.click()")
        page.wait_for_timeout(150)
        if page.eval_on_selector("#query", "el => el.value") != "missing":
            failures.append("edit-query action did not preserve the failed query")

        # Theme and cross-surface deep links keep native behavior intact.
        page.eval_on_selector("#theme-btn", "el => el.click()")
        if not page.eval_on_selector("body", "el => el.classList.contains('light')"):
            failures.append("theme toggle did not switch to light mode")
        if _theme_contrast(page) < 4.5:
            failures.append("light theme foreground contrast is below WCAG AA")
        quick_theme = page.eval_on_selector(
            "#q-create",
            """el => ({
              color:getComputedStyle(el).color,
              backgroundImage:getComputedStyle(el).backgroundImage,
            })""",
        )
        if (
            quick_theme["color"] != "rgb(23, 26, 36)"
            or quick_theme["backgroundImage"] == "none"
        ):
            failures.append("light theme quick actions did not adopt the light product surface")
        _capture(page, "04-home-light")
        page.set_viewport_size({"width": 620, "height": 900})
        page.goto("https://studio.local/app", wait_until="load")
        page.wait_for_timeout(500)
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("wide Telegram viewport has horizontal overflow")
        if page.eval_on_selector(".wrap", "el => el.getBoundingClientRect().width") < 580:
            failures.append("workspace does not adapt to a wide Telegram viewport")
        _capture(page, "05-home-wide")
        page.set_viewport_size({"width": 880, "height": 900})
        page.goto("https://studio.local/app", wait_until="load")
        page.wait_for_timeout(500)
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("desktop Telegram viewport has horizontal overflow")
        if page.eval_on_selector(".wrap", "el => el.getBoundingClientRect().width") < 840:
            failures.append("workspace does not use the expanded desktop viewport")
        if page.locator("#quick button:not(.hidden)").count() < 3:
            failures.append("desktop home is missing the three core actions")
        _capture(page, "06-home-desktop")
        page.goto("https://studio.local/app?view=crate", wait_until="load")
        page.wait_for_timeout(600)
        if page.eval_on_selector("#v-crate", "el => el.classList.contains('hidden')"):
            failures.append("?view=crate deep link did not open the crate")

        if errors:
            failures.append("uncaught page errors: " + " | ".join(errors))
        if not REQUEST_BODIES or any(not body.get("request_id") for body in REQUEST_BODIES):
            failures.append("API requests are missing request_id")
        dashboard_requests = [body for body in REQUEST_BODIES if body.get("action") == "dashboard"]
        if len(dashboard_requests) < 2 or dashboard_requests[0]["request_id"] != dashboard_requests[1]["request_id"]:
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
