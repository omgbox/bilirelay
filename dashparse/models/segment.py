from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dashparse.models.mpd import ByteRange, Representation

SENTINEL_INIT = -1
SENTINEL_INDEX = -2


@dataclass
class SegmentRequest:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    byte_range: Optional[ByteRange] = None
    segment_index: int = 0
    duration: Optional[float] = None
    timestamp: Optional[float] = None


@dataclass
class Segment:
    index: int
    init_data: Optional[bytes] = None
    media_data: Optional[bytes] = None
    request: Optional[SegmentRequest] = None
    duration: Optional[float] = None
    timestamp: Optional[float] = None


@dataclass
class SegmentSequence:
    representation: Representation
    init_segment: Segment
    media_segments: list[Segment] = field(default_factory=list)
    total_duration: float = 0.0
