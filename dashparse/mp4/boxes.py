from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BoxHeader:
    size: int
    box_type: str
    offset: int
    data_offset: int
    extended_size: Optional[int] = None


def read_box_header(data: memoryview | bytes, offset: int) -> BoxHeader:
    size = int.from_bytes(data[offset : offset + 4], "big")
    box_type = bytes(data[offset + 4 : offset + 8]).decode("ascii", errors="replace")
    header_size = 8
    ext_size = None
    if size == 1:
        ext_size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        header_size = 16
        size = ext_size
    elif size == 0:
        size = len(data) - offset
    return BoxHeader(
        size=size,
        box_type=box_type,
        offset=offset,
        data_offset=offset + header_size,
        extended_size=ext_size,
    )
