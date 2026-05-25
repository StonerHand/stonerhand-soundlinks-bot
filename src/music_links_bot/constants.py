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
}

HTTP_USER_AGENT = "StonerHandBot/0.1 (+https://t.me/stonerhand)"

PLATFORM_LABELS = {
    "spotify": "🟢 Spotify",
    "appleMusic": "🍎 Apple",
    "applePodcasts": "🎙 Podcasts",
    "youtubeMusic": "▶️ YouTube",
    "deezer": "🟦 Deezer",
    "tidal": "🌊 Tidal",
    "yandexMusic": "🟡 Yandex",
}

PLATFORM_ALIASES = {
    "spotify": ("spotify",),
    "appleMusic": ("appleMusic", "itunes"),
    "applePodcasts": ("applePodcasts", "itunesPodcast", "podcastApple"),
    "youtubeMusic": ("youtubeMusic", "youtube"),
    "deezer": ("deezer",),
    "tidal": ("tidal",),
    "yandexMusic": ("yandexMusic", "yandex"),
}

INPUT_PLATFORM_HINT = (
    "Spotify (треки, альбомы, плейлисты, артисты), Apple Music / Apple Podcasts, "
    "YouTube / YouTube Music, Deezer, Tidal, Yandex Music или SoundCloud"
)
