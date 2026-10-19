"""B.1 contracts and real FFmpeg comparisons; all fixtures are synthetic."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import numpy as np
from PIL import Image
from mapping360.profiles import (FORMATS, MODES, output_format, preview_size,
                                 projection_filter, max_fov)
from mapping360.preview import render_preview, framing_warning
from mapping360.project import Project, new_document, migrate_document, validate_document

ROOT = Path(__file__).resolve().parents[1]


def texture(width=1440, height=720):
    u, v = np.meshgrid((np.arange(width)+.5)/width, (np.arange(height)+.5)/height)
    return np.stack([127+100*np.sin(2*np.pi*u), 255*v,
                     127+100*np.cos(2*np.pi*u)], axis=-1).astype(np.uint8)


class ProfileTests(unittest.TestCase):
    def test_formats_and_preview_ratio(self):
        for name in FORMATS:
            out = output_format(name)
            w, h = preview_size(out)
            self.assertEqual(w*out['height'], h*out['width'])
            self.assertLessEqual(max(w, h), 720)
            self.assertEqual(out['width'] % 2, 0)
            self.assertEqual(out['height'] % 2, 0)
        for args in [('16:9', 1080, 1920), ('1:1', 101, 101), ('1:1', True, True)]:
            with self.assertRaises(ValueError):
                output_format(*args)

    def test_four_distinct_projections(self):
        c = new_document()['cameras'][0]
        c.update(yaw=0, pitch=0, h_fov=100)
        results = []
        for mode in MODES:
            c['projection']['mode'] = mode
            results.append(render_preview(texture(), c, 160, 90))
        for i in range(4):
            for j in range(i):
                self.assertGreater(np.abs(results[i].astype(float)-results[j]).mean(), .1)

    def test_v1_migration_keeps_reference_and_validation(self):
        old = json.loads((ROOT/'exemple_panorama_fourni/musiciens.json').read_text(encoding='utf-8'))
        cam = old['cameras'][0]
        cam.update(yaw=20, pitch=-10, validated=True)
        cam['reviews'] = [{'reference_id': old['references'][0]['id'], 'visibility': 'partiel',
                           'framing_signature': '[20,-10,65]'}]
        original = copy.deepcopy(old)
        new = validate_document(migrate_document(old))
        self.assertEqual(old, original)
        self.assertTrue(new['cameras'][0]['validated'])
        self.assertEqual(new['cameras'][0]['output']['width'], 1280)
        self.assertEqual(new['references'], old['references'])
        self.assertEqual(migrate_document(new), new)

    def test_ratio_change_preserves_subject_and_annotations(self):
        p = Project('.', new_document())
        c = p.doc['cameras'][0]
        p.change_camera(c, 0, 0, 70)
        c['annotations'] = [{'reference_id': 'r', 'point': {'u': .53, 'v': .5}, 'bbox': None}]
        original = copy.deepcopy(c['annotations'])
        for name in FORMATS:
            p.set_output(c, name)
            self.assertNotIn('hors du cadre', framing_warning(c, 'r'))
            self.assertEqual(c['annotations'], original)
            self.assertEqual((c['yaw'], c['pitch']), (0, 0))

    def test_history_restore_does_not_change_subject(self):
        p = Project('.', new_document())
        c = p.doc['cameras'][0]
        p.change_camera(c, 10, 5, 70, roll=15)
        p.remember_framing(c, 'premier')
        p.set_projection(c, 'Mega')
        p.set_output(c, '9:16')
        p.restore_framing(c)
        self.assertEqual((c['yaw'], c['roll'], c['h_fov']), (10, 15, 70))
        self.assertEqual(c['projection']['mode'], 'Linear')
        self.assertFalse(c['validated'])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg requis')
class ProjectionComparisonTests(unittest.TestCase):
    def test_numpy_against_ffmpeg_all_modes_ratios_and_roll(self):
        with tempfile.TemporaryDirectory(prefix='B1 projection é ') as tmp:
            root = Path(tmp)
            pano = texture()
            Image.fromarray(pano).save(root/'source.png')
            c = new_document()['cameras'][0]
            for mode in MODES:
                for name in FORMATS:
                    for yaw, pitch, roll in [(0, 0, 0), (179, 35, 23)]:
                        with self.subTest(mode=mode, ratio=name, roll=roll):
                            out = output_format(name)
                            w, h = preview_size(out, 188)
                            c.update(yaw=yaw, pitch=pitch, roll=roll, output=out,
                                     projection={'mode': mode}, h_fov=min(100, max_fov(mode, w/h)))
                            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(root/'source.png'),
                                            '-vf', projection_filter(c, w, h), '-frames:v', '1',
                                            '-threads', '1', str(root/'out.png')], check=True, capture_output=True)
                            with Image.open(root/'out.png') as im:
                                actual = np.array(im.convert('RGB'))
                            expected = render_preview(pano, c, w, h)
                            error = np.abs(expected.astype(float)-actual.astype(float))
                            self.assertLess(error.mean(), 2)
                            self.assertLess(np.percentile(error, 99), 5)


class PersistenceTests(unittest.TestCase):
    def test_migration_backup_and_all_settings_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix='B1 sauvegarde é ') as tmp:
            root = Path(tmp)
            original = (ROOT/'musiciens.json').read_bytes()
            (root/'musiciens.json').write_bytes(original)
            p = Project.load(root)
            self.assertEqual((root/'musiciens.json').read_bytes(), original)
            for i, c in enumerate(p.doc['cameras']):
                p.change_camera(c, i*20, -10, 70, roll=i*5)
                p.set_projection(c, list(MODES)[i % 4])
                p.set_output(c, list(FORMATS)[i])
                p.remember_framing(c)
            p.save()
            self.assertEqual(Project.load(root).doc, p.doc)
            self.assertEqual((root/'musiciens.v1.original.json').read_bytes(), original)
            p.save()
            self.assertEqual((root/'musiciens.v1.original.json').read_bytes(), original)
