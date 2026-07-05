# BiliRelay

**Watch bilibili.tv videos in any browser or VLC — without the official app.**

BiliRelay is a single-file HTTP proxy that converts bilibili.tv's fragmented MP4 DASH streams into a playable format. It fixes a broken `sidx` box (bilibili sets `ref_count=0`, which causes Dash.js, VLC, and other DASH players to stall on a blank screen) and serves the stream progressively through a custom MSE player or standard DASH manifest.

## Use Cases

| Use Case | How |
|---|---|
| **Watch in browser** | Open `http://localhost:8080/player` — custom MSE player streams progressively, no dash.js needed |
| **Watch in VLC** | `vlc http://localhost:8080/manifest.mpd` — VLC's built-in DASH parser handles the rest |
| **Embed in another player** | Point any DASH-compatible player to `http://localhost:8080/manifest.mpd` |
| **Bypass region/device restrictions** | Proxy fetches from bilibili CDN; you watch on any device on your LAN |
| **No app install** | No bilibili mobile app, no Electron wrapper, no browser extension needed |

## Quick Start

```
git clone https://github.com/omgbox/bilirelay.git
cd bilirelay
python bilibili_proxy.py https://www.bilibili.tv/en/video/2047206875
```

Then open **http://localhost:8080/player** in your browser.

To use VLC instead:

```
vlc http://localhost:8080/manifest.mpd
```

## Requirements

| Dependency | Required | Notes |
|---|---|---|
| **Python 3.11+** | Yes | Stdlib only — no `pip install` needed |
| **VLC 3.x** | No | Only needed for VLC playback mode |
| **Modern browser** | No | Chrome, Firefox, Edge — for browser player |

Works on Windows, macOS, and Linux.

## How It Works

```
                      ┌─────────────────────────────────────────────┐
                      │         BiliRelay (port 8080)               │
                      │                                             │
 Browser/VLC  ──►  ├── /manifest.mpd   (DASH on-demand manifest) │────►  bilibili CDN
                      │   /player          (custom MSE player HTML) │
                      │   /video           (proxies video .m4s)     │
                      │   /audio           (proxies audio .m4s)     │
                      └─────────────────────────────────────────────┘
```

1. BiliRelay fetches the bilibili page and extracts stream URLs from `window.__initialState`
2. It generates a DASH MPD pointing at itself as the media server
3. When a player requests the `indexRange` bytes (the `sidx` box), BiliRelay returns a **synthetic sidx** with `ref_count=1` — this fixes the blank-screen bug
4. All other byte-range requests are proxied transparently to the CDN
5. Content-Length is always set (required by DASH on-demand profile)

### The sidx Problem

Bilibili's `.m4s` files contain a `sidx` box with `ref_count=0`, which tells DASH players "there are zero subsegments." The player downloads all the data but never feeds any media to the decoder — resulting in a blank/black video that appears to hang.

BiliRelay intercepts the request for the sidx bytes and replaces them with a correct sidx. No modification of the original `.m4s` files is needed.

## Two Player Modes

### Browser Player (`/player`)

A self-contained HTML page that uses the MediaSource API directly (no dash.js). It:

- Fetches 2MB chunks via HTTP Range requests
- Parses `moof`+`mdat` boxes in JavaScript
- Feeds each segment progressively to a SourceBuffer
- Playback starts as soon as the first segment arrives; the rest downloads in the background

No dependencies, no CDN scripts, works offline.

### DASH Player (`/manifest.mpd`)

Standard DASH on-demand manifest compatible with:

- **VLC** — `vlc http://localhost:8080/manifest.mpd`
- **Dash.js** — point any dash.js-based player to the MPD URL
- **Shaka Player** — same URL

## Command-Line Options

```
python bilibili_proxy.py <url> [options]

Options:
  --port PORT   Port to listen on (default: 8080)
  --host HOST   Bind address (default: 127.0.0.1)
```

## Endpoints

| Path | Description |
|---|---|
| `/player` | Custom MSE player (recommended for browsers) |
| `/manifest.mpd` | DASH manifest for VLC/dash.js |
| `/debug` | Debug page with dash.js (logging enabled) |
| `/video` | Proxies video `.m4s` with synthetic sidx |
| `/audio` | Proxies audio `.m4s` with synthetic sidx |
| `/status` | JSON status (codec, resolution, bandwidth) |
| `/ping` | Health check (returns "OK") |

## Project Structure

```
bilirelay/
├── bilibili_proxy.py      # The proxy (single file, ~750 lines)
├── serve.py               # Startup script with self-test
├── README.md              # This file
```

`bilibili_proxy.py` is entirely self-contained — Python stdlib only, no external dependencies.

## Related Projects

- **[dashparse](https://github.com/omgbox/dashparse)** — A Python library for parsing DASH MPD manifests, demuxing/remuxing fMP4 segments, and streaming bilibili videos directly to VLC (no proxy). Provides lower-level DASH building blocks (`SidxBox`, `SegmentResolver`, `MP4Demuxer`) that complement BiliRelay's proxy approach.

## Technical Details

- Synthetic `sidx` box: version 0, `reference_count=1`, covers entire remaining file as one subsegment
- Original sidx padded with zeros to preserve byte offsets
- `find_streams()` regex uses `([$\w]+)` for JS variable names with `$` (fixes `\w+` bug)
- Content-Length fallback from HEAD response when CDN omits it
- `Access-Control-Allow-Origin: *` for cross-origin requests
- CDN URLs have ~1-hour HMAC expiry; proxy refreshes page every 45 minutes

## License

MIT
