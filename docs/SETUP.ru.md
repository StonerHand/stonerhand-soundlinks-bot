# Запуск и эксплуатация

[← Документация](README.md) · [Архитектура](ARCHITECTURE.ru.md) · [Проверка релиза](RELEASE_CHECKLIST.ru.md)

## Локально

Нужны Python 3.10+ и токен из [@BotFather](https://t.me/BotFather).
Для разработки используйте отдельного бота: polling и production webhook
одного токена не должны работать одновременно.

```bash
git clone https://github.com/StonerHand/stonerhand-soundlinks-bot.git
cd stonerhand-soundlinks-bot
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

В Windows PowerShell активация: `.venv\Scripts\Activate.ps1`;
копирование настроек: `Copy-Item .env.example .env`.

Откройте `.env`, замените `BOT_TOKEN=replace-me` своим токеном, затем выполните:

```bash
python -m music_links_bot
```

Для polling достаточно `BOT_TOKEN`; MusicBrainz и iTunes не требуют ключа.
Ключ Songlink необязателен. Без Redis состояние в памяти не гарантирует
сохранность после перезапуска. Все настройки перечислены в [.env.example](../.env.example).

## Свой канал и inline-режим

1. Добавьте бота администратором своего канала с правом публикации.
2. Укажите `ADMIN_CHAT_ID` и `PUBLISH_CHAT_ID` в окружении.
3. Проверьте часовой пояс `BOT_TIMEZONE` для отложенных постов.
4. В BotFather включите `/setinline` и задайте подсказку
   `Исполнитель — Название или ссылка`.
5. Откройте `/start`, соберите карточку и проверьте чистое превью перед отправкой.

`/settings` сохраняет язык RU / EN, оформление новых карточек и настройки
хэштегов. Настройки не переписывают существующие черновики. `/privacy` показывает
порядок удаления пользовательских данных; `/status` и `/stats` доступны администратору.

## Vercel и Redis

Подключите репозиторий к проекту Vercel с корнем в каталоге репозитория.
Маршруты и сборка уже описаны в [vercel.json](../vercel.json).

| Переменная | Назначение |
| --- | --- |
| `BOT_TOKEN` | Токен рабочего Telegram-бота |
| `TELEGRAM_WEBHOOK_SECRET` | Проверка входящих updates |
| `SET_WEBHOOK_SECRET` | Защита настройки webhook |
| `WEBHOOK_BASE_URL` | Публичный HTTPS-адрес проекта, без пути `/api` |
| `UPSTASH_REDIS_REST_URL` | REST-адрес Upstash Redis |
| `UPSTASH_REDIS_REST_TOKEN` | Токен Redis |
| `CRON_SECRET` | Защита обработчика очереди |

Секреты задаются в окружении платформы. Пример `.env.example` хранится в Git,
рабочий `.env` исключён через `.gitignore`. Старые имена `KV_REST_API_URL` и
`KV_REST_API_TOKEN` поддерживаются для совместимости.

После развёртывания зарегистрируйте webhook через защищённый `/api/set_webhook`.
Он принимает `SET_WEBHOOK_SECRET` в параметре `secret` либо `CRON_SECRET`
в заголовке Authorization. Пример второго варианта из доверенной оболочки
с уже заданными переменными окружения:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer ${CRON_SECRET}" \
  "${WEBHOOK_BASE_URL}/api/set_webhook"
```

Проверьте `/api/health`: Telegram, webhook и Redis должны быть доступны.

| Маршрут | Назначение |
| --- | --- |
| `/api/telegram` | Входящие updates Telegram с проверкой секрета |
| `/api/set_webhook` | Защищённая настройка webhook, профиля и команд |
| `/api/queue_worker` | Защищённая обработка очереди |
| `/api/health` | Диагностика, версия, commit и состояние очереди; только чтение |
| `/api/smoke` | Контракт публикаций и основных экранов без отправки сообщений |
| `/api/collage` | Совместимость со ссылками на коллажи в старых постах |

### Расписание и выпуск

[queue-worker.yml](../.github/workflows/queue-worker.yml) вызывает обработчик
каждые пять минут. Укажите одинаковый `CRON_SECRET` в Vercel и GitHub Actions;
для своего домена задайте GitHub Actions variable `QUEUE_BASE_URL`. Запустите workflow
вручную и проверьте `last_tick_at` в health. Плановые запуски GitHub могут
задерживаться; время отправки зависит от фактического запуска обработчика.
Ежедневный Vercel Cron служит резервом.

[production-canary.yml](../.github/workflows/production-canary.yml) проверяет
развёрнутый commit, состояние сервиса и контракт публикаций. Для защищённого
автоматического отката нужны GitHub secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID` и
`VERCEL_PROJECT_ID`. При создании своей копии проверьте адреса в workflow и
`CANARY_BASE_URL` в [production_canary.py](../tests/e2e/production_canary.py).

Отдельный [provider-canary.yml](../.github/workflows/provider-canary.yml)
проверяет публичные музыкальные источники каждые шесть часов. Его результат
отделён от решения об откате: сбой провайдера не означает ошибку нового кода.

### Резервные режимы

- `COLLECTION_COLLAGE_ENABLED=0` отключает коллажи и возвращает превью первого релиза.
- `BOT_SAFE_MODE=1` отключает расширенные форматы и сохраняет классические карточки.
- `RICH_MESSAGES_ENABLED`, `RICH_DRAFTS_ENABLED`, `INLINE_RICH_MEDIA_ENABLED`
  и `EPHEMERAL_GROUP_REPLIES` позволяют управлять отдельными возможностями.
- `BRAND_PHOTO_FRAME=0` оставляет исходную обложку без дополнительной рамки.

## Проверить изменения

Из активированного окружения с установленными зависимостями разработки:

```bash
python -m pip check
python tests/check_dependency_pins.py
python -m pyflakes src api tests
python -m ruff check src api tests
python -m ruff format --check src api tests
python -m bandit -q -r src api -x tests
python -m pip_audit -r requirements.txt --progress-spinner off
python -m compileall -q src api tests
python -m coverage run -m pytest -q
python -m coverage report
python -m mypy
```

[CI](../.github/workflows/ci.yml) запускает тесты на Python 3.10–3.12.
Минимальное покрытие с учётом ветвлений — 72%. Проверка Mypy настроена на
четыре модуля; это не полная проверка типов всего проекта.

Проверка рабочего сервиса без отправки сообщений:

```bash
CANARY_BASE_URL=https://your-bot.example \
CANARY_EXPECT_COMMIT=$(git rev-parse HEAD) \
python tests/e2e/production_canary.py
```

Публичные контракты провайдеров: `python tests/e2e/provider_canary.py`.
Проверку с настоящими отправками `tests/e2e/telegram_canary.py --chat-id <ID>`
запускают отдельно в выделенном закрытом чате; подтверждённые тестовые сообщения
удаляются. Порядок визуальной проверки клиентов Telegram —
в [списке проверки релиза](RELEASE_CHECKLIST.ru.md).
