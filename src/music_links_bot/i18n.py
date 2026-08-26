from __future__ import annotations

from string import Formatter

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


def validate_catalog() -> tuple[str, ...]:
    """Return deterministic errors for incomplete or incompatible locales."""
    formatter = Formatter()
    errors: list[str] = []
    for key, entry in sorted(STRINGS.items()):
        missing_languages = [
            lang
            for lang in (RU, EN)
            if not isinstance(entry.get(lang), str) or not entry[lang]
        ]
        errors.extend(f"{key}: missing {lang}" for lang in missing_languages)
        if missing_languages:
            continue
        fields = {
            lang: {
                field
                for _, field, _, _ in formatter.parse(entry[lang])
                if field is not None
            }
            for lang in (RU, EN)
        }
        if fields[RU] != fields[EN]:
            errors.append(
                f"{key}: placeholders differ "
                f"({sorted(fields[RU])!r} != {sorted(fields[EN])!r})"
            )
    return tuple(errors)


STRINGS: dict[str, dict[str, str]] = {
    "home_title_new": {
        RU: "🎧 <b>StonerHandBot</b>\n<i>Музыкальный конструктор постов</i>",
        EN: "🎧 <b>StonerHandBot</b>\n<i>Music post builder</i>",
    },
    "home_title": {
        RU: "🎧 <b>Музыкальный редактор{name}</b>",
        EN: "🎧 <b>Music post editor{name}</b>",
    },
    "home_body": {
        RU: (
            "{greeting}\n\n"
            "<b>Просто отправь сообщением:</b>\n"
            "• ссылку на трек, альбом, плейлист или артиста\n"
            "• <code>артист — название</code>\n"
            "• несколько ссылок — для подборки\n"
            "• свой текст над ссылкой — для подводки\n\n"
            "<i>Обложку, кнопки и точные хэштеги соберу автоматически.</i>"
        ),
        EN: (
            "{greeting}\n\n"
            "<b>Just send a message with:</b>\n"
            "• a track, album, playlist or artist link\n"
            "• <code>artist — title</code>\n"
            "• several links for a collection\n"
            "• your own text above a link for the intro\n\n"
            "<i>I will add artwork, platform buttons and verified hashtags automatically.</i>"
        ),
    },
    "home_body_new": {
        RU: (
            "{greeting}\n\n"
            "Я найду релиз и подготовлю готовый Telegram-пост: "
            "<b>обложку, название, точные хэштеги и кнопки площадок.</b>\n\n"
            "<b>Что можно прислать</b>\n"
            "• ссылку на трек, альбом, плейлист или артиста\n"
            "• <code>Deftones — Rickets</code>\n"
            "• несколько ссылок одним сообщением — получится подборка\n\n"
            "<blockquote>Свой текст можно написать над ссылкой — он станет подводкой к посту.</blockquote>\n"
            "<i>{mode}</i>"
        ),
        EN: (
            "{greeting}\n\n"
            "I will find the release and prepare a finished Telegram post with "
            "<b>artwork, title, verified hashtags and platform buttons.</b>\n\n"
            "<b>What you can send</b>\n"
            "• a track, album, playlist or artist link\n"
            "• <code>Deftones — Rickets</code>\n"
            "• several links in one message for a collection\n\n"
            "<blockquote>Write your own text above a link to use it as the post intro.</blockquote>\n"
            "<i>{mode}</i>"
        ),
    },
    "home_mode_admin": {
        RU: "Редактор, очередь и публикация доступны прямо в боте",
        EN: "Editing, queueing and publishing are available right in the bot",
    },
    "home_mode_user": {
        RU: "Карточку можно изменить и отправить прямо в этом чате",
        EN: "Edit and send the card directly in this chat",
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
            "Нажми <b>Изменить</b>, чтобы настроить стиль, текст, хэштеги и площадки."
        ),
        EN: (
            "🎛 <b>Step 2 of 3 · Choose the format</b>\n\n"
            "<blockquote>The bot finds artwork, platforms and prepares hashtags.</blockquote>\n"
            "Tap <b>Edit</b> to tune the style, text, hashtags and platforms."
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
    "quick_tour": {RU: "Как это работает?", EN: "How does it work?"},
    "quick_search": {RU: "🔎 Найти", EN: "🔎 Find"},
    "home_create": {RU: "＋ Создать пост", EN: "＋ Create post"},
    "home_continue": {RU: "↩ Вернуться к карточке", EN: "↩ Return to card"},
    "home_continue_named": {RU: "↩ {release}", EN: "↩ {release}"},
    "create_prompt": {
        RU: (
            "🔎 <b>Новая карточка</b>\n\n"
            "Отправь следующим сообщением:\n"
            "• ссылку на трек, альбом, плейлист или артиста\n"
            "• название в формате <code>артист — трек</code>\n"
            "• несколько ссылок, каждую с новой строки — для подборки\n\n"
            "<blockquote><code>Deftones — Rickets</code></blockquote>\n"
            "Свой текст над ссылкой станет подводкой к посту."
        ),
        EN: (
            "🔎 <b>New card</b>\n\n"
            "Send your next message with:\n"
            "• a track, album, playlist or artist link\n"
            "• a title as <code>artist — track</code>\n"
            "• several links, one per line, for a collection\n\n"
            "<blockquote><code>Deftones — Rickets</code></blockquote>\n"
            "Text above a link becomes the post intro."
        ),
    },
    "home_recent": {RU: "История", EN: "History"},
    "home_queue": {RU: "🕒 Очередь публикаций", EN: "🕒 Publication queue"},
    "queue_title": {RU: "🕒 <b>Очередь · {count}</b>", EN: "🕒 <b>Queue · {count}</b>"},
    "queue_page": {RU: "Страница {page} из {pages}", EN: "Page {page} of {pages}"},
    "queue_empty": {
        RU: "Пока пусто. Запланируй карточку через меню «Отправить».",
        EN: "Nothing scheduled. Schedule a card from the Send menu.",
    },
    "queue_unknown": {RU: "Карточка без названия", EN: "Untitled card"},
    "queue_cancel_item": {RU: "Убрать №{index}", EN: "Remove #{index}"},
    "queue_refresh": {RU: "Обновить", EN: "Refresh"},
    "queue_cancelled": {RU: "Убрано из очереди", EN: "Removed from queue"},
    "queue_missing": {RU: "Этой записи уже нет", EN: "This item is already gone"},
    "queue_unavailable": {
        RU: "Очередь временно недоступна. Попробуй ещё раз.",
        EN: "The queue is temporarily unavailable. Try again.",
    },
    "playlist_import": {RU: "＋ Собрать треки", EN: "＋ Import tracks"},
    "playlist_import_started": {
        RU: "Собираю треки в подборку",
        EN: "Importing tracks into a crate",
    },
    "recent_title": {RU: "<b>Недавние посты</b>", EN: "<b>Recent posts</b>"},
    "recent_empty": {
        RU: "<b>Недавних постов пока нет</b>\n\nСоздай первую карточку — она появится здесь.",
        EN: "<b>No recent posts yet</b>\n\nCreate your first card and it will appear here.",
    },
    "recent_repeat": {RU: "Повторить", EN: "Repeat"},
    "recent_add": {RU: "+ В подборку", EN: "+ To crate"},
    "crate_view": {RU: "Открыть подборку", EN: "Open crate"},
    "crate_reorder": {RU: "Порядок", EN: "Reorder"},
    "home_crate": {RU: "🧺 Подборка · {count}", EN: "🧺 Crate · {count}"},
    "home_more": {RU: "••• Ещё", EN: "••• More"},
    "home_back": {RU: "← Главное меню", EN: "← Main menu"},
    "next": {RU: "Дальше →", EN: "Next →"},
    "back": {RU: "← Назад", EN: "← Back"},
    "start_using": {RU: "Готово ✓", EN: "Done ✓"},
    "tab_start": {RU: "🚀 Быстрый старт", EN: "🚀 Quick start"},
    "tab_help": {RU: "❓ Помощь", EN: "❓ Help"},
    "tab_platforms": {RU: "🎛 Сервисы", EN: "🎛 Services"},
    "tab_guide": {RU: "📣 Для каналов", EN: "📣 For channels"},
    "tab_demo": {RU: "🧪 Пример поста", EN: "🧪 Example post"},
    "tab_privacy": {RU: "🔐 Данные и приватность", EN: "🔐 Data and privacy"},
    "privacy_title": {
        RU: (
            "🔐 <b>Данные и приватность</b>\n\n"
            "Бот хранит только состояние, нужное для работы: черновики, подборку, "
            "историю, настройки оформления и запланированные публикации. "
            "Срок хранения ограничен, а статистика продукта считается без текста "
            "постов и музыкальных ссылок.\n\n"
            "<blockquote>После удаления временные токены поиска могут существовать "
            "не более 30 минут, затем исчезают автоматически.</blockquote>"
        ),
        EN: (
            "🔐 <b>Data and privacy</b>\n\n"
            "The bot stores only working state: drafts, your crate, history, design "
            "settings and scheduled publications. Retention is limited, while product "
            "metrics contain no post text or music links.\n\n"
            "<blockquote>After deletion, temporary search tokens may remain for up to "
            "30 minutes and then expire automatically.</blockquote>"
        ),
    },
    "privacy_delete": {RU: "Удалить мои данные", EN: "Delete my data"},
    "privacy_confirm": {
        RU: (
            "⚠️ <b>Удалить данные без возможности восстановления?</b>\n\n"
            "Будут удалены черновики, история, подборка, шаблоны, настройки и "
            "запланированные тобой публикации. Уже опубликованные сообщения в "
            "Telegram останутся на месте."
        ),
        EN: (
            "⚠️ <b>Delete data permanently?</b>\n\n"
            "Drafts, history, crate, templates, settings and your scheduled posts will "
            "be removed. Messages already published to Telegram will remain."
        ),
    },
    "privacy_delete_confirm": {
        RU: "Удалить безвозвратно",
        EN: "Delete permanently",
    },
    "privacy_deleted": {
        RU: (
            "✅ <b>Данные удалены</b>\n\n"
            "Удалено черновиков: <b>{drafts}</b>\n"
            "Снято с очереди: <b>{scheduled}</b>\n\n"
            "Можешь начать заново — просто пришли музыкальную ссылку."
        ),
        EN: (
            "✅ <b>Data deleted</b>\n\n"
            "Drafts removed: <b>{drafts}</b>\n"
            "Scheduled posts removed: <b>{scheduled}</b>\n\n"
            "You can start over by sending a music link."
        ),
    },
    "privacy_deleted_queue_warning": {
        RU: (
            "\n\n⚠️ Очередь публикаций временно недоступна. Остальные данные удалены; "
            "проверь очередь позже через владельца бота."
        ),
        EN: (
            "\n\n⚠️ The publishing queue is temporarily unavailable. Other data was "
            "deleted; ask the bot owner to check the queue later."
        ),
    },
    "share_post": {
        RU: "↗ Поделиться",
        EN: "↗ Share",
    },
    "error_platforms_button": {RU: "Что поддерживается", EN: "What is supported"},
    "error_open_source": {RU: "Открыть исходник", EN: "Open source"},
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
            "• Встроенный редактор карточки и публикация в канал\n"
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
            "• Built-in card editor and channel publishing\n"
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
            "<b>Пример</b> — как выглядит готовый пост\n"
            "<b>Приватность</b> — данные и их удаление</blockquote>"
        ),
        EN: (
            "••• <b>More tools</b>\n"
            "<i>Useful extras without crowding the home screen.</i>\n\n"
            "<blockquote><b>Help</b> — a short guide\n"
            "<b>Services</b> — supported platforms\n"
            "<b>For channels</b> — automatic link replacement\n"
            "<b>Example</b> — a finished post preview\n"
            "<b>Privacy</b> — stored data and deletion controls</blockquote>"
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
    "ed_hashtags_auto": {RU: "# Хэштеги · авто", EN: "# Hashtags · auto"},
    "ed_hashtags_custom": {RU: "# Свои · {count}", EN: "# Custom · {count}"},
    "ed_hashtags_none": {RU: "# Без хэштегов", EN: "# No hashtags"},
    "ed_edit": {RU: "Изменить", EN: "Edit"},
    "ed_last_template": {RU: "↻ Как в прошлый раз", EN: "↻ Same as last time"},
    "ed_templates": {RU: "Шаблоны", EN: "Templates"},
    "ed_templates_title": {
        RU: "🗂 <b>Шаблоны оформления</b>\n<i>Сохрани набор настроек и применяй его одним нажатием.</i>",
        EN: "🗂 <b>Design templates</b>\n<i>Save a set of options and apply it with one tap.</i>",
    },
    "ed_template_save": {RU: "+ Сохранить текущий", EN: "+ Save current"},
    "ed_template_prompt": {
        RU: "<b>Название шаблона</b>\nНапример: <code>Альбом недели</code> или <code>Минимал</code>.\n<code>/cancel</code> — отменить",
        EN: "<b>Template name</b>\nFor example: <code>Album of the week</code> or <code>Minimal</code>.\n<code>/cancel</code> — cancel",
    },
    "ed_template_saved": {RU: "Шаблон сохранён", EN: "Template saved"},
    "ed_template_applied": {RU: "Шаблон применён", EN: "Template applied"},
    "ed_template_deleted": {RU: "Шаблон удалён", EN: "Template deleted"},
    "ed_template_unnamed": {RU: "Без названия", EN: "Untitled"},
    "ed_last_template_applied": {
        RU: "Прошлый формат восстановлен",
        EN: "Previous format restored",
    },
    "ed_text_on": {RU: "Подводка · есть", EN: "Intro · on"},
    "ed_text_off": {RU: "Подводка · нет", EN: "Intro · none"},
    "ed_platforms_all_short": {RU: "все", EN: "all"},
    "ed_platforms_selected": {RU: "Площадки · {count}", EN: "Platforms · {count}"},
    "ed_platforms_audio": {RU: "Площадки · не нужны", EN: "Platforms · not needed"},
    "ed_delivery_auto": {RU: "Telegram · авто", EN: "Telegram · auto"},
    "ed_delivery_classic": {RU: "Telegram · классика", EN: "Telegram · classic"},
    "ed_delivery_title": {
        RU: "📨 <b>Формат Telegram</b>\n<i>Авто использует новый формат и безопасно откатывается к обычному сообщению.</i>",
        EN: "📨 <b>Telegram format</b>\n<i>Auto uses the new format and safely falls back to a classic message.</i>",
    },
    "ed_delivery_auto_name": {
        RU: "Авто — современная карточка",
        EN: "Auto — modern card",
    },
    "ed_delivery_classic_name": {
        RU: "Классика — обычное сообщение",
        EN: "Classic — regular message",
    },
    "ed_cover_auto": {RU: "Обложка · авто", EN: "Artwork · auto"},
    "ed_cover_custom": {RU: "Обложка · своя", EN: "Artwork · custom"},
    "ed_cover_prompt": {
        RU: "<b>Пришли новую обложку</b>\nОтветь одной фотографией. Бот сохранит её только для этой карточки.\n<code>/cancel</code> — отменить",
        EN: "<b>Send new artwork</b>\nReply with one photo. It will be used only for this card.\n<code>/cancel</code> — cancel",
    },
    "ed_cover_invalid": {
        RU: "Нужна фотография. Отправь изображение без файла-документа.",
        EN: "Send a photo, not a document.",
    },
    "ed_cover_saved": {RU: "Обложка сохранена", EN: "Artwork saved"},
    "ed_cover_reset": {RU: "Вернуть обложку релиза", EN: "Restore release artwork"},
    "uploaded_audio_title": {RU: "Аудиофайл", EN: "Audio file"},
    "uploaded_audio_artist": {RU: "Исполнитель не указан", EN: "Unknown artist"},
    "ed_platforms_select_all": {RU: "Выбрать все", EN: "Select all"},
    "ed_preset_minimal": {RU: "Стиль · Минимал", EN: "Style · Minimal"},
    "ed_preset_cover": {RU: "Стиль · Обложка", EN: "Style · Cover"},
    "ed_preset_longread": {RU: "Стиль · Лонгрид", EN: "Style · Longread"},
    "ed_preset_name_minimal": {
        RU: "Минимал — компактное превью",
        EN: "Minimal — compact preview",
    },
    "ed_preset_name_cover": {
        RU: "Обложка — крупное превью",
        EN: "Cover — large preview",
    },
    "ed_preset_name_longread": {
        RU: "Лонгрид — текстовая публикация",
        EN: "Longread — editorial post",
    },
    "ed_status": {
        RU: "{preset} · площадок: {services} · сохранено",
        EN: "{preset} · platforms: {services} · saved",
    },
    "ed_status_audio": {
        RU: "{preset} · аудио Telegram · сохранено",
        EN: "{preset} · Telegram audio · saved",
    },
    "ed_preflight_warnings": {
        RU: "⚠️ Проверка: замечаний — {count}",
        EN: "⚠️ Check: {count} warning(s)",
    },
    "ed_preflight_no_platforms": {
        RU: "⛔ Выбери хотя бы одну площадку",
        EN: "⛔ Select at least one platform",
    },
    "ed_preflight_missing_links": {
        RU: "⛔ У релиза нет рабочей ссылки для отправки",
        EN: "⛔ This release has no working delivery link",
    },
    "ed_preflight_missing_title": {
        RU: "⛔ Не удалось определить исполнителя или название",
        EN: "⛔ Artist or title is missing",
    },
    "ed_intro_counter": {
        RU: "Подводка: {used}/{limit}",
        EN: "Intro: {used}/{limit}",
    },
    "ed_intro_will_trim": {
        RU: "⚠️ Подводка длиннее доступного места и будет сокращена",
        EN: "⚠️ The intro is longer than the available space and will be shortened",
    },
    "ed_constructor_title": {RU: "Конструктор карточки", EN: "Card builder"},
    "ed_constructor_hint": {
        RU: "Нажимай параметры — превью обновится сразу",
        EN: "Tap a setting to update the preview instantly",
    },
    "ed_style_title": {
        RU: "🎨 <b>Стиль карточки</b>\n<i>Выбери один понятный формат.</i>",
        EN: "🎨 <b>Card style</b>\n<i>Choose one clear format.</i>",
    },
    "ed_platforms_title": {
        RU: "🎛 <b>Площадки</b>\n<i>Отметь кнопки, которые нужны в посте.</i>",
        EN: "🎛 <b>Platforms</b>\n<i>Select the buttons to keep in the post.</i>",
    },
    "ed_intro_title": {
        RU: "✍️ <b>Подводка</b>\n<i>Короткий авторский текст перед релизом.</i>",
        EN: "✍️ <b>Intro</b>\n<i>A short personal note before the release.</i>",
    },
    "ed_hashtags_title": {
        RU: (
            "#️⃣ <b>Хэштеги</b>\n"
            "<i>Авто добавляет тип релиза и только подтверждённый жанр. "
            "Сомнительный жанр будет пропущен.</i>"
        ),
        EN: (
            "#️⃣ <b>Hashtags</b>\n"
            "<i>Auto adds the release type and only a verified genre. "
            "Uncertain genres are omitted.</i>"
        ),
    },
    "ed_actions_title": {
        RU: "🚀 <b>Что сделать с постом?</b>\n<i>Отправить себе, запланировать или опубликовать.</i>",
        EN: "🚀 <b>What next?</b>\n<i>Send, schedule or publish.</i>",
    },
    "ed_clean_preview": {RU: "👁 Превью", EN: "👁 Preview"},
    "back_to_editor": {RU: "← К настройкам", EN: "← Back to settings"},
    "ed_intro_add": {RU: "+ Добавить подводку", EN: "+ Add intro"},
    "ed_intro_change": {RU: "Изменить подводку", EN: "Edit intro"},
    "ed_intro_remove": {RU: "Убрать подводку", EN: "Remove intro"},
    "ed_intro_prompt": {
        RU: "<b>Жду подводку</b>\nОтветь одним сообщением — доступно до {limit} символов. Форматирование Telegram сохранится.\n<code>/cancel</code> — отменить",
        EN: "<b>Waiting for an intro</b>\nReply with one message — up to {limit} characters are available. Telegram formatting is preserved.\n<code>/cancel</code> — cancel",
    },
    "ed_intro_saved": {RU: "Подводка сохранена", EN: "Intro saved"},
    "ed_tags_auto": {RU: "Автоматические", EN: "Automatic"},
    "ed_tags_custom": {RU: "Свои хэштеги", EN: "Custom hashtags"},
    "ed_tags_none": {RU: "Без хэштегов", EN: "No hashtags"},
    "ed_tags_prompt": {
        RU: "<b>Жду хэштеги</b>\nПришли до пяти через пробел: <code>#stonerrock #newmusic</code>\n<code>/cancel</code> — отменить",
        EN: "<b>Waiting for hashtags</b>\nSend up to five separated by spaces: <code>#stonerrock #newmusic</code>\n<code>/cancel</code> — cancel",
    },
    "ed_tags_saved": {RU: "Хэштеги сохранены", EN: "Hashtags saved"},
    "ed_deleted": {
        RU: "<b>Карточка удалена</b>\n\nОтменить можно в течение 15 секунд.",
        EN: "<b>Card deleted</b>\n\nYou can undo this for 15 seconds.",
    },
    "ed_undo_delete": {RU: "Вернуть карточку", EN: "Restore card"},
    "ed_undo_expired": {RU: "Время для отмены истекло", EN: "Undo time has expired"},
    "ed_done": {RU: "✓ Готово", EN: "✓ Done"},
    "ed_delete": {RU: "🗑 Удалить", EN: "🗑 Delete"},
    "ed_more": {RU: "Отправить", EN: "Send"},
    "ed_send_self": {RU: "Получить готовый пост", EN: "Get finished post"},
    "ed_add_crate": {RU: "+ В подборку", EN: "+ Add to crate"},
    "ed_crate_count": {RU: "В подборке · {count}/10", EN: "In crate · {count}/10"},
    "ed_crate_added": {RU: "Добавлено · {count}/10", EN: "Added · {count}/10"},
    "ed_crate_exists": {
        RU: "Уже в подборке · {count}/10",
        EN: "Already in crate · {count}/10",
    },
    "ed_sent": {RU: "Готово — пост отправлен ниже", EN: "Done — the post is below"},
    "ed_sent_short": {RU: "Готово · пост отправлен", EN: "Done · post sent"},
    "ed_publish": {RU: "📤 В канал", EN: "📤 To channel"},
    "ed_schedule": {RU: "🕒 Запланировать", EN: "🕒 Schedule"},
    "schedule_title": {
        RU: "🕒 <b>Когда опубликовать?</b>\n<i>Фиксированное время — по часовому поясу бота.</i>",
        EN: "🕒 <b>When to publish?</b>\n<i>Fixed times use the bot timezone.</i>",
    },
    "schedule_1h": {RU: "Через 1 час", EN: "In 1 hour"},
    "schedule_3h": {RU: "Через 3 часа", EN: "In 3 hours"},
    "schedule_evening": {RU: "Сегодня в 20:00", EN: "Today at 20:00"},
    "schedule_1d": {RU: "Завтра в 12:00", EN: "Tomorrow at 12:00"},
    "schedule_custom": {RU: "Выбрать дату и время", EN: "Choose date and time"},
    "schedule_prompt": {
        RU: "<b>Жду дату и время</b>\nНапример: <code>15.08 19:30</code> или <code>21:00</code>\n<code>/cancel</code> — отменить",
        EN: "<b>Waiting for date and time</b>\nFor example: <code>15.08 19:30</code> or <code>21:00</code>\n<code>/cancel</code> — cancel",
    },
    "schedule_invalid": {
        RU: "Не понял время. Используй <code>15.08 19:30</code> или <code>21:00</code>.",
        EN: "I could not read that time. Use <code>15.08 19:30</code> or <code>21:00</code>.",
    },
    "schedule_done": {RU: "Запланировано: {date}", EN: "Scheduled: {date}"},
    "publish_confirm": {
        RU: (
            "<b>Готово к публикации</b>\n\n"
            "<blockquote><b>{artist}</b> — {title}\n"
            "Куда: {target} · сейчас</blockquote>\n"
            "Проверь карточку и подтверди отправку."
        ),
        EN: (
            "<b>Ready to publish</b>\n\n"
            "<blockquote><b>{artist}</b> — {title}\n"
            "Target: {target} · now</blockquote>\n"
            "Check the card and confirm delivery."
        ),
    },
    "publish_confirm_button": {RU: "Опубликовать", EN: "Publish"},
    "settings_saved": {RU: "Настройки сохранены", EN: "Settings saved"},
    "settings_undo": {RU: "Отменить изменение", EN: "Undo change"},
    "settings_restored": {RU: "Изменение отменено", EN: "Change undone"},
    "input_cancelled": {RU: "Ввод отменён", EN: "Input cancelled"},
    "input_nothing": {
        RU: "Сейчас бот ничего не ожидает",
        EN: "Nothing is waiting for input",
    },
    "ed_expired": {
        RU: "Карточка устарела — пришли ссылку заново",
        EN: "This card has expired — send the link again",
    },
    "ed_owner_only": {
        RU: "Эта карточка принадлежит другому пользователю",
        EN: "This card belongs to another user",
    },
    "ed_admin_only": {
        RU: "Публиковать в канал может только владелец бота",
        EN: "Only the bot owner can publish to the channel",
    },
    "ed_published": {RU: "Опубликовано в канал 🎉", EN: "Published to the channel 🎉"},
    "ed_open_publication": {RU: "Открыть публикацию", EN: "Open publication"},
    "ed_create_more": {RU: "+ Создать ещё", EN: "+ Create another"},
    "ed_delete_confirm": {
        RU: "<b>Удалить эту карточку?</b>\n\nПосле удаления будет 15 секунд на отмену.",
        EN: "<b>Delete this card?</b>\n\nYou will have 15 seconds to undo it.",
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
    "ed_queue_full": {
        RU: "Очередь заполнена — сначала опубликуй или удали один из 50 постов",
        EN: "The queue is full — publish or remove one of the 50 posts first",
    },
    "ed_queue_unavailable": {
        RU: "Очередь временно недоступна — попробуй ещё раз через несколько секунд",
        EN: "The queue is temporarily unavailable — try again in a few seconds",
    },
    "action_busy": {
        RU: "Это действие уже выполняется. Подожди пару секунд.",
        EN: "This action is already running. Give it a few seconds.",
    },
    "action_duplicate": {
        RU: "Уже готово — повторно ничего не отправлял.",
        EN: "Already done — nothing was sent twice.",
    },
    "request_cancel": {RU: "Отменить поиск", EN: "Cancel search"},
    "request_cancelled": {RU: "Поиск отменён", EN: "Search cancelled"},
    "request_not_running": {
        RU: "Этот поиск уже завершён",
        EN: "This search has already finished",
    },
    "retry": {RU: "Повторить", EN: "Retry"},
    "retry_failed": {
        RU: "Проверить все ссылки",
        EN: "Check all links again",
    },
    "replace_source": {
        RU: "Заменить №{index}",
        EN: "Replace #{index}",
    },
    "replace_source_prompt": {
        RU: "<b>Замена ссылки №{index}</b>\nПришли одну новую музыкальную ссылку.\n<code>/cancel</code> — отменить",
        EN: "<b>Replace link #{index}</b>\nSend one new music link.\n<code>/cancel</code> — cancel",
    },
    "replace_source_invalid": {
        RU: "Нужна ровно одна поддерживаемая музыкальная ссылка.",
        EN: "Send exactly one supported music link.",
    },
    "partial_not_found": {
        RU: "не удалось распознать релиз — ссылка удалена, закрыта или недоступна",
        EN: "release could not be recognized — the link is private, removed, or unavailable",
    },
    "partial_unavailable": {
        RU: "сервис временно не ответил",
        EN: "service did not respond in time",
    },
    "partial_timeout": {
        RU: "истекло время ожидания сервиса",
        EN: "service response timed out",
    },
    "partial_rate_limited": {
        RU: "площадка временно ограничила запросы",
        EN: "platform temporarily rate-limited requests",
    },
    "partial_result": {
        RU: "<b>Готово не всё</b>\n{ok} из {total} ссылок обработано. Проверь всю подборку ещё раз.",
        EN: "<b>Some links need another try</b>\n{ok} of {total} links were processed. Check the complete collection again.",
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
    "error_rate_limit": {
        RU: (
            "Слишком много запросов подряд. Подожди примерно "
            "<b>{seconds} сек.</b> — уже собранные карточки останутся на месте."
        ),
        EN: (
            "Too many requests in a short time. Wait about "
            "<b>{seconds} sec.</b> — completed cards will stay in place."
        ),
    },
    "search_choose": {
        RU: "<b>Выбери релиз</b>\n\nНашёл несколько вариантов по запросу «{query}»:",
        EN: "<b>Choose a release</b>\n\nI found several matches for “{query}”:",
    },
    "search_change": {RU: "Изменить запрос", EN: "Change query"},
    "search_other": {RU: "Другой релиз", EN: "Another release"},
    "progress_search": {RU: "1/3 · Ищу релиз…", EN: "1/3 · Finding the release…"},
    "progress_links": {
        RU: "2/3 · Собираю площадки…",
        EN: "2/3 · Collecting platforms…",
    },
    "progress_card": {RU: "3/3 · Собираю карточку…", EN: "3/3 · Building the card…"},
    "progress_batch": {
        RU: "3/3 · Собираю подборку · {done}/{total}",
        EN: "3/3 · Building collection · {done}/{total}",
    },
    "progress_batch_start": {
        RU: "0/{total} · Проверяю ссылки…",
        EN: "0/{total} · Checking links…",
    },
    "progress_batch_links": {
        RU: "0/{total} · Получаю данные площадок…",
        EN: "0/{total} · Fetching platform data…",
    },
    "progress_batch_partial": {
        RU: "{done}/{total} · Оформляю результат и отмечаю проблемные ссылки…",
        EN: "{done}/{total} · Building the result and marking failed links…",
    },
    "progress_cancelled": {
        RU: "Поиск отменён.",
        EN: "Search cancelled.",
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
    "crate_title": {
        RU: "🧺 <b>Моя подборка · {count}/10</b>",
        EN: "🧺 <b>My crate · {count}/10</b>",
    },
    "crate_hint": {
        RU: "<blockquote>Выбери номер трека, чтобы изменить порядок или удалить его.</blockquote>",
        EN: "<blockquote>Select a track number to reorder or remove it.</blockquote>",
    },
    "crate_up": {RU: "↑ Выше", EN: "↑ Up"},
    "crate_down": {RU: "↓ Ниже", EN: "↓ Down"},
    "crate_remove": {RU: "✕ Удалить", EN: "✕ Remove"},
    "crate_clear": {RU: "Очистить", EN: "Clear"},
    "crate_clear_confirm": {
        RU: "<b>Очистить всю подборку?</b>\n\nВсе треки будут удалены. После очистки их можно вернуть кнопкой «Отменить».",
        EN: "<b>Clear the whole crate?</b>\n\nAll tracks will be removed. You can restore them with Undo.",
    },
    "crate_clear_confirm_button": {RU: "Очистить подборку", EN: "Clear crate"},
    "crate_undo": {RU: "Вернуть удалённый", EN: "Undo removal"},
    "crate_removed": {RU: "Трек удалён", EN: "Track removed"},
    "crate_restored": {RU: "Трек возвращён", EN: "Track restored"},
    "crate_find": {RU: "+ Найти первый трек", EN: "+ Find the first track"},
    "crate_rename": {RU: "✏️ Название", EN: "✏️ Name"},
    "crate_preview": {RU: "👁 Превью", EN: "👁 Preview"},
    "crate_name_prompt": {
        RU: "Напиши название подборки одним сообщением.",
        EN: "Send the collection name in one message.",
    },
    "crate_name_saved": {RU: "Название сохранено", EN: "Name saved"},
    "crate_preview_title": {RU: "Подборка", EN: "Collection"},
}
