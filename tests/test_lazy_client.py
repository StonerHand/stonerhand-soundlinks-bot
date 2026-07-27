import asyncio
import unittest

from music_links_bot.lazy_client import LazyAsyncClient


class _Client:
    def __init__(self) -> None:
        self.closed = False

    def value(self) -> str:
        return "ready"

    async def aclose(self) -> None:
        self.closed = True


class LazyAsyncClientTests(unittest.TestCase):
    def test_provider_is_created_on_first_use_and_reused(self) -> None:
        instances: list[_Client] = []

        def factory() -> _Client:
            client = _Client()
            instances.append(client)
            return client

        client = LazyAsyncClient(factory)
        self.assertFalse(client.initialized)
        self.assertEqual(client.value(), "ready")
        self.assertEqual(client.value(), "ready")
        self.assertTrue(client.initialized)
        self.assertEqual(len(instances), 1)

    def test_close_does_not_initialize_unused_provider(self) -> None:
        client = LazyAsyncClient(_Client)
        asyncio.run(client.aclose())
        self.assertFalse(client.initialized)

    def test_close_releases_initialized_provider(self) -> None:
        client = LazyAsyncClient(_Client)
        client.value()
        instance = client._instance
        asyncio.run(client.aclose())
        self.assertTrue(instance.closed)


if __name__ == "__main__":
    unittest.main()
