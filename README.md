# Music Links Telegram Bot

StonerHandBot превращает музыкальную ссылку в аккуратный Telegram-пост: релиз, превью, кнопки платформ, подпись автора и фирменные хэштеги.

Проект сделан для [@stonerhand](https://t.me/stonerhand), но спокойно работает в личке, группах и каналах.

## Что Это

Пользователь кидает ссылку на трек, альбом, EP, single, подборку ссылок или подкаст. Бот идет в Song.link / Odesli, находит этот же релиз на других платформах и возвращает пост в стиле канала.

Одиночный релиз получает прямые кнопки платформ. Подборка получает одну Song.link-кнопку на каждый релиз, чтобы пост не превращался в стену кнопок.

## Возможности

- Треки, альбомы, EP, single и подкасты
- Spotify, Apple Music, Apple Podcasts, YouTube Music, Deezer, Tidal, Yandex Music
- Входящие ссылки из Spotify, Apple Music, YouTube / YouTube Music, Deezer, Tidal, Yandex Music, SoundCloud и совместимых podcast-платформ
- Умный preview по приоритетной платформе
- Прямые платформенные кнопки для одного релиза
- Song.link-кнопки для подборок
- Редакторская строка `@username: текст`, если человек прислал ссылку с подписью
- Автохэштеги `#track`, `#album`, `#collection`, `#single`, `#ep`, `#podcast`
- Разные CTA-фразы для треков, альбомов, подкастов и подборок
- Параллельная обработка нескольких ссылок
- Автозамена исходного сообщения в группе или канале, если бот админ
- Локальная статистика и приватная админ-статистика через `/stats`

## Как Выглядит Пост

Один трек:

```text
@username: немного тревоги на вечер

📻 · Youth Code - Transitions

ссылки готовы, звук ждет

#stonerhand #track
```

Альбом или EP:

```text
💿 · Artist - Release

альбом на всех выходах

#stonerhand #album #ep
```

Подборка:

```text
@username: пять вещей на вечер

сегодня в подборке:

1. 📻 · Youth Code - Transitions
2. 🎧 · Show Me The Body - Camp Orchestra
3. 💿 · The Soft Moon - Criminal

выбирай, куда провалиться

#stonerhand #collection #track #album
```

Под подборкой будут кнопки:

```text
1. Youth Code - Transitions
2. Show Me The Body - Camp Orchestra
3. The Soft Moon - Criminal
🪨 Открыть канал
```

## Команды

- `/start` - короткий старт и кнопки
- `/help` - как пользоваться ботом
- `/guide` - инструкция для группы или канала
- `/platforms` - поддерживаемые платформы
- `/channel` - открыть канал StonerHand
- `/id` - показать chat id для `ADMIN_CHAT_ID`
- `/stats` - статистика релизов

## Настройки

Создайте `.env` из примера:

```bash
cp .env.example .env
```

Минимальный набор:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_API_KEY=
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
ADMIN_CHAT_ID=
PRIMARY_PLATFORM=spotify
```

`BOT_TOKEN` обязателен. `SONGLINK_API_KEY` можно оставить пустым. `ADMIN_CHAT_ID` включает приватную статистику для вашего личного чата. `PRIMARY_PLATFORM` управляет preview и порядком кнопок.

Поддерживаемые значения `PRIMARY_PLATFORM`:

- `spotify`
- `appleMusic`
- `applePodcasts`
- `youtubeMusic`
- `deezer`
- `tidal`
- `yandexMusic`

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

На Mac остановка локального процесса: `Control + C`.

## Railway Deploy

Railway запускает бота как background worker, поэтому Zed и терминал на Mac можно закрывать.

1. Залейте проект в GitHub
2. В Railway выберите `New Project`
3. Выберите `Deploy from GitHub repo`
4. Подключите репозиторий
5. В `Variables` добавьте `BOT_TOKEN`
6. При желании добавьте `ADMIN_CHAT_ID` и `PRIMARY_PLATFORM`

`railway.toml` уже содержит команды сборки и запуска:

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

Зеленый `Deployment successful` означает, что бот запущен.

## Render Deploy

Для Render нужен `Background Worker`, потому что бот работает через polling и не слушает HTTP-порт. `render.yaml` уже подготовлен, но Render может попросить карту для worker-сервиса.

## Тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Важные Детали

- `.env` и токены не должны попадать в GitHub
- Если бот не отвечает после деплоя, первым делом проверьте `BOT_TOKEN`
- Если локальный бот и Railway работают одновременно, остановите локальный процесс
- Для автозамены сообщений в канале или группе боту нужны права админа на удаление сообщений
- Тексты сообщений и ссылки не сохраняются в приватной статистике; сохраняются только счетчики, id, label и время последнего использования
