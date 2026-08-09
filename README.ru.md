<div align="center">

# 🎧 StonerHand Soundlinks Bot

### Музыкальная ссылка → готовая публикация в Telegram

[Открыть бота](https://t.me/StonerHandBot) · [Канал](https://t.me/stonerhand) · [English](README.md) · [Архитектура](ARCHITECTURE.ru.md)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Production-000?style=flat-square&logo=vercel)
![CI](https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?style=flat-square&label=CI)

</div>

## Что умеет бот

- принимает ссылку или запрос `артист — трек`;
- находит релиз, обложку и ссылки на музыкальные площадки;
- собирает чистую Telegram-карточку с компактными кнопками;
- объединяет несколько ссылок в одну нумерованную подборку;
- собирает песню и YouTube-клип в единый медиапост;
- поддерживает встроенный редактор, черновики и недавние карточки;
- отправляет публикацию себе, в другой чат или канал;
- поддерживает очередь отложенных публикаций;
- работает inline: `@StonerHandBot артист — трек`.

Поддерживаются Spotify, Apple Music, YouTube, SoundCloud, Bandcamp, Deezer,
Tidal, Яндекс Музыка, подкасты, плейлисты Spotify и Apple Music,
Spotify-артисты и NTS Radio.

## Основной сценарий

```mermaid
flowchart LR
    A["Ссылка или название"] --> B["Поиск релиза"]
    B --> C["Карточка или подборка"]
    C --> D["Редактор в Telegram"]
    D --> E["Себе · чат · канал · очередь"]
```

Бот оставляет в карточке только полезное: обложку, исполнителя, название,
небольшое число хэштегов и кнопки площадок. Несколько ссылок не цитируются
повторно и не засоряют итоговый пост. Редактор меняет то же сообщение;
опасные действия подтверждаются, а удаление из подборки можно отменить.

## Запуск локально

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=src python -m music_links_bot
```

Минимальные переменные окружения:

```env
BOT_TOKEN=...
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
PRIMARY_PLATFORM=spotify
```

Для production также используются `SET_WEBHOOK_SECRET`,
`TELEGRAM_WEBHOOK_SECRET`, `CRON_SECRET` и Upstash Redis.

## Проверка

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src api tests
python -m pyflakes src api tests
python -m ruff check src api tests --select F,B,ASYNC,PERF
python -m bandit -q -r src api -x tests
python tests/check_dependency_pins.py
python -m json.tool vercel.json >/dev/null
```

## Структура

```text
api/                    webhook, health, настройка webhook и worker очереди
src/music_links_bot/    логика бота, провайдеры, редактор и хранение
tests/                  unit и интеграционные тесты
vercel.json             production-маршруты и cron
```

Проект работает на Vercel через Telegram webhook. Redis хранит кеш,
пользовательские сессии, черновики, подборки, историю, очередь и защиту от
повторной обработки. При недоступности Redis некритичные сценарии используют
ограниченный memory fallback.

Лицензия: [MIT](LICENSE).
