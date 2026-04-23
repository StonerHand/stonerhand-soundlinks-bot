# Music Links Telegram Bot

StonerHand music bot: кинул ссылку на релиз, получил аккуратный Telegram-пост со всеми найденными стримингами.

Бот сделан для канала [@stonerhand](https://t.me/stonerhand), но спокойно работает и в личке, и в группах, и в каналах.

## Что умеет

- Принимает ссылки на треки и альбомы
- Собирает найденные платформы через Song.link / Odesli API
- Показывает Spotify, Apple Music, YouTube Music, Deezer, Tidal и Yandex Music
- Делает inline-кнопки вместо голых URL
- Поддерживает подборки из нескольких ссылок в одном сообщении
- Для одиночного релиза показывает прямые кнопки платформ
- Для подборок делает одну Song.link-кнопку на каждый релиз
- Поддерживает треки, альбомы и подкасты
- Добавляет автохэштеги `#stonerhand #track`, `#stonerhand #album`, `#stonerhand #collection`
- Может добавить `#single`, `#ep` и `#podcast`, если формат удалось определить
- Использует разный стиль для треков, альбомов и подборок
- Добавляет редакторскую верхнюю строку вида `@username: текст`, если в сообщении есть подпись
- Меняет фразы в постах и ошибках, чтобы бот не звучал как скучный автоответчик
- Добавляет кнопку `🪨 Открыть канал`
- Может удалить исходную ссылку в группе/канале и заменить ее красивым постом, если у бота есть права админа
- Ведет локальную статистику через `/stats`
- Для админа показывает, кто и в каких чатах пользуется ботом

## Поддерживаемые ссылки

Входящие ссылки:

- Spotify
- Apple Music
- YouTube / YouTube Music
- Deezer
- Tidal
- Yandex Music
- SoundCloud
- Подкаст-ссылки поддерживаются через совместимые с Song.link платформы

Исходящие платформы:

- Spotify
- Apple Music
- YouTube Music
- Deezer
- Tidal
- Yandex Music

## Пример поста

```text
@username: «немного тревоги на вечер»

📻 · Youth Code - Transitions

ссылки готовы, звук ждет

#stonerhand #track
```

Под постом бот добавляет:

- для трека или альбома - прямые кнопки платформ и кнопку канала
- для подкаста - прямые кнопки найденных платформ и кнопку канала
- для подборки - одну кнопку на каждый релиз с переходом на Song.link и кнопку канала

## Команды

- `/start` - запуск и короткое приветствие
- `/help` - помощь
- `/guide` - инструкция, которую можно закрепить в группе или канале
- `/platforms` - список поддерживаемых сервисов
- `/channel` - ссылка на канал
- `/id` - показать chat id, нужен для `ADMIN_CHAT_ID`
- `/stats` - статистика найденных релизов

## Локальный запуск

Создайте окружение:

```bash
python3 -m venv .venv
```

Активируйте его:

```bash
source .venv/bin/activate
```

Установите зависимости:

```bash
pip install -r requirements.txt
```

Скопируйте пример настроек:

```bash
cp .env.example .env
```

Заполните `.env`:

```env
BOT_TOKEN=your-telegram-bot-token
SONGLINK_API_KEY=
SONGLINK_USER_COUNTRIES=US
LOG_LEVEL=INFO
ADMIN_CHAT_ID=
PRIMARY_PLATFORM=spotify
```

Если заполнить `ADMIN_CHAT_ID` своим chat id, команда `/stats` будет показывать расширенную приватную статистику: топ пользователей, топ чатов и дату последнего использования. Тексты сообщений и ссылки не сохраняются.

Запустите бота:

```bash
PYTHONPATH=src python -m music_links_bot
```

На Mac остановка локального бота: `Control + C`.

## Railway Deploy

Railway подходит для запуска polling-бота без открытого терминала на компьютере.

1. Загрузите проект в GitHub
2. В Railway выберите `New Project`
3. Выберите `Deploy from GitHub repo`
4. Подключите репозиторий
5. В `Variables` добавьте переменные окружения

Обязательная переменная:

- `BOT_TOKEN` - токен от BotFather

Рекомендуемые переменные:

- `SONGLINK_USER_COUNTRIES=US`
- `LOG_LEVEL=INFO`
- `PYTHON_VERSION=3.13.4`

`railway.toml` уже содержит команды:

```bash
pip install -r requirements.txt
```

```bash
PYTHONPATH=src python -m music_links_bot
```

Если в логах есть `Deployment successful`, бот запущен.

## Render Deploy

Для Render нужен `Background Worker`, потому что бот работает через polling и не слушает HTTP-порт.

Render может попросить карту для worker-сервиса. Если карта не подходит, используйте Railway.

Если все же деплоите на Render, `render.yaml` уже готов:

- Build Command: `pip install -r requirements.txt`
- Start Command: `PYTHONPATH=src python -m music_links_bot`

## Тесты

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Важные заметки

- Не коммитьте `.env` и токены в GitHub
- Если бот не отвечает после деплоя, сначала проверьте `BOT_TOKEN` в переменных окружения
- Для приватной статистики добавьте `ADMIN_CHAT_ID` в переменные окружения
- `PRIMARY_PLATFORM` позволяет выбрать приоритетную платформу для preview и порядка кнопок, например `spotify`, `appleMusic`, `applePodcasts` или `yandexMusic`
- Если в одном сообщении несколько ссылок, бот обрабатывает их параллельно и собирает подборку быстрее
- Если бот запущен одновременно локально и на хостинге, остановите локальный процесс через `Control + C`
- Для удаления исходных сообщений в канале/группе бот должен быть админом с правом удаления сообщений
