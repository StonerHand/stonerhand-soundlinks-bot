<div align="center">

# StonerHand Soundlinks Bot

**Открытый Telegram-бот, который превращает музыкальные ссылки в аккуратные посты**

[English version](README.md)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Webhook-000000?style=for-the-badge&logo=vercel&logoColor=white)
![Song.link](https://img.shields.io/badge/Song.link-Odesli-FF6B6B?style=for-the-badge)
![GitHub](https://img.shields.io/badge/GitHub-stonerhand--soundlinks--bot-181717?style=for-the-badge&logo=github&logoColor=white)

`стриминговая ссылка -> релиз -> готовый Telegram-пост`

</div>

---

## Обзор

StonerHand Soundlinks Bot собирает музыкальные ссылки в чистые Telegram-посты. Можно отправить трек, альбом, подкаст, Spotify-плейлист, Spotify-артиста, YouTube-видео или несколько ссылок сразу, а бот вернет короткую карточку с названием, preview, хэштегами и кнопками платформ.

Дефолтный стиль сделан под голос канала [@stonerhand](https://t.me/stonerhand), но архитектура специально оставлена переиспользуемой: можно заменить канал, фразы, подписи кнопок и приоритет платформ, чтобы собрать свою версию.

```text
вход
https://open.spotify.com/track/...

выход
📻 · Artist
Track

кнопки ниже, трек ждет

#stonerhand #track

[🟢 Spotify] [🌊 Tidal]
[🟦 Deezer]  [🟡 Yandex]
```

## Пользовательские Сценарии

| Поверхность | Поведение |
| --- | --- |
| Личный чат | Отвечает карточкой с кнопками |
| Группа | Может удалить исходную ссылку и заменить ее красивым постом, если есть права админа |
| Канал | Может превращать сырые ссылки в посты и молчать на обычный контент |
| Несколько ссылок | Собирает пост-подборку |
| Текст над ссылкой | Превращает текст в Telegram-цитату |

## Поддерживаемый Контент

| Тип | Источники | Как оформляется |
| --- | --- | --- |
| Трек | Spotify, Apple Music, YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud | Музыкальная карточка с кнопками платформ |
| Альбом / EP / Single | Spotify, Apple Music, Deezer, Tidal, Yandex Music, SoundCloud sets | Карточка релиза с автохэштегами |
| Подкаст / выпуск / шоу | Spotify, Apple Podcasts и podcast-ссылки, которые понимает Song.link | Podcast-карточка или fallback на одну платформу |
| Spotify playlist | Spotify playlist URL | Отдельная карточка плейлиста |
| Spotify artist | Spotify artist URL | Отдельная карточка артиста |
| YouTube-видео | `youtube.com/watch`, `youtu.be`, `shorts`, `live`, `embed`, `m.youtube.com` | Видео-карточка с кнопкой YouTube |
| Подборка | Несколько ссылок в одном сообщении | Нумерованный пост-плейлист |

## Технический Стек

| Слой | Решение |
| --- | --- |
| Runtime | Python 3.10+ |
| Telegram SDK | `python-telegram-bot` 21.x |
| HTTP client | `httpx` с connection limits и явными таймаутами |
| Музыкальный поиск | Song.link / Odesli API |
| Легкие метаданные | Spotify, YouTube и SoundCloud oEmbed |
| Деплой | Vercel webhook или Railway worker |
| Конфигурация | Environment variables и опциональный `.env` |
| Тестирование | `unittest` и compile checks |

## Почему Можно Открывать Публично

| Зона | Статус |
| --- | --- |
| Секреты | Реальные токены не коммитятся; локально используется `.env`, в проде - env variables хостинга |
| Локальные файлы | `.env`, `.venv`, stats-файлы, кеши и generated egg-info игнорируются |
| Деплой | Описаны Vercel webhook и Railway worker |
| Брендинг | StonerHand-специфика лежит в formatter/constants/phrase bank |
| Форки | Поток разделен на URL parsing, metadata clients, formatting, keyboards и transport |
| Безопасность | Setup endpoint можно закрыть через `SET_WEBHOOK_SECRET` |

## Визуальный Стиль

Главная идея: меньше шума, больше пользы. Пост должен нормально читаться на телефоне, не ломаться на desktop и не превращаться в простыню.

### Одиночный Релиз

```text
цитата от @username:
Альбом, который стоит включить целиком

💿 · Artist
Release

альбом собран, уходи слушать

#stonerhand #album

[🟢 Spotify] [🌊 Tidal]
[🟦 Deezer]  [🟡 Yandex]
```

### Подборка

```text
цитата от @username:
пять ссылок на вечер

сегодня в подборке:

1. 📻 · Youth Code - Transitions
2. 🎧 · Show Me The Body - Camp Orchestra
3. 💿 · The Soft Moon - Criminal
4. 📺 · SANSAE Live Session Vol.3 - Melon

выбирай с чего начать

#stonerhand #collection #track #album #video

[🎧 1. Youth Code] [🎧 2. Show Me The Body]
[💿 3. The Soft Moon] [📺 4. Live Session]
```

### Отдельные Карточки

```text
🎛 · Women of Punk
платформа: Spotify

пачка собрана, вход открыт

#stonerhand #playlist

[🎛 Открыть плейлист]
```

```text
🧬 · 1.Kla$
артист: Spotify

профиль открыт, можно копать глубже

#stonerhand #artist

[🧬 Открыть артиста]
```

## Архитектура

```mermaid
flowchart LR
    U["Пользователь, группа или канал"] --> T["Telegram"]
    T -->|"Webhook / Polling"| H["Вход бота"]
    H --> R["Router"]
    R -->|"Музыкальные ссылки"| S["Song.link / Odesli"]
    R -->|"Spotify playlist / artist"| O1["Spotify oEmbed"]
    R -->|"YouTube video"| O2["YouTube oEmbed"]
    R -->|"SoundCloud fallback"| O3["SoundCloud oEmbed"]
    S --> N["Нормализованный релиз"]
    O1 --> N
    O2 --> N
    O3 --> N
    N --> F["Formatter"]
    F --> K["Inline Keyboard"]
    K --> T
    R --> ST["Local Stats"]
```

## Карта Кода

```text
api/
├── telegram.py       Vercel webhook endpoint
└── set_webhook.py    установка webhook и синхронизация команд

src/music_links_bot/
├── bot.py            Telegram handlers, routing, keyboards, замена сообщений
├── songlink.py       Song.link client, fallback по регионам, нормализация релиза
├── formatter.py      макет поста, подписи, хэштеги, выбор preview
├── playlist.py       Spotify playlist metadata через oEmbed
├── artist.py         Spotify artist metadata через oEmbed
├── youtube.py        YouTube video metadata через oEmbed
├── soundcloud.py     SoundCloud metadata fallback через oEmbed
├── url_utils.py      поиск URL, нормализация, чистка tracking-параметров
├── cache.py          in-memory TTL-кеш внешних запросов
├── stats.py          privacy-safe счетчики
├── phrases.py        живые фразы для CTA и ошибок
├── constants.py      платформы, алиасы и порядок кнопок
└── config.py         настройки из переменных окружения
```

## Надежность И Скорость

| Зона | Как решено |
| --- | --- |
| Скорость | Параллельная обработка ссылок, connection pooling, короткие таймауты внешних API |
| Стабильность | Раздельная обработка not found, service unavailable и неправильного ввода |
| Дедупликация | `si`, `utm_*`, `fbclid` и похожие параметры не участвуют в cache key |
| Лимиты Telegram | Длинные подводки и большие пачки ссылок обрезаются до безопасного размера |
| Чистота каналов | Обычные посты, Instagram/TikTok/Pinterest и нерелевантные ссылки игнорируются в группах и каналах |
| Preview | Приоритетная платформа управляет preview и порядком кнопок |
| SoundCloud | Если Song.link не нашел кроссплатформенные ссылки, прямая SoundCloud-ссылка оформляется через SoundCloud oEmbed |
| Приватность | Статистика хранит счетчики и ids, но не тексты сообщений и не исходные ссылки |
| Serverless | Vercel webhook проверяет размер payload до JSON-парсинга |
| Безопасность админки | Замена сообщений происходит только если Telegram реально дал нужные права |

## Команды

| Команда | Что делает |
| --- | --- |
| `/start` | что умеет бот |
| `/help` | короткая инструкция |
| `/guide` | инструкция для каналов и групп |
| `/platforms` | поддерживаемые сервисы |
| `/channel` | открыть StonerHand |
| `/stats` | публичная статистика и приватная статистика для админа |
| `/id` | скрытая команда для получения `ADMIN_CHAT_ID` |

Публичное меню команд синхронизируется при локальном/Railway запуске и через Vercel endpoint `/api/set_webhook`.

## Переменные Окружения

Создай локальный `.env`:

```bash
cp .env.example .env
```

Минимальная production-настройка:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
PRIMARY_PLATFORM=spotify
```

Полная настройка:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_API_KEY=
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
ADMIN_CHAT_ID=
PRIMARY_PLATFORM=spotify
SET_WEBHOOK_SECRET=
STATS_PATH=
```

| Переменная | Обязательна | Зачем нужна |
| --- | --- | --- |
| `BOT_TOKEN` | да | Telegram Bot API token |
| `SONGLINK_API_KEY` | нет | Опциональный ключ Song.link |
| `SONGLINK_USER_COUNTRIES` | нет | Список регионов для fallback, `US` хороший дефолт |
| `LOG_LEVEL` | нет | `INFO`, `DEBUG`, `WARNING`, `ERROR` |
| `ADMIN_CHAT_ID` | нет | Приватная статистика и админ-уведомления |
| `PRIMARY_PLATFORM` | нет | Приоритет preview и порядка кнопок |
| `SET_WEBHOOK_SECRET` | нет | Защита `/api/set_webhook` |
| `STATS_PATH` | нет | Путь к локальному файлу статистики |

Поддерживаемые значения `PRIMARY_PLATFORM`:

```text
spotify
appleMusic
applePodcasts
youtubeMusic
soundcloud
deezer
tidal
yandexMusic
```

## Локальный Запуск

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

На Mac остановить локального бота можно через `Control + C`.

## Деплой На Vercel

Vercel - основной serverless-вариант. Telegram отправляет updates на `/api/telegram`, поэтому Mac и Zed можно закрывать.

1. Импортируй `StonerHand/stonerhand-soundlinks-bot` в Vercel
2. `Application Preset` оставь `Python`
3. `Root Directory` оставь `./`
4. Добавь production-переменные окружения
5. Нажми `Deploy`
6. После деплоя один раз открой endpoint настройки:

```text
https://your-vercel-domain.vercel.app/api/set_webhook
```

Если задан `SET_WEBHOOK_SECRET`, открывай так:

```text
https://your-vercel-domain.vercel.app/api/set_webhook?secret=your-secret
```

Если Telegram вернул `"ok": true`, webhook и меню команд подключены.

### Vercel Endpoint'ы

| Endpoint | Method | Зачем |
| --- | --- | --- |
| `/api/telegram` | `POST` | Telegram webhook receiver |
| `/api/set_webhook` | `GET` | Установка webhook и синхронизация команд |

## Деплой На Railway

Railway запускает бота как background worker через long polling.

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

В репозитории уже есть `railway.toml`. Если включен Vercel webhook, Railway/local polling лучше остановить, чтобы не было дублей.

## Тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Проверка компиляции:

```bash
python -m compileall -q src tests api
```

## Production Checklist

- `BOT_TOKEN` добавлен в переменные окружения хостинга
- Активен только один режим: Vercel webhook или Railway/local polling
- После деплоя открыт `/api/set_webhook`
- У бота есть право `Delete messages` там, где нужна автозамена постов
- `ADMIN_CHAT_ID` настроен, если нужны приватная статистика и админ-уведомления
- `SET_WEBHOOK_SECRET` задан для более безопасного setup endpoint
- Токены не попадают в git
- Токены перевыпущены, если они когда-либо попадали в публичное место

## Приватность

Бот обрабатывает ссылки, чтобы собрать музыкальный пост. Он не запрашивает пароли, платежные данные или личные файлы. Статистика минимальная: счетчики, chat ids, labels и last-seen timestamp. Тексты сообщений и исходные ссылки в статистике не хранятся.

На Vercel файловая статистика временная, если `STATS_PATH` не ведет в постоянное хранилище. Для серьезной аналитики позже лучше подключить базу данных.

## Кастомизация

Если кто-то хочет адаптировать бота под свой канал, начинать лучше отсюда:

| Файл | Что менять |
| --- | --- |
| `src/music_links_bot/constants.py` | Ссылка на канал, названия платформ, приоритет платформ |
| `src/music_links_bot/phrases.py` | Фразы CTA и ошибок |
| `src/music_links_bot/formatter.py` | Макет поста, хэштеги, стиль заголовков |
| `src/music_links_bot/bot.py` | Тексты команд, intro, поведение админа |
| `.env.example` | Дефолтные переменные для своего деплоя |

## Troubleshooting

| Симптом | Вероятная причина | Что сделать |
| --- | --- | --- |
| Бот не отвечает | Нет или неверный `BOT_TOKEN` | Проверить env variables на хостинге |
| На корневой странице Vercel `404` | Это нормально для webhook-бота | Использовать `/api/telegram` и `/api/set_webhook` |
| Telegram ходит на старый хост | Webhook не обновлен | Открыть `/api/set_webhook` на новом домене |
| Посты дублируются | Одновременно активны polling и webhook | Остановить Railway/local polling |
| В канале ссылка не заменяется | Нет прав админа | Выдать право удалять сообщения |
| Не хватает платформы | Song.link не вернул ее для региона | Попробовать другую исходную ссылку или поменять регион fallback |
| SoundCloud показывает только SoundCloud | Song.link не нашел совпадения на других платформах | Это нормальный fallback: ссылка все равно превращается в чистую карточку |

## Лицензия

Файл лицензии пока не добавлен. Если хочешь, чтобы люди свободно форкали, меняли и переиспользовали проект, лучше явно добавить MIT или Apache-2.0.
