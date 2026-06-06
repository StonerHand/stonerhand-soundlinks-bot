import json
import unittest

from api.set_webhook import ALLOWED_UPDATES
from api.telegram import _decode_update_payload, _read_content_length


class VercelWebhookTests(unittest.TestCase):
    def test_decode_update_payload_accepts_json_objects(self) -> None:
        self.assertEqual(_decode_update_payload(b'{"update_id": 1}'), {"update_id": 1})

    def test_decode_update_payload_rejects_non_object_json(self) -> None:
        with self.assertRaises(ValueError):
            _decode_update_payload(b"[]")

    def test_decode_update_payload_rejects_invalid_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            _decode_update_payload(b"{")

    def test_read_content_length_handles_missing_and_invalid_values(self) -> None:
        self.assertEqual(_read_content_length(None), 0)
        self.assertEqual(_read_content_length("42"), 42)
        self.assertIsNone(_read_content_length("not-a-number"))

    def test_webhook_accepts_menu_button_callbacks(self) -> None:
        self.assertIn("callback_query", ALLOWED_UPDATES)


if __name__ == "__main__":
    unittest.main()
