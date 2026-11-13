#!/usr/bin/env python3
"""Campus Critters Art Studio: a point-and-click page for adding card art.

Run from the repo folder:
    python3 tools/art_studio.py              # only this computer can use it
    python3 tools/art_studio.py --lab        # anyone on the campus network can reach it
Then open the address it prints. Students pick a card, drop in a picture, crop it,
add their credit, and press Save. The studio writes art/source/<id>.png, updates
art/credits.csv and runs tools/build_art.py, so the game shows the art right away.
Everything stays on this computer; nothing is sent anywhere else.
Needs Python 3.9+ and Pillow (pip install pillow).
"""
import argparse, base64, csv, io, json, mimetypes, pathlib, re, subprocess, sys, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS, ART = ROOT / 'tools', ROOT / 'art'
CREDITS = ART / 'credits.csv'
FIELDS = ['id', 'artist', 'alt', 'agreement_on_file']
ID_RE = re.compile(r'^(lore|gear|wild|might|muse|guardian|keeper)-[a-z0-9-]+(\.legendary)?$')
MAX_UPLOAD = 30 * 1024 * 1024
LOCK = threading.Lock()


def slug(s):
    return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', s.lower()))


def catalog():
    """Read the card list straight from the game, so the studio never goes out of date."""
    src = (ROOT / 'index.html').read_text(encoding='utf-8')
    types_block = re.search(r'const TYPES = \{(.*?)\n\};', src, re.S).group(1)
    creatures_block = re.search(r'const CREATURES = \{(.*?)\n\};', src, re.S).group(1)
    places_block = re.search(r'const PLACES = \{(.*?)\n\};', src, re.S).group(1)
    factions = []
    for m in re.finditer(r"(\w+):\s*\{ color:'(#\w+)', icon:'([^']+)'.*?guard:\['([^']+)','([^']+)'\]", types_block):
        key, color, icon, g_emoji, g_name = m.groups()
        row = re.search(rf'^\s*{key}:\s*\[(.*)\],?\s*$', creatures_block, re.M).group(1)
        cards = [{'id': f'{key.lower()}-{slug(name)}', 'name': name, 'emoji': emoji, 'kind': 'card'}
                 for emoji, name in re.findall(r"\['([^']+)','([^']+)'\]", row)]
        prow = re.search(rf'^\s*{key}:\s*\[(.*)\],?\s*$', places_block, re.M).group(1)
        places = re.findall(r"'([^']+)'|\"([^\"]+)\"", prow)
        place = next((a or b for a, b in places), '')
        factions.append({
            'key': key, 'color': color, 'icon': icon, 'place': place, 'cards': cards,
            'bosses': [
                {'id': f'guardian-{key.lower()}', 'name': g_name, 'emoji': g_emoji, 'kind': 'guardian'},
                {'id': f'keeper-{key.lower()}', 'name': f'{key} Well Keeper', 'emoji': '💧', 'kind': 'keeper'},
            ]})
    return factions


def read_credits():
    if not CREDITS.exists():
        return {}
    with open(CREDITS, newline='', encoding='utf-8') as f:
        return {r['id'].strip(): r for r in csv.DictReader(f)}


def write_credits(rows):
    with open(CREDITS, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


def manifest():
    p = ART / 'manifest.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def save_art(data):
    from PIL import Image
    art_id = str(data.get('id', '')).strip()
    if data.get('legendary'):
        art_id += '.legendary'
    artist, alt = str(data.get('artist', '')).strip(), str(data.get('alt', '')).strip()
    if not ID_RE.match(art_id):
        return 400, {'error': 'That card id is not one the game knows.'}
    if not artist or not alt:
        return 400, {'error': 'Please add your name and a description of the picture.'}
    if not data.get('agreement'):
        return 400, {'error': 'Please confirm your art agreement is on file with the art lead.'}
    m = re.match(r'^data:image/png;base64,(.+)$', str(data.get('png', '')))
    if not m:
        return 400, {'error': 'The picture did not arrive. Try saving again.'}
    try:
        im = Image.open(io.BytesIO(base64.b64decode(m.group(1))))
        im.load()
    except Exception:
        return 400, {'error': 'That picture could not be read.'}
    if im.size[0] != im.size[1]:
        return 400, {'error': 'The picture must be square.'}
    with LOCK:
        (ART / 'source').mkdir(parents=True, exist_ok=True)
        for old in (ART / 'source').glob(art_id + '.*'):
            if old.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                old.unlink()
        im.convert('RGBA').save(ART / 'source' / f'{art_id}.png', optimize=True)
        rows = read_credits()
        rows[art_id] = {'id': art_id, 'artist': artist, 'alt': alt, 'agreement_on_file': 'yes'}
        write_credits(rows)
        run = subprocess.run([sys.executable, str(TOOLS / 'build_art.py')], cwd=ROOT, capture_output=True, text=True)
    log = (run.stdout + run.stderr).strip()
    ok = f'ok: {art_id}' in log
    return (200 if ok else 500), {'ok': ok, 'id': art_id, 'log': log, 'art': manifest().get(art_id)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8'):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            return self.send(200, (TOOLS / 'art_studio.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/api/catalog':
            return self.send(200, {'factions': catalog(), 'art': manifest(), 'credits': read_credits()})
        if path.startswith('/art/'):
            f = (ROOT / path.lstrip('/')).resolve()
            if ART.resolve() in f.parents and f.is_file():
                return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        if self.path != '/api/save':
            return self.send(404, {'error': 'not found'})
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0 or n > MAX_UPLOAD:
            return self.send(413, {'error': 'That picture is too large (limit 30 MB).'})
        try:
            data = json.loads(self.rfile.read(n))
        except Exception:
            return self.send(400, {'error': 'Bad request.'})
        self.send(*save_art(data))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8800)
    ap.add_argument('--lab', action='store_true', help='let other computers on the network use the studio')
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit('The studio needs Pillow. Install it with:  python3 -m pip install pillow')
    host = '0.0.0.0' if a.lab else '127.0.0.1'
    srv = ThreadingHTTPServer((host, a.port), Handler)
    url = f'http://localhost:{a.port}/'
    print(f'Art Studio is running at {url}' + ('  (and on this computer\'s network address)' if a.lab else ''))
    print('Leave this window open while you work. Press Ctrl+C to stop.')
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
