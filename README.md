# bilibili_stream

Stream bilibili.tv videos in VLC — no app, no browser extension.

## Quick Start

### Standalone exe (Windows)

```
bilibili_stream.exe "https://www.bilibili.tv/en/video/4800104493751296"
```

### Run from source

```
python bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296"
```

## Command-Line Options

```
python bilibili_stream.py <url> [options]

Options:
  --quality N    Video quality index (0=highest)
  --audio N      Audio quality index (0=best)
  --list         List available streams and exit
  --open         Open in VLC after generating MPD
  --output PATH  Custom output MPD path
```

## Examples

```bash
# Generate MPD only
python bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296"

# Generate and open in VLC
python bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" --open

# List available qualities
python bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" --list

# Pick specific quality
python bilibili_stream.py "https://www.bilibili.tv/en/video/4800104493751296" --quality 2 --open
```

## How It Works

1. Fetches the bilibili page
2. Extracts DASH stream URLs from `window.__initialState`
3. Parses video/audio init segments to get correct duration
4. Generates a DASH MPD manifest file
5. Opens VLC with the MPD

CDN URLs expire after ~1 hour. Re-run for fresh links.

## Requirements

- **Python 3.11+** (source only) — stdlib only, no `pip install` needed
- **VLC 3.x** — [videolan.org](https://www.videolan.org/)

Works on Windows, macOS, and Linux.

## License

MIT
