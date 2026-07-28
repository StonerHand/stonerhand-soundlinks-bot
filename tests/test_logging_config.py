from __future__ import annotations

import logging
import unittest

from music_links_bot.logging_config import quiet_transport_logs


class LoggingConfigTests(unittest.TestCase):
    def test_transport_urls_are_not_logged_at_info_level(self) -> None:
        httpx_logger = logging.getLogger("httpx")
        httpcore_logger = logging.getLogger("httpcore")
        previous_httpx_level = httpx_logger.level
        previous_httpcore_level = httpcore_logger.level
        try:
            httpx_logger.setLevel(logging.NOTSET)
            httpcore_logger.setLevel(logging.NOTSET)

            quiet_transport_logs()

            self.assertEqual(httpx_logger.level, logging.WARNING)
            self.assertEqual(httpcore_logger.level, logging.WARNING)
        finally:
            httpx_logger.setLevel(previous_httpx_level)
            httpcore_logger.setLevel(previous_httpcore_level)
