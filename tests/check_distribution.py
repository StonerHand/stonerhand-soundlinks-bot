"""Exercise the distributable itself, without importing the source checkout."""

from __future__ import annotations

import hashlib
import importlib
import json
import pkgutil
import sys
from importlib.resources import files
from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    wheel = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(wheel))
    import music_links_bot

    assert str(music_links_bot.__file__).startswith(str(wheel))
    for module in pkgutil.iter_modules(music_links_bot.__path__):
        if module.name != "__main__":
            importlib.import_module(f"music_links_bot.{module.name}")

    from music_links_bot.i18n import validate_catalog
    from music_links_bot.release_smoke import build_release_smoke_report

    assert validate_catalog() == ()
    assert build_release_smoke_report()["ok"]
    resources = files("music_links_bot")
    assert json.loads(resources.joinpath("locales/catalog.json").read_text())
    brandmark = resources.joinpath("assets/brandmark.png").read_bytes()
    assert (
        hashlib.sha256(brandmark).hexdigest()
        == "132ca07bddeb3764a308aeab8b2546ff4c67a5b2796080d04918ed20fc80b4ac"
    )
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        assert any(name.endswith("/licenses/LICENSE") for name in names)
        assert not any(Path(name).name.startswith(".env") for name in names)
        metadata = archive.read(
            next(name for name in names if name.endswith("/METADATA"))
        ).decode()
        assert f"Version: {music_links_bot.__version__}\n" in metadata
    print(
        f"Distribution {music_links_bot.__version__}: imports, publication contract, translations, artwork and license OK"
    )


if __name__ == "__main__":
    main()
