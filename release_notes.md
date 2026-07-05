**BiliRelay** - Watch bilibili.tv videos in VLC without the official app.

Standalone exe (7.1 MB) - No Python or VLC install required.

---

## Download

| File | Size | Description |
|------|------|-------------|
| bilibili_stream.exe | 7.1 MB | Standalone Windows exe, no install needed |

---

## Quick Start

```
# Basic - auto best video + English subs + VLC
bilibili_stream.exe "https://www.bilibili.tv/en/video/4800104493751296"

# Pick a lower quality
bilibili_stream.exe "https://www.bilibili.tv/en/video/4800104493751296" -q 2

# No subtitles
bilibili_stream.exe "https://www.bilibili.tv/en/video/4800104493751296" -s -1

# List all available streams
bilibili_stream.exe "https://www.bilibili.tv/en/video/4800104493751296" -l

# Save MPD file for another player
bilibili_stream.exe "https://www.bilibili.tv/en/video/4800104493751296" --mpd-only
```

---

## Requirements

| Requirement | Required | Notes |
|-------------|----------|-------|
| Windows | Yes | Standalone exe, no Python needed |
| VLC | Yes | Download from videolan.org |
| Python | No | Only needed if running from source |

### Running from source (no pip install needed)

```
git clone https://github.com/omgbox/bilirelay.git
cd bilirelay
python dashparse/apps/bilibili_stream.py "URL"
```

All imports are Python stdlib (urllib, json, re, argparse, etc). No external packages required.

---

## Examples

| Command | Description |
|---------|-------------|
| bilibili_stream.exe "URL" | Auto best video + English subs |
| bilibili_stream.exe "URL" -q 2 | Specific quality (0=lowest) |
| bilibili_stream.exe "URL" -s -1 | No subtitles |
| bilibili_stream.exe "URL" -l | List streams, pick manually |
| bilibili_stream.exe "URL" --mpd-only | Output MPD only |
| bilibili_stream.exe "URL" --vlc-path "path" | Custom VLC path |

---

## Options

| Flag | Description | Default |
|------|-------------|---------|
| -q, --quality N | Video quality index | Auto (highest) |
| -a, --audio N | Audio quality index | 0 (best) |
| -s, --subtitle LANG | Subtitle language code | en |
| -l, --list | List streams, select interactively | - |
| --mpd-only | Output MPD only, don't play | - |
| --vlc-path PATH | Path to VLC executable | Auto-detect |

---

Source code + dashparse library included in repo.
