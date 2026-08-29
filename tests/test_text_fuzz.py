import random
import unittest

from telegram import MessageEntity

from music_links_bot.telegram_text import (
    format_user_note_html,
    telegram_text_length,
)
from music_links_bot.url_utils import (
    extract_supported_urls,
    strip_supported_urls_with_mapping,
)


class TelegramTextFuzzTests(unittest.TestCase):
    def test_supported_urls_never_survive_random_user_text(self) -> None:
        randomizer = random.Random(190_300)
        sources = (
            "https://open.spotify.com/track/3E4MuCjetGIkeu2N8fFHgr?si=test",
            "https://music.apple.com/us/song/x/1780000001?i=1780000002",
            "https://soundcloud.com/stoner-hand/example-set",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.nts.live/shows/example/episodes/one",
            "https://deezer.com/track/123456",
            "https://tidal.com/browse/track/123456",
        )
        words = ("музыка", "Slowdive", "текст", "🪨", "line", "альбом")
        separators = (" ", "\n", "\n\n", " — ", ": ", "\r\n")
        wrappers = (("", ""), ("(", ")"), ("«", "»"), ("[", "]"))

        for _ in range(400):
            url = randomizer.choice(sources)
            left, right = randomizer.choice(wrappers)
            source = (
                randomizer.choice(words)
                + randomizer.choice(separators)
                + left
                + url
                + right
                + randomizer.choice(separators)
                + randomizer.choice(words)
            )
            if randomizer.random() < 0.35:
                source += randomizer.choice(separators) + randomizer.choice(sources)

            stripped, mapping = strip_supported_urls_with_mapping(source)
            self.assertFalse(extract_supported_urls(stripped), source)
            self.assertEqual(len(stripped), len(mapping))
            self.assertEqual(tuple(sorted(mapping)), mapping)
            self.assertEqual(len(set(mapping)), len(mapping))
            for character, source_index in zip(stripped, mapping, strict=True):
                expected = source[source_index]
                self.assertEqual(character, "\n" if expected == "\r" else expected)

            entity = MessageEntity(
                type=MessageEntity.TEXT_LINK,
                offset=0,
                length=telegram_text_length(source),
                url=url,
            )
            rendered = format_user_note_html(
                source,
                [entity],
                max_length=3_000,
            )
            self.assertFalse(extract_supported_urls(rendered), source)
            self.assertNotIn('href="https://', rendered)

    def test_random_external_links_remain_safe_and_clickable(self) -> None:
        randomizer = random.Random(103)
        for _ in range(100):
            text = "Примечание " + "🪨" * randomizer.randint(0, 20)
            entity = MessageEntity(
                type=MessageEntity.TEXT_LINK,
                offset=0,
                length=telegram_text_length(text),
                url="https://example.com/editorial?x=1&y=2",
            )
            rendered = format_user_note_html(text, [entity], max_length=3_000)
            self.assertIn("https://example.com/editorial?x=1&amp;y=2", rendered)


if __name__ == "__main__":
    unittest.main()
