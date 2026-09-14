"""Validated, provider-supplied navigation and duration metadata."""

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from music_links_bot.url_utils import apple_music_url_type, spotify_url_type


def metadata_url(value: object, kind: str) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if spotify_url_type(url) == kind:
        return url
    if apple_music_url_type(url) == kind:
        # Apple track links use an album path with an `i` query parameter.
        if kind != "album" or not parse_qs(urlsplit(url).query).get("i"):
            return url
    return None


def duration_ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        milliseconds = int(value)
    except (ValueError, OverflowError):
        return None
    return milliseconds if 0 < milliseconds <= 7 * 24 * 3600 * 1000 else None


def duration_label(value: object) -> str | None:
    milliseconds = duration_ms(value)
    if milliseconds is None:
        return None
    seconds = max(1, (milliseconds + 500) // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes_in_hour = divmod(minutes, 60)
    return (
        f"{hours}:{minutes_in_hour:02}:{seconds:02}"
        if hours
        else f"{minutes}:{seconds:02}"
    )


def spotify_entity_url(value: object, kind: str) -> str | None:
    if isinstance(value, str) and value.startswith(f"spotify:{kind}:"):
        value = "https://open.spotify.com/" + kind + "/" + value.rsplit(":", 1)[-1]
    return metadata_url(value, kind)


def apple_album_url(value: object, collection_id: object) -> str | None:
    """Apple's collectionViewUrl can still point to the selected track."""
    if not isinstance(value, str) or apple_music_url_type(value) != "album":
        return None
    parsed = urlsplit(value)
    if not str(collection_id).isdigit() or parsed.path.rstrip("/").rsplit("/", 1)[
        -1
    ] != str(collection_id):
        return None
    query = parse_qs(parsed.query)
    query.pop("i", None)
    return metadata_url(
        urlunsplit(parsed._replace(query=urlencode(query, doseq=True))), "album"
    )
