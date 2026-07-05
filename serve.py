"""Start the proxy server."""
import sys, os, time, threading, http.client
os.chdir(r'C:\projects')
sys.path.insert(0, r'C:\projects')
import bilibili_proxy as bp

url = 'https://www.bilibili.tv/en/video/2047206875'
cache = bp.Cache(url)
bp.H.cache = cache

cache.get()

server = bp.TS(('127.0.0.1', 8080), bp.H)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
time.sleep(0.5)

# Quick self-test
ok = True
for path, hdrs in [
    ('/manifest.mpd', None),
    ('/video', {'Range': 'bytes=0-1005'}),
    ('/video', {'Range': 'bytes=1006-9509'}),
    ('/video', {'Range': 'bytes=9510-9599'}),
    ('/audio', {'Range': 'bytes=0-933'}),
    ('/player', None),
]:
    conn = http.client.HTTPConnection('127.0.0.1', 8080, timeout=15)
    conn.request('GET', path, headers=hdrs or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    hdrs_dict = dict(resp.getheaders())
    box_raw = data[4:8] if len(data) > 8 else b''
    box = box_raw.decode('ascii','replace') if len(data) > 8 else str(len(data))
    passed = len(data) > 0
    if not passed: ok = False
    cl = hdrs_dict.get('Content-Length','?')
    msg = '  %s %s (%db, CL=%s) [%s]' % ('OK' if passed else 'FAIL', path, len(data), cl, box)
    sys.stdout.buffer.write(msg.encode('ascii','replace')+b'\n')
    sys.stdout.flush()

if ok:
    print('\nProxy ready! http://127.0.0.1:8080/player')
    print('  Player: localhost:8080/player')
    print('  VLC:    vlc http://127.0.0.1:8080/manifest.mpd')
    print('  Debug:  localhost:8080/debug')
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print('\nShutdown')
        server.shutdown()
else:
    print('\nSome tests failed!')
    server.shutdown()
