SUPPORTED_INPUT_HOSTS = {
    "open.spotify.com",
    "spotify.com",
    "music.apple.com",
    "itunes.apple.com",
    "geo.music.apple.com",
    "podcasts.apple.com",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
    "deezer.com",
    "www.deezer.com",
    "tidal.com",
    "listen.tidal.com",
    "music.yandex.ru",
    "music.yandex.com",
    "soundcloud.com",
    "m.soundcloud.com",
    "on.soundcloud.com",
    "bandcamp.com",
    "nts.live",
    "www.nts.live",
}

HTTP_USER_AGENT = "StonerHandBot/0.1 (+https://t.me/stonerhand)"
MAX_LINKS_PER_MESSAGE = 12

PLATFORM_LABELS = {
    "spotify": "🟢 Spotify",
    "appleMusic": "⚪ Apple",
    "applePodcasts": "🟣 Podcasts",
    "youtubeMusic": "🔴 YouTube",
    "soundcloud": "🟠 SoundCloud",
    "deezer": "🟦 Deezer",
    "tidal": "⚫ Tidal",
    "yandexMusic": "🟡 Yandex",
}

PLATFORM_BUTTON_STYLES = {
    # Platform identity already comes from its icon and label. Neutral
    # backgrounds keep a release keyboard calm and make the single main action
    # ("All platforms") immediately obvious.
    platform_key: None for platform_key in PLATFORM_LABELS
}

PLATFORM_ALIASES = {
    "spotify": ("spotify",),
    "appleMusic": ("appleMusic", "itunes"),
    "applePodcasts": ("applePodcasts", "itunesPodcast", "podcastApple"),
    "youtubeMusic": ("youtubeMusic", "youtube"),
    "soundcloud": ("soundcloud",),
    "deezer": ("deezer",),
    "tidal": ("tidal",),
    "yandexMusic": ("yandexMusic", "yandex"),
}
