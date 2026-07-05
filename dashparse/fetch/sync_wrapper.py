from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional


def run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


class SyncHTTPFetcher:
    def __init__(self, **kwargs):
        from dashparse.fetch.http_fetcher import HTTPFetcher

        self._fetcher = HTTPFetcher(**kwargs)

    def fetch_range(self, url: str, byte_range: Any, headers: Optional[dict] = None) -> bytes:
        return run_async(self._fetcher.fetch_range(url, byte_range, headers))

    def fetch_url(self, url: str, headers: Optional[dict] = None) -> bytes:
        return run_async(self._fetcher.fetch_url(url, headers))

    def fetch_segments(
        self,
        requests: list,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> list[bytes]:
        return run_async(self._fetcher.fetch_segments(requests, on_progress))

    def close(self):
        run_async(self._fetcher.close())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
