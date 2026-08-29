from __future__ import annotations

import json
from importlib.resources import files
from string import Formatter

RU = "ru"
EN = "en"
_SUPPORTED_LANGUAGES = (RU, EN)
_RU_FAMILY_PREFIXES = ("ru", "uk", "be", "kk")
_CATALOG_RESOURCE = "locales/catalog.json"


def _load_catalog() -> dict[str, dict[str, str]]:
    """Load the packaged UI catalog once at module import."""
    resource = files("music_links_bot").joinpath(_CATALOG_RESOURCE)
    with resource.open(encoding="utf-8") as catalog_file:
        payload = json.load(catalog_file)
    if not isinstance(payload, dict):
        raise TypeError("Locale catalog must contain a JSON object")
    return payload


STRINGS: dict[str, dict[str, str]] = _load_catalog()


def resolve_lang(language_code: str | None) -> str:
    """Resolve the menu language without changing editorial post text."""
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
        if not isinstance(entry, dict):
            errors.append(f"{key}: entry is not an object")
            continue
        missing_languages = [
            lang
            for lang in _SUPPORTED_LANGUAGES
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
            for lang in _SUPPORTED_LANGUAGES
        }
        if fields[RU] != fields[EN]:
            errors.append(
                f"{key}: placeholders differ "
                f"({sorted(fields[RU])!r} != {sorted(fields[EN])!r})"
            )
    return tuple(errors)
