# Changelog

## 2.1.3 — 2026-10-14

- Кнопки поста легче: если у релиза одна площадка, она стоит в одном ряду с
  «🎧 Слушать трек», а не отдельной широкой полосой.
- Без фиолетового: кнопки под постами больше не выделяются цветом, чтобы не
  спорить с обложкой.
- Подборки: кнопки-номера вместо названий — «1 2 3 4», до пяти в ряд, 8 треков
  = два ряда по 4. У клипов остаётся значок: «🎬 3». В настройках «Кнопки
  подборок» можно вернуть кнопки с названиями.

## 2.1.2 — 2026-10-13

- Подряд идущие релизы одного артиста в подборке собраны под одним жирным
  заголовком: «**Mindless Self Indulgence**», ниже «02 · Pay For It» и т.д.
- Экран редактирования подборки показывает список в том же стиле, что и пост:
  «01 · **Артист** — Трек».
- Расписание очереди в документации — раз в 5 минут (288 запросов QStash в
  день вместо 480 при лимите 500).
- Превью в README перерисованы под текущий вид постов и подборок.
- +12 тестов на маршрутизацию кнопок и действия с подборкой; покрытие 81%.

## 2.1.1 — 2026-10-12

- Подборка оформлена как трек-лист альбома: «🎶 Артист» (или своё название)
  жирным, под ним «Подборка · 8 треков», затем список «01 · Трек». Если у
  всех позиций один артист, он стоит в заголовке, а не отдельной строкой.

## 2.1.0 — 2026-10-12

Итоговый выпуск: бот сверен с Bot API 10.3 и python-telegram-bot 22.8.

- **Время по часам читателя.** Время публикации в подтверждениях, очереди и
  карточке показывается в часовом поясе того, кто читает (Bot API 9.5).
- **Личные ответы в группах.** `/help` и `/channel` в группе видит только
  вызвавший; в меню группы остались только эти две команды, помеченные как
  личные (Bot API 10.2). Если Telegram откажет, ответ уйдёт обычным сообщением.
- **Неактивные кнопки.** Выбранный фильтр в «Мои посты» и выбранные варианты
  в настройках и «Виде» показаны неактивными кнопками (Bot API 10.3).
- Зависимости обновлены: python-dotenv 1.2.4, ruff 0.17, mypy 2.4, pyflakes 4,
  coverage, fakeredis, tomli. Аудит уязвимостей чистый.
- В README и описании площадок добавлен Bandcamp.

## 2.0.1 — 2026-10-12

- Пост больше не выглядит слитным: между названием и строками деталей
  (тип, год, длительность, «Из альбома») появилась пустая строка. То же для
  видео, радио, плейлистов и артистов.

## 2.0.0 — 2026-10-12

Финальный стабильный выпуск: всё, что накопилось после 1.21, плюс облегчение
кода и доводка интерфейса.

**Посты и бот**
- Современный вид постов: «Артист — Название» одной жирной строкой, под ней
  детали с иконкой; три главные площадки в одном ряду под кнопкой «Слушать».
- Видео в постах: несколько клипов или «песня + клипы» выходят одним постом
  с коллажем (кадры со значком ▶) и кнопками по типу видео — 🎬 клип, 🎤 live
  и другие.
- Живой отклик 👀 → 🔥 на ссылке, эффект 🎉 при приветствии и быстрой публикации,
  дашборд владельца в меню, команды с эмодзи.
- Новый редактор: карточка показывает пост таким, каким он выйдет; экраны
  «Текст», «Теги», «Вид», «Кнопки», «Ещё».
- Публикация: «Сейчас / Запланировать / Копию себе», человеческое время
  («завтра 18:30», «через 2 часа»), «↩️ Отменить» в течение двух минут,
  быстрая публикация и подпись на обложке в настройках.
- Все кнопки начинаются с иконки; тексты подсказок сверены с реальными кнопками.

**Скорость и надёжность**
- Меньше обращений к Redis на каждое обновление (28 → 18), ограничение
  статистики, функции Vercel рядом с базой (`iad1`).
- Очередь отложенных постов работает от Upstash QStash с проверкой подписи;
  GitHub-крон удалён.
- Подпись канала на всех обложках, включая подборки и inline.

**Код и репозиторий**
- `bot.py` разделён: `bot_lookup_flow.py` (поиск), `bot_editor.py` (редактор),
  `bot.py` (маршрутизация кнопок).
- Удалены неиспользуемые функции, экраны, к которым больше не ведут кнопки,
  и 58 строк интерфейса, которые бот не показывал.
- Новый README с превью; старые отчёты, дубли документации и чек-лист удалены.

## Ранние версии

- **1.21.0** (2026-09-23) — Кеш готовых брендированных обложек и Telegram file_id, объединение одинаковых запросов и переиспользование HTTP-соединений с корректным закрытием.
- **1.20.2** (2026-09-14) — Исправлена регрессия карточек 1.20.1: ссылки на альбом и артиста больше не принимаются за случайно оставленные исходные URL.
- **1.20.1** (2026-09-14) — Чистая обложка стала исходным выбором для новых музыкальных карточек: публикации из редактора отправляются с фото, inline и ответы в чатах…
- **1.20.0** (2026-09-13) — Гостевой вызов по упоминанию бота: ссылка в сообщении или ответе превращается в карточку без открытия редактора.
- **1.19.2** (2026-09-13) — Вернули разделитель между значком и названием релиза: «🎧 · Dig».
- **1.19.1** (2026-09-13) — Заголовок карточки начинается с небольшого значка и жирного названия релиза; исполнитель находится на следующей строке.
- **1.19.0** (2026-09-12) — Карточка получила компактный рабочий экран: изменение, добавление в подборку, превью, сохранение и отправка.
- **1.18.2** (2026-09-11) — Черновики, настройки, подборки и шаблоны читаются из актуального хранилища.
- **1.18.1** (2026-09-11) — Главная кнопка называет материал: «🎧 Слушать трек», «💿 Слушать альбом», EP, сингл, сборник, саундтрек или подкаст.
- **1.18.0** (2026-09-09) — Текст, теги, обложка и кнопки доступны сразу под постом.
- **1.17.0** (2026-09-09) — Автотеги различают трек, альбом, EP, сингл, официальный сборник, саундтрек, авторскую подборку и видео.
- **1.16.0** (2026-09-08) — Упрощены первый запуск и редактор: оформление, текст и кнопки площадок открываются отдельно, а меню отправки содержит только варианты доставки.
- **1.15.3** (2026-09-08) — Усилена проверка секретов webhook и подписей коллажей: некорректные строки отклоняются без ошибки сервера.
- **1.15.2** (2026-09-05) — Полным Classic-подборкам из 2–6 релизов возвращён единый квадратный коллаж: число обложек теперь соответствует числу найденных релизов, если у…
- **1.15.1** (2026-09-05) — Авторская подводка больше не теряется у сообщений с несколькими музыкальными ссылками: поддерживаемые URL удаляются из текста, а остальное…
- **1.15.0** (2026-09-05) — Исключена слепая повторная отправка после потерянного ответа Telegram: очередь помечает начатую доставку до сетевого вызова, автоматически…
- **1.14.1** (2026-09-04) — Текстовый и Apple Music fallback теперь восстанавливает прямую Spotify-ссылку через точный Deezer ISRC и адресную MusicBrainz-связь; строгий поиск…
- **1.14.0** (2026-09-04) — Главный экран получил явную навигацию: редактируемые Черновики отделены от истории Недавних, а редко используемые параметры собраны в Настройках.
- **1.13.7** (2026-09-01) — Последняя полностью обработанная подборка теперь хранится отдельным durable-снимком, поэтому следующий поиск, действие редактора, перезапуск или…
- **1.13.6** (2026-09-01) — Длинный старый inline-запрос, который Telegram Bot API обрезает на границе 256 символов, теперь восстанавливается из последней приватной операции…
- **1.13.5** (2026-09-01) — Inline-публикация восстанавливает трек, временно потерянный внешним резолвером, из сохранённой подборки её владельца.
- **1.13.4** (2026-09-01) — Неполная inline-подборка больше не является выбираемым постом.
- **1.13.3** (2026-09-01) — Подборка теперь получает штатную кнопку «Поделиться» и передаёт все релизы одним компактным inline-запросом вместо набора длинных URL.
- **1.13.2** (2026-08-31) — Заблокированы ложные Spotify-карточки из общей маркетинговой страницы `Listening is everything`: публичная страница теперь обязана содержать…
- **1.13.1** (2026-08-30) — Fixed the first-run `Deftones — Rickets` example and every equivalent text search disappearing when Songlink rejects its public lookup request.
- **1.13.0** (2026-08-30) — Turned empty inline mode into a personal discovery surface with up to three recent releases, a live fallback example and a persistent Find music…
- **1.12.0** (2026-08-30) — Rebuilt the visual hierarchy around one primary action: Songlink/Odesli owns the universal release CTA, provider shortcuts and sharing stay…
- **1.11.0** (2026-08-30) — Expanded the read-only production smoke contract with RU/EN home screens, editor actions and settings.
- **1.10.1** (2026-08-30) — Removed Spotify branding and SEO phrases such as `Album by … | Spotify` from release, artist and playlist names.
- **1.10.0** (2026-08-29) — Added one final publication contract shared by Classic, Rich, inline, channel, photo/audio and editor delivery.
- **1.9.2** (2026-08-29) — Removed clickable Spotify, Apple Music and other supported source links from author intros when Telegram hides them behind linked text; meaningful…
- **1.9.1** (2026-08-29) — Fixed source-URL removal when a Spotify, Apple Music or another supported music link is the first character of a message followed by an editorial…
- **1.9.0** (2026-08-29) — Split editor callbacks and native Force Reply handling into focused state and input modules while preserving the existing Telegram interaction…
- **1.8.2** (2026-08-28) — Removed the legacy compatibility surface from the central bot module: command, inline, lookup and UI symbols are now imported directly from their…
- **1.8.1** (2026-08-28) — Removed synthetic Spotify search buttons: a platform now appears only when the resolver returned a direct release URL for that exact card.
- **1.8.0** (2026-08-28) — Added signed, cached 2–4-cover collages to classic collection link previews; duplicate or unavailable artwork falls back to the existing…
- **1.7.0** (2026-08-26) — Fixed the publication pipeline so the editor's hashtag choice is respected identically in preview, direct send, channel publishing and queued…
- **1.6.1** (2026-08-26) — Fixed incorrect automatic genre hashtags caused by trusting the first relevance-ranked Apple Search result without verifying its artist or title.
- **1.6.0** (2026-08-25) — Added cancellable lookup progress with a Classic-client fallback and cross-instance request generations, so a cancelled or superseded search can…
- **1.5.0** (2026-08-25) — Hardened the release pipeline: CI now runs the complete configured Ruff ruleset, verifies deterministic formatting and executes the full pytest…
- **1.4.4** (2026-08-25) — Restored large artwork in shared track cards: inline delivery now selects Rich Message only when a reusable Telegram cover `file_id` is available…
- **1.4.3** (2026-08-25) — Restored the All platforms action and made Spotify tracks resolve to a real canonical `song.link/s/<id>` page even while metadata uses the Spotify…
- **1.4.2** (2026-08-25) — Hid the misleading release-hub action when its destination duplicates a Spotify or another platform button, including tracking URL variants.
- **1.4.1** (2026-08-25) — Hardened durable draft migration: unknown future fields and unsafe URLs no longer break strict release reconstruction after a Redis cold start.
- **1.4.0** (2026-08-24) — Expanded the Telegram-native composer: uploaded audio becomes an editable publication, and any release card can use a user-supplied cover.
- **1.3.0** (2026-08-24) — Added a Bot API 10.3 compatibility gateway for Rich Messages, Rich drafts, in-place Rich edits and the new ephemeral-message parameter contract.
- **1.2.0** (2026-08-20) — Rebuilt the native card actions around one unmistakable primary button and neutral secondary controls; editor screens now use one accent action each.
- **1.1.4** (2026-08-12) — Made multi-link resolution source-accountable: every unique input now has exactly one ordered status and complete-cache entries must match every item.
- **1.1.3** (2026-08-12) — Recovered Spotify releases that Song.link misses in its primary region by checking bounded secondary regions and stable public Spotify page metadata.
- **1.1.2** (2026-08-12) — Protected health-to-worker calls with a stable purpose-specific secret when the Vercel `CRON_SECRET` variable exists but has an empty value.
- **1.1.1** (2026-08-12) — Derived the protected queue-worker origin from Telegram's registered HTTPS webhook when optional Vercel hostname variables are absent.
- **1.1.0** (2026-08-12) — Removed durable-queue processing from Telegram's webhook request path; queue work now stays in the dedicated protected worker.
- **1.0.0** (2026-08-12) — Native card builder with explicit style, text, hashtags, services, preview and delivery screens.
