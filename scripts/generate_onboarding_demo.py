from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 640
HEIGHT = 360
FPS = 10
SLIDE_SECONDS = 1.6
BACKGROUND = "#10131b"
SURFACE = "#202433"
TEXT = "#f7f7fb"
MUTED = "#aeb5c7"
ACCENTS = ("#ef7d32", "#5b61e9", "#35b65a")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


TITLE = _font(34, bold=True)
BODY = _font(23)
SMALL = _font(17, bold=True)


def _centered(draw: ImageDraw.ImageDraw, text: str, y: int, font, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((WIDTH - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def _wave(draw: ImageDraw.ImageDraw, phase: float, color: str) -> None:
    points = []
    for x in range(86, WIDTH - 86, 5):
        envelope = math.sin(math.pi * (x - 86) / (WIDTH - 172)) ** 2
        y = 68 + math.sin(x / 14 + phase) * 17 * envelope
        points.append((x, y))
    draw.line(points, fill=color, width=3)


def _frame(slide: int, progress: float) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    accent = ACCENTS[slide]
    _wave(draw, progress * math.tau, accent)
    draw.rounded_rectangle((54, 104, WIDTH - 54, 316), radius=28, fill=SURFACE)
    draw.rounded_rectangle((54, 104, 64, 316), radius=5, fill=accent)

    steps = (
        ("1", "Пришли ссылку", "или напиши: артист — трек"),
        ("2", "Проверь карточку", "обложка, теги и площадки уже готовы"),
        ("3", "Отправь пост", "себе, в чат или прямо в канал"),
    )
    number, title, body = steps[slide]
    draw.ellipse((82, 132, 134, 184), fill=accent)
    number_box = draw.textbbox((0, 0), number, font=SMALL)
    draw.text(
        (
            108 - (number_box[2] - number_box[0]) / 2,
            158 - (number_box[3] - number_box[1]) / 2 - 2,
        ),
        number,
        font=SMALL,
        fill=TEXT,
    )
    draw.text((154, 132), title, font=TITLE, fill=TEXT)
    draw.text((84, 208), body, font=BODY, fill=MUTED)

    for index in range(3):
        x0 = 250 + index * 52
        fill = accent if index == slide else "#444a5d"
        draw.rounded_rectangle((x0, 278, x0 + 34, 284), radius=3, fill=fill)
    _centered(draw, "STONERHAND · MUSIC POST BUILDER", 326, SMALL, MUTED)
    return image


def generate(output: Path) -> None:
    frames_per_slide = round(FPS * SLIDE_SECONDS)
    frames = [
        _frame(slide, index / max(1, frames_per_slide - 1))
        for slide in range(3)
        for index in range(frames_per_slide)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=round(1000 / FPS),
        loop=0,
        optimize=True,
        disposal=2,
    )


if __name__ == "__main__":
    generate(
        Path(__file__).resolve().parents[1]
        / "src"
        / "music_links_bot"
        / "assets"
        / "onboarding-demo.gif"
    )
