<div align="center">

# 🎧 StonerHand Soundlinks Bot

### Кидаешь ссылку — получаешь идеальный пост

**Трек, альбом, плейлист, подкаст, YouTube или NTS Radio → карточка с обложкой,
автохэштегами и кнопками всех стриминговых площадок. В один тап.**

[English](README.md) · [Архитектура](ARCHITECTURE.ru.md) · [Бот](https://t.me/StonerHandBot) · [Канал](https://t.me/stonerhand)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot%20+%20Mini%20App-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-Serverless-000000?style=for-the-badge&logo=vercel&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge)

<img src="assets/studio-demo.svg" alt="Демо Студии: поиск → винил → карточка с кнопками платформ" width="100%">

</div>

```text
вход   →  https://open.spotify.com/track/...   (или просто «black sabbath paranoid»)

выход  →  📻 · Black Sabbath
          Paranoid

          кнопки ниже, трек ждет

          #stonerhand #track #heavymetal

          [🟢 Spotify] [⚪ Apple] [🟦 Deezer] [⚫ Tidal]
          [🪩 Все платформы]
```

## Что умеет

- 🎛 **Студия** — Mini App внутри Telegram: живой предпросмотр, выбор из нескольких найденных релизов, ▶ 30-сек прослушка прямо на обложке, свой текст и хэштеги, набор и порядок кнопок платформ, ↗️ шаринг в любой чат
- 🧺 **Конструктор подборок** — кидай треки «➕ В подборку», меняй порядок и публикуй один пост-плейлист
- 📸 **Фото-режим** — пост уходит фотографией с подписью: обложка всегда сверху на любом клиенте
- 🎨 **Живой акцент** — интерфейс карточки подкрашивается доминирующим цветом обложки
- 🕒 **Отложенный постинг** — «Запланировать» в Студии: пост сам уйдёт в канал в выбранное время, очередь видна и отменяема
- 🕘 **История** — последние релизы на главном экране Студии с пометкой «уже в канале»
- 📊 **Дашборд** — статистика с графиками прямо в Mini App (для админа)
- 🔎 **Поиск без ссылки** — напиши `артист - трек`, бот сам найдёт релиз
- 🪄 **Inline** — `@StonerHandBot запрос` в любом чате → выбор из трёх релизов с обложками
- 🎚 **Редактор** — хэштеги, цитата, размер превью, 📤 в канал — прямо под постом
- 🛡 **Антидубль** — предупредит, если релиз уже публиковался в канале
- 🏷 **Жанры сами** — `#doom`, `#hiphop` из метаданных iTunes
- 📚 **Подборки** — несколько ссылок → нумерованный пост-плейлист
- 🤖 **Автопилот каналов** — бот-админ молча заменяет сырые ссылки на посты
- ⚡ **Живая загрузка** — «⏳ собираю пост…» превращается в карточку, ноль мёртвых пауз
- 🚀 **Serverless-скорость** — тёплые инстансы, общий Redis-кеш, повторы почти мгновенны
- 🔁 **Самовосстановление** — ежедневный cron сам чинит webhook, меню и описания
- 🌍 **RU/EN** — интерфейс подстраивается под язык пользователя

Пересланный пост не теряет смысла: CTA-фраза — живая ссылка на song.link со всеми площадками
(кнопки при пересылке съедает сам Telegram, у всех ботов).

## Быстрый старт (Vercel, ~10 минут)

1. Форкни репозиторий → импортируй в [Vercel](https://vercel.com) (пресет Python, корень `./`)
2. Добавь env: `BOT_TOKEN`, `SET_WEBHOOK_SECRET` (любая длинная строка), `CRON_SECRET`
3. Deploy → открой `https://<домен>/api/set_webhook?secret=<твой секрет>`
4. В [@BotFather](https://t.me/BotFather): `/setinline` → включи inline-режим
5. Готово. Кидай боту ссылку

<details>
<summary><b>⚙️ Все переменные окружения</b></summary>

| Переменная | Зачем |
| --- | --- |
| `BOT_TOKEN` ⭐ | токен из BotFather |
| `SET_WEBHOOK_SECRET` ⭐ | защита `/api/set_webhook` |
| `CRON_SECRET` | ежедневное самовосстановление webhook через Vercel Cron |
| `UPSTASH_REDIS_REST_URL/TOKEN` | Redis: общий кеш, живой `/stats`, вечные черновики, антидубль, история и очередь Студии |
| `ADMIN_CHAT_ID` | твой chat id (команда `/id`): приватная статистика + право 📤 |
| `PUBLISH_CHAT_ID` | куда постит 📤 (по умолчанию `@stonerhand`) |
| `PRIMARY_PLATFORM` | какая площадка первая: `spotify`, `appleMusic`, `tidal`… |
| `SONGLINK_USER_COUNTRIES` | регионы Song.link через запятую, например `US,DE` |
| `BOT_UI_MODE` | стиль кнопок: `stonerhand` / `minimal` / `editorial` |
| `TELEGRAM_WEBHOOK_SECRET` | подпись входящих updates (не задан — выводится из токена автоматически) |
| `WEBAPP_URL`, `WEBHOOK_BASE_URL`, `STATS_PATH`, `LOG_LEVEL` | тонкая настройка |

Алиасы Vercel KV (`KV_REST_API_URL/TOKEN`) тоже работают. Без Redis всё живёт в памяти.
</details>

<details>
<summary><b>🚂 Railway / локально (polling)</b></summary>

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m music_links_bot
```

`railway.toml` уже в репозитории. Не запускай polling одновременно с Vercel-webhook — будут дубли.
</details>

## Под капотом

**Python 3.10+ · python-telegram-bot 21 · httpx · Song.link/Odesli · iTunes Search · Upstash Redis · Vercel**

```text
api/telegram.py      webhook + тёплый reuse приложения
api/webapp.py        API Студии (проверка подписи initData)
api/set_webhook.py   самовосстановление: webhook, команды, описания, кнопка меню
webapp/index.html    Mini App «Студия»
src/music_links_bot/
  bot.py             роутинг, клавиатуры, редактор, inline, черновики
  songlink.py        кроссплатформенные ссылки + обложки + Redis-кеш
  search.py          поиск по названию и жанры (iTunes)
  kvstore.py         Redis по REST, мягкая деградация
  i18n.py            RU/EN интерфейс
  formatter.py       макет постов, хэштеги, CTA
  …и ещё дюжина маленьких модулей с одной задачей у каждого
```

Полная карта — в [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).

```bash
PYTHONPATH=src python -m pytest tests/   # 230 тестов, без сети
```

## Свой канал вместо StonerHand

`constants.py` (канал, площадки) → `phrases.py` (голос) → `formatter.py` (макет) →
`.env` (`PUBLISH_CHAT_ID`, `PRIMARY_PLATFORM`). Всё брендовое собрано в этих файлах.

<details>
<summary><b>🚑 Если что-то не работает</b></summary>

| Симптом | Лечение |
| --- | --- |
| Бот молчит | Проверь `BOT_TOKEN` в env хостинга |
| Кнопки меню не реагируют | Открой `/api/set_webhook?secret=…` (или дождись ночного cron) |
| Посты дублируются | Работают и polling, и webhook — выключи один |
| В канале не заменяет ссылку | Дай боту право удалять сообщения |
| `/stats` по нулям | Подключи Redis (Upstash, бесплатно) |
| Inline не работает | `/setinline` в BotFather + один вызов `/api/set_webhook` |
| Отложенный пост опаздывает | Очередь тикает на любой активности бота; для точности до минуты пингуй `GET /api/webapp` каждые 5 мин (UptimeRobot, бесплатно) |
| Корень сайта отдаёт 404 | Так и задумано: живые пути — `/app` и `/api/*` |

</details>

## Лицензия

[MIT](LICENSE) — форкай, переделывай, запускай для своего канала. 🤘
