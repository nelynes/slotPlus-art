#!/usr/bin/env python3
"""Add a label or a logo to the set.

    tools/add.py GBA "Oriental Blue - Ao no Tengai (Japan).png"
    tools/add.py Lynx "Klax (World).png" --game "Klax (World)"
    tools/add.py GG logo.png --crc 0AB12CD3

The file is named after the game, as slotPlus names a label on the card: the rom's name without
its extension. That name is looked up in libretro's No-Intro database for the system, and the
image is filed under the checksum of every dump the database lists for that game, so Cart Studio+
finds it for anyone who has the game, whatever their file is called. `--game` gives the database
name when the file's own name is not it, and `--crc` skips the database altogether.

An image with any transparency is a logo, `wheel`, which the studio sets on a ground taken from the
box art. A fully opaque one is a whole label, `support-texture`, used as it is. `--logo` and
`--label` say which when that guess is wrong.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / 'index.json'
DAT = 'https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/'

# The card folders slotPlus files roms under, and the No-Intro databases each one is matched in.
# The WonderSwan and NeoGeo Pocket folders each hold two systems, so both are searched.
DATABASES = {
    'GBA': ['Nintendo - Game Boy Advance'],
    'GB': ['Nintendo - Game Boy'],
    'GBC': ['Nintendo - Game Boy Color'],
    'WS': ['Bandai - WonderSwan', 'Bandai - WonderSwan Color'],
    'Lynx': ['Atari - Lynx'],
    'GG': ['Sega - Game Gear'],
    'NGP': ['SNK - Neo Geo Pocket', 'SNK - Neo Geo Pocket Color'],
    'TG16': ['NEC - PC Engine - TurboGrafx 16'],
}


def games(db):
    """Each game in a database, by name, with the checksums of its dumps."""
    url = DAT + urllib.parse.quote(db) + '.dat'
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode('utf-8', 'replace')
    out = {}
    for block in re.finditer(r'game \(\n(.*?)\n\)', text, re.S):
        body = block.group(1)
        name = re.search(r'^\s*name "([^"]*)"', body, re.M)
        crcs = re.findall(r'\bcrc ([0-9A-Fa-f]{8})\b', body)
        if name and crcs:
            out[name.group(1)] = [c.upper() for c in crcs]
    return out


def crcs_for(platform, name):
    found = {}
    for db in DATABASES[platform]:
        for game, crcs in games(db).items():
            found.setdefault(game, crcs)
    if name in found:
        return found[name]
    # The title before any (region) or [tag], compared without case, finds the dumps a near miss meant.
    title = lambda n: re.split(r'\s*[(\[]', n, maxsplit=1)[0].strip().lower()
    want = title(name)
    near = [g for g in found if want and (title(g).startswith(want) or want.startswith(title(g)))]
    hint = ''.join(f'\n  {g}' for g in sorted(near)[:10])
    sys.exit(f'"{name}" is not a game in the {platform} database.'
             + (f' Close names:{hint}' if near else '') + '\nGive the right one with --game, or --crc.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('platform', choices=sorted(DATABASES))
    ap.add_argument('image')
    ap.add_argument('--game', help="the game's name in the No-Intro database, when the file's is not it")
    ap.add_argument('--crc', action='append', help='file it under this checksum instead (repeatable)')
    kind = ap.add_mutually_exclusive_group()
    kind.add_argument('--logo', action='store_true', help='a logo, whatever its transparency')
    kind.add_argument('--label', action='store_true', help='a whole label, whatever its transparency')
    a = ap.parse_args()

    src = Path(a.image)
    im = Image.open(src)
    see_through = im.mode in ('RGBA', 'LA', 'P') and im.convert('RGBA').getextrema()[3][0] < 255
    media = 'wheel' if a.logo or (see_through and not a.label) else 'support-texture'

    crcs = [c.upper() for c in a.crc] if a.crc else crcs_for(a.platform, a.game or src.stem)

    index = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    folder = ROOT / a.platform / media
    folder.mkdir(parents=True, exist_ok=True)
    first = folder / f'{crcs[0]}.png'
    # A logo keeps its transparency. A label is opaque, and saved as RGB, which is all a card needs.
    (im.convert('RGBA') if media == 'wheel' else im.convert('RGB')).save(first, optimize=True)
    for crc in crcs:
        # Every dump points at the one file, so a game with several dumps costs one image.
        index.setdefault(crc, {})[media] = first.relative_to(ROOT).as_posix()
    INDEX.write_text(json.dumps(dict(sorted(index.items())), indent=1, ensure_ascii=False) + '\n')
    kind_name = 'logo' if media == 'wheel' else 'label'
    print(f'{a.platform} {kind_name}: {first.relative_to(ROOT)} for {", ".join(crcs)}')


if __name__ == '__main__':
    main()
