# Music Links Telegram Bot

Telegram-бот для StonerHand: принимает ссылку на трек или альбом и возвращает аккуратный пост с кнопками на найденные музыкальные платформы.

## Возможности

- `/start`, `/help`, `/guide`, `/platforms`, `/channel`, `/id`, `/stats`
- Поддержка входящих ссылок: Spotify, Apple Music, YouTube / YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud
- Поиск ссылок через Song.link / Odesli API
- Inline-кнопки вместо голых ссылок
- Поддержка подборок из нескольких ссылок в одном сообщении
- Авто-хэштеги `#stonerhand #track`, `#stonerhand #album`, `#stonerhand #collection`
- Вариативные фразы для постов и ошибок
- Кнопка `🪨 Открыть канал`
- Локальная статистика через `/stats`
- HTML-ответ в формате:

```text
🎧 Artist - Track

выбирай свою платформу

#stonerhand #track
```

- Платформы без найденного результата не показываются
- Понятные ответы на невалидные ссылки и пустой результат

## Быстрый старт

1. Создайте и активируйте виртуальное окружение.
2. Установите зависимости:

```bash
pip install -e .
```

3. Скопируйте пример окружения:

```bash
cp .env.example .env
```

4. Заполните `.env`:

- `BOT_TOKEN` — токен Telegram-бота
- `SONGLINK_API_KEY` — необязательно, повышает лимит Song.link
- `SONGLINK_USER_COUNTRIES` — коды стран для Song.link, сейчас по умолчанию `US`
- `ADMIN_CHAT_ID` — необязательно, chat id для уведомлений об ошибках в канале

5. Запустите бота:

```bash
python -m music_links_bot
```

## Поведение

- Бот берет все поддерживаемые ссылки из сообщения.
- Одна ссылка превращается в один пост с кнопками.
- Несколько ссылок превращаются в подборку.
- Если бот добавлен админом в канал или группу и может удалять сообщения, он удалит исходное сообщение со ссылкой и опубликует оформленный пост.
- Если ссылка ведет не на трек или альбом, бот отвечает понятной ошибкой.

## Принятые допущения

- `/help` включен сразу.
- Статистика хранится локально в `data/stats.json`.
- Бот работает и в личных сообщениях, и в группах, если ему видны сообщения с ссылкой.

## Тесты

Для быстрых локальных проверок:

```bash
python -m unittest discover -s tests -v
```

## Деплой на Render

Для Telegram-бота на polling нужен `Background Worker`, потому что бот постоянно работает в фоне и не слушает HTTP-порт.

1. Загрузите проект в GitHub.
2. Откройте Render и создайте новый `Blueprint` из этого репозитория.
3. Render прочитает `render.yaml` и создаст worker `stonerhand-bot`.
4. В переменных окружения Render заполните:

- `BOT_TOKEN` - токен от BotFather
- `SONGLINK_API_KEY` - необязательно
- `SONGLINK_USER_COUNTRIES` - `US`
- `LOG_LEVEL` - `INFO`
- `ADMIN_CHAT_ID` - необязательно, ваш chat id для ошибок
- `PYTHON_VERSION` - `3.13.4`

Если создаете сервис вручную, выбирайте `Background Worker`.

- Build Command: `pip install -r requirements.txt`
- Start Command: `PYTHONPATH=src python -m music_links_bot`
