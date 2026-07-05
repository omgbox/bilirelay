"""DashStream - Stream DASH videos via VLC using dashparse."""
import sys
import os
import re
import asyncio
import argparse
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dashparse import parse_mpd
from dashparse.parser.mpd_parser import detect_addressing


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


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


def fetch_mpd(url: str) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def generate_local_mpd(mpd, rep, base_url: str, output_path: str) -> None:
    """Generate a local MPD pointing to the original URLs."""
    period = mpd.periods[0]
    adapt = None
    for a in period.adaptation_sets:
        if rep in a.representations:
            adapt = a
            break

    if rep.segment_template:
        tmpl = rep.segment_template
        mode = "template"
    elif rep.segment_base:
        mode = "base"
    else:
        raise ValueError("No segment template or base found")

    # Find audio rep
    audio_rep = None
    for a in period.adaptation_sets:
        if a.mime_type and "audio" in a.mime_type:
            if a.representations:
                audio_rep = a.representations[0]
                break

    # Build a simple MPD XML
    dur_sec = mpd.media_presentation_duration.total_seconds() if mpd.media_presentation_duration else 600

    mpd_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     type="static"
     mediaPresentationDuration="PT{int(dur_sec)}S"
     minBufferTime="PT2S"
     profiles="urn:mpeg:dash:profile:isoff-live:2011">
  <BaseURL>{base_url}</BaseURL>
  <Period>"""

    for a in period.adaptation_sets:
        if not a.representations:
            continue
        # Pick the selected rep if it belongs to this adaptation, otherwise first rep
        if rep in a.representations:
            r = rep
        elif audio_rep and audio_rep in a.representations:
            r = audio_rep
        else:
            r = a.representations[0]
        if r is None:
            continue

        mime = a.mime_type or "video/mp4"
        seg_attrs = ""
        seg_child = ""

        if r.segment_template:
            t = r.segment_template
            # Make URLs absolute
            init_url = t.initialization
            media_url = t.media
            if not init_url.startswith("http"):
                init_url = base_url + init_url
            if not media_url.startswith("http"):
                media_url = base_url + media_url
            seg_attrs = f' duration="{t.duration}" timescale="{t.timescale}" startNumber="{t.start_number}"'
            seg_attrs += f' media="{media_url}" initialization="{init_url}"'
            seg_child = f"\n      <SegmentTemplate{seg_attrs}/>"
        elif r.segment_base:
            sb = r.segment_base
            idx = f' indexRange="{sb.index_range}"' if sb.index_range else ""
            init_range = f' range="{sb.initialization.range}"' if sb.initialization and sb.initialization.range else ""
            init_url = f' sourceURL="{sb.initialization.source_url}"' if sb.initialization and sb.initialization.source_url else ""
            seg_child = f"\n      <SegmentBase{idx}>\n        <Initialization{init_url}{init_range}/>\n      </SegmentBase>"

        w = f' width="{r.width}"' if r.width else ""
        h = f' height="{r.height}"' if r.height else ""
        bw = f' bandwidth="{r.bandwidth}"' if r.bandwidth else ""
        codecs = f' codecs="{r.codecs}"' if r.codecs else ""
        fps = f' frameRate="{r.frame_rate}"' if r.frame_rate else ""

        mpd_xml += f"""
    <AdaptationSet mimeType="{mime}" segmentAlignment="true">{seg_child}
      <Representation id="{r.id}"{codecs}{bw}{w}{h}{fps}/>
    </AdaptationSet>"""

    mpd_xml += """
  </Period>
</MPD>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(mpd_xml)


async def stream_mpd(url: str, vlc_path: str, quality: int = 0):
    """Fetch MPD, generate local file, open in VLC."""
    # Detect bilibili URLs
    if "bilibili.tv" in url:
        import importlib.util
        spec = importlib.util.spec_from_file_location("bilibili_stream", Path(__file__).parent / "bilibili_stream.py")
        bili = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bili)
        print(f"Fetching bilibili page: {url}")
        html = bili.fetch_page(url)
        video_streams, audio_streams = bili.extract_streams(html)
        if not video_streams:
            raise ValueError("No video streams found")
        if not audio_streams:
            raise ValueError("No audio streams found")

        print(f"\nAvailable video qualities:")
        for i, v in enumerate(video_streams):
            res = f"{v.get('width', '?')}x{v.get('height', '?')}"
            bw = f"{v.get('bandwidth', 0) / 1000:.0f}kbps"
            marker = " <--" if i == quality else ""
            print(f"  [{i}] {res} {v.get('codecs', '?')} {bw}{marker}")

        vid = video_streams[min(quality, len(video_streams) - 1)]
        aud = audio_streams[0]
        mpd_xml = bili.build_mpd(vid, aud)

        tmp_dir = tempfile.mkdtemp(prefix="bilibili_")
        video_id = re.search(r"/video/(\d+)", url).group(1)
        mpd_path = os.path.join(tmp_dir, f"{video_id}.mpd")
        with open(mpd_path, "w", encoding="utf-8") as f:
            f.write(mpd_xml)
        print(f"\nMPD: {mpd_path}")

        vlc_cmd = [vlc_path, mpd_path, "--http-referrer=https://www.bilibili.tv/", "--network-caching=3000"]
        print(f"\nLaunching VLC...")
        subprocess.Popen(vlc_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Playing. Press Ctrl+C to stop.")
        return

    # Regular MPD URL
    print(f"Fetching MPD: {url}")
    mpd_xml = fetch_mpd(url)
    mpd = parse_mpd(mpd_xml)
    print(f"  Periods: {len(mpd.periods)}, Duration: {mpd.media_presentation_duration}")

    # List available qualities
    period = mpd.periods[0]
    video_reps = []
    audio_rep = None
    for adapt in period.adaptation_sets:
        if adapt.mime_type and "video" in adapt.mime_type:
            video_reps.extend(adapt.representations)
        elif adapt.mime_type and "audio" in adapt.mime_type:
            if adapt.representations:
                audio_rep = adapt.representations[0]

    video_reps.sort(key=lambda r: r.bandwidth or 0)
    print(f"\nAvailable video qualities:")
    for i, r in enumerate(video_reps):
        res = f"{r.width}x{r.height}" if r.width else "?"
        bw = f"{(r.bandwidth or 0) / 1000:.0f}kbps"
        marker = " <--" if i == quality else ""
        print(f"  [{i}] {res} {r.codecs} {bw}{marker}")

    selected = video_reps[min(quality, len(video_reps) - 1)]
    # Build absolute base URL from the original MPD URL
    mpd_dir = url.rsplit("/", 1)[0] + "/"
    if mpd.base_url and mpd.base_url.url:
        base = mpd.base_url.url
        if base.startswith("http"):
            base_url = base
        elif base.startswith("./"):
            base_url = mpd_dir + base[2:]
        else:
            base_url = mpd_dir + base
    else:
        base_url = mpd_dir
    if not base_url.endswith("/"):
        base_url += "/"

    print(f"\nSelected: {selected.id} {selected.width}x{selected.height}")
    print(f"Base URL: {base_url}")

    # Generate local MPD
    tmp_dir = tempfile.mkdtemp(prefix="dashstream_")
    mpd_path = os.path.join(tmp_dir, "stream.mpd")
    generate_local_mpd(mpd, selected, base_url, mpd_path)
    print(f"Local MPD: {mpd_path}")

    # Launch VLC
    vlc_cmd = [
        vlc_path,
        mpd_path,
        "--http-referrer=https://www.bilibili.tv/",
        "--network-caching=3000",
        "--verbose=0",
    ]
    print(f"\nLaunching VLC...")
    print(f"  {' '.join(vlc_cmd[:3])}...")
    subprocess.Popen(vlc_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("VLC launched. Press Ctrl+C to stop.")


def main():
    parser = argparse.ArgumentParser(description="Stream DASH videos via VLC")
    parser.add_argument("url", help="DASH MPD URL")
    parser.add_argument("--quality", "-q", type=int, default=0, help="Quality index (0=highest)")
    parser.add_argument("--vlc", help="Path to VLC executable")
    args = parser.parse_args()

    vlc_path = args.vlc or find_vlc()
    if not vlc_path:
        print("Error: VLC not found. Install VLC or pass --vlc path")
        sys.exit(1)

    try:
        asyncio.run(stream_mpd(args.url, vlc_path, args.quality))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
