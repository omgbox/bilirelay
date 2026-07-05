from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Frame:
    track_id: int
    data: bytes
    timestamp: float
    duration: float
    is_keyframe: bool
    composition_time_offset: float = 0.0
