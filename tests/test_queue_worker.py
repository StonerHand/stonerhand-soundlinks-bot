import os
import unittest
from unittest.mock import patch

from api.queue_worker import is_authorized


class QueueWorkerAuthTests(unittest.TestCase):
    def test_worker_requires_cron_bearer_secret(self) -> None:
        with patch.dict(os.environ, {"CRON_SECRET": "secret"}, clear=True):
            self.assertTrue(is_authorized("Bearer secret"))
            self.assertFalse(is_authorized("Bearer wrong"))
            self.assertFalse(is_authorized(None))

    def test_worker_is_closed_when_secret_is_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_authorized(None))


if __name__ == "__main__":
    unittest.main()
