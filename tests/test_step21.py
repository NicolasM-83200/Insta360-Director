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
from mapping360.render import attach_source, export_images, export_clips

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


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg requis')
class ExportTests(unittest.TestCase):
    def test_png_mp4_all_formats_modes_and_source_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='B1 exports é ') as tmp:
            root = Path(tmp)
            Image.fromarray(texture(640, 320)).save(root/'pano.png')
            source = root/'original.mkv'
            subprocess.run(['ffmpeg','-v','error','-loop','1','-i',str(root/'pano.png'),
                            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                            '-t','1','-r','10','-c:v','ffv1','-pix_fmt','bgr0',
                            '-c:a','pcm_s16le',str(source)],check=True,capture_output=True)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            p = Project.create(root)
            p.doc['source'] = attach_source(p.doc, source)
            ref = p.add_panorama(root/'pano.png', .2)
            c = p.doc['cameras'][0]
            p.change_camera(c, 20, 10, 90, roll=12)
            for name in FORMATS:
                w,h = preview_size(output_format(name), 188)
                # H.264 requires even dimensions, while preview pixels need not be even.
                w,h = w*2,h*2
                p.set_output(c,name,w,h)
                for mode in MODES:
                    with self.subTest(ratio=name,mode=mode):
                        p.set_projection(c, mode)
                        images = export_images(p, ref['id'], [c['id']])
                        with Image.open(images/'chanteur.png') as im:
                            actual = np.array(im.convert('RGB'))
                            self.assertEqual(im.size,(w,h))
                        expected = render_preview(texture(640,320),c,w,h)
                        self.assertLess(np.abs(actual.astype(float)-expected.astype(float)).mean(),2)
                        folder = export_clips(p.doc,p.root,.2,.4,camera_ids=[c['id']])
                        report = json.loads((folder/'render_report.json').read_text(encoding='utf-8'))
                        self.assertEqual(report['status'],'success')
                        clip = report['clips'][0]
                        self.assertIn(str(source),clip['command'])
                        self.assertNotIn(str(root/'pano.png'),clip['command'])
                        streams = clip['probe']['streams']
                        video = next(s for s in streams if s['codec_type']=='video')
                        audio = next(s for s in streams if s['codec_type']=='audio')
                        self.assertEqual((video['width'],video['height']),(w,h))
                        self.assertAlmostEqual(float(video['duration']),.4,delta=.1)
                        self.assertAlmostEqual(float(audio['start_time']),float(video['start_time']),delta=.05)
                        # Compare the actual encoded frame, not just dimensions.
                        raw = subprocess.run(['ffmpeg','-v','error','-i',str(folder/'chanteur.mp4'),
                                              '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],
                                             check=True,capture_output=True).stdout
                        encoded = np.frombuffer(raw,np.uint8).reshape(h,w,3)
                        self.assertLess(np.abs(encoded.astype(float)-expected.astype(float)).mean(),6)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)

    def test_image_only_and_video_without_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pano = root/'pano.png'
            Image.fromarray(texture(320,160)).save(pano)
            p = Project.create(root)
            ref = p.add_panorama(pano,0)
            c = p.doc['cameras'][0]
            p.change_camera(c,0,0,90)
            p.set_output(c,'1:1',128,128)
            folder = export_images(p,ref['id'],['chanteur'])
            report = json.loads((folder/'image_report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['quality'],'supplied_panorama')
            source = root/'silent.mkv'
            subprocess.run(['ffmpeg','-v','error','-loop','1','-i',str(pano),'-t','0.5',
                            '-r','10','-c:v','ffv1',str(source)],check=True,capture_output=True)
            p.doc['source'] = attach_source(p.doc,source)
            folder = export_clips(p.doc,p.root,0,.3,camera_ids=['chanteur'])
            report = json.loads((folder/'render_report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'],'success')
            self.assertFalse(any(s['codec_type']=='audio' for s in report['clips'][0]['probe']['streams']))
