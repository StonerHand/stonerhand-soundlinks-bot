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
            "соберу площадки и дам отредактировать карточку перед отправкой.\n\n"
            "Начать можно с короткого знакомства или сразу с поиска 👇"
        ),
        EN: (
            "🎧 <b>Build a music post in a minute</b>\n\n"
            "Send a link or type <i>artist — track</i>. I will find the release, "
            "collect its platforms and let you edit the card before sending.\n\n"
            "Take the quick tour or jump straight into search 👇"
        ),
    },
    "home_title_new": {
        RU: "🎧 <b>Твоя музыкальная мастерская</b>",
        EN: "🎧 <b>Your music post workshop</b>",
    },
    "home_title": {
        RU: "🎛 <b>Студия готова{name}</b>",
        EN: "🎛 <b>Studio is ready{name}</b>",
    },
    "home_body": {
        RU: (
            "{greeting}\n\n"
            "Ссылка или название → точный релиз → готовый Telegram-пост.\n\n"
            "<blockquote>🧺 Подборка: {crate_count}/10\n{mode}</blockquote>\n"
            "Пришли ссылку прямо сюда или выбери действие ниже."
        ),
        EN: (
            "{greeting}\n\n"
            "A link or title → the exact release → a finished Telegram post.\n\n"
            "<blockquote>🧺 Crate: {crate_count}/10\n{mode}</blockquote>\n"
            "Send a link here or choose an action below."
        ),
    },
    "home_mode_admin": {
        RU: "📡 Канал, очередь и статистика доступны",
        EN: "📡 Channel, queue and stats are available",
    },
    "home_mode_user": {
        RU: "✉️ Готовые посты можно отправлять себе",
        EN: "✉️ Finished posts can be sent to your chat",
    },
    "start_returning": {
        RU: "🎧 <b>Что собираем сегодня?</b>\n\nПришли ссылку, название релиза или открой Студию.",
        EN: "🎧 <b>What are we building today?</b>\n\nSend a link, a release name or open Studio.",
    },
    "onboarding_1": {
        RU: (
            "<b>● ○ ○  Найди точный релиз</b>\n\n"
            "Пришли ссылку с музыкальной площадки или напиши "
            "<i>артист — трек</i>. Если совпадений несколько, выберешь нужное."
        ),
        EN: (
            "<b>● ○ ○  Find the exact release</b>\n\n"
            "Send a music link or type <i>artist — track</i>. "
            "If there are several matches, you will choose the right one."
        ),
    },
    "onboarding_2": {
        RU: (
            "<b>● ● ○  Собери карточку</b>\n\n"
            "Бот найдёт обложку и площадки. В чате можно быстро поменять "
            "хэштеги и превью, а в Студии — настроить весь пост."
        ),
        EN: (
            "<b>● ● ○  Build the card</b>\n\n"
            "The bot finds artwork and platforms. Tune hashtags and preview "
            "in chat, or customize the whole post in Studio."
        ),
    },
    "onboarding_3": {
        RU: (
            "<b>● ● ●  Выпусти пост</b>\n\n"
            "Отправь его себе, добавь в подборку или опубликуй в канал. "
            "Для любого чата есть inline: <code>@StonerHandBot запрос</code>."
        ),
        EN: (
            "<b>● ● ●  Release the post</b>\n\n"
            "Send it to yourself, add it to a crate or publish to the channel. "
            "Inline works anywhere: <code>@StonerHandBot query</code>."
        ),
    },
    "quick_tour": {RU: "▶ Быстрый тур", EN: "▶ Quick tour"},
    "quick_search": {RU: "🔎 Новый пост", EN: "🔎 New post"},
    "open_studio": {RU: "🎛 Открыть Студию", EN: "🎛 Open Studio"},
    "home_crate": {RU: "🧺 Подборка · {count}", EN: "🧺 Crate · {count}"},
    "home_stats": {RU: "📊 Статистика канала", EN: "📊 Channel stats"},
    "home_result": {RU: "✨ Что получится", EN: "✨ See the result"},
    "home_back": {RU: "← Главное меню", EN: "← Main menu"},
    "next": {RU: "Дальше →", EN: "Next →"},
    "back": {RU: "← Назад", EN: "← Back"},
    "start_using": {RU: "Готово — открыть меню", EN: "Done — open menu"},
    "tab_start": {RU: "🚀 Быстрый старт", EN: "🚀 Quick start"},
    "tab_help": {RU: "❓ Помощь", EN: "❓ Help"},
    "tab_platforms": {RU: "🎛 Сервисы", EN: "🎛 Services"},
    "tab_guide": {RU: "📣 Для каналов", EN: "📣 For channels"},
    "tab_demo": {RU: "🧪 Пример поста", EN: "🧪 Example post"},
    "share_button": {RU: "↗ Поделиться ботом", EN: "↗ Share the bot"},
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
            "• Inline: type @StonerHandBot + a link in any chat\n\n"
            "Send a link or a name 👇"
        ),
    },
    "menu_help": {
        RU: (
            "<b>Как пользоваться</b>\n\n"
            "1️⃣ Пришли ссылку на релиз, видео или эфир — "
            "или просто название трека\n"
            "2️⃣ Хочешь подводку — напиши текст над ссылкой, он станет цитатой\n"
            "3️⃣ Получи чистый пост: preview, хэштеги и кнопки площадок\n\n"
            "💡 Несколько ссылок одним сообщением превращаются в нумерованную "
            "подборку с кнопкой на каждый релиз\n\n"
            "⚡ В любом другом чате набери <code>@StonerHandBot ссылка</code> — "
            "вставишь готовый пост, не выходя из разговора\n\n"
            "🎚 Под постом в личке есть редактор: хэштеги, цитата, "
            "публикация в канал\n\n"
            "Разметка в подводке сохраняется: жирный, курсив, спойлеры, ссылки"
        ),
        EN: (
            "<b>How it works</b>\n\n"
            "1️⃣ Send a link to a release, video or show — "
            "or just type a track name\n"
            "2️⃣ Want an intro? Write text above the link, it becomes a quote\n"
            "3️⃣ Get a clean post: preview, hashtags and platform buttons\n\n"
            "💡 Several links in one message become a numbered collection "
            "with a button per release\n\n"
            "⚡ In any other chat type <code>@StonerHandBot link</code> — "
            "insert a finished post without leaving the conversation\n\n"
            "🎚 Posts in DM come with an editor: hashtags, quote, "
            "publish-to-channel\n\n"
            "Formatting in the intro is preserved: bold, italic, spoilers, links"
        ),
    },
    "menu_guide": {
        RU: (
            "<b>Для групп и каналов</b>\n\n"
            "1️⃣ Добавь бота в группу или канал\n"
            "2️⃣ Сделай его админом с правом удалять сообщения\n"
            "3️⃣ Кидай ссылки как обычно — бот заменит их готовыми постами\n\n"
            "💡 Текст над ссылкой станет цитатой с подписью автора, "
            "хэштеги добавятся автоматически\n\n"
            "Пост публикуется до удаления исходного сообщения, "
            "так что контент не теряется"
        ),
        EN: (
            "<b>For groups and channels</b>\n\n"
            "1️⃣ Add the bot to a group or channel\n"
            "2️⃣ Make it an admin with the delete-messages right\n"
            "3️⃣ Drop links as usual — the bot swaps them for finished posts\n\n"
            "💡 Text above a link becomes a quote with the author's name, "
            "hashtags are added automatically\n\n"
            "The post is published before the original message is deleted, "
            "so nothing is ever lost"
        ),
    },
    "menu_platforms": {
        RU: (
            "<b>Что можно присылать</b>\n\n"
            "🟢 Spotify — треки, альбомы, плейлисты, артисты, подкасты\n"
            "⚪ Apple Music и Apple Podcasts\n"
            "🔴 YouTube и YouTube Music\n"
            "🟠 SoundCloud\n"
            "🟦 Deezer · ⚫ Tidal · 🟡 Yandex Music\n"
            "📡 NTS Radio\n\n"
            "<b>Что получится</b>\n"
            "Карточка релиза с кнопками всех площадок, где он нашелся. "
            "YouTube оформится как видео-пост, NTS — как радио-эфир, "
            "несколько ссылок — как подборка\n\n"
            "Нет ссылки под рукой — просто напиши название трека"
        ),
        EN: (
            "<b>What you can send</b>\n\n"
            "🟢 Spotify — tracks, albums, playlists, artists, podcasts\n"
            "⚪ Apple Music and Apple Podcasts\n"
            "🔴 YouTube and YouTube Music\n"
            "🟠 SoundCloud\n"
            "🟦 Deezer · ⚫ Tidal · 🟡 Yandex Music\n"
            "📡 NTS Radio\n\n"
            "<b>What you get</b>\n"
            "A release card with buttons for every platform where it was found. "
            "YouTube becomes a video post, NTS a radio show, "
            "several links a collection\n\n"
            "No link at hand? Just type the track name"
        ),
    },
    "menu_demo": {
        RU: (
            "<b>Пример поста</b>\n\n"
            "Присылаешь ссылку — получаешь такое:\n\n"
            "<blockquote>📻 · The Soft Moon\n"
            "Criminal\n\n"
            "кнопки ниже, трек ждет\n\n"
            "#stonerhand #track\n\n"
            "[🟢 Spotify] [⚪ Apple]\n"
            "[🟦 Deezer] [⚫ Tidal]\n"
            "[🪩 Все платформы]</blockquote>\n\n"
            "Сверху — обложка релиза, снизу — живые кнопки всех площадок, "
            "где нашелся релиз\n\n"
            "Попробуй: пришли ссылку из Spotify, Apple Music, YouTube — "
            "или просто название трека 👇"
        ),
        EN: (
            "<b>Example post</b>\n\n"
            "You send a link — you get this:\n\n"
            "<blockquote>📻 · The Soft Moon\n"
            "Criminal\n\n"
            "buttons below, the track is waiting\n\n"
            "#stonerhand #track\n\n"
            "[🟢 Spotify] [⚪ Apple]\n"
            "[🟦 Deezer] [⚫ Tidal]\n"
            "[🪩 All platforms]</blockquote>\n\n"
            "Cover art on top, live buttons for every matched platform below\n\n"
            "Try it: send a Spotify, Apple Music or YouTube link — "
            "or just type a track name 👇"
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
        RU: "🎧 Вставь ссылку или название трека",
        EN: "🎧 Paste a link or type a track name",
    },
    "inline_hint_not_found": {
        RU: "Не нашел площадок — открыть бота",
        EN: "No platforms found — open the bot",
    },
    # Editor toggles use language-free glyphs so the row stays one line
    # on narrow screens: "#️⃣ ✓", "💬 ✗", "🖼 ⊞".
    "ed_hashtags": {RU: "# Хэштеги", EN: "# Hashtags"},
    "ed_quote": {RU: "💬 Цитата", EN: "💬 Quote"},
    "ed_on": {RU: "✓", EN: "✓"},
    "ed_off": {RU: "✗", EN: "✗"},
    "ed_studio": {RU: "🎛 Студия", EN: "🎛 Studio"},
    "menu_button_studio": {RU: "Студия", EN: "Studio"},
    "ed_preview": {RU: "🖼 Обложка", EN: "🖼 Cover"},
    "ed_preview_small": {RU: "малая", EN: "small"},
    "ed_preview_large": {RU: "большая", EN: "large"},
    "ed_done": {RU: "✅ Готово", EN: "✅ Done"},
    "ed_delete": {RU: "Удалить", EN: "Delete"},
    "ed_more": {RU: "••• Ещё", EN: "••• More"},
    "ed_send_self": {RU: "Отправить себе", EN: "Send to me"},
    "ed_add_crate": {RU: "+ В подборку", EN: "+ Add to crate"},
    "ed_crate_added": {RU: "Добавлено в подборку", EN: "Added to crate"},
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
    "error_title": {RU: "Не получилось собрать пост", EN: "Could not build the post"},
    "error_search": {
        RU: "Не нашёл точного совпадения. Добавь имя артиста или уточни название релиза.",
        EN: "No exact match. Add the artist name or refine the release title.",
    },
    "error_provider": {
        RU: "Музыкальный сервис временно не отвечает. Ссылка сохранена — попробуй ещё раз.",
        EN: "A music provider is temporarily unavailable. The link is saved — try again.",
    },
    "search_choose": {
        RU: "<b>Выбери релиз</b>\n\nНашёл несколько вариантов по запросу «{query}»:",
        EN: "<b>Choose a release</b>\n\nI found several matches for “{query}”:",
    },
    "progress_search": {RU: "1/3 · Ищу релиз…", EN: "1/3 · Finding the release…"},
    "progress_links": {RU: "2/3 · Собираю площадки…", EN: "2/3 · Collecting platforms…"},
    "progress_card": {RU: "3/3 · Собираю карточку…", EN: "3/3 · Building the card…"},
    "crate_empty": {
        RU: "<b>Подборка пока пустая</b>\n\nДобавляй релизы кнопкой «+ В подборку» под карточкой.",
        EN: "<b>Your crate is empty</b>\n\nAdd releases with the “+ Add to crate” button under a card.",
    },
    "crate_title": {RU: "<b>Моя подборка · {count}/10</b>", EN: "<b>My crate · {count}/10</b>"},
    "crate_open_studio": {RU: "Собрать сет в Студии", EN: "Build the set in Studio"},
}
