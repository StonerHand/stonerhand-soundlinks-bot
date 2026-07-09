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
    "tab_start": {RU: "🚀 Быстрый старт", EN: "🚀 Quick start"},
    "tab_help": {RU: "📖 Как пользоваться", EN: "📖 How it works"},
    "tab_platforms": {RU: "🎛 Сервисы", EN: "🎛 Services"},
    "tab_guide": {RU: "📣 Для каналов", EN: "📣 For channels"},
    "tab_demo": {RU: "🧪 Пример поста", EN: "🧪 Example post"},
    "share_button": {RU: "Поделиться ботом", EN: "Share the bot"},
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
            "Попробуй: пришли любую ссылку из Spotify, Apple Music или YouTube 👇"
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
            "Try it: send any Spotify, Apple Music or YouTube link 👇"
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
    "ed_hashtags": {RU: "#️⃣ Хэштеги", EN: "#️⃣ Hashtags"},
    "ed_quote": {RU: "💬 Цитата", EN: "💬 Quote"},
    "ed_on": {RU: "вкл", EN: "on"},
    "ed_off": {RU: "выкл", EN: "off"},
    "ed_done": {RU: "✅ Готово", EN: "✅ Done"},
    "ed_delete": {RU: "🗑 Удалить", EN: "🗑 Delete"},
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
    "ed_publish_failed": {
        RU: "Не получилось опубликовать — проверь права бота в канале",
        EN: "Could not publish — check the bot's rights in the channel",
    },
}
