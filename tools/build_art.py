#!/usr/bin/env python3
"""Build card art for the game.

Put source images in art/source/ named by card id (e.g. gear-construction-barrel.png,
gear-construction-barrel.legendary.png) and add one row per image to art/credits.csv.
Run:  python3 tools/build_art.py
It checks each image, makes 512 px and 256 px WebP versions in art/cards/,
and writes art/manifest.json, which the game reads on load.
"""
import csv, json, pathlib, re, sys
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / 'art' / 'source', ROOT / 'art' / 'cards'
MIN_SIZE, SIZES = 1024, (512, 256)
ID_RE = re.compile(r'^(lore|gear|wild|might|muse|guardian|keeper)-[a-z0-9-]+(\.legendary)?$')

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    credits = {}
    with open(ROOT / 'art' / 'credits.csv', newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            credits[row['id'].strip()] = row
    manifest, problems = {}, []
    for path in sorted(SRC.iterdir()):
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            continue
        art_id = path.stem
        if not ID_RE.match(art_id):
            problems.append(f'{path.name}: name must be a card id like gear-pothole-monster'); continue
        c = credits.get(art_id)
        if not c or not c.get('artist', '').strip() or not c.get('alt', '').strip() or c.get('agreement_on_file', '').strip().lower() != 'yes':
            problems.append(f'{path.name}: needs a credits.csv row with artist, alt text and agreement_on_file = yes'); continue
        im = Image.open(path)
        w, h = im.size
        if w != h:
            problems.append(f'{path.name}: must be square (is {w}x{h})'); continue
        if w < MIN_SIZE:
            print(f'warning: {path.name} is {w}px; the spec asks for at least {MIN_SIZE}px')
        im = im.convert('RGBA')
        files = {}
        for s in SIZES:
            out = OUT / f'{art_id}-{s}.webp'
            im.resize((s, s), Image.LANCZOS).save(out, 'WEBP', quality=82, method=6)
            files[s] = f'art/cards/{out.name}'
        manifest[art_id] = {'large': files[512], 'small': files[256], 'artist': c['artist'].strip(), 'alt': c['alt'].strip()}
        print(f'ok: {art_id}')
    (ROOT / 'art' / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for p in problems: print('SKIPPED', p)
    print(f'{len(manifest)} image(s) in art/manifest.json')
    sys.exit(1 if problems else 0)

if __name__ == '__main__':
    main()
