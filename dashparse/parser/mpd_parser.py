from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Optional

from dashparse.exceptions import MPDValidationError
from dashparse.models.mpd import (
    AdaptationSet,
    AddressingMode,
    BaseURL,
    ByteRange,
    Initialization,
    MPD,
    MPDType,
    Period,
    Representation,
    SegmentBase,
    SegmentTemplate,
    TimelineEntry,
)

NS = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}


def _parse_duration(s: Optional[str]) -> Optional[timedelta]:
    if s is None:
        return None
    return _iso8601_to_timedelta(s)


def _iso8601_to_timedelta(s: str) -> timedelta:
    total = 0.0
    num = ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch == "H":
            total += float(num) * 3600
            num = ""
        elif ch == "M":
            total += float(num) * 60
            num = ""
        elif ch == "S":
            total += float(num)
            num = ""
        elif ch == "T":
            continue
    return timedelta(seconds=total)


def _find(el: ET.Element, tag: str) -> Optional[ET.Element]:
    return el.find(f"mpd:{tag}", NS)


def _findall(el: ET.Element, tag: str) -> list[ET.Element]:
    return el.findall(f"mpd:{tag}", NS)


def _attrib(el: ET.Element, name: str, default: Optional[str] = None) -> Optional[str]:
    return el.get(name, default)


def _parse_byte_range(s: Optional[str]) -> Optional[ByteRange]:
    if s is None:
        return None
    return ByteRange.parse(s)


def _parse_initialization(el: Optional[ET.Element]) -> Optional[Initialization]:
    if el is None:
        return None
    range_str = _attrib(el, "range")
    source_url = _attrib(el, "sourceURL")
    return Initialization(
        range=_parse_byte_range(range_str),
        source_url=source_url,
    )


def _parse_segment_base(el: Optional[ET.Element]) -> Optional[SegmentBase]:
    if el is None:
        return None
    init_el = _find(el, "Initialization")
    return SegmentBase(
        index_range=_parse_byte_range(_attrib(el, "indexRange")),
        index_range_exact=_attrib(el, "indexRangeExact", "false") == "true",
        initialization=_parse_initialization(init_el),
    )


def _parse_timeline_entry(el: ET.Element) -> TimelineEntry:
    return TimelineEntry(
        t=int(el.get("t", "0")),
        d=int(el.get("d", "0")),
        r=int(el.get("r", "0")),
    )


def _parse_segment_template(el: Optional[ET.Element]) -> Optional[SegmentTemplate]:
    if el is None:
        return None
    timeline = []
    timeline_el = _find(el, "SegmentTimeline")
    if timeline_el is not None:
        for s_el in _findall(timeline_el, "S"):
            timeline.append(_parse_timeline_entry(s_el))
    return SegmentTemplate(
        media=_attrib(el, "media", ""),
        initialization=_attrib(el, "initialization", ""),
        timescale=int(_attrib(el, "timescale", "1")),
        start_number=int(_attrib(el, "startNumber", "1")),
        duration=int(el.get("duration")) if el.get("duration") else None,
        presentation_time_offset=int(_attrib(el, "presentationTimeOffset", "0")),
        timeline=timeline,
    )


def _parse_base_url(el: Optional[ET.Element]) -> Optional[BaseURL]:
    if el is None:
        return None
    text = el.text
    if text is None:
        return None
    ato_str = _attrib(el, "availabilityTimeOffset")
    ato = None
    if ato_str is not None:
        try:
            ato = float(ato_str)
        except ValueError:
            ato = None  # "Infinity" or invalid
    return BaseURL(
        url=text.strip(),
        service_location=_attrib(el, "serviceLocation"),
        availability_time_offset=ato,
        availability_time_complete=_attrib(el, "availabilityTimeComplete", "true") == "true",
    )


def _safe_int(val: Optional[str], default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _parse_representation(
    el: ET.Element,
    adapt_mime: Optional[str],
    adapt_segment_base: Optional[SegmentBase],
    adapt_segment_template: Optional[SegmentTemplate],
) -> Representation:
    rep_id = _attrib(el, "id", "")
    bandwidth = _safe_int(_attrib(el, "bandwidth"), 0)
    base_url_el = _find(el, "BaseURL")
    base_url = _parse_base_url(base_url_el)

    seg_base = _parse_segment_base(_find(el, "SegmentBase"))
    seg_tmpl = _parse_segment_template(_find(el, "SegmentTemplate"))

    if seg_base is None and adapt_segment_base is not None:
        seg_base = adapt_segment_base
    if seg_tmpl is None and adapt_segment_template is not None:
        seg_tmpl = adapt_segment_template

    return Representation(
        id=rep_id,
        bandwidth=bandwidth,
        base_url=base_url,
        codecs=_attrib(el, "codecs", ""),
        mime_type=_attrib(el, "mimeType", adapt_mime),
        width=_safe_int(el.get("width")) or None,
        height=_safe_int(el.get("height")) or None,
        frame_rate=_attrib(el, "frameRate"),
        audio_sampling_rate=_safe_int(el.get("audioSamplingRate")) or None,
        segment_base=seg_base,
        segment_template=seg_tmpl,
    )


def _parse_adaptation_set(el: ET.Element) -> AdaptationSet:
    mime = _attrib(el, "mimeType")
    seg_base = _parse_segment_base(_find(el, "SegmentBase"))
    seg_tmpl = _parse_segment_template(_find(el, "SegmentTemplate"))

    reps = []
    for rep_el in _findall(el, "Representation"):
        reps.append(_parse_representation(rep_el, mime, seg_base, seg_tmpl))

    return AdaptationSet(
        id=int(_attrib(el, "id", "-1")) if _attrib(el, "id") else None,
        mime_type=mime,
        segment_alignment=_attrib(el, "segmentAlignment", "false") == "true",
        lang=_attrib(el, "lang"),
        representations=reps,
        segment_base=seg_base,
        segment_template=seg_tmpl,
    )


def _parse_period(el: ET.Element) -> Period:
    start_str = _attrib(el, "start")
    dur_str = _attrib(el, "duration")
    return Period(
        id=_attrib(el, "id"),
        start=_parse_duration(start_str),
        duration=_parse_duration(dur_str),
        adaptation_sets=[_parse_adaptation_set(a) for a in _findall(el, "AdaptationSet")],
    )


def parse_mpd(xml: str | bytes) -> MPD:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    root = ET.fromstring(xml)

    mpd_type_str = _attrib(root, "type", "static")
    mpd_type = MPDType(mpd_type_str)

    profiles_str = _attrib(root, "profiles", "")
    profiles = [p.strip() for p in profiles_str.split(",") if p.strip()]

    min_buffer = _parse_duration(_attrib(root, "minBufferTime", "PT0S"))
    mpd_dur = _parse_duration(_attrib(root, "mediaPresentationDuration"))

    base_url_el = _find(root, "BaseURL")
    base_url = _parse_base_url(base_url_el)

    periods = [_parse_period(p) for p in _findall(root, "Period")]

    return MPD(
        type=mpd_type,
        min_buffer_time=min_buffer or timedelta(seconds=0),
        media_presentation_duration=mpd_dur,
        profiles=profiles,
        periods=periods,
        base_url=base_url,
    )


def detect_addressing(rep: Representation) -> AddressingMode:
    if rep.segment_base:
        return AddressingMode.SEGMENT_BASE
    if rep.segment_template:
        if rep.segment_template.timeline:
            return AddressingMode.SEGMENT_TIMELINE
        return AddressingMode.SEGMENT_TEMPLATE
    raise MPDValidationError(
        f"Representation '{rep.id}' has no SegmentBase or SegmentTemplate"
    )
