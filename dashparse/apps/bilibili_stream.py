"""Bilibili DASH stream parser - extracts streams from bilibili.tv and plays via VLC."""
import sys
import os
import re
import json
import argparse
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen, Request

sys.path.insert(0, str(Path(__file__).parent.parent))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.bilibili.tv/",
}


def fetch_page(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_video_id(url: str) -> str:
    m = re.search(r"/video/(\d+)", url)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot extract video ID from: {url}")


def decode_js_str(s: str) -> str:
    return (
        s.replace("\\u002F", "/")
        .replace("\\u003E", ">")
        .replace("\\u003C", "<")
        .replace("\\u0026", "&")
    )


def resolve_vars(val, var_map: dict):
    if isinstance(val, (int, float, bool)) or val is None:
        return val
    val = str(val).strip()
    if val.startswith('"') and val.endswith('"'):
        return decode_js_str(val[1:-1])
    if val in var_map:
        return var_map[val]
    return val


def parse_args_str(args_str: str) -> list:
    args = []
    i = 0
    s = args_str
    while i < len(s):
        while i < len(s) and s[i] in " \t\n,":
            i += 1
        if i >= len(s):
            break
        if s[i] == '"':
            i += 1
            val = ""
            while i < len(s):
                if s[i] == "\\" and i + 1 < len(s):
                    val += s[i : i + 2]
                    i += 2
                elif s[i] == '"':
                    i += 1
                    break
                else:
                    val += s[i]
                    i += 1
            args.append(decode_js_str(val))
        elif s[i : i + 4] == "true":
            args.append(True)
            i += 4
        elif s[i : i + 5] == "false":
            args.append(False)
            i += 5
        elif s[i : i + 4] == "null":
            args.append(None)
            i += 4
        elif s[i : i + 5] == "Array":
            while i < len(s) and s[i] != ")":
                i += 1
            if i < len(s):
                i += 1
            args.append([])
        elif s[i] == "{":
            depth = 1
            i += 1
            while i < len(s) and depth > 0:
                if s[i] == "{":
                    depth += 1
                elif s[i] == "}":
                    depth -= 1
                i += 1
            args.append({})
        elif s[i] == "[":
            depth = 1
            i += 1
            while i < len(s) and depth > 0:
                if s[i] == "[":
                    depth += 1
                elif s[i] == "]":
                    depth -= 1
                i += 1
            args.append([])
        elif s[i] == "-" or s[i].isdigit():
            num = ""
            while i < len(s) and (s[i].isdigit() or s[i] in ".-"):
                num += s[i]
                i += 1
            try:
                args.append(int(num))
            except ValueError:
                args.append(float(num))
        else:
            val = ""
            while i < len(s) and s[i] not in ",)":
                val += s[i]
                i += 1
            args.append(val.strip())
    return args


def parse_stream_entry(entry: str, var_map: dict) -> dict:
    stream = {}
    sb = re.search(r"SegmentBase:\{Initialization:([\w$]+),indexRange:([\w$]+)\}", entry)
    if sb:
        stream["initialization"] = resolve_vars(sb.group(1), var_map)
        stream["index_range"] = resolve_vars(sb.group(2), var_map)

    kv_pairs = re.findall(r'(\w+):("(?:[^"\\]|\\.)*"|\w+|[\d.]+)', entry)
    for key, val in kv_pairs:
        if key == "SegmentBase":
            continue
        resolved = resolve_vars(val, var_map)
        if key in ("bandwidth", "width", "height"):
            try:
                stream[key] = int(resolved)
            except (ValueError, TypeError):
                pass
        elif key in ("base_url", "codecs", "frame_rate"):
            stream[key] = resolved
    return stream


def find_streams(body: str, var_map: dict, stream_type: str) -> list:
    pattern = stream_type + r":\["
    m = re.search(pattern, body)
    if not m:
        return []
    start = m.end()
    depth = 1
    i = start
    while i < len(body) and depth > 0:
        if body[i] == "[":
            depth += 1
        elif body[i] == "]":
            depth -= 1
        i += 1
    array_content = body[start : i - 1]

    entries = []
    depth = 0
    current = ""
    for ch in array_content:
        if ch == "{":
            depth += 1
            current += ch
        elif ch == "}":
            depth -= 1
            current += ch
            if depth == 0:
                entries.append(current)
                current = ""
        elif ch == "," and depth == 0:
            current = ""
        else:
            current += ch

    streams = []
    for entry in entries:
        stream = parse_stream_entry(entry, var_map)
        if "base_url" in stream:
            streams.append(stream)
    return streams


def extract_streams(html: str) -> tuple[list, list]:
    state_start = html.find("window.__initialState=")
    if state_start == -1:
        raise ValueError("Cannot find __initialState in page")

    script_end = html.find("</script>", state_start)
    state_js = html[state_start:script_end]

    param_match = re.search(r"function\s*\(([^)]+)\)", state_js)
    if not param_match:
        raise ValueError("Cannot parse function parameters")
    params = [p.strip() for p in param_match.group(1).split(",")]

    func_start = state_js.find("{")
    depth = 0
    func_end = -1
    for i in range(func_start, len(state_js)):
        if state_js[i] == "{":
            depth += 1
        elif state_js[i] == "}":
            depth -= 1
            if depth == 0:
                func_end = i
                break

    args_raw = state_js[func_end + 1 :].strip()
    if args_raw.startswith(")"):
        args_raw = args_raw[1:]
    args_raw = args_raw.strip()
    if args_raw.startswith("("):
        args_raw = args_raw[1:]
    while args_raw.endswith(")"):
        args_raw = args_raw[:-1]

    args = parse_args_str(args_raw)
    var_map = {}
    for i, param in enumerate(params):
        if i < len(args):
            var_map[param] = args[i]

    body = state_js[func_start : func_end + 1]
    video_streams = find_streams(body, var_map, "video")
    audio_streams = find_streams(body, var_map, "audio")
    subtitles = extract_subtitles(body)
    return video_streams, audio_streams, subtitles


def extract_subtitles(body: str) -> list[dict]:
    subs = []
    for m in re.finditer(r'title:"([^"]+)",url:"([^"]+)"', body):
        title = m.group(1)
        url = m.group(2).replace("\\u002F", "/").replace("\\u0026", "&")
        subs.append({"title": title, "url": url})
    return subs


def fetch_subtitle_srt(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bilibili.tv/",
    })
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    cues = data.get("body", [])
    lines = []
    for i, cue in enumerate(cues, 1):
        start = format_srt_time(cue["from"])
        end = format_srt_time(cue["to"])
        content = cue["content"].replace("\u200e", "").replace("\u200f", "")
        lines.append(f"{i}\n{start} --> {end}\n{content}\n")
    return "\n".join(lines)


def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_mpd(video: dict, audio: dict) -> str:
    from xml.sax.saxutils import escape
    vid_url = escape(video.get("base_url", ""))
    aud_url = escape(audio.get("base_url", ""))
    vid_codecs = video.get("codecs", "avc1.640028")
    aud_codecs = audio.get("codecs", "mp4a.40.2")
    vid_bw = video.get("bandwidth", 0)
    aud_bw = audio.get("bandwidth", 0)
    vid_w = video.get("width", 0)
    vid_h = video.get("height", 0)
    vid_init = video.get("initialization", "0-933")
    vid_idx = video.get("index_range", "934-9593")
    aud_init = audio.get("initialization", "0-943")
    aud_idx = audio.get("index_range", "944-9603")

    # Extract a common base from the URLs for the Period BaseURL
    # Use a dummy base since each representation has its own full URL
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     type="static"
     mediaPresentationDuration="PT59M54S"
     minBufferTime="PT1.5S"
     profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4" segmentAlignment="true" startWithSAP="1">
      <BaseURL>{vid_url}</BaseURL>
      <SegmentBase indexRange="{vid_idx}">
        <Initialization range="{vid_init}"/>
      </SegmentBase>
      <Representation id="vid" bandwidth="{vid_bw}" codecs="{vid_codecs}" width="{vid_w}" height="{vid_h}" frameRate="24000/1001"/>
    </AdaptationSet>
    <AdaptationSet mimeType="audio/mp4" segmentAlignment="true" startWithSAP="1">
      <BaseURL>{aud_url}</BaseURL>
      <SegmentBase indexRange="{aud_idx}">
        <Initialization range="{aud_init}"/>
      </SegmentBase>
      <Representation id="aud" bandwidth="{aud_bw}" codecs="{aud_codecs}" audioSamplingRate="44100"/>
    </AdaptationSet>
  </Period>
</MPD>"""


def find_vlc() -> str | None:
    candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        "/usr/bin/vlc",
        "/usr/local/bin/vlc",
        "/opt/homebrew/bin/vlc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def list_streams(video_streams, audio_streams):
    print(f"\n  Video streams:")
    print(f"  {'IDX':>3}  {'Resolution':<12} {'Codec':<24} {'Bitrate':<10}")
    print(f"  {'---':>3}  {'-'*12} {'-'*24} {'-'*10}")
    for i, v in enumerate(video_streams):
        res = f"{v.get('width', '?')}x{v.get('height', '?')}"
        codec = v.get("codecs", "?")
        bw = f"{v.get('bandwidth', 0) / 1000:.0f}kbps"
        print(f"  [{i}]  {res:<12} {codec:<24} {bw:<10}")

    print(f"\n  Audio streams:")
    print(f"  {'IDX':>3}  {'Codec':<24} {'Bitrate':<10}")
    print(f"  {'---':>3}  {'-'*24} {'-'*10}")
    for i, a in enumerate(audio_streams):
        codec = a.get("codecs", "?")
        bw = f"{a.get('bandwidth', 0) / 1000:.0f}kbps"
        print(f"  [{i}]  {codec:<24} {bw:<10}")


def select_interactive(video_streams, audio_streams):
    list_streams(video_streams, audio_streams)

    try:
        v = input(f"\n  Video [0-{len(video_streams)-1}] (default 0): ").strip()
        vid_idx = int(v) if v else 0
    except (ValueError, EOFError):
        vid_idx = 0

    try:
        a = input(f"  Audio [0-{len(audio_streams)-1}] (default 0): ").strip()
        aud_idx = int(a) if a else 0
    except (ValueError, EOFError):
        aud_idx = 0

    vid_idx = max(0, min(vid_idx, len(video_streams) - 1))
    aud_idx = max(0, min(aud_idx, len(audio_streams) - 1))
    return vid_idx, aud_idx


def main():
    parser = argparse.ArgumentParser(description="Stream bilibili.tv videos via VLC")
    parser.add_argument("url", help="bilibili.tv video URL")
    parser.add_argument("--quality", "-q", type=int, default=None, help="Video quality index")
    parser.add_argument("--audio", "-a", type=int, default=None, help="Audio quality index")
    parser.add_argument("--subtitle", "-s", type=int, default=0, help="Subtitle index (0=first, -1=none)")
    parser.add_argument("--list", "-l", action="store_true", help="List streams and select interactively")
    parser.add_argument("--vlc", help="Path to VLC")
    parser.add_argument("--mpd-only", action="store_true", help="Only output MPD, don't play")
    args = parser.parse_args()

    vlc_path = args.vlc or find_vlc()
    if not vlc_path and not args.mpd_only:
        print("Error: VLC not found. Install VLC or pass --vlc")
        sys.exit(1)

    print(f"Fetching: {args.url}")
    html = fetch_page(args.url)
    video_id = extract_video_id(args.url)
    print(f"Video ID: {video_id}")

    video_streams, audio_streams, subtitles = extract_streams(html)
    if not video_streams:
        print("Error: No video streams found")
        sys.exit(1)
    if not audio_streams:
        print("Error: No audio streams found")
        sys.exit(1)

    if subtitles:
        print(f"\n  Subtitles available:")
        for i, s in enumerate(subtitles):
            print(f"    [{i}] {s['title']}")

    if args.list or args.quality is None:
        vid_idx, aud_idx = select_interactive(video_streams, audio_streams)
    else:
        vid_idx = min(args.quality, len(video_streams) - 1)
        aud_idx = min(args.audio or 0, len(audio_streams) - 1)

    vid = video_streams[vid_idx]
    aud = audio_streams[aud_idx]

    print(f"\n  Selected video: {vid.get('width')}x{vid.get('height')} {vid.get('codecs')}")
    print(f"  Selected audio: {aud.get('codecs')}")

    mpd_xml = build_mpd(vid, aud)

    tmp_dir = tempfile.mkdtemp(prefix="bilibili_")
    mpd_path = os.path.join(tmp_dir, f"{video_id}.mpd")
    with open(mpd_path, "w", encoding="utf-8") as f:
        f.write(mpd_xml)
    print(f"  MPD: {mpd_path}")

    # Download subtitles
    srt_files = []
    if args.subtitle >= 0 and subtitles:
        sub_idx = min(args.subtitle, len(subtitles) - 1)
        sub = subtitles[sub_idx]
        try:
            srt_content = fetch_subtitle_srt(sub["url"])
            srt_path = os.path.join(tmp_dir, f"{video_id}_{sub['title']}.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            srt_files.append(srt_path)
            print(f"  Subtitle: {sub['title']} ({len(srt_content)} bytes)")
        except Exception as e:
            print(f"  Subtitle {sub['title']}: {e}")

    if args.mpd_only:
        print(mpd_xml)
        return

    print(f"\n  Launching VLC...")
    vlc_cmd = [
        vlc_path,
        mpd_path,
        "--http-referrer=https://www.bilibili.tv/",
        "--network-caching=3000",
    ]
    if srt_files:
        vlc_cmd.append(f"--sub-file={srt_files[0]}")
    subprocess.Popen(vlc_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  Playing. Press Ctrl+C to stop.")


if __name__ == "__main__":
    main()
