<p align="center">
  <img src="src/music_links_bot/assets/brandmark.png?v=132ca07bddeb" width="96" alt="Аватарка StonerHand: когтистая рука на белом и бирюзовом фоне">
</p>

<h1 align="center">StonerHand SoundLinks</h1>

<p align="center"><strong>Одна ссылка на музыку — готовый пост для Telegram.</strong></p>

<p align="center">
  <a href="https://t.me/StonerHandBot"><strong>Открыть бота ↗</strong></a> ·
  <a href="https://t.me/stonerhand">Канал</a> ·
  <a href="docs/SETUP.ru.md">Запуск</a> ·
  <a href="docs/README.en.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/StonerHand/stonerhand-soundlinks-bot/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/StonerHand/stonerhand-soundlinks-bot/ci.yml?branch=main&amp;style=flat-square&amp;label=CI&amp;color=12E2B0" alt="Статус CI"></a>
  <a href="https://github.com/StonerHand/stonerhand-soundlinks-bot/releases"><img src="https://img.shields.io/github/v/release/StonerHand/stonerhand-soundlinks-bot?style=flat-square&amp;color=12E2B0&amp;label=release" alt="Последний релиз"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%E2%80%933.14-12E2B0?style=flat-square" alt="Python 3.10–3.14"></a>
  <a href="https://vercel.com"><img src="https://img.shields.io/badge/Deploy-Vercel-12E2B0?style=flat-square" alt="Работает на Vercel"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-12E2B0?style=flat-square" alt="Лицензия MIT"></a>
</p>

<p align="center">
  <img src="docs/assets/hero.png" width="100%" alt="Ссылка превращается в пост с обложкой, тегами и кнопками площадок">
</p>

## ✨ Что умеет

- 🔗 **Любая ссылка или запрос.** Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, Bandcamp, Яндекс Музыка, NTS — или просто `артист — трек`.
- 🖼 **Пост с обложкой.** Обложка с подписью канала, название, год, длительность, умные теги и кнопки всех площадок.
- 🎶 **Подборки.** До 10 треков, альбомов и клипов в одном посте: общий коллаж, список «01 · Артист — Трек» и короткие кнопки.
- 🎬 **Песня + клипы.** Трек и его клипы, лайвы и lyric-видео — одним постом с кадрами в коллаже.
- ✏️ **Редактор в чате.** Свой текст, теги, вид поста и набор кнопок — без команд и форм.
- 📝 **Свой текст без обрезки.** Цитата над карточкой до ~3900 символов с жирным, курсивом и ссылками. Длинный пост уходит сообщением с обложкой крупно сверху.
- 📣 **Публикация в канал.** Сразу, по расписанию («завтра 18:30») или в одно касание; 2 минуты на отмену. Время каждый видит в своём часовом поясе.
- 👥 **Группы и каналы.** Добавьте бота администратором — присланная ссылка превратится в готовый пост; `/channel` проверит права. В группах `/help` и `/channel` отвечают только вам.
- 🎉 **Живой чат.** Реакция 👀 → 🔥 на вашу ссылку, прогресс со шкалой и музыкальными фразами, конфетти при публикации.
- ⚡ **Inline-режим.** `@StonerHandBot артист — трек` в любом чате.
- 🌍 **Русский и английский.** Язык берётся из Telegram или выбирается в настройках.

## 📱 Как выглядит

| Пост в канале | Черновик в боте | Подборка с клипами |
| :---: | :---: | :---: |
| <img src="docs/assets/post.png" width="260" alt="Пост с обложкой и кнопками площадок"> | <img src="docs/assets/draft.png" width="260" alt="Черновик с кнопками редактора"> | <img src="docs/assets/collection.png" width="260" alt="Подборка с коллажем из обложек и кадров клипов"> |

## 🚀 Как пользоваться

1. Отправьте боту ссылку или `артист — трек`. Текст над ссылкой станет текстом поста.
2. Нажмите **✏️ Изменить**, если хотите поправить текст, теги, вид или кнопки.
3. Нажмите **↗️ Поделиться** или **📣 Опубликовать** — пост уйдёт в чат или канал.

| Команда | Что делает |
| --- | --- |
| `/start` | Новый пост и меню |
| `/crate` | Моя подборка |
| `/settings` | Язык, вид и подпись |
| `/channel` | Проверить права бота в канале |
| `/help` | Как это работает |
| `/privacy` | Мои данные и их удаление |

## 🛠 Своя копия

Нужны Python 3.10+ и токен бота от [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/StonerHand/stonerhand-soundlinks-bot.git
cd stonerhand-soundlinks-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # впишите BOT_TOKEN
python -m music_links_bot
```

Для продакшена: Vercel (webhook), Upstash Redis (хранение) и Upstash QStash (очередь отложенных постов). Пошагово — в [руководстве по запуску](docs/SETUP.ru.md).

## 🧩 Как устроено

```
Telegram ──▶ Vercel /api/telegram ──▶ поиск релиза (Songlink, iTunes, MusicBrainz, YouTube)
                                   └─▶ черновик в Upstash Redis ──▶ пост в чат или канал
QStash каждые 5 мин ──▶ /api/queue_worker ──▶ отложенные публикации
```

Python, [python-telegram-bot](https://python-telegram-bot.org), serverless-функции Vercel, Telegram Bot API 10.3. CI проверяет Python 3.10–3.14: 1000+ тестов с покрытием, типы, стиль, безопасность и аудит зависимостей. Подробности — в [архитектуре](docs/ARCHITECTURE.ru.md), изменения — в [CHANGELOG](CHANGELOG.md) и [релизах](https://github.com/StonerHand/stonerhand-soundlinks-bot/releases).

## 📄 Лицензия

[MIT](LICENSE) © StonerHand

<p align="center"><a href="https://t.me/StonerHandBot"><strong>Соберите свой первый пост ↗</strong></a></p>
