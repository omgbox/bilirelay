from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Optional


class MPDType(Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"


class AddressingMode(Enum):
    SEGMENT_BASE = "segment_base"
    SEGMENT_TEMPLATE = "segment_template"
    SEGMENT_TIMELINE = "segment_timeline"
    SEGMENT_LIST = "segment_list"


@dataclass
class ByteRange:
    start: int
    end: int  # inclusive, per DASH spec

    @classmethod
    def parse(cls, s: str) -> ByteRange:
        start, end = s.split("-", 1)
        return cls(start=int(start), end=int(end))

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"

    def __repr__(self) -> str:
        return f"ByteRange({self.start}-{self.end})"

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass
class Initialization:
    range: Optional[ByteRange] = None
    source_url: Optional[str] = None


@dataclass
class SegmentBase:
    index_range: Optional[ByteRange] = None
    index_range_exact: bool = False
    initialization: Optional[Initialization] = None
    # Note: timescale and presentation_time_offset come from the sidx box,
    # not the MPD. SegmentBase in MPD only defines byte ranges.


@dataclass
class TimelineEntry:
    t: int  # start time in timescale units
    d: int  # duration
    r: int = 0  # repeat count (-1 = indefinite)


@dataclass
class SegmentTemplate:
    media: str = ""  # e.g. "segment_$Number$.m4s"
    initialization: str = ""  # e.g. "init_$RepresentationID$.m4s"
    timescale: int = 1
    start_number: int = 1
    duration: Optional[int] = None
    presentation_time_offset: int = 0
    timeline: list[TimelineEntry] = field(default_factory=list)


@dataclass
class BaseURL:
    """Base URL with optional serviceLocation and availabilityTimeOffset."""

    url: str
    service_location: Optional[str] = None
    availability_time_offset: Optional[float] = None
    availability_time_complete: bool = True

    @classmethod
    def resolve(cls, *bases: Optional[BaseURL]) -> str:
        result = ""
        for base in bases:
            if base is not None:
                result = base.url
        return result


@dataclass
class Representation:
    id: str
    bandwidth: int
    base_url: Optional[BaseURL] = None
    codecs: str = ""
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[str] = None
    audio_sampling_rate: Optional[int] = None
    segment_base: Optional[SegmentBase] = None
    segment_template: Optional[SegmentTemplate] = None


@dataclass
class AdaptationSet:
    id: Optional[int] = None
    mime_type: Optional[str] = None
    segment_alignment: bool = False
    lang: Optional[str] = None
    representations: list[Representation] = field(default_factory=list)
    segment_base: Optional[SegmentBase] = None
    segment_template: Optional[SegmentTemplate] = None


@dataclass
class Period:
    id: Optional[str] = None
    start: Optional[timedelta] = None
    duration: Optional[timedelta] = None
    adaptation_sets: list[AdaptationSet] = field(default_factory=list)


@dataclass
class MPD:
    type: MPDType = MPDType.STATIC
    min_buffer_time: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    media_presentation_duration: Optional[timedelta] = None
    profiles: list[str] = field(default_factory=list)
    periods: list[Period] = field(default_factory=list)
    base_url: Optional[BaseURL] = None
