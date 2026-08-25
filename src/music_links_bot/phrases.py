from __future__ import annotations

import hashlib

PHRASES = {
    "no_url": (
        "Пришли музыкальную ссылку или напиши артист — название.",
        "Не вижу музыкальной ссылки. Вставь URL или название релиза.",
        "Нужна ссылка на релиз или запрос в формате артист — трек.",
    ),
    "service_unavailable": (
        "Музыкальный сервис временно не отвечает. Попробуй ещё раз.",
        "Не удалось получить площадки. Повтори запрос чуть позже.",
        "Поиск сейчас недоступен. Ссылка не потеряна — просто повтори.",
    ),
    "not_found": (
        "Релиз не найден. Проверь ссылку или уточни название.",
        "Не удалось сопоставить релиз с площадками. Попробуй другую ссылку.",
        "Подходящего релиза нет. Уточни исполнителя и название.",
    ),
}


def pick_phrase(key: str, seed: str | None = None) -> str:
    phrases = PHRASES[key]
    if seed is None:
        return phrases[0]

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(phrases)
    return phrases[index]
