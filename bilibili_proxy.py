#!/usr/bin/env python3
"""
BiliRelay — HTTP proxy that makes bilibili.tv DASH streams playable in browsers and VLC.

Fixes the broken sidx (ref_count=0) in bilibili .m4s files by injecting a synthetic
sidx on-the-fly. Streams progressively via a custom MSE player or standard DASH.

Usage:  python bilibili_proxy.py <bilibili.tv URL> [--port 8080]
"""
import sys, os, re, time, argparse, threading, struct
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.request import urlopen, Request
from urllib.error import HTTPError

R="\033[0m"; B="\033[1m"; D="\033[2m"; RED="\033[31m"; GRN="\033[32m"
YLW="\033[33m"; CYN="\033[36m"

def ts(): return time.strftime("%H:%M:%S")
def log(m): print(f"  {D}[{ts()}]{R} {m}", flush=True)
def ok(m):  print(f"  {D}[{ts()}]{R} {GRN}[OK]{R} {m}", flush=True)
def err(m): print(f"  {D}[{ts()}]{R} {RED}[XX]{R} {m}", flush=True)

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://www.bilibili.tv/",
    "Origin": "https://www.bilibili.tv",
}

def dec(s): return s.replace('\\u002F','/').replace('\\u003E','>').replace('\\u003C','<')

def parse_args_js(s):
    args=[]; i=0
    while i<len(s):
        while i<len(s) and s[i] in ' \t\n,': i+=1
        if i>=len(s): break
        if s[i]=='"':
            i+=1; v=''
            while i<len(s):
                if s[i]=='\\' and i+1<len(s): v+=s[i:i+2]; i+=2
                elif s[i]=='"': i+=1; break
                else: v+=s[i]; i+=1
            args.append(dec(v))
        elif s[i:i+4]=='true': args.append(True); i+=4
        elif s[i:i+5]=='false': args.append(False); i+=5
        elif s[i:i+4]=='null': args.append(None); i+=4
        elif s[i:i+5]=='Array':
            while i<len(s) and s[i]!=')': i+=1
            if i<len(s): i+=1; args.append([])
        elif s[i] in '{[':
            ch=s[i]; d=1; i+=1
            while i<len(s) and d>0:
                if s[i]==ch: d+=1
                elif s[i]==('}' if ch=='{' else ']'): d-=1
                i+=1
            args.append({})
        elif s[i]=='-' or s[i].isdigit():
            n=''
            while i<len(s) and (s[i].isdigit() or s[i] in '.-'): n+=s[i]; i+=1
            try: args.append(int(n))
            except: args.append(float(n))
        else:
            v=''
            while i<len(s) and s[i] not in ',)': v+=s[i]; i+=1
            args.append(v.strip())
    return args

def find_streams(body, vm, st):
    out=[]; m=re.search(st+r':\[', body)
    if not m: return out
    start=m.end(); d=1; i=start
    while i<len(body) and d>0:
        if body[i]=='[': d+=1
        elif body[i]==']': d-=1
        i+=1
    arr=body[start:i-1]; entries=[]; d=0; cur=''
    for ch in arr:
        if ch=='{': d+=1; cur+=ch
        elif ch=='}':
            d-=1; cur+=ch
            if d==0: entries.append(cur); cur=''
        elif d==0 and ch==',': cur=''
        elif d>0: cur+=ch
    for e in entries:
        s={}
        sb=re.search(r'SegmentBase:\{Initialization:([$\w]+),indexRange:([$\w]+)\}', e)
        if sb:
            init_str = vm.get(sb.group(1), sb.group(1))
            idx_str = vm.get(sb.group(2), sb.group(2))
            s['initialization'] = init_str
            s['index_range'] = idx_str
            # Parse numeric ranges
            m_init = re.match(r'(\d+)-(\d+)', str(init_str))
            m_idx = re.match(r'(\d+)-(\d+)', str(idx_str))
            if m_init:
                s['init_start'] = int(m_init.group(1))
                s['init_end'] = int(m_init.group(2))
            if m_idx:
                s['idx_start'] = int(m_idx.group(1))
                s['idx_end'] = int(m_idx.group(2))
        for k,v in re.findall(r'(\w+):("(?:[^"\\]|\\.)*"|\w+|[\d.]+)', e):
            if k=='SegmentBase': continue
            v=v.strip()
            if v.startswith('"') and v.endswith('"'): v=dec(v[1:-1])
            elif v in vm: v=vm[v]
            if k=='bandwidth':
                try: s['bandwidth']=int(v)
                except: pass
            elif k=='width':
                try: s['width']=int(v)
                except: pass
            elif k=='height':
                try: s['height']=int(v)
                except: pass
            elif k in ('base_url','backup_url','codecs'): s[k]=v
        if 'base_url' in s: out.append(s)
    return out

def parse_mvhd(data):
    """Parse mvhd box to extract timescale and duration."""
    pos = 0
    while pos < len(data) - 8:
        box_size = struct.unpack_from('>I', data, pos)[0]
        box_type = data[pos+4:pos+8].decode('ascii', errors='replace')
        if box_type == 'mvhd':
            version = data[pos+8]
            if version == 0:
                timescale = struct.unpack_from('>I', data, pos+20)[0]
                duration = struct.unpack_from('>I', data, pos+24)[0]
            else:
                timescale = struct.unpack_from('>I', data, pos+28)[0]
                duration = struct.unpack_from('>Q', data, pos+32)[0]
            return timescale, duration
        if box_size == 0: break
        pos += box_size
    return 16000, 3594000  # fallback

def parse_moov(data):
    """Parse moov box to find mvhd and extract timescale/duration."""
    pos = 0
    while pos < len(data) - 8:
        box_size = struct.unpack_from('>I', data, pos)[0]
        box_type = data[pos+4:pos+8].decode('ascii', errors='replace')
        if box_size == 0: break
        if box_type == 'moov':
            return parse_mvhd(data[pos:pos+box_size])
        if box_type not in ('ftyp', 'moov', 'free', 'skip'): break
        pos += box_size
    # Try scanning the whole data
    ts, dur = parse_mvhd(data)
    return ts, dur

def gen_sidx(timescale, duration, first_offset, ref_size):
    """Generate a synthetic sidx box with ref_count=1.
    
    sidx box structure (version 0):
      - size(4) + type(4) + version(1) + flags(3) + ref_id(4) + timescale(4)
      - ept(4) + first_offset(4) + ref_count(2) + references(12 each)
    """
    ref_count = 1
    sidx_size = 30 + ref_count * 12
    buf = bytearray(sidx_size)
    struct.pack_into('>I', buf, 0, sidx_size)
    buf[4:8] = b'sidx'
    buf[8] = 0   # version
    buf[9:12] = b'\0\0\0'  # flags
    struct.pack_into('>I', buf, 12, 1)           # reference_ID = 1
    struct.pack_into('>I', buf, 16, timescale)
    struct.pack_into('>I', buf, 20, 0)            # earliest_presentation_time
    struct.pack_into('>I', buf, 24, first_offset)
    struct.pack_into('>H', buf, 28, ref_count)

    # Reference entry (12 bytes)
    # type(1bit=0) | referenced_size(31bits)
    ref_type_size = ref_size & 0x7FFFFFFF
    struct.pack_into('>I', buf, 30, ref_type_size)
    # subsegment_duration
    struct.pack_into('>I', buf, 34, duration)
    # starts_with_SAP(1bit=1) | SAP_type(3bits=1) | SAP_delta_time(28bits=0)
    struct.pack_into('>I', buf, 38, 0x10000000)  # SAP=1, type=1, delta=0
    return bytes(buf)

class Cache:
    def __init__(self, url):
        self.url=url; self._l=threading.Lock()
        self._vs=[]; self._as=[]; self._t=0; self._title=""
        self._v_sidx=None; self._a_sidx=None
        self._v_first_offset=0; self._a_first_offset=0
        self._v_size=None; self._a_size=None
    def _ref(self):
        log(f"Fetching {CYN}{self.url}{R}")
        req=Request(self.url, headers=HDR)
        html=urlopen(req,timeout=30).read().decode("utf-8",errors="replace")
        tm=re.search(r'<title>([^<]+)</title>',html)
        self._title=tm.group(1).strip() if tm else "bilibili"
        ss=html.find('window.__initialState=')
        if ss==-1: raise ValueError("No __initialState")
        se=html.find('</script>',ss); js=html[ss:se]
        pm=re.search(r'function\s*\(([^)]+)\)',js)
        if not pm: raise ValueError("No params")
        params=[p.strip() for p in pm.group(1).split(',')]
        fs=js.find('{'); d=0; fe=-1
        for i in range(fs,len(js)):
            if js[i]=='{': d+=1
            elif js[i]=='}':
                d-=1
                if d==0: fe=i; break
        ar=js[fe+1:].strip()
        if ar.startswith(')'): ar=ar[1:]
        ar=ar.strip()
        if ar.startswith('('): ar=ar[1:]
        while ar.endswith(')'): ar=ar[:-1]
        args=parse_args_js(ar); vm={}
        for i,p in enumerate(params):
            if i<len(args): vm[p]=args[i]
        body=js[fs:fe+1]
        self._vs=find_streams(body,vm,'video')
        self._as=find_streams(body,vm,'audio')
        self._t=time.time()
        if not self._vs or not self._as: raise ValueError("No streams")
        ok(f"Loaded {len(self._vs)} video + {len(self._as)} audio streams")

        # Generate synthetic sidx for best quality video & audio
        self._gen_sidx_for(0, 0)

    def _gen_sidx_for(self, vi, ai):
        """Generate synthetic sidx with 1 reference covering entire media.
        Fast startup — no scanning needed. The player (custom MSE or VLC)
        handles progressive streaming."""
        vs = self._vs[min(vi, len(self._vs)-1)]
        aud = self._as[min(ai, len(self._as)-1)]

        for kind, stream in [('video', vs), ('audio', aud)]:
            base_url = stream.get('base_url', '')
            if not base_url: continue

            # Get file size
            size_attr = f'_{kind[0]}_size'
            file_size = getattr(self, size_attr)
            if not file_size:
                file_size = self._get_size(base_url)
                if file_size:
                    setattr(self, size_attr, file_size)
            if not file_size:
                err(f"Cannot get size for {kind}")
                continue

            idx_start = stream.get('idx_start', 0)
            idx_end = stream.get('idx_end', 0)
            if not idx_end:
                err(f"No idx_end for {kind}")
                continue
            idx_range_size = idx_end - idx_start + 1
            media_offset = idx_end + 1

            # Fetch init bytes to parse mvhd
            req_h = dict(HDR)
            req_h["Range"] = f"bytes={stream.get('init_start',0)}-{stream.get('init_end',1005)}"
            try:
                req = Request(base_url, headers=req_h)
                resp = urlopen(req, timeout=10)
                init_data = resp.read()
                ts, dur = parse_moov(init_data)
                if kind == 'video':
                    ok(f"Video mvhd: timescale={ts}, duration={dur}, file={file_size:,}b")
                else:
                    ok(f"Audio mvhd: timescale={ts}, duration={dur}, file={file_size:,}b")
            except Exception as e:
                err(f"mvhd parse for {kind}: {e}")
                ts, dur = 16000, 3594000

            # 1 ref covering all media after sidx
            ref_size = file_size - media_offset
            sidx_size = 42
            first_offset = media_offset - (idx_start + sidx_size)
            if first_offset < 0: first_offset = 0

            sidx = gen_sidx(ts, dur, first_offset, ref_size)

            # Pad to original indexRange size
            orig_idx_size = (idx_end - idx_start + 1)
            if len(sidx) < orig_idx_size:
                sidx = sidx + b'\0' * (orig_idx_size - len(sidx))

            if kind == 'video':
                self._v_sidx = sidx
                self._v_first_offset = first_offset
                log(f"  {D}Video sidx: {len(sidx)}b, 1 ref (size={ref_size:,}, first_offset={first_offset}){R}")
            else:
                self._a_sidx = sidx
                self._a_first_offset = first_offset
                log(f"  {D}Audio sidx: {len(sidx)}b, 1 ref (size={ref_size:,}, first_offset={first_offset}){R}")

    def _get_size(self, url):
        if not url: return None
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            import http.client, ssl
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(parsed.hostname, 443, context=ctx, timeout=10)
            conn.request("HEAD", parsed.path + "?" + parsed.query, headers={
                "User-Agent": HDR["User-Agent"],
                "Referer": "https://www.bilibili.tv/",
            })
            resp = conn.getresponse()
            size = int(resp.getheader("Content-Length", 0))
            conn.close()
            return size
        except Exception as e:
            err(f"_get_size error: {e}")
            return None

    def get(self, vi=0, ai=0):
        with self._l:
            if time.time()-self._t>2700: self._ref()
            return (self._vs[min(vi,len(self._vs)-1)],
                    self._as[min(ai,len(self._as)-1)])

class H(BaseHTTPRequestHandler):
    cache: Cache = None
    def log_message(self, *a): pass

    def do_GET(self):
        p=self.path.split('?')[0]
        try:
            if   p=="/manifest.mpd": self._mpd()
            elif p=="/player":       self._player()
            elif p=="/debug":        self._debug()
            elif p=="/video":        self._stream("video")
            elif p=="/audio":        self._stream("audio")
            elif p=="/status":       self._status()
            elif p=="/streams":      self._streams()
            elif p=="/ping":         self._pong()
            else: self.send_error(404)
        except Exception as e:
            import traceback
            err(f"Handler exception: {e}")
            for line in traceback.format_exc().splitlines():
                err(line)
            try: self.send_error(500)
            except: pass

    def _pong(self):
        data=b"OK"
        self.send_response(200)
        self.send_header("Content-Length","2")
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        p=self.path.split('?')[0]
        if p in ("/video","/audio"): self._stream(p[1:])
        else: self.send_error(404)

    def _stream(self, kind):
        try: vid,aud = self.cache.get()
        except Exception as e: err(str(e)); self.send_error(502); return
        stream = vid if kind=="video" else aud
        url = stream.get("base_url","")
        if not url: self.send_error(502); return
        rng = self.headers.get("Range")
        req_h = dict(HDR)

        # Check if this is a request for the sidx bytes - inject synthetic sidx
        sidx_bytes = self.cache._v_sidx if kind == "video" else self.cache._a_sidx
        idx_start = stream.get('idx_start', 0)
        idx_end = stream.get('idx_end', 0)
        inject_sidx = False; sidx_data = None

        if rng and idx_start is not None and idx_end and sidx_bytes:
            rng_match = re.match(r'bytes=(\d+)-(\d*)', rng)
            if rng_match:
                r_start = int(rng_match.group(1))
                r_end_str = rng_match.group(2)
                r_end = int(r_end_str) if r_end_str else None
                # Check if range overlaps with indexRange
                if r_start <= idx_end and (r_end is None or r_end >= idx_start):
                    # Request overlaps with sidx region
                    inject_sidx = True
                    offset_in_sidx = r_start - idx_start
                    if offset_in_sidx < 0:
                        # Request starts before sidx - need to return init data too
                        # Fetch the init part from CDN, then append synthetic sidx
                        log(f"  {D}{kind}: range before sidx, fetching init from CDN{R}")
                        try:
                            cdn_range = f"bytes={r_start}-{idx_start-1}"
                            cdn_req = Request(url, headers={**HDR, "Range": cdn_range})
                            cdn_resp = urlopen(cdn_req, timeout=60)
                            init_part = cdn_resp.read()
                            sidx_portion = sidx_bytes[0:]  # full sidx
                            if r_end is not None:
                                extra_after = r_end - idx_end
                                if extra_after > 0:
                                    cdn_range2 = f"bytes={idx_end+1}-{r_end}"
                                    cdn_req2 = Request(url, headers={**HDR, "Range": cdn_range2})
                                    cdn_resp2 = urlopen(cdn_req2, timeout=60)
                                    extra_part = cdn_resp2.read()
                                    sidx_data = init_part + sidx_portion + extra_part
                                else:
                                    sidx_data = init_part + sidx_portion
                            else:
                                sidx_data = init_part + sidx_portion
                            total_size = self.cache._get_size(url)
                            cl = len(sidx_data)
                            self.send_response(206)
                            self.send_header("Content-Type", f"{'video' if kind=='video' else 'audio'}/mp4")
                            self.send_header("Content-Range", f"bytes {r_start}-{r_start+cl-1}/{total_size or ''}")
                            self.send_header("Content-Length", str(cl))
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.end_headers()
                            self.wfile.write(sidx_data)
                            self.wfile.flush()
                            log(f"  {D}{kind}: served init+sidx ({cl:,}b){R}")
                            return
                        except Exception as e:
                            err(f"CDN {kind} init part error: {e}")
                            self.send_error(502)
                            return
                    else:
                        # Request starts at/after sidx start
                        if r_end is not None and r_end <= idx_end:
                            # Within sidx range only
                            sidx_start_in_data = offset_in_sidx
                            sidx_end_in_data = offset_in_sidx + (r_end - r_start + 1)
                            sidx_data = sidx_bytes[offset_in_sidx:offset_in_sidx + (r_end - r_start + 1)]
                        elif r_end is not None and r_end > idx_end:
                            # Sidx + some media data
                            sidx_size = len(sidx_bytes) - offset_in_sidx
                            extra = r_end - idx_end
                            sidx_data = sidx_bytes[offset_in_sidx:]
                            # Fetch extra bytes from CDN
                            try:
                                cdn_range = f"bytes={idx_end+1}-{r_end}"
                                cdn_req = Request(url, headers={**HDR, "Range": cdn_range})
                                cdn_resp = urlopen(cdn_req, timeout=60)
                                extra_data = cdn_resp.read()
                                sidx_data = sidx_data + extra_data
                            except Exception as e:
                                err(f"CDN {kind} extra error: {e}")
                        else:
                            # r_end is None (open-ended) or different
                            sidx_data = sidx_bytes[offset_in_sidx:]
                            # Fetch remaining after sidx from CDN
                            try:
                                cdn_range = f"bytes={idx_end+1}-"
                                cdn_req = Request(url, headers={**HDR, "Range": cdn_range})
                                cdn_resp = urlopen(cdn_req, timeout=60)
                                extra_data = cdn_resp.read()
                                sidx_data = sidx_data + extra_data
                            except Exception as e:
                                err(f"CDN {kind} remaining error: {e}")

        if inject_sidx and sidx_data is not None:
            total_size = getattr(self.cache, f'_{kind[0]}_size', None) or self.cache._get_size(url) or 0
            cl = len(sidx_data)
            self.send_response(206)
            self.send_header("Content-Type", f"{'video' if kind=='video' else 'audio'}/mp4")
            self.send_header("Content-Range", f"bytes {r_start}-{r_start+cl-1}/{total_size}")
            self.send_header("Content-Length", str(cl))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(sidx_data)
            self.wfile.flush()
            return

        # Normal CDN proxy
        if rng: req_h["Range"] = rng
        log(f"  {D}{kind}: {stream.get('width','?')}x{stream.get('height','?')} {stream.get('codecs','?')}{R}")
        try:
            req = Request(url, headers=req_h)
            resp = urlopen(req, timeout=60)
        except HTTPError as e:
            backup = stream.get("backup_url","")
            if backup:
                try:
                    resp = urlopen(Request(backup, headers=req_h), timeout=60)
                except Exception as e2:
                    err(f"CDN backup failed: {e2}"); self.send_error(502); return
            else:
                err(f"CDN {kind} HTTP {e.code}"); self.send_error(e.code); return
        except Exception as e:
            err(f"CDN {kind} error: {e}"); self.send_error(502); return
        ct = resp.headers.get("Content-Type", f"{'video' if kind=='video' else 'audio'}/mp4")
        cl = resp.headers.get("Content-Length")
        cr = resp.headers.get("Content-Range")
        ar = resp.headers.get("Accept-Ranges","bytes")
        # Ensure Content-Length is always set (dash.js needs it for on-demand)
        if not cl:
            cached_size = getattr(self.cache, f'_{kind[0]}_size', None)
            if cached_size:
                cl = str(cached_size)
            elif cr:
                m = re.match(r'bytes\s+(\d+)-(\d+)/(\d+)', cr)
                if m: cl = str(int(m.group(2)) - int(m.group(1)) + 1)
        self.send_response(206 if cr else 200)
        self.send_header("Content-Type", ct)
        self.send_header("Accept-Ranges", ar)
        if cl: self.send_header("Content-Length", cl)
        if cr: self.send_header("Content-Range", cr)
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        total=0
        try:
            while True:
                chunk=resp.read(65536)
                if not chunk: break
                self.wfile.write(chunk)
                self.wfile.flush()
                total+=len(chunk)
        except (BrokenPipeError, ConnectionResetError): pass
        finally: resp.close()

    def _mpd(self):
        host=self.headers.get("Host","localhost:8080")
        try: vid,aud=self.cache.get()
        except Exception as e: self.send_error(502); return
        bw=vid.get('bandwidth',554682)+aud.get('bandwidth',91864)
        w=vid.get('width',1280); h=vid.get('height',720)
        vc=vid.get('codecs','avc1.640028'); ac=aud.get('codecs','mp4a.40.2')
        vsz = self.cache._v_size or self.cache._get_size(vid.get("base_url","")) or 50000000
        asz = self.cache._a_size or self.cache._get_size(aud.get("base_url","")) or 50000000

        # Use original indexRange values
        v_idx_s = vid.get('idx_start', 1006)
        v_idx_e = vid.get('idx_end', 9653)
        a_idx_s = aud.get('idx_start', 934)
        a_idx_e = aud.get('idx_end', 9593)
        v_init_s = vid.get('init_start', 0)
        v_init_e = vid.get('init_end', 1005)
        a_init_s = aud.get('init_start', 0)
        a_init_e = aud.get('init_end', 933)

        log(f"  {D}MPD: video={v_idx_s}-{v_idx_e} ({vsz:,}b), audio={a_idx_s}-{a_idx_e} ({asz:,}b){R}")
        mpd=f"""<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static"
     mediaPresentationDuration="PT59M54S" minBufferTime="PT1.5S"
     profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4" segmentAlignment="true" startWithSAP="1">
      <SegmentBase indexRange="{v_idx_s}-{v_idx_e}">
        <Initialization range="{v_init_s}-{v_init_e}"/>
      </SegmentBase>
      <Representation id="vid" bandwidth="{bw}" codecs="{vc}" width="{w}" height="{h}" frameRate="24000/1001">
        <BaseURL>http://{host}/video</BaseURL>
      </Representation>
    </AdaptationSet>
    <AdaptationSet mimeType="audio/mp4" segmentAlignment="true" startWithSAP="1">
      <SegmentBase indexRange="{a_idx_s}-{a_idx_e}">
        <Initialization range="{a_init_s}-{a_init_e}"/>
      </SegmentBase>
      <Representation id="aud" bandwidth="{aud.get('bandwidth',91864)}" codecs="{ac}" audioSamplingRate="44100">
        <BaseURL>http://{host}/audio</BaseURL>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""
        data=mpd.encode()
        self.send_response(200)
        self.send_header("Content-Type","application/dash+xml")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _player(self):
        host = self.headers.get("Host","localhost:8080")
        vs = self.cache._vs[0] if self.cache._vs else {}
        aud = self.cache._as[0] if self.cache._as else {}
        v_codec = vs.get('codecs','avc1.640028')
        a_codec = aud.get('codecs','mp4a.40.2')
        v_init_end = vs.get('init_end', 1005)
        a_init_end = aud.get('init_end', 933)
        v_media = vs.get('idx_end', 9653) + 1
        a_media = aud.get('idx_end', 9593) + 1
        v_size = self.cache._v_size or 0
        a_size = self.cache._a_size or 0

        html=f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>bilibili Player</title>
<style>
body{{margin:0;background:#000;display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column;font-family:sans-serif}}
video{{width:90vw;max-width:1280px;background:#000}}
#s{{color:#888;margin-top:8px;font-size:13px}}
#info{{color:#555;font-size:11px;margin-top:4px}}
</style>
</head><body>
<video id="v" controls></video>
<div id="s">Loading...</div>
<div id="info"><a href="/manifest.mpd" style=color:#6cf>MPD</a> | <a href="/debug" style=color:#6cf>Debug</a></div>
<script>
const C = {{
    vCodec:'{v_codec}', aCodec:'{a_codec}',
    vInitEnd:{v_init_end}, aInitEnd:{a_init_end},
    vMedia:{v_media}, aMedia:{a_media},
    vSize:{v_size}, aSize:{a_size},
    chunk:2*1024*1024
}};

function fr(url,s,e){{return fetch(url,{{headers:{{'Range':'bytes='+s+'-'+e}}}}).then(r=>r.arrayBuffer())}}
function pb(d){{var v=new DataView(d),p=0,r=[];while(p+8<=d.byteLength){{var s=v.getUint32(p);if(s<8)break;r.push({{s:s,t:String.fromCharCode(...new Uint8Array(d,p+4,4)),o:p}});p+=s}}return r}}
function cat(a,b){{var r=new Uint8Array(a.length+b.length);r.set(a);r.set(b,a.length);return r}}

async function main(){{
    var ms=new MediaSource(),v=document.getElementById('v'),st=document.getElementById('s');
    v.src=URL.createObjectURL(ms);
    ms.addEventListener('sourceopen',async()=>{{
        try{{
            st.textContent='Loading init...';
            var [vi,ai]=await Promise.all([fr('/video',0,C.vInitEnd),fr('/audio',0,C.aInitEnd)]);
            var vsb=ms.addSourceBuffer('video/mp4;codecs="'+C.vCodec+'"');
            var asb=ms.addSourceBuffer('audio/mp4;codecs="'+C.aCodec+'"');
            vsb.appendBuffer(vi);if(vsb.updating)await new Promise(r=>vsb.addEventListener('updateend',r,{{once:!0}}));
            asb.appendBuffer(ai);if(asb.updating)await new Promise(r=>asb.addEventListener('updateend',r,{{once:!0}}));
            st.textContent='Streaming...';
            await Promise.all([stream(vsb,'/video',C.vMedia),stream(asb,'/audio',C.aMedia)]);
            ms.endOfStream();st.textContent='Done';
        }}catch(e){{st.textContent='Error: '+e.message}}
    }});

    async function stream(sb,url,off){{
        var carry=null;
        while(!0){{
            if(C.vSize&&C.aSize&&url=='/video'&&off>C.vSize)break;
            if(C.aSize&&url=='/audio'&&off>C.aSize)break;
            var end=off+C.chunk-1;
            try{{var d=await fr(url,off,end)}}catch(e){{break}}
            if(!d.byteLength)break;
            var buf=carry?cat(carry,new Uint8Array(d)):d;carry=null;
            var boxes=pb(buf),lastMoof=-1,pos=0;
            for(var b of boxes){{
                if(b.t=='moof')lastMoof=b.o;
                else if(b.t=='mdat'&&lastMoof>=0){{
                    var seg=b.o+b.s,data=buf.slice(lastMoof,seg);
                    if(sb.updating)await new Promise(r=>sb.addEventListener('updateend',r,{{once:!0}}));
                    sb.appendBuffer(data);
                    await new Promise(r=>sb.addEventListener('updateend',r,{{once:!0}}));
                    lastMoof=-1;pos=seg;
                }}
            }}
            if(lastMoof>=0)carry=new Uint8Array(buf.slice(pos));
            off+=C.chunk;
        }}
    }}
}}
main();
</script>
</body></html>"""
        data=html.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _debug(self):
        host=self.headers.get("Host","localhost:8080")
        html=f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>DASH Debug</title>
<style>
body{{font:13px/1.4 monospace;background:#111;color:#0f0;padding:20px}}
#log{{white-space:pre-wrap;max-height:80vh;overflow-y:auto}}
.err{{color:#f00}} .ok{{color:#0f0}} .info{{color:#ff0}}
</style>
</head><body>
<h3>DASH Debug</h3>
<div id="log"></div>
<video id="vid" controls style="width:80%;margin-top:20px;"></video>
<script>
var L=document.getElementById('log');
function log(m,c){{var d=document.createElement('div');d.className=c||'';d.textContent='['+new Date().toLocaleTimeString()+'] '+m;L.appendChild(d);L.scrollTop=L.scrollHeight;}}
log('Checking dash.js...','info');
if(typeof dashjs==='undefined'){{log('dashjs NOT loaded!','err');}}
else{{log('dashjs version: '+dashjs.VERSION,'ok');}}
var url='http://{host}/manifest.mpd';
log('MPD URL: '+url,'info');
fetch(url).then(function(r){{return r.text();}}).then(function(t){{log('MPD loaded OK ('+t.length+' bytes)','ok');log(t.substring(0,200),'info');startPlayer();}}).catch(function(e){{log('MPD FETCH FAILED: '+e,'err');}});
function startPlayer(){{if(typeof dashjs==='undefined'){{log('dashjs not loaded','err');return;}}var p=dashjs.MediaPlayer().create();p.initialize(document.getElementById('vid'),url,true);p.on(dashjs.MediaPlayer.events.ERROR,function(e){{log('PLAYER ERROR: '+JSON.stringify(e.error),'err');}});p.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED,function(){{log('STREAM_INITIALIZED','ok');}});p.on(dashjs.MediaPlayer.events.MANIFEST_LOADED,function(e){{log('MANIFEST_LOADED','ok');}});p.on(dashjs.MediaPlayer.events.PLAYBACK_STARTED,function(){{log('PLAYBACK_STARTED','ok');}});p.on(dashjs.MediaPlayer.events.FRAGMENT_LOADING_COMPLETED,function(e){{if(e.request)log('FRAG: '+e.mediaType+' url='+e.request.url.substring(0,90));}});log('Player created, waiting for events...','info');}}
</script>
<script src="https://cdn.dashjs.org/latest/dash.all.min.js" onload="log('dash.js CDN loaded','ok')" onerror="log('dash.js CDN FAILED','err')"></script>
</body></html>"""
        data=html.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _status(self):
        import json
        try:
            vid,aud=self.cache.get()
            st={"ok":True,"title":self.cache._title,
                "video":{"res":f"{vid.get('width')}x{vid.get('height')}",
                         "codec":vid.get("codecs"),"bw":vid.get("bandwidth")},
                "audio":{"codec":aud.get("codecs"),"bw":aud.get("bandwidth")}}
        except Exception as e:
            st={"ok":False,"error":str(e)}
        data=json.dumps(st,indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(data)

    def _streams(self):
        import json
        try:
            out={"video":[{"idx":i,"w":v.get("width"),"h":v.get("height"),
                           "bw":v.get("bandwidth"),"c":v.get("codecs"),
                           "init":v.get("initialization"),"idx":v.get("index_range")}
                          for i,v in enumerate(self.cache._vs)],
                 "audio":[{"idx":i,"bw":a.get("bandwidth"),"c":a.get("codecs"),
                           "url":a.get("base_url","")[:80],
                           "init":a.get("initialization"),"idx":a.get("index_range")}
                          for i,a in enumerate(self.cache._as)]}
        except Exception as e:
            out={"error":str(e)}
        data=json.dumps(out,indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(data)

class TS(ThreadingMixIn, HTTPServer):
    daemon_threads=True

def main():
    pa=argparse.ArgumentParser()
    pa.add_argument("url")
    pa.add_argument("--port",type=int,default=8080)
    args=pa.parse_args()
    print()
    print(f"  {CYN}{B}+========================================+{R}")
    print(f"  {CYN}{B}|{R}  {B}bilibili.tv{R} {D}->{R} {B}DASH Proxy{R}            {CYN}{B}|{R}")
    print(f"  {CYN}{B}+========================================+{R}")
    print()
    cache=Cache(args.url)
    H.cache=cache
    log("Testing streams...")
    try: cache.get()
    except Exception as e: err(f"Failed: {e}"); sys.exit(1)
    server=TS(("127.0.0.1",args.port),H)
    ok(f"Listening on {GRN}http://127.0.0.1:{args.port}{R}")
    print(f"  Player: {GRN}http://127.0.0.1:{args.port}/player{R}")
    print(f"  Debug:  {GRN}http://127.0.0.1:{args.port}/debug{R}")
    print()
    try: server.serve_forever()
    except KeyboardInterrupt:
        print(); log("Done"); server.shutdown()

if __name__=="__main__": main()
