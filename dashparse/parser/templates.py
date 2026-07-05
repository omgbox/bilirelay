from __future__ import annotations

import re
from typing import Optional


def expand_template(
    template: str,
    representation_id: str,
    bandwidth: int,
    number: Optional[int] = None,
    time: Optional[int] = None,
    sub_number: Optional[int] = None,
) -> str:
    url = template
    url = url.replace("$RepresentationID$", representation_id)
    url = url.replace("$Bandwidth$", str(bandwidth))
    if number is not None:
        m = re.search(r"\$Number(?:%0(\d+)d)?\$", url)
        if m:
            width = int(m.group(1)) if m.group(1) else 0
            url = url[: m.start()] + str(number).zfill(width) + url[m.end() :]
    if time is not None:
        url = url.replace("$Time$", str(time))
    if sub_number is not None:
        url = url.replace("$SubNumber$", str(sub_number))
    return url
