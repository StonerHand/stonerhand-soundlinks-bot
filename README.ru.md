<div align="center">

# 🎧 StonerHand Soundlinks Bot

### Музыкальная ссылка → готовая Telegram-публикация

[Открыть бота](https://t.me/StonerHandBot) · [Канал](https://t.me/stonerhand) · [English](README.md) · [Архитектура](ARCHITECTURE.ru.md)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot%20%2B%20Mini%20App-26A5E4?style=flat-square&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Production-000?style=flat-square&logo=vercel)
![CI](https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?style=flat-square&label=CI)

<img src="assets/studio-demo.svg" alt="Анимация поиска, лонгрида и публикации в StonerHand Studio" width="100%">

</div>

## Возможности

| Telegram-бот | Mini App «Студия» |
| --- | --- |
| Ссылка или название → точный релиз | Поиск, кандидаты и аудиопревью |
| Чистый заголовок, обложка, хэштеги и компактные кнопки | Карточка или блочный Rich-лонгрид |
| Несколько ссылок → одна подборка со статусом каждой ссылки | Подборка до 10 релизов, сортировка и повтор только ошибок |
| Песня + YouTube-клип → двухкадровое медиапревью | Обложка песни и превью клипа |
| Inline-поиск с историей, кешем и страницами | История, очередь, отмена и аналитика |
| Автозамена ссылок в группах и каналах | Нативная отправка поста с кнопками |

Поддерживаются Spotify, Apple Music, YouTube, SoundCloud, Bandcamp, Deezer,
Tidal, Яндекс Музыка, подкасты, Spotify-плейлисты и артисты, NTS Radio.

В карточках нет случайных рекламных подписей и скрытых ссылок в заголовке:
только данные релиза, теги и действия. По умолчанию видны две приоритетные
площадки и универсальная кнопка «Все платформы». Для отправки поста вместе с
кнопками используется действие «Поделиться» в Студии.

Лонгрид отправляется как Telegram Rich Message со структурированными блоками.
Если формат недоступен, бот автоматически создаёт безопасную HTML-версию.
Песня и YouTube-клип публикуются как нативный двухкадровый альбом; видео не
скачивается и открывается в оригинале.

## Сценарий

```mermaid
flowchart LR
    A["Ссылка / название"] --> B["Точный релиз"]
    A2["Несколько ссылок"] --> C["Подборка / медиамикс"]
    B --> D["Карточка / Лонгрид"]
    C --> D
    D --> E["Чат · канал · очередь"]
```

В боте есть два режима: **«Быстро»** для поиска и готовой карточки прямо в чате
и **«Студия»** для лонгрида, подборки, очереди и публикации. Карточка в чате
оставляет только два действия — открыть Студию и добавить релиз в подборку.
Сетевые клиенты создаются лениво, независимые провайдеры работают параллельно,
а успешные результаты кешируются в памяти и Redis. У всего запроса есть общий
дедлайн, а нестабильный провайдер временно отключается после серии ошибок.
Если одна ссылка не обработана, найденная часть сохраняется, а повтор запускается
только для неудачных ссылок.

Перед публикацией бот проверяет право писать в канал. Антидубль хранит ссылку
на прежний пост и предлагает открыть его, опубликовать ещё раз либо заменить.
Владельцу доступна скрытая команда `/status`: Telegram, Redis, очередь, права,
скорость, кеш и состояние провайдеров.

## Запуск на Vercel

```dotenv
BOT_TOKEN=123456:telegram-token
SET_WEBHOOK_SECRET=long-random-secret
CRON_SECRET=another-long-random-secret
ADMIN_CHAT_ID=123456789
PUBLISH_CHAT_ID=@channel
```

1. Создай бота у [@BotFather](https://t.me/BotFather) и включи `/setinline`.
2. Импортируй репозиторий в Vercel с корнем `./`.
3. Подключи Upstash Redis из Vercel Marketplace для черновиков, очереди,
   истории, статистики и межинстансовой дедупликации.
4. Открой `https://<domain>/api/set_webhook?secret=<SET_WEBHOOK_SECRET>`.
5. Проверь `https://<domain>/api/health`: ожидаются HTTP 200 и `"ok": true`.

Все переменные перечислены в [.env.example](.env.example).

<details>
<summary><b>Локальная разработка и проверки</b></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyflakes playwright
python -m playwright install chromium
cp .env.example .env

python -m pyflakes src api tests
PYTHONPATH=src python -m unittest discover -s tests
python tests/e2e/smoke.py
```

Не запускай polling одновременно с production webhook на том же токене.

</details>

## Структура

```text
api/                    webhook, Studio API, health и queue worker
src/music_links_bot/    handlers, provider registry, публикация, очередь, Redis
webapp/                 Mini App из небольших ES-модулей без build-step
tests/                  unit/integration, мобильный smoke и production canary
```

Подробные потоки, API, Redis keyspace и правила расширения описаны в
[ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).

[MIT](LICENSE)
