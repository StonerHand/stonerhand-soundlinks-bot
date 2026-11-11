"""Draw the phone screens of README.md from the bot's real texts and buttons.

Every screen is what the bot actually sends: the text comes from the card
formatters and the buttons from the keyboards, so a picture cannot drift from
the product by hand. Only the artwork (docs/assets/art) is a drawing.

    .venv/bin/python scripts/readme_previews.py            # write docs/assets/*.png
    .venv/bin/python scripts/readme_previews.py --html DIR  # only the HTML pages

Rendering needs Google Chrome. It also records what each picture shows in
docs/assets/previews.json; tests/test_readme_previews.py fails when the bot
has changed since, until the pictures are drawn again.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from music_links_bot.cards.formatter import (
    format_mixed_collection_message,
    format_title_message,
    format_track_message,
)
from music_links_bot.cards.keyboards import (
    _build_link_keyboard,
    _build_mixed_collection_keyboard,
    _build_title_keyboard,
)
from music_links_bot.core.draft_model import new_track_draft
from music_links_bot.core.models import TitleMatch, TrackMatch, VideoMatch
from music_links_bot.editor.editor_view import render_track_draft

ASSETS = ROOT / "docs" / "assets"
RECORD = ASSETS / "previews.json"
ART = ASSETS / "art"
AVATAR = ROOT / "src" / "music_links_bot" / "assets" / "brandmark.png"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SIZE = (420, 860)  # CSS pixels; the pictures are twice that
QUOTE = "Медленно, тяжело, на повторе."


@dataclass
class Screen:
    title: str
    subtitle: str
    art: str
    text: str
    rows: list[list[tuple[str, bool]]]
    views: str = ""
    incoming: str = ""  # the user's own message above a bot card
    narrow: bool = False  # a bot card is narrower than a channel post
    composer: str = ""
    extra_css: str = field(default="", repr=False)


def _rows(keyboard) -> list[list[tuple[str, bool]]]:
    return [
        [(button.text, getattr(button, "style", None) == "primary") for button in row]
        for row in keyboard.inline_keyboard
    ]


def _album() -> TrackMatch:
    return TrackMatch(
        title="Dopesmoker",
        artist="Sleep",
        kind="album",
        release_year="2003",
        duration_ms=63 * 60 * 1000,
        genre="Stoner Rock",
        links={
            "spotify": "https://open.spotify.com/album/5ZRa6b3ZnUfMZsCZbUMJyD",
            "appleMusic": "https://music.apple.com/us/album/dopesmoker/1440898613",
            "youtubeMusic": "https://music.youtube.com/playlist?list=OLAK5uy_example",
        },
        page_url="https://album.link/s/5ZRa6b3ZnUfMZsCZbUMJyD",
        thumbnail_url="https://i.scdn.co/image/dopesmoker",
    )


def channel_post() -> Screen:
    album = _album()
    quote = f"{QUOTE} Час одного риффа — и ни минуты лишней."
    keyboard = _build_link_keyboard(
        album.links,
        release_page_url=album.page_url,
        release_kind=album.kind,
        release_format=album.release_format,
    )
    return Screen(
        title="StonerHand",
        subtitle="канал · музыка без суеты",
        art="cover.png",
        text=f"<blockquote>{quote}</blockquote>\n\n{format_track_message(album)}",
        rows=_rows(keyboard),
        views="1,2K 👁 21:00",
    )


def draft_card() -> Screen:
    album = _album()
    context = SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"admin_chat_id": 7, "timezone_name": "Europe/Moscow"}
        )
    )
    draft = new_track_draft(album, chat_id=7, lang="ru", can_publish=True)
    draft["prefix"] = f"<blockquote>{QUOTE}</blockquote>\n\n"
    draft["quote"] = True
    draft["revision"] = 1
    text, keyboard = render_track_draft(draft, context, draft_id="demo")
    return Screen(
        title="StonerHand Bot",
        subtitle="бот",
        art="cover.png",
        text=text,
        rows=_rows(keyboard),
        incoming=f"{QUOTE}\n<a>open.spotify.com/album/5ZR…</a>",
        narrow=True,
        composer="Ссылка или «артист — трек»",
    )


def collection_post() -> Screen:
    def song(artist: str, title: str, index: int) -> TrackMatch:
        url = f"https://open.spotify.com/track/{index}"
        return TrackMatch(
            title=title,
            artist=artist,
            links={"spotify": url},
            page_url=f"https://song.link/s/{index}",
            thumbnail_url=f"https://i.scdn.co/image/{index}",
        )

    def clip(title: str, author: str, index: int) -> VideoMatch:
        return VideoMatch(
            title=title,
            author=author,
            url=f"https://www.youtube.com/watch?v=clip{index:07}",
        )

    songs = [song("Kyuss", "Gardenia", 1), song("Deftones", "Rickets", 2)]
    clips = [
        clip("Sleep — Dragonaut (Official Video)", "Sleep", 3),
        clip("Kyuss — Live at the Palms", "Kyuss", 4),
    ]
    return Screen(
        title="StonerHand",
        subtitle="канал · музыка без суеты",
        art="collage.png",
        text=format_mixed_collection_message(songs, clips, title="Тяжёлый вечер"),
        rows=_rows(_build_mixed_collection_keyboard(songs, clips)),
        views="864 👁 22:15",
    )


def series_card() -> Screen:
    title = TitleMatch(
        title="Cyberpunk: Edgerunners",
        url="https://www.netflix.com/title/81054853",
        watch_url="https://www.netflix.com/title/81054853",
        service="Netflix",
        kind="series",
        seasons=2,
        genre="Аниме",
        rating="18+",
        trailer_url="https://www.youtube.com/watch?v=JtqIas3bYhg",
        soundtrack_url="https://album.link/i/1647186913",
        image_url="https://occ-0-1.1.nflxso.net/dnm/api/v6/x/hero.jpg",
    )
    quote = "Лучший саундтрек года — и сериал под стать."
    return Screen(
        title="StonerHand",
        subtitle="канал · музыка без суеты",
        art="still.png",
        text=f"<blockquote>{quote}</blockquote>\n\n{format_title_message(title)}",
        rows=_rows(_build_title_keyboard(title, bot_username="StonerHandBot")),
        views="1,4K 👁 21:00",
    )


SCREENS = {
    "post": channel_post,
    "draft": draft_card,
    "collection": collection_post,
    "netflix": series_card,
}

STYLE = """
*{box-sizing:border-box}
html,body{margin:0;width:420px;height:860px;background:#0e1621;overflow:hidden}
body{display:flex;flex-direction:column;color:#fff;-webkit-font-smoothing:antialiased;
  font:17px/1.32 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",sans-serif}
header{height:68px;flex:none;background:#17212b;display:flex;align-items:center;
  gap:12px;padding:0 16px}
header img{width:40px;height:40px;border-radius:50%}
header b{display:block;font-size:17px;font-weight:600}
header span{display:block;font-size:13px;color:#7d8b99}
main{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:flex-end;
  padding:0 12px 12px}
.incoming{align-self:flex-end;max-width:262px;margin-bottom:6px;background:#2b5278;
  border-radius:16px 16px 6px 16px;padding:8px 12px;font-size:15px;white-space:pre-line}
.incoming a{color:#8fc7ff}
.reaction{align-self:flex-end;margin-bottom:10px;background:#223544;border-radius:12px;
  padding:1px 8px;font-size:13px}
.incoming,.reaction,.card,.rows{flex:none}
.card{background:#182533;border-radius:16px 16px 16px 6px;overflow:hidden}
.narrow{width:310px}
.card img{display:block;width:100%}
.text{padding:12px 14px 2px;font-size:15px}
.text p{margin:0 0 9px}
.text b{font-weight:600}
blockquote{margin:0 0 10px;padding:6px 10px;background:#203346;
  border-left:3px solid #6ab3f3;border-radius:4px}
.text code{font:14px ui-monospace,"SF Mono",Menlo,monospace;color:#12e2b0}
.text a{color:inherit;text-decoration:none}
.tag{color:#6ab2f2}
.muted{color:#aab8c5}
.views{padding:0 14px 8px;text-align:right;font-size:12px;color:#6d7f8f}
.rows{display:flex;flex-direction:column;gap:6px;margin-top:6px}
.narrow + .rows{width:310px}
.row{display:flex;gap:6px}
.button{flex:1;min-width:0;height:42px;border-radius:10px;background:#223544;
  display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:600;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 6px}
.primary{background:#5464d5}
footer{flex:none;height:64px;padding:10px 14px}
footer div{height:44px;border-radius:22px;background:#0a1018;color:#6d7f8f;
  display:flex;align-items:center;padding:0 16px;font-size:15px}
"""


def _text_html(text: str) -> str:
    """Telegram HTML as a chat bubble shows it: tags blue, details muted."""
    blocks = []
    for block in text.split("\n\n"):
        if block.startswith("<blockquote>"):
            blocks.append(block)
            continue
        lines = []
        for line in block.split("\n"):
            if re.fullmatch(r"(#\w+ ?)+", line):
                line = f'<span class="tag">{line}</span>'
            elif "<b>" not in line and not line.startswith("<code>"):
                line = f'<span class="muted">{line}</span>'
            lines.append(line)
        blocks.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(blocks)


def page(screen: Screen) -> str:
    rows = "".join(
        '<div class="row">'
        + "".join(
            f'<div class="button{" primary" if primary else ""}">{html.escape(label)}</div>'
            for label, primary in row
        )
        + "</div>"
        for row in screen.rows
    )
    incoming = (
        f'<div class="incoming">{screen.incoming}</div><div class="reaction">🔥 1</div>'
        if screen.incoming
        else ""
    )
    views = f'<div class="views">{screen.views}</div>' if screen.views else ""
    composer = (
        f"<footer><div>{screen.composer}</div></footer>" if screen.composer else ""
    )
    narrow = " narrow" if screen.narrow else ""
    return (
        '<!doctype html><html lang="ru"><meta charset="utf-8">'
        f"<style>{STYLE}{screen.extra_css}</style>"
        f'<header><img src="{AVATAR.as_uri()}" alt=""><div><b>{screen.title}</b>'
        f"<span>{screen.subtitle}</span></div></header>"
        f'<main>{incoming}<div class="card{narrow}">'
        f'<img src="{(ART / screen.art).as_uri()}" alt="">'
        f'<div class="text">{_text_html(screen.text)}</div>{views}</div>'
        f'<div class="rows">{rows}</div></main>{composer}</html>'
    )


def fingerprint(screen: Screen) -> str:
    """What a picture shows; it changes whenever the bot's output does."""
    shown = [
        screen.title,
        screen.subtitle,
        screen.art,
        screen.text,
        screen.rows,
        screen.views,
        screen.incoming,
        screen.composer,
    ]
    payload = json.dumps(shown, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def fingerprints() -> dict[str, str]:
    return {name: fingerprint(build()) for name, build in SCREENS.items()}


def render(directory: Path) -> None:
    for name, build in SCREENS.items():
        source = directory / f"{name}.html"
        source.write_text(page(build()), encoding="utf-8")
        subprocess.run(
            [
                CHROME,
                "--headless=new",
                "--hide-scrollbars",
                "--force-device-scale-factor=2",
                f"--window-size={SIZE[0]},{SIZE[1]}",
                f"--screenshot={ASSETS / f'{name}.png'}",
                source.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
        print(ASSETS / f"{name}.png")
    RECORD.write_text(json.dumps(fingerprints(), indent=2) + "\n", encoding="utf-8")


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--html", type=Path, help="write only the pages here")
    options = parser.parse_args(arguments)
    if options.html is not None:
        options.html.mkdir(parents=True, exist_ok=True)
        for name, build in SCREENS.items():
            (options.html / f"{name}.html").write_text(page(build()), encoding="utf-8")
        return
    with tempfile.TemporaryDirectory() as directory:
        render(Path(directory))


if __name__ == "__main__":
    main()
