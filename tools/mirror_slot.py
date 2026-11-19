#!/usr/bin/env python3
"""Copy slot's art set into this one.

slot's set at art.slot-cfw.fyi holds the Game Boy family's labels and logos, but it sends no
access-control-allow-origin header, so Cart Studio+ on nelynes.github.io can't read it. A copy here
can be. slot's author is fine with it being copied.

Art already in this set wins: a label, logo or look this set has for a key is kept, and only what it
lacks is filled from slot's. Files are kept at slot's own paths. slot's host serves each image as
a .webp beside the .png path its index names, the way slot fetches it, so the .webp is fetched first
and saved as the .png this set keeps. Box art (`box-3D`) is left out,
since nothing that reads this set uses it. slot's named entries, a hack or a GBA Video pak with a
`crcs` list of every dump, are copied with their names and lists.

    tools/mirror_slot.py [--base URL] [--out DIR] [--limit N]
"""

import argparse
import concurrent.futures
import io
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SLOT_BASE = 'https://art.slot-cfw.fyi/'
MEDIA = ('support-texture', 'wheel')
# What a named entry carries besides its files, copied when this set doesn't have it.
DETAILS = ('look', 'name', 'platform', 'crcs', 'aka')
AGENT = 'slotPlus-art mirror (+https://github.com/nelynes/slotPlus-art)'


def fetch(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt)


def as_png(body):
    """A fetched image as PNG bytes, or None when it isn't an image: a missing file comes back as
    an HTML page."""
    if not body:
        return None
    if body.startswith(b'\x89PNG'):
        return body
    if not (body[:4] == b'RIFF' and body[8:12] == b'WEBP'):
        return None
    from PIL import Image

    try:
        with Image.open(io.BytesIO(body)) as im:
            im = im.convert('RGBA' if im.mode in ('RGBA', 'LA', 'P') or 'transparency' in im.info else 'RGB')
            out = io.BytesIO()
            im.save(out, 'PNG', optimize=True)
            return out.getvalue()
    except OSError:
        return None


def safe(path):
    """A path from slot's index, if it stays inside a platform folder of the set."""
    if not isinstance(path, str) or not path.endswith('.png'):
        return None
    parts = path.split('/')
    if len(parts) != 3 or any(p in ('', '.', '..') or p.startswith('.') for p in parts):
        return None
    return path


def plan(ours, theirs):
    """The merged index, and the files it names that this set must fetch from slot's.

    Neither argument is changed."""
    merged = {k: dict(v) for k, v in ours.items()}
    wanted = []
    for key, entry in theirs.items():
        if not isinstance(entry, dict):
            continue
        target = merged.get(key, {})
        added = False
        for media in MEDIA:
            path = safe(entry.get(media))
            if path and media not in target:
                target[media] = path
                wanted.append((key, media, path))
                added = True
        for detail in DETAILS:
            if detail in entry and detail not in target and (added or key in merged):
                target[detail] = entry[detail]
        if target:
            merged[key] = target
    return merged, wanted


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--base', default=SLOT_BASE)
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument('--limit', type=int, help='fetch at most this many files')
    args = ap.parse_args()

    index_path = args.out / 'index.json'
    ours = json.loads(index_path.read_text())
    theirs = json.loads(fetch(args.base + 'index.json'))
    merged, wanted = plan(ours, theirs)
    missing = sorted({p for _, _, p in wanted if not (args.out / p).exists()})
    if args.limit is not None:
        missing = missing[: args.limit]
    print(f'slot has {len(theirs)} entries; filling {len(wanted)} files, {len(missing)} to fetch')

    def one(path):
        body = as_png(fetch(args.base + path[: -len('.png')] + '.webp')) or as_png(fetch(args.base + path))
        if body is None:
            return path, False
        dest = args.out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix('.part')
        tmp.write_bytes(body)
        tmp.replace(dest)
        return path, True

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        failed = 0
        for n, (path, ok) in enumerate(pool.map(one, missing), 1):
            failed += not ok
            if n % 1000 == 0:
                print(f'  {n}/{len(missing)}')

    # Anything that couldn't be fetched, or wasn't fetched under --limit, stays out of the index.
    kept = 0
    for key, media, path in wanted:
        if (args.out / path).exists():
            kept += 1
        else:
            merged[key].pop(media, None)
    for key in {k for k, _, _ in wanted}:
        if key not in ours and not any(m in merged[key] for m in MEDIA):
            del merged[key]

    # Nothing at all fetched means slot's host has moved its files again, not that it lacks them all.
    if missing and failed == len(missing):
        print(f'::error::none of the {len(missing)} files could be fetched from {args.base}')
        return 1
    print(f'::notice::{len(missing) - failed} of {len(missing)} files fetched from slot\'s set')
    index_path.write_text(json.dumps(dict(sorted(merged.items())), indent=1, ensure_ascii=False) + '\n')
    print(f'{kept} of {len(wanted)} files now in the set')
    return 0


if __name__ == '__main__':
    sys.exit(main())
