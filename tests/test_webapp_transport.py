import unittest
from types import SimpleNamespace

from api.webapp_transport import StudioRequestHandler


class StudioRequestHandlerTests(unittest.TestCase):
    def test_public_get_is_read_only_and_does_not_boot_the_bot(self) -> None:
        responses = []
        receiver = SimpleNamespace(
            _send_json=responses.append,
            ensure_application=lambda: self.fail("GET must not initialize Telegram"),
        )

        StudioRequestHandler.do_GET(receiver)

        self.assertEqual(
            responses,
            [{"ok": True, "service": "StonerHand studio API"}],
        )


if __name__ == "__main__":
    unittest.main()
