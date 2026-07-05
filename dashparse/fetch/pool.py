from __future__ import annotations

import asyncio
from typing import Callable, Optional

from dashparse.fetch.http_fetcher import HTTPFetcher
from dashparse.models.segment import SegmentRequest, SegmentSequence
from dashparse.parser.segment_resolver import expand_sidx, resolve_segment_base
from dashparse.parser.segment_resolver import resolve_segment_template


async def fetch_segment_sequence(
    fetcher: HTTPFetcher,
    base_url: str,
    rep,
    period_duration: Optional[float] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> SegmentSequence:
    from dashparse.models.mpd import AddressingMode
    from dashparse.parser.mpd_parser import detect_addressing

    mode = detect_addressing(rep)

    if mode == AddressingMode.SEGMENT_BASE:
        return await _fetch_segment_base(fetcher, base_url, rep, on_progress)
    elif mode in (AddressingMode.SEGMENT_TEMPLATE, AddressingMode.SEGMENT_TIMELINE):
        return await _fetch_segment_template(fetcher, base_url, rep, period_duration, on_progress)
    else:
        raise ValueError(f"Unsupported addressing mode: {mode}")


async def _fetch_segment_base(
    fetcher: HTTPFetcher,
    base_url: str,
    rep,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> SegmentSequence:
    from dashparse.models.segment import Segment, SENTINEL_INIT, SENTINEL_INDEX

    requests = resolve_segment_base(base_url, rep)
    results = await fetcher.fetch_segments(requests, on_progress)

    init_data = None
    sidx_data = None
    sidx_offset = 0

    for req, data in zip(requests, results):
        if req.segment_index == SENTINEL_INIT:
            init_data = data
        elif req.segment_index == SENTINEL_INDEX:
            sidx_data = data
            sidx_offset = req.byte_range.start if req.byte_range else 0

    if sidx_data is None:
        raise ValueError("Failed to fetch sidx data")

    media_requests = expand_sidx(base_url, sidx_data, sidx_offset)
    media_results = await fetcher.fetch_segments(media_requests, on_progress)

    total_duration = sum(r.duration or 0 for r in media_requests)

    init_segment = Segment(
        index=SENTINEL_INIT,
        init_data=init_data,
        media_data=init_data,
    )

    media_segments = []
    for i, (req, data) in enumerate(zip(media_requests, media_results)):
        media_segments.append(
            Segment(
                index=i,
                media_data=data,
                request=req,
                duration=req.duration,
                timestamp=req.timestamp,
            )
        )

    return SegmentSequence(
        representation=rep,
        init_segment=init_segment,
        media_segments=media_segments,
        total_duration=total_duration,
    )


async def _fetch_segment_template(
    fetcher: HTTPFetcher,
    base_url: str,
    rep,
    period_duration: Optional[float],
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> SegmentSequence:
    from dashparse.models.segment import Segment, SENTINEL_INIT

    requests = resolve_segment_template(base_url, rep, period_duration)
    results = await fetcher.fetch_segments(requests, on_progress)

    init_data = results[0] if results else None
    init_segment = Segment(
        index=SENTINEL_INIT,
        init_data=init_data,
        media_data=init_data,
    )

    total_duration = 0.0
    media_segments = []
    for i, (req, data) in enumerate(zip(requests[1:], results[1:])):
        dur = req.duration or 0
        total_duration += dur
        media_segments.append(
            Segment(
                index=i,
                media_data=data,
                request=req,
                duration=req.duration,
                timestamp=req.timestamp,
            )
        )

    return SegmentSequence(
        representation=rep,
        init_segment=init_segment,
        media_segments=media_segments,
        total_duration=total_duration,
    )
