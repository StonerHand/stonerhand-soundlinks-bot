import io
import json
import unittest
from pathlib import Path

from api.smoke import handler
from music_links_bot.release_smoke import build_release_smoke_report

SNAPSHOT = Path(__file__).parent / "snapshots" / "release_smoke.json"


class ReleaseSmokeTests(unittest.TestCase):
    def test_release_matrix_matches_reviewed_snapshot(self) -> None:
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        report = build_release_smoke_report()

        self.assertTrue(report["ok"])
        self.assertEqual(report, expected)

    def test_api_exposes_the_same_release_contract(self) -> None:
        class HandlerStub:
            def __init__(self) -> None:
                self.status = None
                self.headers: dict[str, str] = {}
                self.wfile = io.BytesIO()

            def send_response(self, status) -> None:
                self.status = status

            def send_header(self, name: str, value: str) -> None:
                self.headers[name.casefold()] = value

            def end_headers(self) -> None:
                return None

        target = HandlerStub()
        handler.do_GET(target)

        self.assertEqual(target.status, 200)
        self.assertIn("application/json", target.headers["content-type"])
        self.assertEqual(
            json.loads(target.wfile.getvalue()), build_release_smoke_report()
        )


if __name__ == "__main__":
    unittest.main()
