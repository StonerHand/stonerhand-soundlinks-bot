from __future__ import annotations

RU = "ru"
EN = "en"
_RU_FAMILY_PREFIXES = ("ru", "uk", "be", "kk")


def resolve_lang(language_code: str | None) -> str:
    """Interface language for a user. Post bodies keep the RU editorial voice;
    this only routes menus, hints, errors and editor controls."""
    if not language_code:
        return RU

    return RU if language_code.casefold().startswith(_RU_FAMILY_PREFIXES) else EN


def get_text(lang: str, key: str) -> str:
    entry = STRINGS[key]
    return entry.get(lang) or entry[RU]


def get_texts(lang: str, key: str) -> tuple[str, ...]:
    entry = TEXT_TUPLES[key]
    return entry.get(lang) or entry[RU]


TEXT_TUPLES: dict[str, dict[str, tuple[str, ...]]] = {
    "loading": {
        RU: (
            "⏳ Собираю пост…",
            "🔍 Ищу площадки…",
            "🎧 Ловлю релиз…",
            "📀 Раскладываю по сервисам…",
        ),
        EN: (
            "⏳ Building the post…",
            "🔍 Hunting for platforms…",
            "🎧 Catching the release…",
            "📀 Sorting the services…",
        ),
    },
}

STRINGS: dict[str, dict[str, str]] = {
    "start_new": {
        RU: (
            "🎧 <b>Соберём музыкальный пост за минуту</b>\n\n"
            "Пришли ссылку или напиши <i>артист — трек</i>. Я найду релиз, "
            "соберу площадки и дам выбрать карточку или блочный лонгрид.\n\n"
            "Начать можно с короткого знакомства или сразу с поиска 👇"
        ),
        EN: (
            "🎧 <b>Build a music post in a minute</b>\n\n"
            "Send a link or type <i>artist — track</i>. I will find the release, "
            "collect its platforms and let you choose a card or block-based longread.\n\n"
            "Take the quick tour or jump straight into search 👇"
        ),
    },
    "home_title_new": {
        RU: "🎚 <b>StonerHand Studio</b>",
        EN: "🎚 <b>StonerHand Studio</b>",
    },
    "home_title": {
        RU: "🎚 <b>Твоя Студия{name}</b>",
        EN: "🎚 <b>Your Studio{name}</b>",
    },
    "home_body": {
        RU: (
            "{greeting}\n\n"
            "Пришли ссылку или <code>артист — трек</code> — я соберу готовую карточку.\n"
            "<i>{mode}</i>"
        ),
        EN: (
            "{greeting}\n\n"
            "Send a link or type <code>artist — track</code> and I will build the card.\n"
            "<i>{mode}</i>"
        ),
    },
    "home_mode_admin": {
        RU: "Оформление и публикация — в Студии",
        EN: "Formatting and publishing are in Studio",
    },
    "home_mode_user": {
        RU: "Оформление и лонгриды — в Студии",
        EN: "Formatting and longreads are in Studio",
    },
    "start_returning": {
        RU: "🎧 <b>Что собираем сегодня?</b>\n\nПришли ссылку, название релиза или открой Студию.",
        EN: "🎧 <b>What are we building today?</b>\n\nSend a link, a release name or open Studio.",
    },
    "onboarding_1": {
        RU: (
            "🔎 <b>Шаг 1 из 3 · Найди релиз</b>\n\n"
            "<blockquote>Пришли ссылку с музыкальной площадки или напиши\n"
            "<code>артист — название трека</code></blockquote>\n"
            "Если совпадений несколько, бот покажет варианты — останется выбрать точный."
        ),
        EN: (
            "🔎 <b>Step 1 of 3 · Find the release</b>\n\n"
            "<blockquote>Send a music-platform link or type\n"
            "<code>artist — track title</code></blockquote>\n"
            "If several releases match, the bot will show options for you to choose from."
        ),
    },
    "onboarding_2": {
        RU: (
            "🎛 <b>Шаг 2 из 3 · Выбери формат</b>\n\n"
            "<blockquote>Бот найдёт обложку, площадки и подготовит хэштеги.</blockquote>\n"
            "В чате можно быстро изменить цитату и превью. В <b>Студии</b> — "
            "собрать карточку или блочный лонгрид, настроить текст и кнопки."
        ),
        EN: (
            "🎛 <b>Step 2 of 3 · Choose the format</b>\n\n"
            "<blockquote>The bot finds artwork, platforms and prepares hashtags.</blockquote>\n"
            "Quickly change the quote and preview in chat. Use <b>Studio</b> to "
            "build a card or block-based longread and tune its text and buttons."
        ),
    },
    "onboarding_3": {
        RU: (
            "📡 <b>Шаг 3 из 3 · Отправь пост</b>\n\n"
            "<blockquote>Отправь пост себе, добавь трек в подборку или опубликуй в канал.</blockquote>\n"
            "А в любом другом чате используй inline:\n"
            "<code>@StonerHandBot артист — трек</code>"
        ),
        EN: (
            "📡 <b>Step 3 of 3 · Send the post</b>\n\n"
            "<blockquote>Send it to yourself, add the track to a crate or publish to the channel.</blockquote>\n"
            "In any other chat, use inline mode:\n"
            "<code>@StonerHandBot artist — track</code>"
        ),
    },
    "quick_tour": {RU: "▶ Как всё работает", EN: "▶ How it works"},
    "quick_search": {RU: "🔎 Найти", EN: "🔎 Find"},
    "quick_mode": {RU: "⚡ Быстро", EN: "⚡ Quick"},
    "studio_mode": {RU: "🎛 Студия", EN: "🎛 Studio"},
    "open_studio": {RU: "🎛 Студия", EN: "🎛 Studio"},
    "home_crate": {RU: "🧺 Подборка · {count}", EN: "🧺 Crate · {count}"},
    "home_more": {RU: "••• Ещё", EN: "••• More"},
    "home_stats": {RU: "📊 Статистика канала", EN: "📊 Channel stats"},
    "home_queue": {RU: "🗓 Очередь", EN: "🗓 Queue"},
    "home_result": {RU: "✨ Пример поста", EN: "✨ Example post"},
    "home_back": {RU: "← Главное меню", EN: "← Main menu"},
    "next": {RU: "Дальше →", EN: "Next →"},
    "back": {RU: "← Назад", EN: "← Back"},
    "start_using": {RU: "Готово ✓", EN: "Done ✓"},
    "tab_start": {RU: "🚀 Быстрый старт", EN: "🚀 Quick start"},
    "tab_help": {RU: "❓ Помощь", EN: "❓ Help"},
    "tab_platforms": {RU: "🎛 Сервисы", EN: "🎛 Services"},
    "tab_guide": {RU: "📣 Для каналов", EN: "📣 For channels"},
    "tab_demo": {RU: "🧪 Пример поста", EN: "🧪 Example post"},
    "share_button": {RU: "↗ Поделиться ботом", EN: "↗ Share the bot"},
    "share_post": {
        RU: "↗ Поделиться",
        EN: "↗ Share",
    },
    "error_platforms_button": {RU: "Что поддерживается", EN: "What is supported"},
    "menu_start": {
        RU: (
            "🎧 <b>StonerHand Soundlinks</b>\n\n"
            "Превращаю музыкальные ссылки в аккуратные посты: "
            "обложка, название, автохэштеги и кнопки всех площадок\n\n"
            "<b>Что умею</b>\n"
            "• Трек, альбом, плейлист, артист, подкаст\n"
            "• YouTube-видео и эфиры NTS Radio\n"
            "• Поиск по названию: просто напиши <i>artist - track</i>\n"
            "• Несколько ссылок разом → нумерованная подборка\n"
            "• Подводка над ссылкой → цитата в посте\n"
            "• Студия → карточка или музыкальный Rich-лонгрид\n"
            "• Inline: набери @StonerHandBot + ссылку в любом чате\n\n"
            "Пришли ссылку или название 👇"
        ),
        EN: (
            "🎧 <b>StonerHand Soundlinks</b>\n\n"
            "I turn music links into clean posts: cover art, title, "
            "smart hashtags and buttons for every platform\n\n"
            "<b>What I can do</b>\n"
            "• Track, album, playlist, artist, podcast\n"
            "• YouTube videos and NTS Radio shows\n"
            "• Search by name: just type <i>artist - track</i>\n"
            "• Several links at once → a numbered collection\n"
            "• Text above a link → a quote in the post\n"
            "• Studio → a card or a music Rich longread\n"
            "• Inline: type @StonerHandBot + a link in any chat\n\n"
            "Send a link or a name 👇"
        ),
    },
    "menu_help": {
        RU: (
            "❓ <b>Как собрать пост</b>\n"
            "<i>Три шага — и карточка готова.</i>\n\n"
            "<blockquote><b>1 · Найди релиз</b>\n"
            "Пришли ссылку или напиши <code>артист — трек</code>.\n\n"
            "<b>2 · Проверь карточку</b>\n"
            "Бот добавит обложку, хэштеги и кнопки площадок.\n\n"
            "<b>3 · Отправь</b>\n"
            "Себе, в подборку, очередь или канал.</blockquote>\n\n"
            "<b>Полезные приёмы</b>\n"
            "• Текст над ссылкой станет <i>цитатой</i>.\n"
            "• Несколько ссылок превратятся в нумерованную подборку.\n"
            "• Форматирование подводки сохранится.\n\n"
            "<blockquote>⚡ Inline в любом чате:\n"
            "<code>@StonerHandBot Black Sabbath — Paranoid</code></blockquote>"
        ),
        EN: (
            "❓ <b>How to build a post</b>\n"
            "<i>Three steps and the card is ready.</i>\n\n"
            "<blockquote><b>1 · Find a release</b>\n"
            "Send a link or type <code>artist — track</code>.\n\n"
            "<b>2 · Check the card</b>\n"
            "The bot adds artwork, hashtags and platform buttons.\n\n"
            "<b>3 · Send it</b>\n"
            "To yourself, a crate, the queue or your channel.</blockquote>\n\n"
            "<b>Useful shortcuts</b>\n"
            "• Text above a link becomes a <i>quote</i>.\n"
            "• Several links become a numbered collection.\n"
            "• Intro formatting is preserved.\n\n"
            "<blockquote>⚡ Inline in any chat:\n"
            "<code>@StonerHandBot Black Sabbath — Paranoid</code></blockquote>"
        ),
    },
    "menu_guide": {
        RU: (
            "📣 <b>Бот для групп и каналов</b>\n"
            "<i>Настрой один раз — дальше просто присылай музыку.</i>\n\n"
            "<blockquote><b>1 · Добавь бота</b>\n"
            "В группу или канал как администратора.\n\n"
            "<b>2 · Выдай права</b>\n"
            "На публикацию; в группе — ещё и на удаление сообщений.\n\n"
            "<b>3 · Пришли ссылку</b>\n"
            "Бот заменит её готовым музыкальным постом.</blockquote>\n\n"
            "<b>Автоматически</b>\n"
            "• подводка становится цитатой с автором;\n"
            "• добавляются хэштеги и площадки;\n"
            "• несколько ссылок собираются в подборку.\n\n"
            "<blockquote>🛡 Сначала публикуется готовый пост — и только потом удаляется исходное сообщение.</blockquote>"
        ),
        EN: (
            "📣 <b>The bot for groups and channels</b>\n"
            "<i>Set it up once, then just send music.</i>\n\n"
            "<blockquote><b>1 · Add the bot</b>\n"
            "To a group or channel as an administrator.\n\n"
            "<b>2 · Grant permissions</b>\n"
            "To publish; in groups, also to delete messages.\n\n"
            "<b>3 · Send a link</b>\n"
            "The bot replaces it with a finished music post.</blockquote>\n\n"
            "<b>Automatic touches</b>\n"
            "• intro text becomes a quote with attribution;\n"
            "• hashtags and platforms are added;\n"
            "• several links become a collection.\n\n"
            "<blockquote>🛡 The finished post is published before the original message is removed.</blockquote>"
        ),
    },
    "menu_platforms": {
        RU: (
            "🎛 <b>Поддерживаемые источники</b>\n"
            "<i>Пришли ссылку — бот сам найдёт остальные площадки.</i>\n\n"
            "<b>Музыка и подкасты</b>\n"
            "🟢 Spotify · ⚪ Apple Music / Podcasts\n"
            "🟠 SoundCloud · 🟦 Deezer\n"
            "⚫ Tidal · 🟡 Yandex Music\n\n"
            "<b>Видео и эфиры</b>\n"
            "🔴 YouTube / YouTube Music · 📡 NTS Radio\n\n"
            "<b>Типы материалов</b>\n"
            "Треки, альбомы, плейлисты, артисты, подкасты, видео и радио-шоу.\n\n"
            "<blockquote>✨ На выходе: обложка, название, автохэштеги и кнопки всех найденных площадок.</blockquote>\n\n"
            "Нет ссылки? Напиши <code>артист — трек</code>."
        ),
        EN: (
            "🎛 <b>Supported sources</b>\n"
            "<i>Send one link — the bot finds the other platforms.</i>\n\n"
            "<b>Music and podcasts</b>\n"
            "🟢 Spotify · ⚪ Apple Music / Podcasts\n"
            "🟠 SoundCloud · 🟦 Deezer\n"
            "⚫ Tidal · 🟡 Yandex Music\n\n"
            "<b>Video and radio</b>\n"
            "🔴 YouTube / YouTube Music · 📡 NTS Radio\n\n"
            "<b>Content types</b>\n"
            "Tracks, albums, playlists, artists, podcasts, videos and radio shows.\n\n"
            "<blockquote>✨ The result: artwork, title, smart hashtags and buttons for every matched platform.</blockquote>\n\n"
            "No link? Type <code>artist — track</code>."
        ),
    },
    "menu_demo": {
        RU: (
            "✨ <b>Так выглядит готовый пост</b>\n"
            "<i>Ты присылаешь ссылку — бот собирает остальное.</i>\n\n"
            "<blockquote>📻 · <b>The Soft Moon</b>\n"
            "<i>Criminal</i>\n\n"
            "<code>#stonerhand #track</code>\n\n"
            "[🟢 Spotify] [⚪ Apple]\n"
            "[🪩 Все платформы]</blockquote>\n\n"
            "<b>Внутри карточки:</b> обложка, чистый заголовок, хэштеги и компактные кнопки.\n\n"
            "Попробуй прямо сейчас: пришли ссылку или <code>название трека</code>."
        ),
        EN: (
            "✨ <b>This is a finished post</b>\n"
            "<i>You send a link — the bot builds the rest.</i>\n\n"
            "<blockquote>📻 · <b>The Soft Moon</b>\n"
            "<i>Criminal</i>\n\n"
            "<code>#stonerhand #track</code>\n\n"
            "[🟢 Spotify] [⚪ Apple]\n"
            "[🪩 All platforms]</blockquote>\n\n"
            "<b>Inside the card:</b> artwork, a tappable title, hashtags and compact buttons.\n\n"
            "Try it now: send a link or a <code>track title</code>."
        ),
    },
    "menu_more": {
        RU: (
            "••• <b>Ещё возможности</b>\n"
            "<i>Всё полезное — без перегруженного главного экрана.</i>\n\n"
            "<blockquote><b>Помощь</b> — короткая инструкция\n"
            "<b>Сервисы</b> — поддерживаемые площадки\n"
            "<b>Для каналов</b> — автозамена ссылок\n"
            "<b>Пример</b> — как выглядит готовый пост</blockquote>"
        ),
        EN: (
            "••• <b>More tools</b>\n"
            "<i>Useful extras without crowding the home screen.</i>\n\n"
            "<blockquote><b>Help</b> — a short guide\n"
            "<b>Services</b> — supported platforms\n"
            "<b>For channels</b> — automatic link replacement\n"
            "<b>Example</b> — a finished post preview</blockquote>"
        ),
    },
    "no_url_hint": {
        RU: (
            "Пришли ссылку на трек, альбом, плейлист, артиста, подкаст, "
            "YouTube-видео или NTS Radio — или просто название трека"
        ),
        EN: (
            "Send a link to a track, album, playlist, artist, podcast, "
            "YouTube video or NTS Radio — or just type a track name"
        ),
    },
    "search_not_found": {
        RU: "Ничего не нашел по этому запросу. Попробуй уточнить: артист + название",
        EN: "Found nothing for that query. Try refining it: artist + title",
    },
    "inline_hint_empty": {
        RU: "🎧 Введи артиста и трек или вставь ссылку",
        EN: "🎧 Type an artist and track or paste a link",
    },
    "inline_hint_not_found": {
        RU: "Ничего не найдено — измени запрос",
        EN: "Nothing found — refine your query",
    },
    "ed_hashtags": {RU: "# Хэштеги", EN: "# Hashtags"},
    "ed_quote": {RU: "💬 Цитата", EN: "💬 Quote"},
    "ed_on": {RU: "вкл.", EN: "on"},
    "ed_off": {RU: "выкл.", EN: "off"},
    "ed_studio": {RU: "🎛 Студия", EN: "🎛 Studio"},
    "menu_button_studio": {RU: "Студия", EN: "Studio"},
    "ed_preview": {RU: "🖼 Обложка", EN: "🖼 Cover"},
    "ed_preview_small": {RU: "компактная", EN: "compact"},
    "ed_preview_large": {RU: "крупная", EN: "large"},
    "ed_done": {RU: "Готово", EN: "Done"},
    "ed_delete": {RU: "🗑 Удалить", EN: "🗑 Delete"},
    "ed_more": {RU: "••• Ещё", EN: "••• More"},
    "ed_send_self": {RU: "Отправить себе", EN: "Send to me"},
    "ed_add_crate": {RU: "+ В подборку", EN: "+ Add to crate"},
    "ed_crate_count": {RU: "В подборке · {count}/10", EN: "In crate · {count}/10"},
    "ed_crate_added": {RU: "Добавлено · {count}/10", EN: "Added · {count}/10"},
    "ed_crate_exists": {
        RU: "Уже в подборке · {count}/10",
        EN: "Already in crate · {count}/10",
    },
    "ed_sent": {RU: "Готово — пост отправлен ниже", EN: "Done — the post is below"},
    "ed_publish": {RU: "📤 В канал", EN: "📤 To channel"},
    "ed_expired": {
        RU: "Черновик устарел — пришли ссылку заново",
        EN: "This draft has expired — send the link again",
    },
    "ed_admin_only": {
        RU: "Публиковать в канал может только владелец бота",
        EN: "Only the bot owner can publish to the channel",
    },
    "ed_published": {RU: "Опубликовано в канал 🎉", EN: "Published to the channel 🎉"},
    "ed_open_publication": {RU: "Открыть публикацию", EN: "Open publication"},
    "ed_create_more": {RU: "+ Создать ещё", EN: "+ Create another"},
    "ed_delete_confirm": {
        RU: "<b>Удалить эту карточку?</b>\n\nЧерновик исчезнет из чата. Это действие нельзя отменить.",
        EN: "<b>Delete this card?</b>\n\nThe draft will disappear from the chat. This cannot be undone.",
    },
    "ed_delete_confirm_button": {RU: "Удалить карточку", EN: "Delete card"},
    "ed_duplicate": {
        RU: "⚠️ Уже публиковалось {date}. Нажми 📤 ещё раз, чтобы опубликовать снова",
        EN: "⚠️ Already published on {date}. Tap 📤 again to publish anyway",
    },
    "ed_publish_failed": {
        RU: "Не получилось опубликовать — проверь права бота в канале",
        EN: "Could not publish — check the bot's rights in the channel",
    },
    "action_busy": {
        RU: "Это действие уже выполняется. Подожди пару секунд.",
        EN: "This action is already running. Give it a few seconds.",
    },
    "action_duplicate": {
        RU: "Уже готово — повторно ничего не отправлял.",
        EN: "Already done — nothing was sent twice.",
    },
    "retry": {RU: "Повторить", EN: "Retry"},
    "retry_failed": {
        RU: "Повторить только ошибки",
        EN: "Retry failed links",
    },
    "partial_result": {
        RU: "<b>Готово не всё</b>\n{ok} из {total} ссылок обработано. Остальные можно повторить отдельно.",
        EN: "<b>Some links need another try</b>\n{ok} of {total} links were processed. Retry only the failed ones.",
    },
    "duplicate_repeat": {
        RU: "Опубликовать снова",
        EN: "Publish again",
    },
    "duplicate_replace": {
        RU: "Заменить старый пост",
        EN: "Replace old post",
    },
    "duplicate_open": {
        RU: "Открыть старый пост",
        EN: "Open old post",
    },
    "cancel": {RU: "Отмена", EN: "Cancel"},
    "error_title": {RU: "Не получилось собрать пост", EN: "Could not build the post"},
    "error_search": {
        RU: (
            "Релиз не найден. Уточни <code>артист — название</code> "
            "или пришли прямую ссылку."
        ),
        EN: (
            "Release not found. Refine <code>artist — title</code> "
            "or send a direct link."
        ),
    },
    "error_provider": {
        RU: (
            "Музыкальный сервис временно не отвечает. Ссылка сохранена — "
            "нажми «Повторить»."
        ),
        EN: (
            "The music provider is temporarily unavailable. Your link is saved — "
            "tap Retry."
        ),
    },
    "error_provider_named": {
        RU: (
            "Сервис <b>{provider}</b> временно не отвечает. Ссылка сохранена — "
            "нажми «Повторить»."
        ),
        EN: (
            "<b>{provider}</b> is temporarily unavailable. Your link is saved — "
            "tap Retry."
        ),
    },
    "search_choose": {
        RU: "<b>Выбери релиз</b>\n\nНашёл несколько вариантов по запросу «{query}»:",
        EN: "<b>Choose a release</b>\n\nI found several matches for “{query}”:",
    },
    "search_change": {RU: "Изменить запрос", EN: "Change query"},
    "search_other": {RU: "Другой релиз", EN: "Another release"},
    "progress_search": {RU: "1/3 · Ищу релиз…", EN: "1/3 · Finding the release…"},
    "progress_links": {RU: "2/3 · Собираю площадки…", EN: "2/3 · Collecting platforms…"},
    "progress_card": {RU: "3/3 · Собираю карточку…", EN: "3/3 · Building the card…"},
    "progress_cancelled": {
        RU: "Поиск отменён — обрабатываю новый запрос.",
        EN: "Search cancelled — processing the new request.",
    },
    "crate_empty": {
        RU: (
            "🧺 <b>Подборка пока пустая</b>\n"
            "<i>Собери до десяти релизов в один музыкальный сет.</i>\n\n"
            "<blockquote>Добавляй треки кнопкой «+ В подборку» под готовой карточкой.</blockquote>"
        ),
        EN: (
            "🧺 <b>Your crate is empty</b>\n"
            "<i>Collect up to ten releases into one music set.</i>\n\n"
            "<blockquote>Add tracks with the “+ Add to crate” button under a finished card.</blockquote>"
        ),
    },
    "crate_title": {RU: "🧺 <b>Моя подборка · {count}/10</b>", EN: "🧺 <b>My crate · {count}/10</b>"},
    "crate_hint": {
        RU: "<blockquote>Выбери номер трека, чтобы изменить порядок или удалить его.</blockquote>",
        EN: "<blockquote>Select a track number to reorder or remove it.</blockquote>",
    },
    "crate_up": {RU: "↑ Выше", EN: "↑ Up"},
    "crate_down": {RU: "↓ Ниже", EN: "↓ Down"},
    "crate_remove": {RU: "✕ Удалить", EN: "✕ Remove"},
    "crate_clear": {RU: "Очистить", EN: "Clear"},
    "crate_clear_confirm": {
        RU: "<b>Очистить всю подборку?</b>\n\nВсе треки будут удалены. Отменить это действие нельзя.",
        EN: "<b>Clear the whole crate?</b>\n\nAll tracks will be removed. This cannot be undone.",
    },
    "crate_clear_confirm_button": {RU: "Очистить подборку", EN: "Clear crate"},
    "crate_undo": {RU: "Вернуть удалённый", EN: "Undo removal"},
    "crate_removed": {RU: "Трек удалён", EN: "Track removed"},
    "crate_restored": {RU: "Трек возвращён", EN: "Track restored"},
    "crate_find": {RU: "+ Найти первый трек", EN: "+ Find the first track"},
    "crate_open_studio": {RU: "🎛 Собрать сет в Студии", EN: "🎛 Build the set in Studio"},
}
