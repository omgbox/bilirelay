from dashparse.models.mpd import (
    MPD,
    MPDType,
    AddressingMode,
    Period,
    AdaptationSet,
    Representation,
    BaseURL,
    SegmentBase,
    SegmentTemplate,
    Initialization,
    ByteRange,
    TimelineEntry,
)
from dashparse.models.segment import (
    SegmentRequest,
    Segment,
    SegmentSequence,
    SENTINEL_INIT,
    SENTINEL_INDEX,
)
from dashparse.parser.mpd_parser import parse_mpd, detect_addressing
from dashparse.parser.segment_resolver import (
    resolve_segment_base,
    resolve_segment_template,
    expand_sidx,
)
from dashparse.parser.templates import expand_template
from dashparse.fetch.http_fetcher import HTTPFetcher
from dashparse.fetch.sync_wrapper import SyncHTTPFetcher, run_async
from dashparse.fetch.pool import fetch_segment_sequence
from dashparse.demux.mp4_demuxer import MP4Demuxer
from dashparse.demux.frame import Frame
from dashparse.remux.mp4_remuxer import MP4Remuxer
from dashparse.exceptions import (
    DashParseError,
    MPDValidationError,
    SegmentFetchError,
    SIDXParseError,
    TemplateExpansionError,
    UnsupportedProfileError,
)

from typing import Optional


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


async def parse_and_fetch(
    source: str,
    *,
    representation_id: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    fetcher: Optional[HTTPFetcher] = None,
    period_duration: Optional[float] = None,
) -> SegmentSequence:
    own_fetcher = fetcher is None
    if is_url(source):
        f = fetcher or HTTPFetcher(headers=headers)
        try:
            mpd_xml = (await f.fetch_url(source)).decode("utf-8")
        finally:
            if own_fetcher:
                await f.close()
    else:
        mpd_xml = source

    mpd = parse_mpd(mpd_xml)
    if not mpd.periods:
        raise MPDValidationError("No periods found in MPD")

    period = mpd.periods[0]
    if not period.adaptation_sets:
        raise MPDValidationError("No adaptation sets found")

    rep = None
    for adapt in period.adaptation_sets:
        for r in adapt.representations:
            if representation_id and r.id != representation_id:
                continue
            rep = r
            break
        if rep:
            break

    if rep is None:
        raise MPDValidationError(f"Representation '{representation_id}' not found")

    # Resolve base_url through the hierarchy for the selected representation
    adapt_base = None
    for adapt in period.adaptation_sets:
        if rep in adapt.representations:
            adapt_base = adapt.representations[0].base_url
            break
    base_url = BaseURL.resolve(mpd.base_url, adapt_base, rep.base_url)

    own_fetcher = fetcher is None
    if fetcher is None:
        fetcher = HTTPFetcher(headers=headers)

    try:
        return await fetch_segment_sequence(
            fetcher,
            base_url,
            rep,
            period_duration=period_duration,
        )
    finally:
        if own_fetcher:
            await fetcher.close()


def parse_and_fetch_sync(source: str, **kwargs) -> SegmentSequence:
    return run_async(parse_and_fetch(source, **kwargs))


__all__ = [
    "MPD",
    "MPDType",
    "AddressingMode",
    "Period",
    "AdaptationSet",
    "Representation",
    "BaseURL",
    "SegmentBase",
    "SegmentTemplate",
    "Initialization",
    "ByteRange",
    "TimelineEntry",
    "SegmentRequest",
    "Segment",
    "SegmentSequence",
    "SENTINEL_INIT",
    "SENTINEL_INDEX",
    "parse_mpd",
    "detect_addressing",
    "resolve_segment_base",
    "resolve_segment_template",
    "expand_sidx",
    "expand_template",
    "HTTPFetcher",
    "SyncHTTPFetcher",
    "run_async",
    "fetch_segment_sequence",
    "MP4Demuxer",
    "Frame",
    "MP4Remuxer",
    "DashParseError",
    "MPDValidationError",
    "SegmentFetchError",
    "SIDXParseError",
    "TemplateExpansionError",
    "UnsupportedProfileError",
    "is_url",
    "parse_and_fetch",
    "parse_and_fetch_sync",
]
