"""The harvester's own logic, offline. Run from the repository: python3 -m unittest discover tools"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harvest  # noqa: E402
from PIL import Image  # noqa: E402


def png(size, mode='RGB', alpha=255):
    out = io.BytesIO()
    colour = (10, 20, 30) if mode == 'RGB' else (10, 20, 30, alpha)
    Image.new(mode, size, colour).save(out, 'PNG')
    return out.getvalue()


LISTED = [
    {'id': '45', 'noms': {'nom_eu': 'WonderSwan', 'nom_recalbox': 'wswan', 'noms_commun': 'WonderSwan,WS'}},
    {'id': '46', 'noms': {'nom_eu': 'WonderSwan Color', 'nom_retropie': 'wonderswancolor'}},
    {'id': '28', 'noms': {'nom_eu': 'Lynx', 'nom_retropie': 'atarilynx'}},
    {'id': '21', 'noms': {'nom_eu': 'Game Gear', 'nom_retropie': 'gamegear'}},
    {'id': '25', 'noms': {'nom_eu': 'Neo-Geo Pocket', 'nom_retropie': 'ngp'}},
    {'id': '82', 'noms': {'nom_eu': 'Neo-Geo Pocket Color', 'nom_retropie': 'ngpc'}},
    {'id': '31', 'noms': {'nom_eu': 'PC Engine', 'nom_us': 'TurboGrafx-16', 'nom_retropie': 'pcengine'}},
    {'id': '114', 'noms': {'nom_eu': 'PC Engine CD-Rom', 'nom_us': 'TurboGrafx-CD'}},
]


class ResolveIds(unittest.TestCase):
    def test_each_system_is_found_by_its_names(self):
        ids = harvest.resolve_ids(LISTED, [s for s in harvest.SYSTEMS if s[0] in harvest.DEFAULT_FOLDERS])
        self.assertEqual(ids, {
            'Bandai - WonderSwan': 45, 'Bandai - WonderSwan Color': 46, 'Atari - Lynx': 28,
            'Sega - Game Gear': 21, 'SNK - Neo Geo Pocket': 25, 'SNK - Neo Geo Pocket Color': 82,
            'NEC - PC Engine - TurboGrafx 16': 31,
        })

    def test_a_system_with_no_matching_name_stops_the_run(self):
        with self.assertRaises(SystemExit):
            harvest.resolve_ids(LISTED[:1], [('Lynx', 'Atari - Lynx', ['lynx'])])

    def test_a_name_two_systems_share_falls_through_to_the_next(self):
        listed = [{'id': '1', 'noms': {'nom_eu': 'Lynx'}}, {'id': '2', 'noms': {'nom_eu': 'Lynx', 'nom_retropie': 'atarilynx'}}]
        self.assertEqual(harvest.resolve_ids(listed, [('Lynx', 'Atari - Lynx', ['lynx', 'atarilynx'])]), {'Atari - Lynx': 2})


class ParseDat(unittest.TestCase):
    def test_a_dat_gives_each_dump_its_name_file_and_size(self):
        text = '''clrmamepro (
\tname "Atari - Lynx"
)

game (
\tname "Klax (World)"
\tdescription "Klax (World)"
\trom ( name "Klax (World).lnx" size 131136 crc 006fd398 md5 00 sha1 00 )
)
'''
        self.assertEqual(harvest.parse_dat(text), {'006FD398': ('Klax (World)', 'Klax (World).lnx', 131136)})


class TodoFor(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_art_already_in_the_set_is_never_asked_for(self):
        index = {'AAAA0000': {'support-texture': 'Lynx/support-texture/BBBB1111.png'}}
        self.assertEqual(harvest.todo_for('AAAA0000', ['support-texture', 'wheel'], index, self.root), ['wheel'])

    def test_a_file_on_disk_counts_as_had(self):
        (self.root / 'wheel').mkdir()
        (self.root / 'wheel' / 'AAAA0000.png').write_bytes(b'x')
        self.assertEqual(harvest.todo_for('AAAA0000', ['support-texture', 'wheel'], {}, self.root), ['support-texture'])

    def test_a_dump_asked_about_lately_waits(self):
        asked = {'AAAA0000': '2026-10-01'}
        wanted = ['wheel']
        self.assertEqual(harvest.todo_for('AAAA0000', wanted, {}, self.root, asked, '2026-10-21'), [])
        self.assertEqual(harvest.todo_for('AAAA0000', wanted, {}, self.root, asked, '2026-11-01'), ['wheel'])


class AsPng(unittest.TestCase):
    def test_a_big_scan_is_shrunk_and_kept_opaque(self):
        im = Image.open(io.BytesIO(harvest.as_png(png((1800, 900)), 'support-texture')))
        self.assertEqual((im.size, im.mode), ((600, 300), 'RGB'))

    def test_a_logo_keeps_its_transparency(self):
        im = Image.open(io.BytesIO(harvest.as_png(png((300, 100), 'RGBA', 0), 'wheel')))
        self.assertEqual((im.size, im.mode), ((300, 100), 'RGBA'))

    def test_an_opaque_label_with_an_alpha_channel_is_saved_opaque(self):
        im = Image.open(io.BytesIO(harvest.as_png(png((100, 50), 'RGBA', 255), 'support-texture')))
        self.assertEqual(im.mode, 'RGB')

    def test_a_body_that_is_not_an_image_is_dropped(self):
        self.assertIsNone(harvest.as_png(b'<html>quota</html>' * 20, 'wheel'))


class WriteIndex(unittest.TestCase):
    def test_the_index_is_written_as_add_py_writes_it(self):
        path = Path(tempfile.mkdtemp()) / 'index.json'
        harvest.write_index(path, {'BBBB1111': {'wheel': 'GG/wheel/BBBB1111.png'}, 'AAAA0000': {}})
        self.assertEqual(path.read_text(), json.dumps({'AAAA0000': {}, 'BBBB1111': {'wheel': 'GG/wheel/BBBB1111.png'}}, indent=1) + '\n')


class RegionsFor(unittest.TestCase):
    def test_a_dump_prefers_its_own_region(self):
        self.assertEqual(harvest.regions_for('Klax (World)'), ('wor', 'us', 'eu', 'jp'))
        self.assertEqual(harvest.regions_for('GunPey (Japan)'), ('jp', 'us', 'wor', 'eu'))
        self.assertEqual(harvest.regions_for('Sonic (Germany)'), ('de', 'eu', 'us', 'wor', 'jp'))


if __name__ == '__main__':
    unittest.main()
