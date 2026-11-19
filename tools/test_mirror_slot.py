import functools
import http.server
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mirror_slot import plan, safe  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\nfake'


class Plan(unittest.TestCase):
    def test_this_sets_art_wins_and_only_gaps_are_filled(self):
        ours = {'AAAAAAAA': {'support-texture': 'GBA/support-texture/AAAAAAAA.png'}}
        theirs = {
            'AAAAAAAA': {
                'support-texture': 'GBA/support-texture/AAAAAAAA.png',
                'wheel': 'GBA/wheel/AAAAAAAA.png',
                'box-3D': 'GBA/box-3D/AAAAAAAA.png',
                'look': {'ground': '112233', 'sure': True},
            },
            'BBBBBBBB': {'box-3D': 'GB/box-3D/BBBBBBBB.png'},
        }
        merged, wanted = plan(ours, theirs)
        self.assertEqual(wanted, [('AAAAAAAA', 'wheel', 'GBA/wheel/AAAAAAAA.png')])
        self.assertEqual(
            merged,
            {
                'AAAAAAAA': {
                    'support-texture': 'GBA/support-texture/AAAAAAAA.png',
                    'wheel': 'GBA/wheel/AAAAAAAA.png',
                    'look': {'ground': '112233', 'sure': True},
                }
            },
        )
        self.assertEqual(ours, {'AAAAAAAA': {'support-texture': 'GBA/support-texture/AAAAAAAA.png'}})

    def test_a_named_entry_keeps_its_name_and_checksums(self):
        theirs = {
            'gba-video-x': {
                'name': 'Game Boy Advance Video - X',
                'platform': 'GBA',
                'crcs': ['1029FC8D'],
                'wheel': 'GBA/wheel/gba-video-x.png',
            }
        }
        merged, _ = plan({}, theirs)
        self.assertEqual(merged['gba-video-x']['crcs'], ['1029FC8D'])
        self.assertEqual(merged['gba-video-x']['name'], 'Game Boy Advance Video - X')

    def test_paths_leaving_the_set_are_refused(self):
        for bad in ['../x.png', 'GBA/../../x.png', '/etc/x.png', 'GBA/wheel/x.jpg', 'GBA/x.png', None, 3]:
            self.assertIsNone(safe(bad), bad)
        self.assertEqual(safe('GB/wheel/0A.png'), 'GB/wheel/0A.png')


class EndToEnd(unittest.TestCase):
    def test_files_are_fetched_and_what_slot_lacks_stays_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            slot, out = Path(tmp, 'slot'), Path(tmp, 'out')
            (slot / 'GB/wheel').mkdir(parents=True)
            from PIL import Image

            Image.new('RGBA', (4, 2), (10, 20, 30, 0)).save(slot / 'GB/wheel/11111111.webp', 'WEBP', lossless=True)
            (slot / 'GB/wheel/44444444.png').write_bytes(PNG)
            (slot / 'index.json').write_text(
                json.dumps(
                    {
                        '11111111': {'wheel': 'GB/wheel/11111111.png'},
                        '22222222': {'wheel': 'GB/wheel/22222222.png'},
                        '44444444': {'wheel': 'GB/wheel/44444444.png'},
                    }
                )
            )
            out.mkdir()
            (out / 'index.json').write_text(json.dumps({'33333333': {'wheel': 'GBA/wheel/33333333.png'}}))
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(slot))
            handler.log_message = lambda *a: None
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                base = f'http://127.0.0.1:{server.server_address[1]}/'
                subprocess.run(
                    [sys.executable, str(Path(__file__).parent / 'mirror_slot.py'), '--base', base, '--out', str(out)],
                    check=True,
                    capture_output=True,
                    env={'NO_PROXY': '*', 'no_proxy': '*'},
                )
            finally:
                server.shutdown()
            with Image.open(out / 'GB/wheel/11111111.png') as im:
                self.assertEqual((im.format, im.mode, im.size), ('PNG', 'RGBA', (4, 2)))
            self.assertEqual((out / 'GB/wheel/44444444.png').read_bytes(), PNG)
            self.assertEqual(
                json.loads((out / 'index.json').read_text()),
                {
                    '11111111': {'wheel': 'GB/wheel/11111111.png'},
                    '33333333': {'wheel': 'GBA/wheel/33333333.png'},
                    '44444444': {'wheel': 'GB/wheel/44444444.png'},
                },
            )

    def test_a_host_serving_nothing_fails_the_run_and_leaves_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            slot, out = Path(tmp, 'slot'), Path(tmp, 'out')
            slot.mkdir()
            (slot / 'index.json').write_text(json.dumps({'11111111': {'wheel': 'GB/wheel/11111111.png'}}))
            out.mkdir()
            (out / 'index.json').write_text('{}')
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(slot))
            handler.log_message = lambda *a: None
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                base = f'http://127.0.0.1:{server.server_address[1]}/'
                run = subprocess.run(
                    [sys.executable, str(Path(__file__).parent / 'mirror_slot.py'), '--base', base, '--out', str(out)],
                    capture_output=True,
                    env={'NO_PROXY': '*', 'no_proxy': '*'},
                )
            finally:
                server.shutdown()
            self.assertEqual(run.returncode, 1)
            self.assertEqual((out / 'index.json').read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
