"""Tests B : géométrie et pipeline réels ; aucune fausse observation de concert."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mapping360.geometry import uv_to_angles, angles_to_uv, normalized_box, box_framing, preview_rgb, uv_vectors, camera_matrix
from mapping360.project import Project, new_document, validate_document, review_complete
from mapping360.render import check_conventions, export_clips, attach_source, extract_reference, export_previews
import step1


class GeometryTests(unittest.TestCase):
    def test_cardinals(self):
        for uv, expected in [((.5,.5),(0,0)),((.75,.5),(90,0)),((.25,.5),(-90,0)),
                             ((.5,.25),(0,45)),((.5,.75),(0,-45)),((0,.5),(-180,0))]:
            self.assertEqual(uv_to_angles(*uv),expected)

    def test_roundtrips_and_poles(self):
        for u in [-.1,0,.001,.25,.75,.999,1.2]:
            for v in [0,.001,.3,.5,.999,1]:
                result=angles_to_uv(*uv_to_angles(u,v))
                self.assertAlmostEqual(result[0],u%1)
                self.assertAlmostEqual(result[1],v)

    def test_nan_and_invalid_latitude(self):
        for u,v in [(float('nan'),.5),(.5,1.1),(.5,float('inf'))]:
            with self.assertRaises(ValueError):uv_to_angles(u,v)

    def test_box_across_seam(self):
        b=normalized_box((.98,.3),(.02,.7))
        self.assertTrue(b['wraps_seam'])
        self.assertAlmostEqual(b['u_span'],.04)
        y,p,f,fit=box_framing(b)
        self.assertAlmostEqual(abs(y),180)
        self.assertAlmostEqual(p,0)
        self.assertTrue(fit)

    def test_box_reverse_drag_same_result(self):
        a,b=(.93,.2),(.08,.8)
        self.assertEqual(normalized_box(a,b),normalized_box(b,a))

    def test_fov_contains_box(self):
        b=normalized_box((.64,.4),(.72,.65))
        y,p,f,fit=box_framing(b)
        us,vs=np.meshgrid(np.linspace(.64,.72,21),np.linspace(.4,.65,21))
        local=uv_vectors(us,vs)@camera_matrix(y,p)
        t=local[...,:2]/local[...,2:3]
        self.assertTrue(fit)
        self.assertLess(np.max(abs(t[...,0])),np.tan(np.deg2rad(f/2)))
        self.assertLess(np.max(abs(t[...,1])),np.tan(np.deg2rad(f/2))*9/16)

    def test_too_wide_box_flagged(self):
        self.assertFalse(box_framing(normalized_box((.25,.1),(.75,.9)))[3])

    def test_seam_equivalence(self):
        rng=np.random.default_rng(6)
        pano=rng.integers(0,256,(180,360,3),dtype=np.uint8)
        a=preview_rgb(pano,-180,0,80,160,90)
        b=preview_rgb(pano,180,0,80,160,90)
        self.assertLessEqual(np.max(abs(a.astype(int)-b.astype(int))),1)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='cartographie é ')
        self.path=Path(self.tmp.name)
        self.img=self.path/'panorama.png'
        Image.new('RGB',(640,320),'navy').save(self.img)
        self.p=Project.create(self.path/'projets')
        self.ref=self.p.add_panorama(self.img,10)

    def tearDown(self):self.tmp.cleanup()

    def test_no_fictitious_assignments(self):
        self.assertTrue(all(c['yaw'] is None and c['ai_detection'] is None and not c['validated'] for c in self.p.doc['cameras']))

    def test_save_reload_coordinates_and_a_compatibility(self):
        for c in self.p.doc['cameras']:
            self.p.change_camera(c,45,-15,70)
            self.p.annotate(c,self.ref,.625,7/12)
            self.p.review(c,self.ref,'visible')
            self.p.validate_camera(c)
        self.p.save()
        loaded=Project.load(self.p.root)
        self.assertEqual(loaded.doc['cameras'][0]['center_uv'],{'u':.625,'v':7/12})
        self.assertTrue(loaded.doc['cameras'][0]['validated'])
        views=self.path/'views.json'
        views.write_text(json.dumps(loaded.stage_a_views()))
        self.assertEqual(len(step1.load_views(views)),5)
        folder=export_previews(loaded)
        self.assertEqual(len(list(folder.glob('*.png'))),5)

    def test_change_invalidates_reviews(self):
        c=self.p.doc['cameras'][0]
        self.p.change_camera(c,0,0,70)
        self.p.review(c,self.ref,'partiel')
        self.p.validate_camera(c)
        self.p.change_camera(c,5,0,70)
        self.assertFalse(c['validated'])
        self.assertFalse(review_complete(c,self.p.doc['references']))
        with self.assertRaises(ValueError):self.p.validate_camera(c)

    def test_new_reference_requires_review(self):
        c=self.p.doc['cameras'][0]
        self.p.change_camera(c,0,0,70)
        self.p.review(c,self.ref,'visible')
        self.p.validate_camera(c)
        self.p.add_panorama(self.img,20)
        self.assertFalse(c['validated'])
        with self.assertRaises(ValueError):self.p.validate_camera(c)

    def test_reject_fake_ai(self):
        self.p.doc['cameras'][0]['ai_detection']={'confidence':.99}
        with self.assertRaises(ValueError):self.p.save()

    def test_reference_tampering_detected(self):
        self.p.save()
        Image.new('RGB',(640,320),'red').save(self.p.reference_path(self.ref))
        with self.assertRaises(ValueError):Project.load(self.p.root)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg requis')
class FFmpegTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='vidéo source é ')
        self.path=Path(self.tmp.name)

    def tearDown(self):self.tmp.cleanup()

    def test_experimental_v360_signs_rotation_and_seam(self):
        result=check_conventions(self.path/'conventions')
        self.assertEqual(result['status'],'passed')
        self.assertEqual(len(result['cases']),8)

    def make_source(self):
        source=self.path/'source concert test.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x320:rate=10:duration=3',
                        '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-threads','1',
                        '-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
        return source

    def test_cache_five_clips_audio_and_source_untouched(self):
        source=self.make_source()
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        p=Project.create(self.path/'projects')
        p.doc['source']=attach_source(p.doc,source)
        reference=extract_reference(p.doc,p.root/'cache',.5)
        before=reference.stat().st_mtime_ns
        self.assertEqual(extract_reference(p.doc,p.root/'cache',.5),reference)
        self.assertEqual(reference.stat().st_mtime_ns,before)
        ref=p.add_panorama(reference,.5,'synthetic_test')
        for index,c in enumerate(p.doc['cameras']):
            p.change_camera(c,-144+index*72,0,90)
            p.review(c,ref,'visible')  # Mire synthétique, pas une observation de personne.
            p.validate_camera(c)
        folder=export_clips(p.doc,p.root,.5,1,width=320,height=180)
        report=json.loads((folder/'render_report.json').read_text())
        self.assertEqual(report['status'],'success')
        self.assertEqual(len(report['clips']),5)
        for clip in report['clips']:
            self.assertIn(str(source),clip['command'])
            self.assertNotIn(str(reference),clip['command'])
            self.assertTrue(any(s['codec_type']=='audio' for s in clip['probe']['streams']))
            self.assertAlmostEqual(clip['actual_video_duration_seconds'],1,delta=.11)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
        self.assertEqual(len(list(folder.glob('*.mp4'))),5)

    def test_reject_unvalidated_and_source_mismatch(self):
        p=Project.create(self.path/'projects')
        with self.assertRaises(ValueError):export_clips(p.doc,p.root,0,1)
        source=self.make_source()
        p.doc['source']=attach_source(p.doc,source)
        with source.open('ab') as f:f.write(b'changed')
        with self.assertRaises(ValueError):attach_source(p.doc,source)


if __name__=='__main__':unittest.main(verbosity=2)
