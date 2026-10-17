"""Tests locaux réels FFmpeg; aucune API, aucune donnée de concert."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import step1


class ConfigurationTests(unittest.TestCase):
    def test_five_views_and_rectilinear_fov(self):
        views = step1.load_views(ROOT / 'views.json')
        self.assertEqual(len(views), 5)
        self.assertTrue(all(v['subject'] is None for v in views))
        self.assertIn('v_fov=58.71550709', step1.projection(views[2], 640, 360))

    def test_sampling_excludes_end(self):
        self.assertEqual(step1.sample_times(0, 60, 30, 10), [0, 30])
        with self.assertRaises(ValueError):
            step1.sample_times(0, 60, 1, 10)

    def test_reject_nan(self):
        with self.assertRaises(ValueError):
            step1.number(float('nan'), 'yaw', -180, 180)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg requis')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='360 test accents é ')
        cls.base = Path(cls.tmp.name)
        cls.source = cls.base / 'source é concert.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=640x320:rate=10:duration=2', '-c:v', 'ffv1',
                        str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def invoke(self, *args):
        output = self.base / self._testMethodName
        p = subprocess.run([sys.executable, str(ROOT / 'step1.py'), '--output', str(output), *args],
                           capture_output=True, encoding='utf-8', errors='replace')
        run = next(output.glob('run_*'))
        return p, run, json.loads((run / 'report.json').read_text(encoding='utf-8'))

    def test_full_pipeline_source_preserved(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        p, run, report = self.invoke('--source', str(self.source), '--confirm-equirectangular',
                                     '--interval', '1', '--panorama-width', '640',
                                     '--width', '320', '--height', '180', '--full-decode-check')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(report['sample_count'], 2)
        self.assertEqual(report['validation'], 'full_video_decode')
        self.assertEqual(len(list(run.glob('ref_*/*.png'))), 12)
        for path in run.glob('ref_*/*.png'):
            wh = struct.unpack('>II', path.read_bytes()[16:24])
            self.assertEqual(wh, (640, 320) if path.name == 'panorama.png' else (320, 180))
        self.assertTrue((run / 'gallery.html').is_file())
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_projection_confirmation_required(self):
        p, _, report = self.invoke('--source', str(self.source))
        self.assertEqual(p.returncode, 1)
        self.assertIn('Confirmer', report['error'])

    def test_reject_out_of_range(self):
        p, _, report = self.invoke('--source', str(self.source), '--confirm-equirectangular', '--start', '9')
        self.assertEqual(p.returncode, 1)
        self.assertIn('--start', report['error'])

    def test_reject_non_video(self):
        source = self.base / 'invalide.mp4'
        source.write_text('ceci ne constitue pas une vidéo', encoding='utf-8')
        p, _, report = self.invoke('--source', str(source), '--confirm-equirectangular')
        self.assertEqual(p.returncode, 1)
        self.assertEqual(report['status'], 'failed')

    def test_reject_wrong_ratio(self):
        source = self.base / 'normal.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=size=320x180:duration=0.2', '-c:v', 'ffv1', str(source)], check=True)
        p, _, report = self.invoke('--source', str(source), '--confirm-equirectangular')
        self.assertEqual(p.returncode, 1)
        self.assertIn('ratio 2:1', report['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
