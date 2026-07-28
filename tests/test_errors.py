import unittest

from music_links_bot.errors import normalize_api_response


class ApiErrorContractTests(unittest.TestCase):
    def test_legacy_error_gets_stable_code_and_retryability(self) -> None:
        result = normalize_api_response(
            {"ok": False, "error": "draft not found"}
        )
        self.assertEqual(result["error_code"], "draft_expired")
        self.assertFalse(result["retryable"])

    def test_transient_error_is_retryable(self) -> None:
        result = normalize_api_response({"ok": False, "error": "queue_busy"})
        self.assertEqual(result["error_code"], "action_busy")
        self.assertTrue(result["retryable"])

    def test_success_response_is_untouched(self) -> None:
        payload = {"ok": True, "items": []}
        self.assertIs(normalize_api_response(payload), payload)


if __name__ == "__main__":
    unittest.main()
