from __future__ import annotations

import asyncio
from typing import Callable, Optional

import aiohttp

from dashparse.models.mpd import ByteRange
from dashparse.models.segment import SegmentRequest


class HTTPFetcher:
    def __init__(
        self,
        timeout: float = 30.0,
        max_concurrent: int = 6,
        headers: Optional[dict[str, str]] = None,
    ):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_concurrent = max_concurrent
        self.default_headers = headers or {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def fetch_range(
        self,
        url: str,
        byte_range: ByteRange,
        headers: Optional[dict[str, str]] = None,
    ) -> bytes:
        hdrs = {**self.default_headers, **(headers or {})}
        hdrs["Range"] = f"bytes={byte_range}"
        session = await self._ensure_session()
        async with self._semaphore:
            async with session.get(url, headers=hdrs) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def fetch_url(self, url: str, headers: Optional[dict] = None) -> bytes:
        hdrs = {**self.default_headers, **(headers or {})}
        session = await self._ensure_session()
        async with self._semaphore:
            async with session.get(url, headers=hdrs) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def fetch_segments(
        self,
        requests: list[SegmentRequest],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> list[bytes]:
        results: list[Optional[bytes]] = [None] * len(requests)
        done = 0

        async def _fetch_one(i: int, req: SegmentRequest):
            nonlocal done
            if req.byte_range:
                data = await self.fetch_range(req.url, req.byte_range, req.headers)
            else:
                data = await self.fetch_url(req.url, req.headers)
            results[i] = data
            done += 1
            if on_progress:
                on_progress(done, len(requests))

        tasks = [_fetch_one(i, req) for i, req in enumerate(requests)]
        await asyncio.gather(*tasks)
        return results  # type: ignore
