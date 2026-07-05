from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from dashparse.exceptions import MPDValidationError
from dashparse.models.mpd import ByteRange, Representation, TimelineEntry
from dashparse.models.segment import SENTINEL_INDEX, SENTINEL_INIT, SegmentRequest
from dashparse.mp4.sidx import parse_sidx
from dashparse.parser.templates import expand_template


def resolve_segment_base(
    base_url: str,
    rep: Representation,
) -> list[SegmentRequest]:
    sb = rep.segment_base
    if sb is None:
        raise MPDValidationError(f"Representation '{rep.id}' has no SegmentBase")
    requests = []

    if sb.initialization:
        init_url = sb.initialization.source_url or base_url
        if sb.initialization.range:
            requests.append(
                SegmentRequest(
                    url=init_url,
                    byte_range=sb.initialization.range,
                    headers={"Range": f"bytes={sb.initialization.range}"},
                    segment_index=SENTINEL_INIT,
                )
            )
        else:
            requests.append(
                SegmentRequest(
                    url=init_url,
                    segment_index=SENTINEL_INIT,
                )
            )

    if sb.index_range:
        requests.append(
            SegmentRequest(
                url=base_url,
                byte_range=sb.index_range,
                headers={"Range": f"bytes={sb.index_range}"},
                segment_index=SENTINEL_INDEX,
            )
        )

    return requests


def expand_sidx(
    base_url: str,
    sidx_data: bytes,
    sidx_file_offset: int,
) -> list[SegmentRequest]:
    sidx = parse_sidx(sidx_data)
    media_start = sidx_file_offset + sidx.first_offset
    requests = []
    offset = media_start

    for i, ref in enumerate(sidx.references):
        end = offset + ref.referenced_size - 1
        requests.append(
            SegmentRequest(
                url=base_url,
                byte_range=ByteRange(offset, end),
                headers={"Range": f"bytes={offset}-{end}"},
                segment_index=i,
                duration=ref.segment_duration / sidx.timescale if sidx.timescale else 0,
            )
        )
        offset = end + 1

    return requests


def resolve_segment_template(
    base_url: str,
    rep: Representation,
    period_duration: Optional[float] = None,
) -> list[SegmentRequest]:
    tmpl = rep.segment_template
    if tmpl is None:
        raise MPDValidationError(f"Representation '{rep.id}' has no SegmentTemplate")
    requests = []

    init_url = expand_template(tmpl.initialization, rep.id, rep.bandwidth)
    requests.append(
        SegmentRequest(
            url=urljoin(base_url, init_url),
            segment_index=SENTINEL_INIT,
        )
    )

    if tmpl.timeline:
        for entry in tmpl.timeline:
            if entry.r < 0:
                repeat_count = None
            else:
                repeat_count = entry.r + 1

            t = entry.t
            generated = 0
            while repeat_count is None or generated < repeat_count:
                if period_duration and t / tmpl.timescale >= period_duration:
                    break

                url = expand_template(
                    tmpl.media,
                    rep.id,
                    rep.bandwidth,
                    time=t,
                )
                requests.append(
                    SegmentRequest(
                        url=urljoin(base_url, url),
                        segment_index=len(requests),
                        timestamp=t / tmpl.timescale,
                        duration=entry.d / tmpl.timescale,
                    )
                )
                t += entry.d
                generated += 1
    elif tmpl.duration:
        number = tmpl.start_number
        accumulated = 0.0
        seg_dur = tmpl.duration / tmpl.timescale
        while period_duration is None or accumulated < period_duration:
            url = expand_template(
                tmpl.media,
                rep.id,
                rep.bandwidth,
                number=number,
            )
            requests.append(
                SegmentRequest(
                    url=urljoin(base_url, url),
                    segment_index=len(requests),
                    duration=seg_dur,
                )
            )
            number += 1
            accumulated += seg_dur

    return requests
