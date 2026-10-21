#!/usr/bin/env python3
"""Fill the set from ScreenScraper: labels and logos for every dump the No-Intro databases list.

Adapted from slot-cart-studio's harvester (GPL-3.0) for slotPlus's systems. It runs on a schedule
in this repository's harvest workflow, and works locally the same way:

    SS_DEVID=... SS_DEVPASSWORD=... SS_SSID=... SS_SSPASSWORD=... tools/harvest.py
    SS_... tools/harvest.py --systems Lynx --limit 20      a short trial on one system
    SS_... tools/harvest.py --probe Lynx 006FD398          what ScreenScraper has for one dump

Each image is filed as add.py files one, `<platform>/<media>/<CRC32>.png`, and listed in
index.json. Art already in the set wins: a checksum the index already has a label or logo for is
never asked about again for that media, so a hand-added scan is never replaced. A later run skips
whatever it already has, so the set is built across as many days as the quota needs.

ScreenScraper's quota is per account, per minute and per day, and their documentation makes
managing it the client's job. This reads the account's limits before it starts, leaves a share of
the day for the account's other use, and stops when its share is gone.

ScreenScraper's media are CC BY-NC-SA 4.0. Every file this writes is listed in screenscraper.json,
so the set can say which art is theirs.
"""

import argparse
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

API = 'https://api.screenscraper.fr/api2'
DAT = 'https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/'
ROOT = Path(__file__).resolve().parent.parent

# Each system harvested: the card folder slotPlus files it under, libretro's database for it, and
# the names ScreenScraper may give it. ScreenScraper's id for each is found by those names in its
# own list at startup, rather than written here, so a renumbering cannot quietly file one
# console's art under another's. The WonderSwan and NeoGeo Pocket folders each hold two systems.
SYSTEMS = [
    ('WS', 'Bandai - WonderSwan', ['wonderswan']),
    ('WS', 'Bandai - WonderSwan Color', ['wonderswancolor']),
    ('Lynx', 'Atari - Lynx', ['lynx', 'atarilynx']),
    ('GG', 'Sega - Game Gear', ['gamegear']),
    ('NGP', 'SNK - Neo Geo Pocket', ['neogeopocket', 'ngp']),
    ('NGP', 'SNK - Neo Geo Pocket Color', ['neogeopocketcolor', 'ngpc']),
    ('TG16', 'NEC - PC Engine - TurboGrafx 16', ['pcengine', 'turbografx16', 'pcenginetg16']),
    # slot's own art set already covers these three; they are here for a run that asks for them.
    ('GBA', 'Nintendo - Game Boy Advance', ['gameboyadvance', 'gba']),
    ('GB', 'Nintendo - Game Boy', ['gameboy', 'gb']),
    ('GBC', 'Nintendo - Game Boy Color', ['gameboycolor', 'gbc']),
]
DEFAULT_FOLDERS = ('WS', 'Lynx', 'GG', 'NGP', 'TG16')

MEDIA = ('support-texture', 'wheel')
# A label is shown a couple of hundred pixels wide; this keeps detail for a 2x export without
# filling the repository with full-size scans.
MAX_SIDE = 600

REGIONS = ('us', 'wor', 'eu', 'jp')
COUNTRY = {
    'USA': 'us', 'World': 'wor', 'Europe': 'eu', 'Japan': 'jp', 'Germany': 'de', 'France': 'fr',
    'Spain': 'sp', 'Italy': 'it', 'UK': 'uk', 'Australia': 'au', 'Netherlands': 'nl',
    'Sweden': 'se', 'Korea': 'kr', 'Brazil': 'br', 'China': 'cn',
}
IN_EUROPE = {'de', 'fr', 'sp', 'it', 'uk', 'au', 'nl', 'se'}


def regions_for(name):
    """A dump's own region first, then the regions most dumps in circulation come from."""
    found = re.search(r'\(([^)]*)\)', name)
    own = COUNTRY.get(found.group(1).split(',')[0].strip()) if found else None
    first = [own] + (['eu'] if own in IN_EUROPE else []) if own else []
    return tuple(dict.fromkeys(first + list(REGIONS)))


def creds():
    missing = [k for k in ('SS_DEVID', 'SS_DEVPASSWORD') if not os.environ.get(k)]
    if missing:
        sys.exit(f'set {" and ".join(missing)} in the environment')
    c = {
        'devid': os.environ['SS_DEVID'],
        'devpassword': os.environ['SS_DEVPASSWORD'],
        'softname': os.environ.get('SS_SOFTNAME', 'CartStudioPlus'),
        'output': 'json',
    }
    # A user account carries the quota; without one the day's allowance builds very little.
    if os.environ.get('SS_SSID'):
        c['ssid'] = os.environ['SS_SSID']
        c['sspassword'] = os.environ.get('SS_SSPASSWORD', '')
    return c


class QuotaSpent(Exception):
    pass


def call(endpoint, params, tries=4):
    """One API call, backing off rather than hammering a service that limits by design.

    Errors are reported by status alone: the url carries the credentials, so it is never printed.
    """
    for attempt in range(tries):
        url = f'{API}/{endpoint}?' + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            # 404 means the dump is not known, which is an answer rather than a failure. 429 is
            # the documented rate limit and 430/431 the quota codes.
            if e.code == 404:
                return None
            if e.code in (430, 431):
                raise QuotaSpent(f'ScreenScraper says the quota is spent (HTTP {e.code})') from None
            if attempt < tries - 1 and e.code in (429, 500, 502, 503, 504):
                wait = 20 * (attempt + 1)
                print(f'    HTTP {e.code}, waiting {wait}s', flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f'{endpoint}: HTTP {e.code}') from None
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            if attempt == tries - 1:
                raise RuntimeError(f'{endpoint}: {type(e).__name__}') from None
            time.sleep(5 * (attempt + 1))
    return None


def quota(c):
    data = call('ssuserInfos.php', c) or {}
    u = data.get('response', {}).get('ssuser', {}) or {}

    def num(*keys):
        for k in keys:
            try:
                return int(str(u.get(k)).strip())
            except ValueError:
                pass
        return None

    return {
        'per_min': num('maxrequestspermin'),
        'per_day': num('maxrequestsperday'),
        'today': num('requeststoday') or 0,
        'threads': num('maxthreads') or 1,
    }


def plain(name):
    return re.sub(r'[^a-z0-9]', '', str(name).lower())


def system_names(entry):
    noms = entry.get('noms') or {}
    names = [v for k, v in noms.items() if k != 'noms_commun' and isinstance(v, str)]
    names += str(noms.get('noms_commun') or '').split(',')
    return {plain(n) for n in names if plain(n)}


def resolve_ids(listed, systems):
    """ScreenScraper's id for each system, by name. The first name that picks out exactly one
    system decides; a system none of its names picks out stops the run rather than guessing."""
    named = []
    for s in listed:
        try:
            named.append((int(s['id']), system_names(s)))
        except (KeyError, TypeError, ValueError):
            continue
    ids = {}
    for folder, dat, candidates in systems:
        for want in candidates:
            hits = sorted({sid for sid, names in named if want in names})
            if len(hits) == 1:
                ids[dat] = hits[0]
                break
        else:
            sys.exit(f'ScreenScraper has no single system named any of {candidates} for {dat}')
    if len(set(ids.values())) != len(ids):
        sys.exit(f'two systems took the same ScreenScraper id: {ids}')
    return ids


def dat_entries(dat):
    """CRC32 to No-Intro name: which dumps exist, and what this run calls them while it works."""
    url = DAT + urllib.parse.quote(dat) + '.dat'
    with urllib.request.urlopen(url, timeout=120) as r:
        return parse_dat(r.read().decode('utf-8', 'replace'))


def parse_dat(text):
    """CRC32 to (game name, rom file name, rom size) for each single-rom game in a dat."""
    out = {}
    for block in re.finditer(r'game\s*\((.*?)\n\)', text, re.S):
        body = block.group(1)
        name = re.search(r'name\s+"([^"]+)"', body)
        rom = re.search(r'rom\s*\(\s*name\s+"([^"]+)"\s+size\s+(\d+)\s+crc\s+([0-9A-Fa-f]{8})', body)
        if name and rom:
            out[rom.group(3).upper()] = (name.group(1), rom.group(1), int(rom.group(2)))
    return out


def pick(medias, want, regions=REGIONS):
    """The wanted media in the most useful region, or None."""
    same = [m for m in medias if m.get('type') == want]
    for region in regions:
        for m in same:
            if (m.get('region') or '').lower() == region:
                return m
    return same[0] if same else None


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        body = r.read()
    # A truncated or error body is not an image, and a broken file in the set is worse than none.
    return body if len(body) >= 256 else None


def as_png(body, media):
    """The image as a PNG no larger than MAX_SIDE, or None when it is not an image.

    A logo keeps its transparency; a label is saved opaque, as add.py saves one."""
    from PIL import Image, UnidentifiedImageError
    try:
        im = Image.open(io.BytesIO(body))
        im.load()
    except (UnidentifiedImageError, OSError):
        return None
    im = im.convert('RGBA') if media == 'wheel' or 'transparency' in im.info or im.mode in ('RGBA', 'LA') else im.convert('RGB')
    if media == 'support-texture' and im.mode == 'RGBA' and im.getextrema()[3][0] == 255:
        im = im.convert('RGB')
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, 'PNG', optimize=True)
    return out.getvalue()


# A dump ScreenScraper had nothing (more) for is asked about again after this many days, when its
# art may have been added, rather than on every run.
RETRY_DAYS = 30


def todo_for(crc, wanted, index, folder_root, asked=None, today=None):
    """The media this dump still needs: none the index has, none already on disk, and nothing
    when ScreenScraper was asked about it within RETRY_DAYS."""
    if asked and today and crc in asked:
        if (date.fromisoformat(today) - date.fromisoformat(asked[crc])).days < RETRY_DAYS:
            return []
    have = index.get(crc, {})
    return [w for w in wanted if w not in have and not (folder_root / w / f'{crc}.png').exists()]


def write_index(path, index):
    """The format add.py writes, so a harvest and a hand addition diff cleanly together."""
    path.write_text(json.dumps(dict(sorted(index.items())), indent=1, ensure_ascii=False) + '\n')


def write_sources(path, files):
    path.write_text(json.dumps(sorted(files), indent=1) + '\n')


def probe(c, ids, folder, crc):
    for f, dat, _ in SYSTEMS:
        if f != folder:
            continue
        entry = dat_entries(dat).get(crc.upper())
        if not entry:
            continue
        name, romname, size = entry
        data = call('jeuInfos.php', dict(c, crc=crc.upper(), systemeid=ids[dat], romnom=romname, romtaille=size))
        jeu = (data or {}).get('response', {}).get('jeu')
        print(f'{name} ({dat}, system {ids[dat]}): {"found" if jeu else "no match"}')
        for m in (jeu or {}).get('medias', []):
            print(f'   {str(m.get("type")):<22} {str(m.get("region") or "-"):<5} {m.get("format") or "-"}')
        return
    print(f'{crc} is not a dump the {folder} databases list')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--systems', default=','.join(DEFAULT_FOLDERS),
                    help='card folders to harvest, comma separated (default: %(default)s)')
    ap.add_argument('--media', default=','.join(MEDIA), help='ScreenScraper media types (default: %(default)s)')
    ap.add_argument('--out', default=str(ROOT), help='the set (default: this repository)')
    ap.add_argument('--limit', type=int, help='stop after this many api calls, for a trial run')
    ap.add_argument('--spare', type=float, default=0.25,
                    help="share of the day's quota to leave for the account's other use (default: %(default)s)")
    ap.add_argument('--probe', nargs=2, metavar=('FOLDER', 'CRC'), help='list the media one dump has, and stop')
    args = ap.parse_args()

    folders = [f.strip() for f in args.systems.split(',') if f.strip()]
    unknown = set(folders) - {f for f, _, _ in SYSTEMS}
    if unknown:
        sys.exit(f'no such card folder: {", ".join(sorted(unknown))}')
    systems = [s for s in SYSTEMS if s[0] in (folders if not args.probe else [args.probe[0]])]

    c = creds()
    listed = ((call('systemesListe.php', c) or {}).get('response', {}) or {}).get('systemes', [])
    if not listed:
        sys.exit('ScreenScraper would not list its systems: check the credentials')
    ids = resolve_ids(listed, systems)
    for folder, dat, _ in systems:
        print(f'{dat}: ScreenScraper system {ids[dat]}')

    if args.probe:
        probe(c, ids, *args.probe)
        return

    q = quota(c)
    print(f"quota: {q['today']} used today of {q['per_day'] or '?'}, "
          f"{q['per_min'] or '?'} a minute, {q['threads']} thread(s)")
    budget = None
    if q['per_day'] is not None:
        budget = max(0, int(q['per_day'] * (1 - args.spare)) - q['today'])
    if args.limit is not None:
        budget = args.limit if budget is None else min(budget, args.limit)
    if budget == 0:
        print("nothing left of today's share of the quota; the next run resumes")
        return
    threads = max(1, min(q['threads'] or 1, 4))
    # Their limit is per minute, so pace to it rather than racing into a 429. Pacing is per
    # thread, so the total stays inside the limit however many are running.
    pause = threads * (60.0 / q['per_min'] if q['per_min'] else 1.0)

    out = Path(args.out)
    wanted = [m.strip() for m in args.media.split(',') if m.strip()]
    index_path, sources_path = out / 'index.json', out / 'screenscraper.json'
    asked_path = out / 'tools' / 'harvest-asked.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    sources = set(json.loads(sources_path.read_text())) if sources_path.exists() else set()
    # The day each dump was last asked about and still lacked something: not published.
    asked = json.loads(asked_path.read_text()) if asked_path.exists() else {}
    today = date.today().isoformat()

    lock = threading.Lock()
    stop = threading.Event()
    n = {'asked': 0, 'saved': 0, 'missed': 0, 'skipped': 0}

    def work(folder, system, crc, entry):
        if stop.is_set():
            return
        name, romname, size = entry
        root = out / folder
        with lock:
            todo = todo_for(crc, wanted, index, root, asked, today)
            if not todo:
                n['skipped'] += 1
                return
            if budget is not None and n['asked'] >= budget:
                stop.set()
                return
            n['asked'] += 1
        try:
            data = call('jeuInfos.php', dict(c, crc=crc, systemeid=system, romnom=romname, romtaille=size))
        except QuotaSpent as e:
            print(f'stopped: {e}')
            stop.set()
            return
        except Exception as e:  # one bad game must not take the run down with it
            with lock:
                n['missed'] += 1
            print(f'  {name}: {e}')
            return
        medias = ((data or {}).get('response', {}).get('jeu') or {}).get('medias', [])
        regions = regions_for(name)
        got = []
        for want in todo:
            m = pick(medias, want, regions)
            try:
                body = as_png(fetch(m['url']), want) if m else None
            except Exception:
                body = None
            if body:
                dest = root / want / f'{crc}.png'
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                got.append((want, dest.relative_to(out).as_posix()))
        with lock:
            if len(got) < len(todo):
                asked[crc] = today
            else:
                asked.pop(crc, None)
            if got:
                n['saved'] += len(got)
                for want, rel in got:
                    index.setdefault(crc, {})[want] = rel
                    sources.add(rel)
                print(f'  {name}: {", ".join(w for w, _ in got)}', flush=True)
            else:
                n['missed'] += 1
        time.sleep(pause)

    try:
        for folder, dat, _ in systems:
            if stop.is_set():
                break
            entries = dat_entries(dat)
            print(f'{dat}: {len(entries)} dumps', flush=True)
            with ThreadPoolExecutor(max_workers=threads) as pool:
                for crc, entry in sorted(entries.items()):
                    if stop.is_set():
                        break
                    pool.submit(work, folder, ids[dat], crc, entry)
    except KeyboardInterrupt:
        stop.set()
        print('\nstopped by hand')
    finally:
        # Written whatever happened, so an interrupted run leaves a usable index behind.
        write_index(index_path, index)
        write_sources(sources_path, sources)
        asked_path.write_text(json.dumps(dict(sorted(asked.items())), indent=0) + '\n')
        print(f"\n{n['saved']} files, {n['missed']} dumps without art, {n['skipped']} already done, "
              f"{n['asked']} api calls")


if __name__ == '__main__':
    main()
