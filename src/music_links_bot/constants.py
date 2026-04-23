SUPPORTED_INPUT_HOSTS = {
    "open.spotify.com",
    "spotify.com",
    "music.apple.com",
    "itunes.apple.com",
    "geo.music.apple.com",
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

PLATFORM_LABELS = {
    "spotify": "Spotify",
    "appleMusic": "Apple Music",
    "applePodcasts": "Apple Podcasts",
    "youtubeMusic": "YouTube Music",
    "deezer": "Deezer",
    "tidal": "Tidal",
    "yandexMusic": "Yandex Music",
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
    "Spotify, Apple Music, YouTube / YouTube Music, Deezer, "
    "Tidal, Yandex Music или SoundCloud, а также ссылки на подкасты"
)
