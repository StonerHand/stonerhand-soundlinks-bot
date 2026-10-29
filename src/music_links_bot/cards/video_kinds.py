"""Name a video by what it is — clip, live, lyric video — so buttons say it."""

from __future__ import annotations

import re

from music_links_bot.core.models import VideoMatch

# Order matters: "Official Lyric Video" is a lyric video, "Live Video" is live.
_KINDS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "lyric",
        "📝 Lyric video",
        re.compile(r"\blyrics?\b|lyric video|текст песни|караоке|karaoke"),
    ),
    (
        "live",
        "🎤 Live",
        re.compile(
            r"\blive\b|концерт|выступлени|живьём|живьем|\bsession\b|сессия|"
            r"tiny desk|kexp|boiler room"
        ),
    ),
    ("acoustic", "🎸 Акустика", re.compile(r"acoustic|акусти|unplugged")),
    ("visualizer", "🌀 Визуализация", re.compile(r"visuali[sz]er|визуализ")),
    ("audio", "🎧 Аудио", re.compile(r"official audio|\(audio\)|\[audio\]|аудио\b")),
    (
        "clip",
        "🎬 Клип",
        re.compile(
            r"official (?:music )?video|music video|\bmv\b|\bm/v\b|клип|"
            r"\((?:official )?video\)|\[(?:official )?video\]"
        ),
    ),
)
_DEFAULT = ("video", "📺 Видео")
_EMOJI = {kind: label.split(" ", 1)[0] for kind, label, _ in _KINDS}
_EMOJI[_DEFAULT[0]] = _DEFAULT[1].split(" ", 1)[0]


def video_kind(video: VideoMatch) -> str:
    title = " ".join(str(video.title or "").casefold().split())
    for kind, _label, pattern in _KINDS:
        if pattern.search(title):
            return kind
    return _DEFAULT[0]


_ENGLISH = {
    "acoustic": "🎸 Acoustic",
    "visualizer": "🌀 Visualizer",
    "audio": "🎧 Audio",
    "clip": "🎬 Music video",
    "video": "📺 Video",
}


def video_kind_label(kind: str) -> str:
    from music_links_bot.core.i18n import resolve_lang

    if resolve_lang(None) == "en" and kind in _ENGLISH:
        return _ENGLISH[kind]
    for name, label, _pattern in _KINDS:
        if name == kind:
            return label
    return _DEFAULT[1]


def video_kind_emoji(video: VideoMatch) -> str:
    return _EMOJI[video_kind(video)]


def video_kind_labels(videos: list[VideoMatch]) -> list[str]:
    """Short distinct labels: "🎬 Клип", "🎤 Live", "🎤 Live 2"."""
    kinds = [video_kind(video) for video in videos]
    seen: dict[str, int] = {}
    labels = []
    for kind in kinds:
        seen[kind] = seen.get(kind, 0) + 1
        label = video_kind_label(kind)
        if kinds.count(kind) > 1:
            label = f"{label} {seen[kind]}"
        labels.append(label)
    return labels
