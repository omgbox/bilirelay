"""Bilibili stream player using HTTP server for VLC DASH support."""
import sys
import os
import re
import importlib.util
import argparse
import subprocess
import tempfile
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.request import urlopen, Request

sys.path.insert(0, str(Path(__file__).parent.parent))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.tv/",
}

# Import bilibili parser
spec = importlib.util.spec_from_file_location("bili", Path(__file__).parent / "bilibili_stream.py")
bili = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bili)


def find_vlc():
    for p in [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]:
        if os.path.exists(p):
            return p
    return None


class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="bilibili.tv video URL")
    parser.add_argument("-q", "--quality", type=int, default=0)
    parser.add_argument("--vlc", help="VLC path")
    args = parser.parse_args()

    vlc = args.vlc or find_vlc()
    if not vlc:
        print("VLC not found")
        sys.exit(1)

    print(f"Fetching: {args.url}")
    html = bili.fetch_page(args.url)
    video_streams, audio_streams = bili.extract_streams(html)

    print(f"\nVideo streams:")
    for i, v in enumerate(video_streams):
        res = f"{v.get('width', '?')}x{v.get('height', '?')}"
        bw = f"{v.get('bandwidth', 0) / 1000:.0f}kbps"
        marker = " <--" if i == args.quality else ""
        print(f"  [{i}] {res} {v.get('codecs', '?')} {bw}{marker}")

    vid = video_streams[min(args.quality, len(video_streams) - 1)]
    aud = audio_streams[0]
    mpd_xml = bili.build_mpd(vid, aud)

    # Write MPD
    tmp_dir = tempfile.mkdtemp(prefix="bilibili_")
    video_id = re.search(r"/video/(\d+)", args.url).group(1)
    mpd_path = os.path.join(tmp_dir, f"{video_id}.mpd")
    with open(mpd_path, "w") as f:
        f.write(mpd_xml)

    # Start HTTP server
    os.chdir(tmp_dir)
    server = HTTPServer(("127.0.0.1", 0), SilentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    mpd_url = f"http://127.0.0.1:{port}/{video_id}.mpd"
    print(f"\nServing MPD at: {mpd_url}")

    # Launch VLC with the HTTP URL
    print("Launching VLC...")
    subprocess.Popen([
        vlc, mpd_url,
        "--http-referrer=https://www.bilibili.tv/",
        "--network-caching=3000",
    ])

    print("Playing. Press Ctrl+C to stop.")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
