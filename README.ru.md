# StonerHandBot

[English version](README.md)

Telegram-бот для музыкального канала [@stonerhand](https://t.me/stonerhand). Кидаешь ссылку на трек, альбом, подкаст, YouTube-видео или несколько релизов сразу, а бот собирает аккуратный пост с кнопками.

Он не просто возвращает голые URL. Он превращает ссылку в маленькую редакторскую карточку: название, исполнитель, превью, фирменная фраза, хэштеги и кнопки.

## Что умеет

- Ищет релизы через Song.link / Odesli
- Принимает Spotify, Apple Music, Apple Podcasts, YouTube / YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud и podcast-ссылки
- Видит ссылки в обычных сообщениях и caption-подписях к медиа
- Поддерживает треки, альбомы, EP, singles, подкасты, podcast shows и подборки из нескольких ссылок
- Делает прямые кнопки для одиночного релиза
- Делает playlist-style пост для нескольких ссылок
- Оформляет обычные YouTube-ссылки как отдельные видео-посты с кнопкой и preview
- Обрабатывает как YouTube-видео только реальные видео-ссылки: `watch`, `youtu.be`, `shorts`, `live` и `embed`
- Оставляет `music.youtube.com` в музыкальном поиске через Song.link
- Молчит на обычных постах в группах и каналах, если там нет поддерживаемой музыкальной ссылки
- Подтягивает Telegram preview с приоритетной платформы
- Умеет удалять исходное сообщение в группе/канале и заменять его оформленным постом, если бот админ
- Скрывает кнопку `🪨 Открыть канал`, когда постит прямо внутри `@stonerhand`
- Добавляет автохэштеги: `#track`, `#album`, `#collection`, `#single`, `#ep`, `#podcast`, `#show`
- Показывает статистику через `/stats`
- Не хранит тексты сообщений и исходные ссылки в статистике

## Как выглядит

Одиночный трек:

```text
@username: немного тревоги на вечер

📻 · Youth Code - Transitions

ссылки готовы, звук рядом

#stonerhand #track
```

Альбом или EP:

```text
💿 · Artist - Release

альбом везде, где нужно

#stonerhand #album #ep
```

Подкаст:

```text
🎙️ · Show Name - Episode Title

выпуск на месте, кнопки ниже

#stonerhand #podcast
```

YouTube-видео:

```text
📺 · SANSAE Live Session Vol.3 - Melon
канал: SANSAE

видео на месте, можно смотреть

#stonerhand #video
```

Подборка:

```text
@username: пять вещей на вечер

сегодня в подборке:

1. 📻 · Youth Code - Transitions
2. 🎧 · Show Me The Body - Camp Orchestra
3. 💿 · The Soft Moon - Criminal

выбирай с чего начать

#stonerhand #collection #track #album
```

Кнопки у одиночного релиза:

```text
Spotify
Apple
YouTube
Yandex
🪨 Открыть канал
```

Кнопки у подборки:

```text
1. Youth Code - Transitions
2. Show Me The Body - Camp Orchestra
3. The Soft Moon - Criminal
🪨 Открыть канал
```

## Команды

- `/start` - короткое знакомство и основные кнопки
- `/help` - как пользоваться ботом
- `/guide` - инструкция для группы или канала
- `/platforms` - список поддерживаемых платформ
- `/channel` - кнопка на StonerHand
- `/id` - показать chat id для настройки `ADMIN_CHAT_ID`
- `/stats` - статистика обработанных релизов

## Переменные окружения

Создай `.env` из примера:

```bash
cp .env.example .env
```

Минимальная настройка:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
PRIMARY_PLATFORM=spotify
```

Расширенная настройка:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_API_KEY=
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
ADMIN_CHAT_ID=
PRIMARY_PLATFORM=spotify
```

Что важно:

- `BOT_TOKEN` обязателен
- `SONGLINK_API_KEY` можно оставить пустым
- `SONGLINK_USER_COUNTRIES=US` обычно дает больше международных ссылок
- `ADMIN_CHAT_ID` включает приватную статистику и админ-уведомления по ошибкам обработки в канале
- `PRIMARY_PLATFORM` управляет preview и порядком кнопок

Поддерживаемые значения `PRIMARY_PLATFORM`:

- `spotify`
- `appleMusic`
- `applePodcasts`
- `youtubeMusic`
- `deezer`
- `tidal`
- `yandexMusic`

## Локальный запуск

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

## Railway deploy

Railway запускает бота как background worker. После деплоя Mac и Zed можно закрывать, бот останется онлайн.

1. Запушь код в GitHub
2. Создай Railway project из репозитория
3. Открой сервис `worker`
4. Добавь переменную `BOT_TOKEN`
5. Добавь `SONGLINK_USER_COUNTRIES=US`
6. При желании добавь `ADMIN_CHAT_ID` и `PRIMARY_PLATFORM`
7. Дождись `Deployment successful`

`railway.toml` уже настроен:

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

## Render deploy

Render тоже возможен, но нужен `Background Worker`. На некоторых аккаунтах Render просит карту даже для бесплатных сценариев, поэтому для этого проекта Railway проще.

## Тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Архитектура

```text
src/music_links_bot/
├── bot.py        Telegram handlers, keyboards, group/channel replacement
├── songlink.py   Song.link client and release normalization
├── formatter.py  StonerHand post style, hashtags, captions
├── phrases.py    30 вариантов фраз для разных действий
├── stats.py      local stats without message text or source links
├── url_utils.py  URL extraction and platform helpers
├── config.py     environment variables
├── youtube.py    YouTube oEmbed metadata for video posts
└── constants.py  platforms and aliases
```

## Надежность

- Несколько ссылок обрабатываются параллельно
- Несколько Song.link-регионов проверяются параллельно
- Очень длинная авторская подпись аккуратно обрезается
- Слишком большие пачки ссылок ограничены, чтобы не упереться в лимиты Telegram
- Статистика пишется атомарно и защищена от параллельной записи
- Обычные посты, Instagram/TikTok/Pinterest и другие не-музыкальные ссылки в группах/каналах игнорируются без админ-спама
- YouTube-видео не требуют API-ключа: название и канал берутся через публичный oEmbed, а при сбое бот использует безопасный fallback
- YouTube-каналы и профили игнорируются, поэтому обычный `youtube.com/@channel` не запускает музыкальный поиск
- Spotify и Apple Podcasts episode/show не падают ошибкой, даже если Song.link не нашел кросс-платформенный матч
- Ошибки Song.link, rate limit и временная недоступность отделены от ситуации “релиз не найден”

## Важно

- Никогда не коммить `.env` и токен бота
- Если бот не отвечает после деплоя, первым делом проверь `BOT_TOKEN` в Railway Variables
- Если бот запущен локально и на Railway одновременно, могут быть конфликты polling
- Для автозамены постов в канале нужны права админа на удаление сообщений
- `/stats` хранит только счетчики, ids, labels и last seen, без текстов переписок и без исходных ссылок
