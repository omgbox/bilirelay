# dashparse

A Python library for parsing DASH MPD manifests and streaming video content. Supports SegmentBase (byte-range), SegmentTemplate, and SegmentTimeline addressing modes.

## Features

- Parse DASH MPD manifests into Python objects
- Resolve segment URLs for all addressing modes (SegmentBase, SegmentTemplate, SegmentTimeline)
- Fetch segments with async HTTP (aiohttp) and concurrency control
- Demux fMP4 segments into raw frames
- Remux fMP4 segments (strip headers, concat, ffmpeg mux)
- Parse and encode SIDX (Segment Index) boxes
- Bilibili.tv stream extraction and VLC playback

## Installation

```bash
pip install aiohttp
```

## Library Usage

### Parse an MPD

```python
from dashparse import parse_mpd

with open("video.mpd") as f:
    mpd = parse_mpd(f.read())

print(f"Periods: {len(mpd.periods)}")
print(f"Duration: {mpd.media_presentation_duration}")
```

### Fetch segments

```python
import asyncio
from dashparse import parse_and_fetch

async def main():
    result = await parse_and_fetch(
        "https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd"
    )
    print(f"Segments: {len(result.media_segments)}")
    print(f"Duration: {result.total_duration:.1f}s")

asyncio.run(main())
```

### Sync wrapper

```python
from dashparse import parse_and_fetch_sync

result = parse_and_fetch_sync(
    "https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd"
)
```

### Select specific representation

```python
result = parse_and_fetch_sync(
    "https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd",
    representation_id="bbb_30fps_320x180_200k"
)
```

### Demux segments

```python
from dashparse import parse_and_fetch_sync, MP4Demuxer

result = parse_and_fetch_sync("https://example.com/video.mpd")
demuxer = MP4Demuxer()

for seg in result.media_segments[:3]:
    frames = demuxer.demux(
        result.init_segment.media_data,
        seg.media_data
    )
    print(f"Segment {seg.index}: {len(frames)} frames")
```

### Custom HTTP fetcher

```python
from dashparse import HTTPFetcher, parse_and_fetch

async def main():
    fetcher = HTTPFetcher(
        timeout=30.0,
        max_concurrent=4,
        headers={"Referer": "https://example.com/"}
    )
    result = await parse_and_fetch(
        "https://example.com/video.mpd",
        fetcher=fetcher
    )
    await fetcher.close()
```

## Bilibili Stream Player

Extract and play bilibili.tv videos via VLC.

### Usage

```bash
# Interactive mode - lists streams and prompts for selection
python apps/bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" -l

# Direct quality selection
python apps/bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" -q 0 -a 0

# Just list streams (no play)
python apps/bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" -l --mpd-only
```

### Options

| Flag | Description |
|------|-------------|
| `-l`, `--list` | List available streams and select interactively |
| `-q`, `--quality N` | Video quality index (0 = lowest) |
| `-a`, `--audio N` | Audio quality index (0 = best) |
| `--mpd-only` | Output MPD XML without playing |
| `--vlc PATH` | Custom VLC executable path |

### Example

```
$ python apps/bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" -l

Fetching: https://www.bilibili.tv/en/video/4800104493751296
Video ID: 4800104493751296

  Video streams:
  IDX  Resolution   Codec                     Bitrate
  ---  ----------- ------------------------ ----------
  [0]  1280x720     avc1.640028               556kbps
  [1]  852x480      avc1.64001F               267kbps
  [2]  640x360      avc1.64001E               181kbps
  [3]  426x240      avc1.64001E               102kbps
  ...

  Audio streams:
  IDX  Codec                     Bitrate
  ---  ------------------------ ----------
  [0]  mp4a.40.5                 61kbps
  [1]  mp4a.40.5                 61kbps
  [2]  mp4a.40.5                 38kbps

  Video [0-9] (default 0): 3
  Audio [0-2] (default 0): 0

  Selected video: 426x240 avc1.64001E
  Selected audio: mp4a.40.5
  Launching VLC...
  Playing. Press Ctrl+C to stop.
```

## Architecture

```
dashparse/
  __init__.py          # Public API: parse_and_fetch, parse_and_fetch_sync
  exceptions.py        # Custom exceptions
  models/
    mpd.py             # MPD, Period, AdaptationSet, Representation, ByteRange, BaseURL
    segment.py         # SegmentRequest, Segment, SegmentSequence
  parser/
    mpd_parser.py      # XML parsing, ISO8601 duration, detect_addressing()
    segment_resolver.py # resolve_segment_base(), resolve_segment_template(), expand_sidx()
    templates.py       # expand_template() for $Number$, $Time$, etc.
  mp4/
    boxes.py           # BoxHeader, read_box_header() with extended size
    sidx.py            # SidxBox, SidxReference, parse_sidx(), encode()
  fetch/
    http_fetcher.py    # HTTPFetcher (async aiohttp, semaphore concurrency)
    sync_wrapper.py    # SyncHTTPFetcher, run_async()
    pool.py            # fetch_segment_sequence()
  demux/
    mp4_demuxer.py     # MP4Demuxer (moof -> traf -> trun -> frames)
    frame.py           # Frame dataclass
  remux/
    mp4_remuxer.py     # MP4Remuxer (fMP4 concat, ffmpeg mux)
  apps/
    bilibili_stream.py # Bilibili.tv stream extractor + VLC player
    stream_vlc.py      # Generic DASH stream player
```

## Requirements

- Python 3.10+
- aiohttp (for async HTTP)

## License

MIT
